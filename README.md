\# Reachy Mini — CPS Facilitator



A voice-powered Creative Problem Solving facilitator built on the Reachy Mini robot platform. Uses a local or cloud LLM to guide users through the four stages of CPS (Clarify, Ideate, Develop, Implement) with expressive robot behaviors, voice input/output, and rolling session memory.



\---



\## Prerequisites



Install all of the following before cloning the project.



\### 1. Python 3.10–3.13

Download from \[python.org](https://python.org). During installation, check \*\*"Add Python to PATH"\*\*.



\### 2. Git

Download from \[git-scm.com](https://git-scm.com).



\### 3. uv (Python package manager)

```powershell

pip install uv

```



\### 4. Ollama (local LLM fallback)

Download from \[ollama.com](https://ollama.com). After installing, pull the model:

```powershell

ollama pull llama3.2:3b

```

> Ollama auto-starts on Windows — you do not need to run `ollama serve` manually.



\### 5. ffmpeg (audio processing)

```powershell

winget install ffmpeg

```

> If winget is unavailable, download from \[ffmpeg.org](https://ffmpeg.org) and add to your system PATH.



\### 6. Reachy Mini package (simulation support)

```powershell

pip install reachy-mini\[mujoco]

```

> The `\[mujoco]` extra is required for simulation. For real hardware only, `pip install reachy-mini` is sufficient.



\### 7. Enable microphone access

Go to \*\*Settings → Privacy \& Security → Microphone\*\* and ensure desktop app access is enabled.



\---



\## Installation



\### Step 1 — Clone the repository

```powershell

git clone https://github.com/YOURUSERNAME/reachy\_mini\_app.git

cd reachy\_mini\_app

```

> Replace `YOURUSERNAME` with your actual GitHub username.



\### Step 2 — Install Python dependencies

```powershell

uv sync

```

This reads `pyproject.toml` and installs everything into a local virtual environment automatically.



\### Step 3 — Set your Anthropic API key (strongly recommended)

```powershell

$env:ANTHROPIC\_API\_KEY="your-api-key-here"

```

Get a key from \[console.anthropic.com](https://console.anthropic.com). Without this, the app falls back to Ollama which is significantly slower on CPU.



> To persist the key across sessions, add it to \*\*Windows Environment Variables\*\* via System Settings.



\### Step 4 — Check for GPU (optional)

```powershell

nvidia-smi

```

If a GPU is detected, Ollama will use it automatically for faster local responses.



\---



\## Running the App



\### Option A — Browser Launcher (recommended)



\*\*Terminal 1 — Start the Reachy daemon:\*\*

```powershell

cd reachy\_mini\_app

uv run reachy-mini-daemon --sim

```

A MuJoCo window opens showing the 3D robot simulation. \*\*Keep this terminal open for the entire session.\*\*



> For real hardware: power on the Reachy Mini and connect via USB (Lite) or ensure it's on the same WiFi network (Wireless). The daemon is not needed for real hardware.



\*\*Terminal 2 — Start the launcher server:\*\*

```powershell

cd reachy\_mini\_app

uv run launcher.py

```



\*\*Browser — Open the launcher:\*\*

```

http://localhost:5000

```

The launcher shows your last session date, session count, and current CPS stage. Click \*\*Continue\*\* to resume or \*\*Start New Session\*\* to begin fresh.



\---



\### Option B — Run Directly from Terminal



```powershell

uv run reachy\_chat.py

```

The app will ask at startup whether to continue a previous session or start fresh.



\---



\## How to Speak



```

1\. Press Enter        → starts recording

2\. Speak your message

3\. Press Enter again  → stops recording, Reachy responds

```



To exit cleanly, type `quit` and press Enter.



\### Advancing CPS Stages

Reachy will ask if you're ready to move on when it senses a stage is complete. To advance, say something like:

\- "let's move on"

\- "next stage"

\- "I'm ready to move on"

\- "let's go to the next stage"



\---



\## Project Structure



```

reachy\_mini\_app/

├── cps/

│   ├── clarify.md          ← Clarify stage knowledge base

│   ├── ideate.md           ← Ideate stage knowledge base

│   ├── develop.md          ← Develop stage knowledge base

│   └── implement.md        ← Implement stage knowledge base

├── sessions/               ← auto-created, readable session transcripts

├── cps\_manager.py          ← CPS stage tracking and prompt management

├── memory\_manager.py       ← Rolling session memory (last 5 sessions)

├── reachy\_chat.py          ← Main application entry point

├── launcher.py             ← Flask launcher server

├── index.html              ← Launcher UI (open in browser)

├── memory.json             ← auto-created, rolling session memory

├── stage\_state.json        ← auto-created, saves CPS stage between sessions

├── reachy.log              ← auto-created, detailed application log

├── pyproject.toml          ← Python project config and dependencies

└── uv.lock                 ← Locked dependency versions

```



\---



\## Troubleshooting



\### Responses are very slow

\- Set `ANTHROPIC\_API\_KEY` — Claude API drops response time from minutes to seconds

\- Run `nvidia-smi` to check for a GPU — Ollama uses it automatically if found

\- Try a faster model: `ollama pull qwen2.5:0.5b` then change `OLLAMA\_MODEL = "qwen2.5:0.5b"` in `reachy\_chat.py`



\### Mic not picking up audio

\- Settings → Privacy \& Security → Microphone → enable access

\- Check Windows Sound settings — correct input device must be selected and not muted

\- Disconnect Bluetooth audio devices and test with built-in mic first



\### App starts in wrong CPS stage

\- Choose \*\*Start Fresh\*\* at the startup prompt

\- Or manually delete `stage\_state.json` and `memory.json` from the project root



\### App can't connect to Reachy Mini

\- Make sure the daemon terminal is open and running

\- For Wireless: PC and Reachy must be on the same WiFi network

\- For Lite: check the USB connection



\### Daemon won't start

\- Run `pip install reachy-mini\[mujoco]` to ensure the MuJoCo extra is installed



\### Module not found errors

\- Run `uv sync` inside the project folder

\- Always use `uv run` prefix, not plain `python`



\---



\## Quick Reference



| Task | Command |

|------|---------|

| Clone repo | `git clone https://github.com/YOURUSERNAME/reachy\_mini\_app.git` |

| Install deps | `uv sync` |

| Set API key | `$env:ANTHROPIC\_API\_KEY="your-key"` |

| Start daemon | `uv run reachy-mini-daemon --sim` |

| Start launcher | `uv run launcher.py` |

| Open launcher | `http://localhost:5000` |

| Run directly | `uv run reachy\_chat.py` |



\---



\## Notes



\- Session transcripts are saved to `sessions/` as readable `.md` files after each run

\- The app remembers the last 5 sessions and uses them as context for the LLM

\- Logs are written to `reachy.log` in the project root for debugging

\- `memory.json`, `stage\_state.json`, `sessions/`, and `\*.log` files are gitignored and will not be pushed to GitHub

