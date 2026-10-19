/** Plugin lifecycle, backend startup and vault synchronization. */
import { modelFor } from './settings/modelPicker';
import { backendIsOlder } from './backend/version';
import { SessionController } from './quiz/session';
import { spawn } from 'node:child_process';
import { join } from 'node:path';
import { FileSystemAdapter, MarkdownView, Notice, Plugin, TAbstractFile, TFile, TFolder } from 'obsidian';
import { QuizClient, errorMessage } from './backend/api';
import { QuizView, VIEW_TYPE } from './views/QuizView';
import { QuizSettingsTab, defaults } from './settings/settings';
import { livePreviewExtension, registerReadingWidgets, refreshWidgets } from './views/inlineCodeQuiz';
import { findBlocks } from './views/blocks';
import type { CodeBlock, Health, Settings } from './types';
import { ViewPlugin } from '@codemirror/view';
import type { EditorView } from '@codemirror/view';

export default class QuizPlugin extends Plugin {
  private sessions = new Map<string, SessionController>();
  session(key: string) {
    let controller = this.sessions.get(key);
    if (!controller) { controller = new SessionController(this, key); this.sessions.set(key, controller); }
    return controller;
  }
  settings: Settings = {...defaults};
  selectedTags: string[] = [];
  apiToken = '';
  generationApiKey = '';

  async resetServer() {
    if (this.settings.connectionMode === 'server') {
      await this.api.call('/admin/reset', {target: 'server'});
    } else {
      await this.api.call('/admin/restart', {});
      await new Promise(resolve => window.setTimeout(resolve, 1200));
      await this.startBackend();
    }
    this.api.resetConnection();
    this.settings.initialized = false;
  }
  api = new QuizClient(() => this.settings, () => this.apiToken, () => this.vaultPath());
  currentNote: string | undefined;
  active = false;
  widgetRevision = 0;
  inlineDisposers = new Set<() => void>();
  private editorViews = new Set<EditorView>();
  private blockCache = new Map<string, {mtime: number; blocks: CodeBlock[]}>();
  private timers = new Map<string, number>();
  private pendingSync = new Map<string, {source_file: string; old_path?: string}>();
  private syncRunning = false;
  private initializePromise: Promise<void> | null = null;
  private ready = false;

  async onload() {
    this.settings = {...defaults, ...await this.loadData() as Partial<Settings>};
    if (!this.settings.vaultKey) this.settings.vaultKey = crypto.randomUUID();
    this.settings.quizModels = {...this.settings.quizModels};
    this.settings.collapsed = {...this.settings.collapsed};
    this.settings.sessionIds = {...this.settings.sessionIds};
    this.settings.tagHistory = {...this.settings.tagHistory};
    const uniqueTags = (tags: string[]) => [...new Map(tags.filter(t => t.toLowerCase() !== 'quiz').map(t => [t.toLowerCase(), t])).values()];
    this.selectedTags = this.settings.rememberTags ? uniqueTags(this.settings.tags) : [];
    const included = new Set(this.selectedTags.map(t => t.toLowerCase()));
    this.settings.excludeTags = uniqueTags(this.settings.excludeTags).filter(t => !included.has(t.toLowerCase()));
    this.settings.initialized = false;
    await this.saveSettings();
    this.active = true;
    this.registerView(VIEW_TYPE, leaf => new QuizView(leaf, this));
    this.addRibbonIcon('brain', 'Open Quiz pane', () => void this.openQuiz());
    this.addCommand({id: 'open-quiz-pane', name: 'Open Quiz pane', callback: () => void this.openQuiz()});
    this.addCommand({id: 'start-quiz', name: 'Start quiz', callback: () => void this.openAndStart()});
    this.addCommand({id: 'quiz-current-note', name: 'Quiz current note', callback: () => void this.openAndStart(true)});
    this.addCommand({id: 'practice-next-due-term', name: 'Practice next due term', callback: () => void this.openAndStart(false, true)});
    this.addCommand({id: 'rescan-quiz-data', name: 'Rescan quiz data', callback: () => {
      new Notice('Syncing quiz data...');
      void this.fullSync().then(() => new Notice('Quiz data synced.')).catch(error => new Notice(errorMessage(error)));
    }});
    this.addSettingTab(new QuizSettingsTab(this.app, this));
    registerReadingWidgets(this);
    this.registerEditorExtension(livePreviewExtension(this));
    const owner = this;
    this.registerEditorExtension(ViewPlugin.fromClass(class {
      constructor(private view: EditorView) { owner.editorViews.add(view); }
      destroy() { owner.editorViews.delete(this.view); }
    }));
    this.registerEvent(this.app.workspace.on('file-open', file => {
      if (file?.extension === 'md' && file.path !== this.currentNote) {
        this.currentNote = file.path;
        for (const leaf of this.app.workspace.getLeavesOfType(VIEW_TYPE)) (leaf.view as QuizView).noteChanged();
      }
    }));
    this.registerEvent(this.app.vault.on('modify', file => this.changed(file)));
    this.registerEvent(this.app.vault.on('create', file => this.changed(file)));
    this.registerEvent(this.app.vault.on('delete', file => this.changed(file)));
    this.registerEvent(this.app.vault.on('rename', (file, oldPath) => {
      if (file instanceof TFile) this.queueSync(file.path, oldPath);
      else if (file instanceof TFolder) {
        const visit = (folder: TFolder) => {
          for (const child of folder.children) {
            if (child instanceof TFolder) visit(child);
            else if (child instanceof TFile) this.queueSync(child.path, oldPath + child.path.slice(file.path.length));
          }
        };
        visit(file);
      }
      this.blockCache.clear();
    }));
    this.app.workspace.onLayoutReady(() => {
      if (!this.active) return;
      this.ready = true;
      const file = this.app.workspace.getActiveFile();
      if (file?.extension === 'md') this.currentNote = file.path;
      // No eager scan/model request. First pane use performs initial sync.
    });
  }

