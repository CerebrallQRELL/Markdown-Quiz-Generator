## Error recovery (1.3.7)

Failed questions show Skip question and Retry question, including failures before
a question appears. Skipping a generation failure advances without counting an
incorrect answer. The failed position survives reopening the quiz.

## Python libraries (1.3.6)

Open Settings > Markdown Quiz Generator > Python libraries.

- Built-in libraries (`math`, `collections`, etc.) are already available.
- Enter third-party package names such as `numpy, pandas`, then click Install
  libraries. Optional exact versions use `numpy==2.3.0`. Installation requires
  Docker and internet access on the backend computer and may take several minutes.
- Enter optional import statements such as `import numpy as np` or
  `from math import sqrt` in Additional Python imports. Leave this blank when
  your source code already includes the imports.
- Start a new coding quiz or inline practice to use the changes. Imports appear
  in the exercise and apply to expected output and submitted answers.

Only binary packages compatible with Python 3.13 are supported. Packages install
in a dedicated Docker image, not in the host Python environment. Quiz execution
keeps its existing network, memory, time, and filesystem restrictions. Existing
questions keep their original image. Installation failures preserve the previous
library configuration. Library configuration is saved separately for each vault.
Clear the package list and click Install libraries to use only built-in libraries
for new questions; existing Docker images are retained for active sessions.

## Coding practice updates (1.3.5)

Program input appears inside the coding question after Start practice or Start quiz.
It is blank and disabled for programs that do not request input. When input is
needed, enter one response per line and click Apply program input to calculate
expected output. Input belongs to that question and is fixed after the first answer.

The coding screen includes a difficulty selector. It changes the current blanks
before the first attempt; after an attempt, it applies to the next question.
Invalid source syntax, source execution errors, and silent programs are skipped
automatically, including consecutive unusable blocks. These automatic skips do
not count as incorrect answers. Syntax errors in a student's answer still show
feedback and allow a retry. Docker availability errors remain visible for retry.

## Version 1.3: local or server

Choose **Connection mode** in plugin settings. Local computer uses the active vault directly. Server sends Markdown copies to your configured authenticated HTTPS server (or localhost SSH tunnel). Use the new local/server download bundles and follow [deployment/DEPLOYMENT.md](../deployment/DEPLOYMENT.md). Start backend checks an existing local version and restarts an older bundled backend when it can identify it safely. Server lifecycle is managed through Docker Compose.

# Obsidian plugin setup

## Install or update

Copy the complete `plugin/markdown-quiz-generator` folder into the **Obsidian
vault you study in**, under `.obsidian/plugins/`. Keep its bundled `backend/`
folder alongside `main.js`, `manifest.json`, and `styles.css`. For a download,
extract `dist/markdown-quiz-generator-1.2.0.zip` to the same location.

Enable/reload Markdown Quiz Generator, open the brain ribbon pane, and click
**Start backend** if offline. This launches the included `backend/backend.py`
with the current Obsidian vault path. Python 3.11+ must be installed; set its
executable path in plugin settings if `python` is unavailable (`python3` on
macOS/Linux). No pip dependencies are needed.

When updating from an earlier version, stop the old backend terminal once before clicking
Start backend. Replace the complete plugin folder's distributed files, preserving
`data.json` and `backend/data` if already present. The Python backend remains
running when Obsidian closes and can serve multiple vaults with isolated data.

The plugin explicitly connects using Obsidian's filesystem adapter. It does
**not** use the project's example `vault/` folder. Notes stay read-only. Each
connected vault has its own progress/cache under `backend/data/vaults/<vault-id>`.
Renaming or moving the entire vault changes its identity; migrate its cache if
needed. First pane use scans the actual vault; saved edits synchronize notes
and refresh discovered tags. Hidden directories are excluded from scans.

Start local Ollama and choose an installed model in plugin settings (default
`qwen2.5-coder:7b`). Code execution still uses Docker Linux containers:

```powershell
docker pull python:3.13-alpine
```

For a manually started backend, use:

```powershell
python backend.py --vault "C:\path\to\your\Obsidian vault" --data "./obsidian-data"
```

