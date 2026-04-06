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
2. User speaks
3. User presses Enter again to stop recording
4. Whisper transcribes locally
5. Reachy plays a context-aware thinking phrase (question vs statement detection)
6. LLM generates a facilitation response (Claude API or Ollama fallback)
7. edge-tts speaks the response aloud
8. Reachy Mini moves expressively based on detected mood
9. Dashboard updates with transcript and artifacts in real time
10. Idle animations resume while waiting for next input

---

## Hardware Targets

- **Reachy Mini Wireless** — runs onboard RPi 4, connects via WiFi
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
| Audio I/O | sounddevice + soundfile |
| Robot SDK | reachy-mini (Python SDK + MuJoCo sim) |
| Web server | Flask |
| Package manager | uv |
| Python version | 3.10–3.13 |

---

## File Inventory

### Core Application

**`reachy_chat.py`** — Main entry point. Handles the full conversation loop:
- Mic check on startup — 1 second recording to verify mic is working
- Session mode selection (continue vs fresh) via terminal prompt or `REACHY_SESSION_MODE` env var
- Idle animations — background thread runs subtle robot movements while waiting for input
- Audio recording with Enter-to-start, Enter-to-stop using a background thread
- Whisper transcription with unique temp filenames (avoids file lock conflicts)
- Context-aware thinking phrases — detects if user's message ends with `?` and picks
  from `THINKING_PHRASES_QUESTION` or `THINKING_PHRASES_STATEMENT` accordingly
- LLM call with Claude API primary, Ollama fallback
- Response parsing — extracts MOOD: tag and ARTIFACT_*: tags
- Robot expression based on mood
- Dashboard state updates after every exchange
- Stage advancement when user says explicit advance phrases
- Stage-specific greetings on transition (randomized per stage)
- Session summary spoken on quit
- Session saving and transcript export on exit (including Ctrl+C)

**`cps_manager.py`** — CPS stage management:
- `STAGES` — ordered list: `["clarify", "ideate", "develop", "implement"]`
- `ADVANCE_KEYWORDS` — intentionally strict list of phrases that trigger stage advance
  (avoids false positives from normal conversation words like "ready" or "advance")
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

**`dashboard_state.py`** — Shared in-memory state between `reachy_chat.py` and `launcher.py`:
- Thread-safe using a lock
- Version counter — increments on every state change
- Tracks: active flag, current stage, live transcript, artifacts per stage
- Artifact types: challenge statement, focus question, ideas, clusters, plusses,
  potentials, concerns, action steps, committed actions

**`launcher.py`** — Flask web server:
- Serves `index.html` at `localhost:5000`
- Serves `history.html` at `localhost:5000/history`
- `/api/session-info` — reads memory/stage/session files for the launcher UI
- `/api/launch` — launches `reachy_chat.py` in a new terminal via subprocess
- `/api/clear-history` — deletes memory.json, stage_state.json, session_id.json, all .md transcripts
- `/api/transcripts` — returns list of all transcript files with metadata
- `/api/transcript/<id>` — returns full content of a specific transcript
- `/api/state` — returns full dashboard state immediately
- `/api/poll?since=N` — long-poll endpoint: blocks up to 30s until version > N, then returns state
- `threaded=True` required for long-polling to work correctly

**`index.html`** — Combined launcher + live dashboard (single page, two states):
- **Launcher state**: session info card, Continue/Start New/View History/Clear History buttons
- **Dashboard state**: transitions automatically when session goes active
  - Top bar: live dot, session title, stage progress indicator
  - Left panel: artifacts (challenge, focus question, ideas, clusters, PPCo, actions)
  - Center panel: live scrolling transcript (you + Reachy turns)
  - Right panel: current stage description + session stats
- Long-poll loop keeps dashboard updated without unnecessary requests
- "Don't show again" for clear history confirmation stored in localStorage

**`history.html`** — Session history viewer:
- Lists all past session transcripts with date, preview, exchange count, session count
- Search bar filters transcripts in real time
- Clicking a session loads full transcript rendered as a chat UI
- Session break markers shown between continued sessions
- Back button returns to launcher
- Accessible at `localhost:5000/history`

### CPS Knowledge Base

**`cps/clarify.md`** — Clarify stage facilitation guide:
- Challenge Statement framing ("It would be great if I/we...")
- Gather Data questions (why, what tried, success, who, obstacles, opportunities)
- Creative Questions ("What might be all the ways to...")
- Focus Question landing
- Divergence rules: no evaluation, wide exploration
- Transition signals and language

