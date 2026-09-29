// Cards in the chat that wait for the user: run code, save a file, apply an upgrade.

function showCodeResult(card, success, text, successLabel = '✅ Output:') {
    const result = document.createElement('div');
    result.className = success ? 'code-output' : 'code-error';
    const label = success ? successLabel : '❌ Error:';
    result.innerHTML = (label ? `<strong>${label}</strong><br>` : '') + renderText(text);
    card.appendChild(result);
}

// ==================== RUN CODE ====================

function showCodeRequest(code) {
    const card = document.createElement('div');
    card.className = 'code-execution-request';
    card.innerHTML = `
        <div class="card-title">
            <strong>💻 Code Execution Request</strong>
            <small>Runs on your computer with your permissions. Read it before executing.</small>
        </div>
        <div class="code-block"><div class="code-lines"></div></div>
        <div class="card-buttons">
            <button class="btn-execute">✅ Execute</button>
            <button class="btn-skip">❌ Skip</button>
        </div>
    `;
    card.querySelector('.code-lines').textContent = code;
    const runBtn = card.querySelector('.btn-execute');
    runBtn.onclick = () => executeCode(runBtn, code, card);
    card.querySelector('.btn-skip').onclick = () => card.remove();
    appendToChat(card);
}

function executeCode(button, code, card) {
    button.disabled = true;
    button.textContent = '⏳ Running...';
    api('/api/execute-code', { code })
    .then(data => {
        showCodeResult(card, data.success, data.output || data.error || '');
        button.hidden = true;
        updateStats();
    })
    .catch(err => {
        showCodeResult(card, false, err.message);
        button.disabled = false;
        button.textContent = '✅ Execute';
    });
}

// ==================== SAVE A FILE ====================

function showSaveFileRequest(path, content, exists) {
    const card = document.createElement('div');
    card.className = 'code-execution-request';
    card.innerHTML = `
        <div class="card-title"><strong>💾 Save this file?</strong> You can change the name and text first.</div>
        <label class="save-field">File name <input class="save-path" type="text" spellcheck="false"></label>
        <div class="save-note"></div>
        <textarea class="save-content" spellcheck="false"></textarea>
        <div class="card-buttons">
            <button class="btn-execute">💾 Save</button>
            <button class="btn-skip">❌ Skip</button>
        </div>
    `;
    const pathInput = card.querySelector('.save-path');
    const contentBox = card.querySelector('.save-content');
    const note = card.querySelector('.save-note');
    pathInput.value = path;
    contentBox.value = content;
    contentBox.rows = Math.min(Math.max(content.split('\n').length + 1, 4), 15);
    const showNote = () => {
        note.textContent = exists && pathInput.value.trim() === path ? `This replaces your saved ${path}.` : '';
    };
    pathInput.oninput = showNote;
    showNote();
    const saveBtn = card.querySelector('.btn-execute');
    saveBtn.onclick = () => saveFile(saveBtn, pathInput.value.trim(), contentBox.value, card);
    card.querySelector('.btn-skip').onclick = () => card.remove();
    appendToChat(card);
}

function saveFile(button, path, content, card) {
    button.disabled = true;
    button.textContent = '⏳ Saving...';
    api('/api/files/save', { path, content })
    .then(data => {
        showCodeResult(card, !!data.success, data.success ? data.message : (data.error || 'Could not save'), '');
        button.hidden = !!data.success;
        if (data.success) card.querySelectorAll('input, textarea').forEach(el => { el.disabled = true; });
        loadFilesList();
        updateStats();
    })
    .catch(err => showCodeResult(card, false, err.message))
    .finally(() => {
        button.disabled = false;
        button.textContent = '💾 Save';
    });
}

// ==================== UPGRADES ====================

function showUpgradeRequest(file, description, code) {
    const lines = code.split('\n');
    const card = document.createElement('div');
    card.className = 'upgrade-card';
    card.innerHTML = `
        <h3>🔧 AI Wants to Upgrade Your Code</h3>
        <p><strong>File:</strong> <span class="upgrade-file"></span></p>
        <p><strong>Change:</strong> <span class="upgrade-change"></span></p>
        <div class="upgrade-preview"></div>
        <div class="card-buttons">
            <button class="upgrade-approve">✅ Approve & Apply</button>
            <button class="upgrade-reject">❌ Reject</button>
        </div>
    `;
    card.querySelector('.upgrade-file').textContent = file;
    card.querySelector('.upgrade-change').innerHTML = renderText(description);
    card.querySelector('.upgrade-preview').textContent = 'Code preview:\n' + lines.slice(0, 20).join('\n')
        + (lines.length > 20 ? `\n... (${lines.length - 20} more lines)` : '');
    const approveBtn = card.querySelector('.upgrade-approve');
    approveBtn.onclick = () => approveUpgrade(approveBtn, file, description, code, card);
    card.querySelector('.upgrade-reject').onclick = () => rejectUpgrade(card);
    appendToChat(card);
}

function approveUpgrade(button, file, description, code, card) {
    button.disabled = true;
    button.textContent = '⏳ Applying...';
    const failed = message => {
        addMessage('assistant', message);
        button.disabled = false;
        button.textContent = '✅ Approve & Apply';
    };
    api('/api/upgrade/apply', { file, description, code })
    .then(data => {
        if (!data.success) return failed(`❌ Upgrade failed: ${data.message || data.error}`);
        addMessage('assistant', `✅ Upgrade applied to ${file}!\n\n${data.message}\n\n⚠️ Restart the server to use the new code.`);
        card.remove();
    })
    .catch(err => failed(`❌ Error applying upgrade: ${err.message}`));
}

function rejectUpgrade(card) {
    addMessage('assistant', '❌ Upgrade rejected. Not applying changes.');
    card.remove();
}
