import assert from 'node:assert/strict';

import { EditorState } from '@codemirror/state';

import { EditorView } from '@codemirror/view';

import { editorInfoField, editorLivePreviewField } from 'obsidian';

import { findBlocks, codeHash } from '../src/views/blocks';

import { QuizClient, validateResponse } from '../src/backend/api';

import { mountPractice, livePreviewExtension } from '../src/views/inlineCodeQuiz';

import { SessionController } from '../src/quiz/session';

import { mountBlankEditor } from '../src/views/CodeBlankEditor';

import { renderFilters } from '../src/quiz/filters';

import { QuizView } from '../src/views/QuizView';



const text = '# Notes\n```python\nprint("café")\n```\n~~~py\nprint("café")\n~~~\n```js\nignored()\n```';

const blocks = findBlocks(text);

assert.equal(blocks.length, 2);

assert.deepEqual(blocks.map(b => b.occurrence), [1, 2]);

assert.equal(text.slice(blocks[0].from, blocks[0].to), '```python\nprint("café")\n```');

assert.equal(findBlocks('```python\nunclosed').length, 0);

assert.equal(await codeHash('print(1)  \n'), await codeHash('\nprint(1)'));

const large = Array.from({length: 2000}, (_, i) => '```python\nprint(' + i + ')\n```').join('\n');

const started = performance.now();

assert.equal(findBlocks(large).length, 2000);

assert.ok(performance.now() - started < 1500, 'Large-note scan should remain inexpensive');

assert.throws(() => validateResponse('/health', {status: 'ok', api_version: 2}));

assert.throws(() => validateResponse('/quiz/code/get', {question_id: 1}));



let calls = 0;

let release: ((value: unknown) => void) | undefined;

const coding: any = {question_id: 'q1', source_id: 'underlying', source_file: 'note.md', source_line: 1,

  type: 'coding', blank_code: 'print(<BLANK_1> + <BLANK_2>)', blanks: [{id: 'blank_1', marker: '<BLANK_1>'}, {id: 'blank_2', marker: '<BLANK_2>'}],

  expected_output: '2\n', difficulty: 'medium', mastery: 0, completed: false, attempts: [], result: null, draft: {}};

const progress = {answered: 0, correct: 0, incorrect: 0, first_correct: 0, retry_correct: 0, failed_runs: 0, missed: [], percent: 0};

const sessionState: any = {session_id: 's1', quiz_type: 'coding', question: coding, index: 0, total: 1, complete: false, progress};

const controllers = new Map<string, SessionController>();

const fake: any = {

  settings: {inline: true, livePreview: true, difficulty: 'medium', quizType: 'coding', tags: [], excludeTags: [],

    tagHistory: {}, collapsed: {}, sessionIds: {}, dateFrom: '', dateTo: '', dueOnly: false, currentOnly: false, direction: 'random', length: 10},

  selectedTags: [], currentNote: 'note.md', active: true, widgetRevision: 0, inlineDisposers: new Set<() => void>(),

  app: {workspace: {layoutReady: true}},

  saveSettings: async () => {}, rememberTag: () => {}, ensureInitialized: async () => {},

  session(key: string) { if (!controllers.has(key)) controllers.set(key, new SessionController(fake, key)); return controllers.get(key)!; },

  api: {

    health: async () => ({status: 'ok', ollama: true, sandbox: true}),

    catalog: async () => ({count: 2, tags: ['Python', 'Notes'], stats: {total: 2, due: 2, mastered: 0, learning: 0, new: 2}}),

    quiz: async (action: string, payload: any) => {

      if (action === 'draft') return sessionState;

      calls++;

      if (action === 'answer') return new Promise(resolve => { release = resolve; });

      return structuredClone(sessionState);

    }

  }

};

const host = document.createElement('div'); document.body.append(host);

const dispose = mountPractice(fake, host, 'note.md', blocks[0]);

assert.equal(calls, 0, 'Rendering does not generate a question');

const button = (label: string) => [...host.querySelectorAll('button')].find(b => b.textContent === label)!;

assert.equal(host.querySelector('[aria-label="Program input"]'), null);
button('Start practice').click();

await new Promise(resolve => setTimeout(resolve, 30));

