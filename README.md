## Local setup and server connection (1.3.9)

Use `dist/markdown-quiz-local-1.3.9.zip` for the Windows setup script plus installable plugin, or `dist/markdown-quiz-server-1.3.9.zip` for the Docker Compose backend/Ollama stack. See [deployment instructions](deployment/DEPLOYMENT.md). Server mode uploads Markdown from the active Obsidian vault over HTTPS or an SSH tunnel. Initial runtime/model downloads are required.

# Markdown Quiz Generator

The Obsidian plugin now supports separate Multiple Choice and Coding sessions
through one shared, persisted quiz engine. See [Obsidian setup](docs/OBSIDIAN_SETUP.md)
for version 1.2.0 installation, controls, filters, coding blanks and mastery rules.
The ready-to-copy folder is `plugin/markdown-quiz-generator`; copy its entire
contents, including `backend`, into your Obsidian vault's `.obsidian/plugins`.

The standalone CLI remains available as documented below.

## Project folders

This directory is the Git repository root. Open it when committing or publishing
the current project. The sibling `Coding Quiz Prototype` and
`Multiple Choice Quiz Prototype` folders contain the earlier standalone projects.
Generated downloads in `dist/`, installed plugin copies in `plugin/`, local data,
credentials, logs, and dependencies are excluded from Git. Build the plugin with
`pnpm --dir obsidian_plugin build`, then create downloads with
`python scripts/package_release.py`. GitHub also builds downloads through the
**Build and release** workflow; pushing a version tag publishes release assets.

See the [deployment and AI pipeline diagrams](docs/DIAGRAMS.md) for a visual overview.

- `quiz_backend/notes/`: Markdown parsing and saved records.
- `quiz_backend/quiz/`: selection, questions, sessions and spaced repetition.
- `quiz_backend/services/`: model providers and Docker execution.
- `obsidian_plugin/src/`: `backend/`, `quiz/`, `views/` and `settings/`.
- `docs/`: [architecture and source tree](docs/ARCHITECTURE.md),
  [Obsidian setup](docs/OBSIDIAN_SETUP.md), [refactor notes](docs/REFACTOR_NOTES.md)
  and the machine-readable `PROJECT_MAP.json`.

Root Python files remain launchers so existing commands still work.

## Standalone CLI

**Obsidian integration:** the ready-to-install folder is
`plugin/markdown-quiz-generator`. See [OBSIDIAN_SETUP.md](docs/OBSIDIAN_SETUP.md) for
plugin installation, the local HTTP backend, and GitHub download packaging.

A Python CLI that turns local Markdown notes into two-way multiple-choice term
questions and one-blank Python exercises. Ollama generates questions locally;
Docker executes generated and submitted Python. No cloud API or Python package
dependencies are required. Use Python 3.11 or later.

## Start

Three dedicated programs are available in this folder:

```powershell
python scripts/run_multiple_choice.py
python scripts/run_code_quiz.py
python scripts/reset_json.py
```

The quiz launchers go directly to their quiz and scan Markdown automatically when
their JSON collection is empty. `scripts/reset_json.py` lets you choose term data, code
data, or both. Type `RESET` to confirm clearing generated questions, mastery,
and history. It backs up the selected files in `data/reset-backup-*` first and
preserves settings and Markdown notes. These scripts resolve default paths from
their own project folder, including when launched from another directory.
They also accept `--vault`, `--data`, and `--verbose`.

Open a terminal in this directory:

```powershell
python main.py rescan
python main.py
```

The default vault is `./vault`, which includes a small example. The first command
creates `data/terms.json`, `data/code_quizzes.json`, and `data/settings.json`.
Choose **Term Quiz → All tags → Definition → Term** for an offline demonstration.
This direction needs at least four distinct active terms with different definitions.

To scan your own notes:

```powershell
python main.py --vault "C:\path\to\notes" rescan
python main.py
```

The vault selection persists. Notes are only read. This folder is a standalone
application containing the current backend, CLI, tests, and example vault.
Run `main.py` from this folder. Saved settings and quiz progress live in `data/`.

