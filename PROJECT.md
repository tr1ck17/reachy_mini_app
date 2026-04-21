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
- **Simulation** — MuJoCo-based sim, daemon runs on host PC (`uv run reachy_chat.py --sim`)

**Note:** SDK version must be pinned to `reachy-mini==1.5.0`. Version 1.6.1 has a breaking
change with MuJoCo simulated camera that crashes on startup.

**Audio device indices (Reachy Mini Lite on this machine):**
- Input: device `1` — Echo Cancelling Speakerphone (Reachy Mini Audio)
- Output: system default (pygame) — set Reachy Mini Audio as Windows default output
- Sample rate: `44100Hz` (Reachy Mini Audio native rate)

---

## Tech Stack

| Component | Current Implementation | Notes |
|---|---|---|
| LLM (primary) | Claude API — `claude-haiku-4-5-20251001` | Best instruction-following for CPS |
| LLM (fallback) | Ollama — `llama3.2:3b` (local, offline) | Too slow on CPU for real sessions |
| STT | faster-whisper `tiny` model (local, offline) | Free, slight delay — see alternatives below |
| TTS | edge-tts — `en-US-GuyNeural` voice | Free, decent quality — see alternatives below |
| TTS playback | pygame (MP3 format) | Cross-platform |
| Audio I/O | sounddevice + soundfile | — |
| VAD | numpy RMS energy detection (vad.py) | No external dependencies |
| Robot SDK | reachy-mini==1.5.0 | Pinned — 1.6.1 breaks sim camera |
| Web server | Flask (threaded) | Launcher + dashboard |
| Package manager | uv | — |
| Python version | 3.10–3.13 | — |

---

## STT — Current and Alternatives

The current STT pipeline transcribes locally using faster-whisper running on CPU. This is
free and offline but adds a transcription delay between the user finishing speaking and
Claude receiving the text.

**Current:** `faster-whisper tiny` — local CPU inference, ~0.5-1s transcription delay,
good accuracy for English, free.

**Recommended upgrade — Deepgram Nova-2:**
- Cloud-based, sub-100ms transcription
- ~$0.004/minute — essentially free for personal use
- Handles accents and noise better than local Whisper
- Drop-in replacement: swap the `_transcribe()` call in `vad.py` with a Deepgram API call
- Would noticeably speed up the conversation loop

**Other alternatives:**
- **OpenAI Whisper API** — same model, runs on OpenAI servers. $0.006/minute. Easiest drop-in.
- **AssemblyAI** — solid accuracy, has built-in VAD which could replace our custom VAD module entirely
- **faster-whisper small/medium** — same local approach but better accuracy at cost of more CPU/RAM

---

## TTS — Current and Alternatives

The current TTS pipeline uses Microsoft's edge-tts which generates MP3 files via a free
cloud API and plays them back through pygame. The quality is decent but sounds clearly
synthetic in longer utterances.

**Current:** `edge-tts GuyNeural` — free Microsoft Neural TTS, decent quality, ~0.5s
generation time per response.

**Recommended upgrade — ElevenLabs:**
- Genuinely human-sounding speech, handles emotion and pacing naturally
- Huge voice library, voice cloning available
- Free tier: 10,000 characters/month (~5-6 full CPS sessions)
- $5/month for 30,000 characters after that
- Drop-in replacement: swap `_speak_async()` in `reachy_chat.py` with ElevenLabs API call
- Would make the single biggest perceptible improvement to how the app feels

**Other alternatives:**
- **OpenAI TTS (tts-1-hd)** — very natural, fast, $15/million characters (extremely cheap)
- **Cartesia Sonic** — newer, designed for real-time use, very low latency
- **OmniVoice (k2-fsa)** — open source, 600+ languages, voice cloning, requires GPU

**Implementation note:** Both ElevenLabs and OpenAI TTS are straightforward API swaps.
The `speak()` function in `reachy_chat.py` is isolated enough that swapping TTS backends
requires changing only that function and adding the relevant API key to `.env`.

---

## File Inventory

### Core Application

**`reachy_chat.py`** — Main entry point:
- VAD mode when `vad.py` is present — continuous listening, wake phrase activation
- `--sim` and `--real` CLI flags to auto-spawn daemon (no separate terminal needed)
- Enter-to-speak fallback when VAD unavailable
- Consent flow on startup — Reachy asks if user is ready before CPS begins
- Mic check on startup at 44100Hz using device index 1
- LLM call with Claude API primary, Ollama fallback
- Response parsing — extracts MOOD: and ARTIFACT_*: tags (never spoken)
- Mood reaction + talking animation while speaking
- Dashboard state updates after every exchange
- Stage advancement when user says advance phrase
- LLM-generated stage opening after each transition
- Session ends cleanly with closing message and break after Implement

