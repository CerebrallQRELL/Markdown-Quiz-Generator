import type QuizPlugin from '../main';
import { errorMessage } from '../backend/api';
import type { ResetResponse } from '../types';

export function renderApiSettings(host: HTMLElement, plugin: QuizPlugin) {
  const box = host.createDiv({cls: 'mq-api-settings'});
  const label = box.createEl('label', {cls: 'mq-field', text: 'Generation source'});
  const provider = label.createEl('select', {attr: {'aria-label': 'Generation source'}});
  provider.createEl('option', {value: 'ollama', text: 'Ollama'});
  provider.createEl('option', {value: 'api', text: 'API'});
  provider.value = plugin.settings.generationProvider ?? 'ollama';
  const fields = box.createDiv();
  fields.hidden = provider.value !== 'api';
  provider.addEventListener('change', () => {
    plugin.settings.generationProvider = provider.value as 'ollama' | 'api';
    fields.hidden = provider.value !== 'api';
    void plugin.saveSettings();
    host.dispatchEvent(new Event('mq-provider-change'));
  });
  for (const [key, title, placeholder] of [
    ['apiUrl', 'API base URL', 'https://api.openai.com/v1'],
    ['apiModel', 'API model', 'Enter your provider’s model name']
  ] as const) {
    const field = fields.createEl('label', {cls: 'mq-field', text: title});
    const input = field.createEl('input', {attr: {'aria-label': title, placeholder}});
    input.value = plugin.settings[key] || '';
    input.addEventListener('input', () => { plugin.settings[key] = input.value.trim(); void plugin.saveSettings(); });
  }
  const keyLabel = fields.createEl('label', {cls: 'mq-field', text: 'API key (session only)'});
  const key = keyLabel.createEl('input', {type: 'password', attr: {'aria-label': 'API key', autocomplete: 'off'}});
  key.value = plugin.generationApiKey || '';
  key.addEventListener('input', () => { plugin.generationApiKey = key.value.trim(); });
  const clear = fields.createEl('button', {text: 'Clear API key'});
  clear.addEventListener('click', () => { plugin.generationApiKey = ''; key.value = ''; });
  fields.createEl('small', {text: 'API sends multiple-choice quiz text through your backend to this provider. Use an OpenAI-compatible Chat Completions endpoint with JSON support. The key is never saved; enter it again after restarting Obsidian. Start a new quiz or regenerate to apply a source change.'});
}

export function renderResetControls(host: HTMLElement, plugin: QuizPlugin) {
  const box = host.createEl('details');
  box.createEl('summary', {text: 'Server, sandbox & Ollama'});
  box.createEl('small', {text: 'Reset server restarts the local backend or reloads this vault on a managed server. Reset sandbox prepares a fresh test run with enabled libraries. Reset Ollama unloads the selected model; the next request loads it again. Study progress is kept.'});
  const status = box.createEl('p', {attr: {role: 'status'}});
  const buttons: HTMLButtonElement[] = [];
  for (const target of ['server', 'sandbox', 'ollama']) {
    const button = box.createEl('button', {text: `Reset ${target === 'ollama' ? 'Ollama' : target}`});
    buttons.push(button);
    button.addEventListener('click', async () => {
      buttons.forEach(b => b.disabled = true);
      status.textContent = `Resetting ${target}…`;
      try {
        if (target === 'server') { await plugin.resetServer(); status.textContent = 'Server reset complete.'; }
        else {
          const result = await plugin.api.call<ResetResponse>('/admin/reset', {target, model: plugin.settings.quizModels?.['multiple-choice'] || plugin.settings.ollamaModel});
          status.textContent = result.message;
        }
      } catch (error) { status.textContent = errorMessage(error); }
      finally { buttons.forEach(b => b.disabled = false); }
    });
  }
}
