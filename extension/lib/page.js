// Read a job posting out of the current page (career sites): JSON-LD JobPosting first, visible text as fallback. Plus a tiny status banner.
(function (g) {
  'use strict';
  const JP = (g.JP = g.JP || {});

  function findPosting(node) {
    if (Array.isArray(node)) { for (const n of node) { const r = findPosting(n); if (r) return r; } return null; }
    if (node && typeof node === 'object') {
      const t = node['@type'];
      if (t === 'JobPosting' || (Array.isArray(t) && t.includes('JobPosting'))) return node;
      return findPosting(node['@graph']);
    }
    return null;
  }

  const strip = (html) => {
    const div = g.document.createElement('div');
    div.innerHTML = String(html || '');
    return (div.textContent || '').replace(/\s+/g, ' ').trim();
  };

  function scrapeJob(doc) {
    doc = doc || g.document;
    for (const s of doc.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const p = findPosting(JSON.parse(s.textContent));
        if (p) {
          const loc = [].concat(p.jobLocation || []).map((l) => { const a = (l && l.address) || {}; return [a.addressLocality, a.addressRegion].filter(Boolean).join(', '); }).filter(Boolean).join(' | ');
          const org = p.hiringOrganization;
          return { title: strip(p.title), company: strip(org && org.name ? org.name : org), location: loc, description: strip(p.description).slice(0, 12000) };
        }
      } catch (e) { /* malformed JSON-LD: keep looking */ }
    }
    const h1 = doc.querySelector('h1');
    const main = doc.querySelector('main, [role="main"], #content, .content') || doc.body;
    return { title: (h1 ? h1.textContent : doc.title).replace(/\s+/g, ' ').trim(), company: '', location: '',
      description: ((main && main.textContent) || '').replace(/\s+/g, ' ').trim().slice(0, 12000) };
  }

  function banner(text, kind = 'info') {
    const doc = g.document;
    let el = doc.getElementById('jp-banner');
    if (!el) {
      el = doc.createElement('div');
      el.id = 'jp-banner';
      el.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:2147483647;max-width:360px;padding:10px 14px;border-radius:8px;font:13px/1.4 system-ui,sans-serif;color:#fff;box-shadow:0 4px 16px rgba(0,0,0,.3)';
      (doc.body || doc.documentElement).appendChild(el);
    }
    el.style.background = { info: '#2b5fd9', ok: '#1f8a4c', warn: '#b7791f', err: '#c0392b' }[kind] || '#2b5fd9';
    el.textContent = 'JobPilot: ' + text;
  }

  // Outline fields the filler could not answer so you can fill them yourself.
  function highlight(unanswered) {
    const d = JP.dom;
    for (const f of JP.form.collectFields(g.document)) {
      if (unanswered.some((u) => u.label === f.label)) f.el.style.outline = '3px solid #c0392b';
    }
  }

  JP.page = { scrapeJob, banner, highlight };
  if (typeof module !== 'undefined' && module.exports) module.exports = JP.page;
})(typeof globalThis !== 'undefined' ? globalThis : window);
