// DOM Elements
const chatArea = document.getElementById('chat-area');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const feedbackBtn = document.getElementById('feedback-btn');
const feedbackPanel = document.getElementById('feedback-panel');

// State
let selectedFolder = null;
let lastResponseRole = null;
let currentStreamingDiv = null;

// ==================== HTML SAFETY ====================

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

// ==================== SCROLLING ====================

// Only follow new text when the user is at the bottom; if they scrolled up to read, stay put
function isNearBottom() {
    return chatArea.scrollHeight - chatArea.scrollTop - chatArea.clientHeight < 80;
}

function keepScrolled(follow) {
    if (follow) chatArea.scrollTop = chatArea.scrollHeight;
}

function textDivFor(text) {
    const textDiv = document.createElement('div');
    textDiv.className = 'message-text';
    textDiv.innerHTML = renderText(text);
    return textDiv;
}

// ==================== INITIALIZATION ====================

document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 Chat interface loaded');
    loadConversationHistory();
    updateStats();
    loadFoldersList();
    loadFilesList();
    // Show the model in use, and keep showing progress if a download is still running
    refreshModels().then(data => {
        if (data && data.download && !data.download.done) watchModelDownload();
    });
    
    // Load dark mode preference
    if (localStorage.getItem('darkMode') === 'true') {
        document.body.classList.add('dark-mode');
    }
});

// ==================== CHAT FUNCTIONS ====================

function handleKeyPress(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}

function sendMessage(customMessage = null) {
    if (sendBtn.disabled) return;  // a reply is still coming
    const message = customMessage || messageInput.value.trim();
    
    if (!message) {
        console.warn('⚠️ Empty message');
        return;
    }
    
    console.log('📤 Sending message:', message.substring(0, 50) + '...');
    
    messageInput.value = '';
    sendBtn.disabled = true;
    
    // Add user message to chat
    addMessage('user', message);
    
    // Send to server
    if (selectedFolder) {
        sendMessageWithFolder(message);
    } else {
        sendMessageNormal(message);
    }
}

function sendMessageNormal(message) {
    streamMessage(message);
}

function sendMessageWithFolder(message) {
    console.log('📁 Sending with folder:', selectedFolder);
    
    try {
        fetch('/api/chat/with-folder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                folder_name: selectedFolder
            })
        })
        .then(r => {
            console.log('📡 Response status:', r.status);
            return r.json();
        })
        .then(data => {
            console.log('✅ Got response:', data);
            if (data.error) {
                addMessage('assistant', '❌ Error: ' + data.error);
            } else {
                const div = document.createElement('div');
                div.className = 'message assistant';
                const contentDiv = document.createElement('div');
                contentDiv.className = 'content';
                div.appendChild(contentDiv);
                chatArea.appendChild(div);
                formatMessage(contentDiv, data.response);
                if (data.has_code && data.code) {
                    showCodeRequest(data.code);
                }
                (data.files || []).forEach(f => showSaveFileRequest(f.path, f.content, f.exists));
                lastResponseRole = 'assistant';
                feedbackBtn.style.display = 'inline-block';
            }
            sendBtn.disabled = false;
            messageInput.focus();
            updateStats();
        })
        .catch(err => {
            console.error('❌ Fetch error:', err);
            addMessage('assistant', '❌ Connection error: ' + err.message);
            sendBtn.disabled = false;
        });
    } catch (err) {
        console.error('❌ Try error:', err);
        addMessage('assistant', '❌ Error: ' + err.message);
        sendBtn.disabled = false;
    }
}