The plugin connects to `http://127.0.0.1:8765` by default. Its vault connection
overrides the manual backend's default note folder for plugin requests.

## Eligible terms and filters

Term questions require `#quiz`, which is an eligibility marker and never a
selectable filter. Use scoped tag lines, inline term/definition tags, or note
frontmatter `tags: [quiz, Python]` (a YAML tag list on separate lines also works).
A new scoped tag group replaces the previous group; frontmatter tags persist.

```markdown
#quiz #Python #2026-10-14
Variable:: A named reference to a value.
Loop:: Repeats a sequence of instructions.

#Notes
Not studied:: This term lacks the quiz marker.
Single term:: This one is eligible. #quiz #Python
```

Include tags match **any** selected tag. Exclude tags remove **any** matching
term, even if it matches an included tag. Empty inclusion means all eligible
terms. Date bounds include both endpoints and match date tags such as
`#2026-10-14` or `#date/2026-10-14`; undated terms are omitted only while a date
bound is set. Dates refer to tags, not filesystem timestamps.

Tags are discovered automatically from eligible terms. Recently selected or
exactly searched tags are saved at the top; other tags start with the most common
in your notes. Question cards show mastery before answering and update it after
answering. Open source note resolves the exact file in the current vault.

## Studying

Choose exactly one sidebar quiz type: **Multiple Choice** or **Coding**.
Both use include/exclude tags, inclusive date calendars, due/current-note filters,
matching counts, random selection and the requested number of questions.
Multiple-choice terms require #quiz; coding questions come from Python/py fences.
Coding difficulty controls blank complexity and count; all supported sources can
be practiced at any difficulty. Coding direction is Random or Source order.

Tag/date sections collapse with saved summaries. Search tags, use arrow keys
and Enter to select, or remove selected chips. Selecting an included tag in
Exclude moves it there (and vice versa). The Start button is disabled for zero
matches or invalid dates. The current note is captured when starting a session;
opening another note does not replace an active question.

Multiple-choice answers shuffle for each new instance and are graded by answer
ID. A first wrong option is disabled without revealing the key. A second wrong
answer or a correct answer reveals feedback and starts a five-second countdown.
Use **Next now** to advance immediately. While the quiz pane is focused, 1-4 or
A-D selects answers and Enter advances a completed question.

Coding answers are edited directly inside highlighted code blanks. Protected
code is not an editable document: each blank is a separate native editing
surface, and only its value is sent to Python. The server reconstructs the code
from its private template. Tab/Shift+Tab moves between blanks, Ctrl+Enter runs,
and Enter adds an indented new line. Feedback distinguishes incorrect output,
syntax errors, runtime errors, timeout, output limits and sandbox failures.
**Try again** keeps the same variation. Feedback colors refer to the whole
program's correctness, not independently proven correctness of individual blanks.

**Practice this code** below notes uses the same session engine, coding model,
blank editor, grader and sandbox as sidebar coding. Collapsing or remounting it
preserves its state. Sidebar sessions and coding drafts survive pane changes;
backend sessions are stored in `sessions.json`, while plugin settings store
session references. The 256 most recently used sessions are retained. A backend
restart keeps saved sessions; changing/deleting source content invalidates grading
of stale questions. Use **Skip question** or **Start over** explicitly.

Safe numeric variation uses Python syntax trees. Positive integer demonstration
arguments to simple straight-line arithmetic functions can vary; algorithm
constants, indexes, loops, sentinels, APIs and unsupported examples are preserved.
Expected output is executed and checked twice in Docker. Sidebar/inline coding
does not require Ollama; multiple-choice distractor generation still uses Ollama.
Existing CLI generation commands remain available.

Mastery labels are New, Learning, Familiar and Mastered. A first-run success gains
2 points; a second-run success gains 1; later successes gain 0 and get a shorter
review interval. A final failure/skip loses 2 (minimum zero). The existing numeric
scores and history remain valid. Every student attempt records its type, outcome,
response, duration, difficulty and mastery context; coding outcomes include run
counts. Infrastructure failures are shown without penalizing mastery.

## Shared API and data

Backend version is `1.2.0`, protocol version `1` with capability
`shared-sessions-v2`. Update plugin and backend together.

