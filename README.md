# Reachy Mini — CPS Facilitator

A voice-driven Creative Problem Solving (CPS) facilitator built on the Reachy Mini robot platform. Guides users through all four CPS stages — Clarify, Ideate, Develop, Implement — via natural voice conversation, expressive robot behaviors, a live web dashboard, and persistent session memory.

---

## What It Does

- **Voice-driven conversation** — Press Enter to speak, press Enter again to send
- **Four CPS stages** — Clarify → Ideate → Develop → Implement, fully facilitated by Claude API
- **Expressive robot behaviors** — Thinking poses, talking animation, listening pose, idle movements, mood reactions
- **Live dashboard** — Real-time transcript, artifact capture, stage progress, and stage timer at `localhost:5001`
- **Session memory** — Remembers past sessions and resumes where you left off
- **History viewer** — Browse all past transcripts at `localhost:5001/history`

---

## Requirements

- Python 3.10–3.13
- [uv](https://docs.astral.sh/uv/) package manager
- Reachy Mini robot (Lite via USB, Wireless via WiFi, or MuJoCo simulation)
- Anthropic API key (Claude API)
- Windows (tested), macOS/Linux should work with minor audio device changes

---

## Setup

```powershell
# 1. Clone the repo
git clone https://github.com/tr1ck17/reachy_mini_app.git
cd reachy_mini_app

# 2. Install dependencies
uv sync

# 3. Set up your API key
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# 4. Pull Ollama fallback model (optional)
ollama pull llama3.2:3b
```

---

## Running the App

### With Dashboard (recommended)

```powershell
# Terminal 1 — start the Reachy daemon
uv run reachy-mini-daemon --sim      # simulation
# uv run reachy-mini-daemon           # real hardware

# Terminal 2 — start the launcher
uv run launcher.py

# Then open http://localhost:5001 in your browser
```

### Without Dashboard (terminal only)

```powershell
# Terminal 1
uv run reachy-mini-daemon --sim

# Terminal 2
uv run reachy_chat.py
```

---

## Audio Setup (Reachy Mini Lite)

The app targets the Reachy Mini Lite audio devices explicitly. If your device indices differ, run:

```powershell
uv run python -c "import sounddevice as sd; print(sd.query_devices())"
```

Then update these constants in `reachy_chat.py`:

```python
REACHY_INPUT_DEVICE  = 1     # Echo Cancelling Speakerphone - input
REACHY_OUTPUT_DEVICE = 12    # Echo Cancelling Speakerphone - output
SAMPLE_RATE          = 44100
```

---

## How to Use

1. Start the daemon and launcher (see above)
2. Open `http://localhost:5001` in your browser
3. Click **Start New Session** or **Continue Session**
4. In the terminal: press Enter when prompted and say you're ready
5. Speak your message, press Enter again to send
6. Reachy facilitates through all four CPS stages
7. Say **"I'm ready to move on to the next stage"** to advance stages
8. Type `quit` to end the session cleanly

---

## Project Structure

```
reachy_mini_app/
├── reachy_chat.py          # Main app entry point
├── launcher.py             # Flask server — launcher UI + dashboard
├── behaviors.py            # Robot movement library
├── cps_manager.py          # CPS stage management + advance keywords
├── memory_manager.py       # Session persistence + transcript export
├── dashboard_state.py      # File-based IPC between processes
├── index.html              # Combined launcher + live dashboard UI
├── history.html            # Session history viewer
├── cps/
│   ├── clarify.md          # Clarify stage knowledge base
│   ├── ideate.md           # Ideate stage knowledge base
│   ├── develop.md          # Develop stage knowledge base
│   └── implement.md        # Implement stage knowledge base
├── sessions/               # Transcript .md files (auto-generated)
├── .env                    # API keys (gitignored)
├── .env.example            # Template for .env
├── pyproject.toml          # Dependencies
└── PROJECT.md              # Full project documentation
```

---

## Environment Variables

```
ANTHROPIC_API_KEY=your-key-here
```

`REACHY_SESSION_MODE` is set automatically by the launcher — do not set manually.

---

## LLM Backends

| Backend | Speed | Quality | Cost |
|---|---|---|---|
| Claude API (primary) | ~1-2s | Excellent | ~$0.01/session |
| Ollama llama3.2:3b (fallback) | 1-4min (CPU) / 5-30s (GPU) | Moderate | Free |

Claude API is strongly recommended for real sessions. Ollama is useful for offline development.

---

## CPS Stage Flow

```
Clarify → Ideate → Develop → Implement
```

Each stage is facilitated by Claude using a dedicated knowledge base file injected into the system prompt. Stage advancement is always user-controlled — say **"I'm ready to move on to the next stage"** when prompted.

---

## Roadmap

- [ ] VAD continuous voice input (no Enter required)
- [ ] ElevenLabs TTS for better voice quality
- [ ] `--sim` / `--real` CLI args to auto-spawn daemon
- [ ] Publish to Hugging Face app store
- [ ] flask-socketio for real-time dashboard updates

---

## License

MIT