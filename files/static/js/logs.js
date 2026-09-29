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
