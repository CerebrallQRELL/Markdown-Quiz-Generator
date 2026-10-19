# Refactor review

The later folder organization and unused-code cleanup sections supersede the flat
paths and retained engine aliases in the original analysis. The current directory
map is in `ARCHITECTURE.md`.

## Before editing

Reviewed the canonical Python package, all TypeScript source and tests, launchers,
configuration, documentation, packaging, CI and deployment scripts. Generated
bundles and runtime JSON are outputs, not separate implementations. This checkout
has no Git metadata; `../quiz-refactor-before.zip` preserves the original source.

Baseline: 91 Python tests, 84 passed and 7 Docker tests skipped by default;
frontend checks and TypeScript/build passed. Docker integration baseline is also
run explicitly with `RUN_DOCKER_TESTS=1`.

## Original flow map and findings

| Flow | Original path | Finding / decision |
| --- | --- | --- |
| Entry points | root launchers → `main.main` or `api.main`; `__main__` → CLI | Already small launchers; retain commands and working-directory behavior. |
| Markdown | backend rescan → parser scan → parse → storage sync | Extract frontmatter and record shapes; preserve hashes, duplicate occurrences, tag scope and physical line numbers. |
| Quiz selection | API → engine → questions → term tag filter → scheduler | Filters span unrelated generation files; consolidate in `quiz/selection.py`, shared with CLI tag selection. |
| Multiple choice | engine → backend term question → term builder → Ollama/cloud | Move cache reuse into term construction; engine calls builder directly. Preserve backend's documented CLI interface. |
| Coding | engine → questions AST variation/blanks → sandbox | Keep local interactive generation separate from CLI's LLM one-blank generator; their rules are intentionally different. |
| Sessions | engine start/prepare/answer/operate | Already shared by MC and coding. Extract meaningful transitions from the long dispatcher; consolidate invalid-source removal and history metadata. |
| Spaced repetition | engine or CLI → record_answer → review_time/priority | Shared scheduler already small; keep weighted CLI selection and shuffled interactive queues distinct. |
| Storage | backend validates/loads → storage read/write/sync; engine saves sessions | Put record validation with storage; keep atomic writes, corrupt-file refusal and JSON shape. |
| HTTP | handler auth/vault → dispatch → quiz adapter → engine | Keep legacy routes; extract sync/reset operations so routes read as a list of endpoints. |
| Obsidian | plugin → QuizClient → API; SessionController → sidebar/inline renderers | Both surfaces already use one controller. Share recovery/regeneration rendering and make request assembly explicit. |
| Docker | sandbox create → attach → inspect → forced removal | Preserve isolation/resource restrictions, stdin transport and image snapshots; verify with real Docker. |
| LLM | term/CLI coding → ollama.request_json → local or cloud request | Providers have different protocols and credential rules; keep both implementations and validation. |
| Release | TypeScript build → package_release → copied backend/bundles/ZIPs | Regenerate through scripts only; preserve installer and deployment behavior. |

## Compatibility and deletion audit

Tests and README use `QuizBackend` question/answer methods, `QuizAPI` convenience
methods, `sync_terms`, legacy HTTP routes, and old filter import locations. Retain
these supported entry points. Existing filter imports can be direct re-exports
instead of forwarding implementations. Keep saved model migration, source-change
checks and startup migration: they serve existing installations.

No evidence supports removing sandbox restrictions, model providers, CLI quiz
semantics, or release scripts. Do not merge those to reduce file count.

## Stages

1. Define parsed records and filters; consolidate selection and storage validation.
2. Clarify parser stages and move distractor reuse into term construction.
3. Simplify session transitions, attempt recording and HTTP route dispatch.
4. Share frontend recovery controls and clarify session/transport request flow.
5. Run complete tests (including Docker), build, packaged smoke tests; update maps.

## Changes made

- Added `quiz/selection.py` as the single owner of eligibility, tags, dates, sources,
  due-state and explicit-ID filtering. Moved implementations out of `quiz/questions.py`
  and `quiz/term_quiz.py`; retained their original import locations as direct re-exports.
- Moved saved source/cache/history validation from `QuizBackend.__init__` into
  `storage.load_records`. Added named `ParsedTerm`, `ParsedCode`, `ProgressRecord`,
  `QuizFilters` and `SessionState` dictionary shapes without changing JSON formats.
- Extracted `parser.extract_frontmatter`, kept the visible line-based parsing
  pipeline and normalized each extracted term/definition once before hashing.
- Moved cross-note distractor reuse from `backend.term_question` into
  `term_quiz.build_question`. Interactive MC construction now calls the builder
  directly; backend's documented CLI methods still generate and save as before.