assert.equal(calls, 1);
assert.equal((host.querySelector('[aria-label="Program input"]') as HTMLTextAreaElement).value, '');
assert.ok(host.querySelector('[aria-label="Coding difficulty"]'));

const inputs = [...host.querySelectorAll<HTMLTextAreaElement>('.mq-code-editor textarea')];

assert.equal(inputs.length, 2);

assert.ok(host.querySelector('.mq-code-editor')?.textContent?.includes('print('));

inputs[0].value = '1'; inputs[0].dispatchEvent(new Event('input'));

inputs[1].value = '1'; inputs[1].dispatchEvent(new Event('input'));

inputs[0].focus(); inputs[0].dispatchEvent(new KeyboardEvent('keydown', {key: 'Tab', bubbles: true, cancelable: true}));

assert.equal(document.activeElement, inputs[1], 'Tab moves between blanks');

button('Run answer').click(); button('Run answer').click();

assert.equal(calls, 2, 'Concurrent submissions are suppressed');

const solved = structuredClone(sessionState);

solved.question.completed = true;

solved.question.result = {correct: true, completed: true, status: 'correct', stdout: '2\n', stderr: '', attempts: 1, mastery: 2};

solved.question.mastery = 2; solved.result = solved.question.result;

release!(solved);

await new Promise(resolve => setTimeout(resolve, 0));

assert.ok(host.textContent?.includes('Received output'));

assert.ok(host.textContent?.includes('Correct output'));

const controller = [...controllers.values()][0];

assert.equal(controller.state?.question?.source_id, 'underlying');

dispose();

assert.equal(host.isConnected, false);

const secondHost = document.createElement('div'); document.body.append(secondHost);

const secondDispose = mountPractice(fake, secondHost, 'note.md', blocks[0]);

await new Promise(resolve => setTimeout(resolve, 10));

assert.ok(secondHost.textContent?.includes('Correct output'), 'Closing/remounting preserves inline practice');

secondDispose();



const protectedHost = document.createElement('div'); document.body.append(protectedHost);

const editor = mountBlankEditor(protectedHost, coding, () => {}, () => {});

const originalTemplate = editor.model.template;

assert.throws(() => editor.model.set('protected', 'overwrite'));

assert.throws(() => { (editor.model as any).template = 'overwrite'; });

editor.inputs[0].value = 'paste\n    multiline'; editor.inputs[0].dispatchEvent(new Event('input'));

assert.equal(editor.model.template, originalTemplate);

assert.deepEqual(Object.keys(editor.model.answers()), ['blank_1', 'blank_2']);

assert.equal(protectedHost.querySelector('[contenteditable="true"]'), null);

await new Promise(resolve => setTimeout(resolve, 5));

assert.ok(protectedHost.querySelector('.token.keyword'), 'Syntax tokens remain visible');

editor.dispose();



const state = EditorState.create({doc: text, extensions: [editorInfoField, editorLivePreviewField, livePreviewExtension(fake)]});

assert.ok(state.facet(EditorView.decorations).some(value => typeof value !== 'function' && value.size === 2));

assert.equal(state.doc.toString(), text);

const transaction = state.update({changes: {from: 0, to: text.length, insert: 'No code'}});

assert.ok(transaction.state.facet(EditorView.decorations).every(value => typeof value === 'function' || value.size === 0));



const filtersHost = document.createElement('div'); document.body.append(filtersHost);

let filterChanges = 0;

renderFilters(filtersHost, fake, ['Python', 'Notes'], () => { filterChanges++; });

const sections = [...filtersHost.querySelectorAll('details')];

const searches = [...filtersHost.querySelectorAll<HTMLInputElement>('input[type=search]')];

searches[0].value = 'Pyth'; searches[0].dispatchEvent(new Event('input'));

searches[0].dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true}));

assert.deepEqual(fake.selectedTags, ['Python']);

const excludePython = [...sections[1].querySelectorAll('button')].find(b => b.textContent === 'Python')!;

excludePython.click();

assert.deepEqual(fake.selectedTags, []);

assert.deepEqual(fake.settings.excludeTags, ['Python']);

assert.ok(sections[1].querySelector('.mq-chips')?.textContent?.includes('Python ×'));

sections[1].open = false; sections[1].dispatchEvent(new Event('toggle'));

