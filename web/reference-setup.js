/* Schedule only while the user can actually see the first-run choice. */
(() => {
  const panel = $("#libSetup"), dialog = $("#referencePicker");
  const start = $("#libSetupStart"), skip = $("#libSetupSkip");
  let status = null, seconds = 20, sequence = 0, inFlight = 0, changing = false;
  const active = state => ["downloading", "importing", "other", "stopping"].includes(state);

  function render() {
    if (!status) return;
    const {state, missing = []} = status;
    panel.hidden = state === "ready" || (state === "skipped" && !dialog.open);
    if (panel.hidden) return;
    const reason = ["space", "network", "integrity", "storage"].includes(status.reason) ? status.reason : "storage";
    $("#libSetupText").textContent = t("setup." + (state === "error" ? reason : state), {
      s: seconds, size: status.sizeMB, libraries: missing.map(k => t("lib." + k)).join(" + "),
      kind: status.kind ? t("lib." + status.kind) : "", mb: Math.floor((status.bytes || 0) / 1000000),
    });
    $("#libSetupTerms").hidden = !missing.includes("poses");
    start.hidden = active(state);
    start.disabled = changing;
    start.textContent = t(state === "error" || state === "interrupted" ? "setup.retry" : "setup.start");
    skip.hidden = state === "skipped" || state === "stopping";
    skip.disabled = changing;
    skip.textContent = t(active(state) ? "setup.stop" : "setup.skip");
  }

  async function update(action) {
    if (MODE !== "local" || (action ? changing : inFlight > 0)) return;
    const ticket = ++sequence;
    inFlight++;
    if (action) { changing = true; render(); }
    try {
      const options = action ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action})} : {};
      const response = await fetch(BASE + "/api/reference-setup", options);
      if (ticket !== sequence) return;
      if (!response.ok) throw new Error();
      const next = await response.json();
      if (ticket !== sequence || !next.state) return;
      const previous = status;
      status = next;
      if (previous?.missing?.some(k => !next.missing.includes(k))) dialog.dispatchEvent(new Event("library-installed"));
    } catch {
      // Older local servers have no installer; leave their other studio features available.
      if (ticket === sequence && status) status = {...status, state: "error", reason: "storage"};
    } finally {
      inFlight--;
      if (action) changing = false;
      render();
    }
  }

  function movePanel() {
    (dialog.open ? $("#libSetupPicker") : $("#libSetupHome")).append(panel);
    render();
    update();
  }
  dialog.addEventListener("library-opened", movePanel);
  dialog.addEventListener("close", movePanel);
  document.addEventListener("studio-language", render);
  start.onclick = () => update("start");
  skip.onclick = () => update("skip");

  studioReady.then(() => {
    if (MODE !== "local") return;
    update();
    setInterval(() => {
      if (!status || changing || document.hidden) return;
      if (active(status.state)) { update(); return; }
      if (status.state !== "offer" || $("#settings").classList.contains("open") || $("#lb").classList.contains("open")) return;
      const rect = skip.getBoundingClientRect();
      if (rect.height <= 0 || rect.top < 0 || rect.bottom > innerHeight) return;
      if (--seconds <= 0) update("auto");
      else render();
    }, 1000);
  });
})();
