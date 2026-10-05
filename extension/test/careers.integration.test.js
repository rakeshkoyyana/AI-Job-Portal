// Runs the real careers.js controller against a Greenhouse-style page with a fake chrome.* and fake backend.
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./helpers');

const PAGE = `<html><head><script type="application/ld+json">{"@type":"JobPosting","title":"Data Engineer","hiringOrganization":{"name":"Example Co"},
"description":"${'Build ETL pipelines in Python and SQL on Snowflake with Airflow. '.repeat(4)}"}</script></head><body><main><h1>Data Engineer</h1>
<form id="application_form" novalidate>
  <label for="first_name">First Name *</label><input id="first_name" required>
  <label for="last_name">Last Name *</label><input id="last_name" required>
  <label for="email">Email *</label><input id="email" type="email" required>
  <label for="phone">Phone</label><input id="phone">
  <label for="resume">Resume/CV *</label><input id="resume" type="file" required>
  <label for="q1">Are you legally authorized to work in the US? *</label>
  <select id="q1" required><option value="">Select</option><option>Yes</option><option>No</option></select>
  <button type="submit" id="go">Submit Application</button>
</form></main></body></html>`;

function fakeChrome(calls, { probability = 0.8, apply = true } = {}) {
  const store = {};
  const listeners = [];
  return {
    listeners,
    runtime: {
      lastError: null,
      onMessage: { addListener: (f) => listeners.push(f) },
      sendMessage(msg, cb) {
        const reply = (r) => cb && setTimeout(() => cb(r), 0);
        if (msg.type !== 'api') return reply({});
        calls.push({ path: msg.path, body: msg.body });
        if (msg.path === '/api/profile') return reply({ ok: true, data: { profile: { first_name: 'Jane', last_name: 'Sample', email: 'jane@example.com', phone: '555-0000' },
          extension: { daily_cap: { 'career-site': 25 }, auto_submit: true }, answers: {} } });
        if (msg.path.startsWith('/api/applications/status')) return reply({ ok: true, data: { status: null } });
        if (msg.path === '/api/job-match') return reply({ ok: true, data: { apply, reason: apply ? '' : 'match probability 10% is below your minimum 30%', probability, ats_after: 84, resume_id: 7,
          resume: { filename: 'Jane_Resume.docx', mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', b64: Buffer.from('PKfake').toString('base64') } } });
        if (msg.path === '/api/answer') return reply({ ok: true, data: /authorized/i.test(msg.body.question) ? { answer: 'Yes', reason: 'config' } : { answer: null, reason: 'unknown' } });
        if (msg.path === '/api/applications') return reply({ ok: true, data: { id: 1 } });
        reply({ ok: false, error: 'unexpected ' + msg.path });
      },
    },
    storage: { local: {
      async get(k) { return typeof k === 'string' ? { [k]: store[k] } : { ...store }; },
      async set(o) { Object.assign(store, o); },
    } },
  };
}

function load(calls, opts) {
  const env = boot(PAGE);
  globalThis.chrome = fakeChrome(calls, opts);
  const w = env.dom.window;
  globalThis.location = w.location;
  w.JP = globalThis.JP;
  for (const m of ['core', 'page']) { delete require.cache[require.resolve(`../lib/${m}.js`)]; require(`../lib/${m}.js`); }
  w.JP = globalThis.JP;
  // fast steps for the test
  globalThis.JP.flow.DEFAULTS.stepDelay = [0, 0];
  globalThis.JP.flow.DEFAULTS.successTimeout = 1500;
  return env;
}

test('careers controller: scrapes job, gets tailored resume, fills form, uploads, submits, records', async () => {
  const calls = [];
  const env = load(calls);
  const { document } = env;
  // the site shows a confirmation when the form is submitted
  document.getElementById('application_form').addEventListener('submit', (e) => { e.preventDefault(); document.body.insertAdjacentHTML('beforeend', '<h2>Thank you for applying</h2>'); });
  Object.defineProperty(document.getElementById('resume'), 'files', { get() { return this._f || []; }, set(v) { this._f = v; }, configurable: true });
  delete require.cache[require.resolve('../content/careers.js')];
  require('../content/careers.js');

  const deadline = Date.now() + 15000;
  while (Date.now() < deadline && !calls.some((c) => c.path === '/api/applications')) await new Promise((r) => setTimeout(r, 100));

  const v = (id) => document.getElementById(id).value;
  assert.equal(v('first_name'), 'Jane'); assert.equal(v('last_name'), 'Sample'); assert.equal(v('email'), 'jane@example.com'); assert.equal(v('q1'), 'Yes');
  assert.equal(document.getElementById('resume').files[0].name, 'Jane_Resume.docx', 'tailored resume must be attached');

  const match = calls.find((c) => c.path === '/api/job-match').body;
  assert.equal(match.title, 'Data Engineer'); assert.equal(match.company, 'Example Co'); assert.match(match.description, /Snowflake/);
  const rec = calls.find((c) => c.path === '/api/applications').body;
  assert.equal(rec.status, 'applied', 'note was: ' + rec.notes); assert.equal(rec.source, 'career-site'); assert.equal(rec.resume_id, 7);
  assert.ok(!calls.some((c) => c.path === '/api/answer' && /first name|email/i.test(c.body.question)), 'simple fields must not hit the backend');
});

test('careers controller: a poor match is skipped and nothing is filled or submitted', async () => {
  const calls = [];
  const env = load(calls, { apply: false, probability: 0.1 });
  const { document } = env;
  delete require.cache[require.resolve('../content/careers.js')];
  require('../content/careers.js');
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline && !calls.some((c) => c.path === '/api/applications')) await new Promise((r) => setTimeout(r, 100));
  const rec = calls.find((c) => c.path === '/api/applications').body;
  assert.equal(rec.status, 'skipped'); assert.match(rec.notes, /below your minimum/);
  assert.equal(document.getElementById('first_name').value, '');
});
