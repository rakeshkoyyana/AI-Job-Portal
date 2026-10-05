// Extension runtime glue: talks to the local JobPilot API (via the service worker), keeps settings, daily caps and the activity log.
(function (g) {
  'use strict';
  const JP = (g.JP = g.JP || {});
  const hasChrome = typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.sendMessage;

  const send = (msg) => new Promise((resolve) => {
    if (!hasChrome) return resolve({ ok: false, error: 'no chrome runtime' });
    chrome.runtime.sendMessage(msg, (r) => resolve(r || { ok: false, error: chrome.runtime.lastError?.message || 'no response' }));
  });
  const call = (path, body, method = 'POST') => send({ type: 'api', path, method, body });

  JP.api = {
    call,
    profile: () => call('/api/profile', null, 'GET'),
    jobMatch: (b) => call('/api/job-match', b),
    answer: (b) => call('/api/answer', b),
    status: (platform, key) => call(`/api/applications/status?platform=${encodeURIComponent(platform)}&job_key=${encodeURIComponent(key)}`, null, 'GET'),
    log: (b) => call('/api/applications', b),
  };

  // ---------------------------------------------------------------- settings, counters, activity log
  const DEFAULT = { running: { linkedin: false, indeed: false }, autofillCareers: true, counts: {}, log: [] };
  const day = () => new Date().toISOString().slice(0, 10);
  const store = {
    async get() {
      if (!hasChrome) return structuredClone(DEFAULT);
      const s = await chrome.storage.local.get('jp');
      return { ...structuredClone(DEFAULT), ...(s.jp || {}) };
    },
    async set(patch) {
      const cur = await store.get();
      await chrome.storage.local.set({ jp: { ...cur, ...patch } });
    },
    async count(platform) { return ((await store.get()).counts[day()] || {})[platform] || 0; },
    async inc(platform) {
      const s = await store.get();
      const counts = { [day()]: { ...(s.counts[day()] || {}), [platform]: ((s.counts[day()] || {})[platform] || 0) + 1 } };   // keep only today
      await store.set({ counts });
    },
    async setRunning(platform, on) { const s = await store.get(); await store.set({ running: { ...s.running, [platform]: on } }); },
    async push(entry) {
      const s = await store.get();
      await store.set({ log: [{ t: new Date().toISOString(), ...entry }, ...s.log].slice(0, 100) });
    },
  };
  JP.state = store;

  /** Record an outcome in the backend tracker and the local activity log; bumps today's counter when applied. */
  JP.record = async function record(platform, job, status, note = '', extra = {}) {
    await JP.api.log({ source: platform, external_id: String(job.key || job.url || job.title), title: job.title || '', company: job.company || '',
      location: job.location || '', url: job.url || '', status, notes: note, score: extra.probability ?? null, resume_id: extra.resume_id ?? null });
    await store.push({ platform, status, title: job.title, company: job.company, note });
    if (status === 'applied') await store.inc(platform);
  };

  /** Build the context the form filler needs from the backend profile + a job-match result. */
  JP.makeCtx = function makeCtx(profileData, job, match) {
    const ext = (profileData && profileData.extension) || {};
    return {
      profile: (profileData && profileData.profile) || {}, job: { title: job.title, company: job.company, description: (job.description || '').slice(0, 3000) },
      resume: match && match.resume ? match.resume : null, cover: null,
      acceptConsent: ext.accept_consent_checkboxes !== false,
      answer: async (req) => { const r = await JP.api.answer(req); return r.ok ? r.data : { answer: null, reason: r.error || 'api error' }; },
    };
  };

  JP.capFor = (profileData, platform) => Number(((profileData.extension || {}).daily_cap || {})[platform] ?? 25);
  JP.pace = (profileData) => JP.dom.pace(((profileData.extension || {}).pace_seconds) || [4, 9]);

  const api = { day };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : window);
