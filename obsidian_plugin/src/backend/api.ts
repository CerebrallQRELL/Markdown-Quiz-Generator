/** HTTP transport, active-vault connection and response validation. */
import { requestUrl } from 'obsidian';
import type { QuizAction, QuizSession, Catalog, Health, Settings, VaultConnection } from '../types';

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'The request could not finish. Please retry.';
}

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

// Small runtime checks keep an incompatible/malformed backend out of the UI.
export function validateResponse(path: string, value: unknown): void {
  if (!object(value)) throw new Error('Invalid backend response. Update the backend and plugin together.');
  let valid = true;
  if (path === '/vault/connect') valid = typeof value.vault_id === 'string' && typeof value.vault_path === 'string';
  else if (path === '/quiz/catalog') valid = typeof value.count === 'number' && Array.isArray(value.tags);
  else if (/^\/quiz\/(start|resume|answer|next|skip|regenerate|draft|abandon|input|difficulty|retry)$/.test(path)) valid = typeof value.session_id === 'string' && typeof value.complete === 'boolean' && object(value.progress) && (value.question === null || object(value.question));
  else if (path === '/health') valid = value.api_version === 1 && typeof value.ollama === 'boolean' && typeof value.sandbox === 'boolean';
  else if (path === '/tags') valid = Array.isArray(value.tags) && value.tags.every(v => typeof v === 'string');
  else if (path === '/stats') valid = ['due', 'mastered', 'learning', 'new', 'correct', 'incorrect', 'total'].every(k => typeof value[k] === 'number');
  else if (path.startsWith('/quiz/term/') && !path.endsWith('/answer')) {
    valid = typeof value.session_id === 'string' && typeof value.complete === 'boolean' && object(value.progress);
    if (value.question !== null) {
      const q = value.question;
      valid = valid && object(q) && typeof q.question_id === 'string' && typeof q.prompt === 'string'
        && typeof q.source_file === 'string' && Array.isArray(q.choices) && q.choices.length === 4
        && q.choices.every(v => typeof v === 'string');
    }
  } else if (path === '/quiz/term/answer') valid = typeof value.correct === 'boolean' && typeof value.correct_answer === 'string';
  else if (path === '/quiz/code/answer') valid = typeof value.correct === 'boolean' && typeof value.stdout === 'string' && typeof value.stderr === 'string';
  else if (path.startsWith('/quiz/code/')) valid = typeof value.question_id === 'string' && typeof value.blank_code === 'string' && typeof value.expected_output === 'string';
  if (!valid) throw new Error('Incompatible or invalid backend response. Use backend API version 1.');
}

export class QuizClient {
  private vaultId = '';
  private connectedBase = '';
  private connecting: Promise<void> | null = null;
  resetConnection() { this.vaultId = ''; this.connectedBase = ''; }
  private pending = new Map<string, Promise<unknown>>();
  constructor(private settings: () => Settings, private token: () => string = () => '', private vault: () => string = () => '') {}

  async call<T>(path: string, body?: unknown): Promise<T> {
    const settings = this.settings();
    const base = settings.backendUrl.replace(/\/$/, '');
    const url = new URL(base);
    const loopback = ['127.0.0.1', 'localhost'].includes(url.hostname);
    if (url.username || url.password || url.search || url.hash ||
        (settings.connectionMode === 'server' ? !(url.protocol === 'https:' || (loopback && url.protocol === 'http:')) : !(loopback && url.protocol === 'http:'))) {
      throw new Error('Use local HTTP or an HTTPS server URL.');
    }
    if (settings.connectionMode === 'server' && !this.token()) throw new Error('Enter the server token in plugin settings.');
    if (!['/vault/connect', '/health', '/admin/restart'].includes(path) && this.vault() && (!this.vaultId || this.connectedBase !== base)) {
      const body = settings.connectionMode === 'server' ? {vault_key: settings.vaultKey} : {vault_path: this.vault()};
      if (!this.connecting) this.connecting = this.call<VaultConnection>('/vault/connect', body)
        .then(value => { this.vaultId = value.vault_id; this.connectedBase = base; })
        .finally(() => { this.connecting = null; });
      await this.connecting;
    }
    const key = this.vaultId + base + path + JSON.stringify(body ?? null);
    const existing = this.pending.get(key);
    if (existing) return existing as Promise<T>;
    const request = (async () => {
      let response;
      try {
        response = await requestUrl({url: base + path, method: body === undefined ? 'GET' : 'POST',
          contentType: 'application/json', body: body === undefined ? undefined : JSON.stringify(body),
          headers: {...(this.token() ? {Authorization: `Bearer ${this.token()}`} : {}),
            ...(this.vaultId && path !== '/vault/connect' ? {'X-Quiz-Vault': this.vaultId} : {})}, throw: false});
      } catch {
        this.resetConnection();
        throw new Error(`Quiz backend is not available. Click Start backend. Configured address: ${base}`);
      }
      let value: unknown;
      try { value = JSON.parse(response.text); }
      catch { throw new Error('Backend returned invalid JSON. Check its address and version.'); }
      if (path === '/vault/connect' && response.status === 404) throw new Error('An older backend is running. Stop its Python terminal, replace the complete plugin folder, then click Start backend.');
      if (response.status === 409) this.resetConnection();
      if (response.status >= 400) throw new Error(object(value) && typeof value.error === 'string' ? value.error : 'Backend request failed.');
      validateResponse(path, value);
      return value as T;
    })();
    // requestUrl cannot cancel a transport request. Retain its in-flight entry
    // after a UI timeout, so another click cannot start the same work twice.
    this.pending.set(key, request);
    void request.finally(() => this.pending.delete(key)).catch(() => {});
    let timer: number | undefined;
    try {
      return await Promise.race([request, new Promise<never>((_, reject) => {
        timer = window.setTimeout(() => reject(new Error('Backend request timed out. Work may still be finishing; retry shortly.')),
          (path === '/libraries' && body !== undefined ? Math.max(330, settings.timeoutSeconds) : settings.timeoutSeconds) * 1000);
      })]);
    } finally { if (timer !== undefined) window.clearTimeout(timer); }
  }

  quiz(action: QuizAction, body: unknown) { return this.call<QuizSession>('/quiz/' + action, body); }
  catalog(body: unknown) { return this.call<Catalog>('/quiz/catalog', body); }
  async health() {
    const health = await this.call<Health>('/health');
    if (!health.capabilities?.includes('shared-sessions-v2') || !health.capabilities?.includes('session-models')) throw new Error('An older backend is running. Restart it using the updated complete plugin folder.');
    return health;
  }
  tags() { return this.call<{tags: string[]}>('/tags'); }
}
