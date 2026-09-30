// Cards in the chat that wait for the user: run code, save a file, apply an upgrade.

function showCodeResult(card, success, text, successLabel = '✅ Output:') {
    const result = document.createElement('div');
    result.className = success ? 'code-output' : 'code-error';
    const label = success ? successLabel : '❌ Error:';
    result.innerHTML = (label ? `<strong>${label}</strong><br>` : '') + renderText(text);
    card.appendChild(result);
}

// ==================== RUN CODE ====================

function showCodeRequest(code, packages = []) {
    const card = document.createElement('div');
    card.className = 'code-execution-request';
    card.innerHTML = `
        <div class="card-title">
            <strong>💻 Code Execution Request</strong>
            <small>Runs on your computer with your permissions. Read it before executing.
                Missing packages are installed automatically.</small>
        </div>
        <div class="code-block"><div class="code-lines"></div></div>
        <div class="code-packages hint" hidden></div>
        <label class="code-answers" hidden>Typed answers: what the program asks for with input(), one per line
            <textarea class="save-content code-input" rows="3" spellcheck="false"></textarea>
        </label>
        <div class="card-buttons">
            <button class="btn-execute">✅ Execute</button>
            <button class="btn-skip btn-stop" hidden>⏹ Stop</button>
            <button class="btn-skip btn-dismiss">❌ Skip</button>
        </div>
    `;
    card.querySelector('.code-lines').textContent = code;
    if (packages.length) {
        const note = card.querySelector('.code-packages');
        note.textContent = `📦 Installs first if missing: ${packages.join(', ')}`;
        note.hidden = false;
    }
    card.querySelector('.code-answers').hidden = !/\binput\s*\(/.test(code);
    const runBtn = card.querySelector('.btn-execute');
    runBtn.onclick = () => executeCode(runBtn, code, packages, card);
    card.querySelector('.btn-dismiss').onclick = () => card.remove();
    appendToChat(card);
}

// Runs the code with no time limit, showing its output as it comes; ⏹ Stop ends it
async function executeCode(button, code, packages, card) {
    const stopBtn = card.querySelector('.btn-stop');
    const input = card.querySelector('.code-input').value;
    card.querySelectorAll('.code-output, .code-error').forEach(el => el.remove());
    const live = document.createElement('div');
    live.className = 'code-output code-live';
    card.appendChild(live);
    button.disabled = true;
    button.textContent = '⏳ Running...';
    card.querySelector('.btn-dismiss').hidden = true;
    stopBtn.hidden = false;
    stopBtn.disabled = false;
    let runId = null;
    stopBtn.onclick = () => {
        stopBtn.disabled = true;
        if (runId) api('/api/stop-code', { run_id: runId }).catch(() => {});
    };
    let result = null;
    try {
        const response = await fetch('/api/execute-code', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code, packages, input })
        });
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.error || `Server error ${response.status}`);
        }
        await readEvents(response, data => {
            if (data.run_id) runId = data.run_id;
            if (data.output !== undefined && !data.done) {
                live.textContent += data.output;
                live.scrollTop = live.scrollHeight;
            }
            if (data.done) result = data;
        });
        if (!result) throw new Error('The app stopped before the code finished');
    } catch (err) {
        result = { success: false, output: err.message };
    }
    live.remove();
    showCodeResult(card, result.success, result.output || '');
    stopBtn.hidden = true;
    button.disabled = false;
    button.textContent = '🔁 Run again';
    card.querySelector('.btn-dismiss').hidden = false;
    updateStats();
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
