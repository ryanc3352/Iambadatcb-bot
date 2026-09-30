// The ⬆️ Update button: install the newest version from GitHub, then wait for the app to restart.

async function updateApp() {
    if (!confirm('Download the newest version of the app from GitHub and restart it?\n\n'
                 + 'Your chats, saved files and settings are kept.')) return;
    const button = document.getElementById('update-btn');
    button.disabled = true;
    button.textContent = '⏳ Updating...';
    try {
        const data = await api('/api/update', { confirm: true });
        if (!data.success) {
            addMessage('assistant', `❌ Update failed: ${data.error || 'Unknown error'}`);
        } else if (!data.changed.length) {
            addMessage('assistant', '✅ The app is already up to date.');
        } else if (data.restarting) {
            addMessage('assistant', `⬆️ Updated ${data.changed.length} files. Restarting the app...`);
            await waitForRestart();
            location.reload();
            return;
        } else {
            addMessage('assistant', `⬆️ Updated ${data.changed.length} files. Close the app's black window and `
                                    + 'start it again with "Start AI.bat" to use the new version.');
        }
    } catch (err) {
        addMessage('assistant', `❌ Update failed: ${err.message}`);
    }
    button.disabled = false;
    button.textContent = '⬆️ Update app';
}

// The app is gone for a few seconds (longer when new libraries are installed); wait until it answers again
async function waitForRestart() {
    await new Promise(resolve => setTimeout(resolve, 3000));
    for (let i = 0; i < 600; i++) {
        try {
            if ((await fetch('/api/stats', { cache: 'no-store' })).ok) return;
        } catch (e) { /* not back yet */ }
        await new Promise(resolve => setTimeout(resolve, 2000));
    }
}
