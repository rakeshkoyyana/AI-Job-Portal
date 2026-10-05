// Indeed autopilot. Two cooperating roles:
//   * results page (www.indeed.com/jobs): walks the cards, scores each job, opens the Indeed Apply flow
//   * apply flow  (smartapply.indeed.com): fills each step and submits, then reports back to the results tab
// Jobs that apply on the company's own site are logged as needs_review with their link (use the career-site autofill there).
// NOTE: automating Indeed is against Indeed's terms; you accepted that risk. Selectors are best-effort (SEL).
(function () {
  'use strict';
  const JP = window.JP, D = JP.dom, PLATFORM = 'indeed';
  const isApplyFlow = location.hostname === 'smartapply.indeed.com';
  if (!isApplyFlow && window !== window.top) return;           // ads/other iframes on indeed.com: do nothing
  if (window.__jpIndeed) return;
  window.__jpIndeed = true;
  let stopFlag = false, running = false;

  const SEL = {
    cards: 'div.job_seen_beacon, li div.cardOutline',
    link: 'a.jcs-JobTitle, h2 a',
    pane: '#jobsearch-ViewjobPaneWrapper, .jobsearch-RightPane, #viewJobSSRRoot',
    title: ['.jobsearch-JobInfoHeader-title', 'h1'],
    company: ['[data-testid="inlineHeader-companyName"]', '[data-company-name="true"]'],
    location: ['[data-testid="inlineHeader-companyLocation"]', '[data-testid="job-location"]'],
    description: ['#jobDescriptionText'],
    applyBtn: '#indeedApplyButton, button[id*="indeedApply" i]',
    nextPage: 'a[data-testid="pagination-page-next"], a[aria-label="Next Page"]',
    flowRoot: 'main, #ia-container, form',
  };
  const text = (sels, root = document) => { for (const s of [].concat(sels)) { const e = root.querySelector(s); if (e && D.clean(e.textContent)) return D.clean(e.textContent); } return ''; };
  const PENDING = 'jp_pending_indeed';
  const getPending = async () => (await chrome.storage.local.get(PENDING))[PENDING] || null;

  // ------------------------------------------------------------------ apply flow (smartapply.indeed.com)
  async function runApplyFlow() {
    const pending = await getPending();
    if (!pending) return;                                                        // you opened it by hand: use the popup's "Fill this page"
    const prof = await JP.api.profile();
    if (!prof.ok) return;
    const pd = prof.data;
    JP.page.banner(`Applying: ${pending.job.title}`);
    const res = await JP.flow.stepLoop(() => document.querySelector(SEL.flowRoot), JP.makeCtx(pd, pending.job, pending.match), {
      autoSubmit: (pd.extension || {}).auto_submit !== false, submit: /submit your application|^submit/i, next: /^(continue|next)/i, review: /^review/i,
      success: /your application has been submitted|application submitted|thanks for applying/i,
    });
    await chrome.storage.local.remove(PENDING);
    chrome.runtime.sendMessage({ type: 'jp-forward', tabId: pending.tabId, payload: { type: 'indeed-done', result: res } });
    if (res.status === 'applied') chrome.runtime.sendMessage({ type: 'jp-close-tab' });
  }

  // ------------------------------------------------------------------ results page
  const waitDone = () => new Promise((resolve) => {
    const t = setTimeout(() => resolve({ status: 'needs_review', note: 'apply flow timed out' }), 240000);
    const h = (m) => { if (m.type === 'indeed-done') { clearTimeout(t); chrome.runtime.onMessage.removeListener(h); resolve(m.result); } };
    chrome.runtime.onMessage.addListener(h);
  });

  async function runResults() {
    if (running) return;
    running = true; stopFlag = false;
    await JP.state.setRunning(PLATFORM, true);
    JP.page.banner('Indeed autopilot running (use the popup to stop)');
    try {
      const prof = await JP.api.profile();
      if (!prof.ok) { JP.page.banner(prof.error || 'cannot reach JobPilot API', 'err'); return; }
      const pd = prof.data, cap = JP.capFor(pd, PLATFORM), seen = new Set();
      const me = await new Promise((r) => chrome.runtime.sendMessage({ type: 'jp-whoami' }, r));
      for (let page = 0; page < 30 && !stopFlag; page++) {
        for (const card of Array.from(document.querySelectorAll(SEL.cards))) {
          if (stopFlag) break;
          if ((await JP.state.count(PLATFORM)) >= cap) { await JP.state.push({ platform: PLATFORM, status: 'info', note: `daily cap of ${cap} reached` }); JP.page.banner(`daily cap of ${cap} reached`, 'ok'); stopFlag = true; break; }
          const link = card.querySelector(SEL.link);
          if (!link) continue;
          const jk = link.getAttribute('data-jk') || new URL(link.href, location.href).searchParams.get('jk');
          if (!jk || seen.has(jk)) continue;
          seen.add(jk);
          const st = await JP.api.status(PLATFORM, jk);
          if (st.ok && st.data.status) continue;

          D.click(link);
          await D.waitFor(() => text(SEL.description).length > 100, 8000);
          const job = { key: jk, url: `https://www.indeed.com/viewjob?jk=${jk}`, title: text(SEL.title), company: text(SEL.company), location: text(SEL.location), description: text(SEL.description) };
          const btn = document.querySelector(SEL.applyBtn);
          if (!btn) { await JP.record(PLATFORM, job, 'needs_review', 'applies on the company site - open it and use the career-site autofill: ' + job.url); continue; }
          if (job.description.length < 150) { await JP.record(PLATFORM, job, 'skipped', 'job description did not load'); continue; }

          const mr = await JP.api.jobMatch({ platform: PLATFORM, job_key: jk, url: job.url, title: job.title, company: job.company, location: job.location, description: job.description });
          if (!mr.ok) { await JP.record(PLATFORM, job, 'failed', 'backend: ' + mr.error); JP.page.banner(mr.error, 'err'); stopFlag = true; break; }
          if (!mr.data.apply) { await JP.record(PLATFORM, job, 'skipped', mr.data.reason, { probability: mr.data.probability }); continue; }

          await chrome.storage.local.set({ [PENDING]: { tabId: me.tabId, job, match: mr.data } });
          JP.page.banner(`Applying: ${job.title} @ ${job.company} (match ${Math.round(mr.data.probability * 100)}%)`);
          const done = waitDone();
          D.click(btn);
          const res = await done;
          await chrome.storage.local.remove(PENDING);
          const status = res.status === 'ready_to_submit' ? 'needs_review' : res.status;
          await JP.record(PLATFORM, job, status, res.note, { probability: mr.data.probability, resume_id: mr.data.resume_id });
          if (res.status === 'ready_to_submit' || /captcha|security/i.test(res.note || '')) { JP.page.banner(res.note, 'warn'); stopFlag = true; break; }
          await JP.pace(pd);
        }
        const nxt = !stopFlag && document.querySelector(SEL.nextPage);
        if (!nxt) break;
        D.click(nxt);
        await D.sleep(3500);
      }
      if (!stopFlag) JP.page.banner('finished this search', 'ok');
    } finally {
      running = false;
      await JP.state.setRunning(PLATFORM, false);
    }
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === 'jp-start' && msg.platform === PLATFORM && !isApplyFlow) runResults();
    if (msg.type === 'jp-stop') stopFlag = true;
  });
  if (isApplyFlow) runApplyFlow();
  else JP.state.get().then((s) => { if (s.running[PLATFORM]) runResults(); });
})();
