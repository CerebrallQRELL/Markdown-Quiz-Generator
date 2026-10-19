# Deployment and AI pipeline

These diagrams describe the implemented system. Local and managed-server modes
are alternatives. The application performs model inference, not model training.

## Deployment

```mermaid
flowchart TB
    subgraph desktop["Student computer"]
        vault["Obsidian Markdown vault"]
        plugin["Obsidian plugin: sidebar and inline practice"]
        localApi["Local Python HTTP backend"]
        localModel["Local Ollama service"]
        localData[("Local JSON study data")]
        localDocker["Local Docker Engine"]
        localSandbox["Disposable Python sandbox"]
        vault -->|"Read notes"| plugin
        plugin -->|"Local mode: HTTP on loopback"| localApi
        localApi -->|"Read source notes"| vault
        localApi <-->|"Progress, sessions, settings"| localData
        localApi -->|"Generation requests"| localModel
        localApi -->|"Docker CLI"| localDocker
        localDocker -->|"Create, run, remove"| localSandbox
    end
    subgraph server["Managed server: Docker Compose"]
        gateway["HTTPS reverse proxy or SSH tunnel"]
        managedApi["Python API container: port 8765"]
        serverModel["Ollama container: internal network"]
        studyVolume[("Study volume: uploaded notes and JSON state")]
        modelVolume[("Model volume: downloaded weights")]
        serverDocker["Host Docker Engine"]
        serverSandbox["Disposable Python sandbox"]
        gateway -->|"Loopback published port"| managedApi
        managedApi <-->|"Per-vault snapshots and progress"| studyVolume
        managedApi -->|"Generation requests"| serverModel
        serverModel <-->|"Model storage"| modelVolume
        managedApi -->|"Docker socket"| serverDocker
        serverDocker -->|"Create, run, remove"| serverSandbox
    end
    provider["Optional remote model provider"]
    plugin -->|"Server mode: bearer token and Markdown uploads"| gateway
    localApi -.->|"Optional HTTPS generation"| provider
    managedApi -.->|"Optional HTTPS generation"| provider
```

- The managed API port is published on server loopback. HTTPS termination is an
  administrator-provided reverse proxy; SSH forwarding is the alternative.
- Remote provider keys accompany quiz requests and are not saved. The backend
  token authenticates the plugin separately.
- Only the trusted API container receives the Docker socket. Student sandboxes
  have no network, no vault/socket mounts, a read-only root, an unprivileged user,
  resource limits and enforced cleanup.
- Optional Python packages are installed into dedicated sandbox images.
- The standalone terminal CLI uses the same Python modules, model services,
  JSON storage and sandbox. It can also run in the root Dockerfile's CLI image.

Sources: `deployment/compose.yaml`, both Dockerfiles, `markdown_quiz/api.py`,
`markdown_quiz/services/sandbox.py` and `obsidian-markdown-quiz/src/main.ts`.

## AI and question-generation pipeline

```mermaid
flowchart TB
    notes["Markdown notes"] --> parse["Parse terms, definitions, tags and Python blocks"]
    parse --> records[("Saved source records and stable IDs")]
    records --> select["Filter and select study material"]
    select --> quizType{"Question type?"}

    quizType -->|"Multiple choice"| direction{"Direction?"}
    direction -->|"Definition to term"| reverse["Choose other distinct terms locally"]
    direction -->|"Term to definition"| cache{"Valid cached distractors?"}
    cache -->|"Yes"| choices["Build and shuffle four choices"]
    cache -->|"No"| provider{"Configured provider"}
    provider --> ollama["Ollama: structured JSON generation"]
    provider --> remote["Remote API: JSON generation over HTTPS"]
    ollama --> validate["Validate three distinct wrong definitions"]
    remote --> validate
    validate -->|"Invalid: retry, up to three attempts"| provider
    validate -->|"Valid: save distractors"| choices
    reverse --> choices

    quizType -->|"Interactive coding"| astVariation["Conservative AST input variation: no LLM"]
    quizType -->|"CLI coding"| cliModel["Ollama or configured provider generates a short program"]
    cliModel --> cliValidation["Validate syntax, size and generation uniqueness"]
    cliValidation -->|"Invalid: retry, up to three attempts"| cliModel
    cliValidation --> blanks["Create editable blanks locally"]
    astVariation --> blanks
    blanks --> verify["Docker: verify successful, stable program output"]
    verify -->|"Valid question"| display["Present question to student"]
    choices --> display
    display --> answer["Student submits an answer"]
    answer --> grade["Compare choice key or reconstructed code output"]
    grade --> progress["Record attempt and update mastery and review time"]
    progress --> saved[("Saved progress; interactive sessions also persist")]
```

AI generates forward multiple-choice distractors and CLI coding programs.
Reverse multiple choice uses existing terms. Sidebar/inline coding variation and
blank creation use Python ASTs rather than an LLM. Generated programs are checked
and executed inside Docker; an LLM does not grade submitted code.

For interactive coding, missing stdin pauses preparation for program input;
silent or invalid sources are skipped. Wrong coding answers remain retryable.
Interactive multiple choice allows two attempts. Drafts and request IDs support
resume and safe retransmission. Sandbox infrastructure failures do not penalize
the student. Exhausted model retries surface an error for retry/skip handling.

Sources: `notes/parser.py`, `quiz/selection.py`, `quiz/term_quiz.py`,
`quiz/questions.py`, `quiz/code_quiz.py`, `quiz/engine.py` and
`services/ollama.py` / `services/cloud.py` within `markdown_quiz/`.
