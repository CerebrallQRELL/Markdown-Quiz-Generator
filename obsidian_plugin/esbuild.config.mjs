import esbuild from 'esbuild';
const options = {
  entryPoints: ['src/main.ts'], bundle: true, external: ['node:child_process', 'node:path', 'obsidian', '@codemirror/state', '@codemirror/view'],
  format: 'cjs', target: 'es2022', platform: 'browser', outfile: 'main.js',
  banner: {js: '/* Markdown Quiz Generator — generated from TypeScript source. */'},
  logLevel: 'info'
};
if (process.argv.includes('--watch')) {
  const context = await esbuild.context(options);
  await context.watch();
} else await esbuild.build(options);
