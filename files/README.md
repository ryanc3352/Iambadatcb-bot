# Personal AI Assistant - Starting Code

This is a minimal but functional AI assistant that runs locally. Here's what each file does.

---

## What This Code Does

When you run it:
1. **Connects to Ollama** (your local LLM)
2. **Stores conversations** in a local database
3. **Uses conversation history** to make better responses
4. **Remembers everything** between sessions

---

## File-by-File Explanation

### 1. **config.py** — The Settings File

```python
MODEL_NAME = "mistral"
MODEL_TEMPERATURE = 0.7
```

**What it does:** Holds all the settings you might want to change.

- `MODEL_NAME`: Which model to use (mistral, llama2, etc.)
- `MODEL_TEMPERATURE`: How creative the AI is (0 = predictable, 1 = random)
- `MODEL_MAX_TOKENS`: How long each response can be
- `SYSTEM_PROMPT`: Instructions that shape how the AI behaves
- `CONTEXT_MESSAGES`: How many previous messages to include for context

**Why separate?** So you can tweak settings without editing the main code.

---

### 2. **llm_interface.py** — Talk to Ollama

**What it does:** Handles all communication with your local language model.

**Key parts:**

```python
def __init__(self, model_name, temperature, max_tokens):
    # Connects to Ollama running on localhost:11434
    # Tests the connection
```
- Sets up the connection to Ollama (the local LLM server)
- Checks that Ollama is actually running

```python
def generate_response(self, prompt):
    # Takes your prompt
    # Sends it to Ollama
    # Gets back the response
    # Returns just the text
```
- This is the core: it sends text to the model and gets text back
- If Ollama isn't running, it tells you so you can fix it

```python
def test_model(self):
    # Sends a simple message to verify the model works
```
- Useful for debugging if something breaks

**In simple terms:** This file is like a "translator" between your code and Ollama.

---

### 3. **conversation_history.py** — Remember Everything

**What it does:** Saves all conversations to a database so the AI can learn and reference past chats.

**Key parts:**

```python
def __init__(self, db_path):
    # Creates a SQLite database
    # Makes a table for storing messages
```
- Sets up SQLite (a simple file-based database)
- Creates a table with columns: id, role (user/assistant), content, timestamp

```python
def add_message(self, role, content):
    # Takes a message ("user" or "assistant")
    # Stores it in the database
```
- Every time you type something or the AI responds, it's saved
- This persists between sessions (even if you restart the program)

```python
def get_last_n_messages(self, n):
    # Gets the last N messages from the database
    # Returns them as a list
```
- If you ask for the last 5 messages, it retrieves them
- This is used for context (see below)

```python
def format_for_prompt(self, messages):
    # Takes: [{"role": "user", "content": "Hi"}]
    # Returns: "User: Hi\nAssistant: Hello!\n"
```
- Formats messages nicely so they can be included in the prompt

**In simple terms:** This is your AI's memory. Everything it says and hears is saved.

---

### 4. **main.py** — The Brain

**What it does:** Ties everything together and runs the chat loop.

**Key parts:**

```python
class PersonalAI:
    def __init__(self):
        self.llm = LLMInterface(...)
        self.history = ConversationHistory(...)
```
- Initializes both the LLM and the history storage
- This is where the AI "wakes up"

```python
def build_prompt(self, user_input):
    # Gets the last few messages from history
    # Formats them
    # Combines with system prompt + user input
    # Returns the complete prompt to send to the model
```

**Example of what a prompt looks like:**

```
You are a helpful personal AI assistant. You help the user with coding, learning, and tasks.

Previous conversation:
User: How do I use Python?
Assistant: Python is a programming language...

User: Can you help me with a loop?
Assistant:
```

Notice:
- System prompt at the top (tells AI how to behave)
- Previous conversation for context
- Current user input at the bottom
- The AI completes the sentence after "Assistant:"

```python
def chat(self, user_input):
    # Stores user message in database
    # Builds a prompt with context
    # Sends to LLM
    # Stores AI response in database
    # Returns the response
```

This is the main action. Every conversation goes through here.

```python
def run(self):
    # Infinite loop:
    # 1. Wait for user to type
    # 2. Call chat()
    # 3. Display response
    # Repeat until user types "exit"
```

The endless loop that keeps the conversation going.

---

## How It All Works Together

