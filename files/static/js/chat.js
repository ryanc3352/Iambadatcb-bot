// Sending messages and showing the answers as they are written.

let selectedFolder = null;  // when set, questions are about this uploaded folder

function handleKeyPress(event) {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        sendMessage();
    }
}

function sendMessage(customMessage = null) {
    if (sendBtn.disabled) return;  // a reply is still coming
    const message = customMessage || messageInput.value.trim();
    if (!message) return;

    messageInput.value = '';
    sendBtn.disabled = true;
    addMessage('user', message);

    (selectedFolder ? askAboutFolder(message) : streamAnswer(message))
    .catch(err => addMessage('assistant', `❌ Connection error: ${err.message}`))
    .finally(() => {
        sendBtn.disabled = false;
        messageInput.focus();
        updateStats();
    });
}

// A new, empty answer in the chat to fill in
function newAnswer() {
    const div = document.createElement('div');
    div.className = 'message assistant';
    const contentDiv = document.createElement('div');
    contentDiv.className = 'content';
    div.appendChild(contentDiv);
    appendToChat(div);
    return { div, contentDiv };
}

// The cards that go with an answer: code to run, files to save
function showAnswerCards(data) {
    if (data.has_code && data.code) showCodeRequest(data.code);
    (data.files || []).forEach(f => showSaveFileRequest(f.path, f.content, f.exists));
    feedbackBtn.hidden = false;
}

async function askAboutFolder(message) {
    const data = await api('/api/chat/with-folder', { message, folder_name: selectedFolder });
    if (data.error) {
        addMessage('assistant', `❌ Error: ${data.error}`);
        return;
    }
    formatMessage(newAnswer().contentDiv, data.response);
    showAnswerCards(data);
}

// A note above the answer ("thinking", "searched the web"); formatting the answer keeps it
function addNote(div, contentDiv, className, text) {
    if (div.querySelector(`.${className}`)) return;
    const note = document.createElement('div');
    note.className = `note ${className}`;
    note.textContent = text;
    div.insertBefore(note, contentDiv);
}

async function streamAnswer(message) {
    const response = await fetch('/api/chat-stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message })
    });
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `Server error ${response.status}`);
    }

    const { div, contentDiv } = newAnswer();
    contentDiv.style.whiteSpace = 'pre-wrap';  // raw text while streaming
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let fullText = '';
    let formatted = false;

    for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const raw of lines) {
            const line = raw.trim();
            if (!line.startsWith('data: ')) continue;
            let data;
            try {
                data = JSON.parse(line.slice(6));
            } catch (e) {
                console.warn('⚠️ Could not read part of the answer:', e);
                continue;
            }
            if (data.thinking) addNote(div, contentDiv, 'thinking-note', '🤔 Thinking it through first…');
            if (data.searching) addNote(div, contentDiv, 'search-note', `🔍 Searched the web for: ${data.searching}`);
            if (data.token) {
                fullText += data.token;
                // Text nodes, not innerHTML: no escaping needed and no re-parsing per token
                const follow = isNearBottom();
                contentDiv.insertAdjacentText('beforeend', data.token);
                keepScrolled(follow);
            }
            if (data.done) {
                formatted = true;
                formatMessage(contentDiv, fullText);
                if (data.error) addMessage('assistant', `❌ ${data.error}`);
                showAnswerCards(data);
            }
        }
    }
    if (!formatted) formatMessage(contentDiv, fullText);
}

// ==================== FORMATTING ANSWERS ====================

// Same pattern as the server's SAVE_FILE_BLOCK
const SAVE_FILE_BLOCK = /SAVE_FILE:\**[ \t]*`?([^\n`*]+?)`?\**[ \t]*\n+```[\w+.-]*[ \t]*\n([\s\S]*?)\n?```/g;

// Parse "UPGRADE_REQUEST: FILE: ... DESCRIPTION: ... CODE: ```python ... ```".
// The code runs to the closing fence (or the end of the message), blank lines included.
function parseUpgradeRequest(text) {
    const match = text.match(/UPGRADE_REQUEST:\s*FILE:\s*(.+?)\s*\n\s*DESCRIPTION:\s*([\s\S]+?)\s*CODE:\s*(?:```[\w-]*\n([\s\S]*?)\n```|([\s\S]+))/);
    if (!match) return null;
    const code = (match[3] !== undefined ? match[3] : match[4]).trim();
    if (!code) return null;
    return { file: match[1].trim(), description: match[2].trim(), code };
}

function formatMessage(contentDiv, text) {
    const follow = isNearBottom();
    renderFormatted(contentDiv, text);
    keepScrolled(follow);
}

function renderFormatted(contentDiv, text) {
    contentDiv.innerHTML = '';
    contentDiv.style.whiteSpace = '';

    const upgrade = parseUpgradeRequest(text);
    if (upgrade) {
        const beforeUpgrade = text.substring(0, text.indexOf('UPGRADE_REQUEST:')).trim();
        if (beforeUpgrade) contentDiv.appendChild(textDivFor(beforeUpgrade));
        showUpgradeRequest(upgrade.file, upgrade.description, upgrade.code);
        return;
    }
    // Files to save are shown as Save cards instead
    appendTextAndCode(contentDiv, text.replace(SAVE_FILE_BLOCK, (_, path) => `📄 File: ${path.trim()} (see below)`));
}
