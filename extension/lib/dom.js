// DOM helpers shared by every site controller.
(function (g) {
  'use strict';
  const JP = (g.JP = g.JP || {});
  const M = () => JP.mapper;

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const rand = (a, b) => a + Math.random() * (b - a);
  const pace = (range = [4, 9]) => sleep(rand(range[0], range[1]) * 1000);   // rate limiting between jobs

  async function waitFor(fn, timeout = 8000, interval = 250) {
    const end = Date.now() + timeout;
    while (Date.now() < end) {
      const v = fn();
      if (v) return v;
      await sleep(interval);
    }
    return null;
  }

  function isVisible(el) {
    if (!el || el.hidden) return false;
    const cs = (el.ownerDocument.defaultView || window).getComputedStyle(el);
    return cs.display !== 'none' && cs.visibility !== 'hidden' && !el.closest('[hidden],[aria-hidden="true"]');
  }

  const clean = (s) => String(s || '').replace(/\s+/g, ' ').replace(/\*/g, '').trim();

  // Best human-readable question text for a form control.
  function labelFor(el) {
    const doc = el.ownerDocument;
    const by = el.getAttribute('aria-labelledby');
    if (by) {
      const t = by.split(/\s+/).map((id) => doc.getElementById(id)?.textContent || '').join(' ');
      if (clean(t)) return clean(t);
    }
    if (el.getAttribute('aria-label')) return clean(el.getAttribute('aria-label'));
    if (el.id) {
      const id = g.CSS && g.CSS.escape ? g.CSS.escape(el.id) : el.id.replace(/["\\]/g, '\\$&');
      const l = doc.querySelector(`label[for="${id}"]`);
      if (l && clean(l.textContent)) return clean(l.textContent);
    }
    const wrap = el.closest('label');
    if (wrap && clean(wrap.textContent)) return clean(wrap.textContent);
    const group = el.closest('fieldset, [role="group"], [role="radiogroup"]');
    const legend = group && (group.querySelector('legend') || group.querySelector('[class*="label"], [class*="title"]'));
    if (legend && clean(legend.textContent)) return clean(legend.textContent);
    const block = el.closest('[class*="form-element"], [class*="question"], [class*="field"], .form-group, div');
    const bl = block && block.querySelector('label, [class*="label"]');
    if (bl && clean(bl.textContent)) return clean(bl.textContent);
    return clean(el.getAttribute('placeholder') || el.name || '');
  }

  function optionsOf(el) {
    return Array.from(el.options || []).filter((o) => o.value !== '' || o.textContent.trim()).map((o) => ({ text: clean(o.textContent), value: o.value }))
      .filter((o) => !/^(select|choose|please select|--)/i.test(o.text));
  }

  // Frameworks (React etc.) track the value themselves: use the native setter and fire real events.
  function setValue(el, value) {
    const proto = el instanceof g.HTMLTextAreaElement ? g.HTMLTextAreaElement.prototype
      : el instanceof g.HTMLSelectElement ? g.HTMLSelectElement.prototype : g.HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    el.focus && el.focus();
    desc && desc.set ? desc.set.call(el, value) : (el.value = value);
    el.dispatchEvent(new g.Event('input', { bubbles: true }));
    el.dispatchEvent(new g.Event('change', { bubbles: true }));
    el.dispatchEvent(new g.Event('blur', { bubbles: true }));
  }

  function chooseSelect(el, answer) {
    const opts = optionsOf(el);
    const hit = M().pickOption(answer, opts);
    if (!hit) return false;
    setValue(el, hit.value);
    return true;
  }

  function setChecked(el, on) {
    if (el.checked === on) return;
    el.click();
    if (el.checked !== on) { el.checked = on; el.dispatchEvent(new g.Event('change', { bubbles: true })); }
  }

  function b64ToFile(b64, filename, mime) {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new g.File([bytes], filename, { type: mime });
  }

  function attachFile(input, file) {
    const dt = new g.DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    input.dispatchEvent(new g.Event('input', { bubbles: true }));
    input.dispatchEvent(new g.Event('change', { bubbles: true }));
    return input.files && input.files.length === 1;
  }

  function buttons(root) {
    return Array.from(root.querySelectorAll('button, input[type="submit"], input[type="button"], a[role="button"], [role="button"]')).filter(isVisible);
  }

  // Find a visible, enabled button by its text / aria-label / value.
  function findButton(root, re, { not } = {}) {
    return buttons(root).find((b) => {
      const t = clean(b.textContent || b.value || '') + ' ' + (b.getAttribute('aria-label') || '');
      return re.test(t) && !(not && not.test(t)) && !b.disabled && b.getAttribute('aria-disabled') !== 'true';
    }) || null;
  }

  function click(el) {
    el.scrollIntoView && el.scrollIntoView({ block: 'center' });
    el.click();
  }

  // Captcha / bot-check detection: we never try to solve these, we stop and hand the page to you.
  function hasCaptcha(root) {
    root = root || g.document;
    if (root.querySelector('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="captcha"], .g-recaptcha, .h-captcha, [data-sitekey]')) return true;
    const t = (root.body ? root.body.innerText : root.textContent) || '';
    return /verify you are (a )?human|security check|unusual activity|are you a robot|complete the captcha/i.test(t);
  }

  const api = { sleep, rand, pace, waitFor, isVisible, clean, labelFor, optionsOf, setValue, chooseSelect, setChecked,
    b64ToFile, attachFile, buttons, findButton, click, hasCaptcha };
  JP.dom = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : window);
