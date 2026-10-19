# Obsidian Markdown Quiz Generator

Source for the sidebar and inline practice UI. Python remains the authority for
parsing, generation, scheduling, persistence, and sandboxed execution.

The installable folder is `../plugin/markdown-quiz-generator`.
See [Obsidian setup](../docs/OBSIDIAN_SETUP.md) for installation, configuration,
API details, and GitHub packaging.

Build with `pnpm install --frozen-lockfile` and `pnpm build` using Node 24+ and
pnpm 11.25.0. Run `pnpm test` for frontend checks. Output is CommonJS `main.js`;
Obsidian and CodeMirror are host-provided external dependencies.

`src/main.ts` registers lifecycle/events; `src/types.ts` centralizes shared types.
Related source files are grouped into:

- `src/backend/`: HTTP communication and backend version checks.
- `src/quiz/`: session state and selection filters.
- `src/views/`: sidebar, inline practice, question rendering and editable blanks.
- `src/settings/`: preferences, model selection, libraries and service controls.

Quiz business logic remains in Python.
