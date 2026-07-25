"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// esc() is for HTML text/attributes. It is UNSAFE for a value passed as a JS-string argument in an
// inline handler (onclick="fn('…')"): the HTML parser decodes &#39; back to ' before the JS runs,
// so a name like O'Brien breaks out of the string. jsStr() hex-escapes every non-alphanumeric
// char (\xHH/\uHHHH) — the result can't break out of the JS string nor the HTML attribute, and
// decodes back to the exact original for the receiving handler.
const jsStr = (s) => String(s ?? "").replace(/[^A-Za-z0-9_]/g, c => {
  const n = c.charCodeAt(0);
  return (n < 256 ? "\\x" : "\\u") + n.toString(16).padStart(n < 256 ? 2 : 4, "0");
});
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const APPCOLORS = ["#5a8fef", "#f0a63a", "#38b2ac", "#ef6f6c", "#9b7ede", "#4bb76a", "#e0607e"];
const color = (n) => APPCOLORS[(n ? n.charCodeAt(0) : 0) % APPCOLORS.length];

let STATE = {
  identity: null, catalog: null, cache: null, auth: null, lastResult: null,
  mode: "individual", channel: "stable",
  apps: null, scripts: null, stage: { apps: [], scripts: [] }, hist: { apps: [], scripts: [] },
  busy: { apps: false, scripts: false },  // a remote .nwa download is in flight for this workshop
};
// Optional deep-link / reproducible-capture overrides (all are already user-settable prefs):
// ?lang=fr|en · ?theme=light|dark · ?mode=individual|classroom. They never auto-connect a device.
const QS = new URLSearchParams(location.search);

