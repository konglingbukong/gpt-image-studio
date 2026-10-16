/* 浏览器模式后端：没有本机服务时，网页用它直接在浏览器里调 OpenAI。
 * 对外只有 BB.handle(path, body)，返回的 JSON 和 server.py 的同名接口一致，
 * 所以 index.html 不用关心自己是连着本机服务还是在浏览器里独立运行。
 * 设置（含 API key）存 localStorage，出图记录和图片存 IndexedDB，都只在这个浏览器里。
 */
const BB = (() => {
  const VERSION = "0.4";
  const DEF = {
    api_url: "https://api.openai.com/v1", model: "gpt-image-2.5-sunburst", size: "2K 16:9", quality: "high",
    format: "png", moderation: "auto", low_balance_warn: 5, timeout: 900,
    confirm_over_usd: 0.5, clear_after_submit: false, rates: { text_in: 5, image_in: 8, image_out: 30, per_image: 0 },
  };
  const SETTABLE = ["api_url", "model", "size", "quality", "format", "moderation", "usd_to_cny", "low_balance_warn",
    "timeout", "rates", "clear_after_submit", "confirm_over_usd", "agent_name", "fx_code", "fx_rate", "minimal_params", "balance_source"];
  const CFG_KEY = "gis_cfg";

  // ---------- 设置 ----------
  function cfg() {
    let c = {};
    try { c = JSON.parse(localStorage.getItem(CFG_KEY) || "{}"); } catch (e) {}
    return { ...DEF, ...c, rates: { ...DEF.rates, ...(c.rates || {}) } };
  }
  function saveCfg(c) { try { localStorage.setItem(CFG_KEY, JSON.stringify(c)); } catch (e) {} }
  const maskKey = k => (k && k.length > 12 ? `${k.slice(0, 7)}…${k.slice(-4)}` : (k ? "***" : ""));
  const apiBase = c => (c.api_url || DEF.api_url).replace(/\/+$/, "");

  // ---------- IndexedDB ----------
  let dbp;
  function db() {
    return dbp ||= new Promise((res, rej) => {
      const r = indexedDB.open("gpt-image-studio", 1);
      r.onupgradeneeded = () => {
        r.result.createObjectStore("records", { keyPath: "id" });
        r.result.createObjectStore("images", { keyPath: "id" });
      };
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
  }
  async function tx(store, mode, fn) {
    const d = await db();
    return new Promise((res, rej) => {
      const t = d.transaction(store, mode), s = t.objectStore(store);
      const out = fn(s);
      t.oncomplete = () => res(out && "result" in out ? out.result : out);
      t.onerror = () => rej(t.error);
    });
  }
  const allRecords = () => tx("records", "readonly", s => s.getAll());
  const getRecord = id => tx("records", "readonly", s => s.get(id));
  const putRecord = r => tx("records", "readwrite", s => s.put(r));
  const putImage = (id, blob) => tx("images", "readwrite", s => s.put({ id, blob }));
  const getImage = id => tx("images", "readonly", s => s.get(id));

  // 图片 id → blob: 地址（缓存，删除时回收）
  const urls = new Map();
  async function urlOf(imgId) {
    if (!urls.has(imgId)) {
      const r = await getImage(imgId);
      if (!r) return null;
      urls.set(imgId, URL.createObjectURL(r.blob));
    }
    return urls.get(imgId);
  }

  // ---------- 尺寸（移植自 gen.py parse_size） ----------
  const MIN_PIXELS = 655360, MAX_PIXELS = 8294400, MAX_EDGE = 3840;
  const TIER = { "1K": 1536, "2K": 2560, "4K": 3840 };
  const snap = v => Math.max(16, Math.floor(v / 16) * 16);
  function checkSize(w, h) {
    const p = [];
    if (w % 16 || h % 16) p.push(t("be.size.16"));
    if (Math.max(w, h) > MAX_EDGE) p.push(t("be.size.edge", { n: MAX_EDGE }));
    if (Math.max(w, h) / Math.min(w, h) > 3) p.push(t("be.size.ratio"));
    if (w * h < MIN_PIXELS || w * h > MAX_PIXELS) p.push(t("be.size.px", { n: (w * h).toLocaleString() }));
    if (p.length) throw new Error(t("be.size.invalid", { s: `${w}x${h}`, p: p.join("; ") }));
    return `${w}x${h}`;
  }
  function parseSize(text) {
    const t = String(text || "").trim().replace(/[×*]/g, "x");
    if (t.toLowerCase() === "auto") return "auto";
    if (/x/i.test(t) && !t.includes(":")) {
      const [w, h] = t.toLowerCase().split("x").map(Number);
      return checkSize(w, h);
    }
    const parts = t.toUpperCase().split(/\s+/);
    if (parts.length !== 2 || !TIER[parts[0]] || !parts[1].includes(":")) throw new Error(t("be.size.bad", { s: text }));
    const [rw, rh] = parts[1].split(":").map(Number);
    let L = TIER[parts[0]];
    if (rw === rh && parts[0] === "1K") L = 1024;
    let w = rw >= rh ? L : L * rw / rh, h = rw >= rh ? L * rh / rw : L;
    if (w * h > MAX_PIXELS) { const s = Math.sqrt(MAX_PIXELS / (w * h)); w *= s; h *= s; }
    if (w * h < MIN_PIXELS) { const s = Math.sqrt(MIN_PIXELS / (w * h)); w = Math.ceil(w * s / 16) * 16; h = Math.ceil(h * s / 16) * 16; }
    return checkSize(snap(w), snap(h));
  }

  // ---------- 计费（移植自 gen.py calc_cost / spend_summary） ----------
  // per_image > 0 (relays that bill per image) → per_image × n; otherwise from token usage (null if none)
  function calcCost(usage, c, n = 1) {
    if (+c.rates.per_image > 0) return Math.round(+c.rates.per_image * Math.max(n, 1) * 1e5) / 1e5;
    if (!usage) return null;
    const r = c.rates, ind = usage.input_tokens_details || {}, outd = usage.output_tokens_details || {};
    const textIn = ind.text_tokens ?? ((usage.input_tokens || 0) - (ind.image_tokens || 0));
    const imgIn = ind.image_tokens || 0, imgOut = outd.image_tokens ?? (usage.output_tokens || 0);
    return Math.round((textIn * r.text_in + imgIn * r.image_in + imgOut * r.image_out) / 1e6 * 1e5) / 1e5;
  }
  const pad = n => String(n).padStart(2, "0");
  const stampOf = d => `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
  function spendSummary(recs) {
    const today = stampOf(new Date()).slice(0, 8), month = today.slice(0, 6);
    const t = { today: 0, month: 0, all: 0, count_today: 0 };
    for (const m of recs) {
      const c = m.cost_usd || 0;
      t.all += c;
      if (m.time.startsWith(month)) t.month += c;
      if (m.time.startsWith(today)) { t.today += c; if (m.status !== "failed" || m.charged) t.count_today++; }
    }
    for (const k of ["today", "month", "all"]) t[k] = Math.round(t[k] * 1e4) / 1e4;
    return t;
  }

  // ---------- 余额：校准值 − 校准后花费（管理员 key 能查就用账单接口） ----------
  let costCache = { key: null, at: 0, value: null, error: null };
  async function adminSpendSince(ts, c) {
    const key = `${ts}|${c.admin_key}`;
    if (costCache.key === key && Date.now() - costCache.at < 300000) return costCache;
    let total = 0, page = null, error = null;
    try {
      for (let i = 0; i < 20; i++) {
        const u = `${apiBase(c)}/organization/costs?start_time=${Math.floor(ts)}&bucket_width=1d&limit=180${page ? `&page=${page}` : ""}`;
        const r = await fetch(u, { headers: { Authorization: `Bearer ${c.admin_key}` } });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        for (const b of d.data || []) for (const x of b.results || []) total += +(x.amount?.value || 0);
        if (!d.has_more) break;
        page = d.next_page;
      }
    } catch (e) {
      total = null;
      error = t("be.adminFail", { e: e.message });
    }
    costCache = { key, at: Date.now(), value: total, error };
    return costCache;
  }
  let relayCache = { at: 0, value: null };
  async function relayBalance(c) {
    if (Date.now() - relayCache.at < 60000) return relayCache.value;
    let v = null;
    const base = apiBase(c), roots = [base, base.replace(/\/v1$/, "")];
    for (const root of roots) {
      try {
        const h = { headers: { Authorization: `Bearer ${c.api_key}` }, signal: AbortSignal.timeout(15000) };
        const sub = await (await fetch(`${root}/dashboard/billing/subscription`, h)).json();
        const total = +(sub.hard_limit_usd || sub.system_hard_limit_usd || 0);
        let used = 0;
        try { used = +((await (await fetch(`${root}/dashboard/billing/usage?start_date=2000-01-01&end_date=${new Date().toISOString().slice(0, 10)}`, h)).json()).total_usage || 0) / 100; } catch (e) {}
        if (total > 0) { v = { total, used, remaining: total - used }; break; }
      } catch (e) {}
    }
    relayCache = { at: Date.now(), value: v };
    return v;
  }

  async function balance(c, recs) {
    const src = c.balance_source || "auto";
    if (c.api_key && (src === "relay" || (src === "auto" && !/api\.openai\.com/.test(apiBase(c))))) {
      const rb = await relayBalance(c);
      if (rb) return { set: true, source: "relay", amount: rb.total, spent: Math.round(rb.used * 1e4) / 1e4,
        remaining: Math.round(rb.remaining * 1e4) / 1e4, at: null, error: null, low: rb.remaining < +(c.low_balance_warn ?? 5) };
    }
    const b = c.balance;
    if (!b || b.amount == null) return { set: false };
    const since = stampOf(new Date(b.at * 1000));
    let spent = null, source = "local", error = null;
    if (c.admin_key) {
      const r = await adminSpendSince(b.at, c);
      if (r.value != null) { spent = r.value; source = "admin"; } else error = r.error;
    }
    if (spent == null) spent = recs.filter(m => m.time >= since).reduce((a, m) => a + (m.cost_usd || 0), 0);
    const remaining = +b.amount - spent;
    return { set: true, amount: +b.amount, at: b.at, spent: Math.round(spent * 1e4) / 1e4, remaining: Math.round(remaining * 1e4) / 1e4,
      source, error, low: remaining < +(c.low_balance_warn ?? 5) };
  }

  // ---------- 出图 ----------
  let RUNNING = [];
  const safeName = s => (String(s || "img").replace(/[\\/:*?"<>|]/g, "").trim().slice(0, 40) || "img");
  function dataUrlToBlob(u) {
    const [head, b64] = u.split(",", 2);
    const mime = (head.match(/data:([^;]+)/) || [])[1] || "application/octet-stream";
    const bin = atob(b64), arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    return new Blob([arr], { type: mime });
  }
  async function openaiError(r) {
    let msg = "";
    try { msg = (await r.json()).error?.message || ""; } catch (e) { msg = (await r.text().catch(() => "")).slice(0, 500); }
    return t("be.openaiErr", { code: r.status, msg }) + (r.status === 400 && /param|argument|unknown|unrecognized|not supported/i.test(msg) ? " — " + t("compat.title") + "?" : "");
  }
  // OpenAI 的 POST 出错时（401/400/429…）响应里不带 CORS 头，浏览器只给一句 "Failed to fetch"，
  // 看不到真正原因。这里用一个带 CORS 的 GET 再探一次，推断是 key、网络还是这次请求本身被拒。
  async function diagnose(c) {
    const r = await test({});
    if (!r.ok && /401/.test(r.msg)) return t("be.keyBad");
    if (!r.ok) return t("be.cantReach", { e: r.raw || r.msg });
    return t("be.rejected");
  }

  // image data from a response item: base64 (official API) or a URL (many relays)
  async function itemBlob(item, fmt) {
    if (item.b64_json) return dataUrlToBlob(`data:image/${fmt};base64,${item.b64_json}`);
    if (item.url && item.url.startsWith("data:")) return dataUrlToBlob(item.url);
    if (item.url) {
      try { const r = await fetch(item.url); if (r.ok) return await r.blob(); throw new Error("HTTP " + r.status); }
      catch (e) { throw Object.assign(new Error(t("be.imgDownload", { e: e.message })), { openai: true }); }
    }
    throw Object.assign(new Error(t("be.noImage")), { openai: true });
  }

  // best guess for a billed-but-lost call: per-image price, else the average of earlier runs with the same specs
  async function estimateCost(params, c, hasRefs) {
    if (+c.rates.per_image > 0) return +c.rates.per_image * (params.n || 1);
    const same = (await allRecords()).filter(m => m.status === "done" && m.cost_usd && (m.files || []).length
      && m.params.size === params.size && m.params.quality === params.quality && ((m.refs || []).length > 0) === hasRefs);
    return same.length ? same.reduce((a, m) => a + m.cost_usd / m.files.length, 0) / same.length * (params.n || 1) : null;
  }

  async function generate(body) {
    const c = cfg();
    if (!c.api_key) return { error: t("be.noKey") };
    const prompt = (body.prompt || "").trim();
    if (!prompt) return { error: t("be.emptyPrompt") };
    let size;
    try { size = parseSize(body.size || c.size); } catch (e) { return { error: e.message }; }
    const fmt = body.format || c.format;
    const params = { model: body.model || c.model, prompt, size, quality: body.quality || c.quality, n: +body.n || 1, output_format: fmt };
    if (body.background && body.background !== "auto") params.background = body.background;
    const refs = body.refs || [];
    const endpoint = refs.length ? "/images/edits" : "/images/generations";
    if (!refs.length) params.moderation = body.moderation || c.moderation;
    if (c.minimal_params) for (const k of ["moderation", "output_format", "background"]) delete params[k];  // relays that reject extras
    const now = new Date(), stamp = stampOf(now), name = safeName(body.name);
    const id = `${stamp}_${name}_${Math.random().toString(36).slice(2, 6)}`;
    const job = { started: now.getTime() / 1000, name, source: "web", refs: refs.length, size, quality: params.quality, model: params.model, prompt };
    RUNNING.push(job);
    const t0 = performance.now();
    const base = { id, time: stamp, endpoint, params, refs: refs.map(r => r.name || "ref"), mask: body.mask ? "mask.png" : null };
    try {
      let r;
      const signal = AbortSignal.timeout((+c.timeout || 900) * 1000);
      if (refs.length) {
        const fd = new FormData();
        for (const [k, v] of Object.entries(params)) fd.append(k, String(v));
        refs.forEach((x, i) => fd.append("image[]", dataUrlToBlob(x.data), x.name || `ref${i + 1}.png`));
        if (body.mask) fd.append("mask", dataUrlToBlob(body.mask.data), "mask.png");
        r = await fetch(apiBase(c) + endpoint, { method: "POST", headers: { Authorization: `Bearer ${c.api_key}` }, body: fd, signal });
      } else {
        r = await fetch(apiBase(c) + endpoint, { method: "POST", signal,
          headers: { Authorization: `Bearer ${c.api_key}`, "Content-Type": "application/json" }, body: JSON.stringify(params) });
      }
      if (!r.ok) throw Object.assign(new Error(await openaiError(r)), { openai: true });
      let resp;
      try { resp = await r.json(); }  // the image exists (and was billed) but the body broke off while downloading
      catch (e) { throw Object.assign(new Error(e.message), { lost: true }); }
      const files = [];
      if (!(resp.data || []).length) throw Object.assign(new Error(t("be.noImage")), { openai: true });
      for (const [i, item] of resp.data.entries()) {
        const imgId = `${id}_${i + 1}`;
        await putImage(imgId, await itemBlob(item, fmt));
        files.push(imgId);
      }
      navigator.storage?.persist?.(); // 尽量别让浏览器在空间紧张时清掉图片
      const rec = { ...base, status: "done", seconds: Math.round((performance.now() - t0) / 100) / 10,
        usage: resp.usage || null, cost_usd: calcCost(resp.usage, c, files.length), files };
      await putRecord(rec);
      return { ...rec, files: await Promise.all(files.map(urlOf)) };
    } catch (e) {
      if (e.lost) {
        const est = await estimateCost(params, c, refs.length > 0);
        const msg = t("be.lost", { c: est != null ? "$" + est.toFixed(4) : t("be.lostUnknown") });
        await putRecord({ ...base, status: "failed", charged: true, error: msg, seconds: Math.round((performance.now() - t0) / 100) / 10, cost_usd: est || 0, files: [] });
        return { error: msg };
      }
      const msg = e.name === "TimeoutError" ? t("be.timeout")
        : e.openai ? e.message : await diagnose(c);
      await putRecord({ ...base, status: "failed", error: msg, seconds: Math.round((performance.now() - t0) / 100) / 10, cost_usd: 0, files: [] });
      return { error: msg };
    } finally {
      RUNNING = RUNNING.filter(j => j !== job);
    }
  }

  // ---------- 记录 ----------
  async function history() {
    const recs = (await allRecords()).sort((a, b) => (a.id < b.id ? 1 : -1));
    const out = [];
    for (const m of recs) {
      const files = (await Promise.all((m.files || []).map(urlOf))).filter(Boolean);
      if (!files.length && m.status !== "failed") continue;
      out.push({ ...m, files });
    }
    return out;
  }
  async function setFav(id, fav) {
    const m = await getRecord(id);
    if (!m) return { error: t("be.notFound") };
    if (fav) m.fav = true; else delete m.fav;
    await putRecord(m);
    return { ok: true };
  }
  async function del(id) {
    const m = await getRecord(id);
    if (!m) return { error: t("be.notFound") };
    await tx("images", "readwrite", s => (m.files || []).forEach(f => s.delete(f)));
    await tx("records", "readwrite", s => s.delete(id));
    for (const f of m.files || []) { if (urls.has(f)) { URL.revokeObjectURL(urls.get(f)); urls.delete(f); } }
    return { ok: true };
  }

  // ---------- 设置接口 ----------
  async function settingsView() {
    const c = cfg();
    let usage = null;
    try { const e = await navigator.storage?.estimate?.(); if (e) usage = e.usage; } catch (e) {}
    const v = {};
    for (const k of SETTABLE) v[k] = c[k];
    return { ...v, mode: "browser", api_key_masked: maskKey(c.api_key), key_source: t("be.keySrc"),
      admin_key_masked: maskKey(c.admin_key), balance: c.balance || null, out_dir: t("be.outDir"),
      storage_bytes: usage, version: VERSION, skill_dir: "", config_file: "" };
  }
  async function saveSettings(b) {
    const c = cfg();
    for (const k of SETTABLE) if (k in b) c[k] = b[k];
    if (b.api_key) c.api_key = String(b.api_key).trim();
    if ("admin_key" in b) { if (b.admin_key) c.admin_key = String(b.admin_key).trim(); else delete c.admin_key; }
    if ("balance_amount" in b) {
      if (b.balance_amount === "" || b.balance_amount == null) delete c.balance;
      else c.balance = { amount: +b.balance_amount, at: Date.now() / 1000 };
    }
    if (+b.topup_amount) {  // a top-up raises the calibrated amount; calibration time stays
      if (!c.balance || c.balance.amount == null) return { error: t("toast.needCal") };
      c.balance.amount = Math.round((+c.balance.amount + +b.topup_amount) * 1e4) / 1e4;
      (c.balance.topups ||= []).push({ amount: +b.topup_amount, at: Date.now() / 1000 });
    }
    saveCfg(c);
    costCache.key = null;
    relayCache.at = 0;
    return settingsView();
  }
  async function test(b) {
    const c = cfg(), key = (b.api_key || "").trim() || c.api_key;
    if (!key) return { ok: false, msg: t("be.noKeyTest") };
    const t0 = performance.now(), base = (b.api_url || c.api_url || DEF.api_url).replace(/\/+$/, ""), model = b.model || c.model;
    const opt = { headers: { Authorization: `Bearer ${key}` }, signal: AbortSignal.timeout(30000) };
    try {
      let r = await fetch(`${base}/models/${model}`, opt).catch(() => null);
      if (r && r.ok) return { ok: true, msg: t("be.testOk", { ms: Math.round(performance.now() - t0), m: model }) };
      if (r && (r.status === 401 || r.status === 403)) return { ok: false, msg: await openaiError(r) };
      // many relays only implement GET /models
      r = await fetch(`${base}/models`, opt);
      if (!r.ok) return { ok: false, msg: await openaiError(r) };
      const ids = ((await r.json()).data || []).map(m => m.id);
      return { ok: true, msg: ids.includes(model) ? t("be.testOk", { ms: Math.round(performance.now() - t0), m: model }) : t("be.unlisted", { m: model }) };
    } catch (e) {
      return { ok: false, msg: t("be.cantConnect", { e: e.message }), raw: e.message };
    }
  }

  // ---------- 路由（和 server.py 同名） ----------
  async function handle(path, body) {
    try {
      switch (path) {
        case "/api/size": try { return { size: parseSize(body.size) }; } catch (e) { return { error: e.message }; }
        case "/api/generate": return await generate(body);
        case "/api/history": return await history();
        case "/api/status": {
          const recs = await allRecords(), c = cfg();
          const last = recs.reduce((a, m) => (m.id > a ? m.id : a), "");
          return { running: RUNNING.map(j => ({ ...j, elapsed: Math.round(Date.now() / 1000 - j.started) })),
            sig: `${recs.length}:${last}`, spend: spendSummary(recs), usd_to_cny: c.usd_to_cny, balance: await balance(c, recs) };
        }
        case "/api/settings": return body ? await saveSettings(body) : await settingsView();
        case "/api/test": return await test(body || {});
        case "/api/fav": return await setFav(body.id, !!body.fav);
        case "/api/delete": return await del(body.id);
        default: return { ok: true, unsupported: true }; // 打开文件夹、关闭服务这类只有本机才有的
      }
    } catch (e) {
      return { error: `${e.name}: ${e.message}` };
    }
  }
  return { handle };
})();