- Replaced the long action dispatcher with explicit `advance`,
  `configure_coding_question` and `regenerate_question` operations. Consolidated
  rejected-source removal in `discard_invalid_source` and shared attempt metadata
  in `record_attempt`. Named current-record/public-session operations clearly;
  old Python method names remain direct aliases.
- Extracted API sync/reset operations into methods in the same file. Validated
  rename paths once. Preserved routes, status handling, locks and vault isolation.
- Shared recovery and regeneration UI between sidebar/inline practice. Made
  session request assembly explicit and centralized response/action/answer types.
- Merged `src/models.ts` into `src/modelPicker.ts`; removed the former file and
  unused `QuizClient.stats` convenience method. The `/stats` HTTP endpoint remains.
- Replaced nested result/mastery conditionals with explicit branches. Clarified
  module responsibilities and the source map. Release source ZIPs now include
  this report and `PROJECT_MAP.json` alongside architecture documentation.

## Removed, merged and renamed inventory

**Deleted source file:** `obsidian-markdown-quiz/src/models.ts`.

**Merged:** model preference functions into `modelPicker.ts`; selection functions
from `quiz/questions.py` and `quiz/term_quiz.py` into `quiz/selection.py`; duplicated frontend
recovery/regeneration rendering into `questionRenderers.ts`/`modelPicker.ts`;
shared history metadata and invalid-source removal into engine operations.

**Renamed files:** none. No Python module or stateful class was removed. The
classes own meaningful settings, collections, sessions, connections or UI state.

**Renamed engine operations:** `row` → `find_source_record`, `current` →
`current_question`, `commit` → `record_attempt`, `get` → `get_session`, `public` →
`public_session`, `prepare` → `prepare_question`. Direct aliases keep existing
Python callers compatible. There are no additional forwarding implementations.

Root launchers already contained almost no business logic and were retained.
`sync_terms`, documented backend/API convenience methods and legacy routes remain
because tests, CLI clients or documentation use them.

## Baseline issue corrected

The opt-in Docker baseline ran all 91 original tests and exposed one existing
failure: `pass` was rejected for lacking editable expressions before being
classified as a silent program. The coding preparation fallback now checks output
before surfacing that blank-construction error. Silent code remains silent; it is
never rewritten to print. Normal questions still verify their reconstructed
solutions in Docker. New unit coverage protects both cases. No original Python
test assertions were changed; the frontend's old model-helper import was updated
to its merged location, and additional checks were appended.

## Verification

Final verification passed:

| Check | Result |
| --- | --- |
| `RUN_DOCKER_TESTS=1 python -B -m unittest discover -s tests -v` | **100 tests passed**, including all 7 normally skipped Docker tests; no skips. Final run: 25.281 seconds. Log: `dist/refactor-python-tests.log`. |
| `node node_modules/typescript/bin/tsc --noEmit` in the frontend directory | Passed strict TypeScript checking. |
| `node esbuild.config.mjs` | Plugin build passed. |
| `node tests/run.mjs` | All existing frontend checks and new recovery/request-retry checks passed. |
| Comparison with original source from the backup | 1,000 parser cases returned identical records/IDs/line numbers; 500 filter cases returned identical selections or validation errors. |
| Both Dockerfiles | Current-source CLI and managed-server images built successfully; containerized CLI `--help` passed. |
| `python scripts/smoke_server.py` against the freshly rebuilt helper image | Passed authentication, managed uploads, multiple choice, real Docker coding execution and resume. |
| `python scripts/package_release.py` and `python scripts/smoke_release.py` | Five version 1.3.9 archives regenerated; packaged API verifies MC retries, coding execution, filters, restart/resume and unchanged notes. |

The final package audit verifies all ZIPs, canonical-to-bundled source equality,
generated frontend equality, inclusion of new source/docs/tests and exclusion of
runtime data/caches. Runtime/release version was not changed. No original Python
tests were deleted or weakened; nine regression tests were added.

The high-level source-file count remains 33 (18 Python and 15 TypeScript). This
was not a file-count exercise: the multiple-choice construction path loses one
module, filters have one owner, the session dispatcher shrinks from 79 to 33
lines, and the HTTP dispatcher shrinks from 108 to 46 lines. Both dispatchers
delegate to explicit operations within their existing files.

## Boundaries kept and remaining debt

- CLI and interactive coding generation remain distinct: the CLI creates cached
  one-blank LLM exercises; interactive practice safely varies source programs and
  supports multiple blanks, input and retries. Merging their semantics would
  change established behavior. They share storage, providers and Docker execution.
- Local and remote generation retain separate HTTP implementations because their
  protocols, redirects, authentication and error redaction differ.
- Persisted question/history payloads still contain flexible nested dictionaries.
  Top-level shapes are documented, but exhaustive validation of old session files
  would require a separate schema/migration policy. No new serialization layer
  was introduced.
