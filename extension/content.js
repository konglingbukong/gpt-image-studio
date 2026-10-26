/* Runs on platform.openai.com. On the billing page, finds the "Credit balance" figure and hands it to
 * background.js. It reads nothing else — no cookies, tokens or other page data. */
(() => {
  // label in the dashboard, in the languages OpenAI's UI may show
  const LABEL = /credit\s*balance|remaining\s*credit|余额|剩余额度|クレジット残高|残高|크레딧 잔액|잔액|баланс/i;
  const MONEY = /(-?)\$\s?([\d,]+(?:\.\d{1,2})?)/;

  function parseAmount(text) {
    const m = text.match(MONEY);
    return m ? (m[1] ? -1 : 1) * parseFloat(m[2].replace(/,/g, "")) : null;
  }

  // the dollar figure closest after a "Credit balance" label
  function findBalance() {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (!LABEL.test(node.textContent)) continue;
      // look at the label's container and a few levels up for the amount
      let el = node.parentElement;
      for (let up = 0; el && up < 4; up++, el = el.parentElement) {
        const text = el.innerText || "";
        const after = parseAmount(text.slice(text.search(LABEL)));  // usual layout: label, then amount
        if (after != null) return after;
        const before = parseAmount(text);                            // some layouts put the amount first
        if (before != null && up >= 1) return before;
      }
    }
    return null;
  }

  function isBillingPage() {
    return /\/billing/i.test(location.pathname);
  }

  let sent = false;
  function tryRead() {
    if (sent || !isBillingPage()) return;
    const amount = findBalance();
    if (amount == null) return;
    sent = true;
    chrome.runtime.sendMessage({ type: "balance", amount, url: location.href });
  }

  // the dashboard is a single-page app: wait for the figure to render, and re-check on navigation
  const obs = new MutationObserver(() => tryRead());
  obs.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
  let lastPath = location.pathname;
  setInterval(() => { if (location.pathname !== lastPath) { lastPath = location.pathname; sent = false; } tryRead(); }, 1500);
  tryRead();
  setTimeout(() => { if (!sent && isBillingPage()) chrome.runtime.sendMessage({ type: "not_found", url: location.href }); }, 25000);
})();
