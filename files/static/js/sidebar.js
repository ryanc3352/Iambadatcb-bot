// The sidebar: new conversation, history, documents, project folders, the user's files and stats.

function emptyNote(text) {
    return `<p class="hint">${escapeHtml(text)}</p>`;
}

// ==================== CONVERSATION ====================

function newConversation() {
    api('/api/conversations/new', {})
    .then(() => loadConversationHistory())
    .catch(err => console.warn('⚠️ Could not reset conversation:', err));
    chatArea.innerHTML = `
        <div class="message assistant">
            <div class="content">
                <div class="message-text">👋 New conversation started! How can I help?</div>
            </div>
        </div>
    `;
    messageInput.value = '';
    feedbackBtn.hidden = true;
    useFolder(null);
}

function loadConversationHistory() {
    api('/api/history?limit=5')
    .then(data => {
        if (!data.messages || !data.messages.length) return;
        const list = document.getElementById('conversations-list');
        list.innerHTML = '';
        for (const message of data.messages) {
            const div = document.createElement('div');
            div.className = 'history-item';
            div.textContent = `${message.role === 'user' ? 'You' : 'AI'}: ${message.content.substring(0, 30)}...`;
            list.appendChild(div);
        }
    })
    .catch(err => console.warn('⚠️ History error:', err));
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
