/* Receives the balance from content.js, keeps the latest value, and sends it to the local
 * GPT Image Studio service (http://127.0.0.1:<port>/api/balance-sync). Optionally refreshes on a timer
 * by opening the billing page in a background tab and closing it once the figure has been read. */
const BILLING_URL = "https://platform.openai.com/settings/organization/billing/overview";
const DEFAULTS = { port: 8765, intervalHours: 6 };
const autoTabs = new Set(); // tabs we opened ourselves, closed after reading

async function settings() {
  return { ...DEFAULTS, ...(await chrome.storage.local.get(["port", "intervalHours"])) };
}

async function pushToWorkbench(amount) {
  const { port } = await settings();
  try {
    const r = await fetch(`http://127.0.0.1:${port}/api/balance-sync`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount, source: "extension" }),
    });
    const d = await r.json().catch(() => ({}));
    return r.ok && !d.error ? { ok: true } : { ok: false, error: d.error || `HTTP ${r.status}` };
  } catch (e) {
    return { ok: false, error: "workbench offline" };
  }
}

async function record(patch) {
  await chrome.storage.local.set({ ...patch, lastCheck: Date.now() });
}

chrome.runtime.onMessage.addListener((msg, sender) => {
  (async () => {
    const tabId = sender.tab && sender.tab.id;
    if (msg.type === "balance") {
      const push = await pushToWorkbench(msg.amount);
      await record({ amount: msg.amount, readAt: Date.now(), push, status: "ok" });
    } else if (msg.type === "not_found") {
      await record({ status: "not_found" });
    }
    if (tabId != null && autoTabs.has(tabId)) { autoTabs.delete(tabId); chrome.tabs.remove(tabId).catch(() => {}); }
  })();
});

// open the billing page quietly in the background; close it after reading (or after 60 s at most)
async function refreshNow() {
  const tab = await chrome.tabs.create({ url: BILLING_URL, active: false });
  autoTabs.add(tab.id);
  setTimeout(() => {
    if (autoTabs.has(tab.id)) {
      autoTabs.delete(tab.id);
      chrome.tabs.remove(tab.id).catch(() => {});
      record({ status: "timeout" }); // usually: not logged in to platform.openai.com in this browser
    }
  }, 60000);
}

async function schedule() {
  const { intervalHours } = await settings();
  await chrome.alarms.clear("refresh");
  if (+intervalHours > 0) chrome.alarms.create("refresh", { periodInMinutes: +intervalHours * 60, delayInMinutes: 1 });
}

chrome.alarms.onAlarm.addListener(a => { if (a.name === "refresh") refreshNow(); });
chrome.runtime.onInstalled.addListener(schedule);
chrome.runtime.onStartup.addListener(schedule);
chrome.storage.onChanged.addListener(ch => { if (ch.intervalHours) schedule(); });
chrome.runtime.onMessage.addListener(msg => { if (msg.type === "refresh_now") refreshNow(); });
