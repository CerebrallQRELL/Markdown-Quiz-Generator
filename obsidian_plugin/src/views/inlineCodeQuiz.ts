/** Reading-view and Live Preview placement of shared coding practice controls. */
import { renderRegeneration } from '../settings/modelPicker';
import { MarkdownRenderChild, TFile, editorInfoField, editorLivePreviewField } from 'obsidian';
import { StateEffect, StateField, type EditorState, type Extension } from '@codemirror/state';
import { Decoration, type DecorationSet, EditorView, WidgetType } from '@codemirror/view';
import type QuizPlugin from '../main';
import { errorMessage } from '../backend/api';
import { codeHash, findBlocks, normalizeCode } from './blocks';
import type { CodeBlock, Difficulty } from '../types';
import type { SessionController } from '../quiz/session';
import { renderCoding, renderSessionError } from './questionRenderers';
import { selection } from '../quiz/filters';

export const refreshWidgets = StateEffect.define<null>();
const disposers = new WeakMap<HTMLElement, () => void>();

export function mountPractice(plugin: QuizPlugin, host: HTMLElement, source: string, block: CodeBlock): () => void {
  host.addClass('mq-inline');
  let disposed = false;
  let controller: SessionController | undefined;
  let unsubscribe: (() => void) | undefined;
  let editorDispose: (() => void) | undefined;
  let difficulty = plugin.settings.difficulty;
  let localError = '';
  const details = host.createEl('details');
  details.createEl('summary', {text: 'Practice this code'});
  const body = details.createDiv({cls: 'mq-practice'});
  const ready = codeHash(block.code).then(hash => {
    controller = plugin.session(`inline:${source}:${block.occurrence}:${hash}`);
    if (!disposed) { unsubscribe = controller.subscribe(render); render(); }
    return {controller, hash};
  });
  const start = async () => {
    const {controller, hash} = await ready;
    await controller.start({...selection(plugin), quiz_type: 'coding', source_file: source, code_hash: hash,
      occurrence: block.occurrence, tags: [], exclude_tags: [], date_from: '', date_to: '', due_only: false,
      direction: 'random', length: 1, difficulty});
  };
  details.addEventListener('toggle', () => {
    if (details.open) void ready.then(({controller}) => controller.restore());
  });
  function render() {
    if (disposed) return;
    editorDispose?.(); body.empty();
    if (controller?.state?.notice) body.createEl('p', {text: controller.state.notice, attr: {role: 'status'}});
    const button = (text: string, action: () => void) => {
      const element = body.createEl('button', {text}); element.disabled = !!controller?.busy;
      element.addEventListener('click', action); return element;
    };
    if (controller?.busy) body.createEl('p', {text: 'Working…', attr: {role: 'status'}});
    const error = controller ? renderSessionError(body, controller, localError) : localError;
    if (error) {
      if (error.includes('not available')) button('Start backend', () => void plugin.startBackend()
        .then(() => { localError = ''; render(); }).catch(error => { localError = errorMessage(error); render(); }));
    }
    if (controller?.state?.question?.type === 'coding') {
      editorDispose = renderCoding(body, controller);
      if (!error && !controller.state.question.completed) button('Skip question', () => void controller!.perform('skip'));
      renderRegeneration(body, plugin, controller);
      button('Start over', () => controller!.reset());
      return;
    }
    if (controller?.state?.preparation_error) { button('Start over', () => void controller!.reset()); return; }
    const label = body.createEl('label', {cls: 'mq-field'}); label.createSpan({text: 'Difficulty'});
    const select = label.createEl('select');
    for (const value of ['easy', 'medium', 'hard']) select.createEl('option', {value, text: value});
    select.value = difficulty; select.disabled = !!controller?.busy;
    select.addEventListener('change', () => { difficulty = select.value as Difficulty; });
    button('Start practice', () => void start());
  }
  render();
  const dispose = () => { disposed = true; unsubscribe?.(); editorDispose?.(); host.remove(); plugin.inlineDisposers.delete(dispose); };
  plugin.inlineDisposers.add(dispose);
  return dispose;
}


