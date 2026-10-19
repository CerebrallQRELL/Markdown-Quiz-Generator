import { loadPrism } from 'obsidian';
import type { CodingQuestion } from '../types';

/** Only blank values are mutable. Protected code is never an editable document. */
class BlankModel {
  readonly template: string;
  readonly blanks: ReadonlyArray<Readonly<{id: string; marker: string}>>;
  private values: Record<string, string>;
  constructor(question: CodingQuestion) {
    this.template = question.blank_code;
    this.blanks = Object.freeze(question.blanks.map(b => Object.freeze({id: b.id, marker: b.marker})));
    this.values = Object.fromEntries(this.blanks.map(b => [b.id, question.draft[b.id] ?? '']));
    Object.defineProperty(this, 'template', {writable: false});
  }
  set(id: string, value: string) { if (!this.blanks.some(b => b.id === id)) throw new Error('Protected code cannot be edited.'); this.values[id] = value; }
  answers() { return {...this.values}; }
}

// Render Prism tokens with text nodes, never untrusted HTML.
function tokens(parent: HTMLElement, values: any) {
  if (typeof values === 'string') { parent.append(document.createTextNode(values)); return; }
  if (Array.isArray(values)) { for (const token of values) tokens(parent, token); return; }
  const span = parent.createSpan({cls: `token ${values.type}`}); tokens(span, values.content);
}

export function mountBlankEditor(host: HTMLElement, question: CodingQuestion, change: (answers: Record<string, string>) => void,
  run: () => void, disabled = false) {
  const model = new BlankModel(question);
  const code = host.createEl('div', {cls: 'mq-code-editor', attr: {role: 'group', 'aria-label': 'Python code with editable blanks'}});
  const inputs: HTMLTextAreaElement[] = [];
  let disposed = false;
  const highlight = (element: HTMLElement, text: string) => {
    element.textContent = text;
    void loadPrism().then(prism => {
      if (disposed || element.textContent !== text || !prism.languages.python) return;
      element.empty(); tokens(element, prism.tokenize(text, prism.languages.python));
    });
  };
  const markerPattern = /<BLANK_\d+>/g;
  let cursor = 0;
  for (const match of question.blank_code.matchAll(markerPattern)) {
    const blank = question.blanks.find(b => b.marker === match[0]);
    if (!blank) continue;
    const protectedPart = code.createSpan({cls: 'mq-protected'});
    highlight(protectedPart, question.blank_code.slice(cursor, match.index));
    const wrap = code.createSpan({cls: 'mq-code-blank'});
    const paint = wrap.createSpan({cls: 'mq-blank-highlight', attr: {'aria-hidden': 'true'}});
    const input = wrap.createEl('textarea', {attr: {rows: '1', spellcheck: 'false', 'aria-label': `Editable ${blank.id.replace('_', ' ')}`}});
    input.value = model.answers()[blank.id]; input.disabled = disabled; input.wrap = 'off';
    const resize = () => {
      const lines = input.value.split('\n');
      wrap.style.width = `${Math.max(6, ...lines.map(line => line.length + 1))}ch`;
      wrap.style.height = `${Math.max(1, lines.length) * 1.6}em`;
      highlight(paint, input.value || ' ');
    };
    input.addEventListener('input', () => { model.set(blank.id, input.value); wrap.classList.remove('mq-wrong', 'mq-correct'); resize(); change(model.answers()); });
    input.addEventListener('keydown', event => {
      if (event.key === 'Tab') {
        event.preventDefault(); event.stopPropagation();
        const index = inputs.indexOf(input);
        inputs[(index + (event.shiftKey ? -1 : 1) + inputs.length) % inputs.length]?.focus();
      } else if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault(); event.stopPropagation(); run();
      } else if (event.key === 'Enter') {
        event.preventDefault();
        const line = input.value.slice(0, input.selectionStart).split('\n').pop() ?? '';
        const indent = /^\s*/.exec(line)?.[0] ?? '';
        input.setRangeText('\n' + indent + (line.trimEnd().endsWith(':') ? '    ' : ''), input.selectionStart, input.selectionEnd, 'end');
        input.dispatchEvent(new Event('input'));
      }
    });
    // Each blank is a separate native editing surface. Selection, paste, delete,
    // backspace and undo cannot cross into protected text or another blank.
    if (question.result && question.result.status !== 'sandbox_failure') wrap.classList.add(question.result.correct ? 'mq-correct' : 'mq-wrong');
    inputs.push(input); resize(); cursor = match.index! + match[0].length;
  }
  highlight(code.createSpan({cls: 'mq-protected'}), question.blank_code.slice(cursor));
  return {model, inputs, dispose: () => { disposed = true; code.remove(); }};
}
