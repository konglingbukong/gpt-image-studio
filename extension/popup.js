const m = (k, s) => chrome.i18n.getMessage(k, s) || k;
document.querySelectorAll("[data-m]").forEach(e => { e.textContent = m(e.dataset.m); });
document.querySelector('#interval option[value="0"]').textContent = m("off");

function ago(ts) {
  if (!ts) return "";
  const min = Math.round((Date.now() - ts) / 60000);
  return min < 1 ? m("justNow") : min < 60 ? m("minAgo", [String(min)]) : m("hourAgo", [String(Math.round(min / 60))]);
}

async function render() {
  const s = await chrome.storage.local.get(["amount", "readAt", "push", "status", "intervalHours", "port"]);
  document.getElementById("amount").textContent = s.amount != null ? "$" + s.amount.toFixed(2) : "—";
  const when = document.getElementById("when");
  when.textContent = s.status === "timeout" ? m("needLogin") : s.status === "not_found" ? m("notFound") : s.readAt ? m("readAt", [ago(s.readAt)]) : m("never");
  const push = document.getElementById("push");
  push.textContent = s.push ? (s.push.ok ? "✓ " + m("pushed") : "✕ " + m("pushFail", [s.push.error || ""])) : "";
  push.className = "muted " + (s.push ? (s.push.ok ? "ok" : "bad") : "");
  document.getElementById("interval").value = String(s.intervalHours ?? 6);
  document.getElementById("port").value = s.port ?? 8765;
}

document.getElementById("interval").onchange = e => chrome.storage.local.set({ intervalHours: +e.target.value });
document.getElementById("port").onchange = e => chrome.storage.local.set({ port: +e.target.value || 8765 });
document.getElementById("now").onclick = () => { chrome.runtime.sendMessage({ type: "refresh_now" }); document.getElementById("when").textContent = m("syncing"); };
chrome.storage.onChanged.addListener(render);
render();