assert.equal(fake.settings.collapsed.exclude, true);

assert.ok(sections[1].querySelector('summary')?.textContent?.includes('1 selected'));

assert.equal(filtersHost.querySelectorAll('input[type=date]').length, 2);

const dates = [...filtersHost.querySelectorAll<HTMLInputElement>('input[type=date]')];

dates[0].value = '2026-10-14'; dates[0].dispatchEvent(new Event('change'));

assert.equal(fake.settings.dateFrom, '2026-10-14');

assert.ok(filterChanges >= 3);



// Sidebar uses one selector and preserves controller state when changing notes.

fake.settings.dateFrom = ''; fake.settings.excludeTags = [];

const sidebar = fake.session('sidebar');

const view = new QuizView({app: fake.app} as never, fake);

document.body.append(view.contentEl);

await view.onOpen();

const radios = [...view.contentEl.querySelectorAll<HTMLInputElement>('input[type=radio]')];

assert.equal(radios.length, 2); assert.equal(radios.filter(r => r.checked).length, 1);

assert.ok(view.contentEl.textContent?.includes('2 questions available'));
fake.settings.dateFrom = '2026-10-16'; fake.settings.dateTo = '2026-10-14';
await (view as any).updateCount();
assert.ok(view.contentEl.textContent?.includes('From must be on or before Through'));
assert.ok([...view.contentEl.querySelectorAll('button')].find(b => b.textContent === 'Start quiz')?.disabled);
fake.settings.dateFrom = fake.settings.dateTo = '';
const oldCatalog = fake.api.catalog;
fake.api.catalog = async () => ({count: 0, tags: [], stats: {total: 0}});
await (view as any).updateCount();
assert.ok(view.contentEl.textContent?.includes('No questions match'));
assert.ok([...view.contentEl.querySelectorAll('button')].find(b => b.textContent === 'Start quiz')?.disabled);
fake.api.catalog = oldCatalog;
await (view as any).updateCount();

const mc: any = {...coding, type: 'multiple-choice', question_id: 'mc1', prompt: 'Which?', direction: 'forward',

  answers: [{id: 'a', text: 'Alpha'}, {id: 'b', text: 'Beta'}, {id: 'c', text: 'Gamma'}, {id: 'd', text: 'Delta'}],

  attempts: [{correct: false, selected_answer_id: 'a'}], completed: false,

  result: {correct: false, completed: false, selected_answer_id: 'a'}};

sidebar.state = {...sessionState, quiz_type: 'multiple-choice', question: mc};

(view as any).render();

const choices = [...view.contentEl.querySelectorAll<HTMLButtonElement>('.mq-choices button')];

assert.equal(choices[0].disabled, true); assert.equal(choices[1].disabled, false);

assert.ok(choices[0].classList.contains('mq-wrong'));

view.noteChanged(); assert.equal(sidebar.state.question.question_id, 'mc1');

mc.completed = true; mc.result = {correct: true, completed: true, correct_answer_id: 'b', explanation: 'Beta is correct.'};

(view as any).render();

assert.ok(view.contentEl.textContent?.includes('Next question in 5'));

assert.ok(view.contentEl.querySelector('.mq-correct')?.textContent?.includes('Beta'));

assert.ok([...view.contentEl.querySelectorAll('button')].some(b => b.textContent === 'Next now'));

fake.api.quiz = async (action: string) => { calls++; assert.equal(action, 'next'); return {...sessionState, question: null, complete: true}; };

await new Promise(resolve => setTimeout(resolve, 5300));

assert.equal(sidebar.state.complete, true, 'Countdown advances automatically');

await view.onClose();

assert.equal(sidebar.state.complete, true);

for (const c of controllers.values()) c.dispose();

console.log('Frontend checks passed: shared sessions, protected multiblank editor, retries, countdown, filters, radio selection, state retention, syntax tokens, and unchanged Markdown.');



// Every request binds to the current Obsidian vault, never the server default.

const requests: any[] = [];

(globalThis as any).__quizRequest = async (options: any) => {

  requests.push(options);

  const value = options.url.endsWith('/vault/connect') ? {vault_id: 'active-vault', vault_path: 'C:/My Obsidian Vault'}

    : {tags: ['Python']};

  return {status: 200, text: JSON.stringify(value)};

};

