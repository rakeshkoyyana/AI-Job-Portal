// Generic form filler: collects fields, answers them (profile -> backend), fills them, reports what it could not answer.
(function (g) {
  'use strict';
  const JP = (g.JP = g.JP || {});
  const D = () => JP.dom;
  const M = () => JP.mapper;

  const SKIP_TYPES = ['hidden', 'submit', 'button', 'image', 'reset', 'search'];

  function isRequired(el, label) {
    return el.required || el.getAttribute('aria-required') === 'true' || /\*\s*$/.test(label || '') || /\brequired\b/i.test(label || '');
  }

  function collectFields(root) {
    const d = D();
    const fields = [], seenRadio = new Set();
    root.querySelectorAll('input, textarea, select').forEach((el) => {
      const type = (el.type || el.tagName).toLowerCase();
      if (SKIP_TYPES.includes(type)) return;
      if (type !== 'file' && !d.isVisible(el)) return;
      if (type === 'radio') {
        const key = el.name || el.id;
        if (seenRadio.has(key)) return;
        seenRadio.add(key);
        const group = Array.from(root.querySelectorAll(`input[type="radio"]`)).filter((r) => (r.name || r.id) === key);
        const label = d.labelFor(group[0].closest('fieldset, [role="radiogroup"], [role="group"]') ? group[0] : group[0]);
        const q = group[0].closest('fieldset, [role="radiogroup"], [role="group"]');
        const legend = q && (q.querySelector('legend') || q.querySelector('[class*="label"], [class*="title"], span'));
        const text = legend ? d.clean(legend.textContent) : label;
        const options = group.map((r) => ({ el: r, text: d.labelFor(r) }));
        fields.push({ kind: 'radio', el: group[0], label: text, options, required: group.some((r) => r.required) || isRequired(group[0], text), filled: group.some((r) => r.checked) });
        return;
      }
      const label = d.labelFor(el);
      const base = { el, label, required: isRequired(el, label) };
      if (type === 'file') fields.push({ ...base, kind: 'file', filled: !!(el.files && el.files.length) });
      else if (type === 'checkbox') fields.push({ ...base, kind: 'checkbox', filled: el.checked });
      else if (el.tagName === 'SELECT') fields.push({ ...base, kind: 'select', options: d.optionsOf(el), filled: !!el.value && !/^(select|choose|please)/i.test(d.clean(el.selectedOptions[0]?.textContent || '')) });
      else if (el.tagName === 'TEXTAREA') fields.push({ ...base, kind: 'textarea', filled: !!el.value.trim() });
      else fields.push({ ...base, kind: 'text', filled: !!el.value.trim() });
    });
    return fields;
  }

  /**
   * ctx = { profile, resume:{b64,filename,mime}|null, cover:{...}|null, job:{title,company,description},
   *         answer: async (req) => ({answer, reason}),  acceptConsent: bool }
   * Returns { filled, unanswered:[{label, required, reason}], uploaded }
   */
  async function fillForm(root, ctx) {
    const d = D(), m = M();
    const out = { filled: 0, unanswered: [], uploaded: false };
    for (const f of collectFields(root)) {
      try {
        if (f.kind === 'file') {
          const isCover = /cover/i.test(f.label || '');
          const file = isCover ? ctx.cover : ctx.resume;
          if (file && !f.filled) {
            out.uploaded = d.attachFile(f.el, d.b64ToFile(file.b64, file.filename, file.mime)) || out.uploaded;
            out.filled++;
          } else if (!file && f.required && !f.filled) out.unanswered.push({ label: f.label || 'file upload', required: true, reason: 'no file available' });
          continue;
        }
        if (f.kind === 'checkbox') {
          if (f.filled) continue;
          if (/follow/i.test(f.label) && /company|page/i.test(f.label)) continue;          // never follow companies
          if (ctx.acceptConsent && m.isAcceptableConsent(f.label)) { d.setChecked(f.el, true); out.filled++; }
          else if (f.required) out.unanswered.push({ label: f.label, required: true, reason: 'needs your consent' });
          continue;
        }
        if (f.filled || !f.label) continue;

        const options = f.kind === 'radio' ? f.options.map((o) => o.text) : f.kind === 'select' ? f.options.map((o) => o.text) : undefined;
        let answer = f.kind === 'text' || f.kind === 'textarea' ? m.mapField(f.label, ctx.profile) : null;
        if (!answer && !(f.kind === 'text' && !f.required)) {
          const r = await ctx.answer({ question: f.label, field_type: f.kind, options, job: ctx.job });
          answer = r && r.answer;
          if (!answer) { if (f.required) out.unanswered.push({ label: f.label, required: true, reason: (r && r.reason) || 'unknown' }); continue; }
        }
        if (!answer) continue;

        if (f.kind === 'select') { if (d.chooseSelect(f.el, answer)) out.filled++; else if (f.required) out.unanswered.push({ label: f.label, required: true, reason: 'no matching option' }); }
        else if (f.kind === 'radio') {
          const hit = m.pickOption(answer, f.options);
          if (hit) { hit.el.click(); out.filled++; } else if (f.required) out.unanswered.push({ label: f.label, required: true, reason: 'no matching option' });
        } else { d.setValue(f.el, answer); out.filled++; }
      } catch (e) {
        if (f.required) out.unanswered.push({ label: f.label || '(field)', required: true, reason: 'error: ' + e.message });
      }
    }
    return out;
  }

  const api = { collectFields, fillForm, isRequired };
  JP.form = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : window);
