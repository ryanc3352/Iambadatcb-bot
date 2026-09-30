// Shared by the page's scripts: page elements, safe text, code blocks, scrolling, messages, server calls.

const chatArea = document.getElementById('chat-area');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const feedbackBtn = document.getElementById('feedback-btn');
const feedbackPanel = document.getElementById('feedback-panel');

// ==================== SAFE TEXT ====================

// Model output is untrusted: always escape it before putting it into innerHTML
function escapeHtml(text) {
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// Escaped text with **bold** and line breaks
function renderText(text) {
    return escapeHtml(text)
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n/g, '<br>');
}

function textDivFor(text) {
    const textDiv = document.createElement('div');
    textDiv.className = 'message-text';
    textDiv.innerHTML = renderText(text);
    return textDiv;
}

// Split a message into text and ```lang code blocks and add them to contentDiv
function appendTextAndCode(contentDiv, text) {
    for (const part of text.split(/(```[\s\S]*?```)/)) {
        const fence = part.match(/^```([\w+-]*)[ \t]*\n?([\s\S]*?)\n?```$/);
        if (fence) {
            contentDiv.appendChild(createCodeBlock(fence[2], fence[1]));
        } else if (part.trim()) {
            contentDiv.appendChild(textDivFor(part));
        }
    }
}

function createCodeBlock(code, language = '') {
    const blockDiv = document.createElement('div');
    blockDiv.className = 'code-block';

    // Use the fence's language, or guess
    if (!language) {
        language = 'python';
        if (code.includes('function ') || code.includes('const ')) language = 'javascript';
        if (code.includes('SELECT') || code.includes('INSERT')) language = 'sql';
    }

    const header = document.createElement('div');
    header.className = 'code-block-header';
    const label = document.createElement('span');
    label.textContent = language.toUpperCase();
    const copyBtn = document.createElement('button');
    copyBtn.className = 'code-copy-btn';
    copyBtn.textContent = '📋 Copy';
    copyBtn.onclick = () => copyCode(copyBtn, code);
    header.append(label, copyBtn);
    blockDiv.appendChild(header);

    const codeContent = document.createElement('div');
    codeContent.className = 'code-lines';
    codeContent.textContent = code;
    blockDiv.appendChild(codeContent);

    // Long code starts folded
    const lineCount = code.split('\n').length;
    if (lineCount > 30) {
        blockDiv.classList.add('collapsed');
        const expandBtn = document.createElement('button');
        expandBtn.className = 'code-expand-btn';
        expandBtn.textContent = `📖 Show Full Code (${lineCount} lines)`;
        expandBtn.onclick = () => {
            blockDiv.classList.remove('collapsed');
            expandBtn.remove();
        };
        blockDiv.appendChild(expandBtn);
    }
    return blockDiv;
}

function copyCode(button, code) {
    navigator.clipboard.writeText(code).then(() => {
        const original = button.textContent;
        button.textContent = '✅ Copied!';
        setTimeout(() => { button.textContent = original; }, 2000);
    });
}

// ==================== SCROLLING ====================

// Only follow new text when the user is at the bottom; if they scrolled up to read, stay put
function isNearBottom() {
    return chatArea.scrollHeight - chatArea.scrollTop - chatArea.clientHeight < 80;
}

function keepScrolled(follow) {
    if (follow) chatArea.scrollTop = chatArea.scrollHeight;
}

// Add a message or card to the chat (`follow` is decided before it makes the chat longer)
function appendToChat(element, follow = isNearBottom()) {
    chatArea.appendChild(element);
    keepScrolled(follow);
}

// ==================== MESSAGES ====================

function addMessage(role, content) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    const contentDiv = document.createElement('div');
    contentDiv.className = 'content';
    appendTextAndCode(contentDiv, content);
    div.appendChild(contentDiv);

    // Long messages start folded
    if (content.length > 1000) {
        contentDiv.classList.add('long-response');
        const showMoreBtn = document.createElement('button');
        showMoreBtn.className = 'show-more-btn';
        showMoreBtn.textContent = '📖 Show Full Response';
        showMoreBtn.onclick = () => {
            contentDiv.classList.remove('long-response');
            showMoreBtn.remove();
        };
        div.appendChild(showMoreBtn);
    }
    appendToChat(div, role === 'user' || isNearBottom());
}

// ==================== SERVER ====================

// Call the server and return its JSON reply. With a body it's a POST (JSON, or a FormData upload).
async function api(url, body, method) {
    const options = { method: method || (body === undefined ? 'GET' : 'POST') };
    if (body instanceof FormData) {
        options.body = body;
    } else if (body !== undefined) {
        options.headers = { 'Content-Type': 'application/json' };
        options.body = JSON.stringify(body);
    }
    return (await fetch(url, options)).json();
}

// Read a stream of server-sent events, calling onEvent with each JSON event
async function readEvents(response, onEvent) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();
        for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            let data;
            try {
                data = JSON.parse(line.slice(6));
            } catch (e) {
                continue;  // a broken line: skip it
            }
            onEvent(data);
        }
    }
}

// Show a text report from the server (code quality, learning stats...) in the chat
function showReport(url, field) {
    api(url)
    .then(data => addMessage('assistant', data.success ? data[field] : `❌ Error: ${data.error || 'Unknown error'}`))
    .catch(err => addMessage('assistant', `❌ Error: ${err.message}`));
}