const client = new QuizClient(() => ({backendUrl: 'http://127.0.0.1:8765', timeoutSeconds: 10}) as never,

  () => '', () => 'C:/My Obsidian Vault');

await Promise.all([client.tags(), client.tags()]);

assert.equal(requests.filter(r => r.url.endsWith('/vault/connect')).length, 1);

assert.equal(JSON.parse(requests[0].body).vault_path, 'C:/My Obsidian Vault');

assert.equal(requests[1].headers['X-Quiz-Vault'], 'active-vault');

client.resetConnection();

await client.tags();

assert.equal(requests.filter(r => r.url.endsWith('/vault/connect')).length, 2);

const remote = new QuizClient(() => ({timeoutSeconds: 10, connectionMode: 'server', vaultKey: 'private-id', backendUrl: 'https://quiz.example.test'}) as never, () => 'secret', () => 'C:/Vault');
requests.length = 0;
await remote.tags();
assert.deepEqual(JSON.parse(requests[0].body), {vault_key: 'private-id'});
assert.equal(requests[1].headers.Authorization, 'Bearer secret');
const insecure = new QuizClient(() => ({timeoutSeconds: 10, connectionMode: 'server', backendUrl: 'http://remote.example.test'}) as never, () => 'secret');
await assert.rejects(() => insecure.tags(), /HTTPS/);
const unauthenticated = new QuizClient(() => ({timeoutSeconds: 10, connectionMode: 'server', backendUrl: 'https://quiz.example.test'}) as never);
await assert.rejects(() => unauthenticated.tags(), /token/);
const {backendIsOlder} = await import('../src/backend/version');
assert.equal(backendIsOlder('1.2.0', '1.3.0'), true);
assert.equal(backendIsOlder('1.3.0', '1.3.0'), false);
assert.equal(backendIsOlder('1.10.0', '1.3.0'), false);
assert.throws(() => backendIsOlder('garbage', '1.3.0'));
delete (globalThis as any).__quizRequest;

console.log('Vault connection and request isolation checks passed.');


const {renderCoding} = await import('../src/views/questionRenderers');
const inputHost = document.createElement('div'); document.body.append(inputHost);
const inputCalls: any[] = [];
const inputController: any = {busy: false, state: {question: {...coding, needs_input: true, stdin_text: ''}},
  draft: () => {}, answer: () => {}, perform: async (action: string, payload: unknown) => { inputCalls.push({action, payload}); }};
const inputDispose = renderCoding(inputHost, inputController);
const programInput = inputHost.querySelector<HTMLTextAreaElement>('[aria-label="Program input"]')!;
assert.equal(programInput.disabled, false);
programInput.value = '5\n4'; programInput.dispatchEvent(new Event('input'));
assert.equal([...inputHost.querySelectorAll('button')].find(b => b.textContent === 'Run answer')!.disabled, true);
[...inputHost.querySelectorAll('button')].find(b => b.textContent === 'Apply program input')!.click();
const difficultySelect = inputHost.querySelector<HTMLSelectElement>('[aria-label="Coding difficulty"]')!;
difficultySelect.value = 'hard'; difficultySelect.dispatchEvent(new Event('change'));
assert.deepEqual(inputCalls, [{action: 'input', payload: {stdin_text: '5\n4'}}, {action: 'difficulty', payload: {difficulty: 'hard'}}]);
inputDispose(); inputHost.remove();
console.log('In-question program input and difficulty controls passed.');

const {renderModelPicker} = await import('../src/settings/modelPicker');
const modelHost = document.createElement('div');
const modelCalls: any[] = [];
const modelPlugin: any = {settings: {ollamaModel: 'alpha'}, saveSettings: async () => {},
  api: {call: async () => ({models: ['alpha', 'beta', 'beta']})}};
const modelController: any = {busy: false, state: {question: {type: 'multiple-choice'}},
  perform: async (action: string, payload: unknown) => { modelCalls.push({action, payload}); }};
