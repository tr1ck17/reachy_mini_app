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

**Core interaction loop (VAD mode):**
1. Reachy listens continuously in background via VAD
2. User says a wake phrase ("Hey Reachy", "Wake up", "Daddy's home")
3. Reachy asks "Are you ready to begin the CPS process?"
4. User says yes → CPS begins / User says no → Reachy goes back to sleep
5. User speaks naturally — VAD detects start/end of utterance automatically
6. Reachy hits a thinking pose (question vs statement detection)
7. Context-aware thinking phrase spoken aloud
8. LLM generates a facilitation response (Claude API or Ollama fallback)
9. Mood reaction fires (happy, surprised, thinking, neutral)
10. Talking animation runs while Reachy speaks
11. Dashboard updates with transcript and artifacts in real time
12. VAD resumes listening after Reachy finishes speaking

**Fallback mode (Enter-to-speak):**
- Press Enter to start recording, press Enter again to stop
- Always available — if vad.py is deleted or import fails, app falls back automatically

---

## Hardware Targets

- **Reachy Mini Lite** — connects via USB, daemon runs on host PC
- **Reachy Mini Wireless** — runs onboard RPi CM4, connects via WiFi
- **Simulation** — MuJoCo-based sim, daemon runs on host PC (`uv run reachy-mini-daemon --sim`)

**Note:** SDK version must be pinned to `reachy-mini==1.5.0`. Version 1.6.1 has a breaking
change with MuJoCo simulated camera that crashes on startup.

**Audio device indices (Reachy Mini Lite on this machine):**
- Input: device `1` — Echo Cancelling Speakerphone (Reachy Mini Audio)
- Output: system default (pygame) — set Reachy Mini Audio as Windows default output
- Sample rate: `44100Hz` (Reachy Mini Audio native rate)

---

## Tech Stack

| Component | Technology |
|---|---|
| LLM (primary) | Claude API — `claude-haiku-4-5-20251001` |
| LLM (fallback) | Ollama — `llama3.2:3b` (local, offline) |
| Speech-to-text | faster-whisper `tiny` model (local, offline) |
| Text-to-speech | edge-tts — `en-US-GuyNeural` voice |
| TTS playback | pygame (MP3 format — cross-platform) |
| Audio I/O | sounddevice + soundfile |
| VAD | numpy RMS energy detection (vad.py) |
| Robot SDK | reachy-mini==1.5.0 |
| Web server | Flask (threaded) |
| Package manager | uv |
| Python version | 3.10–3.13 |

---

## File Inventory

### Core Application

**`reachy_chat.py`** — Main entry point:
- VAD mode when `vad.py` is present — continuous listening, wake phrase activation
- Enter-to-speak fallback when VAD unavailable
- Consent flow on startup — Reachy asks if user is ready before CPS begins
- Mic check on startup at 44100Hz using device index 1
- LLM call with Claude API primary, Ollama fallback
- Response parsing — extracts MOOD: and ARTIFACT_*: tags (never spoken)
- Mood reaction + talking animation while speaking
- Dashboard state updates after every exchange
- Stage advancement when user says advance phrase
- LLM-generated stage opening after each transition (not just hardcoded greeting)
- Session ends cleanly with closing message and break after Implement

**`vad.py`** — Voice Activity Detection module:
- Continuous RMS energy detection via sounddevice InputStream
- `SPEECH_THRESHOLD = 0.018` — raise if noise triggers, lower if voice not detected
- `SILENCE_DURATION = 1.2` — seconds of silence before utterance is considered done
- `NO_SPEECH_THRESHOLD = 0.5` — Whisper no_speech_prob filter for hallucinations
- Wake phrase detection with punctuation stripping before matching
- Consent flow after wake — yes continues, no goes back to sleep
- Smart completeness check via Claude API before dispatching utterance
- 18s silence timeout check-in ("Still there?")
- `pause()` drains audio queue — prevents Reachy hearing itself
- Falls back gracefully — delete vad.py to revert to Enter-to-speak

**`behaviors.py`** — Natural movement library:
- `THINKING_QUESTION_POSES` — upward/sideways gaze for questions
- `THINKING_STATEMENT_POSES` — downward/reflective poses for statements
- `talking_animation()` — background thread: head bobs while speaking
- `LISTENING_POSES` — attentive tilt when recording starts
- Mood reactions: happy, surprised, thinking, neutral
- `idle_loop()` — subtle randomized movements every 3-6 seconds
- All functions silently ignore errors to prevent conversation crashes

**`cps_manager.py`** — CPS stage management:
- `STAGES` — `["clarify", "ideate", "develop", "implement"]`
- `ADVANCE_KEYWORDS` — strict list including "i'm ready to move on to the next stage"
- `load_stage()` — reads knowledge base `.md` for current stage
- `build_system_prompt()` — injects stage knowledge into base prompt
- `check_for_advance()` — detects explicit advance phrases

**`memory_manager.py`** — Session persistence:
- Rolling memory: last 5 sessions in `memory.json`
- Stage state: current CPS stage in `stage_state.json`
- Session ID: unique ID per CPS problem in `session_id.json`
- Transcript export: all sessions for one problem in `sessions/session_<id>.md`

**`dashboard_state.py`** — File-based IPC between processes:
- `set_inactive_on_startup()` — called by launcher on start, always shows home page
- `set_stage()` — timestamps stage start, records previous stage time
- `stage_started_at` + `stage_times` — drives live stage timer in dashboard
- Atomic writes via `.tmp` → `os.replace()`
- Version counter drives long-polling efficiency

