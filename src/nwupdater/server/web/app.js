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
  mode: "individual", channel: "stable", tab: "system", name: null, sources: null,
  apps: null, scripts: null, stage: { apps: [], scripts: [] }, hist: { apps: [], scripts: [] },
  // per-workshop op descriptor while busy (still truthy): false | {op:"write"} | {op:"download", name}
  busy: { apps: false, scripts: false },
  // classroom roster ("Parc"): the joined fleet register + the selected class filter
  // ("__all__" | "__unfiled__" | a class name), the multi-select set (keys), a pending
  // delete-class confirmation, and the class currently being renamed inline.
  roster: null, parcClass: "__all__", parcSel: [], parcConfirm: null, parcRenamingClass: null,
};
// Optional deep-link / reproducible-capture overrides (all are already user-settable prefs):
// ?lang=fr|en · ?theme=light|dark · ?mode=individual|classroom. They never auto-connect a device.
const QS = new URLSearchParams(location.search);
let SERIAL_SHOWN = false;  // the rail serial is blurred by default; the whole value toggles it

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

// -- inline icons (currentColor SVG) -------------------------------------------
const ACCOUNT_ICON = `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M13 13.5a5 5 0 0 0-10 0" stroke-linecap="round"/><circle cx="8" cy="5" r="2.6"/></svg>`;
const FLEET_ICON = `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"><rect x="2" y="4" width="12" height="8" rx="1.5"/><path d="M2 7h12"/></svg>`;
const CHECK_SM = `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3.5 8.5l3 3 6-6.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const SHIELD_SM = `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M8 1.8 2 4.3v3.4c0 3.4 2.5 5.6 6 6.5 3.5-.9 6-3.1 6-6.5V4.3L8 1.8Z"/><path d="M5.6 8 7.4 9.8 10.6 6.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const REFRESH_SM = `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 3v2.4h-2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
// Write = down-arrow INTO a tray (into the calculator).
const WRITE_SVG = `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2.4v6.2M5.4 6 8 8.6 10.6 6"/><rect x="2.8" y="10.6" width="10.4" height="3" rx="1"/></svg>`;
const PENCIL_SVG = `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M10.5 3 13 5.5 5.8 12.7 3 13.4l.7-2.8Z"/></svg>`;
const CHECK_ICON = `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3.5 8.5l3 3 6-6.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const DASH_ICON = `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M4 8h8" stroke-linecap="round"/></svg>`;
const DROP_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V4m0 0 4 4m-4-4L8 8"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/></svg>`;

// -- load / connection ---------------------------------------------------------
async function load() {
  const qm = QS.get("mode");
  STATE.mode = (qm === "individual" || qm === "classroom") ? qm : (localStorage.getItem("nwmode") || "individual");
  if (STATE.mode === "classroom") STATE.tab = "parc";  // the roster is the classroom's home
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
  STATE.name = await api("/api/device/name").catch(() => null);  // user calc name (local store)
  STATE.roster = await api("/api/roster").catch(() => null);  // classroom fleet register ("Parc")
  STATE.sources = null;  // lazily fetched for the Sources popover on first open
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
  STATE.catalog = STATE.cache = STATE.apps = STATE.scripts = STATE.name = STATE.sources = null;
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
  // toolbar + statusbar + tab labels (present regardless of connection)
  $("lang-fr").setAttribute("aria-pressed", LANG === "fr");
  $("lang-en").setAttribute("aria-pressed", LANG === "en");
  $("quit-btn").title = t("quit"); $("quit-btn").setAttribute("aria-label", t("quit"));
  $("mode-individual-label").textContent = t("mode_individual");
  $("mode-classroom-label").textContent = t("mode_classroom");
  $("tab-parc-label").textContent = t("parc");
  $("tab-system-label").textContent = t("tab_system");
  $("tab-apps-label").textContent = t("tab_apps");
  $("tab-scripts-label").textContent = t("tab_scripts");
  $("flash-title").textContent = t("flash");
  $("c-risk-label").textContent = t("risk");
  $("status-local").textContent = t("status_local");
  $("status-offline-label").textContent = t("offline_ready");
  $("status-disc").textContent = t("disc");
  $("status-learn").textContent = t("learn");
  $("src-pop-title").textContent = t("src_title");
  $("src-pop-foot").textContent = t("src_foot");
  renderModeButtons();
  const conn = !!(STATE.identity && STATE.identity.connected);
  $("window").dataset.conn = conn ? "1" : "0";
  renderRail();
  if (conn) { renderSystem(); renderWorkbench(); renderParc(); setTab(STATE.tab); }
  else renderNoDevMain();
}

function renderNoDevMain() {
  $("nodev-main").innerHTML = `<div class="ico" aria-hidden="true">🔌</div>
    <h3>${t("nodev_title")}</h3><p>${t("nodev_hint")}</p>
    <div class="row">
      <button class="btn" onclick="rescanDevice()">${t("rescan")}</button>
      <div class="demo-pick">
        <select id="demo-model" aria-label="${t("demo_model")}">${demoModelOptions("n0110")}</select>
        <button class="btn ghost" onclick="exploreDemo()">${t("demo_btn")}</button>
      </div>
    </div>
    <p class="hint" style="margin-top:14px"><span class="waitdot"></span>${t("nodev_wait")}</p>`;
}