function streamMessage(message) {
    console.log('🌊 Starting stream...');
    
    try {
        fetch('/api/chat-stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message })
        })
        .then(response => {
            if (!response.ok) {
                console.error('❌ Response not ok:', response.status);
                return response.json()
                    .catch(() => ({}))
                    .then(data => { throw new Error(data.error || `Server error ${response.status}`); });
            }
            
            console.log('📡 Got stream response');
            
            const div = document.createElement('div');
            div.className = 'message assistant';
            const contentDiv = document.createElement('div');
            contentDiv.className = 'content';
            div.appendChild(contentDiv);
            const follow = isNearBottom();
            chatArea.appendChild(div);
            keepScrolled(follow);
            currentStreamingDiv = contentDiv;
            contentDiv.style.whiteSpace = 'pre-wrap';  // raw text while streaming
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let fullText = '';
            let formatted = false;
            
            return reader.read().then(function processText({ done, value }) {
                if (done) {
                    console.log('✅ Stream done');
                    if (!formatted) formatMessage(currentStreamingDiv, fullText);
                    lastResponseRole = 'assistant';
                    feedbackBtn.style.display = 'inline-block';
                    updateStats();
                    sendBtn.disabled = false;
                    messageInput.focus();
                    return;
                }
                
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines[lines.length - 1];
                
                for (let i = 0; i < lines.length - 1; i++) {
                    const line = lines[i].trim();
                    
                    if (line.startsWith('data: ')) {
                        try {
                            const data = JSON.parse(line.substring(6));
                            
                            if (data.thinking && !div.querySelector('.thinking-note')) {
                                const note = document.createElement('div');
                                note.className = 'thinking-note';
                                note.style.cssText = 'font-size: 12px; opacity: 0.75; margin-bottom: 6px;';
                                note.textContent = '🤔 Thinking it through first…';
                                div.insertBefore(note, currentStreamingDiv);
                            }

                            if (data.searching) {
                                // shown above the answer; formatMessage() doesn't clear it
                                const note = document.createElement('div');
                                note.className = 'search-note';
                                note.style.cssText = 'font-size: 12px; opacity: 0.75; margin-bottom: 6px;';
                                note.textContent = `🔍 Searched the web for: ${data.searching}`;
                                div.insertBefore(note, currentStreamingDiv);
                            }

                            if (data.token) {
                                fullText += data.token;
                                // Text nodes, not innerHTML: no escaping needed and no re-parsing per token
                                const follow = isNearBottom();
                                currentStreamingDiv.insertAdjacentText('beforeend', data.token);
                                keepScrolled(follow);
                            }
                            
                            if (data.done) {
                                formatted = true;
                                formatMessage(currentStreamingDiv, fullText);
                                if (data.error) {
                                    addMessage('assistant', '❌ ' + data.error);
                                }
                                if (data.has_code && data.code) {
                                    showCodeRequest(data.code);
                                }
                                (data.files || []).forEach(f => showSaveFileRequest(f.path, f.content, f.exists));
                            }
                        } catch (e) {
                            console.warn('⚠️ Parse error:', e);
                        }
                    }
                }
                
                return reader.read().then(processText);
            });
        })
        .catch(err => {
            console.error('❌ Stream error:', err);
            addMessage('assistant', '❌ Connection error: ' + err.message);
            sendBtn.disabled = false;
            messageInput.focus();
        });
    } catch (err) {
        console.error('❌ Stream try error:', err);
        addMessage('assistant', '❌ Error: ' + err.message);
        sendBtn.disabled = false;
    }
}

// ==================== MESSAGE FORMATTING ====================

function addMessage(role, content) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'content';
    
    appendTextAndCode(contentDiv, content);
    
    // Show full response button if too long
    if (content.length > 1000) {
        contentDiv.classList.add('long-response');
        const showMoreBtn = document.createElement('button');
        showMoreBtn.className = 'show-more-btn';
        showMoreBtn.textContent = '📖 Show Full Response';
        showMoreBtn.onclick = () => {
            contentDiv.classList.remove('long-response');
            showMoreBtn.remove();
        };
        div.appendChild(contentDiv);
        div.appendChild(showMoreBtn);
    } else {
        div.appendChild(contentDiv);
    }
    
    const follow = role === 'user' || isNearBottom();
    chatArea.appendChild(div);
    keepScrolled(follow);
}

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
    
    // Check for UPGRADE_REQUEST first
    const upgrade = parseUpgradeRequest(text);
    if (upgrade) {
        console.log('🔧 Detected UPGRADE_REQUEST for:', upgrade.file);
        const beforeUpgrade = text.substring(0, text.indexOf('UPGRADE_REQUEST:')).trim();
        if (beforeUpgrade) {
            contentDiv.appendChild(textDivFor(beforeUpgrade));
        }
        showUpgradeRequest(upgrade.file, upgrade.description, upgrade.code);
        return;
    }

    // Normal message formatting (files to save are shown as Save cards instead)
    appendTextAndCode(contentDiv, text.replace(SAVE_FILE_BLOCK, (_, path) => `📄 File: ${path.trim()} (see below)`));
}

