# Reachy Mini — CPS Facilitator

A voice-driven Creative Problem Solving (CPS) facilitator built on the Reachy Mini robot platform. Guides users through all four CPS stages — Clarify, Ideate, Develop, Implement — via continuous voice conversation, expressive robot behaviors, a live web dashboard, and persistent session memory.

---

## What It Does

- **Always-listening VAD** — say "Hey Reachy" to wake it up, speak naturally during CPS
- **Four CPS stages** — Clarify → Ideate → Develop → Implement, fully facilitated by Claude API
- **Expressive robot behaviors** — thinking poses, talking animation, listening tilt, mood reactions, and idle movements
- **Live dashboard** — real-time transcript, artifact capture, stage progress, and stage timer at `localhost:5001`
- **Session memory** — remembers past sessions and resumes where you left off
- **History viewer** — browse all past transcripts at `localhost:5001/history`
- **Enter-to-speak fallback** — always available if VAD isn't needed

---

## Full Setup — From Scratch

Follow these steps in order. Assumes Windows with PowerShell.

### Step 1 — Install Prerequisites

**Git:**
Download and install from [git-scm.com](https://git-scm.com/download/win). Use all default options during installation.

**Python 3.12:**
Download from [python.org](https://www.python.org/downloads/). During installation check **"Add Python to PATH"**.

Verify:
```powershell
python --version
```

**uv (package manager):**
```powershell
pip install uv
```

Verify:
```powershell
uv --version
```

---

### Step 2 — Install the Reachy Mini SDK

```powershell
pip install reachy-mini==1.5.0
```

> ⚠️ Pin to version 1.5.0 exactly. Version 1.6.1 has a breaking change with MuJoCo simulation that crashes on startup.

---

### Step 3 — Get an Anthropic API Key

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Create an account and log in
3. Go to **API Keys** → **Create Key**
4. Copy the key — you'll need it in Step 5

---

### Step 4 — Clone the Repository

```powershell
git clone https://github.com/tr1ck17/reachy_mini_app.git
cd reachy_mini_app
```

---

### Step 5 — Install Dependencies

```powershell
uv sync
```

This installs all Python dependencies into a local `.venv` folder. May take 2-5 minutes on first run.

---

### Step 6 — Create Your .env File

In PowerShell, from inside the `reachy_mini_app` folder:

```powershell
Copy-Item .env.example .env
```

Then open `.env` in any text editor (Notepad, VS Code) and add your API key:

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Save the file.

---

### Step 7 — Find Your Audio Device Index (Reachy Mini Lite)

Plug in your Reachy Mini Lite via USB, then run:

```powershell
uv run python -c "import sounddevice as sd; print(sd.query_devices())"
```

Look for `Echo Cancelling Speakerphone (Reachy Mini Audio)` in the output. Note the index number next to it.

Open `reachy_chat.py` and update these two lines near the top:

```python
REACHY_INPUT_DEVICE = 1      # replace 1 with your actual index
SAMPLE_RATE         = 44100  # leave this as-is
```

Also go to Windows Sound Settings → Output and set **Echo Cancelling Speakerphone (Reachy Mini Audio)** as your default playback device so TTS plays through the robot's speaker.

---

### Step 8 — Install Ollama (Optional — offline fallback LLM)

If you want the app to work without an internet connection or API key:

1. Download from [ollama.com](https://ollama.com)
2. Install and run it
3. Pull the fallback model:

```powershell
ollama pull llama3.2:3b
```

The app automatically falls back to Ollama if the Claude API is unavailable. Note: Ollama on CPU is significantly slower and less reliable for CPS facilitation.

---

## Running the App

### Option A — With Dashboard (recommended)

Open two PowerShell terminals.

**Terminal 1 — choose one:**
```powershell
# If using MuJoCo simulation (no hardware needed):
uv run reachy_chat.py --sim

# If using real Reachy Mini Lite hardware:
uv run reachy_chat.py --real

# If you started the daemon separately already:
uv run reachy_chat.py
```

**Terminal 2:**
```powershell
uv run launcher.py
```

Then open [http://localhost:5001](http://localhost:5001) in your browser.

### Option B — Terminal Only (no dashboard)

```powershell
uv run reachy_chat.py --sim
# or
uv run reachy_chat.py --real
```

---

## How to Use

1. Start the app using Option A or B above
2. If using the dashboard, open `http://localhost:5001` and click **Start New Session**
3. In the terminal, press Enter when prompted
4. Say **"Hey Reachy"** to wake the robot
5. Say **"yes"** when asked if you're ready to begin
6. Speak naturally — VAD handles the rest, no button pressing needed
7. Say **"I'm ready to move on to the next stage"** to advance through CPS stages
8. Type `quit` in the terminal to end the session cleanly

---

## VAD Tuning

If voice detection isn't working well, adjust these constants in `vad.py`:

| Constant | Default | Adjust if... |
|---|---|---|
| `SPEECH_THRESHOLD` | `0.018` | Background noise triggering → raise. Voice not detected → lower |
| `SILENCE_DURATION` | `1.2` | Cuts off too early → raise. Waits too long → lower |
| `NO_SPEECH_THRESHOLD` | `0.5` | Whisper hallucinating words → raise |

To disable VAD entirely and use Enter-to-speak only, simply delete `vad.py` from the project folder. The app falls back automatically.

---

## Tech Stack

| Component | Current | Alternatives |
|---|---|---|
| LLM | Claude API (claude-haiku) | Ollama llama3.2:3b (offline fallback) |
| STT | faster-whisper tiny (local) | Deepgram Nova-2, OpenAI Whisper API, AssemblyAI |
| TTS | edge-tts GuyNeural (free) | ElevenLabs, OpenAI TTS (tts-1-hd), Cartesia Sonic, Kokoro TTS |
| VAD | numpy RMS energy (local) | pvporcupine wake word, AssemblyAI built-in VAD |
| Audio I/O | sounddevice + soundfile | — |
| Web server | Flask (threaded) | flask-socketio (real-time) |

### On STT Alternatives
faster-whisper runs locally for free but adds ~1s transcription delay. **Deepgram Nova-2** is the recommended upgrade — sub-100ms cloud transcription at ~$0.004/minute. **OpenAI Whisper API** is the easiest drop-in at $0.006/minute. Both pair cleanly with Claude API — they only handle transcription.

### On TTS Alternatives
edge-tts is free but sounds synthetic. **ElevenLabs** is the most human-sounding option — free tier covers ~5-6 full CPS sessions/month. **OpenAI TTS (tts-1-hd)** is excellent at ~$15/million characters. **Kokoro TTS** is a free local alternative that runs on CPU. None of these require switching away from Claude API — TTS and LLM are completely independent.

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
├── dashboard_state.py  # File-based IPC between processes
├── index.html          # Launcher + live dashboard UI
├── history.html        # Session history viewer
├── cps/                # CPS stage knowledge bases
│   ├── clarify.md
│   ├── ideate.md
│   ├── develop.md
│   └── implement.md
├── sessions/           # Auto-generated transcript files
├── .env                # Your API keys (gitignored — never commit this)
├── .env.example        # Template for .env
├── pyproject.toml      # Python dependencies
└── PROJECT.md          # Full architecture and design documentation
```

---

## Troubleshooting

**"No module named X" error:**
Run `uv sync` again from inside the `reachy_mini_app` folder.

**Mic not detected or too quiet:**
Re-run the sounddevice query with Reachy plugged in and update `REACHY_INPUT_DEVICE` in `reachy_chat.py`.

**TTS not playing through Reachy:**
Set Echo Cancelling Speakerphone as your default Windows output device in Sound Settings.

**"Cannot change resolution of Mujoco simulated camera":**
You have SDK version 1.6.1 installed. Downgrade: `pip install reachy-mini==1.5.0`

**App crashes on startup with connection error:**
The daemon isn't running. Use `--sim` or `--real` flags to auto-start it, or run `uv run reachy-mini-daemon` in a separate terminal first.

**Wake phrase not triggering:**
Whisper sometimes mishears "Hey Reachy" — try "Wake up", "Daddy's home", or "Hey Richie". You can also press Enter at any time to use manual recording instead.

---

## Important Notes

- **SDK version:** must use `reachy-mini==1.5.0`
- **Wake phrases:** "Hey Reachy", "Wake up", "Daddy's home", "Hey Richie"
- **Stage advance phrase:** "I'm ready to move on to the next stage"
- **Never commit `.env`** — it contains your API key

---

## Roadmap

- [ ] ElevenLabs or OpenAI TTS for more human-sounding voice
- [ ] Deepgram Nova-2 for faster STT
- [ ] Claude API streaming for lower perceived latency
- [ ] Make HF Space public
- [ ] flask-socketio real-time dashboard
- [ ] pvporcupine wake word detection
- [ ] Desktop app packaging (PyInstaller)

---

## License

MIT