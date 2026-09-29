// The 🧠 Model panel: pick, download and switch models.

let modelPollTimer = null;

function formatSize(bytes) {
    return bytes ? `${(bytes / 1e9).toFixed(1)} GB` : '';
}

function modelRow(label, detail, onClick, inUse) {
    const row = document.createElement('button');
    row.className = 'btn-secondary model-row' + (inUse ? ' in-use' : '');
    const name = document.createElement('strong');
    name.textContent = label;
    const info = document.createElement('small');
    info.textContent = detail;
    row.append(name, info);
    row.onclick = onClick;
    return row;
}

// 'mistral' and 'mistral:latest' are the same model
function sameModel(a, b) {
    const full = name => name.split('/').pop().includes(':') ? name : `${name}:latest`;
    return full(a) === full(b);
}

function showModelError(text) {
    const error = document.getElementById('model-error');
    error.hidden = !text;
    error.textContent = text ? `⚠️ ${text}` : '';
}

function renderModelPanel(data) {
    document.getElementById('model-btn').textContent = `🧠 Model: ${data.current}`;
    document.getElementById('model-current').textContent =
        `In use: ${data.current}` + (data.current_installed ? '' : ' (not downloaded yet: pick it below to download)');
    showModelError(data.error);

    const installed = document.getElementById('model-installed');
    installed.innerHTML = '';
    if (!data.installed.length) installed.textContent = data.error ? '' : 'No models downloaded yet.';
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

    const d = data.download;
    document.getElementById('model-download').hidden = !d || (d.done && !d.error);
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
        const data = await api('/api/models');
        renderModelPanel(data);
        return data;
    } catch (err) {
        console.warn('⚠️ Could not load models:', err);
        return null;
    }
}

function showModelPanel() {
    document.getElementById('model-panel').hidden = false;
    refreshModels();
}

function closeModelPanel() {
    document.getElementById('model-panel').hidden = true;
}

function watchModelDownload() {
    clearInterval(modelPollTimer);
    modelPollTimer = setInterval(async () => {
        const data = await refreshModels();
        const d = data && data.download;
        if (d && !d.done) return;
        clearInterval(modelPollTimer);
        modelPollTimer = null;
        if (d && d.error) addMessage('assistant', `❌ Couldn't download ${d.model}: ${d.error}`);
        else if (d) addMessage('assistant', `🧠 ${d.model} is downloaded and now in use.`);
    }, 1000);
}

async function selectModel(name) {
    name = (name || '').trim();
    if (!name) return;
    try {
        const data = await api('/api/models/select', { model: name });
        if (!data.success) {
            showModelError(data.error);
            return;
        }
        document.getElementById('model-name-input').value = '';
        if (data.action === 'downloading') watchModelDownload();
        else if (data.action === 'switched') addMessage('assistant', `🧠 ${data.message}`);
        await refreshModels();
    } catch (err) {
        addMessage('assistant', `❌ Couldn't change the model: ${err.message}`);
    }
}
