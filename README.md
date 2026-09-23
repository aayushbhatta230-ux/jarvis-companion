# JARVIS — Personal Computer Companion

JARVIS is a local-first **intelligent computer agent** for Windows. It understands
natural language, plans actions, and controls your computer — all through conversation.

## What's New: Agent Architecture

JARVIS is no longer a command-based assistant. You speak naturally, and JARVIS:

1. **Understands** your intent from many phrasings
2. **Plans** the right sequence of actions
3. **Selects** the appropriate tools automatically
4. **Executes** and reports the verified result
5. **Confirms** before destructive or external actions

### Natural Language Examples

Just talk to JARVIS like a person:

- "Open that physics paper I was working on yesterday."
- "Find all PDFs related to physics in my Downloads folder."
- "Open my browser and search for the latest SAT registration information."
- "Email my teacher saying I'll submit the assignment tonight."
- "Read this document and summarize it."
- "Create a folder for my physics notes and organize the relevant files into it."
- "What's on my computer that I was working on last night?"
- "Find the Python project I was working on and tell me what's wrong."
- "Fix the bug and run the tests."

**No commands to memorize.** JARVIS figures out what you mean.

## Run

```powershell
\. \.venv\Scripts\python.exe -m pip install -r requirements.txt
ollama pull llama3.2
\. \.venv\Scripts\python.exe main.py
```

Then open the interface:

```
http://127.0.0.1:8765/
```

Press `Ctrl+C` to stop JARVIS.

No new dependencies were introduced: the web interface is served by the Python
standard library (`http.server`), and browser state is pushed over
Server-Sent-Events.

## Architecture

| Area | File | Role |
|------|------|------|
| Entry point | `main.py` | Starts the brain worker, web server, and static UI |
| Orchestration | `core/conversation.py` | Agent turn pipeline: understand → plan → execute → confirm |
| Reasoning | `core/brain.py` | Ollama wrapper with `respond` and `respond_stream` |
| Intent | `core/intent.py` | Rich intent inference (synonyms, indirect phrases, follow-ups) |
| Planning | `core/planner.py` | Maps intents to capabilities with argument extraction |
| Capabilities | `core/capabilities.py` | 35+ tools with risk levels and confirmation gates |
| Preferences | `core/memory.py` | Weighted local preference evidence (`memory/preferences.json`) |
| Settings | `core/settings.py` | Real persisted knobs (`config/settings.json`) |
| History | `core/history.py` | Conversation log (`memory/history.json`) |
| Events | `core/events.py` | Thread-safe pub/sub for UI state + messages |
| Web bridge | `interface/server.py` | Stdlib HTTP + SSE server, static UI, command API |
| Voice in | `voice/listener.py` | Persistent single microphone stream, VAD, STT |
| Voice out | `voice/speaker.py` | Interruptible SAPI worker with streaming `enqueue_chunk` |
| File tools | `tools/files.py` | Search, read, create, edit, move, copy, rename, delete files |
| App tools | `tools/computer.py` | Application launch, close, system info |
| Terminal tools | `tools/terminal.py` | Safe command execution with output capture |
| Browser tools | `tools/browser.py` | URL opening and web search |
| Media tools | `tools/media.py` | Music play, stop, pause, resume, next |
| Email tools | `tools/email.py` | Email drafting, contact management |
| Document tools | `tools/documents.py` | Summarize, format cleanup, structure extraction |
| UI | `interface/index.html`, `style.css`, `app.js` | Agent state frontend (idle/listening/understanding/planning/executing/speaking) |

### Capability Registry

All actions JARVIS can perform are registered in `core/capabilities.py` with:

- **Risk level**: `low` (auto-execute), `medium` (ask if ambiguous), `high` (always confirm)
- **Reversible**: Whether the action can be undone
- **Confirmation required**: Whether user confirmation is needed

| Category | Capabilities |
|----------|-------------|
| File | search, read, create, edit, move, copy, rename, delete, list, info, find_recent, create_folder |
| Application | open, close, list running |
| Browser | open_url, search web |
| Media | play, stop, pause, resume, next |
| Terminal | execute, run_python |
| System | get_info |
| Email | draft, list, get, update, confirm_send, resolve_contact, add_contact, list_contacts |
| Document | summarize, create, clean_formatting, count_words, extract_sections |

### Safety Model

JARVIS never silently performs destructive actions:

- **LOW RISK** (open files, read, search, web search): Automatic
- **MEDIUM RISK** (modify files, move, rename, run commands): Ask when ambiguous
- **HIGH RISK** (delete files, send emails): Always confirm

When intent is unclear, JARVIS asks a single clarifying question instead of guessing.
## Microphone

The audio input stream is opened **once** and kept alive on a dedicated capture
thread, so every utterance reuses the same device instead of re-initialising
it. The adaptive threshold is derived from ambient noise and is scaled by the
`mic_sensitivity` setting, and the buffer is cleared between passes so speaker
echo cannot trigger a false start. JARVIS distinguishes silence, background
noise, speech, and end-of-speech before transcribing.

While JARVIS is speaking, a separate monitor watches for user speech and
immediately stops TTS, re-arms listening, and captures the interruption.

## Companion intelligence

JARVIS routes each transcript through contextual intent inference before sending
it to Ollama. It considers recent conversation, open-ended goals, and a small
local preference model, so phrases such as "I think I want to watch something"
are treated as intent rather than requiring an exact command.

Preference evidence is stored locally in `memory/preferences.json`. Explicit
statements carry more weight than inferred behaviour, confidence increases
gradually, and sensitive actions are marked for confirmation. JARVIS can open
HTTP(S) URLs, search the web, and launch Notepad, Calculator, or Paint.
Arbitrary shell commands, file changes, messages, purchases, and other
consequential actions remain confirmation-gated.
## Interface

The web command center mirrors the backend in real time:

- Header status chips: backend link, microphone capture state.
- Central neural core that reacts to `idle / listening / processing / speaking /
  interrupted / error / offline`.
- Live conversation with streaming assistant responses and timestamps.
- Command bar with microphone toggle, text input, send, and a Stop button while
  JARVIS is speaking.
- Settings drawer that actually drives the backend (auto-listen, microphone
  sensitivity, response length, visual intensity).
- History drawer backed by `memory/history.json`.

Settings live in `config/settings.json`; delete the file to restore defaults.
Voice selection prefers installed natural voices, or set `JARVIS_VOICE` to part
of a voice name:

```powershell
$env:JARVIS_VOICE = "Zira"
\. \.venv\Scripts\python.exe main.py
```

## Interaction reliability

JARVIS runs a lightweight speech interruption monitor while SAPI is speaking. A
detected speech onset purges the SAPI queue, cancels the active response
generation, and returns control to the normal listener. The monitor uses
WebRTC VAD when the optional `webrtcvad` package is available; otherwise it
uses a conservative sustained speech heuristic. Windows SAPI does not expose an
acoustic echo-cancellation reference to this Python process, so speaker
feedback can still require a headset or lower volume.

Natural website and music requests are dispatched through the action planner and
return verified tool results before JARVIS speaks. Music uses YouTube Music in
the default browser; Windows media keys handle stop, next-track, pause and
resume requests. External actions are gated on speech confidence; uncertain
commands are withheld rather than guessed.

## Security

The web server binds to `127.0.0.1` only. The frontend can submit typed
commands, toggle listening, adjust known settings, and request an interrupt —
nothing else. There is no arbitrary command execution, no file access, and no
secrets exposed to the browser.

## Tests

```powershell
\. \.venv\Scripts\python.exe -m pytest -q
```