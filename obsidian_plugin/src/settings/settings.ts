import { renderResetControls } from './serviceSettings';
import { renderLibrarySettings } from './librarySettings';
import { renderModelPicker } from './modelPicker';
import { App, PluginSettingTab, Setting } from 'obsidian';
import type QuizPlugin from '../main';
import type { Direction, Difficulty, QuizLength, Settings } from '../types';

export const defaults: Settings = {
  generationProvider: 'ollama', apiUrl: 'https://api.openai.com/v1', apiModel: '', disabledLibraries: [],
  connectionMode: 'local', vaultKey: '', quizType: 'multiple-choice', collapsed: {}, sessionIds: {}, dateFrom: '', dateTo: '', currentOnly: false,
  pythonImports: '', quizModels: {}, pythonPath: 'python', ollamaModel: 'qwen2.5-coder:7b', excludeTags: [], tagHistory: {},
  backendUrl: 'http://127.0.0.1:8765', length: 10, direction: 'random', difficulty: 'medium',
  dueOnly: false, rememberTags: true, tags: [], inline: true, reading: true, livePreview: true,
  autoSync: true, debounceMs: 1500, timeoutSeconds: 600, initialized: false
};

export class QuizSettingsTab extends PluginSettingTab {
  constructor(app: App, private plugin: QuizPlugin) { super(app, plugin); }
  display(): void {
    const el = this.containerEl;
    el.empty();
    el.createEl('h2', {text: 'Markdown Quiz Generator'});
    el.createEl('p', {text: 'The plugin automatically connects the backend to this Obsidian vault. Generation uses Ollama or API; code runs in Docker.'});
    new Setting(el).setName('Connection mode').setDesc('Server mode uploads Markdown copies from this vault to your configured server. Local mode reads this vault directly.')
      .addDropdown(dropdown => dropdown.addOptions({local: 'Local computer', server: 'Server'}).setValue(this.plugin.settings.connectionMode)
        .onChange(async value => { this.plugin.settings.connectionMode = value as 'local' | 'server'; this.plugin.connectionChanged(); await this.plugin.saveSettings(); }));
    renderModelPicker(el, this.plugin, undefined, 'multiple-choice');
    renderModelPicker(el, this.plugin, undefined, 'coding');
    el.createEl('small', {text: 'Coding currently uses the built-in Python generator. Its model preference is saved separately.'});
    new Setting(el).setName('Python executable').setDesc('Python command or full executable path used by Start backend.')
      .addText(text => text.setValue(this.plugin.settings.pythonPath).onChange(async value => {
        this.plugin.settings.pythonPath = value.trim() || 'python'; await this.plugin.saveSettings();
      }));
    new Setting(el).setName('Backend URL').setDesc('Local: http://127.0.0.1:8765. Server: your HTTPS address (or a localhost SSH tunnel).')
      .addText(text => {
        text.setValue(this.plugin.settings.backendUrl);
        text.inputEl.addEventListener('change', () => {
          this.plugin.settings.backendUrl = text.getValue().trim();
          this.plugin.connectionChanged();
          void this.plugin.saveSettings();
        });
      });
    new Setting(el).setName('Default quiz length').addDropdown(dropdown => dropdown
      .addOptions({'5': '5', '10': '10', '20': '20', all: 'All matching', until: 'Until I stop'})
      .setValue(String(this.plugin.settings.length)).onChange(async value => {
        this.plugin.settings.length = (value === 'all' || value === 'until' ? value : Number(value)) as QuizLength;
        await this.plugin.saveSettings();
      }));
    new Setting(el).setName('Backend token (session only)').setDesc('Required for server mode; enter again after restarting Obsidian. Kept in memory and never saved to plugin settings.')
      .addText(text => {
        text.inputEl.type = 'password';
        text.setValue(this.plugin.apiToken).onChange(value => { this.plugin.apiToken = value; this.plugin.api.resetConnection(); });
      });
    new Setting(el).setName('Default direction').addDropdown(dropdown => dropdown
      .addOptions({random: 'Random', forward: 'Term → Definition', reverse: 'Definition → Term'})
      .setValue(this.plugin.settings.direction).onChange(async value => {
        this.plugin.settings.direction = value as Direction; await this.plugin.saveSettings();
      }));
    new Setting(el).setName('Default code difficulty').addDropdown(dropdown => dropdown
      .addOptions({easy: 'Easy', medium: 'Medium', hard: 'Hard'}).setValue(this.plugin.settings.difficulty)
      .onChange(async value => { this.plugin.settings.difficulty = value as Difficulty; await this.plugin.saveSettings(); }));
    renderLibrarySettings(el, this.plugin);
    renderResetControls(el, this.plugin);
    const toggles: [keyof Pick<Settings, 'dueOnly' | 'rememberTags' | 'inline' | 'reading' | 'livePreview' | 'autoSync'>, string][] = [
      ['dueOnly', 'Due only by default'], ['rememberTags', 'Remember selected tags'],
      ['inline', 'Show inline code practice'], ['reading', 'Reading view widgets'],
      ['livePreview', 'Live Preview widgets'], ['autoSync', 'Automatically sync modified notes']
    ];
    for (const [key, label] of toggles) new Setting(el).setName(label).addToggle(toggle => toggle
      .setValue(this.plugin.settings[key]).onChange(async value => {
        this.plugin.settings[key] = value;
        await this.plugin.saveSettings();
        if (['inline', 'reading', 'livePreview'].includes(key)) this.plugin.refreshInline();
      }));
    new Setting(el).setName('Modification debounce (milliseconds)').addText(text => text
      .setValue(String(this.plugin.settings.debounceMs)).onChange(async value => {
        const number = Number(value);
        if (Number.isFinite(number) && number >= 500 && number <= 30000) {
          this.plugin.settings.debounceMs = number; await this.plugin.saveSettings();
        }
      }));
    new Setting(el).setName('Backend request timeout (seconds)').setDesc('Local model generation can take several minutes.')
      .addText(text => text.setValue(String(this.plugin.settings.timeoutSeconds)).onChange(async value => {
        const number = Number(value);
        if (Number.isFinite(number) && number >= 10 && number <= 3600) {
          this.plugin.settings.timeoutSeconds = number; await this.plugin.saveSettings();
        }
      }));
    el.createEl('p', {text: 'Widget visibility changes apply immediately in the editor. Reopen Reading view to add newly enabled widgets.'});
  }
}