**`cps/ideate.md`** — Ideate stage facilitation guide:
- CRITICAL RULES section explicitly forbidding consulting/implementation advice
- Brainstorm sprint: 20-30+ verb-first ideas
- Redirection phrases for when conversation drifts into consulting
- Clustering into 2-3 action-oriented theme headings
- Develop Statement: "What I see myself doing is..."
- Strong divergence rules: no evaluation until clustering

**`cps/develop.md`** — Develop stage facilitation guide:
- PPCo process: Plusses, Potentials, Concerns, action steps
- Concern reframing: "How to..." format
- Resource group of real figures for generating action steps
- 10 action steps per concern, verb-first
- Hit identification and reframing: "In order to [concern], I will [action]"
- Convergence rules: evaluation now appropriate

**`cps/implement.md`** — Implement stage facilitation guide:
- Confirm the plan
- First steps with specificity (when, how long)
- Resources, support, obstacles
- Accountability and success metrics
- Warm close — final stage, end meaningfully
- Strong convergence rules

### Auto-Generated Files (gitignored)

- `memory.json` — rolling session memory (last 5 sessions)
- `stage_state.json` — current CPS stage
- `session_id.json` — current problem's session ID
- `sessions/` — transcript `.md` files, one per CPS problem
- `reachy.log` — detailed application log
- `input_*.wav`, `tts_*.wav` — temporary audio files (deleted after each turn)

---

## Key Design Decisions

### LLM Strategy
- **Claude API is primary** — significantly better instruction-following, 1-2s response time
- **Ollama is fallback** — free and offline but slow on CPU (minutes per response) and
  unreliable at following complex system prompts
- **Do not rely on Ollama for artifact extraction or stage control** — it ignores these reliably
- Claude model: `claude-haiku-4-5-20251001` — fastest/cheapest Claude model, sufficient quality

### Stage Advancement
- **User controls advancement, not the LLM** — removed `ADVANCE: yes` auto-trigger
- Reachy asks if user is ready to move on when it senses stage is complete
- User says explicit phrase → `check_for_advance()` catches it → stage advances
- Keywords are intentionally strict to avoid false positives (e.g., "ready" alone does NOT trigger)

### Audio Architecture
- **Unique filenames per turn** (`uuid`) — eliminates file lock conflicts that caused dropped responses
- **Enter-to-start, Enter-to-stop** — background thread records while main thread waits for Enter
- **MIN_AUDIO_VOLUME = 0.0005** — lowered to avoid dropping out at normal mic distance
- **0.5s delay** at start of `record_audio()` — prevents TTS bleed into next recording
- Mic check on startup — warns user if volume too low before session begins

### Context-Aware Thinking Phrases
- After transcription, check if user's message ends with `?`
- Questions → `THINKING_PHRASES_QUESTION` ("Good question, give me a moment...")
- Statements → `THINKING_PHRASES_STATEMENT` ("Got it, just a moment...")
- Prevents unnatural "Good question..." responses to statements

### Idle Animations
- Background thread runs while waiting for user input
- Subtle head tilts, antenna bobs, gentle look-up movements
- Stops immediately when user presses Enter, resumes after Reachy finishes speaking
- Makes robot feel alive rather than frozen between turns

### Transcript Merging
- Each CPS problem gets a unique `session_id` stored in `session_id.json`
- Transcript file is `sessions/session_<id>.md`
- Continuing a session appends to the same file with `## Session continued — [timestamp]`
- Starting fresh generates a new session ID and a new transcript file
- History viewer renders all transcripts as readable chat UI

### Dashboard Long-Polling
- Frontend polls `/api/poll?since=N` — server blocks until version > N (up to 30s)
- On state change, server returns immediately with new data
- Client updates and immediately re-polls
- Zero unnecessary requests — only fires when something actually changes
- Flask must run with `threaded=True` for this to work

---

## Known Issues & Limitations

### Ollama Quality
Ollama (`llama3.2:3b`) does not reliably follow the CPS knowledge base instructions.
It drifts into consulting mode during Ideate, ignores artifact tags, and responds
in markdown formatting (headers, bullet points) which sounds terrible when spoken.
**Solution: Use Claude API for any real testing or demo.**

### Response Latency (Ollama)
On CPU without GPU, Ollama takes 1-4 minutes per response as context window grows.
This is unacceptable for a real demo.
**Solution: Claude API (1-2s), or NVIDIA GPU (Ollama uses CUDA automatically).**

