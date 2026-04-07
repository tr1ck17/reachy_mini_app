# Reachy Mini — CPS Facilitator: Project Documentation

This document is the canonical reference for the Reachy Mini CPS Facilitator project.
It covers architecture, file inventory, design decisions, known issues, and roadmap.
Any AI agent or collaborator should read this before making changes.

---

## Project Overview

An embodied Creative Problem Solving (CPS) facilitator built on the Reachy Mini robot platform
(by Pollen Robotics, now part of Hugging Face). The app guides users through the four stages
of Buffalo State-style CPS (Clarify, Ideate, Develop, Implement) via voice conversation,
with expressive robot behaviors, live dashboard, persistent session memory, and session history viewer.

**Core interaction loop:**
1. User presses Enter to start recording
2. Listening pose triggered on Reachy
3. User speaks
4. User presses Enter again to stop recording
5. Whisper transcribes locally
6. Reachy hits a thinking pose (question vs statement detection)
7. Context-aware thinking phrase spoken aloud
8. LLM generates a facilitation response (Claude API or Ollama fallback)
9. Mood reaction fires (happy, surprised, thinking, neutral)
10. Talking animation runs in background while edge-tts speaks the response
11. Dashboard updates with transcript and artifacts in real time
12. Idle animations resume while waiting for next input

---

## Hardware Targets

- **Reachy Mini Wireless** — runs onboard RPi CM4, connects via WiFi
- **Reachy Mini Lite** — connects via USB, daemon runs on host PC
- **Simulation** — MuJoCo-based sim, daemon runs on host PC (`uv run reachy-mini-daemon --sim`)

The SDK auto-detects Lite vs Wireless. For Wireless, pass `host="192.168.x.x"` to `ReachyMini()`.
All code is hardware-agnostic — same scripts run on sim and real hardware with zero changes.

---

## Tech Stack

| Component | Technology |
|---|---|
| LLM (primary) | Claude API — `claude-haiku-4-5-20251001` |
| LLM (fallback) | Ollama — `llama3.2:3b` (local, offline) |
| Speech-to-text | faster-whisper `tiny` model (local, offline) |
| Text-to-speech | edge-tts — `en-US-AriaNeural` voice |
| TTS playback | pygame (MP3 format — cross-platform fix) |
| Audio I/O | sounddevice + soundfile |
| Robot SDK | reachy-mini (Python SDK + MuJoCo sim) |
| Web server | Flask (threaded) |
| Package manager | uv |
| Python version | 3.10–3.13 |

---

## File Inventory

### Core Application

**`reachy_chat.py`** — Main entry point. Handles the full conversation loop:
- Mic check on startup — 1 second recording to verify mic is working
- Session mode selection (continue vs fresh) via terminal prompt or `REACHY_SESSION_MODE` env var
- Listening pose triggered when user presses Enter to record
- Audio recording with Enter-to-start, Enter-to-stop using a background thread
- Whisper transcription with unique temp filenames (avoids file lock conflicts)
- Context-aware thinking phrases — detects if user's message ends with `?` and picks
  from `THINKING_PHRASES_QUESTION` or `THINKING_PHRASES_STATEMENT` accordingly
- Thinking pose triggered while LLM generates response
- LLM call with Claude API primary, Ollama fallback
- Response parsing — extracts MOOD: tag and ARTIFACT_*: tags (never spoken aloud)
- Mood reaction via `behaviors.py` before speaking
- Talking animation runs in background thread while Reachy speaks
- Returns to neutral and resumes idle after each turn
- Dashboard state updates after every exchange
- Stage advancement when user says explicit advance phrases
- Stage-specific greetings on transition (randomized per stage)
- Session summary spoken on quit
- Session saving and transcript export on exit (including Ctrl+C)
- pygame startup message suppressed via `os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"`

**`behaviors.py`** — Natural movement library for Reachy Mini:
- `THINKING_QUESTION_POSES` — upward/sideways gaze poses for when user asks a question
- `THINKING_STATEMENT_POSES` — downward/reflective poses for when user makes a statement
- `talking_animation()` — background thread with gentle head bobs and sways while speaking
- `LISTENING_POSES` — attentive head tilts triggered when recording starts
- `react_happy()`, `react_surprised()`, `react_thinking()`, `react_neutral()` — mood reactions
- `idle_loop()` — subtle randomized movements every 3-6 seconds while waiting
- `do_thinking_pose()`, `do_listening_pose()`, `do_mood_reaction()` — convenience wrappers
- `return_to_neutral()` — smooth return to default pose after speaking

