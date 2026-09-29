// Tests for the browser code's text handling. Run: node --test tests/frontend.test.js
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Load script.js with just enough of a fake browser for its top-level code to run
const element = () => ({ style: {}, classList: { add() {}, remove() {}, toggle() {} }, addEventListener() {} });
const context = {
    document: { getElementById: element, addEventListener() {}, body: element() },
    localStorage: { getItem: () => null, setItem() {} },
    console: { log() {}, warn() {}, error() {} },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'script.js'), 'utf8'), context);
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
