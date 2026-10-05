const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const root = path.join(__dirname, '..');
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'));

test('every file the manifest references exists', () => {
  const files = [manifest.background.service_worker, manifest.action.default_popup, manifest.options_page,
    ...manifest.content_scripts.flatMap((c) => c.js)];
  for (const f of files) assert.ok(fs.existsSync(path.join(root, f)), `missing ${f}`);
});

test('content scripts load libs before controllers; indeed covers the apply flow host', () => {
  for (const c of manifest.content_scripts) {
    const last = c.js[c.js.length - 1];
    assert.match(last, /^content\//);
    assert.deepEqual(c.js.slice(0, 6), ['lib/mapper.js', 'lib/dom.js', 'lib/form.js', 'lib/flow.js', 'lib/core.js', 'lib/page.js']);
  }
  assert.ok(manifest.content_scripts.some((c) => c.matches.includes('https://*.indeed.com/*') && c.all_frames));
});

test('extension only talks to the local server', () => {
  assert.deepEqual(manifest.host_permissions, ['http://127.0.0.1:8765/*', 'http://localhost:8765/*']);
});

test('popup injects the same lib list the manifest uses', () => {
  const popup = fs.readFileSync(path.join(root, 'popup.js'), 'utf8');
  for (const lib of manifest.content_scripts[0].js.slice(0, 6)) assert.ok(popup.includes(`'${lib}'`), `popup.js missing ${lib}`);
});
