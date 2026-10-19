import { modelFor } from '../settings/modelPicker';
import type QuizPlugin from '../main';
import type { AnswerPayload, QuizAction, QuizSession, Selection } from '../types';
import { errorMessage } from '../backend/api';

/** One controller for every view; views never own or discard quiz state. */
export class SessionController {
  state: QuizSession | null = null;
  busy = false;
  error = '';
  private listeners = new Set<() => void>();
  private draftTimer?: number;
  private pendingAttempt: {payload: string; id: string} | null = null;
  constructor(private plugin: QuizPlugin, readonly key: string) {}
  subscribe(listener: () => void) { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; }
  private notify() { for (const listener of this.listeners) listener(); }
  async restore() {
    const id = this.plugin.settings.sessionIds[this.key];
    if (!this.state && id) await this.perform('resume', {session_id: id});
  }
  async start(filters: Selection) { await this.perform('start', filters); }
  async perform(action: QuizAction, payload: object = {}) {
    if (this.busy) return;
    if (['difficulty', 'skip', 'next', 'retry'].includes(action) && this.draftTimer) window.clearTimeout(this.draftTimer);
    this.busy = true; this.error = ''; this.notify();
    try {
      if (action === 'start' && this.plugin.settings.connectionMode === 'server') await this.plugin.ensureInitialized();
      const settings = this.plugin.settings;
      const type = action === 'start' ? (payload as Selection).quiz_type : this.state?.quiz_type ?? settings.quizType;
      const choosingModel = action === 'start' || action === 'regenerate';
      const data: Record<string, unknown> = {};
      if (choosingModel) data.model = modelFor(settings, type);
      if (this.state) {
        data.session_id = this.state.session_id;
        data.question_id = this.state.question?.question_id;
        data.index = this.state.index;
      }
      Object.assign(data, payload);
      if (choosingModel && type === 'multiple-choice') {
        data.provider = settings.generationProvider ?? 'ollama';
        data.api_url = settings.apiUrl;
        data.api_model = settings.apiModel;
      }
      // Credentials accompany each request but never enter saved plugin settings.
      data.api_key = this.plugin.generationApiKey || '';
      data.api_key_url = settings.apiUrl || '';
      this.state = await this.plugin.api.quiz(action, data);
      this.plugin.settings.sessionIds[this.key] = this.state.session_id;
      await this.plugin.saveSettings();
    } catch (error) {
      this.error = errorMessage(error);
      // A failed advance may already have moved the server to an unrendered question.
      // Refresh that position before the next Skip, instead of resending the old ID.
      if (this.state && ['next', 'skip', 'regenerate', 'retry'].includes(action)) {
        try {
          this.state = await this.plugin.api.quiz('resume', {session_id: this.state.session_id});
          if (!this.state.question && (this.state.total === null || this.state.index < this.state.total)) {
            this.state.complete = false;
            this.state.preparation_error ||= this.error;
          }
        }
        catch { /* Keep the last known state and original error if reconnect fails. */ }
      }
    }
    finally { this.busy = false; this.notify(); }
  }
  async answer(payload: AnswerPayload) {
    if (this.busy) return;
    const signature = JSON.stringify({question: this.state?.question?.question_id, payload});
    if (this.pendingAttempt?.payload !== signature) this.pendingAttempt = {payload: signature, id: crypto.randomUUID()};
    await this.perform('answer', {...payload, request_id: this.pendingAttempt.id});
    if (!this.error) this.pendingAttempt = null;
  }
  draft(answers: Record<string, string>) {
    const q = this.state?.question;
    if (!q || q.type !== 'coding') return;
    q.draft = {...answers};
    if (this.draftTimer) window.clearTimeout(this.draftTimer);
    const session_id = this.state!.session_id, question_id = q.question_id;
    this.draftTimer = window.setTimeout(() => {
      void this.plugin.api.quiz('draft', {session_id, question_id, answers}).catch(() => {});
    }, 400);
  }
  async reset() {
    if (this.busy) return;
    if (this.state?.question && !this.state.question.completed) {
      await this.perform('abandon');
      if (this.error) return;
    }
    this.state = null; this.error = ''; this.pendingAttempt = null;
    delete this.plugin.settings.sessionIds[this.key];
    void this.plugin.saveSettings(); this.notify();
  }
  dispose() { if (this.draftTimer) window.clearTimeout(this.draftTimer); this.listeners.clear(); }
}
