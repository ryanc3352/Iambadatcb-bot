// The sidebar: new conversation, history, documents, project folders, the user's files and stats.

function emptyNote(text) {
    return `<p class="hint">${escapeHtml(text)}</p>`;
}

// ==================== CHATS ====================

let currentChatId = null;

function showWelcome(text) {
    chatArea.innerHTML = `
        <div class="message assistant">
            <div class="content">
                <div class="message-text">${escapeHtml(text)}</div>
            </div>
        </div>
    `;
    messageInput.value = '';
    feedbackBtn.hidden = true;
    useFolder(null);
}

function newConversation() {
    if (sendBtn.disabled) return alert('Please wait until the answer has finished.');
    api('/api/conversations/new', {})
    .then(() => loadChats())
    .catch(err => console.warn('⚠️ Could not reset conversation:', err));
    showWelcome('👋 New conversation started! How can I help?');
}

// "2026-09-30 09:15:00" (UTC, from the database) as a short local date and time
function chatDate(timestamp) {
    const date = new Date(String(timestamp).replace(' ', 'T') + 'Z');
    if (isNaN(date)) return '';
    const sameDay = date.toDateString() === new Date().toDateString();
    return sameDay ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                   : date.toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' });
}

function chatButton(icon, title, onClick) {
    const button = document.createElement('button');
    button.className = 'icon-btn';
    button.textContent = icon;
    button.title = title;
    button.onclick = (e) => {
        e.stopPropagation();
        onClick();
    };
    return button;
}

// Fill the Past Chats list; resolves to the server's reply
async function loadChats() {
    try {
        const data = await api('/api/conversations');
        if (!data.success) return data;
        currentChatId = data.current;
        const list = document.getElementById('conversations-list');
        if (!data.conversations.length) {
            list.innerHTML = emptyNote('No chats yet');
            return data;
        }
        list.innerHTML = '';
        for (const chat of data.conversations) {
            const item = document.createElement('div');
            item.className = 'chat-item' + (chat.id === data.current ? ' active' : '');
            item.title = chat.id === data.current ? 'The chat you are in' : 'Open this chat';
            const text = document.createElement('div');
            text.className = 'chat-text';
            const title = document.createElement('div');
            title.className = 'chat-title';
            title.textContent = chat.title;
            const date = document.createElement('small');
            date.textContent = chatDate(chat.updated);
            text.append(title, date);
            item.append(text,
                chatButton('✏️', 'Rename', () => renameChat(chat.id, chat.title)),
                chatButton('🗑️', 'Delete', () => deleteChat(chat.id, chat.title)));
            item.onclick = () => openChat(chat.id);
            list.appendChild(item);
        }
        return data;
    } catch (err) {
        console.warn('⚠️ Chats error:', err);
        return null;
    }
}

// "notes.md" -> "md": labels a file's text in an old chat
function fileType(path) {
    const match = path.trim().match(/\.([\w+-]+)$/);
    return match ? match[1].toLowerCase() : 'text';
}

// Show a saved chat's messages. Files it offered are shown as text (they were saved, or not, back then).
function showChat(messages) {
    chatArea.innerHTML = '';
    for (const message of messages) {
        const content = message.role === 'user' ? message.content : message.content.replace(
            SAVE_FILE_BLOCK, (_, path, body) => `📄 File: ${path.trim()}\n\`\`\`${fileType(path)}\n${body}\n\`\`\``);
        addMessage(message.role === 'user' ? 'user' : 'assistant', content);
    }
    chatArea.scrollTop = chatArea.scrollHeight;
}

async function openChat(chatId) {
    if (chatId === currentChatId && chatArea.querySelector('.message.user')) return;  // already showing it
    if (sendBtn.disabled) return alert('Please wait until the answer has finished.');
    try {
        const data = await api(`/api/conversations/${chatId}/open`, {});
        if (!data.success) {
            addMessage('assistant', `❌ ${data.error}`);
        } else {
            showWelcome('');
            showChat(data.messages);
        }
    } catch (err) {
        addMessage('assistant', `❌ Could not open the chat: ${err.message}`);
    }
    loadChats();
}

async function renameChat(chatId, oldTitle) {
    const title = prompt('New name for this chat (leave empty to name it after its first question):', oldTitle);
    if (title === null) return;
    const data = await api(`/api/conversations/${chatId}/rename`, { title });
    if (!data.success) addMessage('assistant', `❌ ${data.error}`);
    loadChats();
}

async function deleteChat(chatId, title) {
    if (sendBtn.disabled) return alert('Please wait until the answer has finished.');
    if (!confirm(`Delete the chat "${title}"?\nThe AI will forget it too. This can't be undone.`)) return;
    const data = await api(`/api/conversations/${chatId}`, undefined, 'DELETE');
    if (!data.success) {
        addMessage('assistant', `❌ ${data.error}`);
    } else if (chatId === currentChatId) {
        showWelcome('🗑️ Chat deleted. Ask me anything to start a new one.');
    }
    loadChats();
    updateStats();
}

// On start-up: show the chat that was open last time
async function restoreCurrentChat() {
    const data = await loadChats();
    if (!data || !data.success || !data.conversations.some(chat => chat.id === data.current)) return;
    const chat = await api(`/api/conversations/${data.current}`);
    if (chat.success && chat.messages.length) showChat(chat.messages);
}