  vaultPath(): string {
    const adapter = this.app.vault.adapter;
    if (!(adapter instanceof FileSystemAdapter)) throw new Error('This plugin needs a local desktop Obsidian vault.');
    return adapter.getBasePath();
  }

  connectionChanged() {
    this.api.resetConnection(); this.settings.initialized = false;
    this.settings.sessionIds = {};
    for (const controller of this.sessions.values()) { controller.state = null; controller.error = ''; }
  }

  private starting: Promise<void> | null = null;
  async startBackend(): Promise<void> {
    if (this.starting) return this.starting;
    this.starting = this.launchBackend().finally(() => { this.starting = null; });
    return this.starting;
  }

  private async launchBackend() {
    this.api.resetConnection();
    if (this.settings.connectionMode === 'server') {
      await this.api.health(); return; // Server lifecycle belongs to its administrator.
    }
    const folder = join(this.vaultPath(), this.manifest.dir ?? `${this.app.vault.configDir}/plugins/${this.manifest.id}`, 'backend');
    let running: Health | undefined;
    try { running = await this.api.call<Health>('/health'); } catch { /* Offline backend. */ }
    if (running && !backendIsOlder(running.version, this.manifest.version)) { await this.api.health(); return; }
    if (running?.service === 'markdown-quiz-generator' && running.capabilities?.includes('local-restart')) {
      await this.api.call('/admin/restart', {});
      await new Promise(resolve => window.setTimeout(resolve, 1000));
    } else if (running) {
      await this.restartLegacy(folder);
      await new Promise(resolve => window.setTimeout(resolve, 1000));
    }
    const url = new URL(this.settings.backendUrl);
    if (!['127.0.0.1', 'localhost'].includes(url.hostname) || url.protocol !== 'http:') throw new Error('Use a local HTTP backend URL.');
    const child = spawn(this.settings.pythonPath, [join(folder, 'backend.py'), '--vault', this.vaultPath(),
      '--data', join(folder, 'data'), '--port', url.port || '80'],
      {cwd: folder, windowsHide: true, detached: true, stdio: ['ignore', 'pipe', 'pipe'],
        env: {...process.env, QUIZ_API_TOKEN: this.apiToken, OLLAMA_MODEL: modelFor(this.settings, 'multiple-choice')}});
    let failure = '';
    let diagnostics = '';
    const capture = (chunk: Buffer) => { diagnostics = (diagnostics + chunk.toString()).slice(-4000); };
    child.stdout?.on('data', capture); child.stderr?.on('data', capture);
    child.on('error', error => { failure = error.message; });
    child.on('exit', code => { if (code) failure = `Python backend exited (${code}). ${diagnostics.split(/\r?\n/).filter(Boolean).slice(-1).join()}`; });
    child.unref();
    for (let attempt = 0; attempt < 20; attempt++) {
      await new Promise(resolve => window.setTimeout(resolve, 500));
      if (failure) throw new Error(failure);
      try { await this.api.health(); this.settings.initialized = false; return; } catch { /* Bounded startup retry. */ }
    }
    throw new Error('Backend did not start. Check the Python executable setting and update the complete plugin folder.');
  }

