import { StateField } from '@codemirror/state';
export const editorInfoField = StateField.define({create: () => ({file: {path: 'note.md'}}), update: value => value});
export const editorLivePreviewField = StateField.define({create: () => true, update: value => value});
export class TFile {}
export class MarkdownRenderChild { constructor(public containerEl: HTMLElement) {} }
export function requestUrl(options: unknown): unknown {
  const handler = (globalThis as any).__quizRequest;
  if (handler) return handler(options);
  throw new Error('HTTP is mocked in UI tests');
}

export async function loadPrism() { return {languages: {python: {}}, tokenize: (text: string) => [{type: 'keyword', content: text}]}; }
export class ItemView {
  contentEl = document.createElement('div'); app: any;
  constructor(public leaf: any) { this.app = leaf.app; }
  registerDomEvent(el: HTMLElement, type: string, callback: EventListener) { el.addEventListener(type, callback); }
}