function updateStats() {
    api('/api/stats')
    .then(data => {
        if (!data.success) return;
        document.getElementById('msg-count').textContent = data.message_count || 0;
        document.getElementById('file-count').textContent = data.files || 0;
        document.getElementById('code-count').textContent = data.code_runs || 0;
    })
    .catch(err => console.warn('⚠️ Stats error:', err));
}

// ==================== DOCUMENTS ====================

function uploadDocument(event) {
    const file = event.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    addMessage('user', `📤 Uploading: ${file.name}`);
    api('/api/knowledge-base/upload', formData)
    .then(data => addMessage('assistant', data.success ? data.message : `❌ Error: ${data.message || data.error}`))
    .catch(err => addMessage('assistant', `❌ Upload failed: ${err.message}`))
    .finally(() => { event.target.value = ''; });
}

function loadDocumentsList() {
    api('/api/knowledge-base/list')
    .then(data => addMessage('assistant', data.documents && data.documents.length
        ? '📚 Your Documents:\n\n' + data.documents.map(doc => `• ${doc}`).join('\n')
        : 'No documents uploaded yet.'))
    .catch(err => addMessage('assistant', `❌ Could not load documents: ${err.message}`));
}

// ==================== PROJECT FOLDERS ====================

// Chat about `folderName` from now on (or stop, with null)
function useFolder(folderName) {
    selectedFolder = folderName;
    const button = document.getElementById('folder-btn');
    button.textContent = folderName ? `📁 ${folderName}` : '📁 With Folder';
    button.classList.toggle('active', !!folderName);
}

async function loadFoldersList() {
    try {
        const data = await api('/api/folders/list');
        if (!data.success) return;
        const list = document.getElementById('folders-list');
        if (!data.folders.length) {
            list.innerHTML = emptyNote('No folders uploaded');
            return;
        }
        list.innerHTML = '';
        for (const folder of data.folders) {
            const div = document.createElement('div');
            div.className = 'folder-item';
            div.innerHTML = `<strong>${escapeHtml(folder.name)}</strong><br><small>${Number(folder.file_count) || 0} files</small>`;
            div.onclick = () => selectFolder(folder.name);
            const deleteBtn = document.createElement('button');
            deleteBtn.className = 'folder-delete';
            deleteBtn.textContent = '🗑️';
            deleteBtn.onclick = (e) => {
                e.stopPropagation();
                deleteFolder(folder.name);
            };
            div.appendChild(deleteBtn);
            list.appendChild(div);
        }
    } catch (err) {
        console.warn('⚠️ Could not load folders:', err);
    }
}

function selectFolder(folderName) {
    useFolder(folderName);
    addMessage('user', `📁 Selected folder: ${folderName}`);
    api(`/api/folders/${encodeURIComponent(folderName)}/summary`)
    .then(data => { if (data.success) addMessage('assistant', data.summary); })
    .catch(() => addMessage('assistant', '❌ Error loading folder summary'));
}

function selectFolderMode() {
    if (selectedFolder) {
        useFolder(null);
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
    sendFolder('/api/folders/upload-files', formData, event.target);
}

function uploadFolder(event) {
    const file = event.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('folder', file);
    formData.append('folder_name', file.name.replace(/\.zip$/i, ''));
    addMessage('user', `📤 Uploading folder: ${file.name}`);
    sendFolder('/api/folders/upload', formData, event.target);
}

function sendFolder(url, formData, input) {
    api(url, formData)
    .then(data => {
        addMessage('assistant', data.success ? data.message : `❌ Error: ${data.error || data.message}`);
        loadFoldersList();
    })
    .catch(err => addMessage('assistant', `❌ Upload failed: ${err.message}`))
    .finally(() => { input.value = ''; });
}

async function deleteFolder(folderName) {
    if (!confirm(`Delete folder "${folderName}"?`)) return;
    const data = await api(`/api/folders/${encodeURIComponent(folderName)}/delete`, undefined, 'DELETE');
    addMessage('assistant', data.message || data.error);
    if (selectedFolder === folderName) selectFolderMode();  // stop chatting with a deleted folder
    await loadFoldersList();
}

// ==================== MY FILES ====================

function loadFilesList() {
    api('/api/files')
    .then(data => {
        const list = document.getElementById('files-list');
        if (!data.files || !data.files.length) {
            list.innerHTML = emptyNote('No files yet. Ask the AI to create one!');
            return;
        }
        list.innerHTML = '';
        for (const file of data.files) {
            const row = document.createElement('div');
            row.className = 'file-row';
            const link = document.createElement('a');
            link.href = `/api/files/download?path=${encodeURIComponent(file.path)}`;
            link.textContent = `📄 ${file.path}`;
            link.title = 'Download';
            const remove = document.createElement('button');
            remove.className = 'icon-btn';
            remove.textContent = '🗑️';
            remove.title = 'Delete';
            remove.onclick = () => deleteSavedFile(file.path);
            row.append(link, remove);
            list.appendChild(row);
        }
    })
    .catch(err => console.warn('⚠️ Files error:', err));
}

function deleteSavedFile(path) {
    if (!confirm(`Delete ${path}?`)) return;
    api(`/api/files?path=${encodeURIComponent(path)}`, undefined, 'DELETE')
    .then(data => {
        addMessage('assistant', data.success ? `🗑️ ${data.message}` : `❌ ${data.error}`);
        loadFilesList();
        updateStats();
    });
}