**`launcher.py`** — Flask web server:
- Always resets `active=False` on startup — browser always opens to home page
- `/api/poll?since=N` — long-poll blocks up to 30s until version > N
- Serves dashboard at `localhost:5001`
- Serves history viewer at `localhost:5001/history`

**`index.html`** — Combined launcher + live dashboard:
- Launcher state: session info, Continue/Start New/History/Clear buttons
- Dashboard state: stage progress, artifacts, live transcript, stage timers
- Stage timer: live ticker for active stage, green bars for completed stages

**`history.html`** — Session history viewer at `localhost:5001/history`

### CPS Knowledge Base

- `cps/clarify.md` — Clarify stage: challenge framing, data gathering, Focus Question
- `cps/ideate.md` — Ideate stage: brainstorming, no consulting, clustering
- `cps/develop.md` — Develop stage: PPCo process (Plusses, Potentials, Concerns, Actions)
- `cps/implement.md` — Implement stage: concrete commitments, timelines, accountability

### Auto-Generated Files (gitignored)

- `memory.json`, `stage_state.json`, `session_id.json` — session persistence
- `dashboard_state.json` — live IPC state
- `sessions/` — markdown transcripts
- `reachy.log` — application log
- `vad_*.wav`, `tts_*.mp3`, `input_*.wav` — temp audio files (auto-deleted)

### Placeholder Files (future features)

- `replace_files_with/_test_reachy_chat.py` — instructions for `--sim`/`--real` CLI args
- `replace_files_with/_test_launcher.py` — instructions for hardware toggle in launcher UI

---

## Key Design Decisions

### VAD Architecture
- **numpy RMS energy detection** — no external VAD dependencies, works cross-platform
- **sounddevice InputStream** — runs at device native rate (44100Hz), no resampling needed
- **Whisper `no_speech_prob` filter** — discards hallucinated transcriptions
- **Punctuation stripping** — "Hey, Reachy." matches "hey reachy" reliably
- **`condition_on_previous_text=False`** — prevents Whisper hallucinating continuations
- **`pause()` drains queue** — prevents Reachy hearing its own TTS output

### LLM Strategy
- Claude API is primary — 1-2s, reliable instruction-following
- Ollama is fallback — free but too slow on CPU, unreliable at complex prompts
- Stage knowledge base injected dynamically at each LLM call
- After stage transitions, LLM generates opening — not just a hardcoded greeting

### Stage Advancement
- User-controlled only — Reachy summarizes, gives magic phrase, waits
- Magic phrase: "Whenever you're ready, just say 'I'm ready to move on to the next stage'"
- After final stage (Implement), session ends cleanly with closing message and break

### Audio Architecture
- Unique filenames per turn (UUID) — eliminates file lock conflicts
- 44100Hz native rate for Reachy Mini Lite mic
- pygame for TTS playback — set Reachy Mini Audio as Windows default output
- File size check before playback — skips corrupt/empty MP3s

### Dashboard IPC
- File-based via `dashboard_state.json` — works across separate OS processes
- Atomic writes using `.tmp` → `os.replace()`
- Long-polling with version counter — zero unnecessary requests
- Launcher always resets `active=False` on startup

---

## Running the App

### With Dashboard (recommended)

```powershell
# Terminal 1
uv run reachy-mini-daemon        # real Lite hardware
# uv run reachy-mini-daemon --sim  # simulation

# Terminal 2
uv run launcher.py

# Browser: http://localhost:5001
# History: http://localhost:5001/history
```

### Without Dashboard

```powershell
uv run reachy-mini-daemon
uv run reachy_chat.py
```

### New Machine Setup

```powershell
git clone https://github.com/tr1ck17/reachy_mini_app.git
cd reachy_mini_app
uv sync
cp .env.example .env
# Edit .env and add ANTHROPIC_API_KEY

# Find audio device indices on this machine:
uv run python -c "import sounddevice as sd; print(sd.query_devices())"
# Update REACHY_INPUT_DEVICE in reachy_chat.py
```

---

## Known Issues & Limitations

- **SDK version** — must use `reachy-mini==1.5.0`. Version 1.6.1 breaks MuJoCo sim camera
- **Audio devices** — device indices change between machines and after reconnecting USB
- **VAD tuning** — thresholds in `vad.py` may need adjustment per environment
- **Ollama quality** — unreliable at following CPS knowledge base on CPU
- **Artifact capture** — only works reliably with Claude API, not Ollama

---

## Roadmap

### Immediate
- [ ] Sync latest changes into HF package
- [ ] Test on desktop machine (clone, uv sync, find audio devices)
- [ ] `--sim` / `--real` CLI args to auto-spawn daemon

### Short Term
- [ ] ElevenLabs or OmniVoice TTS upgrade
- [ ] Publish to Hugging Face app store
- [ ] flask-socketio for real-time dashboard updates

### Long Term
- [ ] Desktop app packaging (PyInstaller)
- [ ] Multi-user group facilitation mode
- [ ] Wake word via pvporcupine ("Hey Reachy")

---

## Contact / Context

- **Platform:** Reachy Mini by Pollen Robotics (now Hugging Face)
- **CPS Framework:** Buffalo State Creative Problem Solving model
- **Academic context:** School project with Professor Zhang
- **GitHub:** https://github.com/tr1ck17/reachy_mini_app