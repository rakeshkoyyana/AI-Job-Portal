// Career-site autofill (Greenhouse, Lever, Ashby, Workday, iCIMS, SmartRecruiters and any page you trigger from the popup).
// Reads the posting, picks your best resume, rewrites it for the job, fills every field and (optionally) submits.
(function () {
  'use strict';
  const JP = window.JP, D = JP.dom, PLATFORM = 'career-site';
  if (window.__jpCareers) return;
  window.__jpCareers = true;
  let busy = false;

  const looksLikeApplicationForm = () => {
    const fields = JP.form.collectFields(document);
    return fields.filter((f) => f.kind !== 'checkbox' && f.kind !== 'radio').length >= 4 && fields.some((f) => f.kind === 'file' || /e-?mail/i.test(f.label));
  };

  async function run({ submit }) {
    if (busy) return;
    busy = true;
    try {
      const prof = await JP.api.profile();
      if (!prof.ok) { JP.page.banner(prof.error || 'cannot reach JobPilot API', 'err'); return; }
      const pd = prof.data, cap = JP.capFor(pd, PLATFORM);
      if ((await JP.state.count(PLATFORM)) >= cap) { JP.page.banner(`daily cap of ${cap} career-site applications reached`, 'warn'); return; }
      const job = { ...JP.page.scrapeJob(), url: location.href.split('#')[0], key: location.origin + location.pathname };
      if (!job.title) job.title = document.title;
      if ((await JP.api.status(PLATFORM, job.key)).data?.status === 'applied') { JP.page.banner('already applied to this job', 'ok'); return; }
      if (job.description.length < 150) JP.page.banner('could not read the job description; using your default resume', 'warn');

      JP.page.banner('tailoring your resume for this job...');
      const mr = await JP.api.jobMatch({ platform: PLATFORM, job_key: job.key, url: job.url, title: job.title, company: job.company, location: job.location, description: job.description || job.title });
      if (!mr.ok) { JP.page.banner(mr.error, 'err'); return; }
      const m = mr.data;
      if (!m.apply) { await JP.record(PLATFORM, job, 'skipped', m.reason, { probability: m.probability }); JP.page.banner('skipped: ' + m.reason, 'warn'); return; }

      JP.page.banner(`filling application (match ${Math.round(m.probability * 100)}%, ATS ${Math.round(m.ats_after)})`);
      const autoSubmit = submit && (pd.extension || {}).auto_submit !== false;
      const res = await JP.flow.stepLoop(() => document.querySelector('form') || document.body, JP.makeCtx(pd, job, m), { autoSubmit });
      if (res.unanswered && res.unanswered.length) JP.page.highlight(res.unanswered);
      const status = res.status === 'ready_to_submit' ? 'needs_review' : res.status;
      await JP.record(PLATFORM, job, status, res.note, { probability: m.probability, resume_id: m.resume_id });
      JP.page.banner(res.status === 'applied' ? 'application submitted' : res.status === 'ready_to_submit' ? 'filled - review and press Submit' : res.note,
        res.status === 'applied' ? 'ok' : 'warn');
    } finally { busy = false; }
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === 'jp-fill-now' && JP.form.collectFields(document).length) run({ submit: !!msg.submit });   // only frames that contain a form
  });
  // auto-run on known ATS pages once an application form is on screen
  JP.state.get().then(async (s) => {
    if (!s.autofillCareers) return;
    for (let i = 0; i < 6; i++) { if (looksLikeApplicationForm()) return run({ submit: true }); await D.sleep(1500); }
  });
})();