// -- helpers -------------------------------------------------------------------
async function api(path, opts) {
  const r = await fetch(path, opts);
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
  return d;
}
const post = (path, body) => api(path,
  { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
let TT;
function toast(msg, err) {
  $("toast-msg").textContent = msg;
  $("toast").className = "toast show" + (err ? " err" : "");
  clearTimeout(TT); TT = setTimeout(() => $("toast").className = "toast", 3600);
}
function runMeter(m) {
  return new Promise(res => {
    if (reduced) { m.style.width = "100%"; m.classList.add("done"); return res(); }
    let p = 0; const it = setInterval(() => {
      p += 19; if (p >= 100) { p = 100; clearInterval(it); m.style.width = "100%"; m.classList.add("done"); setTimeout(res, 180); }
      else m.style.width = p + "%";
    }, 90);
  });
}
function fmtBytes(n) {
  n = n || 0;
  if (n < 1024) return n + " o";
  if (n < 1024 * 1024) return (Math.round(n / 102.4) / 10) + " Kio";
  return (Math.round(n / 104857.6) / 10) + " Mio";
}
function setLang(l) { LANG = l; localStorage.setItem("nwlang", l); document.documentElement.lang = l; renderAll(); }
const variantOf = (fam) => fam === "graphique" ? "graphing" : "scientific";
const clone = (x) => JSON.parse(JSON.stringify(x));

// -- load / connection ---------------------------------------------------------
async function load() {
  const qm = QS.get("mode");
  STATE.mode = (qm === "individual" || qm === "classroom") ? qm : (localStorage.getItem("nwmode") || "individual");
  STATE.demoModels = await api("/api/device/demo-models").catch(() => null);
  STATE.identity = await api("/api/identity");
  if (STATE.identity && STATE.identity.connected) await loadConnected();
  else renderAll();
  startPoll();  // always on: catches a plug-in while disconnected AND an unplug while connected
}

async function loadConnected() {
  const [cat, cache, auth] = await Promise.all(
    [api("/api/catalog"), api("/api/cache"), api("/api/auth")]);
  STATE.catalog = cat; STATE.cache = cache; STATE.auth = auth;
  STATE.channel = cat.channel || STATE.channel || "stable";
  const appsInfo = await api("/api/apps").catch(() => ({ has_external_apps: false, apps: [], api_level: 0 }));
  const installed = await api("/api/apps/installed").catch(() => ({ installed: [] }));
  const reg = STATE.identity.external_apps_flash;
  const cap = reg ? (parseInt(reg[1], 16) - parseInt(reg[0], 16)) : 0;
  STATE.apps = { hasRegion: appsInfo.has_external_apps, avail: appsInfo.apps || [],
                 apiLevel: appsInfo.api_level || 0, device: installed.installed || [], capacity: cap };
  const sc = await api("/api/scripts").catch(() => ({ has_scripts: false, capacity: 0, scripts: [], available: [] }));
  STATE.scripts = { hasScripts: sc.has_scripts, device: sc.scripts || [],
                    avail: sc.available || [], capacity: sc.capacity || 0 };
  initStage("apps"); initStage("scripts");
  renderAll();
}

let POLL = null;
function startPoll() { if (!POLL) POLL = setInterval(pollOnce, 4000); }
function stopPoll() { if (POLL) { clearInterval(POLL); POLL = null; } }
async function pollOnce() {
  const i = STATE.identity;
  if (!i || !i.connected) {
    // Disconnected: watch for a calculator being plugged in.
    try { const r = await post("/api/device/rescan"); if (r && r.connected) await onConnected(true); }
    catch (e) { /* keep waiting */ }
  } else if (!i.virtual) {
    // Connected to real hardware: notice an unplug (cheap, lock-guarded liveness probe).
    try { const r = await api("/api/device/health"); if (r && r.connected === false) await onDisconnected(); }
    catch (e) { /* transient — retry next tick */ }
  }
}
async function onConnected(real) {
  STATE.identity = await api("/api/identity");
  await loadConnected();
  toast(t(real ? "real_connected" : "demo_connected"));
}
async function onDisconnected() {
  // The cable was pulled: drop to the "no calculator" screen. POLL stays on, so the next ticks
  // hit the rescan branch and re-attach automatically when it is plugged back in.
  STATE.identity = { connected: false };
  STATE.catalog = STATE.cache = STATE.apps = STATE.scripts = null;
  renderAll();
  toast(t("device_lost"), true);
}
async function rescanDevice() {
  const r = await post("/api/device/rescan").catch(() => ({}));
  if (r && r.connected) await onConnected(true); else toast(t("nodev_wait"));
}
function demoModelOptions(sel) {
  const ms = STATE.demoModels || [{ name: "n0110", family: "graphique" }];
  return ms.map(m => `<option value="${m.name}"${m.name === sel ? " selected" : ""}>`
    + `${m.name.toUpperCase()} · ${t(m.family === "graphique" ? "fam_g" : "fam_s")}</option>`).join("");
}
async function exploreDemo() {
  const model = ($("demo-model") && $("demo-model").value) || "n0110";
  try { await post("/api/device/demo", { model }); await onConnected(false); }
  catch (e) { toast(t("fail", { msg: e.message }), true); }
}
async function switchDemo(model) {
  try { await post("/api/device/demo", { model }); await onConnected(false); }
  catch (e) { toast(t("fail", { msg: e.message }), true); }
}
async function disconnectDevice() {
  try { await post("/api/device/detach"); } catch (e) { /* ignore */ }
  STATE.identity = { connected: false }; renderAll(); startPoll(); toast(t("disconnected_toast"));
}

// -- top-level render ----------------------------------------------------------
function renderAll() {
  $("lang-fr").setAttribute("aria-pressed", LANG === "fr");
  $("lang-en").setAttribute("aria-pressed", LANG === "en");
  $("subtitle").textContent = t("subtitle");
  $("disclaimer-txt").innerHTML = t("disclaimer");
  $("quit-btn").textContent = t("quit");
  $("note-txt").innerHTML = t("note");
  $("t-accmode").textContent = t("accmode");
  $("t-update").textContent = t("update");
  $("t-apps").textContent = t("apps");
  $("t-scripts").textContent = t("scripts_title");
  $("mode-individual").textContent = t("mode_individual");
  $("mode-classroom").textContent = t("mode_classroom");
  $("chan-stable").textContent = t("chan_stable");
  $("chan-beta").textContent = t("chan_beta");
  $("c-supervise-label").textContent = t("supervise_label");
  $("c-dl-label").textContent = t("dl_label");
  $("acc-hint").textContent = t("acc_hint");
  const conn = !!(STATE.identity && STATE.identity.connected);
  $("stack").style.display = conn ? "" : "none";
  document.querySelector(".grid").classList.toggle("solo", !conn);
  renderDeviceCard();
  if (conn) { renderMode(); renderCatalog(); renderWorkbench(); }
}

function renderDeviceCard() {
  const el = $("device-card"), i = STATE.identity;
  if (!i || !i.connected) {
    el.innerHTML = `<div class="nodev">
      <div class="ico" aria-hidden="true">🔌</div>
      <h3>${t("nodev_title")}</h3>
      <p>${t("nodev_hint")}</p>
      <div class="row">
        <button class="btn" onclick="rescanDevice()">${t("rescan")}</button>
        <div class="demo-pick">
          <select id="demo-model" aria-label="${t("demo_model")}">${demoModelOptions("n0110")}</select>
          <button class="btn ghost" onclick="exploreDemo()">${t("demo_btn")}</button>
        </div>
      </div>
      <p class="hint" style="margin-top:16px"><span class="waitdot"></span>${t("nodev_wait")}</p>
    </div>`;
    return;
  }
  const variant = variantOf(i.family), fc = variant === "graphing" ? "g" : "s";
  el.innerHTML = `<div class="dev-head"><h2>${t("device")}</h2>
      <button class="gear" title="${t("dev_menu")}" aria-label="${t("dev_menu")}" onclick="disconnectDevice()">⚙</button></div>
    <div class="calc-slot">${buildCalc(variant)}</div>
    <dl>
      <dt>${t("model")}</dt><dd>${esc(i.model)}${i.virtual ? ` <span class="tag imp">${t("demo_tag")}</span>` : ""}</dd>
      <dt>${t("family")}</dt><dd><span class="fam ${fc}">${t(fc === "g" ? "fam_g" : "fam_s")}</span></dd>
      <dt>MCU</dt><dd>${esc(i.mcu || "—")}</dd>
      <dt>${t("serial")}</dt><dd>${esc(i.serial_number || "—")}</dd>
      <dt>OS</dt><dd>Epsilon ${esc(i.os_version || "?")}</dd>
      <dt>bcdDevice</dt><dd>${esc(i.bcd_device)}</dd>
      <dt>${t("appsregion")}</dt><dd>${i.has_external_apps ? t("region_present") : t("region_absent")}</dd>
    </dl>
    <p class="hint">${i.virtual ? t("demo_dev_hint") : t("real_hint")}</p>`
    + (i.virtual ? `<div class="demo-switch"><span>${t("demo_model")}</span>
      <select id="demo-model2" onchange="switchDemo(this.value)">${demoModelOptions(i.model)}</select></div>` : "");
}

// -- account & mode ------------------------------------------------------------
function setMode(m) { STATE.mode = m; localStorage.setItem("nwmode", m); renderMode(); renderWorkbench(); }
function renderMode() {
  $("mode-individual").setAttribute("aria-pressed", STATE.mode === "individual");
  $("mode-classroom").setAttribute("aria-pressed", STATE.mode === "classroom");
  const b = $("mode-body");
  if (STATE.mode === "classroom") {
    b.innerHTML = `<p class="classroom-intro">${t("classroom_intro")}</p>
      <div id="cache-body" class="cache"></div>
      <div class="classroom-row"><button class="btn" onclick="updateCaches()">${t("update_caches")}</button></div>`;
    renderCache();
  } else {
    b.innerHTML = `<div id="auth-body"></div>`;
    renderAuth();
  }
}
function renderAuth() {
  const a = STATE.auth || {}, b = $("auth-body");
  if (!b) return;
  let status;
  if (a.authenticated) status = `<span class="auth-ok">${t("auth_in", { d: a.expires_at || "?" })}</span>`;
  else if (a.expired) status = `<span class="hint" style="margin:0">${t("auth_expired")}</span>`;
  else status = `<span class="hint" style="margin:0">${t("auth_out")}</span>`;
  if (a.authenticated) {
    b.innerHTML = `<div class="status">${status}</div>
      <div class="reg-chip">✓ ${t("registered")}</div>
      <div class="auth-row">
        <button class="btn sm" onclick="captureSequence()">${t("capture_btn")}</button>
        <button class="btn ghost sm" onclick="logoutAuth()">${t("auth_logout")}</button>
      </div>
      <p class="hint">${t("capture_hint")}</p>`;
  } else {
    b.innerHTML = `<div class="status">${status}</div>
      <div class="auth-row">
        <input id="auth-email" type="email" placeholder="${t("auth_email")}" autocomplete="username">
        <input id="auth-pw" type="password" placeholder="${t("auth_pw")}" autocomplete="current-password">
        <button class="btn sm" onclick="loginPassword()">${t("auth_login")}</button>
      </div>
      <p class="hint">${t("auth_pw_note")}</p>
      <details class="auth-adv"><summary>${t("auth_adv")}</summary>
        <p class="hint">${t("auth_hint")}</p>
        <div class="auth-row">
          <input id="auth-token" type="password" placeholder="${t("auth_ph")}" autocomplete="off">
          <button class="btn ghost sm" onclick="loginToken()">${t("auth_save")}</button>
        </div></details>`;
  }
}
async function _applyLogin(payload) {
  STATE.auth = await post("/api/auth/login", payload);
  toast(t("auth_saved")); renderAuth(); renderCatalog();
}
async function loginPassword() {
  const email = ($("auth-email").value || "").trim(), pw = $("auth-pw").value || "";
  if (!email || !pw) return;
  try { await _applyLogin({ email, password: pw }); } catch (e) { toast(t("fail", { msg: e.message }), true); }
}
async function loginToken() {
  const token = ($("auth-token").value || "").trim();
  if (!token) return;
  try { await _applyLogin({ token }); } catch (e) { toast(t("fail", { msg: e.message }), true); }
}
async function logoutAuth() {
  try { STATE.auth = await post("/api/auth/logout"); toast(t("auth_gone")); renderAuth(); renderCatalog(); }
  catch (e) { toast(t("fail", { msg: e.message }), true); }
}
async function captureSequence() {
  toast(t("capture_running"));
  try {
    const dump = await post("/api/capture");
    const blob = new Blob([JSON.stringify(dump, null, 2)], { type: "application/json" });
    const ts = (dump.timestamp || "dump").replace(/[:\-]/g, "").slice(0, 15);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = `nwupdater-capture-${ts}.json`;
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(a.href);
    toast(t("capture_done"));
  } catch (e) { toast(t("fail", { msg: e.message }), true); }
}
function renderCache() {
  const c = STATE.cache, el = $("cache-body");
  if (!el) return;
  const entries = (c && c.entries) || [];
  if (!entries.length) {
    el.className = "cache";
    el.innerHTML = `<span class="ct"><b>${t("cache_mode")}</b> — ${t("cache_intro")}</span>`;
    return;
  }
  el.className = "cache-list";
  // Channel badge: beta stands out (imp), stable is muted (un) — so a cached pre-release is
  // never mistaken for a stable image at a glance.
  const chanTag = (e) => e.channel === "beta"
    ? ` <span class="tag imp">${t("chan_beta")}</span>`
    : ` <span class="tag un">${t("chan_stable")}</span>`;
  const rows = entries.map(e => `<div class="cache-row">
      <span class="cache-nm">${esc(e.model.toUpperCase())} · Epsilon ${esc(e.version)}${chanTag(e)}${
        e.real ? "" : ` <span class="tag imp">${t("demo_tag")}</span>`}</span>
      <span class="cache-sz">${fmtBytes(e.size)}</span></div>`).join("");
  el.innerHTML = rows + `<div class="cache-foot">
      <span class="ct">${t("cache_summary", { n: entries.length, d: c.expires_in_days ?? 30 })}</span>
      <button class="btn ghost sm" onclick="clearCache()">${t("clear")}</button></div>`;
}
async function updateCaches() {
  try { STATE.cache = await post("/api/cache/preload-all"); toast(t("caches_updated")); renderCache(); }
  catch (e) { toast(t("fail", { msg: e.message }), true); }
}
async function preload(v) {
  try { STATE.cache = await post("/api/cache/preload", { version: v }); toast(t("preloaded", { v })); renderCache(); }
  catch (e) { toast(t("fail", { msg: e.message }), true); }
}
async function clearCache() {
  try { STATE.cache = await post("/api/cache/clear"); toast(t("cache_cleared")); renderCache(); }
  catch (e) { toast(t("fail", { msg: e.message }), true); }
}

// -- system update -------------------------------------------------------------
async function setChannel(ch) {
  STATE.channel = ch;
  try { await post("/api/channel", { channel: ch }); STATE.catalog = await api("/api/catalog"); }
  catch (e) { /* offline: keep the last catalogue */ }
  renderCatalog();
}
function renderCatalog() {
  const c = STATE.catalog; if (!c) return;
  $("chan-stable").setAttribute("aria-pressed", STATE.channel === "stable");
  $("chan-beta").setAttribute("aria-pressed", STATE.channel === "beta");
  $("c-img-hint").textContent = t("img_hint");
  $("c-exam-warn").textContent = t("exam_warn");  // guide: cold-boot (RESET) after flashing keeps official status
  const up = c.up_to_date;
  $("c-badge").className = "badge " + (up ? "ok" : "up");
  $("c-badge").textContent = up ? t("uptodate") : t("update_avail");
  const srcTag = c.source === "official"
    ? `<span class="tag un" style="margin-left:7px">${t("cat_official")}</span>`
    : `<span class="tag imp" style="margin-left:7px">${t("cat_sample")}</span>`;
  $("c-text").innerHTML = (up ? t("uptodate_txt", { v: esc(c.current) })
    : t("updates_txt", { cur: esc(c.current), n: c.updates.length })) + srcTag;
  $("c-row").style.display = up ? "none" : "flex";
  // A firmware cached for THIS model can be flashed with no account (classroom / offline). When
  // present, pre-select it and tag the option so it's the obvious one-click choice.
  const ce = cachedEntryForDevice();
  const cachedHit = !!(ce && c.updates.some(u => u.version === ce.version));
  $("c-select").innerHTML = c.updates.map((u, i) =>
    `<option value="${esc(u.version)}"${(cachedHit ? u.version === ce.version : i === 0) ? " selected" : ""}>`
    + `Epsilon ${esc(u.version)}${i === 0 ? " — " + t("latest_opt") : ""}`
    + `${(ce && u.version === ce.version) ? " · " + t("cached") : ""}</option>`).join("");
  const isReal = !STATE.identity.virtual;
  $("c-install").textContent = (cachedHit && isReal) ? t("install_cache") : t("install");
  const slot = STATE.identity.has_external_apps ? t("slot_ab", { slot: "B" }) : t("slot_single");
  const authed = !!(STATE.auth && STATE.auth.authenticated);
  const dl = $("c-download");
  if (isReal) {
    $("c-dl-toggle").style.display = "none"; if (dl) dl.checked = true;
    // Enable when there's an update AND we can source an image: a cached one (no sign-in) or a
    // signed-in official download.
    $("c-install").disabled = up || (!cachedHit && !authed);
    $("c-slot").textContent = up ? "" : (cachedHit ? t("slot_cache", { v: ce.version }) : (authed ? slot : t("dl_need_auth")));
  } else {
    $("c-dl-toggle").style.display = up ? "none" : "flex";
    if (dl) { dl.disabled = !authed; if (!authed) dl.checked = false; }
    $("c-dl-label").textContent = authed ? t("dl_label") : t("dl_need_auth");
    $("c-install").disabled = false;
    $("c-slot").textContent = up ? "" : slot;
  }
  renderResult();
}
function renderResult() {
  const res = STATE.lastResult, el = $("c-result");
  if (!res) { el.className = "result"; el.innerHTML = ""; return; }
  const slotNote = res.slot ? t("fw_slot_note", { slot: res.slot }) : "";
  el.className = "result on";
  el.innerHTML = `<span class="r-ok">${esc(t("fw_result", { v: res.version }) + slotNote)}</span>`
    + `<span class="r-reboot"><b>${esc(t("fw_reboot"))}</b></span>`;
}
// The firmware cached for the CONNECTED model (one entry per model), or null. Classroom preloads
// the whole fleet, so the fleet-wide STATE.cache.version is null — the per-model entry is what
// lets us flash this device from cache without a re-download.
function cachedEntryForDevice() {
  const m = STATE.identity && STATE.identity.model;
  const es = (STATE.cache && STATE.cache.entries) || [];
  return m ? es.find(e => e.model === m) || null : null;
}
async function installFw() {
  const btn = $("c-install");
  const isReal = !STATE.identity.virtual;
  const ce = cachedEntryForDevice();
  const version = $("c-select").value;
  // The selected version is cached for THIS model → flash it with no account (classroom/offline).
  // renderCatalog pre-selects the cached version, so this is the one-click default.
  const cacheable = !!(ce && ce.version === version);
  let download, fromCache;
  if (isReal) {
    download = !cacheable; fromCache = cacheable;  // cache first; else official download (sign-in)
  } else {
    download = !!($("c-download") && $("c-download").checked && !$("c-download").disabled);
    fromCache = !download && cacheable;
  }
  const realConsequence = download || isReal;
  if (realConsequence) {
    if (!$("c-supervise").checked) { toast(t("supervise_need"), true); return; }
    if (!window.confirm(t("confirm_flash", { v: version }))) return;
  }
  btn.disabled = true; btn.textContent = fromCache ? t("installing_cache") : t("installing");
  $("c-meterwrap").className = "meterwrap on"; $("c-meter").className = "meter"; $("c-meter").style.width = "0";
  try {
    const meterP = runMeter($("c-meter"));
    const r = await post("/api/install/firmware",
      { version, from_cache: !!fromCache, download, channel: STATE.channel });
    await meterP;
    STATE.identity = await api("/api/identity"); STATE.catalog = await api("/api/catalog");
    STATE.lastResult = { version: r.verified_version || version, slot: r.target_slot };
    toast(t("fw_done", { v: r.verified_version || version,
      slot: r.target_slot ? t("fw_slot_b") : "", cache: r.from_cache ? t("fw_from_cache") : "" }));
    renderDeviceCard(); renderCatalog();
  } catch (e) {
    toast(t("fail", { msg: e.message }), true);
  } finally {
    btn.disabled = false; btn.textContent = t("install");
  }
}

// -- unified workshop (apps + scripts render identically) ----------------------
function wcfg(kind) {
  return kind === "apps"
    ? { device: STATE.apps.device, avail: STATE.apps.avail, capacity: STATE.apps.capacity,
        accept: ".nwa", chooseLabel: t("choose_nwa"), order: t("mem_order") }
    : { device: STATE.scripts.device, avail: STATE.scripts.avail, capacity: STATE.scripts.capacity,
        accept: ".py", chooseLabel: t("choose_py"), order: t("storage_order") };
}
const deviceList = (kind) => (kind === "apps" ? STATE.apps.device : STATE.scripts.device);
function initStage(kind) {
  STATE.stage[kind] = deviceList(kind).map(x => ({ ...x, onDevice: true, deleted: false }));
  STATE.hist[kind] = [];
}
function pushHist(kind) { STATE.hist[kind].push(clone(STATE.stage[kind])); }

// Write plan: the frozen prefix is the longest run of the target (kept items) still matching
// the device's memory order — nothing there is rewritten. After the first divergence every
// item is (re)written, so its order is the user's to arrange. Returns a per-slot status:
// "un" (frozen), "rw" (rewritten), "new" (added), "del" (staged for erase, kept visible).
function planFor(kind) {
  const device = deviceList(kind), dnames = device.map(d => d.name);
  const slots = STATE.stage[kind], target = slots.filter(s => !s.deleted);
  let frozen = 0;
  while (frozen < target.length && frozen < device.length
         && target[frozen].name === device[frozen].name) frozen++;
  const status = new Map();
  let ti = 0;
  for (const s of slots) {
    if (s.deleted) { status.set(s, "del"); continue; }
    status.set(s, ti < frozen ? "un" : (dnames.includes(s.name) ? "rw" : "new"));
    ti++;
  }
  let un = 0, rw = 0, nw = 0, unB = 0, rwB = 0, nwB = 0;
  for (const s of slots) {
    const b = s.size || 0, st = status.get(s);
    if (st === "un") { un++; unB += b; } else if (st === "rw") { rw++; rwB += b; }
    else if (st === "new") { nw++; nwB += b; }
  }
  const cap = wcfg(kind).capacity, usedB = unB + rwB + nwB, freeB = Math.max(0, cap - usedB);
  const dirty = target.map(s => s.name).join("\n") !== dnames.join("\n");
  return { frozen, status, un, rw, nw, unB, rwB, nwB, usedB, freeB, cap, dirty };
}
// Source glyphs (inline SVG, currentColor): online (remote URL) · cloud (NumWorks) · local (PC).
const ORIGIN_SVG = {
  online: `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><circle cx="8" cy="8" r="6"/><path d="M2 8h12M8 2c1.9 1.7 1.9 10.3 0 12M8 2c-1.9 1.7-1.9 10.3 0 12"/></svg>`,
  cloud: `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"><path d="M4.7 12.4h6.5a2.6 2.6 0 0 0 .4-5.2A3.5 3.5 0 0 0 4.9 6 2.55 2.55 0 0 0 4.7 12.4Z"/></svg>`,
  local: `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round" stroke-linecap="round"><rect x="2" y="3" width="12" height="7.5" rx="1"/><path d="M5.5 13.3h5M8 10.5v2.8"/></svg>`,
};
function originIcon(a) {
  const s = (a.source || "").toLowerCase();
  if (a.origin === "local" || s.includes("local") || s.includes("fichier")) return ORIGIN_SVG.local;
  if (s.includes("cloud")) return ORIGIN_SVG.cloud;
  return ORIGIN_SVG.online;
}
// Export-to-computer glyphs (inline SVG, currentColor): save (down-arrow into a tray) shown when
// the file is not yet local; have (drive + check) shown when a same-name, same-size copy already
// sits in the local library. Both states export on click.
const EXPORT_SVG = {
  save: `<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2.4v6.6"/><path d="M5.2 6.3 8 9.1l2.8-2.8"/><path d="M2.8 11.3v1.1a1.2 1.2 0 0 0 1.2 1.2h8a1.2 1.2 0 0 0 1.2-1.2v-1.1"/></svg>`,
  have: `<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3.4" width="12" height="7.4" rx="1"/><path d="M5.4 13.2h5.2M8 10.8v2.4"/><path d="M5.7 6.9 7.3 8.5 10.5 5.3"/></svg>`,
};
// The export button for an installed item. Two visuals via `s.local`, but the same click action —
// even "already local" re-exports (spec: always clickable). Only on-device items can be pulled off.
function exportBtn(kind, s) {
  const have = !!s.local;
  const tip = have ? t("export_pc_have") : t("export_pc");
  return `<button class="ib dl${have ? " have" : ""}" title="${tip}" aria-label="${tip} ${esc(s.name)}"
    onclick="exportItem('${kind}','${jsStr(s.name)}')">${have ? EXPORT_SVG.have : EXPORT_SVG.save}</button>`;
}
function slotIcon(kind, item) {
  const name = (typeof item === "string" ? item : item.name) || "?";
  const icon = typeof item === "object" && item ? item.icon : null;
  if (icon) return `<img class="ic" src="${icon}" alt="" width="32" height="32">`;  // real decoded .nwa icon
  return kind === "scripts" ? `<div class="ic py">py</div>`
    : `<div class="ic" style="background:${color(name)}">${esc(name[0].toUpperCase())}</div>`;
}
function onCalcRow(kind, s, p, mov) {
  const st = p.status.get(s), movable = st === "rw" || st === "new";
  const meta = kind === "scripts"
    ? `${fmtBytes(s.size)}${s.auto_import ? " · " + t("auto_import") : ""}`
    : `${fmtBytes(s.size)} · API ${s.api_level ?? 0}`;
  const tagKey = { un: "st_unchanged", rw: "st_rw", new: "st_new", del: "st_erased" }[st];
  // Export is a device→PC pull, so it is offered for every item actually on the calculator —
  // including ones staged for erase — but not for not-yet-written additions.
  const dl = s.onDevice ? exportBtn(kind, s) : "";
  let btns;
  if (st === "del") {
    btns = dl + `<button class="ib" title="${t("restore")}" aria-label="${t("restore")} ${esc(s.name)}"
      onclick="restoreSlot('${kind}','${jsStr(s.name)}')">↺</button>`;
  } else {
    let mv = "";
    if (movable) {
      const mi = mov.indexOf(s);
      mv = `<button class="ib" title="${t("up")}" ${mi <= 0 ? "disabled" : ""} onclick="moveSlot('${kind}','${jsStr(s.name)}',-1)">▲</button>
        <button class="ib" title="${t("down")}" ${mi >= mov.length - 1 ? "disabled" : ""} onclick="moveSlot('${kind}','${jsStr(s.name)}',1)">▼</button>`;
    }
    btns = dl + mv + `<button class="ib" title="${t("remove")}" aria-label="${t("remove")} ${esc(s.name)}"
      onclick="stageRemove('${kind}','${jsStr(s.name)}')">✕</button>`;
  }
  // Writable items are draggable; the drop handler keeps them within the writable region.
  const drag = movable
    ? ` draggable="true" ondragstart="dragStart('${kind}','${jsStr(s.name)}')" ondragend="dragEnd()"
        ondragover="event.preventDefault()" ondragenter="this.classList.add('drag-over')"
        ondragleave="this.classList.remove('drag-over')" ondrop="dropOn(event,'${kind}','${jsStr(s.name)}')"` : "";
  return `<div class="item oncalc st-${st}${movable ? " grab" : ""}"${drag}>${slotIcon(kind, s)}
    <div class="grow"><div class="nm">${esc(s.name)} <span class="tag ${st}">${t(tagKey)}</span></div>
      <div class="mt">${meta}</div></div>
    <div class="rowbtns">${btns}</div></div>`;
}
function availRow(kind, a) {
  const nm = a.name;
  const inStage = STATE.stage[kind].some(x => x.name === nm && !x.deleted);
  const bad = kind === "apps" && a.api_level && a.api_level > (STATE.apps.apiLevel || 0);
  const src = a.source || a.url || "";
  const meta = `${a.size ? fmtBytes(a.size) + " · " : ""}API ${a.api_level ?? 0}${src ? " · " + esc(src) : ""}`;
  return `<div class="item"><span class="origin" aria-hidden="true">${originIcon(a)}</span>${slotIcon(kind, a)}
    <div class="grow"><div class="nm">${esc(nm)}${bad ? ` <span class="mt bad">${t("incompatible", { n: a.api_level })}</span>` : ""}</div>
      <div class="mt">${meta}</div></div>
    <button class="ib add" ${inStage || bad ? "disabled" : ""} title="+" aria-label="${esc(nm)}"
      onclick="stageAdd('${kind}','${jsStr(nm)}')">+</button></div>`;
}
function workshopBody(kind) {
  const cfg = wcfg(kind), slots = STATE.stage[kind], p = planFor(kind);
  const target = slots.filter(s => !s.deleted);
  // Classroom prepares a fleet from local/remote sources, not a personal NumWorks-cloud account.
  let avail = cfg.avail;
  if (STATE.mode === "classroom") avail = avail.filter(a => !(a.source || "").toLowerCase().includes("cloud"));
  avail = [...avail].sort((a, b) => a.name.localeCompare(b.name));  // alphabetical order
  const pct = (b) => cfg.capacity ? Math.max(b > 0 ? 1.5 : 0, 100 * b / cfg.capacity) : (b > 0 ? 100 : 0);
  // Memory bar: ONE segment per item (2px gaps → a separator between EVERY item, even same
  // type), followed by the free tail.
  const seg = (b, cls) => `<span class="${cls}" style="width:${pct(b)}%"></span>`;
  const bar = `<div class="membar">${target.map(s => seg(s.size || 0, "seg-" + p.status.get(s))).join("")}`
    + `${seg(p.freeB, "seg-free")}</div>`;
  const legend = `<div class="legend">
    <span><i class="seg-un"></i>${t("leg_un")}</span><span><i class="seg-rw"></i>${t("leg_rw")}</span>
    <span><i class="seg-new"></i>${t("leg_new")}</span><span><i class="seg-free"></i>${t("leg_free")}</span></div>`;
  const head = `<div class="wkhead">
    <span>${t("used", { used: "<b>" + fmtBytes(p.usedB) + "</b>", total: fmtBytes(cfg.capacity) })}</span>
    <span>${t("free", { n: fmtBytes(p.freeB) })}</span></div>`;
  const warn = kind === "apps"
    ? `<p class="warn">⚠️ ${esc(t("apps_warn"))}</p>` : `<p class="warn">${esc(t("scripts_note"))}</p>`;
  const mov = slots.filter(s => ["rw", "new"].includes(p.status.get(s)));  // writable = reorderable
  const left = slots.length ? slots.map(s => onCalcRow(kind, s, p, mov)).join("")
    : `<p class="empty">${t("no_installed")}</p>`;
  // Drop zone: anchored at the BOTTOM of the LEFT column, always visible (outside the scroll area).
  const drop = `<div class="drop" ondragover="event.preventDefault();this.classList.add('drag-over')"
    ondragleave="this.classList.remove('drag-over')" ondrop="dropFiles(event,'${kind}')">
    <input id="${kind}-file" type="file" accept="${cfg.accept}" style="display:none"
      onchange="onLocalFile('${kind}',this)"><label for="${kind}-file">${cfg.chooseLabel}</label></div>`;
  const availList = avail.length ? avail.map(a => availRow(kind, a)).join("")
    : `<p class="empty">${t("no_compat")}</p>`;
  const cols = `<div class="cols2">
    <div class="wcol">
      <div class="colhead"><span class="sub-h">${t("on_calc")}</span><span class="cnt">${target.length}</span></div>
      <div class="sub-sub">${cfg.order}</div>
      <div class="wlist">${left}</div>${drop}</div>
    <div class="wcol">
      <div class="colhead"><span class="sub-h">${t("available")}</span><span class="cnt">${avail.length}</span></div>
      <div class="sub-sub">${t("src_clr")}</div>${warn}
      <div class="wlist">${availList}</div></div></div>`;
  const busy = !!STATE.busy[kind];  // a remote download is in flight → sweep items, lock actions
  const wplan = `<div class="wplan">
    <div class="stat"><b>${p.un}</b>${t("wp_unchanged")}</div>
    <div class="stat"><b>${p.rw + p.nw}</b>${t("wp_rewrite")}</div>
    <div class="stat"><b>${fmtBytes(p.freeB)}</b>${t("wp_free")}</div>
    <div class="spacer"></div>
    <button class="btn ghost sm" onclick="undoStage('${kind}')" ${(STATE.hist[kind].length && !busy) ? "" : "disabled"}>${t("undo")}</button>
    <button class="btn ghost sm" onclick="resetStage('${kind}')" ${(p.dirty && !busy) ? "" : "disabled"}>${t("reset")}</button>
    <button class="btn sm" onclick="commitStage('${kind}')" ${(p.dirty && !busy) ? "" : "disabled"}>${busy ? t("writing") : (p.dirty ? t("write") : t("nothing"))}</button>
  </div>`;
  return `<div class="wk${busy ? " wk-busy" : ""}">${head + bar + legend + cols + wplan}</div>`;
}
function renderWorkbench() {
  // Workshops follow the HARDWARE (QSPI apps region / Python storage), in both modes.
  const hasApps = STATE.apps && STATE.apps.hasRegion;
  const hasPy = STATE.scripts && STATE.scripts.hasScripts;
  $("apps-card").style.display = hasApps ? "" : "none";
  $("scripts-card").style.display = hasPy ? "" : "none";
  if (hasApps) $("apps-body").innerHTML = workshopBody("apps");
  if (hasPy) $("scripts-body").innerHTML = workshopBody("scripts");
}
async function stageAdd(kind, name) {
  const a = (kind === "apps" ? STATE.apps.avail : STATE.scripts.avail).find(x => x.name === name);
  if (!a || STATE.busy[kind] || STATE.stage[kind].some(x => x.name === name && !x.deleted)) return;
  const remote = kind === "apps" && /^https?:\/\//.test(a.url || "") && !a.url.includes("example.invalid");
  if (remote) {
    // Real app: download the .nwa server-side into memory (temporary). Items show a progress
    // sweep and "Write" is disabled until it lands.
    STATE.busy.apps = true;
    renderWorkbench();
    toast(t("downloading", { name }));
    try {
      // Stream through the local server so we get the REAL byte count -> exact progress bar.
      const resp = await fetch("/api/apps/download?url=" + encodeURIComponent(a.url));
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const total = +(resp.headers.get("Content-Length") || 0);
      const wk = $("apps-body").querySelector(".wk");
      if (total && wk) wk.classList.add("determinate");
      const reader = resp.body.getReader();
      const parts = []; let got = 0;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        parts.push(value); got += value.length;
        if (total && wk) wk.style.setProperty("--dlp", Math.round(100 * got / total) + "%");
      }
      const buf = new Uint8Array(got); let off = 0;
      for (const p of parts) { buf.set(p, off); off += p.length; }
      let bin = "";
      for (let i = 0; i < buf.length; i += 8192) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 8192));
      const b64 = btoa(bin);
      let icon = null;
      try { icon = (await post("/api/apps/inspect", { data_b64: b64 })).icon || null; } catch (e) { /* no icon */ }
      pushHist(kind);
      STATE.stage.apps.push({ name: a.name, api_level: a.api_level || 0, size: got, source: a.source,
        origin: "remote", onDevice: false, deleted: false, blob: b64, icon });
      toast(t("staged_add", { name }));
    } catch (e) {
      toast(t("fail", { msg: e.message }), true);
    } finally {
      STATE.busy.apps = false;
      renderWorkbench();
    }
    return;
  }
  pushHist(kind);
  STATE.stage[kind].push(kind === "apps"
    ? { name: a.name, api_level: a.api_level || 0, size: a.size || 0, source: a.source, onDevice: false, deleted: false }
    : { name: a.name, size: a.size || 0, auto_import: true, source: a.source, url: a.url, code: a.code || "", onDevice: false, deleted: false });
  renderWorkbench(); toast(t("staged_add", { name }));
}
// Pull an installed app/script off the device onto the computer. The server also drops a copy into
// the local library, so the button flips to "already on the computer" — flipped in place so an
// in-progress plan (staged adds/removes/reorders) is never reset.
async function exportItem(kind, name) {
  if (STATE.busy[kind]) return;  // a write/download is in flight — the workshop is locked
  try {
    const r = await post(kind === "apps" ? "/api/apps/export" : "/api/scripts/export", { name });
    let blob, filename;
    if (kind === "apps") {
      const bin = atob(r.data_b64 || "");
      const buf = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
      blob = new Blob([buf], { type: "application/octet-stream" });
      filename = r.filename || (name.endsWith(".nwa") ? name : name + ".nwa");
    } else {
      blob = new Blob([r.code || ""], { type: "text/x-python" });
      filename = r.filename || (name.endsWith(".py") ? name : name + ".py");
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = filename;
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(a.href);
    // It now sits in the local library → mark every copy of this item so the button turns green.
    deviceList(kind).forEach(x => { if (x.name === name) x.local = true; });
    STATE.stage[kind].forEach(x => { if (x.name === name) x.local = true; });
    renderWorkbench();
    toast(t("exported", { name }));
  } catch (e) {
    toast(t("fail", { msg: e.message }), true);
  }
}
// Erase: an on-device item stays VISIBLE (greyed, restorable) so undo is trivial; a not-yet-
// written staged item just drops out.
function stageRemove(kind, name) {
  const s = STATE.stage[kind].find(x => x.name === name && !x.deleted);
  if (!s) return;
  pushHist(kind);
  if (s.onDevice) s.deleted = true;
  else STATE.stage[kind] = STATE.stage[kind].filter(x => x !== s);
  renderWorkbench(); toast(t("staged_rm", { name }));
}
function restoreSlot(kind, name) {
  const s = STATE.stage[kind].find(x => x.name === name && x.deleted);
  if (!s) return;
  pushHist(kind);
  s.deleted = false;
  minimize(kind);  // restoring re-runs the planner to maximise the frozen (never-rewritten) prefix
  renderWorkbench(); toast(t("restored", { name }));
}
// Re-order the writable tail: swap a movable slot with its nearest movable neighbour (frozen
// and erased slots keep their place, so the frozen prefix is never disturbed).
function moveSlot(kind, name, dir) {
  const slots = STATE.stage[kind], p = planFor(kind);
  const movable = slots.map((s, i) => i).filter(i => ["rw", "new"].includes(p.status.get(slots[i])));
  const pos = slots.findIndex(s => s.name === name && !s.deleted), mp = movable.indexOf(pos);
  const np = mp + dir;
  if (mp < 0 || np < 0 || np >= movable.length) return;
  pushHist(kind);
  const j = movable[np];
  [slots[pos], slots[j]] = [slots[j], slots[pos]];
  renderWorkbench();
}
let DRAG = null;
function dragStart(kind, name) { DRAG = { kind, name }; }
function dragEnd() {
  DRAG = null;
  document.querySelectorAll(".item.drag-over").forEach(e => e.classList.remove("drag-over"));
}
// Drag-reorder within the writable region only: dropping onto a frozen/erased item is a no-op,
// so the never-rewritten prefix is preserved.
function dropOn(event, kind, targetName) {
  event.preventDefault();
  document.querySelectorAll(".item.drag-over").forEach(e => e.classList.remove("drag-over"));
  if (!DRAG || DRAG.kind !== kind || DRAG.name === targetName) return;
  const slots = STATE.stage[kind], p = planFor(kind);
  const to = slots.find(s => s.name === targetName && !s.deleted);
  if (!to || !["rw", "new"].includes(p.status.get(to))) return;
  const from = slots.findIndex(s => s.name === DRAG.name && !s.deleted);
  if (from < 0) return;
  pushHist(kind);
  const [it] = slots.splice(from, 1);
  slots.splice(slots.indexOf(to), 0, it);  // insert before the drop target
  DRAG = null;
  renderWorkbench();
}
// Minimise memory writes: put device items back in device order (kept + erased, in place) so
// the unchanged prefix is as long as possible; freshly-added items keep their order at the end.
function minimize(kind) {
  const device = deviceList(kind), slots = STATE.stage[kind];
  const byName = new Map(slots.map(s => [s.name, s]));
  const out = [], used = new Set();
  for (const d of device) { const s = byName.get(d.name); if (s) { out.push(s); used.add(s.name); } }
  for (const s of slots) if (!used.has(s.name)) out.push(s);
  STATE.stage[kind] = out;
}
function undoStage(kind) {
  if (!STATE.hist[kind].length) return;
  STATE.stage[kind] = STATE.hist[kind].pop();
  renderWorkbench();
}
function resetStage(kind) { initStage(kind); renderWorkbench(); toast(t("reset_done")); }
// Stage a local file (from the picker OR a drag-and-drop) directly into the plan — it is NEVER
// uploaded anywhere; the bytes stay in the browser until "Write". At most one reference per
// file: a name already in the plan is refused.
function handleFile(kind, f) {
  const ext = kind === "apps" ? ".nwa" : ".py";
  if (!f.name.toLowerCase().endsWith(ext)) { toast(t("wrong_ext", { ext }), true); return; }
  const base = f.name.replace(/\.(nwa|py)$/i, "");
  if (STATE.stage[kind].some(x => (x.name === f.name || x.name === base) && !x.deleted)) {
    toast(t("already_staged", { name: f.name }), true); return;
  }
  const reader = new FileReader();
  reader.onload = async () => {
    if (kind === "apps") {
      const b64 = reader.result.split(",")[1] || "";
      let icon = null;  // decode the real .nwa (ELF) icon server-side so it shows straight away
      try { icon = (await post("/api/apps/inspect", { data_b64: b64 })).icon || null; } catch (e) { /* no icon */ }
      pushHist(kind);
      STATE.stage.apps.push({ name: base, api_level: 0, size: f.size, source: t("src_local"),
        origin: "local", onDevice: false, deleted: false, blob: b64, icon });
    } else {
      pushHist(kind);
      STATE.stage.scripts.push({ name: f.name.endsWith(".py") ? f.name : f.name + ".py", size: f.size,
        auto_import: true, source: t("src_local"), origin: "local", onDevice: false, deleted: false, code: reader.result });
    }
    renderWorkbench(); toast(t("staged_add", { name: f.name }));
  };
  if (kind === "apps") reader.readAsDataURL(f); else reader.readAsText(f);
}
function onLocalFile(kind, input) {
  if (input.files[0]) handleFile(kind, input.files[0]);
  input.value = "";  // reset so the same file can be re-picked later (e.g. after removing it)
}
function dropFiles(event, kind) {
  event.preventDefault();
  if (event.currentTarget.classList) event.currentTarget.classList.remove("drag-over");
  for (const f of (event.dataTransfer && event.dataTransfer.files) || []) handleFile(kind, f);
}
async function refreshLists() {
  const installed = await api("/api/apps/installed").catch(() => ({ installed: [] }));
  STATE.apps.device = installed.installed || [];
  const sc = await api("/api/scripts").catch(() => ({ scripts: [] }));
  STATE.scripts.device = sc.scripts || [];
  initStage("apps"); initStage("scripts");
}
async function commitStage(kind) {
  if (STATE.busy[kind]) return;  // a write (or a remote download) is already in flight
  const slots = STATE.stage[kind], target = slots.filter(s => !s.deleted);
  const removed = slots.filter(s => s.onDevice && s.deleted).map(s => s.name);
  const added = target.filter(s => !s.onDevice);
  // Lock the workshop straight away: the "Write" button relabels to "Writing…" and disables,
  // the items sweep (wk-busy) — immediate feedback, and no parallel second commit.
  STATE.busy[kind] = true; renderWorkbench();
  try {
    if (kind === "apps") {
      for (const name of removed) await post("/api/apps/uninstall", { name });
      for (const a of added) {
        if (a.blob) await post("/api/apps/push", { filename: a.name.endsWith(".nwa") ? a.name : a.name + ".nwa", data_b64: a.blob });
        else await post("/api/apps/add", { name: a.name });
      }
      await post("/api/apps/reorder", { order: target.map(s => s.name) });  // arrange write order
    } else {
      // Scripts live in one SRAM store: rewrite it to exactly the target, in the chosen order.
      await post("/api/scripts/set", { scripts: target.map(s => (
        { name: s.name.replace(/\.py$/i, ""), code: s.code || ("# " + s.name + "\n"), auto_import: !!s.auto_import })) });
    }
    await refreshLists();
    toast(t("written_ok", { n: removed.length + added.length }));
  } catch (e) {
    toast(t("fail", { msg: e.message }), true);
  } finally {
    STATE.busy[kind] = false; renderWorkbench();
  }
}

async function quitApp() {
  try { await post("/api/quit"); } catch (e) { /* server drops the connection */ }
  document.body.innerHTML = `<div style="max-width:520px;margin:18vh auto;text-align:center;
    font-family:var(--sans);color:var(--muted);padding:0 20px">
    <div style="font-size:40px">🧮</div><p style="font-size:16px;margin-top:10px">${t("quit_done")}</p></div>`;
}

// Heartbeat: keep the local server alive while this tab is open.
setInterval(() => { fetch("/api/ping").catch(() => {}); }, 30000);

// Safety net: never let the browser navigate to / download a file dropped anywhere in the page
// (the drop zones read files themselves; this just kills the default "open the file" behaviour).
["dragover", "drop"].forEach(ev => window.addEventListener(ev, e => e.preventDefault()));

if (QS.get("lang") === "fr" || QS.get("lang") === "en") LANG = QS.get("lang");
const qth = QS.get("theme");
if (qth === "light" || qth === "dark") document.documentElement.dataset.theme = qth;
document.documentElement.lang = LANG;
load().catch(e => toast(t("error", { msg: e.message }), true));
