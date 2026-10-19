# Local and server setup (1.3.9)

## Local Windows package
Extract the **markdown-quiz-local-1.3.9.zip** download. In PowerShell, run `./deployment/install-local.ps1`. If PowerShell blocks a downloaded file, review it then use `Unblock-File ./deployment/install-local.ps1` under your normal execution policy. `-PlanOnly` prints the plan without changing the computer.

Setup installs Python 3.13, Ollama, and Docker Desktop via Windows Package Manager, starts the services, pulls the Python sandbox image and qwen2.5-coder:7b model. Internet and sufficient disk/RAM are required. Windows App Installer/winget is a prerequisite. Docker may need WSL, enabled virtualization, an administrator prompt, license acceptance, or a restart. Rerun setup after completing those OS steps. This is an online setup bundle, not a portable Docker engine or offline model download. Logs are in `%LOCALAPPDATA%/MarkdownQuizSetup`.

Copy `markdown-quiz-generator` into `<your vault>/.obsidian/plugins/` and enable it. Restart Obsidian after installation so PATH refreshes. Choose **Local computer**, backend `http://127.0.0.1:8765`, then **Start backend**. If Python is not found, select its executable in settings. Use the Ollama model dropdown after the backend starts. Existing JSON answers are reused; missing distractors alone require generation.

Start backend replaces a different bundled backend version through its local restart endpoint. For old versions without that endpoint, Windows verifies that the listening process is Python running this plugin folder's exact backend.py before stopping it. Unrelated services/other installations must be stopped manually. Server mode only checks connectivity; it never stops a remote service.

## Server package
Extract **markdown-quiz-server-1.3.9.zip** on a Linux server with Docker Engine and Compose installed. Run `sh deployment/setup-server.sh`. It builds the API, starts Ollama, prepares the sandbox image, pulls the model, and generates a random token in `deployment/.env`. Rerunning preserves the token and stored study/model volumes. This is a single trusted-user deployment, not a multi-tenant hosting platform.

The API binds to server loopback only. From your computer, keep an SSH tunnel open:

```sh
ssh -N -L 8766:127.0.0.1:8765 YOUR_USER@YOUR_SERVER
```

In Obsidian choose **Server**, URL `http://127.0.0.1:8766`, and paste QUIZ_API_TOKEN from the server's `.env` into **Backend token (session only)**. Enter it again after reopening Obsidian. Alternatively configure an HTTPS reverse proxy with a valid certificate to the loopback backend and use its HTTPS URL. Plain HTTP to remote hosts is rejected. Do not expose port 8765 directly to the internet.

Server mode uploads Markdown copies from the active vault (up to 800 KB per note; 20,000 notes), then reconciles removed notes after a successful full upload. It never reads a client-specified server path or writes answers back to the Obsidian vault. Notes are stored in the server's study volume, separated by a random vault key persisted in plugin settings. Treat that key and the server token as private. Duplicate vault keys share study data: keep the plugin data when reinstalling, but do not copy it to unrelated vaults. Attachments and plugin files are not uploaded. Back up the study volume and .env. A rescan retries incomplete uploads.

The trusted backend has Docker socket access to create restricted sibling sandbox containers. Student containers receive no socket or vault mounts, no network, a read-only root, unprivileged UID, resource limits, and execution timeout. Run this stack on a dedicated trusted host; Docker socket access is administrative authority. Ollama is internal to the Compose network. CPU inference is the default; provision appropriate RAM for your model.

Update by replacing package code and running `docker compose -f deployment/compose.yaml up -d --build`. Stop with `docker compose -f deployment/compose.yaml down` (without `-v` to preserve data). Add models using `docker compose -f deployment/compose.yaml exec ollama ollama pull MODEL`, then reopen plugin settings.

Official runtime instructions: https://docs.docker.com/desktop/setup/install/windows-install/ and https://docs.ollama.com/docker

## Programs using input()
Before starting Coding or inline practice, enter one response per line in **Program input**. For two numeric prompts, enter `5`, a newline, then `4`. The same input is shown with the question and used for expected output and every retry. Use Start over to change it. Missing lines produce an actionable message. Input is saved in plugin settings/session data; do not use secrets. Source notes remain unchanged.

Silent code blocks are skipped during coding-question preparation without changing mastery. Remaining matching blocks fill the requested count where available. Bare expressions are no longer automatically wrapped in print(); use explicit output for a quiz question. The pre-start count is a candidate count; output is checked inside the sandbox when preparing each question.

## Choosing an LLM
The quiz menu and question regeneration controls list the connected Ollama service’s installed models. Use Refresh models after installing another model. Selection is saved and applied with the next start/regenerate request; existing cached answers are preserved. Multiple-choice regeneration uses that model. Coding regeneration currently uses the deterministic Python variation generator and remains available without Ollama.

### Separate model preferences
Multiple Choice model and Coding model are saved independently in plugin settings. The quiz menu shows the active type; regeneration and inline practice use the actual question type. Existing installations fall back to the previous shared preference until each type is changed. Sessions retain their own model for subsequent questions and regeneration. Coding still uses the built-in Python generator; its saved LLM preference does not change that implementation.