// Same pattern as the server's SAVE_FILE_BLOCK
const SAVE_FILE_BLOCK = /SAVE_FILE:\**[ \t]*`?([^\n`*]+?)`?\**[ \t]*\n+```[\w+.-]*[ \t]*\n([\s\S]*?)\n?```/g;

function createCodeBlock(code, language = '') {
    const blockDiv = document.createElement('div');
    blockDiv.className = 'code-block';
    
    // Use the fence's language, or guess
    if (!language) {
        language = 'python';
        if (code.includes('function ') || code.includes('const ')) language = 'javascript';
        if (code.includes('SELECT') || code.includes('INSERT')) language = 'sql';
    }
    
    // Header
    const header = document.createElement('div');
    header.className = 'code-block-header';
    const label = document.createElement('span');
    label.textContent = language.toUpperCase();
    const copyBtn = document.createElement('button');
    copyBtn.className = 'code-copy-btn';
    copyBtn.textContent = '📋 Copy';
    copyBtn.onclick = () => copyCode(copyBtn);
    header.append(label, copyBtn);
    blockDiv.appendChild(header);
    
    // Code content
    const codeContent = document.createElement('div');
    codeContent.className = 'code-lines';
    codeContent.textContent = code;
    blockDiv.appendChild(codeContent);
    
    // Collapse if too long
    if (code.split('\n').length > 30) {
        blockDiv.classList.add('collapsed');
        const expandBtn = document.createElement('button');
        expandBtn.className = 'code-expand-btn';
        expandBtn.textContent = `📖 Show Full Code (${code.split('\n').length} lines)`;
        expandBtn.onclick = () => {
            blockDiv.classList.remove('collapsed');
            expandBtn.remove();
        };
        blockDiv.appendChild(expandBtn);
    }
    
    return blockDiv;
}

function copyCode(button) {
    const codeBlock = button.closest('.code-block');
    const code = codeBlock.querySelector('.code-lines').textContent;
    
    navigator.clipboard.writeText(code).then(() => {
        const original = button.textContent;
        button.textContent = '✅ Copied!';
        setTimeout(() => button.textContent = original, 2000);
    });
}

function showCodeRequest(code) {
    const blockDiv = document.createElement('div');
    blockDiv.className = 'code-execution-request';
    blockDiv.innerHTML = `
        <div style="background: var(--accent-1); color: white; padding: 10px; border-radius: 5px; margin-bottom: 10px;">
            <strong>💻 Code Execution Request</strong>
            <div style="font-size: 12px; opacity: 0.9;">Runs on your computer with your permissions. Read it before executing.</div>
        </div>
        <div class="code-block" style="margin-bottom: 10px;">
            <div class="code-lines"></div>
        </div>
        <div style="display: flex; gap: 10px;">
            <button class="btn-execute">✅ Execute</button>
            <button class="btn-skip">❌ Skip</button>
        </div>
    `;
    blockDiv.querySelector('.code-lines').textContent = code;
    blockDiv.querySelector('.btn-execute').onclick = (e) => executeCode(e.target, code, blockDiv);
    blockDiv.querySelector('.btn-skip').onclick = () => blockDiv.remove();

    const follow = isNearBottom();
    chatArea.appendChild(blockDiv);
    keepScrolled(follow);
}

function showCodeResult(blockDiv, success, text, successLabel = '✅ Output:') {
    const result = document.createElement('div');
    result.className = success ? 'code-output' : 'code-error';
    const label = success ? successLabel : '❌ Error:';
    result.innerHTML = (label ? `<strong>${label}</strong><br>` : '') + renderText(text);
    blockDiv.appendChild(result);
}

function executeCode(button, code, blockDiv) {
    button.disabled = true;
    button.textContent = '⏳ Running...';

    fetch('/api/execute-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code })
    })
    .then(r => r.json())
    .then(data => {
        showCodeResult(blockDiv, data.success, data.output || data.error || '');
        button.style.display = 'none';
        updateStats();
    })
    .catch(err => {
        showCodeResult(blockDiv, false, err.message);
        button.disabled = false;
        button.textContent = '✅ Execute';
    });
}

// ==================== KNOWLEDGE BASE ====================

function uploadDocument(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    const formData = new FormData();
    formData.append('file', file);
    
    addMessage('user', `📤 Uploading: ${file.name}`);
    
    fetch('/api/knowledge-base/upload', {
        method: 'POST',
        body: formData
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            addMessage('assistant', data.message);
        } else {
            addMessage('assistant', `❌ Error: ${data.message || data.error}`);
        }
        event.target.value = '';
    })
    .catch(err => {
        addMessage('assistant', `❌ Upload failed: ${err.message}`);
        event.target.value = '';
    });
}

function loadDocumentsList() {
    fetch('/api/knowledge-base/list')
    .then(r => r.json())
    .then(data => {
        let message = '📚 Your Documents:\n\n';
        if (data.documents && data.documents.length > 0) {
            data.documents.forEach(doc => {
                message += `• ${doc}\n`;
            });
        } else {
            message = 'No documents uploaded yet.';
        }
        addMessage('assistant', message);
    })
    .catch(err => addMessage('assistant', '❌ Could not load documents: ' + err.message));
}

// ==================== FOLDER ACCESS ====================

async function loadFoldersList() {
    console.log('📂 Loading folders list...');
    try {
        const response = await fetch('/api/folders/list');
        const data = await response.json();
        
        console.log('📂 Folders response:', data);
        
        const foldersList = document.getElementById('folders-list');
        if (data.success && data.folders && data.folders.length === 0) {
            foldersList.innerHTML = '<p style="font-size: 12px; color: var(--text-secondary);">No folders uploaded</p>';
        } else if (data.success && data.folders) {
            foldersList.innerHTML = '';
            
            for (let folder of data.folders) {
                const div = document.createElement('div');
                div.style.cssText = 'padding: 8px; border: 1px solid var(--border-color); margin: 5px 0; border-radius: 5px; cursor: pointer; background: var(--bg-secondary);';
                div.innerHTML = `<strong>${escapeHtml(folder.name)}</strong><br><small>${Number(folder.file_count) || 0} files</small>`;
                div.onclick = () => selectFolder(folder.name);
                
                const deleteBtn = document.createElement('button');
                deleteBtn.textContent = '🗑️';
                deleteBtn.style.cssText = 'float: right; background: #ff6b6b; color: white; border: none; padding: 2px 6px; border-radius: 3px; cursor: pointer;';
                deleteBtn.onclick = (e) => {
                    e.stopPropagation();
                    deleteFolder(folder.name);
                };
                div.appendChild(deleteBtn);
                
                foldersList.appendChild(div);
            }
        } else {
            console.log('No folders or error:', data);
        }
    } catch (err) {
        console.error('❌ Error loading folders:', err);
    }
}

function selectFolder(folderName) {
    console.log('✅ Selected folder:', folderName);
    selectedFolder = folderName;
    addMessage('user', `📁 Selected folder: ${folderName}`);
    document.getElementById('folder-btn').textContent = `📁 ${folderName}`;
    document.getElementById('folder-btn').style.background = 'var(--accent-1)';
    
    fetch(`/api/folders/${encodeURIComponent(folderName)}/summary`)
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                addMessage('assistant', data.summary);
            }
        })
        .catch(err => {
            console.error('❌ Error getting summary:', err);
            addMessage('assistant', '❌ Error loading folder summary');
        });
}

function selectFolderMode() {
    if (selectedFolder) {
        selectedFolder = null;
        document.getElementById('folder-btn').textContent = '📁 With Folder';
        document.getElementById('folder-btn').style.background = '';
        addMessage('assistant', '📁 Folder mode disabled');
    } else {
        loadFoldersList();
    }
}

function uploadFolderFiles(event) {
    // A folder picked directly (no ZIP): send each file with its path inside the folder
    const skip = /(^|\/)(\.git|node_modules|__pycache__|\.venv|venv|\.idea|\.vscode)\//;
    const files = [...event.target.files].filter(f => !skip.test(f.webkitRelativePath));
    if (!files.length) return;
    const folderName = files[0].webkitRelativePath.split('/')[0];

    const formData = new FormData();
    formData.append('folder_name', folderName);
    files.forEach(f => formData.append('files', f, f.webkitRelativePath));

    addMessage('user', `📤 Adding folder: ${folderName} (${files.length} files)`);
    fetch('/api/folders/upload-files', { method: 'POST', body: formData })
    .then(r => r.json())
    .then(data => {
        addMessage('assistant', data.success ? data.message : `❌ Error: ${data.error || data.message}`);
        loadFoldersList();
    })
    .catch(err => addMessage('assistant', `❌ Upload failed: ${err.message}`))
    .finally(() => { event.target.value = ''; });
}

function uploadFolder(event) {
    const file = event.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('folder', file);
    formData.append('folder_name', file.name.replace(/\.zip$/i, ''));

    addMessage('user', `📤 Uploading folder: ${file.name}`);

    fetch('/api/folders/upload', { method: 'POST', body: formData })
    .then(r => r.json())
    .then(data => {
        addMessage('assistant', data.success ? data.message : `❌ Error: ${data.error || data.message}`);
        loadFoldersList();
    })
    .catch(err => addMessage('assistant', `❌ Upload failed: ${err.message}`))
    .finally(() => { event.target.value = ''; });
}

async function deleteFolder(folderName) {
    if (confirm(`Delete folder "${folderName}"?`)) {
        const response = await fetch(`/api/folders/${encodeURIComponent(folderName)}/delete`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        addMessage('assistant', data.message || data.error);
        if (selectedFolder === folderName) selectFolderMode();  // stop chatting with a deleted folder
        await loadFoldersList();
    }
}

// ==================== SELF-IMPROVEMENT ====================

function analyzeMyself() {
    console.log('📊 Analyzing code quality...');
    fetch('/api/self/analyze')
    .then(r => {
        console.log('Response status:', r.status);
        return r.json();
    })
    .then(data => {
        console.log('Analysis result:', data);
        if (data.success) {
            addMessage('assistant', data.report);
        } else {
            addMessage('assistant', '❌ Error: ' + (data.error || 'Unknown error'));
        }
    })
    .catch(err => {
        console.error('❌ Fetch error:', err);
        addMessage('assistant', '❌ Error: ' + err.message);
    });
}

function showLearning() {
    console.log('📈 Getting learning stats...');
    fetch('/api/self/learning')
    .then(r => r.json())
    .then(data => {
        console.log('Learning result:', data);
        if (data.success) {
            addMessage('assistant', data.report);
        } else {
            addMessage('assistant', '❌ Error: ' + data.error);
        }
    })
    .catch(err => {
        console.error('❌ Fetch error:', err);
        addMessage('assistant', '❌ Error: ' + err.message);
    });
}

function showImprovements() {
    console.log('💡 Getting improvement suggestions...');
    fetch('/api/self/improvements')
    .then(r => r.json())
    .then(data => {
        console.log('Improvements result:', data);
        if (data.success) {
            addMessage('assistant', data.suggestions_text);
        } else {
            addMessage('assistant', '❌ Error: ' + data.error);
        }
    })
    .catch(err => {
        console.error('❌ Fetch error:', err);
        addMessage('assistant', '❌ Error: ' + err.message);
    });
}

function selfImprove() {
    console.log('🚀 Triggering self-improve...');
    
    fetch('/api/self/improvement-prompt')
    .then(r => r.json())
    .then(data => {
        console.log('Self-improve prompt:', data);
        if (data.success) {
            messageInput.value = '';
            sendMessage(data.prompt);
        } else {
            addMessage('assistant', '❌ Error: ' + data.error);
        }
    })
    .catch(err => {
        console.error('❌ Fetch error:', err);
        addMessage('assistant', '❌ Error: ' + err.message);
    });
}

// ==================== UPGRADE REQUESTS ====================

function showUpgradeRequest(file, description, code) {
    console.log('🔧 Showing upgrade request for:', file);

    const lines = code.split('\n');
    const blockDiv = document.createElement('div');
    blockDiv.style.cssText = `
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 20px;
        border-radius: 8px;
        margin: 15px 0;
        border: 2px solid #667eea;
    `;

    const buttonStyle = `
        flex: 1;
        color: white;
        border: none;
        padding: 12px 20px;
        border-radius: 5px;
        font-weight: 600;
        cursor: pointer;
        font-size: 14px;
    `;

    blockDiv.innerHTML = `
        <div style="margin-bottom: 15px;">
            <h3 style="margin: 0 0 10px 0; color: white;">🔧 AI Wants to Upgrade Your Code</h3>
            <p style="margin: 5px 0;"><strong>File:</strong> ${escapeHtml(file)}</p>
            <p style="margin: 5px 0;"><strong>Change:</strong> ${renderText(description)}</p>
        </div>

        <div style="background: #1a1a2e; padding: 15px; border-radius: 5px; margin-bottom: 15px; max-height: 300px; overflow-y: auto;">
            <div style="font-family: 'Courier New', monospace; font-size: 12px; line-height: 1.5; color: #abb2bf;">
                <strong>Code Preview:</strong><br>
                ${lines.slice(0, 20).map(escapeHtml).join('<br>')}
                ${lines.length > 20 ? `<br><em>... (${lines.length - 20} more lines)</em>` : ''}
            </div>
        </div>

        <div style="display: flex; gap: 10px;">
            <button class="upgrade-approve" style="${buttonStyle} background: #51cf66;">✅ Approve & Apply</button>
            <button class="upgrade-reject" style="${buttonStyle} background: #ff6b6b;">❌ Reject</button>
        </div>
    `;

    blockDiv.querySelector('.upgrade-approve').onclick = (e) => approveUpgrade(e.target, file, description, code, blockDiv);
    blockDiv.querySelector('.upgrade-reject').onclick = () => rejectUpgrade(blockDiv);

    const follow = isNearBottom();
    chatArea.appendChild(blockDiv);
    keepScrolled(follow);
}

function approveUpgrade(button, file, description, code, blockDiv) {
    button.disabled = true;
    button.textContent = '⏳ Applying...';

    console.log('✅ Applying upgrade to:', file);

    fetch('/api/upgrade/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file, description, code })
    })
    .then(r => r.json())
    .then(data => {
        console.log('Upgrade result:', data);
        if (data.success) {
            addMessage('assistant', `✅ Upgrade applied to ${file}!\n\n${data.message}\n\n⚠️ Restart the server to use the new code.`);
            blockDiv.remove();
        } else {
            addMessage('assistant', `❌ Upgrade failed: ${data.message || data.error}`);
            button.disabled = false;
            button.textContent = '✅ Approve & Apply';
        }
    })
    .catch(err => {
        console.error('❌ Upgrade error:', err);
        addMessage('assistant', `❌ Error applying upgrade: ${err.message}`);
        button.disabled = false;
        button.textContent = '✅ Approve & Apply';
    });
}

function rejectUpgrade(blockDiv) {
    addMessage('assistant', '❌ Upgrade rejected. Not applying changes.');
    blockDiv.remove();
}

// ==================== FEEDBACK ====================

function showFeedbackPanel() {
    feedbackPanel.style.display = 'flex';
}

function closeFeedbackPanel() {
    feedbackPanel.style.display = 'none';
    document.getElementById('feedback-text').value = '';
}

function rateResponse(stars) {
    const feedback = document.getElementById('feedback-text').value;
    
    console.log('⭐ Rating response with', stars, 'stars');
    
    fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            rating: stars,
            feedback: feedback
        })
    })
    .then(r => r.json())
    .then(data => {
        console.log('Feedback result:', data);
        addMessage('assistant', '✅ Thanks for the feedback! I\'m learning and improving.');
        closeFeedbackPanel();
    })
    .catch(err => {
        console.error('❌ Feedback error:', err);
        addMessage('assistant', '❌ Error submitting feedback');
    });
}

function submitFeedback() {
    rateResponse(3); // Default rating
}

// ==================== HISTORY & STATS ====================

function newConversation() {
    fetch('/api/conversations/new', { method: 'POST' })
        .then(() => loadConversationHistory())
        .catch(err => console.warn('⚠️ Could not reset conversation:', err));
    chatArea.innerHTML = `
        <div class="message assistant">
            <div class="content">
                <div class="message-text">
                    👋 New conversation started! How can I help?
                </div>
            </div>
        </div>
    `;
    messageInput.value = '';
    feedbackBtn.style.display = 'none';
    selectedFolder = null;
    document.getElementById('folder-btn').textContent = '📁 With Folder';
    document.getElementById('folder-btn').style.background = '';
}

function loadConversationHistory() {
    console.log('📜 Loading conversation history...');
    fetch('/api/history?limit=5')
    .then(r => r.json())
    .then(data => {
        const list = document.getElementById('conversations-list');
        if (data.messages && data.messages.length > 0) {
            list.innerHTML = '';
            const recent = data.messages;
            recent.forEach((conv, idx) => {
                const div = document.createElement('div');
                div.style.cssText = 'padding: 8px; border-left: 3px solid var(--accent-1); margin: 5px 0; cursor: pointer; font-size: 12px;';
                const preview = conv.content.substring(0, 30) + '...';
                div.textContent = conv.role === 'user' ? `You: ${preview}` : `AI: ${preview}`;
                list.appendChild(div);
            });
        }
    })
    .catch(err => console.warn('⚠️ History error:', err));
}

function updateStats() {
    console.log('📊 Updating stats...');
    fetch('/api/stats')
    .then(r => r.json())
    .then(data => {
        console.log('Stats data:', data);
        if (data.success) {
            document.getElementById('msg-count').textContent = data.message_count || 0;
            document.getElementById('file-count').textContent = data.files || 0;
            document.getElementById('code-count').textContent = data.code_runs || 0;
        } else {
            console.warn('Stats error:', data.error);
        }
    })
    .catch(err => console.error('❌ Stats error:', err));
}

// ==================== FILES THE AI SAVES ====================

function showSaveFileRequest(path, content, exists) {
    const blockDiv = document.createElement('div');
    blockDiv.className = 'code-execution-request';
    blockDiv.innerHTML = `
        <div style="background: var(--accent-1); color: white; padding: 10px; border-radius: 5px; margin-bottom: 10px;">
            <strong>💾 Save this file?</strong> You can change the name and text first.
        </div>
        <label class="save-field">File name <input class="save-path" type="text" spellcheck="false"></label>
        <div class="save-note"></div>
        <textarea class="save-content" spellcheck="false"></textarea>
        <div style="display: flex; gap: 10px;">
            <button class="btn-execute">💾 Save</button>
            <button class="btn-skip">❌ Skip</button>
        </div>
    `;
    const pathInput = blockDiv.querySelector('.save-path');
    const contentBox = blockDiv.querySelector('.save-content');
    const note = blockDiv.querySelector('.save-note');
    pathInput.value = path;
    contentBox.value = content;
    contentBox.rows = Math.min(Math.max(content.split('\n').length + 1, 4), 15);
    const showNote = () => {
        note.textContent = exists && pathInput.value.trim() === path ? `This replaces your saved ${path}.` : '';
    };
    pathInput.oninput = showNote;
    showNote();
    const saveBtn = blockDiv.querySelector('.btn-execute');
    saveBtn.onclick = () => saveFile(saveBtn, pathInput.value.trim(), contentBox.value, blockDiv);
    blockDiv.querySelector('.btn-skip').onclick = () => blockDiv.remove();

    const follow = isNearBottom();
    chatArea.appendChild(blockDiv);
    keepScrolled(follow);
}

function saveFile(button, path, content, blockDiv) {
    button.disabled = true;
    button.textContent = '⏳ Saving...';
    fetch('/api/files/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, content })
    })
    .then(r => r.json())
    .then(data => {
        showCodeResult(blockDiv, !!data.success, data.success ? data.message : (data.error || 'Could not save'), '');
        button.style.display = data.success ? 'none' : '';
        if (data.success) blockDiv.querySelectorAll('input, textarea').forEach(el => { el.disabled = true; });
        button.disabled = false;
        button.textContent = '💾 Save';
        loadFilesList();
        updateStats();
    })
    .catch(err => {
        showCodeResult(blockDiv, false, err.message);
        button.disabled = false;
        button.textContent = '💾 Save';
    });
}

function loadFilesList() {
    fetch('/api/files')
    .then(r => r.json())
    .then(data => {
        const list = document.getElementById('files-list');
        list.innerHTML = '';
        if (!data.files || !data.files.length) {
            list.innerHTML = '<p style="font-size: 12px; color: var(--text-secondary);">No files yet. Ask the AI to create one!</p>';
            return;
        }
        for (const file of data.files) {
            const row = document.createElement('div');
            row.style.cssText = 'display: flex; align-items: center; gap: 6px; padding: 4px 0; border-bottom: 1px solid var(--border-color);';
            const link = document.createElement('a');
            link.href = `/api/files/download?path=${encodeURIComponent(file.path)}`;
            link.textContent = `📄 ${file.path}`;
            link.title = 'Download';
            link.style.cssText = 'flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: inherit;';
            const remove = document.createElement('button');
            remove.textContent = '🗑️';
            remove.title = 'Delete';
            remove.style.cssText = 'background: none; border: none; cursor: pointer;';
            remove.onclick = () => deleteSavedFile(file.path);
            row.append(link, remove);
            list.appendChild(row);
        }
    })
    .catch(err => console.warn('⚠️ Files error:', err));
}

function deleteSavedFile(path) {
    if (!confirm(`Delete ${path}?`)) return;
    fetch(`/api/files?path=${encodeURIComponent(path)}`, { method: 'DELETE' })
    .then(r => r.json())
    .then(data => {
        addMessage('assistant', data.success ? `🗑️ ${data.message}` : `❌ ${data.error}`);
        loadFilesList();
        updateStats();
    });
}

// ==================== MODELS ====================

let modelPollTimer = null;

function formatSize(bytes) {
    return bytes ? `${(bytes / 1e9).toFixed(1)} GB` : '';
}

function modelRow(label, detail, onClick, highlight) {
    const row = document.createElement('button');
    row.className = 'btn-secondary';
    row.style.cssText = `display: flex; justify-content: space-between; gap: 8px; width: 100%; margin: 3px 0; text-align: left;${highlight ? ' border: 2px solid var(--accent-1);' : ''}`;
    const name = document.createElement('strong');
    name.textContent = label;
    const info = document.createElement('small');
    info.textContent = detail;
    row.append(name, info);
    row.onclick = onClick;
    return row;
}

function sameModel(a, b) {
    const full = name => name.split('/').pop().includes(':') ? name : `${name}:latest`;
    return full(a) === full(b);
}

function renderModelPanel(data) {
    document.getElementById('model-btn').textContent = `🧠 Model: ${data.current}`;
    document.getElementById('model-current').textContent =
        `In use: ${data.current}` + (data.current_installed ? '' : ' (not downloaded yet: pick it below to download)');

    const error = document.getElementById('model-error');
    error.style.display = data.error ? 'block' : 'none';
    error.textContent = data.error ? `⚠️ ${data.error}` : '';

    const installed = document.getElementById('model-installed');
    installed.innerHTML = '';
    if (!data.installed.length) {
        installed.textContent = data.error ? '' : 'No models downloaded yet.';
    }
    for (const model of data.installed) {
        const inUse = sameModel(model.name, data.current);
        const inMemory = data.loaded.some(name => sameModel(name, model.name));
        const detail = [formatSize(model.size), inMemory ? 'in memory' : '', inUse ? '✓ in use' : ''].filter(Boolean).join(' · ');
        installed.appendChild(modelRow(model.name, detail, () => selectModel(model.name), inUse));
    }

    const suggestions = document.getElementById('model-suggestions');
    suggestions.innerHTML = '';
    for (const model of data.suggestions) {
        if (data.installed.some(m => sameModel(m.name, model.name))) continue;
        suggestions.appendChild(modelRow(model.name, `${model.size} · ${model.note}`, () => selectModel(model.name), false));
    }

    const box = document.getElementById('model-download');
    const d = data.download;
    box.style.display = d && !(d.done && !d.error) ? 'block' : 'none';
    if (d) {
        const pct = d.total ? Math.floor(d.completed * 100 / d.total) : 0;
        document.getElementById('model-progress-bar').style.width = `${d.done && !d.error ? 100 : pct}%`;
        document.getElementById('model-download-text').textContent = d.error
            ? `❌ Couldn't download ${d.model}: ${d.error}`
            : `Downloading ${d.model}: ${d.status}${d.total ? ` ${pct}%` : ''}`;
    }
}

