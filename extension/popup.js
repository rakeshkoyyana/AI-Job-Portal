const LIBS = ['lib/mapper.js', 'lib/dom.js', 'lib/form.js', 'lib/flow.js', 'lib/core.js', 'lib/page.js'];
const $ = (id) => document.getElementById(id);
const day = () => new Date().toISOString().slice(0, 10);
const api = (path, method = 'GET') => new Promise((r) => chrome.runtime.sendMessage({ type: 'api', path, method, body: {} }, r));
const msg = (t) => { $('msg').textContent = t || ''; };

async function state() { return { running: {}, autofillCareers: true, counts: {}, log: [], ...((await chrome.storage.local.get('jp')).jp || {}) }; }
async function save(patch) { await chrome.storage.local.set({ jp: { ...(await state()), ...patch } }); }
const activeTab = async () => (await chrome.tabs.query({ active: true, currentWindow: true }))[0];

async function render() {
  const s = await state();
  const today = s.counts[day()] || {};
  for (const p of ['linkedin', 'indeed', 'career-site']) $('c-' + p).textContent = today[p] || 0;
  $('auto-careers').checked = !!s.autofillCareers;
  $('log').innerHTML = '';
  for (const e of s.log.slice(0, 25)) {
    const li = document.createElement('li');
    li.className = e.status;
    li.textContent = `${e.status.toUpperCase()} ${e.title || ''}${e.company ? ' @ ' + e.company : ''}${e.note ? ' - ' + e.note : ''}`;
    $('log').appendChild(li);
  }
}

async function start(platform, urlRe, hint) {
  const tab = await activeTab();
  if (!tab || !urlRe.test(tab.url || '')) return msg(hint);
  msg('');
  const s = await state();
  await save({ running: { ...s.running, [platform]: true } });
  chrome.tabs.sendMessage(tab.id, { type: 'jp-start', platform });
  window.close();
}

async function fill(submit) {
  const tab = await activeTab();
  if (!tab) return;
  await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, files: [...LIBS, 'content/careers.js'] });
  chrome.tabs.sendMessage(tab.id, { type: 'jp-fill-now', submit });
  window.close();
}

$('start-linkedin').onclick = () => start('linkedin', /linkedin\.com\/jobs/, 'Open a LinkedIn Jobs search page first.');
$('start-indeed').onclick = () => start('indeed', /^https:\/\/(?!smartapply)[^/]*indeed\.com\//, 'Open an Indeed search results page first.');
for (const p of ['linkedin', 'indeed']) {
  $('stop-' + p).onclick = async () => {
    const s = await state();
    await save({ running: { ...s.running, [p]: false } });
    const tab = await activeTab();
    if (tab) chrome.tabs.sendMessage(tab.id, { type: 'jp-stop' });
    msg('Stopping after the current job.');
  };
}
$('fill-submit').onclick = () => fill(true);
$('fill-only').onclick = () => fill(false);
$('auto-careers').onchange = (e) => save({ autofillCareers: e.target.checked });
$('opts').onclick = (e) => { e.preventDefault(); chrome.runtime.openOptionsPage(); };

(async () => {
  const r = await api('/api/health');
  $('conn').textContent = r.ok ? (r.data.llm ? 'connected (AI on)' : 'connected (rules mode)') : 'not connected';
  if (!r.ok) msg(r.error);
  render();
  chrome.storage.onChanged.addListener(render);
})();