renderModelPicker(modelHost, modelPlugin, modelController);
await new Promise(resolve => setTimeout(resolve, 0));
const modelSelect = modelHost.querySelector<HTMLSelectElement>('[aria-label="Multiple Choice model"]')!;
assert.equal(modelSelect.options.length, 2);
modelSelect.value = 'beta'; modelSelect.dispatchEvent(new Event('change'));
assert.equal(modelPlugin.settings.quizModels['multiple-choice'], 'beta');
assert.equal(modelPlugin.settings.ollamaModel, 'alpha');
[...modelHost.querySelectorAll('button')].find(b => b.textContent === 'Regenerate question')!.click();
await new Promise(resolve => setTimeout(resolve, 0));
assert.deepEqual(modelCalls, [{action: 'regenerate', payload: {model: 'beta'}}]);
const offlineHost = document.createElement('div');
modelPlugin.api.call = async () => { throw new Error('Ollama offline'); };
modelController.state.question.type = 'coding';
renderModelPicker(offlineHost, modelPlugin, modelController);
await new Promise(resolve => setTimeout(resolve, 0));
assert.equal([...offlineHost.querySelectorAll('button')].find(b => b.textContent === 'Regenerate question')!.disabled, false);
console.log('Installed model selection, regeneration payload, and offline coding checks passed.');

const {modelFor, setModelFor} = await import('../src/settings/modelPicker');
assert.equal(modelFor(modelPlugin.settings, 'coding'), 'alpha', 'Old shared preference seeds untouched types');
setModelFor(modelPlugin.settings, 'coding', 'code-model');
assert.equal(modelFor(modelPlugin.settings, 'multiple-choice'), 'beta');
assert.equal(modelFor(modelPlugin.settings, 'coding'), 'code-model');
const persistedModels = JSON.parse(JSON.stringify(modelPlugin.settings));
assert.equal(modelFor(persistedModels, 'coding'), 'code-model');
// Inline coding must use its actual question type even when sidebar is MC.
modelPlugin.settings.quizType = 'multiple-choice';
modelPlugin.api.call = async () => ({models: ['beta', 'code-model']});
const separateHost = document.createElement('div');
renderModelPicker(separateHost, modelPlugin, modelController);
await new Promise(resolve => setTimeout(resolve, 0));
assert.equal(separateHost.querySelector('select')!.value, 'code-model');
assert.equal(separateHost.querySelector('select')!.getAttribute('aria-label'), 'Coding model');
console.log('Separate model preferences, legacy migration, persistence, and inline type isolation passed.');

const {renderLibrarySettings} = await import('../src/settings/librarySettings');
const libraryHost = document.createElement('div');
const libraryCalls: any[] = [];
const libraryPlugin: any = {settings: {pythonImports: ''}, saveSettings: async () => {}, api: {
  call: async (path: string, body?: any) => { libraryCalls.push({path, body}); return {packages: body?.packages ?? 'numpy'}; }
}};
renderLibrarySettings(libraryHost, libraryPlugin);
await new Promise(resolve => setTimeout(resolve, 0));
const searchLibraries = libraryHost.querySelector<HTMLInputElement>('[aria-label="Search Python libraries"]')!;
assert.equal(libraryHost.querySelector<HTMLInputElement>('[aria-label="Enable numpy"]')!.checked, true);
searchLibraries.value = 'pandas'; searchLibraries.dispatchEvent(new Event('input'));
assert.equal(libraryHost.querySelectorAll('.mq-library-row').length, 1);
libraryHost.querySelector<HTMLButtonElement>('[aria-label="Add pandas"]')!.click();
await new Promise(resolve => setTimeout(resolve, 0));
assert.deepEqual(libraryCalls.at(-1), {path: '/libraries', body: {packages: 'numpy pandas'}});
libraryHost.querySelector<HTMLInputElement>('[aria-label="Enable pandas"]')!.dispatchEvent(new Event('change'));
await new Promise(resolve => setTimeout(resolve, 0));
assert.deepEqual(libraryPlugin.settings.disabledLibraries, ['pandas']);
assert.equal(libraryCalls.at(-1).body.packages, 'numpy');
libraryHost.querySelector<HTMLButtonElement>('[aria-label="Remove pandas"]')!.click();
await new Promise(resolve => setTimeout(resolve, 0));
assert.deepEqual(libraryPlugin.settings.disabledLibraries, []);
searchLibraries.value = 'custom-package==1.0'; searchLibraries.dispatchEvent(new Event('input'));
[...libraryHost.querySelectorAll('button')].find(b => b.textContent === 'Add library')!.click();
await new Promise(resolve => setTimeout(resolve, 0));
assert.equal(libraryCalls.at(-1).body.packages, 'numpy custom-package==1.0');
libraryPlugin.api.call = async () => { throw new Error('Installation failed'); };
searchLibraries.value = 'numpy'; searchLibraries.dispatchEvent(new Event('input'));
libraryHost.querySelector<HTMLInputElement>('[aria-label="Enable numpy"]')!.dispatchEvent(new Event('change'));
await new Promise(resolve => setTimeout(resolve, 0));
assert.equal(libraryHost.querySelector<HTMLInputElement>('[aria-label="Enable numpy"]')!.checked, true);
assert.ok(libraryHost.textContent!.includes('Installation failed'));
const importsField = libraryHost.querySelector<HTMLTextAreaElement>('[aria-label="Additional Python imports"]')!;
importsField.value = 'import numpy as np'; importsField.dispatchEvent(new Event('input'));
assert.equal(libraryPlugin.settings.pythonImports, 'import numpy as np');
console.log('Python package installation and optional import controls passed.');