async function refreshModels() {
    try {
        const data = await (await fetch('/api/models')).json();
        renderModelPanel(data);
        return data;
    } catch (err) {
        console.warn('⚠️ Could not load models:', err);
        return null;
    }
}

function showModelPanel() {
    document.getElementById('model-panel').style.display = 'flex';
    refreshModels();
}

function closeModelPanel() {
    document.getElementById('model-panel').style.display = 'none';
}

function watchModelDownload() {
    clearInterval(modelPollTimer);
    modelPollTimer = setInterval(async () => {
        const data = await refreshModels();
        const d = data && data.download;
        if (!d || d.done) {
            clearInterval(modelPollTimer);
            modelPollTimer = null;
            if (d && d.error) addMessage('assistant', `❌ Couldn't download ${d.model}: ${d.error}`);
            else if (d) addMessage('assistant', `🧠 ${d.model} is downloaded and now in use.`);
        }
    }, 1000);
}

async function selectModel(name) {
    name = (name || '').trim();
    if (!name) return;
    try {
        const response = await fetch('/api/models/select', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: name })
        });
        const data = await response.json();
        if (!data.success) {
            const error = document.getElementById('model-error');
            error.style.display = 'block';
            error.textContent = `⚠️ ${data.error}`;
            return;
        }
        document.getElementById('model-name-input').value = '';
        if (data.action === 'downloading') {
            watchModelDownload();
        } else if (data.action === 'switched') {
            addMessage('assistant', `🧠 ${data.message}`);
        }
        await refreshModels();
    } catch (err) {
        addMessage('assistant', `❌ Couldn't change the model: ${err.message}`);
    }
}