- `POST /vault/connect`: absolute Obsidian vault_path; subsequent calls carry
  the returned vault_id in `X-Quiz-Vault`.
- `POST /quiz/catalog`: shared filters, matching count, discovered tags and statistics.
- `POST /quiz/start`: shared filters plus quiz_type, direction, difficulty and length.
- `POST /quiz/resume`, `/quiz/next`, `/quiz/skip`, `/quiz/abandon`, `/quiz/regenerate`:
  session_id and, for question-changing actions, question_id.
- `POST /quiz/answer`: session_id, question_id, request_id, and either answer_id
  or an answers object keyed by blank ID. Returns the updated shared session.
- `POST /quiz/draft`: saves the current blank values.
- `/health`, `/sync`, `/sync/file`, `/tags`, `/stats` remain available.

Legacy term/code endpoints adapt to the shared engine; they do not own separate
session implementations. The current plugin uses only the unified session API.
Answer keys and code solutions stay server-side. Source Markdown is never written.
Code execution retains Docker's non-root, read-only, network-disabled containers,
CPU/memory/PID limits, execution/output limits and forced cleanup. All Python
Docker subprocesses use CREATE_NO_WINDOW on Windows; the Electron launcher uses
windowsHide and captures diagnostics. No student code runs inside Obsidian.

## Backend location

Run the backend natively on the same computer as Obsidian so it can read the
vault's actual path. Only generated Python exercises run inside Docker. A
containerized HTTP backend with differently mapped paths does not support this
automatic vault connection.

## Build and publish on GitHub

Use Node 24+, pnpm 11.25.0, and Python 3.11+:

```sh
cd obsidian_plugin
pnpm install --frozen-lockfile
pnpm build
pnpm test
cd ..
python -m unittest discover -s tests -v
python scripts/package_release.py
```

Outputs include the plugin folder and three ZIPs in `dist/`: plugin, backend,
and clean repository source. The source archive excludes personal study data,
credentials, unrelated projects, dependencies, and notes except the sample.

Extract **markdown-quiz-source-1.2.0.zip** into a new GitHub repository's root.
Install from the complete plugin ZIP so the bundled Python backend is included.
Create a `1.2.0` release with the plugin/backend ZIPs and individual `main.js`,
`manifest.json`, and `styles.css` assets. Alternatively push a `1.2.0` tag: the
included GitHub Actions workflow builds, tests, packages, and publishes those
assets. Update manifest/package/versions JSON together for later versions.
Community Plugin listing requires a separate Obsidian review/submission.
The packaging script does not create a GitHub repository or publish anything.

## Troubleshooting and verification

Validation commands from the project folder:

```powershell
$env:RUN_DOCKER_TESTS = "1"
python -B -m unittest discover -s tests -v
python scripts/smoke_release.py
```

The packaged smoke test starts a hidden temporary backend, tests both quiz types
and restart/resume, then stops it. It needs Docker and the sandbox image. Run
`pnpm build` and `pnpm test` in `obsidian_plugin` for frontend checks.


- Backend offline: click Start backend, or start `run_backend.py` manually; check its URL and reconnect.
- No terms: mark eligible terms #quiz and use Rescan vault.
- No due questions: clear Due only.
- Ollama unavailable: check `ollama list` and the configured model/server.
- Sandbox unavailable: start Docker with Linux containers and pull its image.
- Changed question: save the note and start practice again.

Python tests cover sessions, idempotency, traversal/origin protection,
rename/delete synchronization, duplicate blocks, caching, and stale questions.
Frontend checks cover lazy generation, duplicate clicks, output display,
cleanup, CodeMirror decorations, and a 2,000-block note. TypeScript builds
against official Obsidian types. Real desktop Obsidian layout/theme/enable-disable
acceptance checks still require an Obsidian vault; the test DOM is not that app.

Official references:
[Obsidian API](https://github.com/obsidianmd/obsidian-api),
[editor decorations](https://docs.obsidian.md/Plugins/Editor/Decorations),
[Markdown post processing](https://docs.obsidian.md/Plugins/Editor/Markdown%20post%20processing).
