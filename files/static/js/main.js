// Start-up: fill the sidebar and restore dark mode. Loaded last.

document.addEventListener('DOMContentLoaded', () => {
    setUpFoldingSections();
    restoreCurrentChat();
    updateStats();
    loadFoldersList();
    loadFilesList();
    // Show the model in use, and keep showing progress if a download is still running
    refreshModels().then(data => {
        if (data && data.download && !data.download.done) watchModelDownload();
    });
    if (localStorage.getItem('darkMode') === 'true') document.body.classList.add('dark-mode');
});

function toggleDarkMode() {
    document.body.classList.toggle('dark-mode');
    localStorage.setItem('darkMode', document.body.classList.contains('dark-mode'));
}