// ==================== DARK MODE ====================

function toggleDarkMode() {
    document.body.classList.toggle('dark-mode');
    localStorage.setItem('darkMode', document.body.classList.contains('dark-mode'));
}

// ==================== LOG STARTUP ====================
console.log('✅ Script loaded - Chat interface ready!');
console.log('Available commands: analyzeMyself(), showLearning(), showImprovements(), selfImprove()');

// ==================== LOGS FOR TROUBLESHOOTING ====================
// The 🐞 button downloads the app's log of the last few minutes plus the page's own errors,
// so whoever helps can see exactly what happened.

const LOG_MINUTES = 5;
const pageEvents = [];

function notePageEvent(text) {
    pageEvents.push({ time: Date.now(), text: String(text) });
    if (pageEvents.length > 200) pageEvents.shift();
}

function localStamp(time) {
    const d = new Date(time);
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} `
        + `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function recentPageEvents(minutes) {
    const cutoff = Date.now() - minutes * 60 * 1000;
    return pageEvents.filter(e => e.time >= cutoff).map(e => `${localStamp(e.time)} ${e.text}`);
}

window.addEventListener('error', e => notePageEvent(`Page error: ${e.message} (${e.filename}:${e.lineno})`));
window.addEventListener('unhandledrejection', e => notePageEvent(`Page error: ${e.reason}`));

