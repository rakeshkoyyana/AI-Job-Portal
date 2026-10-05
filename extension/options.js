const $ = (id) => document.getElementById(id);
chrome.storage.local.get({ serverUrl: 'http://127.0.0.1:8765', token: '' }).then((v) => { $('url').value = v.serverUrl; $('token').value = v.token; });
$('save').onclick = async () => {
  await chrome.storage.local.set({ serverUrl: $('url').value.trim().replace(/\/$/, ''), token: $('token').value.trim() });
  $('status').textContent = 'Testing...';
  chrome.runtime.sendMessage({ type: 'api', path: '/api/health', method: 'GET' }, (r) => {
    const ok = r && r.ok;
    $('status').className = ok ? 'ok' : 'err';
    $('status').textContent = ok ? `Connected${r.data.llm ? ' (AI answers enabled)' : ' (rules mode: set ANTHROPIC_API_KEY for AI answers)'}.` : (r && r.error) || 'Could not connect.';
  });
};