function renderRail() {
  const el = $("rail"), i = STATE.identity;
  if (!i || !i.connected) {
    el.innerHTML = `<div class="rail-nodev"><div class="ico" aria-hidden="true">🔌</div>
      <p>${t("nodev_title")}</p></div>`;
    return;
  }
  const variant = variantOf(i.family), fc = variant === "graphing" ? "g" : "s";
  const name = STATE.name || { name: null, default: "calc " + (i.model || "").toUpperCase() };
  const regTip = i.has_external_apps ? t("region_present") : t("region_absent");
  const regIcon = i.has_external_apps
    ? `<span class="regok" title="${regTip}" aria-label="${regTip}">${CHECK_ICON}</span>`
    : `<span class="regno" title="${regTip}" aria-label="${regTip}">${DASH_ICON}</span>`;
  el.innerHTML = `
    <div class="calcname">
      <input class="cn-input" id="calc-name" type="text" value="${esc(name.name || "")}"
        placeholder="${esc(name.default)}" aria-label="${t("calc_name")}"
        onchange="saveDeviceName()" onblur="saveDeviceName()" onfocus="this.select()">
      <span class="cn-pencil" aria-hidden="true">${PENCIL_SVG}</span>
    </div>
    <div class="calc">${buildCalc(variant)}</div>
    <dl class="spec">
      <dt>${t("model")}</dt><dd>${esc(i.model)}${i.virtual ? ` <span class="tag imp">${t("demo_tag")}</span>` : ""}</dd>
      <dt>${t("family")}</dt><dd><span class="fam ${fc}">${t(fc === "g" ? "fam_g" : "fam_s")}</span></dd>
      <dt>MCU</dt><dd>${esc(i.mcu || "—")}</dd>
      <dt>${t("serial")}</dt>
      <dd><button class="serial${SERIAL_SHOWN ? "" : " blur"}" id="serial-btn" onclick="toggleSerial()"
        title="${t("serial_reveal")}" aria-label="${t("serial_reveal")}"><span class="val">${esc(i.serial_number || "—")}</span></button></dd>
      <dt>OS</dt><dd>Epsilon ${esc(i.os_version || "?")}</dd>
      <dt>${t("appsregion")}</dt><dd>${regIcon}</dd>
    </dl>
    ${i.virtual ? `<div class="demo-switch"><span>${t("demo_model")}</span>
      <select id="demo-model2" onchange="switchDemo(this.value)">${demoModelOptions(i.model)}</select></div>` : ""}
    <div class="rail-foot"><button class="btn ghost sm" onclick="disconnectDevice()">${t("dev_menu")}</button></div>`;
}

// -- tabs ----------------------------------------------------------------------
function setTab(tab) {
  STATE.tab = tab;
  ["parc", "system", "apps", "scripts"].forEach(k => {
    const tb = $("tab-" + k), pn = $("pane-" + k);
    if (tb) tb.setAttribute("aria-selected", k === tab);
    if (pn) pn.classList.toggle("on", k === tab);
  });
}
function renderTabs() {
  const hasApps = !!(STATE.apps && STATE.apps.hasRegion);
  const hasPy = !!(STATE.scripts && STATE.scripts.hasScripts);
  const cls = STATE.mode === "classroom";
  // The "Parc" (roster) tab is classroom-only — the fleet home. Workshops follow the HARDWARE
  // (QSPI apps region / Python storage) — hide the tab when absent.
  $("tab-parc").style.display = cls ? "" : "none";
  $("tab-apps").style.display = hasApps ? "" : "none";
  $("tab-scripts").style.display = hasPy ? "" : "none";
  $("tab-parc-cnt").textContent = (cls && STATE.roster) ? String(STATE.roster.total || 0) : "";
  $("tab-apps-cnt").textContent = hasApps ? String(STATE.apps.device.length) : "";
  $("tab-scripts-cnt").textContent = hasPy ? String(STATE.scripts.device.length) : "";
  // The "update available" signal is a pulsing dot on the System tab (not a text pill).
  const up = !!(STATE.catalog && STATE.catalog.up_to_date);
  $("updot").style.display = (STATE.catalog && !up) ? "block" : "none";
  if ((STATE.tab === "apps" && !hasApps) || (STATE.tab === "scripts" && !hasPy)
      || (STATE.tab === "parc" && !cls)) setTab("system");
}

