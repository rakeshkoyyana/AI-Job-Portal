const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./helpers');

const PROFILE = { full_name: 'Jane Sample', first_name: 'Jane', last_name: 'Sample', email: 'jane@example.com', phone: '555-000-0000',
  linkedin: 'https://linkedin.com/in/jane', city: 'Dallas', state: 'TX', zip: '75001', country: 'United States', years_experience: 5.4,
  current_company: 'Example Corp', notice_period: '2 weeks' };

test('mapper maps profile fields and refuses sensitive / ambiguous ones', () => {
  const { JP } = boot('<body></body>');
  const m = JP.mapper;
  assert.equal(m.mapField('First name *', PROFILE), 'Jane');
  assert.equal(m.mapField('Last Name', PROFILE), 'Sample');
  assert.equal(m.mapField('Email address', PROFILE), 'jane@example.com');
  assert.equal(m.mapField('Mobile phone number', PROFILE), '555-000-0000');
  assert.equal(m.mapField('LinkedIn Profile', PROFILE), 'https://linkedin.com/in/jane');
  assert.equal(m.mapField('City', PROFILE), 'Dallas');
  assert.equal(m.mapField('How many years of work experience do you have?', PROFILE), '5');
  assert.equal(m.mapField('Current company', PROFILE), 'Example Corp');
  // skill-specific experience goes to the resume-aware backend, not the generic number
  assert.equal(m.mapField('How many years of experience do you have with Kubernetes?', PROFILE), null);
  assert.equal(m.mapField('Company name', PROFILE), null);
  assert.equal(m.mapField('What is your gender?', PROFILE), null);
  assert.equal(m.mapField('Desired salary', PROFILE), null);
  assert.equal(m.mapField('Phone country code', PROFILE), null);
});

test('pickOption: exact, prefix, containment', () => {
  const { JP } = boot('<body></body>');
  const opts = [{ text: 'Yes, I am authorized' }, { text: 'No' }];
  assert.equal(JP.mapper.pickOption('Yes', opts).text, 'Yes, I am authorized');
  assert.equal(JP.mapper.pickOption('no', opts).text, 'No');
  assert.equal(JP.mapper.pickOption('Maybe', opts), null);
});

test('consent checkboxes: only privacy/certify style, never legal waivers or marketing', () => {
  const { JP } = boot('<body></body>');
  const ok = JP.mapper.isAcceptableConsent;
  assert.ok(ok('I agree to the privacy policy'));
  assert.ok(ok('I certify that the information is true and complete'));
  assert.ok(!ok('I agree to binding arbitration'));
  assert.ok(!ok('Send me marketing emails and accept the terms'));
  assert.ok(!ok('I consent to a background check'));
});

const FORM = `<body><form>
  <label for="fn">First name *</label><input id="fn" required>
  <label for="ln">Last name *</label><input id="ln" required>
  <label for="em">Email *</label><input id="em" type="email" required>
  <label for="ph">Phone</label><input id="ph" type="tel">
  <label for="co">Current company</label><input id="co" value="Already filled">
  <label for="exp">How many years of experience do you have with Python? *</label><input id="exp" type="number" required>
  <label for="auth">Are you legally authorized to work in the US? *</label>
  <select id="auth" required><option value="">Select</option><option value="y">Yes</option><option value="n">No</option></select>
  <fieldset><legend>Will you now or in the future require sponsorship? *</legend>
    <label><input type="radio" name="sp" value="y" required> Yes</label><label><input type="radio" name="sp" value="n"> No</label></fieldset>
  <label for="gen">What is your gender? *</label><input id="gen" required>
  <label for="res">Resume *</label><input id="res" type="file" required>
  <label><input type="checkbox" id="priv" required> I agree to the privacy policy *</label>
  <label><input type="checkbox" id="arb" required> I agree to binding arbitration *</label>
  <label><input type="checkbox" id="fol"> Follow Acme to stay up to date with their page</label>
  <input type="hidden" name="csrf" value="x"><button type="submit">Submit application</button>
</form></body>`;

test('fillForm fills profile, backend answers, radios/selects, uploads resume, flags what it cannot answer', async () => {
  const { document, JP } = boot(FORM);
  const asked = [];
  const ctx = {
    profile: PROFILE, job: { title: 'DE', company: 'Acme' }, acceptConsent: true,
    resume: { b64: Buffer.from('PKfake').toString('base64'), filename: 'Jane_Resume.docx', mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' },
    answer: async (req) => {
      asked.push(req.question);
      if (/python/i.test(req.question)) return { answer: '5', reason: 'llm' };
      if (/authorized/i.test(req.question)) return { answer: 'Yes', reason: 'config' };
      if (/sponsorship/i.test(req.question)) return { answer: 'No', reason: 'config' };
      return { answer: null, reason: 'sensitive' };
    },
  };
  const r = await JP.form.fillForm(document, ctx);
  const v = (id) => document.getElementById(id).value;
  assert.equal(v('fn'), 'Jane'); assert.equal(v('ln'), 'Sample'); assert.equal(v('em'), 'jane@example.com'); assert.equal(v('ph'), '555-000-0000');
  assert.equal(v('co'), 'Already filled');                                  // existing values are not overwritten
  assert.equal(v('exp'), '5');                                              // skill-specific -> backend
  assert.equal(v('auth'), 'y');                                             // select
  assert.equal(document.querySelector('input[name=sp][value=n]').checked, true);   // radio
  assert.ok(document.getElementById('priv').checked);                       // acceptable consent
  assert.ok(!document.getElementById('arb').checked);                       // legal waiver left alone
  assert.ok(!document.getElementById('fol').checked);                       // never follows companies
  assert.equal(document.getElementById('res').files.length, 1);
  assert.equal(document.getElementById('res').files[0].name, 'Jane_Resume.docx');
  assert.ok(r.uploaded);
  const labels = r.unanswered.map((u) => u.label);
  assert.ok(labels.some((l) => /gender/i.test(l)), 'sensitive question must be flagged, not guessed');
  assert.ok(labels.some((l) => /arbitration/i.test(l)), 'unticked required legal checkbox must be flagged');
  assert.ok(!asked.some((q) => /first name|email/i.test(q)), 'simple profile fields never hit the backend');
});

test('findButton / captcha detection', () => {
  const { document, JP } = boot('<body><div role="dialog"><button aria-label="Continue to next step">Next</button><button aria-label="Review your application">Review</button><button disabled>Submit application</button></div></body>');
  const d = JP.dom;
  assert.ok(d.findButton(document, /next|continue/i));
  assert.ok(d.findButton(document, /review/i));
  assert.equal(d.findButton(document, /submit application/i), null);        // disabled buttons are ignored
  assert.equal(d.hasCaptcha(document), false);
  const b = boot('<body><iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe></body>');
  assert.equal(b.JP.dom.hasCaptcha(b.document), true);
});