Before generating questions, start your local Ollama server and download a model:

```powershell
ollama pull qwen3
$env:OLLAMA_MODEL = "qwen3"
$env:OLLAMA_URL = "http://localhost:11434"
```

Code quizzes also need a running Docker engine using Linux containers. Prepare
the default sandbox image once:

```powershell
docker pull python:3.13-alpine
```

Missing services produce an actionable error; the app never executes a program
on the host as a fallback. Ctrl+C or EOF exits cleanly. Previously answered
questions are already saved.

## Markdown rules

```markdown
#Biology #Notes

Mitochondria:: Organelle responsible for ATP production.

**Term:** Ribosome
**Definition:** Structure responsible for protein synthesis.

#Chemistry #Notes
Atom:: A basic unit of a chemical element.
```

Consecutive tag-only lines form one tag group (blank lines are allowed). A new
group after content replaces the previous group. Tags are independent, preserve
their spelling, and filter case-insensitively with OR. `# Biology` is a heading,
not a tag. Inline tags embedded in prose and YAML frontmatter tags are outside
this MVP. `#Topic/Subtopic` is treated as a single literal tag, with no hierarchy.

Closed backtick or tilde fences labeled `python` or `py` become code sources.
Other fenced content is ignored, including apparent terms and tags inside it.
Malformed terms, orphan definition labels, empty files, unsupported languages,
and unclosed code fences are skipped. Invalid UTF-8 files are reported and their
previous stored records remain active until they can be read successfully.

## Studying and managing questions

- Select one or multiple tag numbers, a direction, and a length. Zero means keep
  going until quitting. Random mode chooses either direction when enough real
  terms exist; otherwise it uses term-to-definition.
- Forward questions cache exactly three validated wrong definitions. Reverse
  questions prefer real terms with shared tags, then other real terms. No model
  request is needed for reverse questions.
- Every answer updates mastery, counts, history, last-seen time, and next-review
  time. The intervals are 0, 1, 3, 7, 14, 30, then 60 days. Correct answers add one
  mastery level; incorrect answers subtract two, with a floor of zero.
- Selection uses weights of 20/12/6/3/1 for unseen, due, last-answer-incorrect,
  low-mastery, and other terms. This favors urgent material while occasionally
  reviewing questions that are not due. Term sessions avoid immediate repeats
  when another question is available.
- **View Terms** shows active and inactive records, statistics and mastery, and
  allows manual distractor regeneration or mastery reset. Reset preserves history.
- Code questions use `<BLANK>`. Enter a replacement, `:multi` for multiple lines
  ending in `:end`, `:r` to regenerate, or `:q` to quit. Expected output is shown
  so the task is solvable from the question. Equivalent replacements are accepted
  if they exit successfully and produce exactly the expected stdout.
- Code caches hold one current difficulty per source. Reusing that difficulty
  uses the saved question; changing difficulty creates a fresh variation. All
  old generation hashes remain excluded from future generations. Regeneration
  preserves mastery and history.

## Synchronization and persistence

**Rescan Markdown** synchronizes the complete configured vault. A term's identity
hash uses its relative POSIX file path and normalized term. Formatting and
whitespace changes preserve identity and definition hashes; tags update without
resetting progress. Meaningful definition changes lower mastery by two, make the
term due, invalidate distractors, and automatically request new ones. If Ollama
is unavailable, the invalidation remains saved and generation is retried when
needed. New terms generate distractors lazily.

Deleted records become inactive; returning records recover their history and
caches. Renames and substantial term changes produce new records. Code identity
uses relative path, language, and normalized code. Changed code creates a new
record and deactivates its old version, preserving the old history without
guessing which block it replaced. Moving a file changes its source identities.
Duplicate terms within a file collapse to one record; the last term occurrence
wins. Identical code blocks have separate occurrence IDs. Separate files retain
separate records. The Obsidian bridge preserves history on note rename events;
CLI-only moves without that event still create new identities.

