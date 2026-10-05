// The generic "walk through a multi-step application" loop used by LinkedIn's modal, Indeed's pages and career sites.
(function (g) {
  'use strict';
  const JP = (g.JP = g.JP || {});

  const DEFAULTS = {
    submit: /submit( your)? application|^submit$|^send application|^apply$/i,
    review: /review( your)? application|^review$/i,
    next: /^(next|continue|save (and|&) continue|continue to next step|go to next)/i,
    success: /application (was )?sent|thank you for applying|thanks for applying|application (has been )?(submitted|received)|successfully submitted|your application (was|has been) submitted/i,
    error: '[role="alert"], .artdeco-inline-feedback--error, [class*="error" i], [aria-invalid="true"]',
    maxSteps: 15, autoSubmit: true, stepDelay: [0.6, 1.4], successTimeout: 12000,
  };

  const signature = (root) => (root ? root.textContent.replace(/\s+/g, ' ').slice(0, 600) + root.querySelectorAll('input,select,textarea').length : '');

  /**
   * getRoot: () => element containing the current step (re-queried every step: sites re-render).
   * Returns { status: 'applied' | 'ready_to_submit' | 'needs_review' | 'failed', note, unanswered }
   */
  async function stepLoop(getRoot, ctx, options = {}) {
    const o = { ...DEFAULTS, ...options }, d = JP.dom, f = JP.form;
    let stuck = 0, lastSig = '';
    const bodyText = () => (g.document.body ? g.document.body.innerText || g.document.body.textContent : '');
    for (let step = 0; step < o.maxSteps; step++) {
      await d.sleep(d.rand(o.stepDelay[0], o.stepDelay[1]) * 1000);
      const root = getRoot();
      if (!root) return o.success.test(bodyText()) ? { status: 'applied', note: 'submitted' } : { status: 'failed', note: 'application window disappeared' };
      if (d.hasCaptcha(g.document)) return { status: 'needs_review', note: 'captcha / security check - finish manually', unanswered: [] };

      const filled = await f.fillForm(root, ctx);
      if (filled.unanswered.length) {
        return { status: 'needs_review', note: 'needs your answer: ' + filled.unanswered.map((u) => `${u.label} (${u.reason})`).join('; ').slice(0, 400), unanswered: filled.unanswered };
      }

      const submit = d.findButton(root, o.submit);
      if (submit) {
        if (!o.autoSubmit) return { status: 'ready_to_submit', note: 'filled; waiting for you to press Submit' };
        d.click(submit);
        const ok = await d.waitFor(() => o.success.test(bodyText()), o.successTimeout, 400);
        if (ok) return { status: 'applied', note: 'submitted' };
        const err = g.document.querySelector(o.error);
        return { status: 'needs_review', note: 'clicked Submit but no confirmation' + (err ? ': ' + d.clean(err.textContent).slice(0, 120) : ''), unanswered: [] };
      }
      const nxt = d.findButton(root, o.review) || d.findButton(root, o.next);
      if (!nxt) return { status: 'needs_review', note: 'no Next/Submit button found on this step', unanswered: [] };

      const before = signature(root);
      d.click(nxt);
      await d.sleep(500);
      const after = signature(getRoot());
      stuck = after === before && after === lastSig ? stuck + 1 : 0;
      lastSig = after;
      if (stuck >= 2) {
        const err = g.document.querySelector(o.error);
        return { status: 'needs_review', note: 'stuck on a step' + (err ? ': ' + d.clean(err.textContent).slice(0, 120) : ''), unanswered: [] };
      }
    }
    return { status: 'needs_review', note: 'too many steps', unanswered: [] };
  }

  JP.flow = { stepLoop, DEFAULTS };
  if (typeof module !== 'undefined' && module.exports) module.exports = JP.flow;
})(typeof globalThis !== 'undefined' ? globalThis : window);