// -- account & mode ------------------------------------------------------------
function renderModeButtons() {
  const authed = !!(STATE.auth && STATE.auth.authenticated);
  $("mode-individual").setAttribute("aria-pressed", STATE.mode === "individual");
  $("mode-classroom").setAttribute("aria-pressed", STATE.mode === "classroom");
  // Connection state = signed in: tint the Individual toggle green (a green dot shows when signed
  // in but Classroom is the active toggle). No separate header chip → no layout shift.
  $("mode-individual").classList.toggle("conn", authed);
}
function setMode(m) {
  STATE.mode = m; localStorage.setItem("nwmode", m);
  if (STATE.identity && STATE.identity.connected) {
    renderSystem(); renderWorkbench(); renderParc();
    // The roster is the classroom's home; leaving classroom drops off the (now hidden) Parc tab.
    if (m === "classroom") setTab("parc");
    else if (STATE.tab === "parc") setTab("system");
  } else renderModeButtons();
}
function renderSystem() {
  renderModeButtons();
  renderCatalog();
  const ind = STATE.mode === "individual";
  $("account-card").style.display = ind ? "" : "none";
  $("classroom-card").style.display = ind ? "none" : "";
  $("status-offline").style.display = ind ? "none" : "inline-flex";
  if (ind) renderAuth(); else renderCache();
}
function renderAuth() {
  const a = STATE.auth || {}, el = $("account-card");
  const head = `<h3>${ACCOUNT_ICON}<span>${t("account")}</span></h3>`;
  if (a.authenticated) {
    el.innerHTML = head + `<div class="acct-row">
        <span class="authok">${CHECK_SM}${t("auth_in", { d: a.expires_at || "?" })}</span>
        <button class="btn ghost sm" onclick="logoutAuth()">${t("auth_logout")}</button></div>
      <p class="muted acct-purpose">${t("acct_purpose")}</p>`;
  } else {
    const status = a.expired ? t("auth_expired") : t("auth_out");
    el.innerHTML = head + `<p class="muted" style="margin:0 0 9px">${status}</p>
      <div class="auth-row">
        <input id="auth-email" type="email" placeholder="${t("auth_email")}" autocomplete="username">
        <input id="auth-pw" type="password" placeholder="${t("auth_pw")}" autocomplete="current-password">
        <button class="btn sm" onclick="loginPassword()">${t("auth_login")}</button></div>
      <details class="auth-adv"><summary>${t("auth_adv")}</summary>
        <p class="muted">${t("auth_hint")}</p>
        <div class="auth-row">
          <input id="auth-token" type="password" placeholder="${t("auth_ph")}" autocomplete="off">
          <button class="btn ghost sm" onclick="loginToken()">${t("auth_save")}</button></div></details>
      <p class="muted acct-purpose">${t("acct_purpose")}</p>`;
  }
}
async function _applyLogin(payload) {
  STATE.auth = await post("/api/auth/login", payload);
  toast(t("auth_saved")); renderSystem(); renderWorkbench();
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
  try { STATE.auth = await post("/api/auth/logout"); toast(t("auth_gone")); renderSystem(); renderWorkbench(); }
  catch (e) { toast(t("fail", { msg: e.message }), true); }
}
function renderCache() {
  const el = $("classroom-card"); if (!el) return;
  const c = STATE.cache, entries = (c && c.entries) || [];
  const head = `<h3>${FLEET_ICON}<span>${t("fleet")}</span></h3>
    <div class="cls-head">
      <span class="offline">${SHIELD_SM}${t("offline_ready")}</span>
      <button class="btn ghost sm" onclick="updateCaches()">${REFRESH_SM}${t("update_caches")}</button></div>`;
  if (!entries.length) {
    el.innerHTML = head + `<p class="muted" style="margin:0">${t("cache_intro")}</p>`;
    return;
  }
  // Channel badge: beta stands out (imp), stable is muted (un) — so a cached pre-release is never
  // mistaken for a stable image at a glance.
  const chanTag = (e) => e.channel === "beta"
    ? ` <span class="tag imp">${t("chan_beta")}</span>` : ` <span class="tag un">${t("chan_stable")}</span>`;
  const rows = entries.map(e => `<div class="cacherow">
      <span>${esc(e.model.toUpperCase())} · Epsilon ${esc(e.version)}${chanTag(e)}${
        e.real ? "" : ` <span class="tag imp">${t("demo_tag")}</span>`}</span>
      <span class="sz">${fmtBytes(e.size)}</span></div>`).join("");
  el.innerHTML = head + rows + `<div class="cache-foot">
      <span class="muted">${t("cache_summary", { n: entries.length, d: c.expires_in_days ?? 30 })}</span>
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

// -- sources popover -----------------------------------------------------------
let SRC_BTN = null;
async function ensureSources() {
  if (!STATE.sources) {
    STATE.sources = await api("/api/sources").catch(() => ({ apps: [], scripts: [], dirs: {} }));
  }
  return STATE.sources;
}
function srcIcon(kind) {
  return kind === "cloud" ? ORIGIN_SVG.cloud : kind === "local" ? ORIGIN_SVG.local : ORIGIN_SVG.online;
}
function renderSourcesList(s) {
  const cls = STATE.mode === "classroom", rows = [];
  const add = (list, label) => (list || []).forEach(x => {
    if (cls && x.kind === "cloud") return;  // personal (cloud) sources are hidden in classroom
    rows.push(`<div class="srcline">${srcIcon(x.kind)}<span class="u">${esc(x.url || x.source || x.label)}</span>`
      + `<span class="k">${label}</span></div>`);
  });
  add(s.apps, t("tab_apps"));
  add(s.scripts, t("tab_scripts"));
  if (s.dirs) {
    if (s.dirs.apps) rows.push(`<div class="srcline">${ORIGIN_SVG.local}<span class="u">${esc(s.dirs.apps)}</span><span class="k">${t("tab_apps")}</span></div>`);
    if (s.dirs.scripts) rows.push(`<div class="srcline">${ORIGIN_SVG.local}<span class="u">${esc(s.dirs.scripts)}</span><span class="k">${t("tab_scripts")}</span></div>`);
  }
  $("src-pop-list").innerHTML = rows.join("") || `<div class="srcline"><span class="u muted">—</span></div>`;
}
async function toggleSources(kind, btn) {
  const pop = $("src-pop");
  if (pop.classList.contains("on") && SRC_BTN === btn) { pop.classList.remove("on"); SRC_BTN = null; return; }
  renderSourcesList(await ensureSources());
  const r = btn.getBoundingClientRect();
  pop.style.top = (r.bottom + window.scrollY + 8) + "px";
  pop.style.left = Math.min(r.left + window.scrollX, window.innerWidth - 372) + "px";
  pop.classList.add("on"); SRC_BTN = btn;
}
document.addEventListener("click", (e) => {
  const pop = $("src-pop");
  if (pop && pop.classList.contains("on") && !pop.contains(e.target) && !e.target.closest(".srcbtn")) {
    pop.classList.remove("on"); SRC_BTN = null;
  }
});

// -- calculator name (local store) ---------------------------------------------
async function saveDeviceName() {
  const inp = $("calc-name"); if (!inp) return;
  const val = inp.value.trim(), cur = (STATE.name && STATE.name.name) || "";
  if (val === cur) return;  // nothing changed since the last save
  try {
    const r = await post("/api/device/name", { name: val });
    STATE.name = { name: r.name, default: r.default };
    if (inp === document.activeElement) inp.value = r.name || "";
  } catch (e) { toast(t("fail", { msg: e.message }), true); }
}

// -- serial reveal -------------------------------------------------------------
function toggleSerial() {
  const b = $("serial-btn"); if (!b) return;
  SERIAL_SHOWN = !SERIAL_SHOWN;
  b.classList.toggle("blur", !SERIAL_SHOWN);
}

// -- disclaimer (moved to a slim status-bar line + details) --------------------
function showDisclaimer() {
  // The disclaimer i18n string carries <b> markup; extract its plain text via a detached
  // <template> (no regex sanitization, nothing is ever inserted into the live DOM).
  const tpl = document.createElement("template");
  tpl.innerHTML = t("disclaimer");
  window.alert(tpl.content.textContent || "");
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
  $("c-exam-warn").textContent = t("exam_warn");  // guide: cold-boot (RESET) after flashing keeps official status
  const up = c.up_to_date;
  $("updot").style.display = up ? "none" : "block";  // pulsing dot on the System tab
  const srcTag = c.source === "official"
    ? `<span class="tag un" style="margin-left:7px">${t("cat_official")}</span>`
    : `<span class="tag imp" style="margin-left:7px">${t("cat_sample")}</span>`;
  $("c-text").innerHTML = (up ? t("uptodate_txt", { v: esc(c.current) })
    : t("updates_txt", { cur: esc(c.current), n: c.updates.length })) + srcTag;
  $("c-row").style.display = up ? "none" : "flex";
  $("c-risk").style.display = up ? "none" : "flex";
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
  const authed = !!(STATE.auth && STATE.auth.authenticated);
  const dl = $("c-download");
  if (isReal) {
    $("c-dl-toggle").style.display = "none"; if (dl) dl.checked = true;
    // Enable when there's an update AND we can source an image: a cached one (no sign-in) or a
    // signed-in official download.
    $("c-install").disabled = up || (!cachedHit && !authed);
    // The atomic-slot note is gone; keep only the meaningful cache / sign-in hints.
    $("c-slot").textContent = up ? "" : (cachedHit ? t("slot_cache", { v: ce.version }) : (authed ? "" : t("dl_need_auth")));
  } else {
    $("c-dl-toggle").style.display = up ? "none" : "flex";
    if (dl) { dl.disabled = !authed; if (!authed) dl.checked = false; }
    $("c-dl-label").textContent = authed ? t("dl_label") : t("dl_need_auth");
    $("c-install").disabled = false;
    $("c-slot").textContent = "";
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
    // No standing supervision checkbox: fold the acknowledgment into the confirmation itself.
    if (!window.confirm(t("confirm_flash", { v: version }) + "\n\n" + t("supervise_label"))) return;
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
    renderRail(); renderCatalog(); renderTabs();
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
  online: `<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><circle cx="8" cy="8" r="6"/><path d="M2 8h12M8 2c1.9 1.7 1.9 10.3 0 12M8 2c-1.9 1.7-1.9 10.3 0 12"/></svg>`,
  cloud: `<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"><path d="M4.7 12.4h6.5a2.6 2.6 0 0 0 .4-5.2A3.5 3.5 0 0 0 4.9 6 2.55 2.55 0 0 0 4.7 12.4Z"/></svg>`,
  local: `<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round" stroke-linecap="round"><rect x="2" y="3" width="12" height="7.5" rx="1"/><path d="M5.5 13.3h5M8 10.5v2.8"/></svg>`,
};
function originIcon(a) {
  const s = (a.source || "").toLowerCase();
  if (a.origin === "local" || s.includes("local") || s.includes("fichier")) return ORIGIN_SVG.local;
  if (s.includes("cloud")) return ORIGIN_SVG.cloud;
  return ORIGIN_SVG.online;
}
// Export-to-computer glyphs (inline SVG, currentColor): save = UP-arrow out of a tray (upload to
// the PC — distinct from Write's down-arrow); have = drive + check (a same-name, same-size copy
// already sits in the local library). Both states export on click.
const EXPORT_SVG = {
  save: `<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M8 10.4V3.6M5.2 6.4 8 3.6l2.8 2.8"/><path d="M2.8 11.2v1.1a1.2 1.2 0 0 0 1.2 1.2h8a1.2 1.2 0 0 0 1.2-1.2v-1.1"/></svg>`,
  have: `<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3.4" width="12" height="7.4" rx="1"/><path d="M5.4 13.2h5.2M8 10.8v2.4"/><path d="M5.7 6.9 7.3 8.5 10.5 5.3"/></svg>`,
};
// The export button for an installed item. Two visuals via `s.local`, but the same click action —
// even "already local" re-exports (spec: always clickable). Only on-device items can be pulled off.
function exportBtn(kind, s) {
  const have = !!s.local;
  const tip = have ? t("export_pc_have") : t("export_pc");
  return `<button class="ib dl${have ? " have" : ""}" title="${tip}" aria-label="${tip} ${esc(s.name)}"
    onclick="exportItem('${kind}','${jsStr(s.name)}',this)">${have ? EXPORT_SVG.have : EXPORT_SVG.save}</button>`;
}
function slotIcon(kind, item) {
  const name = (typeof item === "string" ? item : item.name) || "?";
  const icon = typeof item === "object" && item ? item.icon : null;
  if (icon) return `<img class="ic" src="${icon}" alt="" width="28" height="28">`;  // real decoded .nwa icon
  return kind === "scripts" ? `<div class="ic py">py</div>`
    : `<div class="ic" style="background:${color(name)}">${esc(name[0].toUpperCase())}</div>`;
}
function onCalcRow(kind, s, p, mov, busy) {
  const st = p.status.get(s), movable = st === "rw" || st === "new";
  // During a write, only the slots actually being (re)written animate — rw (rewritten) and new
  // (added). Frozen "un" items and everything else stay still.
  const busyCard = !!(busy && busy.op === "write" && (st === "rw" || st === "new"));
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
  return `<div class="item oncalc st-${st}${movable ? " grab" : ""}${busyCard ? " busy" : ""}"${drag}>${slotIcon(kind, s)}
    <div class="grow"><div class="nm">${esc(s.name)} <span class="tag ${st}">${t(tagKey)}</span></div>
      <div class="mt">${meta}</div></div>
    <div class="rowbtns">${btns}</div></div>`;
}
function availRow(kind, a, busy) {
  const nm = a.name;
  // During a remote download, only the single item being fetched animates (its --dlp fill).
  const busyCard = !!(busy && busy.op === "download" && busy.name === nm);
  const inStage = STATE.stage[kind].some(x => x.name === nm && !x.deleted);
  const bad = kind === "apps" && a.api_level && a.api_level > (STATE.apps.apiLevel || 0);
  const src = a.source || a.url || "";
  const meta = `<span class="origin" aria-hidden="true">${originIcon(a)}</span>${a.size ? fmtBytes(a.size) + " · " : ""}API ${a.api_level ?? 0}${src ? " · " + esc(src) : ""}`;
  return `<div class="item${busyCard ? " busy" : ""}">${slotIcon(kind, a)}
    <div class="grow"><div class="nm">${esc(nm)}${bad ? ` <span class="mt bad">${t("incompatible", { n: a.api_level })}</span>` : ""}</div>
      <div class="mt">${meta}</div></div>
    <button class="ib add" ${inStage || bad ? "disabled" : ""} title="+" aria-label="${esc(nm)}"
      onclick="stageAdd('${kind}','${jsStr(nm)}')">+</button></div>`;
}
function workshopBody(kind) {
  const cfg = wcfg(kind), slots = STATE.stage[kind], p = planFor(kind);
  const busy = STATE.busy[kind];  // false | {op:"write"} | {op:"download",name} — truthy while busy
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
    <span class="wkhead-r"><span>${t("free", { n: fmtBytes(p.freeB) })}</span>
      <button class="srcbtn" onclick="toggleSources('${kind}',this)">${ORIGIN_SVG.online}${t("sources")}</button></span></div>`;
  const mov = slots.filter(s => ["rw", "new"].includes(p.status.get(s)));  // writable = reorderable
  const left = slots.length ? slots.map(s => onCalcRow(kind, s, p, mov, busy)).join("")
    : `<p class="empty">${t("no_installed")}</p>`;
  // Drop zone: taller, anchored at the BOTTOM of the LEFT column, always visible (outside scroll).
  const drop = `<div class="drop" ondragover="event.preventDefault();this.classList.add('drag-over')"
    ondragleave="this.classList.remove('drag-over')" ondrop="dropFiles(event,'${kind}')">${DROP_SVG}
    <span><b>${cfg.accept}</b> — <input id="${kind}-file" type="file" accept="${cfg.accept}" style="display:none"
      onchange="onLocalFile('${kind}',this)"><label for="${kind}-file">${cfg.chooseLabel}</label></span></div>`;
  const availList = avail.length ? avail.map(a => availRow(kind, a, busy)).join("")
    : `<p class="empty">${t("no_compat")}</p>`;
  const cols = `<div class="cols2">
    <div class="wcol">
      <div class="colhead"><span class="sub-h">${t("on_calc")}</span><span class="cnt">${target.length}</span></div>
      <div class="sub-sub">${cfg.order}</div>
      <div class="wlist">${left}</div>${drop}</div>
    <div class="wcol">
      <div class="colhead"><span class="sub-h">${t("available")}</span><span class="cnt">${avail.length}</span></div>
      <div class="sub-sub">${t("src_clr")}</div>
      <div class="wlist">${availList}</div></div></div>`;
  const writeLabel = busy ? t("writing") : WRITE_SVG + (p.dirty ? t("write") : t("nothing"));
  const wplan = `<div class="wplan">
    <div class="stat"><b>${p.un}</b>${t("wp_unchanged")}</div>
    <div class="stat"><b>${p.rw + p.nw}</b>${t("wp_rewrite")}</div>
    <div class="stat"><b>${fmtBytes(p.freeB)}</b>${t("wp_free")}</div>
    <div class="spacer"></div>
    <button class="btn ghost sm" onclick="undoStage('${kind}')" ${(STATE.hist[kind].length && !busy) ? "" : "disabled"}>${t("undo")}</button>
    <button class="btn ghost sm" onclick="resetStage('${kind}')" ${(p.dirty && !busy) ? "" : "disabled"}>${t("reset")}</button>
    <button class="btn sm" onclick="commitStage('${kind}')" ${(p.dirty && !busy) ? "" : "disabled"}>${writeLabel}</button>
  </div>`;
  return `<div class="wk${busy ? " wk-busy" : ""}">${head + bar + legend + cols + wplan}</div>`;
}
function renderWorkbench() {
  // Workshops follow the HARDWARE (QSPI apps region / Python storage), in both modes.
  renderTabs();
  const hasApps = STATE.apps && STATE.apps.hasRegion;
  const hasPy = STATE.scripts && STATE.scripts.hasScripts;
  if (hasApps) $("pane-apps").innerHTML = workshopBody("apps");
  if (hasPy) $("pane-scripts").innerHTML = workshopBody("scripts");
}

// -- roster ("Parc") — classroom-only, read-only in this phase ------------------
// Two panes: a classes rail (Toutes / Sans classe / each class, with counts) and a calculator
// table (type icon · name · known firmware + up-to-date chip · last scan). The serial stays the
// internal key server-side and is NEVER rendered here. Rename / move / delete / drag / multi-select
// are later phases; the render is structured so an actions column can drop in.
const CLASS_ALL = "__all__", CLASS_UNFILED = "__unfiled__";
function parcTypeCell(family) {
  const label = t(family === "scientifique" ? "fam_s" : "fam_g");
  const glyph = buildCalc({ variant: variantOf(family), mode: "icon" });
  return `<span class="pc-ic" title="${label}" role="img" aria-label="${label}">${glyph}</span>`;
}
// Locale-aware relative time (no extra i18n strings): "hier"/"yesterday", "il y a 3 j"/"3 d ago".
function fmtRelative(iso) {
  if (!iso) return "—";
  const then = Date.parse(iso);
  if (isNaN(then)) return "—";
  const sec = Math.round((then - Date.now()) / 1000), abs = Math.abs(sec);
  let unit = "second", val = sec;
  if (abs >= 86400) { unit = "day"; val = Math.round(sec / 86400); }
  else if (abs >= 3600) { unit = "hour"; val = Math.round(sec / 3600); }
  else if (abs >= 60) { unit = "minute"; val = Math.round(sec / 60); }
  try { return new Intl.RelativeTimeFormat(LANG, { numeric: "auto" }).format(val, unit); }
  catch (e) { return new Date(then).toLocaleDateString(LANG); }
}
function selectParcClass(id) { STATE.parcClass = id; STATE.parcConfirm = null; renderParc(); }
// Rows filtered for the currently-selected bucket (Toutes / Sans classe / a class).
function parcRows() {
  const r = STATE.roster; if (!r) return [];
  const sel = STATE.parcClass || CLASS_ALL, rows = r.calculators || [];
  if (sel === CLASS_UNFILED) return rows.filter(c => !c.class);
  if (sel !== CLASS_ALL) return rows.filter(c => c.class === sel);
  return rows;
}
// <option>s for a "Move to…" <select>: a disabled placeholder, "Sans classe", then each class.
function parcMoveOptions() {
  const opts = [`<option value="" disabled selected>${esc(t("roster_move_to"))}</option>`,
    `<option value="${CLASS_UNFILED}">${esc(t("roster_unfiled"))}</option>`];
  (STATE.roster.classes || []).forEach(c => opts.push(`<option value="${esc(c)}">${esc(c)}</option>`));
  return opts.join("");
}
// Interactive controls sit inside a draggable <tr>: stop mousedown so grabbing a control (to type
// / click) never starts a row drag, and mark them non-draggable.
const NODRAG = `draggable="false" onmousedown="event.stopPropagation()"`;
function renderParc() {
  const el = $("pane-parc"); if (!el) return;
  if (STATE.mode !== "classroom") { el.innerHTML = ""; return; }
  const r = STATE.roster;
  if (!r) { el.innerHTML = `<div class="parc-main"><p class="parc-empty">${t("roster_empty")}</p></div>`; return; }
  const sel = STATE.parcClass || CLASS_ALL;
  // -- classes rail: each real class is a drop target + gets rename/delete tools --------------
  const railBtn = (id, label, count, pressed, cls) => {
    if (cls && STATE.parcRenamingClass === cls) {  // inline rename: the button becomes an input
      return `<div class="clsedit"><input id="parc-clsedit" value="${esc(cls)}" aria-label="${t("roster_rename_class")}"
        onkeydown="if(event.key==='Enter')parcClassRenameCommit('${jsStr(cls)}',this);else if(event.key==='Escape')parcClassRenameCancel()"
        onblur="parcClassRenameCommit('${jsStr(cls)}',this)"></div>`;
    }
    const dnd = `ondragover="parcRailOver(event)" ondragleave="this.classList.remove('drop-hot')" ondrop="parcRailDrop(event,'${jsStr(id)}')"`;
    const tools = cls ? `<span class="cls-tools">
      <button class="ib xs" ${NODRAG} title="${t("roster_rename_class")}" aria-label="${t("roster_rename_class")} ${esc(cls)}" onclick="event.stopPropagation();parcClassRename('${jsStr(cls)}')">${PENCIL_SVG}</button>
      <button class="ib xs" ${NODRAG} title="${t("roster_delete")}" aria-label="${t("roster_delete")} ${esc(cls)}" onclick="event.stopPropagation();parcDeleteClass('${jsStr(cls)}')">✕</button></span>` : "";
    return `<button class="clsbtn" aria-pressed="${pressed}" ${dnd} onclick="selectParcClass('${jsStr(id)}')">
      <span class="nm">${esc(label)}</span><span class="cnt">${count}</span>${tools}</button>`;
  };
  let rail = `<h4>${t("roster_classes")}</h4>`;
  rail += railBtn(CLASS_ALL, t("roster_class_all"), r.total || 0, sel === CLASS_ALL, null);
  rail += railBtn(CLASS_UNFILED, t("roster_unfiled"), r.unfiled_count || 0, sel === CLASS_UNFILED, null);
  (r.classes || []).forEach(c => rail += railBtn(c, c, (r.counts && r.counts[c]) || 0, sel === c, c));
  rail += `<div class="cls-add">
    <input id="parc-newclass" type="text" placeholder="${esc(t("roster_new_class"))}" aria-label="${t("roster_add_class")}"
      onkeydown="if(event.key==='Enter')parcAddClass()">
    <button class="ib" title="${t("roster_add_class")}" aria-label="${t("roster_add_class")}" onclick="parcAddClass()">＋</button></div>`;
  if (STATE.parcConfirm) {
    const c = STATE.parcConfirm;
    rail += `<div class="cls-confirm" role="alertdialog" aria-label="${t("roster_delete")}">
      <p>${t("roster_delete_class_confirm", { c: esc(c.name), n: c.count })}</p>
      <div class="row"><button class="btn ghost sm" onclick="parcDeleteCancel()">${t("roster_cancel")}</button>
        <button class="btn sm danger" onclick="parcDeleteConfirm()">${t("roster_confirm")}</button></div></div>`;
  }
  // -- calculator table: checkbox · type · editable name · firmware · last scan · actions ------
  const rows = parcRows(), selKeys = new Set(STATE.parcSel || []);
  const nsel = rows.filter(c => selKeys.has(c.key)).length;
  let main = "";
  if (nsel) {
    main += `<div class="parc-bulk" role="region" aria-label="${t("roster_bulk_selected", { n: nsel })}">
      <span class="n">${t("roster_bulk_selected", { n: nsel })}</span>
      <select class="mv" aria-label="${t("roster_move_to")}" onchange="parcBulkMove(this)">${parcMoveOptions()}</select>
      <button class="btn ghost sm" onclick="parcBulkDelete()">${t("roster_delete")}</button></div>`;
  }
  if (!rows.length) {
    main += `<p class="parc-empty">${t(sel === CLASS_ALL ? "roster_empty" : "roster_empty_class")}</p>`;
  } else {
    const allSel = rows.every(c => selKeys.has(c.key));
    const head = `<thead><tr>
      <th class="pc-sel"><input type="checkbox" ${allSel ? "checked" : ""} aria-label="${t("roster_select_all")}" onchange="parcSelectAll(this.checked)"></th>
      <th class="pc-type">${t("roster_col_type")}</th><th>${t("roster_col_name")}</th>
      <th>${t("roster_known_fw")}</th><th>${t("roster_col_lastscan")}</th>
      <th class="pc-act">${t("roster_col_actions")}</th></tr></thead>`;
    const body = rows.map(c => {
      const i = r.calculators.indexOf(c), label = esc(c.name || c.default || ""), checked = selKeys.has(c.key);
      const fw = c.known_firmware ? "Epsilon " + esc(c.known_firmware) : "—";
      let chip = "";
      if (c.up_to_date === true) chip = `<span class="fwchip ok">${t("uptodate")}</span>`;
      else if (c.up_to_date === false) chip = `<span class="fwchip upd">${t("roster_update")}</span>`;
      // Handlers key on the ROW INDEX, never the calculator key: the serial lives INSIDE the key,
      // and must never reach the DOM (privacy, §6). The key is resolved from STATE.roster on action.
      return `<tr draggable="true"${checked ? ' class="sel"' : ""} ondragstart="parcDragStart(event,${i})" ondragend="parcDragEnd()">
        <td class="pc-sel"><input type="checkbox" ${checked ? "checked" : ""} ${NODRAG} aria-label="${label}" onchange="parcToggleSel(${i},this.checked)"></td>
        <td class="pc-type">${parcTypeCell(c.family)}</td>
        <td class="parc-nm"><input class="pnm" ${NODRAG} value="${esc(c.name || "")}" placeholder="${esc(c.default || "")}"
          aria-label="${t("roster_col_name")}" onkeydown="if(event.key==='Enter')this.blur()" onchange="parcRename(${i},this)"></td>
        <td><span class="fwcell">${fw}${chip}</span></td>
        <td class="parc-lastscan">${esc(fmtRelative(c.last_scan))}</td>
        <td class="pc-act">
          <select class="mv" ${NODRAG} aria-label="${t("roster_move_to")}" onchange="parcRowMove(${i},this)">${parcMoveOptions()}</select>
          <button class="ib" ${NODRAG} title="${t("roster_delete")}" aria-label="${t("roster_delete")} ${label}" onclick="parcRowDelete(${i})">✕</button></td></tr>`;
    }).join("");
    main += `<table class="parc-tbl">${head}<tbody>${body}</tbody></table>`;
  }
  el.innerHTML = `<aside class="parc-rail">${rail}</aside><div class="parc-main">${main}</div>`;
}

// -- roster mutations (Phase 2-3) — all go through the SSRF/CSRF-guarded local endpoints --------
const parcClassValue = (v) => (v === CLASS_UNFILED || !v ? null : v);
async function reloadRoster() {
  STATE.roster = await api("/api/roster").catch(() => STATE.roster);
  // Drop selections/pending state that no longer refer to existing rows.
  const live = new Set((STATE.roster && STATE.roster.calculators || []).map(c => c.key));
  STATE.parcSel = (STATE.parcSel || []).filter(k => live.has(k));
  renderTabs(); renderParc();
}
async function parcDo(fn, okMsg) {  // shared error/toast wrapper for a mutation
  try { const r = await fn(); await reloadRoster(); if (okMsg) toast(okMsg(r)); return r; }
  catch (e) { toast(t("fail", { msg: e.message }), true); }
}
// Resolve a row index back to its "model:serial" key (kept out of the DOM). Robust to a stale
// index after a concurrent reload: returns undefined, and the callers no-op.
const parcKey = (i) => ((STATE.roster && STATE.roster.calculators[i]) || {}).key;
function parcRename(i, inp) {
  const key = parcKey(i); if (!key) return;
  return parcDo(() => post("/api/roster/rename", { key, name: inp.value.trim() }), () => t("roster_renamed"));
}
function parcRowMove(i, sel) {
  const key = parcKey(i); if (!key) return;
  return parcDo(() => post("/api/roster/move", { keys: [key], class: parcClassValue(sel.value) }),
    r => t("roster_moved", { n: r.moved }));
}
function parcRowDelete(i) {
  const key = parcKey(i); if (!key) return;
  return parcDo(() => post("/api/roster/delete", { keys: [key] }), r => t("roster_deleted", { n: r.deleted }));
}
function parcToggleSel(i, on) {
  const key = parcKey(i); if (!key) return;
  const s = new Set(STATE.parcSel || []); on ? s.add(key) : s.delete(key); STATE.parcSel = [...s]; renderParc();
}
function parcSelectAll(on) {
  const s = new Set(STATE.parcSel || []);
  parcRows().forEach(c => on ? s.add(c.key) : s.delete(c.key));
  STATE.parcSel = [...s]; renderParc();
}
function parcBulkMove(sel) {
  const keys = STATE.parcSel || []; if (!keys.length) return;
  return parcDo(() => post("/api/roster/move", { keys, class: parcClassValue(sel.value) }),
    r => t("roster_moved", { n: r.moved }));
}
function parcBulkDelete() {
  const keys = STATE.parcSel || []; if (!keys.length) return;
  return parcDo(() => post("/api/roster/delete", { keys }), r => t("roster_deleted", { n: r.deleted }));
}
function parcAddClass() {
  const inp = $("parc-newclass"), name = (inp ? inp.value : "").trim(); if (!name) return;
  return parcDo(() => post("/api/roster/class/create", { name }), () => t("roster_class_saved"));
}
function parcClassRename(cls) {
  STATE.parcRenamingClass = cls; renderParc();
  const inp = $("parc-clsedit"); if (inp) { inp.focus(); inp.select(); }
}
function parcClassRenameCancel() { STATE.parcRenamingClass = null; renderParc(); }
async function parcClassRenameCommit(from, inp) {
  const to = inp.value.trim(); STATE.parcRenamingClass = null;
  if (!to || to === from) { renderParc(); return; }
  await parcDo(() => post("/api/roster/class/rename", { from, to }), () => t("roster_class_saved"));
}
async function parcDeleteClass(name) {
  try {
    const r = await post("/api/roster/class/delete", { name });
    if (r && r.needs_confirm) { STATE.parcConfirm = { name, count: r.count }; renderParc(); return; }
    await reloadRoster(); toast(t("roster_class_deleted"));
  } catch (e) { toast(t("fail", { msg: e.message }), true); }
}
function parcDeleteCancel() { STATE.parcConfirm = null; renderParc(); }
async function parcDeleteConfirm() {
  const c = STATE.parcConfirm; if (!c) return;
  STATE.parcConfirm = null;
  await parcDo(() => post("/api/roster/class/delete", { name: c.name, confirm: true }), () => t("roster_class_deleted"));
}

// -- drag-and-drop: drag one (or the whole selection) onto a rail bucket ------------------------
let PARCDRAG = null;
function parcDragStart(event, i) {
  const key = parcKey(i); if (!key) return;
  const s = new Set(STATE.parcSel || []);
  PARCDRAG = s.has(key) ? [...s] : [key];  // dragging a selected row moves the whole selection
  try { event.dataTransfer.effectAllowed = "move"; event.dataTransfer.setData("text/plain", ""); } catch (e) { /* jsdom */ }
}
function parcDragEnd() {
  PARCDRAG = null;
  document.querySelectorAll(".clsbtn.drop-hot").forEach(e => e.classList.remove("drop-hot"));
}
function parcRailOver(event) {
  if (!PARCDRAG) return;
  event.preventDefault();
  if (!reduced) event.currentTarget.classList.add("drop-hot");
}
function parcRailDrop(event, id) {
  event.preventDefault();
  event.currentTarget.classList.remove("drop-hot");
  const keys = PARCDRAG; PARCDRAG = null;
  if (!keys || !keys.length || id === CLASS_ALL) return;  // "Toutes" is a view, not a bucket
  return parcDo(() => post("/api/roster/move", { keys, class: parcClassValue(id) }),
    r => t("roster_moved", { n: r.moved }));
}
async function stageAdd(kind, name) {
  const a = (kind === "apps" ? STATE.apps.avail : STATE.scripts.avail).find(x => x.name === name);
  if (!a || STATE.busy[kind] || STATE.stage[kind].some(x => x.name === name && !x.deleted)) return;
  const remote = kind === "apps" && /^https?:\/\//.test(a.url || "") && !a.url.includes("example.invalid");
  if (remote) {
    // Real app: download the .nwa server-side into memory (temporary). ONLY this available item
    // shows the progress fill; "Write" is disabled until it lands.
    STATE.busy.apps = { op: "download", name };
    renderWorkbench();
    toast(t("downloading", { name }));
    try {
      // Stream through the local server so we get the REAL byte count -> exact progress bar.
      const resp = await fetch("/api/apps/download?url=" + encodeURIComponent(a.url));
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const total = +(resp.headers.get("Content-Length") || 0);
      const wk = $("pane-apps").querySelector(".wk");
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
// Pull an installed app/script off the device onto the computer. The row shows a RIGHT→LEFT
// progress fill (device→PC — the mirror of the write bar's left→right) while the request runs;
// the server also drops a copy into the local library, so the button flips to "already on the
// computer" — flipped in place so an in-progress plan (staged adds/removes/reorders) is never reset.
async function exportItem(kind, name, btn) {
  if (STATE.busy[kind]) return;  // a write/download is in flight — the workshop is locked
  const row = btn && btn.closest(".item");
  let sweep = null;
  if (row) {
    row.classList.add("exporting");
    if (reduced) row.style.setProperty("--exp", "100%");
    else {
      let p = 6; row.style.setProperty("--exp", p + "%");
      sweep = setInterval(() => { p = Math.min(92, p + 7); row.style.setProperty("--exp", p + "%"); }, 90);
    }
  }
  const clearSweep = () => { if (sweep) { clearInterval(sweep); sweep = null; } };
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
    clearSweep();
    if (row) row.style.setProperty("--exp", "100%");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = filename;
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(a.href);
    // It now sits in the local library → mark every copy of this item so the button turns green.
    deviceList(kind).forEach(x => { if (x.name === name) x.local = true; });
    STATE.stage[kind].forEach(x => { if (x.name === name) x.local = true; });
    renderWorkbench();
    toast(t("exported", { name }));
  } catch (e) {
    clearSweep();
    if (row) { row.classList.remove("exporting"); row.style.removeProperty("--exp"); }
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
  // the written items (rw/new) sweep (wk-busy) — immediate feedback, and no parallel second commit.
  STATE.busy[kind] = { op: "write" }; renderWorkbench();
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