class ReadingPractice extends MarkdownRenderChild {
  private dispose?: () => void;
  constructor(container: HTMLElement, private plugin: QuizPlugin, private source: string, private block: CodeBlock) { super(container); }
  onload() { this.dispose = mountPractice(this.plugin, this.containerEl, this.source, this.block); }
  onunload() { this.dispose?.(); }
}

export function registerReadingWidgets(plugin: QuizPlugin) {
  plugin.registerMarkdownPostProcessor(async (element, context) => {
    if (!plugin.settings.inline || !plugin.settings.reading || !plugin.active) return;
    const codes = [...element.querySelectorAll<HTMLElement>('pre > code.language-python, pre > code.language-py')];
    if (!codes.length) return;
    const file = plugin.app.vault.getAbstractFileByPath(context.sourcePath);
    if (!(file instanceof TFile)) return;
    const blocks = await plugin.blocksFor(file);
    if (!plugin.active || !plugin.settings.inline || !plugin.settings.reading) return;
    for (const code of codes) {
      const pre = code.parentElement;
      if (!pre || pre.closest('.mq-inline, .markdown-source-view') || pre.nextElementSibling?.classList.contains('mq-inline')) continue;
      const section = context.getSectionInfo(pre);
      const matching = blocks.filter(block => normalizeCode(code.textContent ?? '') === block.code
        && (!section || (block.startLine >= section.lineStart && block.endLine <= section.lineEnd)));
      // Never guess which duplicate block to use when the renderer provides no location.
      const already = new Set<number>();
      for (const sibling of element.querySelectorAll<HTMLElement>('.mq-inline')) {
        const line = sibling.dataset.sourceLine; if (line !== undefined) already.add(Number(line));
      }
      const block = matching.find(item => !already.has(item.startLine));
      if (!block || (!section && matching.length > 1)) continue;
      const host = pre.ownerDocument.createElement('div');
      host.dataset.sourceLine = String(block.startLine);
      pre.after(host);
      context.addChild(new ReadingPractice(host, plugin, context.sourcePath, block));
    }
  });
}

class PracticeWidget extends WidgetType {
  constructor(private plugin: QuizPlugin, private source: string, private block: CodeBlock, private revision: number) { super(); }
  eq(other: PracticeWidget) {
    return other.source === this.source && other.block.code === this.block.code
      && other.block.occurrence === this.block.occurrence && other.revision === this.revision;
  }
  toDOM(view: EditorView) {
    const host = view.dom.ownerDocument.createElement('div');
    const dispose = mountPractice(this.plugin, host, this.source, this.block);
    const observer = new ResizeObserver(() => view.requestMeasure());
    observer.observe(host);
    disposers.set(host, () => { observer.disconnect(); dispose(); });
    return host;
  }
  destroy(dom: HTMLElement) { disposers.get(dom)?.(); disposers.delete(dom); }
  ignoreEvent() { return true; }
}

export function livePreviewExtension(plugin: QuizPlugin): Extension {
  const build = (state: EditorState): DecorationSet => {
    if (!plugin.active || !plugin.settings.inline || !plugin.settings.livePreview || !state.field(editorLivePreviewField, false)) return Decoration.none;
    const source = state.field(editorInfoField, false)?.file?.path;
    if (!source) return Decoration.none;
    const blocks = findBlocks(state.doc.toString());
    return Decoration.set(blocks.map(block => Decoration.widget({widget: new PracticeWidget(plugin, source, block, plugin.widgetRevision),
      side: 1, block: true}).range(block.to)), true);
  };
  return StateField.define<DecorationSet>({
    create: build,
    update(value, transaction) {
      const before = transaction.startState.field(editorInfoField, false)?.file?.path;
      const after = transaction.state.field(editorInfoField, false)?.file?.path;
      if (transaction.docChanged || before !== after || transaction.effects.some(effect => effect.is(refreshWidgets))
          || transaction.startState.field(editorLivePreviewField, false) !== transaction.state.field(editorLivePreviewField, false)) return build(transaction.state);
      return value;
    },
    provide: field => EditorView.decorations.from(field)
  });
}