Writes use a temporary file and atomic replacement. Corrupted JSON is reported
without overwriting it; repair it or move it aside explicitly. The MVP supports
one running writer per data directory. An HTTP API should serialize mutations
before introducing concurrent clients. There is no permanent inactive-record
cleanup command yet.

## Settings

Use the CLI's **Settings** menu or `data/settings.json`. Environment variables
override saved values on restart. Relative paths resolve from the working
directory. `--vault` and `--data` override their corresponding environment values.
Change the data directory at startup rather than moving it from the menu.

| Environment variable | Default |
| --- | --- |
| `VAULT_PATH` | `./vault` |
| `DATA_PATH` | `./data` |
| `OLLAMA_URL` | `http://localhost:11434` |
| `OLLAMA_MODEL` | `qwen3` |
| `OLLAMA_TIMEOUT` | `120` seconds |
| `SANDBOX_TIMEOUT` | `5` seconds |
| `SANDBOX_MEMORY` | `128m` |
| `SANDBOX_CPUS` | `0.5` |
| `SANDBOX_IMAGE` | `python:3.13-alpine` |
| `DEFAULT_QUIZ_LENGTH` | `10` |
| `DEFAULT_CODE_DIFFICULTY` | `medium` |

`python main.py tags` and `python main.py terms` inspect saved data without model
calls. `--verbose` enables scan, generation, regeneration, and result logging.
Normal operation logs warnings only.

## Sandbox and generation limits

Every execution uses a fresh non-root Docker container with no network, no host
mounts, no capabilities, no new privileges, a read-only root, 32-process limit,
memory/swap and CPU limits, and an 8 MB temporary filesystem. Input travels over
stdin, never through shell interpolation. The host caps each output stream at
64 KiB, enforces the execution deadline, and forcibly removes the named container
in `finally`, including interruption and timeout paths. Docker management commands
have separate 15-second deadlines, so setup/cleanup can add wall-clock time.

Ollama generates a complete program. Python selects a syntax node appropriate
for the difficulty and replaces it with `<BLANK>`, keeping the exact removed
text as the answer. This avoids malformed blanks from model responses.
The code quiz checks Docker and its image before requesting generation.

Generated code must be syntactically valid, short, different from the source and
all prior generations, and contain exactly one replaceable blank. The completed
program runs twice in separate containers to check success and stable output.
Invalid responses retry at most three times; infrastructure failures stop early.
Failed regeneration does not replace the previous cached question.

This MVP compares stdout, not full program semantics. Exercises must print a
meaningful result; input-driven, nondeterministic, silent, and multi-file programs
may fail generation. A hard-coded output can pass, and agreement on one output
does not establish correctness for all inputs. `grade_answer` is the replacement
point for stronger hidden-test grading. Prompt instructions guide difficulty and
concept preservation; the model's factual accuracy and pedagogical quality are
not mechanically guaranteed. Docker provides the execution boundary; this is a
local study tool rather than a public untrusted-code service.

## Docker application deployment

```sh
docker build -t markdown-quiz .
docker run --rm -it \
  -v /absolute/notes:/vault:ro \
  -v markdown-quiz-data:/data \
  -e OLLAMA_URL=http://host.docker.internal:11434 \
  -e OLLAMA_MODEL=qwen3 \
  markdown-quiz
```

This supports term quizzes. For code quizzes, the application container must
also reach a Docker engine. For a trusted local deployment, add
`-v /var/run/docker.sock:/var/run/docker.sock`. This grants the **application**
control of that engine; only use it for your trusted CLI/backend. The generated
code's child containers never receive this socket or any host mount. The sandbox
image must exist on that engine. On Linux, host Ollama access may require
`--add-host=host.docker.internal:host-gateway` and a reachable Ollama binding.
Alternatively, run the CLI directly on the host and let it create sandbox
containers through Docker Desktop.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The default suite uses mocks for Ollama and Docker; generated/submitted code is
never executed by host Python in tests. It covers parser behavior, tag filtering,
sync and restoration, portable hashes, scheduler updates, retries, generation
validation, caching, behavioral grading, CLI persistence, and container policy
and timeout cleanup. Opt into real container tests after starting Docker and
pulling the sandbox image:

