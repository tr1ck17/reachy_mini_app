# Reachy Mini — CPS Facilitator

A voice-driven Creative Problem Solving (CPS) facilitator built on the Reachy Mini robot platform. Guides users through all four CPS stages — Clarify, Ideate, Develop, Implement — via continuous voice conversation, expressive robot behaviors, a live web dashboard, and persistent session memory.

---

## What It Does

- **Always-listening VAD** — say "Hey Reachy" to wake it up, speak naturally during CPS
- **Four CPS stages** — Clarify → Ideate → Develop → Implement, fully facilitated by Claude API
- **Expressive robot behaviors** — thinking poses, talking animation, listening pose, idle movements, mood reactions
- **Live dashboard** — real-time transcript, artifact capture, stage progress, and stage timer at `localhost:5001`
- **Session memory** — remembers past sessions and resumes where you left off
- **History viewer** — browse all past transcripts at `localhost:5001/history`
- **Enter-to-speak fallback** — always available if VAD isn't needed

---

## Requirements

- Python 3.10–3.13
- [uv](https://docs.astral.sh/uv/) package manager
- Reachy Mini (Lite via USB, Wireless via WiFi, or MuJoCo simulation)
- Anthropic API key

---

## Setup

```powershell
git clone https://github.com/tr1ck17/reachy_mini_app.git
cd reachy_mini_app
uv sync
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY
```

---

## Running

### With Dashboard (recommended)
```powershell
# Terminal 1
uv run reachy-mini-daemon        # real hardware
# uv run reachy-mini-daemon --sim  # simulation

# Terminal 2
uv run launcher.py
# Open http://localhost:5001
```

### Without Dashboard
```powershell
uv run reachy-mini-daemon
uv run reachy_chat.py
```

---

## Audio Setup (Reachy Mini Lite)

Find your device indices:
```powershell
uv run python -c "import sounddevice as sd; print(sd.query_devices())"
```

Update in `reachy_chat.py`:
```python
REACHY_INPUT_DEVICE = 1      # your Reachy mic index
SAMPLE_RATE         = 44100  # Reachy Mini Audio native rate
```

Set Reachy Mini Audio as your Windows default output device for TTS playback through the robot.

---

## How to Use

1. Start the daemon and launcher
2. Open `http://localhost:5001` and click **Start New Session**
3. Say **"Hey Reachy"** to wake the robot
4. Say **"yes"** when asked if you're ready to begin
5. Speak naturally — VAD handles the rest
6. Say **"I'm ready to move on to the next stage"** to advance stages
7. Type `quit` in the terminal to end the session

---

## VAD Tuning

If the voice detection isn't right, adjust these constants in `vad.py`:

| Constant | Default | Adjust if... |
|---|---|---|
| `SPEECH_THRESHOLD` | `0.018` | Too much noise triggering → raise. Voice not detected → lower |
| `SILENCE_DURATION` | `1.2` | Cuts off too early → raise. Too slow → lower |
| `NO_SPEECH_THRESHOLD` | `0.5` | Whisper hallucinating → raise |

---

## Project Structure

```
reachy_mini_app/
├── reachy_chat.py      # Main app — VAD + conversation loop
├── vad.py              # Voice activity detection module
├── launcher.py         # Flask server — launcher + dashboard
├── behaviors.py        # Robot movement library
├── cps_manager.py      # CPS stage management
├── memory_manager.py   # Session persistence
├── dashboard_state.py  # File-based IPC
├── index.html          # Launcher + live dashboard UI
├── history.html        # Session history viewer
├── cps/                # CPS stage knowledge bases
│   ├── clarify.md
│   ├── ideate.md
│   ├── develop.md
│   └── implement.md
├── sessions/           # Transcript files (auto-generated)
├── .env                # API keys (gitignored)
├── .env.example        # Template
└── PROJECT.md          # Full project documentation
```

---

## Important Notes

- **SDK version:** must use `reachy-mini==1.5.0` — version 1.6.1 has a breaking change with MuJoCo simulation
- **Wake phrases:** "Hey Reachy", "Wake up", "Daddy's home", "Hey Richie" (Whisper mishear)
- **Stage advance phrase:** "I'm ready to move on to the next stage"

---

## License

MIT