**`cps_manager.py`** — CPS stage management:
- `STAGES` — ordered list: `["clarify", "ideate", "develop", "implement"]`
- `ADVANCE_KEYWORDS` — strict list of phrases that trigger stage advance including
  `"i'm ready to move on to the next stage"` and similar explicit phrases
- `load_stage()` — reads knowledge base `.md` file for a given stage
- `build_system_prompt()` — injects stage knowledge into the base system prompt
- `check_for_advance()` — checks if user's message contains an explicit advance phrase
- `next_stage()` — returns next stage or None if at final stage

**`memory_manager.py`** — Session persistence:
- Rolling memory: last 5 sessions stored in `memory.json`
- Stage state: current CPS stage stored in `stage_state.json`
- Session ID: unique ID per CPS problem stored in `session_id.json`
- Transcript export: all sessions for one problem append to one `sessions/session_<id>.md` file
  — first session creates the file, continuations append with a `## Session continued` marker
- `build_history_context()` — flattens past sessions into LLM message list with timestamps

**`dashboard_state.py`** — File-based shared state between `reachy_chat.py` and `launcher.py`:
- Uses `dashboard_state.json` on disk — works across separate OS processes (file-based IPC)
- Thread-safe using a lock with atomic file writes (`.tmp` → `os.replace`)
- Version counter — increments on every state change, drives long-poll efficiency
- Tracks: active flag, current stage, `stage_started_at` timestamp, `stage_times` dict,
  live transcript, artifacts per stage
- `set_stage()` — automatically records time spent in previous stage and timestamps new stage start
- `set_active(False)` — records final stage time on shutdown
- Artifact types: challenge statement, focus question, ideas, clusters, plusses,
  potentials, concerns, action steps, committed actions

**`launcher.py`** — Flask web server:
- Serves `index.html` at `localhost:5000`
- Serves `history.html` at `localhost:5000/history`
- `/api/session-info` — reads memory/stage/session files for the launcher UI
- `/api/launch` — launches `reachy_chat.py` in a new terminal via subprocess
- `/api/clear-history` — deletes all history files including transcripts
- `/api/transcripts` — returns list of all transcript files with metadata
- `/api/transcript/<id>` — returns full content of a specific transcript
- `/api/state` — returns full dashboard state immediately (reads from `dashboard_state.json`)
- `/api/poll?since=N` — long-poll endpoint: blocks up to 30s until version > N, then returns state
- `threaded=True` required for long-polling to work correctly

**`index.html`** — Combined launcher + live dashboard (single page, two states):
- **Launcher state**: session info card, Continue/Start New/View History/Clear History buttons
- **Dashboard state**: transitions automatically when session goes active
  - Top bar: live dot, session title, stage progress indicator
  - Left panel: artifacts (challenge, focus question, ideas, clusters, PPCo, actions)
  - Center panel: live scrolling transcript (you + Reachy turns)
  - Right panel: stage description, time-per-stage bars with live ticker, session stats
- Long-poll loop keeps dashboard updated without unnecessary requests
- Stage timer: completed stages show locked time with green bar, active stage ticks live
- "Don't show again" for clear history confirmation stored in localStorage

**`history.html`** — Session history viewer:
- Lists all past session transcripts with date, preview, exchange count, session count
- Search bar filters transcripts in real time
- Clicking a session loads full transcript rendered as a chat UI
- Session break markers shown between continued sessions
- Back button returns to launcher
- Accessible at `localhost:5000/history`

### CPS Knowledge Base

**`cps/clarify.md`** — Clarify stage facilitation guide
**`cps/ideate.md`** — Ideate stage facilitation guide (includes strict no-consulting rules)
**`cps/develop.md`** — Develop stage facilitation guide (PPCo process)
**`cps/implement.md`** — Implement stage facilitation guide

### Auto-Generated Files (gitignored)

