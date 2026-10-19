/** Model preferences and shared model/regeneration controls. */
import { renderApiSettings } from './serviceSettings';
import type { ModelsResponse, QuizType, Settings } from '../types';
import type QuizPlugin from '../main';
import type { SessionController } from '../quiz/session';
import { errorMessage } from '../backend/api';

export function modelFor(settings: Settings, type: QuizType): string {
  return settings.quizModels?.[type] || settings.ollamaModel;
}

export function setModelFor(settings: Settings, type: QuizType, model: string) {
  settings.quizModels = {...settings.quizModels, [type]: model};
}

export function renderRegeneration(host: HTMLElement, plugin: QuizPlugin, controller: SessionController) {
  const question = controller.state?.question;
  if (!question || question.attempts.length) return;
  renderModelPicker(host, plugin, controller);
  if (question.type === 'coding') host.createEl('small', {text: 'Coding regeneration uses the built-in Python generator, not the selected LLM.'});
}

/** One installed-model control for the menu and both regeneration surfaces. */
export function renderModelPicker(host: HTMLElement, plugin: QuizPlugin, controller?: SessionController, quizType?: QuizType) {
  host = host.createDiv();
  const type = quizType ?? controller?.state?.question?.type ?? plugin.settings.quizType ?? 'multiple-choice';
  if (type === 'multiple-choice') renderApiSettings(host, plugin);
  const title = type === 'coding' ? 'Coding model' : 'Multiple Choice model';
  const box = host.createDiv({cls: 'mq-model-picker'});
  const label = box.createEl('label', {cls: 'mq-field'});
  label.createSpan({text: title});
  const select = label.createEl('select', {attr: {'aria-label': title}});
  select.disabled = true;
  const status = box.createEl('small', {attr: {role: 'status'}});
  const refresh = box.createEl('button', {text: 'Refresh models'});
  const coding = type === 'coding';
  const apiMode = () => type === 'multiple-choice' && plugin.settings.generationProvider === 'api';
  let selected = modelFor(plugin.settings, type);
  let saving = false;
  const regenerate = controller ? box.createEl('button', {text: 'Regenerate question'}) : null;
  if (regenerate) regenerate.disabled = true;
  async function load() {
    label.hidden = apiMode(); refresh.hidden = apiMode();
    select.disabled = true; refresh.disabled = true;
    if (regenerate) regenerate.disabled = true;
    if (apiMode()) {
      status.textContent = 'API selected. Enter an API model and key above.';
      refresh.disabled = false;
      if (regenerate) regenerate.disabled = !!controller?.busy;
      return;
    }
    status.textContent = 'Loading installed models…';
    try {
      const {models} = await plugin.api.call<ModelsResponse>('/models');
      if (apiMode()) return;
      select.empty();
      for (const model of [...new Set(models)]) select.createEl('option', {value: model, text: model});
      if (!models.length && !apiMode()) { status.textContent = 'No installed models. Install a model in Ollama, then refresh.'; return; }
      if (!models.includes(selected)) {
        select.createEl('option', {value: '', text: 'Choose an installed model'}); selected = '';
      }
      select.value = selected;
      select.disabled = !!controller?.busy;
      if (regenerate) regenerate.disabled = (!selected && !coding && !apiMode()) || !!controller?.busy;
      status.textContent = 'Cached answers are kept until you regenerate.';
    } catch (error) { status.textContent = errorMessage(error); }
    finally { refresh.disabled = !!controller?.busy; if (regenerate && (coding || apiMode())) regenerate.disabled = !!controller?.busy; }
  }
  select.addEventListener('change', () => {
    selected = select.value;
    if (regenerate) regenerate.disabled = (!selected && !coding && !apiMode()) || !!controller?.busy;
    // The selected model is applied atomically with start/regenerate, not via a
    // separate model-changing request that could race another quiz view.
    if (selected) { setModelFor(plugin.settings, type, selected); void plugin.saveSettings(); }
  });
  refresh.addEventListener('click', () => { if (!saving) void load(); });
  regenerate?.addEventListener('click', () => {
    if ((!selected && !coding && !apiMode()) || saving || controller?.busy) return;
    saving = true; regenerate.disabled = true; select.disabled = true;
    void controller!.perform('regenerate', selected ? {model: selected} : {}).finally(() => { saving = false; });
  });
  host.addEventListener('mq-provider-change', () => void load());
  void load();
  return box;
}
