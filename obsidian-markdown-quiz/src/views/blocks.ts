import type { CodeBlock } from '../types';

// Locate fences for UI placement only. Python remains the source parser.
export function normalizeCode(code: string): string {
  return code.replace(/\r\n?/g, '\n').split('\n').map(line => line.replace(/\s+$/u, '')).join('\n').replace(/^\n+|\n+$/g, '');
}

export function findBlocks(text: string): CodeBlock[] {
  const blocks: CodeBlock[] = [];
  const lines = text.split('\n');
  const occurrences = new Map<string, number>();
  let fence = '', language = '', startLine = 0, start = 0, offset = 0;
  let code: string[] = [];
  for (let index = 0; index < lines.length; index++) {
    const raw = lines[index];
    const line = raw.trim();
    if (fence) {
      const close = new RegExp(`^${fence[0]}{${fence.length},}\\s*$`);
      if (close.test(line)) {
        const normalized = normalizeCode(code.join('\n'));
        if (['python', 'py'].includes(language) && normalized) {
          const occurrence = (occurrences.get(normalized) ?? 0) + 1;
          occurrences.set(normalized, occurrence);
          blocks.push({code: normalized, occurrence, from: start, to: offset + raw.length, startLine, endLine: index});
        }
        fence = ''; code = [];
      } else code.push(raw);
    } else {
      const match = /^(`{3,}|~{3,})\s*([^\s`]*)[^`]*$/.exec(line);
      if (match) { fence = match[1]; language = match[2].toLowerCase(); startLine = index; start = offset; }
    }
    offset += raw.length + 1;
  }
  return blocks;
}

export async function codeHash(code: string): Promise<string> {
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(normalizeCode(code)));
  return [...new Uint8Array(hash)].map(value => value.toString(16).padStart(2, '0')).join('');
}
