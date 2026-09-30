// Tests for the browser code's text handling. Run: node --test tests/frontend.test.js
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Load the page's scripts with just enough of a fake browser for their top-level code to run
const element = () => ({ style: {}, classList: { add() {}, remove() {}, toggle() {} }, addEventListener() {} });
const context = {
    document: { getElementById: element, addEventListener() {}, body: element() },
    localStorage: { getItem: () => null, setItem() {} },
    window: { addEventListener() {}, fetch: async () => ({ ok: false, status: 500 }) },
    console: { log() {}, warn() {}, error() {} },
};
vm.createContext(context);
// The page's scripts, in the order index.html loads them
const page = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');
for (const [, name] of page.matchAll(/filename='js\/([\w-]+\.js)'/g)) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'static', 'js', name), 'utf8'), context, { filename: name });
}
const { escapeHtml, renderText, parseUpgradeRequest } = context;

test('escapeHtml neutralises HTML', () => {
    assert.strictEqual(escapeHtml(`<img src=x onerror="alert('x')">&`),
        '&lt;img src=x onerror=&quot;alert(&#39;x&#39;)&quot;&gt;&amp;');
});

test('renderText escapes first, then formats', () => {
    assert.strictEqual(renderText('<b>hi</b> **bold**\nline file_name_here'),
        '&lt;b&gt;hi&lt;/b&gt; <strong>bold</strong><br>line file_name_here');
    assert.strictEqual(renderText('**<script>x</script>**'), '<strong>&lt;script&gt;x&lt;/script&gt;</strong>');
});

test('parseUpgradeRequest keeps code with blank lines', () => {
    const message = 'Sure.\nUPGRADE_REQUEST:\nFILE: memory.py\nDESCRIPTION: Add caching\nCODE:\n```python\nimport os\n\n\ndef f():\n    return 1\n```\nDone.';
    assert.deepStrictEqual({ ...parseUpgradeRequest(message) },
        { file: 'memory.py', description: 'Add caching', code: 'import os\n\n\ndef f():\n    return 1' });
});

test('parseUpgradeRequest handles Windows line endings and missing fences', () => {
    const crlf = 'UPGRADE_REQUEST:\r\nFILE: a.py\r\nDESCRIPTION: d\r\nCODE:\r\nx = 1\r\n';
    const parsed = parseUpgradeRequest(crlf);
    assert.strictEqual(parsed.file, 'a.py');
    assert.strictEqual(parsed.code.trim(), 'x = 1');
});

test('parseUpgradeRequest ignores normal messages', () => {
    assert.strictEqual(parseUpgradeRequest('Just a normal answer'), null);
    assert.strictEqual(parseUpgradeRequest('UPGRADE_REQUEST: FILE: a.py DESCRIPTION: d CODE:'), null);
});

test('failed requests are noted for the logs button', async () => {
    await context.window.fetch('/api/chat', { method: 'POST' });
    assert.match(context.recentPageEvents(5).join('\n'), /^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d POST \/api\/chat → HTTP 500$/m);
    assert.strictEqual(context.localStamp(new Date(2026, 8, 29, 7, 5, 3).getTime()), '2026-09-29 07:05:03');
});

test('every button in the page calls a function that exists', () => {
    const called = [...page.matchAll(/on(?:click|change|keydown)="(?:if \([^)]*\) )?([A-Za-z_]\w*)\(/g)].map(m => m[1]);
    assert.ok(called.length > 20);
    assert.deepStrictEqual(called.filter(name => name !== 'document' && typeof context[name] !== 'function'), []);
});

test('fileType labels saved files by extension', () => {
    assert.strictEqual(context.fileType('shopping.TXT '), 'txt');
    assert.strictEqual(context.fileType('notes/todo.md'), 'md');
    assert.strictEqual(context.fileType('Makefile'), 'text');
});
