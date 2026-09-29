# Personal AI Assistant

A private AI assistant that runs on your own PC. It chats through a local model
([Ollama](https://ollama.com)), remembers earlier conversations, reads your documents
and project folders, does exact maths, looks things up online when it has to, runs
Python code you approve, and can suggest (and, with your OK, apply) improvements to
its own code.

Everything stays on your computer except the weather and web searches.

![Tests](https://github.com/ryanc3352/Iambadatcb-bot/actions/workflows/tests.yml/badge.svg)

---

## Quick start (Windows)

1. **Install Python 3.12 or 3.13** from [python.org](https://www.python.org/downloads/).
   In the installer, tick **"Add python.exe to PATH"**.
2. **Install Ollama** from [ollama.com/download](https://ollama.com/download).
3. **Download this project**: the green **Code** button above → **Download ZIP**, then unzip it
   (or `git clone https://github.com/ryanc3352/Iambadatcb-bot`).
4. Open the `files` folder and **double-click `Start AI.bat`**.

The first start sets everything up by itself: it installs the Python libraries into a
private `.venv` folder (a few minutes) and downloads the AI model (about 4 GB). After
that it starts in seconds. Your browser opens at **http://127.0.0.1:5000**.

To stop it, close the black window.

**Mac / Linux:** install Python and Ollama, then run `python3 start.py` in the `files` folder.

---

## What it can do

| Feature | How to use it |
|---|---|
| **Chat** | Type and press Enter. Answers stream in as they are written; scroll up to read while it writes. |
| **Change model** | **🧠 Model** (top left). Pick a downloaded model or a suggested one: models you don't have are downloaded (with progress), and the previous model is unloaded from memory. Your choice is remembered. |
| **Memory** | It remembers earlier chats and brings up relevant ones later. **New Conversation** starts a fresh chat (old ones stay in long-term memory). |
| **Your documents** | **Upload Documents** (PDF, Word, text, Markdown, code). Relevant parts are used in answers; **View Docs** lists them. |
| **Project folders** | **📂 Add Folder** and pick a folder (or **🗜️ Add Folder (.zip)**). Click the folder to chat about its files. |
| **Create files** | "Make me a shopping list file", "save this as notes.md". The AI shows a **💾 Save** card; saved files appear under **📄 My Files** (download or delete). Name a file ("add eggs to shopping.txt") and the AI sees its content to update it. |
| **Weather** | "What's the weather in Paris tomorrow?" (live data from Open-Meteo, no account needed). "London, Ontario" works too. |
| **Web search** | Local first: your documents, folders and memory are checked before going online. If the answer isn't there, the assistant searches the web itself ("🔍 Searched the web for…"). |
| **Exact maths** | Calculations (`1234*5678`, `15% of 240`, `sqrt(2)^10`, `5 times 6`) and equations (`solve 2x^2 + 3x - 2 = 0`, `3x + 5 = 20`) are worked out exactly by the app, including complex roots, and handed to the model. |
| **Run code** | When an answer contains Python, a **Run** card appears. Code only runs when you click **Execute**. |
| **Learning** | Rate an answer with ⭐ and say what to change; later answers follow your feedback. **Learning Stats** shows what it has learned. |
| **Self-improvement** | **Code Quality** checks its own code. **Auto-Improve** picks one file, shows the model the current code and asks for a fix. You approve or reject each change; the old version is backed up and can be rolled back. Restart after an upgrade. |
| **Dark mode** | 🌙 at the top left. |

### Better maths and answers

The default model is `mistral`. Newer models such as **Qwen3** are much better at maths
and reasoning: click **🧠 Model** and pick `qwen3:8b` (or `qwen3:4b` on a slower PC).
"Thinking" models like Qwen3 and DeepSeek-R1 reason before answering; the app hides that
and shows "🤔 Thinking it through first…".

---

## Settings (`files/.env`)

All optional. Create a text file named `.env` in the `files` folder:

| Setting | Default | What it does |
|---|---|---|
| `MODEL_NAME` | `mistral` | Starting model (the 🧠 Model button overrides it) |
| `MODEL_CONTEXT_TOKENS` | `8192` | How much text the model can read at once |
| `MODEL_TIMEOUT` | `600` | Seconds to wait for an answer (slow PCs need longer) |
| `OLLAMA_URL` | `http://localhost:11434` | Where Ollama runs |
| `PORT` | `5000` | Web page port |
| `HOST` | `127.0.0.1` | Keep this: the app can run code and change its own files |
| `DATA_DIR` | the `files` folder | Where chats, uploads, saved files and backups are stored |
| `MAX_UPLOAD_MB` | `200` | Largest upload (documents and folders) |
| `ENABLE_CODE_EXECUTION` | `true` | Allow the Execute button |
| `ENABLE_SELF_IMPROVEMENT` | `true` | Allow approved upgrades to change the code |
| `LEARNING_ENABLED` | `true` | Save usage statistics and feedback |

## Safety

- **Executed code is not sandboxed.** It runs as you, in the `files/ai_files` folder, with a
  30-second limit. Read code before clicking Execute.
- Upgrades can only change the app's own listed files, must still contain everything the
  file had before, and are backed up first.
- The server only listens on your own PC (`127.0.0.1`).

## Troubleshooting

| Problem | Fix |
|---|---|
| "Ollama isn't running" | Start Ollama from the Start menu (or install it), then start the assistant again. |
| Installing the libraries fails | Check your internet connection. Use Python 3.12 or 3.13, delete the `files/.venv` folder and double-click `Start AI.bat` again. |
| `No module named 'exceptions'` | An old package called `docx` is installed. Delete `files/.venv` and start again. |
| Port 5000 is in use | Add `PORT=5050` to `files/.env`. |
| Files can't be saved ("Access is denied") | Windows is blocking Python from writing there: usually *Controlled folder access* or a OneDrive-synced Documents/Desktop folder. Move the project to a simple folder like `C:\AI\` (or set `DATA_DIR`), or allow Python in Windows Security → Ransomware protection. |
| Answers are slow | Normal on PCs without a graphics card. Try a smaller model, e.g. `MODEL_NAME=qwen3:4b`. |

## For developers

```
files/
  start.py / Start AI.bat   one-click setup and start
  web_server.py             Flask app and all /api endpoints
  config.py                 settings and the system prompt
  llm_interface.py          talks to Ollama
  memory.py                 long-term memory (ChromaDB)
  knowledge_base.py         uploaded documents (ChromaDB)
  calculator.py             exact arithmetic and equation solving
  model_manager.py          switching, downloading and unloading models
  web_search.py             web search (ddgs, Wikipedia, DuckDuckGo instant answers)
  weather_provider.py       Open-Meteo weather
  ...                       one module per feature
  templates/, static/       the web page
  tests/                    automated tests (fake Ollama server)
```

Run the tests (after the first start has created `.venv`):

```
cd files
.venv\Scripts\python -m pip install pytest      (Mac/Linux: .venv/bin/python)
.venv\Scripts\python -m pytest
```

The tests use a fake model server and never touch your real chats or files. They also run
automatically on Windows and Linux for every push (see the badge above).

`python main.py` starts a simple text-only chat in the terminal (no documents, search or tools).
