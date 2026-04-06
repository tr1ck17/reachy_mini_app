# Reachy Mini — CPS Facilitator

A voice-powered Creative Problem Solving facilitator built on the Reachy Mini robot platform.
Uses a local or cloud LLM to guide users through the four stages of CPS (Clarify, Ideate, Develop, Implement)
with expressive robot behaviors, live dashboard, session history, and rolling session memory.

---

## Prerequisites

Install all of the following before cloning the project.

### 1. Python 3.10–3.13
Download from [python.org](https://python.org). During installation, check **"Add Python to PATH"**.

### 2. Git
Download from [git-scm.com](https://git-scm.com).

### 3. uv (Python package manager)
```powershell
pip install uv
```

### 4. Ollama (local LLM fallback)
Download from [ollama.com](https://ollama.com). After installing, pull the model:
```powershell
ollama pull llama3.2:3b
```
> Ollama auto-starts on Windows — you do not need to run `ollama serve` manually.

### 5. ffmpeg (audio processing)
```powershell
winget install ffmpeg
```
> If winget is unavailable, download from [ffmpeg.org](https://ffmpeg.org) and add to your system PATH.

### 6. Reachy Mini package (simulation support)
```powershell
pip install reachy-mini[mujoco]
```
> The `[mujoco]` extra is required for simulation. For real hardware only, `pip install reachy-mini` is sufficient.

### 7. Enable microphone access
Go to **Settings → Privacy & Security → Microphone** and ensure desktop app access is enabled.

---

## Installation

### Step 1 — Clone the repository
```powershell
git clone https://github.com/YOURUSERNAME/reachy_mini_app.git
cd reachy_mini_app
```
> Replace `YOURUSERNAME` with your actual GitHub username.

### Step 2 — Install Python dependencies
```powershell
uv sync
```
This reads `pyproject.toml` and installs everything into a local virtual environment automatically.

> If `pygame` has issues installing via uv, try: `pip install pygame --break-system-packages`

### Step 3 — Set your Anthropic API key (strongly recommended)
Copy the example env file and fill in your key:
```powershell
cp .env.example .env
```
Then open `.env` and replace `your-api-key-here` with your actual key from [console.anthropic.com](https://console.anthropic.com).

The app reads the key automatically from `.env` on startup. Without it, the app falls back to Ollama
which is significantly slower on CPU and less reliable at following CPS facilitation instructions.

> `.env` is gitignored — your key will never be pushed to GitHub.

### Step 4 — Check for GPU (optional)
```powershell
nvidia-smi
```
If a GPU is detected, Ollama will use it automatically for faster local responses.

---

## Running the App

### Option A — Browser Launcher (recommended)

**Terminal 1 — Start the Reachy daemon:**
```powershell
cd reachy_mini_app
uv run reachy-mini-daemon --sim
```
A MuJoCo window opens showing the 3D robot simulation. **Keep this terminal open for the entire session.**

> For real hardware: power on the Reachy Mini and connect via USB (Lite) or ensure it's on the same
> WiFi network (Wireless). The daemon is not needed for real hardware.

**Terminal 2 — Start the launcher server:**
```powershell
cd reachy_mini_app
uv run launcher.py
```

**Browser — Open the launcher:**
```
http://localhost:5000
```
The launcher shows your last session info and gives you four options:
- **Continue** — resume the previous session (restores stage and memory)
- **Start New Session** — begin fresh with a new CPS problem
- **📖 View Session History** — browse and read all past transcripts
- **🗑 Clear All History** — delete all memory, stage, and transcripts (with confirmation)

---

### Option B — Run Directly from Terminal

```powershell
uv run reachy_chat.py
```
The app will ask at startup whether to continue a previous session or start fresh.

---

## How to Speak

```
1. Press Enter        → starts recording (mic check plays on startup)
2. Speak your message
3. Press Enter again  → stops recording, Reachy responds
```

To exit cleanly, type `quit` and press Enter. Reachy will give a session summary before closing.

### Advancing CPS Stages
Reachy will ask if you're ready to move on when it senses a stage is complete. To advance, say:
- "let's move on"
- "next stage"
- "I'm ready to move on"
- "let's go to the next stage"
- "move forward to the next"

---

## Project Structure

```
reachy_mini_app/
├── cps/
│   ├── clarify.md          ← Clarify stage knowledge base
│   ├── ideate.md           ← Ideate stage knowledge base
│   ├── develop.md          ← Develop stage knowledge base
│   └── implement.md        ← Implement stage knowledge base
├── sessions/               ← auto-created, readable session transcripts
├── cps_manager.py          ← CPS stage tracking and prompt management
├── memory_manager.py       ← Rolling session memory (last 5 sessions)
├── dashboard_state.py      ← Shared state between app and web dashboard
├── reachy_chat.py          ← Main application entry point
├── launcher.py             ← Flask launcher/dashboard server
├── index.html              ← Launcher + live dashboard UI
├── history.html            ← Session history viewer
├── memory.json             ← auto-created, rolling session memory
├── stage_state.json        ← auto-created, saves CPS stage between sessions
├── session_id.json         ← auto-created, tracks current problem's session ID
├── reachy.log              ← auto-created, detailed application log
├── pyproject.toml          ← Python project config and dependencies
├── requirements.txt        ← pip-compatible dependency list
├── PROJECT.md              ← Full architecture and project documentation
└── uv.lock                 ← Locked dependency versions
```

---

## Troubleshooting

### Responses are very slow
- Set `ANTHROPIC_API_KEY` — Claude API drops response time from minutes to seconds
- Run `nvidia-smi` to check for a GPU — Ollama uses it automatically if found
- Try a faster model: `ollama pull qwen2.5:0.5b` then change `OLLAMA_MODEL` in `reachy_chat.py`

### Mic not picking up audio
- Settings → Privacy & Security → Microphone → enable access
- Check Windows Sound settings — correct input device must be selected and not muted
- Disconnect Bluetooth audio devices and test with built-in mic first
- The app runs a mic check on startup and will warn you if volume is too low

### App starts in wrong CPS stage
- Choose **Start Fresh** at the startup prompt or click **Start New Session** in the launcher
- Or manually delete `stage_state.json` and `memory.json` from the project root

### App can't connect to Reachy Mini
- Make sure the daemon terminal is open and running
- For Wireless: PC and Reachy must be on the same WiFi network
- For Lite: check the USB connection

### Daemon won't start
- Run `pip install reachy-mini[mujoco]` to ensure the MuJoCo extra is installed

### Module not found errors
- Run `uv sync` inside the project folder
- Always use `uv run` prefix, not plain `python`

### History page shows no transcripts
- Transcripts are only created after a full session ends (quit cleanly or Ctrl+C)
- Make sure the launcher server is running at `localhost:5000`

---

## Quick Reference

| Task | Command |
|------|---------|
| Clone repo | `git clone https://github.com/YOURUSERNAME/reachy_mini_app.git` |
| Install deps | `uv sync` |
| Set API key | Copy `.env.example` to `.env` and fill in your key |
| Start daemon | `uv run reachy-mini-daemon --sim` |
| Start launcher | `uv run launcher.py` |
| Open launcher | `http://localhost:5000` |
| View history | `http://localhost:5000/history` |
| Run directly | `uv run reachy_chat.py` |

---

## Notes

- Session transcripts are saved to `sessions/` as `.md` files — one file per CPS problem,
  with all sessions for that problem appended together
- The app remembers the last 5 sessions and uses them as LLM context
- Logs are written to `reachy.log` in the project root for debugging
- `memory.json`, `stage_state.json`, `session_id.json`, `sessions/`, and `*.log` files
  are gitignored and will not be pushed to GitHub
- For full architecture documentation, see `PROJECT.md`