  private restartLegacy(folder: string): Promise<void> {
    if (process.platform !== 'win32') throw new Error('Stop the legacy backend once, then retry. New versions support automatic restart.');
    // Only stop Python running this plugin's exact bundled backend script.
    // Paths and ports are environment data, never interpolated shell source.
    const script = String.raw`
$ErrorActionPreference = 'Stop'
$owners = @(Get-NetTCPConnection -LocalPort ([int]$env:QUIZ_RESTART_PORT) -State Listen | Select-Object -ExpandProperty OwningProcess -Unique)
if ($owners.Count -ne 1) { throw 'Cannot identify one backend process.' }
$proc = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $owners[0])
$expected = [regex]::Escape($env:QUIZ_RESTART_SCRIPT)
if ($proc.Name -notmatch '^python(w|[0-9.]*)?\.exe$' -or $proc.CommandLine -notmatch ('(?i)(?:^|["\s])' + $expected + '(?:["\s]|$)')) { throw 'The running service is not this plugin bundled backend. Stop it manually once.' }
Stop-Process -Id $owners[0] -ErrorAction Stop
`;
    return new Promise((resolve, reject) => {
      const child = spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], {
        windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
        env: {...process.env, QUIZ_RESTART_PORT: new URL(this.settings.backendUrl).port || '80', QUIZ_RESTART_SCRIPT: join(folder, 'backend.py')}});
      let message = ''; child.stderr?.on('data', chunk => { message = (message + chunk.toString()).slice(-2000); });
      const timer = window.setTimeout(() => { child.kill(); reject(new Error('Legacy backend restart timed out.')); }, 15000);
      child.on('error', error => { window.clearTimeout(timer); reject(error); });
      child.on('exit', code => { window.clearTimeout(timer); if (code === 0) resolve(); else reject(new Error(message || 'Cannot safely restart the legacy backend.')); });
    });
  }

  async openSource(path: string, line: number) {
    const file = this.app.vault.getAbstractFileByPath(path);
    if (!(file instanceof TFile)) { new Notice('Source note no longer exists in this vault.'); return; }
    const leaf = this.app.workspace.getLeaf('tab');
    await leaf.openFile(file, {eState: {line: Math.max(0, line - 1)}});
    if (leaf.view instanceof MarkdownView) leaf.view.editor.setCursor({line: Math.max(0, line - 1), ch: 0});
  }

  rememberTag(tag: string) {
    const old = this.settings.tagHistory[tag];
    this.settings.tagHistory[tag] = {count: (old?.count ?? 0) + 1, last: Date.now()};
    void this.saveSettings();
  }

  async saveSettings() {
    this.settings.tags = this.settings.rememberTags ? [...this.selectedTags] : [];
    await this.saveData(this.settings);
  }

  async openQuiz(): Promise<QuizView> {
    let leaf = this.app.workspace.getLeavesOfType(VIEW_TYPE)[0];
    if (!leaf) {
      leaf = this.app.workspace.getRightLeaf(false) ?? this.app.workspace.getLeaf(true);
      await leaf.setViewState({type: VIEW_TYPE, active: true});
    }
    await this.app.workspace.revealLeaf(leaf);
    return leaf.view as QuizView;
  }

  private async openAndStart(current = false, due = false) {
    const view = await this.openQuiz();
    view.currentOnly = current;
    view.dueOnly = due || this.settings.dueOnly;
    await view.start();
  }

  async ensureInitialized() {
    if (this.settings.initialized) { await this.flushSync(); return; }
    if (!this.initializePromise) this.initializePromise = this.fullSync().finally(() => { this.initializePromise = null; });
    await this.initializePromise;
  }

  async fullSync() {
    await this.flushSync();
    if (this.settings.connectionMode === 'server') {
      const files = this.app.vault.getMarkdownFiles();
      for (const file of files) await this.api.call('/sync/file', {source_file: file.path, content: await this.app.vault.read(file)});
      await this.api.call('/sync/manifest', {files: files.map(file => file.path)});
    } else await this.api.call('/sync', {});
    this.settings.initialized = true;
    await this.saveSettings();
  }

  private changed(file: TAbstractFile) {
    this.blockCache.delete(file.path);
    if (file instanceof TFile) this.queueSync(file.path);
  }

  private queueSync(path: string, oldPath?: string) {
    if (!this.active || !this.ready || !this.settings.autoSync || !path.toLowerCase().endsWith('.md')) return;
    // Chain rapid A -> B -> C renames to preserve the original backend identity.
    const previous = oldPath ? this.pendingSync.get(oldPath) : this.pendingSync.get(path);
    if (oldPath) {
      this.pendingSync.delete(oldPath);
      const timer = this.timers.get(oldPath); if (timer) window.clearTimeout(timer);
      this.timers.delete(oldPath);
    }
    this.pendingSync.set(path, {source_file: path, old_path: previous?.old_path ?? oldPath});
    const timer = this.timers.get(path); if (timer) window.clearTimeout(timer);
    this.timers.set(path, window.setTimeout(() => {
      this.timers.delete(path); void this.flushSync();
    }, this.settings.debounceMs));
  }

  private async flushSync() {
    if (this.syncRunning || !this.active) return;
    this.syncRunning = true;
    let failed = false;
    try {
      for (const [path, event] of this.pendingSync) {
        if (!this.active) return;
        if (this.timers.has(path)) continue;
        try {
          const file = this.app.vault.getAbstractFileByPath(event.source_file);
          const payload = this.settings.connectionMode === 'server'
            ? {...event, content: file instanceof TFile ? await this.app.vault.read(file) : null} : event;
          await this.api.call('/sync/file', payload);
          if (this.pendingSync.get(path) === event) this.pendingSync.delete(path);
          for (const leaf of this.app.workspace.getLeavesOfType(VIEW_TYPE)) void (leaf.view as QuizView).refreshTags();
        } catch (error) {
          failed = true;
          console.warn('Markdown Quiz sync:', errorMessage(error));
          // Retain events for the next edit/retry, without a polling loop.
          break;
        }
      }
    } finally {
      this.syncRunning = false;
      if (!failed && this.active && [...this.pendingSync.keys()].some(path => !this.timers.has(path))) {
        queueMicrotask(() => void this.flushSync());
      }
    }
  }

  async blocksFor(file: TFile): Promise<CodeBlock[]> {
    const cached = this.blockCache.get(file.path);
    if (cached?.mtime === file.stat.mtime) return cached.blocks;
    const blocks = findBlocks(await this.app.vault.cachedRead(file));
    if (this.blockCache.size >= 100) this.blockCache.delete(this.blockCache.keys().next().value!);
    this.blockCache.set(file.path, {mtime: file.stat.mtime, blocks});
    return blocks;
  }

  refreshInline() {
    this.widgetRevision++;
    for (const dispose of [...this.inlineDisposers]) dispose();
    for (const view of this.editorViews) view.dispatch({effects: refreshWidgets.of(null)});
  }

  onunload() {
    this.active = false;
    for (const controller of this.sessions.values()) controller.dispose();
    this.sessions.clear();
    this.apiToken = '';
    this.generationApiKey = '';
    for (const timer of this.timers.values()) window.clearTimeout(timer);
    this.timers.clear(); this.pendingSync.clear(); this.blockCache.clear();
    for (const dispose of [...this.inlineDisposers]) dispose();
    this.app.workspace.detachLeavesOfType(VIEW_TYPE);
    this.editorViews.clear();
  }
}