- Source rescans before preparation/grading remain deliberate stale-source checks.
  JSON is still a one-writer store, with API mutations serialized per vault.
- Legacy routes, Python import locations and startup/model migration remain to
  support current installations. A future removal needs a published compatibility
  policy, rather than guessing that external clients no longer use them.
- Actual Obsidian desktop/theme rendering remains a manual acceptance check.
  Provider protocol/error tests use mocked HTTP; live Ollama generation and paid
  remote-provider calls were not exercised in this refactor.
- The server smoke helper still names its test image `markdown-quiz-server:1.3.0`;
  verification explicitly rebuilds that tag from current source before running it.
  Runtime/release version remains 1.3.9.

See `ARCHITECTURE.md` for the complete source tree, both request flows and the
before/after layer comparison. Generated backend copies and bundles are produced
by the normal scripts; they were never independently refactored.

## Folder organization

Grouped 29 existing files into shallow folders, without adding call layers:

| Folder | Contents |
| --- | --- |
| `markdown_quiz/notes/` | Parser and JSON storage/synchronization. |
| `markdown_quiz/quiz/` | Session engine, selection, multiple-choice/coding construction and review scheduling. |
| `markdown_quiz/services/` | Ollama/cloud clients, Docker execution and optional libraries. |
| `obsidian-markdown-quiz/src/backend/` | HTTP client and version checks. |
| `obsidian-markdown-quiz/src/quiz/` | Session controller and filter controls. |
| `obsidian-markdown-quiz/src/views/` | Sidebar, inline placement, question rendering and protected code blanks. |
| `obsidian-markdown-quiz/src/settings/` | Settings, models, libraries and service controls. |
| `docs/` | Architecture, Obsidian setup, this report and the source map. |

Root launchers, `markdown_quiz.api`, `markdown_quiz.main`, `markdown_quiz.backend`
and `markdown_quiz.config` remain in place. CLI commands and HTTP endpoints are
unchanged. Internal Python/TypeScript imports and test mock targets now use the
new folders directly; no alias registry or forwarding package was introduced.
The three Python subpackage markers contain only a short responsibility docstring.

Packaging now discovers Python and TypeScript source recursively. It removes
obsolete generated Python copies from the former flat layout while preserving
runtime data. A new packaging regression test checks nested source inclusion,
obsolete-file cleanup and unchanged saved bytes. Docker build inclusion rules,
guides, documentation links and `PROJECT_MAP.json` follow the new structure.

Folder-layout verification passed: **101 Python tests**, including every Docker
test with no skips; all frontend checks; strict TypeScript checking and plugin
build; both Docker image builds; packaged-backend and managed-server smoke tests.
The final Python log is `dist/folder-layout-python-tests.log`. Documentation links
and all source-map paths resolve, and the generated backend exactly matches the
canonical nested Python sources. All five release ZIPs are regenerated from the
new layout. Application source moves changed imports rather than application logic.

## Unused-code cleanup

Reviewed the canonical application, tests, launchers, HTTP routes, frontend hooks,
documentation and release scripts before removing candidates. Removed:

- Seven uncalled engine aliases: `row`, `current`, `commit`, `get`, `public`,
  `prepare` and `_prepare`. Their descriptive implementations remain the methods
  used by all current callers.
- The unused `available_tags` import/re-export from `term_quiz.py`. CLI tag
  discovery continues to use `selection.available_tags`.
- An obsolete full-code JSON schema. Only its field names were being read; those
  are now the straightforward `CODE_FIELDS` tuple. The model still receives the
  active program-generation schema.
- The unused frontend `programInput` setting declaration/default. Program input
  continues to use each coding question's `stdin_text` and in-question controls.
  Saved JSON was not edited.
- Unused exports of the internal `BlankModel` class and `masteryText` function;
  both implementations remain in use within their modules.
- Three unused Python test imports, one unused frontend test import and an
  unread sandbox-reset result binding.
- A stale HTTP error special case containing a corrupted string that no current
  error producer emits. Current validation errors still use `APIError`.

Kept tested compatibility filter imports, legacy HTTP routes, CLI launchers,
provider implementations and Obsidian lifecycle hooks: they have current callers
or framework/API entry points. No source module was entirely unused, so no whole
module was deleted. No test assertions were removed or weakened.

Enabled TypeScript `noUnusedLocals` and `noUnusedParameters` in the normal build
configuration. Cleanup verification passed: **101 Python tests** including all
Docker tests with no skips (31.227 seconds; `dist/unused-code-python-tests.log`),
all frontend checks, strict type checking and plugin build, both Docker image
builds, containerized CLI launch and both server/packaged-backend smoke tests.
All five release archives were regenerated through the normal packaging script.