```
User types: "How do I learn Python?"
    ↓
main.py: chat("How do I learn Python?")
    ↓
history.add_message("user", "How do I learn Python?")
    ↓
build_prompt() does:
  - Gets last 5 messages from database
  - Formats them
  - Adds system prompt
  - Creates full prompt
    ↓
llm_interface.generate_response(prompt)
    ↓
Ollama processes it
    ↓
Returns: "Start with the basics..."
    ↓
history.add_message("assistant", "Start with the basics...")
    ↓
Display response to user
```

---

## How to Run It

### Prerequisites
1. **Install Ollama:** https://ollama.ai
2. **Install Python:** 3.10+
3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

### Setup
1. **Start Ollama:**
   ```bash
   ollama serve
   ```
   (Leave this running in another terminal)

2. **Download a model:**
   ```bash
   ollama pull mistral
   ```
   (Run once, takes a few minutes)

### Run the AI

**Web interface** (all features):
```bash
python web_server.py
```
Then open http://127.0.0.1:5000

**Terminal chat** (simple):
```bash
python main.py
```

### Project layout
```
web_server.py          Flask app + all /api endpoints
config.py              Settings (override with a .env file)
templates/index.html   Web page
static/css/style.css
static/js/script.js
*.py                   One module per feature (memory, knowledge_base, weather_provider, ...)
```

### Settings (.env)
| Variable | Default | Meaning |
|---|---|---|
| `MODEL_NAME` | `mistral` | Ollama model |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server |
| `HOST` / `PORT` | `127.0.0.1` / `5000` | Keep HOST local: the app can run code and edit its own files |
| `FLASK_DEBUG` | `false` | Never enable on a network-reachable host |
| `ENABLE_CODE_EXECUTION` | `true` | Allow the ✅ Execute button |
| `CODE_EXECUTION_TIMEOUT` | `30` | Seconds before running code is stopped |
| `ENABLE_SELF_IMPROVEMENT` | `true` | Allow approved UPGRADE_REQUESTs to rewrite files |

⚠️ Executed code is **not sandboxed**: it runs as your user in `ai_files/`. Read it before clicking Execute.

You should see:
```
Initializing Personal AI...

✓ Connected to Ollama
✓ AI initialized with mistral model
✓ Conversation history: 0 messages stored

============================================================
Personal AI Assistant
Type 'exit' to quit, 'stats' to see conversation stats
============================================================

You: 
```

Now type something and it responds!

---

## What's Actually Happening

1. **You type:** "Hello"
2. **Database stores:** "user" → "Hello"
3. **Code creates prompt:** "You are a helpful AI... Previous messages... User: Hello\nAssistant:"
4. **Ollama reads prompt:** Processes the full context
5. **Ollama generates:** Token by token, the response
6. **You see:** "Hi! How can I help?"
7. **Database stores:** "assistant" → "Hi! How can I help?"

Next time you chat, the AI has access to all previous conversations.

---

## Key Concepts

### **Context Window**
- The prompt gets built with the last 5 messages (configurable)
- This gives the AI memory of recent conversation
- Older messages aren't included (to keep prompt size manageable)

### **Database**
- SQLite stores messages locally
- They persist between sessions
- The AI can theoretically learn from all past interactions (with good retrieval)

### **System Prompt**
- The instructions at the top that shape behavior
- "You are helpful, honest, and concise"
- Edit this to change the AI's personality

### **Temperature**
- 0.0 = AI gives the same answer every time (deterministic)
- 0.7 = AI is creative but still sensible (good for most use)
- 1.0 = AI is very random and unpredictable

---

## What's Missing (For Later)

This code does NOT include:
- ❌ Vector database (no semantic search of past conversations yet)
- ❌ Code execution
- ❌ Fine-tuning
- ❌ Web interface (just terminal for now)

These are Phase 3+ features. Master this first.

---

## Troubleshooting

### "Error: Can't connect to Ollama"
- Make sure Ollama is running: `ollama serve`
- Check if it's on localhost:11434

### "Model not found"
- Download it: `ollama pull mistral`
- Or change MODEL_NAME in config.py to a model you have

### "Response is slow"
- Your GPU might not be used. Check Ollama logs.
- Smaller models like Mistral 7B are faster than larger ones

### "Getting the same response repeatedly"
- Lower temperature in config.py (currently 0.7 is good)
- Or increase it for more creativity

---

## Next Steps

Once this is working:
1. **Add code execution** (Phase 4)
2. **Add vector database** for memory (Phase 3)
3. **Fine-tune on your conversations** (Phase 5)
4. **Build a nicer UI** (web interface, not just terminal)

Good luck! 🚀
