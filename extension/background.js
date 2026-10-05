// Service worker: the only place that talks to the local JobPilot API (so the token never reaches web pages),
// plus small helpers for cross-tab coordination.
const DEFAULTS = { serverUrl: "http://127.0.0.1:8765", token: "" };

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg) return;
  if (msg.type === "api") {
    (async () => {
      try {
        const { serverUrl, token } = await chrome.storage.local.get(DEFAULTS);
        if (!token) return sendResponse({ ok: false, error: "No token set. Open the extension options and paste the token printed by `python -m jobpilot api`." });
        const method = msg.method || "POST";
        const res = await fetch(serverUrl + msg.path, {
          method,
          headers: { "Content-Type": "application/json", "X-JobPilot-Token": token },
          body: method === "GET" ? undefined : JSON.stringify(msg.body || {}),
        });
        const data = await res.json().catch(() => ({}));
        sendResponse({ ok: res.ok, status: res.status, data, error: res.ok ? null : data.detail || data.error || `HTTP ${res.status}` });
      } catch (e) {
        sendResponse({ ok: false, error: "Can't reach JobPilot. Is `python -m jobpilot api` running?" });
      }
    })();
    return true; // async response
  }
  if (msg.type === "jp-whoami") { sendResponse({ tabId: sender.tab && sender.tab.id }); return; }
  if (msg.type === "jp-forward") { chrome.tabs.sendMessage(msg.tabId, msg.payload).catch(() => {}); return; }
  if (msg.type === "jp-close-tab" && sender.tab && sender.frameId === 0) { chrome.tabs.remove(sender.tab.id).catch(() => {}); return; }
});
