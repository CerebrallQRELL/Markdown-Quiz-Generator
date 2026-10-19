/** Sidebar presentation; SessionController owns the quiz state. */
import { renderResetControls } from '../settings/serviceSettings';
import { renderModelPicker, renderRegeneration } from '../settings/modelPicker';
import { ItemView, WorkspaceLeaf } from 'obsidian';
import type QuizPlugin from '../main';
import { errorMessage } from '../backend/api';
import { selection, renderFilters } from '../quiz/filters';
import { renderCoding, renderMultipleChoice, renderSessionError } from './questionRenderers';
import type { Catalog, Health } from '../types';
import type { SessionController } from '../quiz/session';

export const VIEW_TYPE = 'markdown-quiz-view';
export class QuizView extends ItemView {
  private controller: SessionController;
  private catalog: Catalog | null = null;
  private health: Health | null = null;
  private error = '';
  private alive = true;
  private connecting = false;
  private unsubscribe?: () => void;
  private disposeQuestion?: () => void;
  private countdown?: number;
  private countdownQuestion = '';
  private deadline = 0;
  private countRevision = 0;
  private countMessage = '';
  private countEl?: HTMLElement;
  private startButton?: HTMLButtonElement;
  constructor(leaf: WorkspaceLeaf, private plugin: QuizPlugin) { super(leaf); this.controller = plugin.session('sidebar'); }
  get currentOnly() { return this.plugin.settings.currentOnly; }
  set currentOnly(value: boolean) { this.plugin.settings.currentOnly = value; }
  get dueOnly() { return this.plugin.settings.dueOnly; }
  set dueOnly(value: boolean) { this.plugin.settings.dueOnly = value; }
  getViewType() { return VIEW_TYPE; }
  getDisplayText() { return 'Quiz'; }
  getIcon() { return 'brain'; }
  async onOpen() {
    this.alive = true; this.contentEl.addClass('mq-pane'); this.contentEl.tabIndex = 0;
    this.unsubscribe = this.controller.subscribe(() => this.render());
    this.registerDomEvent(this.contentEl, 'keydown', event => {
      if ((event.target as HTMLElement).closest('input, textarea, select, [contenteditable="true"]') || event.ctrlKey || event.metaKey || event.altKey) return;
      const q = this.controller.state?.question;
      if (!q || this.controller.busy) return;
      if (event.key === 'Enter' && q.completed) { event.preventDefault(); void this.controller.perform('next'); }
      if (q.type !== 'multiple-choice' || q.completed) return;
      const index = ['1a', '2b', '3c', '4d'].findIndex(keys => event.key.length === 1 && keys.includes(event.key.toLowerCase()));
      if (index >= 0) { event.preventDefault(); void this.controller.answer({answer_id: q.answers[index].id}); }
    });
    this.render();
    if (this.app.workspace.layoutReady) await this.refresh();
    else this.app.workspace.onLayoutReady(() => { if (this.alive) void this.refresh(); });
  }
  async onClose() {
    this.alive = false; this.unsubscribe?.(); this.disposeQuestion?.();
    if (this.countdown) window.clearInterval(this.countdown);
    this.countdown = undefined; this.countdownQuestion = ''; this.countRevision++;
  }
  noteChanged() { if (!this.controller.state && this.currentOnly) void this.updateCount(); }
  async refreshTags() { if (!this.controller.state) { await this.updateCount(); if (this.alive && !this.contentEl.querySelector('input:focus')) this.render(); } }
  async refresh() {
    if (this.connecting) return;
    this.connecting = true; this.error = ''; this.render();
    try {
      this.health = await this.plugin.api.health();
      await this.plugin.ensureInitialized();
      await this.controller.restore();
      await this.updateCount();
    } catch (error) { this.error = errorMessage(error); this.health = null; }
    finally { this.connecting = false; this.render(); }
  }
  async start(missed?: string[]) {
    if (this.controller.state && !this.controller.state.complete) return;
    const filters = selection(this.plugin);
    if (filters.date_from && filters.date_to && filters.date_from > filters.date_to) { this.error = 'From must be on or before Through.'; this.render(); return; }
    if (this.currentOnly && !filters.source_file) { this.error = 'Open a Markdown note first.'; this.render(); return; }
    if (missed) { filters.question_ids = missed; filters.length = 'all'; filters.due_only = false; }
    await this.controller.start(filters);
  }
  private async updateCount() {
    const revision = ++this.countRevision;
    const filters = selection(this.plugin);
    this.catalog = null; this.showCount('Checking matching questions…');
    if (this.currentOnly && !filters.source_file) { this.showCount('Open a Markdown note for Current note only.'); return; }
    if (filters.date_from && filters.date_to && filters.date_from > filters.date_to) { this.showCount('From must be on or before Through.'); return; }
    try {
      const catalog = await this.plugin.api.catalog(filters);
      if (revision !== this.countRevision || !this.alive) return;
      this.catalog = catalog; this.showCount();
    } catch (error) { if (revision === this.countRevision) this.showCount(errorMessage(error)); }
  }
  private showCount(message?: string) {
    if (message !== undefined) this.countMessage = message;
    else if (this.catalog) this.countMessage = '';
    if (this.countEl) this.countEl.textContent = this.countMessage || (this.catalog?.count ? `${this.catalog.count} questions available` : 'No questions match these filters.');
    if (this.startButton) this.startButton.disabled = !this.catalog?.count || this.controller.busy || this.connecting;
  }
  private button(parent: HTMLElement, text: string, callback: () => void) {
    const button = parent.createEl('button', {text}); button.disabled = this.controller.busy || this.connecting;
    button.addEventListener('click', callback); return button;
  }
  private home() {
    const el = this.contentEl, settings = this.plugin.settings;
    const group = el.createEl('fieldset', {cls: 'mq-quiz-type'}); group.createEl('legend', {text: 'Quiz type'});
    for (const [value, text] of [['multiple-choice', 'Multiple Choice'], ['coding', 'Coding']] as const) {
      const label = group.createEl('label'); const input = label.createEl('input', {type: 'radio', attr: {name: 'mq-quiz-type', value}});
      input.checked = settings.quizType === value; label.createSpan({text});
      input.addEventListener('change', () => {
        settings.quizType = value; settings.direction = 'random'; this.catalog = null;
        void this.plugin.saveSettings(); this.render(); void this.updateCount().then(() => { if (this.alive && !this.controller.state) this.render(); });
      });
    }
    el.createEl('small', {text: settings.quizType === 'multiple-choice' ? 'Only terms marked #quiz in this vault.' : 'Python code blocks in this vault.'});
    renderModelPicker(el, this.plugin);
    renderResetControls(el, this.plugin);
    if (settings.quizType === 'coding') el.createEl('small', {text: 'Coding variations use the built-in Python generator; the LLM model is used for multiple-choice answers.'});
    renderFilters(el, this.plugin, this.catalog?.tags ?? [], () => void this.updateCount());
    this.countEl = el.createEl('p', {attr: {role: 'status'}});
    this.startButton = this.button(el, 'Start quiz', () => void this.start()); this.startButton.addClass('mod-cta'); this.showCount();
    if (this.catalog) {
      const details = el.createEl('details'); details.createEl('summary', {text: 'Statistics for matching questions'});
      const stats = this.catalog.stats;
      details.createEl('p', {text: `Due: ${stats.due} · Mastered: ${stats.mastered} · Learning: ${stats.learning} · New: ${stats.new}`});
    }
    this.button(el, 'Rescan vault', () => void this.plugin.fullSync().then(() => this.refreshTags()).catch(error => { this.error = errorMessage(error); this.render(); }));
  }
  private render() {
    if (!this.alive) return;
    this.disposeQuestion?.(); this.disposeQuestion = undefined;
    const el = this.contentEl, focused = el.contains(el.ownerDocument.activeElement);
    el.empty(); this.countEl = undefined; this.startButton = undefined;
    el.createEl('h2', {text: 'Quiz'});
    el.createDiv({cls: 'mq-status', text: this.health ? `Connected · Ollama ${this.health.ollama ? 'ready' : 'unavailable'} · Sandbox ${this.health.sandbox ? 'ready' : 'unavailable'}` : 'Backend offline'});
    if (!this.health) this.button(el, this.plugin.settings.connectionMode === 'server' ? 'Connect to server' : 'Start backend', () => void this.plugin.startBackend().then(() => this.refresh()).catch(error => { this.error = errorMessage(error); this.render(); }));
    const error = renderSessionError(el, this.controller, this.error, this.controller.busy || this.connecting);
    if (error) {
      this.button(el, 'Reconnect', () => void this.refresh());
    }
    if (this.controller.busy || this.connecting) el.createEl('p', {text: 'Working…', attr: {role: 'status'}});
    const state = this.controller.state;
    if (!state) { this.home(); return; }
    if (state.notice) el.createEl('p', {text: state.notice, attr: {role: 'status'}});
    if (state.complete) {
      el.createEl('h3', {text: 'Quiz complete'});
      const p = state.progress;
      el.createEl('p', {text: `${p.correct}/${p.answered} correct · ${p.percent}% · First try: ${p.first_correct} · After retry: ${p.retry_correct} · Incorrect/skipped: ${p.incorrect}`});
      if (p.missed.length) this.button(el, 'Practice missed questions', () => void this.start(p.missed));
    } else if (state.question) {
      const q = state.question;
      el.createEl('p', {text: `Question ${state.index + 1}${state.total === null ? '' : ` of ${state.total}`}`});
      const progress = el.createEl('progress', {attr: {'aria-label': 'Quiz progress'}});
      progress.max = state.total ?? state.index + 1; progress.value = state.progress.answered;
      el.createEl('small', {text: `First try: ${state.progress.first_correct} · After retry: ${state.progress.retry_correct} · Incorrect: ${state.progress.incorrect}`});
      if (q.type === 'coding') this.disposeQuestion = renderCoding(el, this.controller);
      else renderMultipleChoice(el, this.controller);
      if (q.completed) {
        if (q.type === 'multiple-choice') {
          if (this.countdownQuestion !== q.question_id) {
            if (this.countdown) window.clearInterval(this.countdown);
            this.countdownQuestion = q.question_id; this.deadline = Date.now() + 5000;
            this.countdown = window.setInterval(() => {
              if (!this.alive || this.controller.state?.question?.question_id !== q.question_id) return;
              const left = Math.max(0, Math.ceil((this.deadline - Date.now()) / 1000));
              const output = this.contentEl.querySelector('.mq-countdown'); if (output) output.textContent = `Next question in ${left}…`;
              if (!left && !this.controller.busy) {
                window.clearInterval(this.countdown); this.countdown = undefined;
                void this.controller.perform('next');
              }
            }, 200);
          }
          el.createEl('p', {cls: 'mq-countdown', text: `Next question in ${Math.max(0, Math.ceil((this.deadline - Date.now()) / 1000))}…`, attr: {role: 'status'}});
        }
        this.button(el, 'Next now', () => { if (this.countdown) window.clearInterval(this.countdown); this.countdown = undefined; void this.controller.perform('next'); });
      } else {
        if (!error) this.button(el, 'Skip question', () => void this.controller.perform('skip'));
        renderRegeneration(el, this.plugin, this.controller);
      }
      this.button(el, 'Open source note', () => void this.plugin.openSource(q.source_file, q.source_line));
    }
    this.button(el, 'Start over', () => {
      if (this.countdown) window.clearInterval(this.countdown); this.countdown = undefined; this.countdownQuestion = '';
      void this.controller.reset().then(() => this.updateCount()).then(() => this.render());
    });
    if (focused) el.focus({preventScroll: true});
  }
}
