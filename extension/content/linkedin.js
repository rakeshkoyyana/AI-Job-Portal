// LinkedIn Easy Apply autopilot. Runs in YOUR logged-in browser on linkedin.com/jobs/search (use the "Easy Apply" filter).
// NOTE: automating LinkedIn is against LinkedIn's User Agreement; you accepted that risk. Selectors are best-effort and
// kept in one place (SEL) because LinkedIn changes its markup often.
(function () {
  'use strict';
  const JP = window.JP, D = JP.dom, PLATFORM = 'linkedin';
  if (window.__jpLinkedIn) return;
  window.__jpLinkedIn = true;
  let stopFlag = false, running = false;

  const SEL = {
    cards: 'li[data-occludable-job-id], div.job-card-container[data-job-id], li.jobs-search-results__list-item',
    title: ['.job-details-jobs-unified-top-card__job-title h1', '.jobs-unified-top-card__job-title', 'h1'],
    company: ['.job-details-jobs-unified-top-card__company-name', '.jobs-unified-top-card__company-name'],
    location: ['.job-details-jobs-unified-top-card__primary-description-container', '.jobs-unified-top-card__bullet'],
    description: ['#job-details', '.jobs-description__content', '.jobs-box__html-content'],
    modal: '.jobs-easy-apply-modal, [role="dialog"][aria-labelledby*="easy-apply" i], div.artdeco-modal',
    list: '.jobs-search-results-list, .scaffold-layout__list',
    nextPage: ['button[aria-label="View next page"]', 'li.artdeco-pagination__indicator--number.active + li button'],
  };
  const text = (sels) => { for (const s of [].concat(sels)) { const e = document.querySelector(s); if (e && D.clean(e.textContent)) return D.clean(e.textContent); } return ''; };

  const jobIdOf = (card) => card.getAttribute('data-occludable-job-id') || card.getAttribute('data-job-id')
    || ((card.querySelector('a[href*="/jobs/view/"]') || {}).href || '').match(/view\/(\d+)/)?.[1] || '';

  function readDetail(id) {
    return { key: id, url: `https://www.linkedin.com/jobs/view/${id}`, title: text(SEL.title), company: text(SEL.company),
      location: text(SEL.location), description: text(SEL.description) };
  }

  async function scrollList() {
    const l = document.querySelector(SEL.list);
    if (!l) return;
    for (let i = 1; i <= 4; i++) { l.scrollTo({ top: (l.scrollHeight * i) / 4 }); await D.sleep(500); }
  }

  async function nextPage() {
    for (const s of SEL.nextPage) { const b = document.querySelector(s); if (b && !b.disabled) { D.click(b); await D.sleep(3000); return true; } }
    return false;
  }

  async function dismiss() {
    const x = document.querySelector('button[aria-label="Dismiss"], button.artdeco-modal__dismiss');
    if (x) D.click(x);
    await D.sleep(700);
    const discard = D.findButton(document, /^discard/i);
    if (discard) { D.click(discard); await D.sleep(500); }
  }

  async function applyEasy(pd, job, match, autoSubmit) {
    const btn = D.findButton(document, /easy apply/i);
    if (!btn) return { status: 'failed', note: 'Easy Apply button missing' };
    D.click(btn);
    if (!(await D.waitFor(() => document.querySelector(SEL.modal), 8000))) return { status: 'failed', note: 'Easy Apply window did not open' };
    const res = await JP.flow.stepLoop(() => document.querySelector(SEL.modal), JP.makeCtx(pd, job, match), {
      autoSubmit, submit: /submit application/i, review: /review( your)? application|^review/i, next: /^next|continue to next step/i,
    });
    if (res.status === 'applied') { const done = D.findButton(document, /^(done|dismiss)$/i); if (done) D.click(done); else await dismiss(); }
    else if (res.status !== 'ready_to_submit') await dismiss();
    return res;
  }

  async function run() {
    if (running) return;
    running = true; stopFlag = false;
    await JP.state.setRunning(PLATFORM, true);
    JP.page.banner('LinkedIn autopilot running (use the popup to stop)');
    try {
      const prof = await JP.api.profile();
      if (!prof.ok) { JP.page.banner(prof.error || 'cannot reach JobPilot API', 'err'); return; }
      const pd = prof.data, cap = JP.capFor(pd, PLATFORM), autoSubmit = (pd.extension || {}).auto_submit !== false, seen = new Set();
      for (let page = 0; page < 40 && !stopFlag; page++) {
        await scrollList();
        for (const card of Array.from(document.querySelectorAll(SEL.cards))) {
          if (stopFlag) break;
          if ((await JP.state.count(PLATFORM)) >= cap) { await JP.state.push({ platform: PLATFORM, status: 'info', note: `daily cap of ${cap} reached` }); JP.page.banner(`daily cap of ${cap} reached`, 'ok'); stopFlag = true; break; }
          const id = jobIdOf(card);
          if (!id || seen.has(id)) continue;
          seen.add(id);
          const st = await JP.api.status(PLATFORM, id);
          if (st.ok && st.data.status) continue;                                        // already handled in an earlier run

          D.click(card.querySelector('a') || card);
          await D.waitFor(() => text(SEL.title) && text(SEL.description).length > 100, 8000);
          const job = readDetail(id);
          if (!D.findButton(document, /easy apply/i)) { await JP.record(PLATFORM, job, 'skipped', 'not an Easy Apply job'); continue; }
          if (job.description.length < 150) { await JP.record(PLATFORM, job, 'skipped', 'job description did not load'); continue; }

          const mr = await JP.api.jobMatch({ platform: PLATFORM, job_key: id, url: job.url, title: job.title, company: job.company, location: job.location, description: job.description });
          if (!mr.ok) { await JP.record(PLATFORM, job, 'failed', 'backend: ' + mr.error); JP.page.banner(mr.error, 'err'); stopFlag = true; break; }
          if (!mr.data.apply) { await JP.record(PLATFORM, job, 'skipped', mr.data.reason, { probability: mr.data.probability }); continue; }

          JP.page.banner(`Applying: ${job.title} @ ${job.company} (match ${Math.round(mr.data.probability * 100)}%)`);
          const res = await applyEasy(pd, job, mr.data, autoSubmit);
          const status = res.status === 'ready_to_submit' ? 'needs_review' : res.status;
          await JP.record(PLATFORM, job, status, res.note, { probability: mr.data.probability, resume_id: mr.data.resume_id });
          if (res.status === 'ready_to_submit' || /captcha|security/i.test(res.note || '')) { JP.page.banner(res.note, 'warn'); stopFlag = true; break; }   // hand over to you
          await JP.pace(pd);
        }
        if (!stopFlag && !(await nextPage())) break;
      }
      if (!stopFlag) JP.page.banner('finished this search', 'ok');
    } finally {
      running = false;
      await JP.state.setRunning(PLATFORM, false);
    }
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === 'jp-start' && msg.platform === PLATFORM) run();
    if (msg.type === 'jp-stop') { stopFlag = true; JP.page.banner('stopping after the current job...', 'warn'); }
  });
  JP.state.get().then((s) => { if (s.running[PLATFORM]) run(); });      // resume after a page reload
})();
