import type QuizPlugin from '../main';
import { errorMessage } from '../backend/api';
import type { LibrariesResponse } from '../types';

const suggestions = ['numpy', 'pandas', 'scipy', 'sympy', 'matplotlib', 'requests', 'pillow', 'scikit-learn', 'networkx', 'pytest'];
const identity = (name: string) => name.split('==')[0].toLowerCase().replace(/[-_.]+/g, '-');
export function renderLibrarySettings(host: HTMLElement, plugin: QuizPlugin) {
  host.createEl('h3', {text: 'Python libraries'});
  host.createEl('p', {text: 'Search suggested and added packages, or enter a package name to add it. Built-in Python libraries are always available. Changes apply to new questions; existing questions keep their original environment.'});
  const search = host.createEl('input', {type: 'search', attr: {'aria-label': 'Search Python libraries', placeholder: 'Search libraries or enter package==version'}});
  const add = host.createEl('button', {text: 'Add library'});
  const refresh = host.createEl('button', {text: 'Refresh libraries'});
  const status = host.createEl('p', {attr: {role: 'status'}});
  const list = host.createDiv({cls: 'mq-library-list'});
  let enabled: string[] = [];
  let disabled = [...(plugin.settings.disabledLibraries || [])];
  let busy = true;
  const render = () => {
    list.empty(); add.disabled = busy; refresh.disabled = busy;
    const known = new Map<string, string>();
    for (const name of [...suggestions, ...disabled, ...enabled]) known.set(identity(name), name);
    const matches = [...known.values()].filter(name => name.toLowerCase().includes(search.value.trim().toLowerCase())).sort();
    if (!matches.length) list.createEl('p', {text: 'No matches. Enter an exact package name and click Add library.'});
    for (const name of matches) {
      const active = enabled.includes(name), added = active || disabled.includes(name);
      const row = list.createDiv({cls: 'mq-library-row'});
      const label = row.createEl('label');
      const toggle = label.createEl('input', {type: 'checkbox', attr: {'aria-label': `Enable ${name}`}});
      toggle.checked = active; toggle.disabled = busy;
      label.createSpan({text: name + (active ? ' · Enabled' : added ? ' · Disabled' : ' · Suggested')});
      toggle.addEventListener('change', () => void change(name, active ? 'disable' : 'enable'));
      const action = row.createEl('button', {text: added ? 'Remove' : 'Add', attr: {'aria-label': `${added ? 'Remove' : 'Add'} ${name}`}});
      action.disabled = busy;
      action.addEventListener('click', () => void change(name, added ? 'remove' : 'enable'));
    }
  };
  async function change(name: string, action: 'enable' | 'disable' | 'remove') {
    if (busy) return;
    if (!/^[A-Za-z0-9][A-Za-z0-9_.-]*(?:==[A-Za-z0-9][A-Za-z0-9_.+-]*)?$/.test(name)) {
      status.textContent = 'Enter one package name, optionally with ==version.'; return;
    }
    const same = (p: string) => identity(p) === identity(name);
    const next = enabled.filter(p => !same(p));
    const off = disabled.filter(p => !same(p));
    if (action === 'enable') next.push(name);
    if (action === 'disable') off.push(name);
    busy = true; render(); status.textContent = 'Applying libraries… This may take several minutes.';
    try {
      const result = await plugin.api.call<LibrariesResponse>('/libraries', {packages: next.join(' ')});
      enabled = result.packages.split(/\s+/).filter(Boolean); disabled = off;
      plugin.settings.disabledLibraries = off; await plugin.saveSettings();
      status.textContent = 'Libraries updated. Start a new quiz to use this environment.';
    } catch (error) { status.textContent = errorMessage(error); }
    finally { busy = false; render(); }
  }
  async function load() {
    busy = true; render(); status.textContent = 'Loading libraries…';
    try {
      const result = await plugin.api.call<LibrariesResponse>('/libraries');
      enabled = result.packages.split(/\s+/).filter(Boolean);
      status.textContent = enabled.length ? `${enabled.length} enabled libraries.` : 'Built-in Python libraries only.';
    } catch (error) { status.textContent = errorMessage(error); }
    finally { busy = false; render(); }
  }
  search.addEventListener('input', render);
  add.addEventListener('click', () => void change(search.value.trim(), 'enable'));
  refresh.addEventListener('click', () => void load());
  host.createEl('small', {text: 'Third-party installation requires Docker and internet access on the backend. Up to 20 enabled packages; Python 3.13 wheels only. Disable keeps a package in your list; Remove removes it from your list and future environments.'});
  const importsLabel = host.createEl('label', {cls: 'mq-field', text: 'Additional Python imports (optional)'});
  const imports = importsLabel.createEl('textarea', {attr: {'aria-label': 'Additional Python imports', placeholder: 'import numpy as np\nfrom math import sqrt'}});
  imports.rows = 3; imports.maxLength = 4000; imports.value = plugin.settings.pythonImports || '';
  imports.addEventListener('input', () => { plugin.settings.pythonImports = imports.value; void plugin.saveSettings(); });
  host.createEl('small', {text: 'These import statements are added to new coding questions and used for both expected output and your answers. Leave blank when your code already includes its imports.'});
  void load();
}