// Note failed requests too (e.g. when the black window was closed)
const unloggedFetch = window.fetch.bind(window);
window.fetch = (resource, options) => {
    const request = `${(options && options.method) || 'GET'} ${resource}`;
    return unloggedFetch(resource, options).then(response => {
        if (!response.ok) notePageEvent(`${request} → HTTP ${response.status}`);
        return response;
    }, err => {
        notePageEvent(`${request} failed: ${err.message}`);
        throw err;
    });
};

function downloadLogs() {
    const button = document.getElementById('logs-btn');
    button.disabled = true;
    unloggedFetch(`/api/logs?minutes=${LOG_MINUTES}`)
    .then(r => r.json())
    .then(data => data.report || data.error)
    .catch(err => `Couldn't get the app's log (${err.message}). Is the black window still open?`)
    .then(appLog => {
        const page = recentPageEvents(LOG_MINUTES);
        const text = [appLog, '', '--- Page ---', ...(page.length ? page : ['(no errors in the page)']),
                      `Browser: ${navigator.userAgent}`, ''].join('\n');
        const name = `assistant-logs-${localStamp(Date.now()).replace(/[: ]/g, '-')}.txt`;
        const link = document.createElement('a');
        link.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
        link.download = name;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(link.href), 10000);
        addMessage('assistant', `🐞 Saved the last ${LOG_MINUTES} minutes of logs as ${name} in your Downloads `
            + 'folder. Send that file to whoever is helping you.');
    })
    .finally(() => { button.disabled = false; });
}