### VAD Voice Input (Not Yet Implemented)
Continuous voice activity detection (no Enter required) was attempted with `webrtcvad`
and `sounddevice` but failed due to Windows audio device conflicts — `sd.InputStream`
and `sd.play()` cannot coexist on Windows.
**Next attempt: use `pyaudio` instead of `sounddevice` for the VAD recording stream.**

### Artifact Extraction Dependency
The artifacts panel in the dashboard only fills when Claude API is used.
Ollama ignores the `ARTIFACT_*:` tags in the system prompt.

---

## Professor's Architecture Recommendations (from email)

The project advisor provided these architectural recommendations:

1. **Separate divergent/convergent modes** — LLM should suppress evaluative language during Ideate
2. **Explicit CPS workflow state machine** — track stage, objective, timebox, participation state, artifacts
3. **Artifact layer** — shared screen captures ideas and outputs (implemented via dashboard)
4. **Low-interruption model** — short utterances, human lead / robot support
5. **Fallback/recovery** — handle ASR errors, repeatable prompts, safe idle state
6. **Measure facilitation quality** — not just robot likability

**Recommended 5-layer architecture:**
- Layer 1: CPS workflow engine (state machine)
- Layer 2: Facilitation policy (when to ask, summarize, redirect)
- Layer 3: Robot behavior layer (speech, gesture, gaze)
- Layer 4: Artifact layer (dashboard) ✅ implemented
- Layer 5: AI layer (LLM for rephrasing/prompts only, not control) ✅ implemented

---

## Roadmap

### Immediate
- [ ] Get Claude API credits and do a full end-to-end test (all 4 stages in one session)
- [ ] Verify dashboard artifact extraction works with Claude API
- [ ] Test Continue session flow end-to-end

### Short Term
- [ ] VAD continuous voice input (pyaudio-based, no Enter required)
- [ ] Divergence/convergence mode flags in system prompt per stage
- [ ] Stage-specific robot gestures (not just mood-based)
- [ ] Facilitation intensity controls (pause/override)

### Medium Term
- [ ] Dashboard artifact export (download session artifacts as PDF/doc)
- [ ] Proper CPS workflow state machine (timebox, participation tracking)
- [ ] ElevenLabs TTS for more natural voice (currently edge-tts)
- [ ] Wake word detection ("Hey Reachy")

### Long Term / Product Vision
- [ ] Desktop app packaging (PyInstaller + auto-daemon startup)
- [ ] User accounts and multi-problem management
- [ ] Subscription model with API key management
- [ ] Multi-user / group facilitation mode
- [ ] Integration with external tools (Miro, Notion, Google Docs)

---

## Running the App

### Simple (terminal only)
```powershell
# Terminal 1
uv run reachy-mini-daemon --sim

# Terminal 2
uv run reachy_chat.py
```

### With Dashboard (recommended for demos)
```powershell
# Terminal 1
uv run reachy-mini-daemon --sim

# Terminal 2
uv run launcher.py

# Browser
http://localhost:5000          ← launcher + dashboard
http://localhost:5000/history  ← session history viewer
```

### Environment Variables
API keys are loaded from a `.env` file in the project root (gitignored, never committed).
Copy `.env.example` to `.env` and fill in your values.

```powershell
# .env file contents:
ANTHROPIC_API_KEY=your-key-here   # enables Claude API (strongly recommended)
```

The following are set automatically by the launcher (not needed in .env):
```powershell
$env:REACHY_SESSION_MODE="continue"   # set by launcher, skip terminal prompt
$env:REACHY_SESSION_MODE="new"        # set by launcher for fresh sessions
```

---

## New Machine Setup (Quick Reference)

```powershell
# Prerequisites: Python 3.10+, Git, uv, Ollama, ffmpeg, reachy-mini[mujoco]
pip install uv
ollama pull llama3.2:3b
winget install ffmpeg
pip install reachy-mini[mujoco]

# Clone and install
git clone https://github.com/YOURUSERNAME/reachy_mini_app.git
cd reachy_mini_app
uv sync

# Set up API key
cp .env.example .env
# Then edit .env and add your ANTHROPIC_API_KEY
```

See `README.md` for full setup instructions.

---

## Contact / Context

- **Platform:** Reachy Mini by Pollen Robotics (now Hugging Face)
- **CPS Framework:** Buffalo State Creative Problem Solving model
- **Academic context:** School project with professor oversight
- **Professor guidance:** Reachy as embodied process scaffolding, not idea generator
- **Key constraint:** Robot should facilitate, not dominate — human makes all decisions