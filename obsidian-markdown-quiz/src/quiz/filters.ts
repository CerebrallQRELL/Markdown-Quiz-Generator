import type QuizPlugin from '../main';
import type { Selection } from '../types';

export function selection(plugin: QuizPlugin): Selection {
  const s = plugin.settings;
  return {quiz_type: s.quizType, tags: [...plugin.selectedTags], exclude_tags: [...s.excludeTags], date_from: s.dateFrom,
    date_to: s.dateTo, due_only: s.dueOnly, source_file: s.currentOnly ? plugin.currentNote : undefined,
    direction: s.quizType === 'coding' && !['random', 'source'].includes(s.direction) ? 'random' : s.direction,
    length: s.length, difficulty: s.difficulty, python_imports: s.pythonImports || ''};
}

export function renderFilters(host: HTMLElement, plugin: QuizPlugin, tags: string[], changed: () => void) {
  const settings = plugin.settings;
  const save = () => { void plugin.saveSettings(); changed(); };
  const rerender: (() => void)[] = [];
  for (const exclude of [false, true]) {
    const key = exclude ? 'exclude' : 'include';
    const section = host.createEl('details', {cls: 'mq-filter'});
    section.open = !settings.collapsed[key];
    const summary = section.createEl('summary');
    section.addEventListener('toggle', () => { settings.collapsed[key] = !section.open; void plugin.saveSettings(); });
    const selected = () => exclude ? settings.excludeTags : plugin.selectedTags;
    const set = (values: string[]) => { if (exclude) settings.excludeTags = values; else plugin.selectedTags = values; };
    const chips = section.createDiv({cls: 'mq-tags mq-chips'});
    const search = section.createEl('input', {type: 'search', placeholder: 'Search tags...', attr: {'aria-label': `Search ${key} tags`}});
    const options = section.createDiv({cls: 'mq-tags', attr: {role: 'group', 'aria-label': `${key} tag options`}});
    const toggle = (tag: string) => {
      const normal = tag.toLowerCase();
      if (selected().some(t => t.toLowerCase() === normal)) set(selected().filter(t => t.toLowerCase() !== normal));
      else {
        set([...selected(), tag]);
        if (exclude) plugin.selectedTags = plugin.selectedTags.filter(t => t.toLowerCase() !== normal);
        else settings.excludeTags = settings.excludeTags.filter(t => t.toLowerCase() !== normal);
        plugin.rememberTag(tag);
      }
      for (const render of rerender) render(); save();
    };
    const render = () => {
      summary.textContent = `${exclude ? 'Exclude' : 'Include'} tags (${selected().length} selected)`;
      chips.empty(); options.empty();
      for (const tag of selected()) {
        const chip = chips.createEl('button', {text: `${tag} ×`, attr: {'aria-label': `Remove ${tag}`}});
        chip.addEventListener('click', () => toggle(tag));
      }
      const history = settings.tagHistory;
      const matches = tags.filter(t => t.toLowerCase() !== 'quiz' && t.toLowerCase().includes(search.value.toLowerCase())
        && !selected().some(v => v.toLowerCase() === t.toLowerCase()))
        .sort((a, b) => (history[b]?.last ?? 0) - (history[a]?.last ?? 0) || (history[b]?.count ?? 0) - (history[a]?.count ?? 0));
      for (const tag of matches.slice(0, 40)) {
        const button = options.createEl('button', {text: tag}); button.addEventListener('click', () => toggle(tag));
      }
      if (matches.length > 40) options.createEl('small', {text: 'Type more to narrow the list.'});
    };
    rerender.push(render); render();
    search.addEventListener('input', render);
    const keyboard = (event: KeyboardEvent) => {
      const buttons = [...options.querySelectorAll('button')];
      if (event.key === 'Escape') { search.value = ''; render(); section.open = false; search.blur(); event.stopPropagation(); }
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
        buttons[(index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length]?.focus();
      }
      if (event.key === 'Enter' && event.target === search) { event.preventDefault(); buttons[0]?.click(); }
    };
    search.addEventListener('keydown', keyboard); options.addEventListener('keydown', keyboard);
    const clear = section.createEl('button', {text: 'Clear'}); clear.addEventListener('click', () => { set([]); render(); save(); });
    section.createEl('small', {text: exclude ? 'Any match is excluded. Selecting a tag moves it out of Include.' : 'Any match is included. Selecting a tag moves it out of Exclude.'});
  }
  const dates = host.createEl('details', {cls: 'mq-filter'}); dates.open = !settings.collapsed.dates;
  const dateSummary = dates.createEl('summary');
  const summary = () => { dateSummary.textContent = `Date range (${settings.dateFrom || 'Any'} – ${settings.dateTo || 'Any'})`; };
  summary();
  dates.addEventListener('toggle', () => { settings.collapsed.dates = !dates.open; void plugin.saveSettings(); });
  const dateInputs: HTMLInputElement[] = [];
  for (const end of [false, true]) {
    const label = dates.createEl('label', {cls: 'mq-field'}); label.createSpan({text: end ? 'Through' : 'From'});
    const input = label.createEl('input', {type: 'date'}); dateInputs.push(input);
    input.value = end ? settings.dateTo : settings.dateFrom;
    input.addEventListener('click', () => { try { input.showPicker?.(); } catch { /* Native control remains available. */ } });
    input.addEventListener('keydown', event => { if (event.key === 'Escape') { input.blur(); event.stopPropagation(); } });
    input.addEventListener('change', () => { if (end) settings.dateTo = input.value; else settings.dateFrom = input.value; summary(); save(); });
  }
  dates.createEl('small', {text: 'Inclusive dates from #YYYY-MM-DD or #date/YYYY-MM-DD tags.'});
  const clearDates = dates.createEl('button', {text: 'Clear dates'});
  clearDates.addEventListener('click', () => { settings.dateFrom = settings.dateTo = ''; for (const input of dateInputs) input.value = ''; summary(); save(); });
  for (const [key, label] of [['dueOnly', 'Due only'], ['currentOnly', 'Current note only']] as const) {
    const row = host.createEl('label', {cls: 'mq-check'}); const input = row.createEl('input', {type: 'checkbox'});
    input.checked = settings[key]; row.createSpan({text: label}); input.addEventListener('change', () => { settings[key] = input.checked; save(); });
  }
  const select = (label: string, options: Record<string, string>, value: string, update: (value: string) => void) => {
    const row = host.createEl('label', {cls: 'mq-field'}); row.createSpan({text: label}); const input = row.createEl('select');
    for (const [value, text] of Object.entries(options)) input.createEl('option', {value, text});
    input.value = value; input.addEventListener('change', () => { update(input.value); save(); });
  };
  select('Direction', settings.quizType === 'coding' ? {random: 'Random', source: 'Source order'} :
    {random: 'Random', forward: 'Term → Definition', reverse: 'Definition → Term'}, selection(plugin).direction,
    value => { settings.direction = value as Selection['direction']; });
  if (settings.quizType === 'coding') select('Difficulty', {easy: 'Easy', medium: 'Medium', hard: 'Hard'}, settings.difficulty,
    value => { settings.difficulty = value as Selection['difficulty']; });
  select('Questions', {'5': '5', '10': '10', '20': '20', all: 'All matching', until: 'Until I stop'}, String(settings.length),
    value => { settings.length = value === 'all' || value === 'until' ? value : Number(value); });
}