const errorHost = document.createElement('div'); document.body.append(errorHost);
const errorController = new SessionController(fake, 'error-practice');
errorController.state = {...structuredClone(sessionState), question: null, preparation_error: 'Generation failed'};
let skipAction = '';
errorController.perform = async (action: string) => { skipAction = action; };
const errorPlugin: any = {...fake, session: () => errorController};
const errorDispose = mountPractice(errorPlugin, errorHost, 'note.md', blocks[0]);
await new Promise(resolve => setTimeout(resolve, 30));
const errorSkip = [...errorHost.querySelectorAll('button')].find(b => b.textContent === 'Skip question')!;
assert.ok(errorSkip); assert.equal(errorSkip.disabled, false);
errorSkip.click(); assert.equal(skipAction, 'skip');
assert.ok([...errorHost.querySelectorAll('button')].some(b => b.textContent === 'Retry question'));
errorDispose();
console.log('Failed question exposes Skip and Retry without a rendered question.');

const recoveryCalls: any[] = [];
const recoveryPlugin: any = {...fake, api: {quiz: async (action: string, payload: any) => {
  recoveryCalls.push({action, payload});
  if (action === 'next') throw new Error('Source Python syntax error: invalid character');
  if (action === 'resume') return {...structuredClone(sessionState), question: null, index: 1, total: 3, complete: true};
  return {...structuredClone(sessionState), question: {...coding, question_id: 'third'}, index: 2, total: 3};
}}};
const recovery = new SessionController(recoveryPlugin, 'recovery');
recovery.state = {...structuredClone(sessionState), total: 3};
await recovery.perform('next');
assert.equal(recovery.state!.index, 1);
assert.equal(recovery.state!.complete, false);
await recovery.perform('skip');
assert.equal(recoveryCalls.at(-1).payload.index, 1);
assert.equal(recoveryCalls.at(-1).payload.question_id, undefined);
assert.equal(recovery.state!.question!.question_id, 'third');
console.log('Skipping after failed advance uses the failed second position and reaches question three.');