```powershell
$env:RUN_DOCKER_TESTS = "1"
python -m unittest discover -s tests -p test_sandbox.py -v
Remove-Item Env:RUN_DOCKER_TESTS
```

## Backend map

| File | Purpose and important functions |
| --- | --- |
| `main.py` / `quiz_backend/main.py` | Entry point and terminal presentation |
| `config.py` | Settings defaults, environment overrides, validation and persistence |
| `notes/parser.py` | `parse_markdown`, `scan_vault`, normalization and source hashes |
| `notes/storage.py` | Saved-record validation, atomic JSON read/write and source synchronization |
| `quiz/selection.py` | Shared eligibility, tag/date/source/due filters and CLI tag selection |
| `quiz/engine.py` | Session start, current question, attempts, retries, queue transitions and summaries |
| `quiz/term_quiz.py` | Cached distractor reuse, `generate_wrong_answers`, `build_question` |
| `quiz/questions.py` | Interactive coding variation, protected blanks and sandbox grading |
| `quiz/spaced_repetition.py` | `select_question`, `record_answer`, review scheduling |
| `services/ollama.py` | Configurable local structured-JSON request |
| `quiz/code_quiz.py` | `generate_code_quiz`, candidate validation, `grade_answer` |
| `services/sandbox.py` | `run_in_sandbox`, bounded output and container cleanup |
| `backend.py` | `QuizBackend` coordinates the collections and saves mutations |

Rows remain JSON-compatible dictionaries, documented by typed records. See
[ARCHITECTURE.md](docs/ARCHITECTURE.md) for request flows and the complete directory map.
Backend operations do not prompt or print:

```python
from quiz_backend.backend import QuizBackend
from quiz_backend.config import Settings
from quiz_backend.quiz.spaced_repetition import select_question
from quiz_backend.quiz.selection import filter_tags

backend = QuizBackend(Settings(vault_path="./vault", data_path="./data"))
warnings = backend.rescan()
row = select_question(filter_tags(backend.terms, ["Biology"]))
question = backend.term_question(row, "reverse")
correct = backend.answer_term(question, 0)  # Index from the user's selected choice
```

`backend.rescan(files=["chapter.md"])` provides a partial scan without deactivating
unrelated files. The HTTP adapter in `quiz_backend/api.py` exposes these
operations to the Obsidian TypeScript plugin. It retains answer keys server-side
and returns question IDs and choices. Start it with
`python scripts/run_backend.py --vault /your/vault`.


### Library, API, and service controls (1.3.9)

In plugin settings, **Python libraries** searches suggested packages and your added packages. Check a package to enable it, uncheck to disable it, or use Add/Remove. Enter an exact package name (optionally `==version`) to add packages outside the suggestions. Search is a local list, not a live PyPI index. Disabled packages remain in your list. Removal excludes packages from future environments; existing questions retain their original image. Docker images are retained for existing quizzes. Built-in Python modules remain available.

Choose **API** under Generation source in settings or the multiple-choice quiz controls. Enter an HTTPS OpenAI-compatible base URL, model name, and API key. Requests use Chat Completions JSON mode; see the [official API documentation](https://developers.openai.com/api/docs/guides/structured-outputs). Quiz text travels through the backend to the provider, and provider usage charges may apply. The key stays in memory, is sent only with quiz requests, and is excluded from saved settings and sessions. Re-enter it after restarting Obsidian. The backend token is separate. Existing sessions retain their provider; start a new quiz or regenerate to switch. Coding questions still use the built-in generator.

**Server, sandbox & Ollama** appears in settings and the quiz setup pane. Reset server restarts the local backend; in managed mode it reloads only this vault's saved state. Reset sandbox rebuilds/selects the enabled library image and verifies a fresh restricted execution. Reset Ollama unloads the selected model, which loads again on the next request. These controls preserve study history and do not restart Docker Desktop or stop unrelated processes.
