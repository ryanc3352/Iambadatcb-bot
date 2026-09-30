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
| **Past chats** | **💬 Past Chats** lists your chats, newest first. Click one to read it again and carry on where you left off. ✏️ renames a chat, 🗑️ deletes it (the AI forgets it too). The chat you were in is shown again when you reopen the app. |
| **Your documents** | **Upload Documents** (PDF, Word, text, Markdown, code). Relevant parts are used in answers; **View Docs** lists them. |
| **Project folders** | **📂 Add Folder** and pick a folder (or **🗜️ Add Folder (.zip)**). Click the folder to chat about its files. |
| **Create files** | "Make me a shopping list file", "save this as notes.md". A **💾 Save** card appears where you can change the name and text, then click Save. Saved files appear under **📄 My Files** (download or delete) and in the `files/ai_files` folder. Name a file ("add eggs to shopping.txt") and the AI sees its content to update it. |
| **Weather** | "What's the weather in Paris tomorrow?" (live data from Open-Meteo, no account needed). "London, Ontario" works too. |
| **Web search** | Local first: your documents, folders and memory are checked before going online. If the answer isn't there, the assistant searches the web itself ("🔍 Searched the web for…"). |
| **Exact maths** | Calculations (`1234*5678`, `15% of 240`, `sqrt(2)^10`, `5 times 6`) and equations (`solve 2x^2 + 3x - 2 = 0`, `3x + 5 = 20`) are worked out exactly by the app, including complex roots, and handed to the model. |
| **Run code** | When an answer contains Python, a **Run** card appears. Code only runs when you click **Execute**. Missing packages are installed automatically (into the app's own `.venv`). Output shows as it comes, there's no time limit, and **⏹ Stop** ends a program. If the code asks questions with `input()`, type the answers in the box on the card first. |
| **Update** | **⬆️ Update app** downloads the newest version from GitHub, replaces the changed app files and restarts. Chats, saved files, settings and documents are kept; the replaced files are copied to `backups/update-<date>`. |
| **Learning** | Rate an answer with ⭐ and say what to change; later answers follow your feedback. **Learning Stats** shows what it has learned. |
| **Self-improvement** | **Code Quality** checks its own code. **Auto-Improve** picks one file, shows the model the current code and asks for a fix. You approve or reject each change; the old version is backed up and can be rolled back. Restart after an upgrade. |
| **Dark mode** | 🌙 at the top left. |
| **Tidy sidebar** | Click a sidebar heading (💬 Past Chats, 📚 Knowledge Base...) to fold that section away; click again to open it. The app remembers which are folded. |
| **Experimental** | 🧪 Experimental, at the bottom of the sidebar: settings that are still being tested. |
| **Problem? Get logs** | **🐞 Problem? Get logs** (top left) downloads what the app did in the last 5 minutes (your messages, the answers, errors, versions) as a text file. Send it to whoever helps you. |

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
| `ALLOWED_HOSTS` | (empty) | Extra names the app may be opened by (e.g. `my-pc.local`); IP addresses and `localhost` always work. Other names are refused, so a web page can't reach the app by pointing its own domain at your PC |
| `DATA_DIR` | the `files` folder | Where chats, uploads, saved files, backups and logs are stored |
| `MAX_UPLOAD_MB` | `200` | Largest upload (documents and folders) |
| `ENABLE_CODE_EXECUTION` | `true` | Allow the Execute button |
| `CODE_EXECUTION_TIMEOUT` | `0` | Seconds before running code is stopped; `0` means no limit |
| `ENABLE_SELF_IMPROVEMENT` | `true` | Allow approved upgrades to change the code |
| `LEARNING_ENABLED` | `true` | Save usage statistics and feedback |

## Safety

- **Executed code is not sandboxed.** It runs as you, in the `files/ai_files` folder, with a
  no time limit, and packages it needs are installed from the internet (PyPI). Read code before clicking Execute.
- Upgrades can only change the app's own listed files, must still contain everything the
  file had before, and are backed up first.
- The server only listens on your own PC (`127.0.0.1`).
- A short log of recent questions, answers and errors is kept in `files/logs` (at most about
  3 MB) for the 🐞 button. It never leaves your PC unless you send it to someone.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Ollama isn't running" | Start Ollama from the Start menu (or install it), then start the assistant again. |
| Installing the libraries fails | Check your internet connection. Use Python 3.12 or 3.13, delete the `files/.venv` folder and double-click `Start AI.bat` again. |
| `No module named 'exceptions'` | An old package called `docx` is installed. Delete `files/.venv` and start again. |
| Port 5000 is in use | Add `PORT=5050` to `files/.env`. |
| Files can't be saved ("Access is denied") | Windows is blocking Python from writing there: usually *Controlled folder access* or a OneDrive-synced Documents/Desktop folder. Move the project to a simple folder like `C:\AI\` (or set `DATA_DIR`), or allow Python in Windows Security → Ransomware protection. |
| The AI says it can't create files, or lists files that don't exist | Older models like `mistral` do this. The 💾 Save card still appears (fix the name or text before saving), and **📄 My Files** always shows what really exists. Newer models follow instructions better: **🧠 Model** → `qwen3:8b`. |
| Answers are slow | Normal on PCs without a graphics card. Try a smaller model, e.g. `MODEL_NAME=qwen3:4b`. |
| Anything else | Right after it happens, click **🐞 Problem? Get logs** and send the downloaded file. |

## For developers

```
files/
  start.py / Start AI.bat   one-click setup and start
  web_server.py             the Flask app: the page, error handling, the routes below
  routes_chat.py            chat, running approved code, history, stats, feedback
  routes_files.py           saved files, uploaded documents, project folders
  routes_improve.py         self-improvement and upgrades
  routes_system.py          models, the 🐞 logs and the ⬆️ Update button
  services.py               the shared parts (model, memory, files...), created once
  prompts.py                what the model is told with each question
  answers.py                getting answers (with a web search when needed) and saving them
  file_offers.py            files the AI offers to save, even when the model won't use the format
  config.py                 settings and the system prompt
  llm_interface.py          talks to Ollama
  model_manager.py          switching, downloading and unloading models
  memory.py                 long-term memory (ChromaDB)
  knowledge_base.py         uploaded documents (ChromaDB)
  calculator.py             exact arithmetic and equation solving
  web_search.py             web search (ddgs, Wikipedia, DuckDuckGo instant answers)
  weather_provider.py       Open-Meteo weather
  app_logging.py            the log file behind the 🐞 button
  updater.py                ⬆️ Update: download the newest version and replace changed files
  templates/, static/       the web page (static/js has one script per part of the page)
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

`python main.py` chats in the terminal with the same memory, documents, maths and web search
(no Save cards or code running).