**`vad.py`** — Voice Activity Detection module:
- Continuous RMS energy detection via sounddevice InputStream
- `SPEECH_THRESHOLD = 0.018` — raise if noise triggers, lower if voice not detected
- `SILENCE_DURATION = 1.2` — seconds of silence before utterance is considered done
- `NO_SPEECH_THRESHOLD = 0.5` — Whisper no_speech_prob filter for hallucinations
- Wake phrase detection with punctuation stripping before matching
- Consent flow after wake — yes continues, no goes back to sleep
- Smart completeness check via Claude API before dispatching utterance
- 18s silence timeout check-in
- `pause()` drains audio queue — prevents Reachy hearing itself

**`behaviors.py`** — Natural movement library

**`cps_manager.py`** — CPS stage management

**`memory_manager.py`** — Session persistence

**`dashboard_state.py`** — File-based IPC between processes

**`launcher.py`** — Flask web server (port 5001)

**`index.html`** — Combined launcher + live dashboard

**`history.html`** — Session history viewer

### CPS Knowledge Base

- `cps/clarify.md` — Clarify stage knowledge base
- `cps/ideate.md` — Ideate stage knowledge base
- `cps/develop.md` — Develop stage knowledge base
- `cps/implement.md` — Implement stage knowledge base

---

## Key Design Decisions

### VAD Architecture
- numpy RMS energy detection — no external VAD dependencies
- sounddevice InputStream at 44100Hz native rate
- Whisper `no_speech_prob` filter discards hallucinations
- Punctuation stripping before wake phrase matching
- `condition_on_previous_text=False` prevents Whisper hallucinating continuations
- `pause()` drains queue — prevents Reachy hearing its own TTS output

### LLM Strategy
- Claude API is primary — 1-2s, reliable instruction-following for CPS structure
- Ollama is fallback — free but too slow on CPU, unreliable at complex prompts
- Stage knowledge base injected dynamically at each LLM call
- After stage transitions, LLM generates opening — not hardcoded greeting

### Stage Advancement
- User-controlled only — Reachy summarizes, gives magic phrase, waits
- After final stage (Implement), session ends cleanly with break

### Audio Architecture
- Unique filenames per turn (UUID) — eliminates file lock conflicts
- 44100Hz native rate for Reachy Mini Lite mic
- pygame for TTS playback — set Reachy Mini Audio as Windows default output

### Dashboard IPC
- File-based via `dashboard_state.json` — works across separate OS processes
- Atomic writes using `.tmp` → `os.replace()`
- Long-polling with version counter
- Launcher always resets `active=False` on startup

---

## Running the App

```powershell
# Recommended — one terminal
uv run reachy_chat.py --sim     # simulation
uv run reachy_chat.py --real    # Lite hardware

# With dashboard
uv run launcher.py              # http://localhost:5001
```

---

## Known Issues & Limitations

- **SDK version** — must use `reachy-mini==1.5.0`
- **Audio devices** — device indices change between machines and after reconnecting USB
- **VAD tuning** — thresholds in `vad.py` may need adjustment per environment
- **Ollama quality** — unreliable at following CPS knowledge base on CPU
- **TTS quality** — edge-tts sounds synthetic; ElevenLabs or OpenAI TTS recommended upgrade

---

## Roadmap

### Audio Quality (High Priority)
- [ ] ElevenLabs TTS — most impactful single upgrade for realism
- [ ] OpenAI TTS (tts-1-hd) — cheaper alternative with similar quality improvement
- [ ] Deepgram Nova-2 STT — faster transcription, better accuracy

### Infrastructure
- [ ] Make HF Space public
- [ ] Test HF package on real hardware end-to-end
- [ ] flask-socketio for real-time dashboard updates

### Features
- [ ] pvporcupine wake word detection
- [ ] Desktop app packaging (PyInstaller)
- [ ] Multi-user group facilitation mode

---

## Contact / Context

- **Platform:** Reachy Mini by Pollen Robotics (now Hugging Face)
- **CPS Framework:** Buffalo State Creative Problem Solving model
- **Academic context:** School project with Professor Zhang
- **GitHub:** https://github.com/tr1ck17/reachy_mini_app
- **HF Space:** https://huggingface.co/spaces/tr1ck17/cps_reachy_mini