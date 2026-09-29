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
                addMessage('assistant', data.response);
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
                throw new Error('Network error');
            }
            
            console.log('📡 Got stream response');
            
            const div = document.createElement('div');
            div.className = 'message assistant';
            const contentDiv = document.createElement('div');
            contentDiv.className = 'content';
            div.appendChild(contentDiv);
            chatArea.appendChild(div);
            currentStreamingDiv = contentDiv;
            
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
                            
                            if (data.token) {
                                fullText += data.token;
                                if (!data.token.includes('```')) {
                                    currentStreamingDiv.innerHTML += escapeHtml(data.token).replace(/\n/g, '<br>');
                                    chatArea.scrollTop = chatArea.scrollHeight;
                                }
                            }
                            
                            if (data.done) {
                                formatted = true;
                                formatMessage(currentStreamingDiv, fullText);
                                if (data.has_code && data.code) {
                                    showCodeRequest(data.code);
                                }
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
    
    // Split content into text and code blocks
    const parts = content.split(/(```[\s\S]*?```)/);
    
    for (let part of parts) {
        if (part.match(/```/)) {
            const codeContent = part.replace(/```python\n?|```\n?/g, '').trim();
            const codeDiv = createCodeBlock(codeContent);
            contentDiv.appendChild(codeDiv);
        } else if (part.trim()) {
            contentDiv.appendChild(textDivFor(part));
        }
    }
    
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
    
    chatArea.appendChild(div);
    chatArea.scrollTop = chatArea.scrollHeight;
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
    contentDiv.innerHTML = '';
    
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

    // Normal message formatting
    const parts = text.split(/(```[\s\S]*?```)/);
    
    for (let part of parts) {
        if (part.match(/```/)) {
            const codeContent = part.replace(/```python\n?|```\n?/g, '').trim();
            const codeDiv = createCodeBlock(codeContent);
            contentDiv.appendChild(codeDiv);
        } else if (part.trim()) {
            contentDiv.appendChild(textDivFor(part));
        }
    }
}

function createCodeBlock(code) {
    const blockDiv = document.createElement('div');
    blockDiv.className = 'code-block';
    
    // Detect language
    let language = 'python';
    if (code.includes('import requests') || code.includes('def ')) language = 'python';
    if (code.includes('function ') || code.includes('const ')) language = 'javascript';
    if (code.includes('SELECT') || code.includes('INSERT')) language = 'sql';
    
    // Header
    const header = document.createElement('div');
    header.className = 'code-block-header';
    header.innerHTML = `
        <span>${language.toUpperCase()}</span>
        <button class="code-copy-btn" onclick="copyCode(this)">📋 Copy</button>
    `;
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

    chatArea.appendChild(blockDiv);
    chatArea.scrollTop = chatArea.scrollHeight;
}

function showCodeResult(blockDiv, success, text) {
    const result = document.createElement('div');
    result.className = success ? 'code-output' : 'code-error';
    result.innerHTML = `<strong>${success ? '✅ Output:' : '❌ Error:'}</strong><br>${renderText(text)}`;
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
            addMessage('assistant', `✅ Document uploaded: ${file.name}`);
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
    });
}

// ==================== FOLDER ACCESS ====================

async function loadFoldersList() {
    console.log('📂 Loading folders list...');
    try {
        const response = await fetch('/api/folders/list');
        const data = await response.json();
        
        console.log('📂 Folders response:', data);
        
        if (data.success && data.folders && data.folders.length > 0) {
            const foldersList = document.getElementById('folders-list');
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

async function deleteFolder(folderName) {
    if (confirm(`Delete folder "${folderName}"?`)) {
        const response = await fetch(`/api/folders/${encodeURIComponent(folderName)}/delete`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        addMessage('assistant', data.message || data.error);
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
    addMessage('user', 'Please analyze yourself and suggest improvements');
    
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

    chatArea.appendChild(blockDiv);
    chatArea.scrollTop = chatArea.scrollHeight;
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
    fetch('/api/history')
    .then(r => r.json())
    .then(data => {
        const list = document.getElementById('conversations-list');
        if (data.messages && data.messages.length > 0) {
            list.innerHTML = '';
            const recent = data.messages.slice(-5);
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
        } else {
            console.warn('Stats error:', data.error);
        }
    })
    .catch(err => console.error('❌ Stats error:', err));
}

// ==================== DARK MODE ====================

function toggleDarkMode() {
    document.body.classList.toggle('dark-mode');
    localStorage.setItem('darkMode', document.body.classList.contains('dark-mode'));
}

// ==================== LOG STARTUP ====================
console.log('✅ Script loaded - Chat interface ready!');
console.log('Available commands: analyzeMyself(), showLearning(), showImprovements(), selfImprove()');