- `memory.json` — rolling session memory (last 5 sessions)
- `stage_state.json` — current CPS stage
- `session_id.json` — current problem's session ID
- `dashboard_state.json` — live state shared between processes (file-based IPC)
- `sessions/` — transcript `.md` files, one per CPS problem
- `reachy.log` — detailed application log
- `input_*.wav`, `tts_*.mp3` — temporary audio files (deleted after each turn)

---

## Key Design Decisions

### LLM Strategy
- **Claude API is primary** — significantly better instruction-following, 1-2s response time
- **Ollama is fallback** — free and offline but slow on CPU (minutes per response) and
  unreliable at following complex system prompts. GPU makes it viable for testing.
- Claude model: `claude-haiku-4-5-20251001` — fastest/cheapest Claude model, sufficient quality
- API key loaded from `.env` file via `python-dotenv` — never hardcoded, never committed to Git

### Stage Advancement
- **User controls advancement, not the LLM** — no auto-advance
- When Reachy senses a stage is complete, it:
  1. Speaks a brief summary of what was covered
  2. Tells the user which stage comes next
  3. Says exactly: "Whenever you're ready, just say 'I'm ready to move on to the next stage' and we'll continue."
- Keywords in `ADVANCE_KEYWORDS` are intentionally strict to avoid false positives
- Stage saved to `stage_state.json` on every transition

### Audio Architecture
- **Unique filenames per turn** (`uuid`) — eliminates file lock conflicts
- **Enter-to-start, Enter-to-stop** — background thread records while main thread waits
- **0.5s delay** at start of `record_audio()` — prevents TTS audio bleed into recording
- **edge-tts saves as MP3** — pygame handles MP3 playback (soundfile was incompatible)
- **File size check** before playback — skips corrupt/empty MP3s silently
- Mic check on startup warns if volume is too low

### Context-Aware Thinking Phrases
- After transcription, check if user's message ends with `?`
- Questions → `THINKING_PHRASES_QUESTION` ("Good question, give me a moment...")
- Statements → `THINKING_PHRASES_STATEMENT` ("Got it, just a moment...")

### Robot Behaviors
- All movement logic lives in `behaviors.py` — imported into `reachy_chat.py`
- Poses are categorized by conversational moment (thinking, listening, talking, idle, mood)
- Talking animation runs in a background thread while TTS plays — stops cleanly when done
- All movement functions silently ignore errors to prevent crashing the conversation

### Dashboard IPC
- **File-based IPC via `dashboard_state.json`** — works across separate OS processes
- Atomic writes using `.tmp` → `os.replace()` — prevents partial reads
- Version counter drives long-polling — zero unnecessary requests
- Flask must run with `threaded=True` for long-polling to work

### Stage Timer
- `stage_started_at` unix timestamp stored in `dashboard_state.json` when stage begins
- `stage_times` dict records elapsed seconds for each completed stage on transition
- Dashboard renders completed stages as green bars with locked time
- Active stage ticks live every second via JS `setInterval`

### Transcript Merging
- Each CPS problem gets a unique `session_id` stored in `session_id.json`
- Transcript file is `sessions/session_<id>.md`
- Continuing a session appends with `## Session continued — [timestamp]`
- Starting fresh generates a new session ID and a new transcript file

---

## Known Issues & Limitations

### Ollama Quality
Ollama does not reliably follow the CPS knowledge base instructions, ignores artifact tags,
and produces markdown formatting that sounds bad when spoken.
**Solution: Use Claude API for real sessions and demos.**

### VAD Voice Input (Not Yet Implemented)
Continuous voice activity detection was attempted but failed on Windows — `sd.InputStream`
and `sd.play()` cannot coexist.
**Next attempt: use `pyaudio` instead of `sounddevice` for the VAD recording stream.**

### Artifact Extraction
The artifacts panel in the dashboard only fills reliably when Claude API is used.
Ollama ignores the `ARTIFACT_*:` tags in the system prompt.

---

## Professor's Architecture Recommendations

1. **Separate divergent/convergent modes** — LLM should suppress evaluative language during Ideate
2. **Explicit CPS workflow state machine** — track stage, objective, timebox, participation state
3. **Artifact layer** — shared screen captures ideas and outputs ✅ implemented
4. **Low-interruption model** — short utterances, human lead / robot support
5. **Fallback/recovery** — handle ASR errors, repeatable prompts, safe idle state
6. **Measure facilitation quality** — not just robot likability

