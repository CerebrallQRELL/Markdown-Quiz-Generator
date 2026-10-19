import { build } from 'esbuild';
import { Window } from 'happy-dom';
import { pathToFileURL } from 'node:url';
import { mkdtemp, rm } from 'node:fs/promises';
import path from 'node:path';

const window = new Window();
for (const key of ['window', 'document', 'HTMLElement', 'Element', 'Node', 'Event', 'KeyboardEvent', 'MutationObserver', 'ResizeObserver']) {
  globalThis[key] = key === 'window' ? window : window[key];
}
function make(tag, options = {}) {
  const el = this.ownerDocument.createElement(tag);
  if (options.text !== undefined) el.textContent = options.text;
  if (options.cls) el.className = options.cls;
  for (const [key, value] of Object.entries(options.attr ?? {})) el.setAttribute(key, value);
  for (const key of ['type', 'value', 'placeholder']) if (options[key] !== undefined) el[key] = options[key];
  this.append(el); return el;
}
window.HTMLElement.prototype.createEl = make;
window.HTMLElement.prototype.createDiv = function (opts) { return make.call(this, 'div', opts); };
window.HTMLElement.prototype.createSpan = function (opts) { return make.call(this, 'span', opts); };
window.HTMLElement.prototype.empty = function () { this.replaceChildren(); };
window.HTMLElement.prototype.addClass = function (...names) { this.classList.add(...names); };

const folder = await mkdtemp(path.join(process.cwd(), 'tests', '.build-'));
try {
  const outfile = path.join(folder, 'tests.mjs');
  await build({entryPoints: ['tests/ui.ts'], bundle: true, platform: 'node', format: 'esm', target: 'node22', outfile,
    alias: {obsidian: path.resolve('tests/obsidian-stub.ts')}});
  await import(pathToFileURL(outfile).href);
} finally {
  if (path.dirname(path.resolve(folder)) !== path.resolve('tests')) throw new Error('Unexpected test output folder');
  await rm(folder, {recursive: true, force: true});
  await window.happyDOM.close();
}