const {renderApiSettings, renderResetControls} = await import('../src/settings/serviceSettings');
const apiHost = document.createElement('div');
const apiPlugin: any = {settings: {generationProvider: 'api', apiUrl: 'https://provider.test/v1', apiModel: 'test-model', quizType: 'multiple-choice', sessionIds: {}, ollamaModel: 'alpha'}, generationApiKey: '', saveSettings: async () => {}};
renderApiSettings(apiHost, apiPlugin);
const apiKeyInput = apiHost.querySelector<HTMLInputElement>('[aria-label="API key"]')!;
assert.equal(apiKeyInput.type, 'password');
apiKeyInput.value = 'test-secret'; apiKeyInput.dispatchEvent(new Event('input'));
assert.equal(apiPlugin.generationApiKey, 'test-secret');
assert.ok(!JSON.stringify(apiPlugin.settings).includes('test-secret'));
const apiRequests: any[] = [];
apiPlugin.api = {quiz: async (action: string, body: any) => { apiRequests.push(body); return structuredClone(sessionState); }, call: async () => { throw new Error('Ollama offline'); }};
const apiSession = new SessionController(apiPlugin, 'api-test');
await apiSession.perform('start', {quiz_type: 'multiple-choice'});
assert.equal(apiRequests[0].provider, 'api');
assert.equal(apiRequests[0].api_key, 'test-secret');
await apiSession.perform('next');
assert.equal(apiRequests[1].api_key, 'test-secret');
assert.equal(apiRequests[1].provider, undefined);
const apiPicker = document.createElement('div');
renderModelPicker(apiPicker, apiPlugin, apiSession);
await new Promise(resolve => setTimeout(resolve, 0));
assert.equal([...apiPicker.querySelectorAll('button')].find(b => b.textContent === 'Regenerate question')!.disabled, false);
[...apiHost.querySelectorAll('button')].find(b => b.textContent === 'Clear API key')!.click();
assert.equal(apiPlugin.generationApiKey, '');
const resetHost = document.createElement('div');
const resets: string[] = [];
apiPlugin.resetServer = async () => { resets.push('server'); };
apiPlugin.api.call = async (_: string, body: any) => { resets.push(body.target); return {message: 'Reset complete'}; };
renderResetControls(resetHost, apiPlugin);
for (const button of resetHost.querySelectorAll('button')) { button.click(); await new Promise(resolve => setTimeout(resolve, 0)); }
assert.deepEqual(resets, ['server', 'sandbox', 'ollama']);
console.log('API controls, in-memory key, offline API regeneration, session credentials, and reset buttons passed.');

// Both quiz surfaces use the same recovery controls, including busy-state rules.
const {renderSessionError} = await import('../src/views/questionRenderers');
const sharedErrorHost = document.createElement('div');
const sharedActions: string[] = [];
const sharedController = new SessionController(fake, 'shared-errors');
sharedController.state = {...structuredClone(sessionState), question: null, preparation_error: 'Cannot prepare question'};
sharedController.perform = async action => { sharedActions.push(action); };
assert.equal(renderSessionError(sharedErrorHost, sharedController), 'Cannot prepare question');
assert.equal(sharedErrorHost.querySelectorAll('[role=alert]').length, 1);
for (const button of sharedErrorHost.querySelectorAll('button')) button.click();
assert.deepEqual(sharedActions, ['skip', 'retry']);
sharedErrorHost.empty(); sharedController.busy = true;
renderSessionError(sharedErrorHost, sharedController);
assert.ok([...sharedErrorHost.querySelectorAll('button')].every(button => button.disabled));
sharedErrorHost.empty(); sharedController.busy = false;
renderSessionError(sharedErrorHost, sharedController, '', true);
assert.ok([...sharedErrorHost.querySelectorAll('button')].every(button => button.disabled), 'A connecting sidebar also disables recovery');
sharedErrorHost.empty(); sharedController.busy = false; sharedController.state = null;
renderSessionError(sharedErrorHost, sharedController, 'Connection failed');
assert.equal(sharedErrorHost.textContent, 'Connection failed');
assert.equal(sharedErrorHost.querySelectorAll('button').length, 0);
sharedController.dispose();

// A failed answer retransmits the same request ID; a different answer gets a new ID.
const attemptRequests: Record<string, unknown>[] = [];
let failAttempt = true;
const attemptPlugin: any = {...fake, api: {quiz: async (_action: string, payload: Record<string, unknown>) => {
  attemptRequests.push(payload);
  if (failAttempt) { failAttempt = false; throw new Error('Connection lost'); }
  return structuredClone(sessionState);
}}};
const attemptController = new SessionController(attemptPlugin, 'attempt-retry');
attemptController.state = structuredClone(sessionState);
await attemptController.answer({answers: {blank_1: '1', blank_2: '1'}});
await attemptController.answer({answers: {blank_1: '1', blank_2: '1'}});
await attemptController.answer({answers: {blank_1: '2', blank_2: '1'}});
assert.equal(attemptRequests[0].request_id, attemptRequests[1].request_id);
assert.notEqual(attemptRequests[1].request_id, attemptRequests[2].request_id);
attemptController.dispose();
console.log('Shared recovery controls and idempotent answer retry checks passed.');
