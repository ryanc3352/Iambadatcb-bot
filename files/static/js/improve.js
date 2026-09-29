// Self-improvement buttons and rating answers.

function analyzeMyself() {
    showReport('/api/self/analyze', 'report');
}

function showLearning() {
    showReport('/api/self/learning', 'report');
}

function showImprovements() {
    showReport('/api/self/improvements', 'suggestions_text');
}

// Ask the model to improve one of its files (the prompt names the file, so its code is shown)
function selfImprove() {
    api('/api/self/improvement-prompt')
    .then(data => {
        if (data.success) sendMessage(data.prompt);
        else addMessage('assistant', `❌ Error: ${data.error}`);
    })
    .catch(err => addMessage('assistant', `❌ Error: ${err.message}`));
}

// ==================== FEEDBACK ====================

function showFeedbackPanel() {
    feedbackPanel.hidden = false;
}

function closeFeedbackPanel() {
    feedbackPanel.hidden = true;
    document.getElementById('feedback-text').value = '';
}

function rateResponse(stars) {
    const feedback = document.getElementById('feedback-text').value;
    api('/api/feedback', { rating: stars, feedback })
    .then(() => {
        addMessage('assistant', '✅ Thanks for the feedback! I\'m learning and improving.');
        closeFeedbackPanel();
    })
    .catch(() => addMessage('assistant', '❌ Error submitting feedback'));
}

function submitFeedback() {
    rateResponse(3);  // feedback text without picking stars
}
