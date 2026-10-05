const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./helpers');

const PROFILE = { full_name: 'Jane Sample', email: 'jane@example.com', phone: '555-000-0000' };
const FAST = { stepDelay: [0, 0], successTimeout: 600 };

function ctx(answerFn) {
  return { profile: PROFILE, job: { title: 'DE', company: 'Acme' }, acceptConsent: true, resume: null,
    answer: answerFn || (async (r) => (/authorized/i.test(r.question) ? { answer: 'Yes', reason: 'config' } : { answer: null, reason: 'unknown' })) };
}

// Simulates a LinkedIn-style modal: contact -> questions -> review -> submit -> confirmation.
function wizard({ stuck = false } = {}) {
  const env = boot(`<body><div id="modal" role="dialog">
    <div id="step"><label for="em">Email address *</label><input id="em" required><button id="nx" aria-label="Continue to next step">Next</button></div></div></body>`);
  const { document } = env, modal = () => document.getElementById('modal');
  const step = (html) => { modal().innerHTML = `<div id="step">${html}</div>`; wire(); };
  function wire() {
    const on = (id, fn) => { const b = document.getElementById(id); if (b) b.addEventListener('click', fn); };
    on('nx', () => !stuck && step(`<label for="au">Are you legally authorized to work in the US? *</label>
      <select id="au" required><option value="">Select</option><option>Yes</option><option>No</option></select>
      <button id="rv" aria-label="Review your application">Review</button>`));
    on('rv', () => step(`<p>Review</p><button id="sb" aria-label="Submit application">Submit application</button>`));
    on('sb', () => { modal().remove(); document.body.insertAdjacentHTML('beforeend', '<h2>Your application was sent</h2>'); });
  }
  wire();
  return { ...env, modal };
}

test('stepLoop walks contact -> questions -> review -> submit and detects confirmation', async () => {
  const w = wizard();
  const r = await w.JP.flow.stepLoop(() => w.document.getElementById('modal'), ctx(), FAST);
  assert.equal(r.status, 'applied', JSON.stringify(r));
});

test('autoSubmit=false stops at the Submit button', async () => {
  const w = wizard();
  const r = await w.JP.flow.stepLoop(() => w.document.getElementById('modal'), ctx(), { ...FAST, autoSubmit: false });
  assert.equal(r.status, 'ready_to_submit');
  assert.ok(w.document.getElementById('sb'), 'Submit button must still be there, unclicked');
});

test('an unanswerable required question stops the application and reports it', async () => {
  const w = wizard();
  const r = await w.JP.flow.stepLoop(() => w.document.getElementById('modal'), ctx(async () => ({ answer: null, reason: 'sensitive' })), FAST);
  assert.equal(r.status, 'needs_review');
  assert.match(r.note, /authorized/i);
  assert.ok(w.document.getElementById('au'), 'must not have clicked past the unanswered step');
});

test('captcha -> stop, never try to solve', async () => {
  const w = wizard();
  w.document.body.insertAdjacentHTML('beforeend', '<iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe>');
  const r = await w.JP.flow.stepLoop(() => w.document.getElementById('modal'), ctx(), FAST);
  assert.equal(r.status, 'needs_review');
  assert.match(r.note, /captcha/i);
});

test('a Next button that does nothing is detected as stuck, not looped forever', async () => {
  const w = wizard({ stuck: true });
  const r = await w.JP.flow.stepLoop(() => w.document.getElementById('modal'), ctx(), { ...FAST, maxSteps: 10 });
  assert.equal(r.status, 'needs_review');
  assert.match(r.note, /stuck/i);
});