**5-layer architecture:**
- Layer 1: CPS workflow engine (state machine) — partial
- Layer 2: Facilitation policy (when to ask, summarize, redirect) — partial
- Layer 3: Robot behavior layer (speech, gesture, gaze) ✅ implemented via behaviors.py
- Layer 4: Artifact layer (dashboard) ✅ implemented
- Layer 5: AI layer (LLM for rephrasing/prompts only) ✅ implemented

---

## Hugging Face App Package

The app is also packaged in the official Reachy Mini app format for the HF app store.
Located in a separate `reachy_mini_cps/` folder alongside the dev project.

```
reachy_mini_cps/
├── index.html              ← HF Space front page
├── README.md               ← Space metadata and install instructions
├── pyproject.toml          ← Python package config
├── style.css
└── reachy_mini_cps/
    ├── __init__.py
    ├── main.py             ← ReachyMiniCPS(ReachyMiniApp) — entry point
    ├── cps_manager.py      ← bundled copy
    ├── memory_manager.py   ← bundled copy
    ├── dashboard_state.py  ← bundled copy (file-based IPC)
    ├── web_server.py       ← Flask server starts in background thread
    ├── knowledge/          ← CPS stage knowledge base files
    │   ├── clarify.md
    │   ├── ideate.md
    │   ├── develop.md
    │   └── implement.md
    └── static/             ← Dashboard HTML files served by Flask
        ├── index.html
        └── history.html
```

**To publish:**
```powershell
pip install huggingface_hub
huggingface-cli login
reachy-mini-app-assistant publish
```

**Note:** The HF package needs to be kept in sync with the dev project when significant
changes are made. The `behaviors.py` module and latest `dashboard_state.py` (with stage timer)
need to be copied into the HF package before publishing.

---

## Running the App

### Simple (terminal only)
```powershell
uv run reachy-mini-daemon --sim   # Terminal 1
uv run reachy_chat.py             # Terminal 2
```

### With Dashboard (recommended for demos)
```powershell
uv run reachy-mini-daemon --sim   # Terminal 1
uv run launcher.py                # Terminal 2
# Browser: http://localhost:5000
# History: http://localhost:5000/history
```

### Environment Variables
API keys are loaded from a `.env` file in the project root (gitignored, never committed).
Copy `.env.example` to `.env` and fill in your values.

```
ANTHROPIC_API_KEY=your-key-here
```

`REACHY_SESSION_MODE` is set automatically by the launcher — not needed in `.env`.

---

## New Machine Setup (Quick Reference)

```powershell
pip install uv
ollama pull llama3.2:3b
winget install ffmpeg
pip install reachy-mini[mujoco]

git clone https://github.com/tr1ck17/reachy_mini_app.git
cd reachy_mini_app
uv sync
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

---

## Roadmap

### Immediate
- [ ] Full end-to-end Claude API test — all 4 stages in one session
- [ ] Verify dashboard transcript and timer work live
- [ ] Verify stage transition magic phrase works correctly
- [ ] Sync latest changes (behaviors.py, dashboard_state.py timer) into HF package

### Short Term
- [ ] VAD continuous voice input (pyaudio-based, no Enter required)
- [ ] Divergence/convergence mode flags in system prompt per stage
- [ ] Stage-specific robot gestures beyond mood reactions

### Medium Term
- [ ] Dashboard artifact export (download as PDF/doc)
- [ ] ElevenLabs TTS for more natural voice
- [ ] Wake word detection ("Hey Reachy")
- [ ] Publish HF app package

### Long Term / Product Vision
- [ ] Desktop app packaging (PyInstaller + auto-daemon startup)
- [ ] User accounts and multi-problem management
- [ ] Subscription model with API key management
- [ ] Multi-user / group facilitation mode

---

## Contact / Context

- **Platform:** Reachy Mini by Pollen Robotics (now Hugging Face)
- **CPS Framework:** Buffalo State Creative Problem Solving model
- **Academic context:** School project with professor oversight
- **Professor guidance:** Reachy as embodied process scaffolding, not idea generator
- **Key constraint:** Robot should facilitate, not dominate — human makes all decisions
- **GitHub:** https://github.com/tr1ck17/reachy_mini_app