"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

let STATE = { identity: null, catalog: null, apps: null, cache: null, auth: null, lastResult: null };
const APPCOLORS = ["#5a8fef","#f0a63a","#38b2ac","#ef6f6c","#9b7ede","#4bb76a","#e0607e"];

async function api(path, opts) {
  const r = await fetch(path, opts);
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
  return d;
}
function post(path, body) {
  return api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}
let TT;
function toast(msg, err) { $("toast-msg").textContent = msg; $("toast").className = "toast show" + (err ? " err" : "");
  clearTimeout(TT); TT = setTimeout(() => $("toast").className = "toast", 3600); }
function runMeter(m) { return new Promise(res => { if (reduced) { m.style.width = "100%"; m.classList.add("done"); return res(); }
  let p = 0; const it = setInterval(() => { p += Math.random()*16+7; if (p >= 100) { p = 100; clearInterval(it); m.style.width = "100%"; m.classList.add("done"); setTimeout(res, 180); } else m.style.width = p + "%"; }, 90); }); }

function setLang(l) { LANG = l; localStorage.setItem("nwlang", l); document.documentElement.lang = l; renderAll(); }
const variantOf = (fam) => fam === "graphique" ? "graphing" : "scientific";

async function load() {
  STATE.identity = await api("/api/identity");
  const [cat, apps, cache, auth] = await Promise.all([
    api("/api/catalog"), api("/api/apps"), api("/api/cache"), api("/api/auth")]);
  STATE.catalog = cat; STATE.apps = apps; STATE.cache = cache; STATE.auth = auth;
  renderAll();
}

function renderAll() {
  // language toggle state
  $("lang-fr").setAttribute("aria-pressed", LANG === "fr");
  $("lang-en").setAttribute("aria-pressed", LANG === "en");
  // static labels
  $("subtitle").textContent = t("subtitle");
  $("t-device").textContent = t("device"); $("t-model").textContent = t("model");
  $("t-family").textContent = t("family"); $("t-appsregion").textContent = t("appsregion");
  $("t-update").textContent = t("update"); $("t-apps").textContent = t("apps");
  $("quit-btn").textContent = t("quit");
  $("note-txt").innerHTML = t("note");
  $("disclaimer-txt").innerHTML = t("disclaimer");
  $("t-auth").textContent = t("auth");
  $("c-supervise-label").textContent = t("supervise_label");
  if (STATE.identity) { renderDevice(); renderAuth(); renderCatalog(); renderCache(); renderApps(); }
}

function renderAuth() {
  const a = STATE.auth || {}, b = $("auth-body");
  let status;
  if (a.authenticated) status = `<span class="auth-ok">${t("auth_in", { d: a.expires_at || "?" })}</span>`;
  else if (a.expired) status = `<span class="hint" style="margin:0">${t("auth_expired")}</span>`;
  else status = `<span class="hint" style="margin:0">${t("auth_out")}</span>`;
  if (a.authenticated) {
    b.innerHTML = `<div class="status">${status}</div>
      <div class="auth-row"><button class="btn ghost sm" onclick="logoutAuth()">${t("auth_logout")}</button></div>`;
  } else {
    b.innerHTML = `<div class="status">${status}</div>
      <div class="auth-row">
        <input id="auth-email" type="email" placeholder="${t("auth_email")}" autocomplete="username">
        <input id="auth-pw" type="password" placeholder="${t("auth_pw")}" autocomplete="current-password">
        <button class="btn sm" onclick="loginPassword()">${t("auth_login")}</button>
      </div>
      <p class="hint">${t("auth_pw_note")}</p>
      <details class="auth-adv">
        <summary>${t("auth_adv")}</summary>
        <p class="hint">${t("auth_hint")}</p>
        <div class="auth-row">
          <input id="auth-token" type="password" placeholder="${t("auth_ph")}" autocomplete="off">
          <button class="btn ghost sm" onclick="loginToken()">${t("auth_save")}</button>
        </div>
      </details>`;
  }
}

async function _applyLogin(payload) {
  STATE.auth = await post("/api/auth/login", payload);
  toast(t("auth_saved")); renderAuth(); renderCatalog();
}
async function loginPassword() {
  const email = ($("auth-email").value || "").trim(), pw = $("auth-pw").value || "";
  if (!email || !pw) return;
  try { await _applyLogin({ email, password: pw }); }
  catch (e) { toast(t("fail", { msg: e.message }), true); }
}
async function loginToken() {
  const token = ($("auth-token").value || "").trim();
  if (!token) return;
  try { await _applyLogin({ token }); }
  catch (e) { toast(t("fail", { msg: e.message }), true); }
}
async function logoutAuth() {
  try {
    STATE.auth = await post("/api/auth/logout", {});
    toast(t("auth_gone")); renderAuth(); renderCatalog();
  } catch (e) { toast(t("fail", { msg: e.message }), true); }
}

function renderDevice() {
  const i = STATE.identity, variant = variantOf(i.family);
  $("calc-slot").innerHTML = buildCalc(variant);
  $("d-model").innerHTML = esc(i.model)
    + (i.virtual ? ` <span class="pill-demo">${t("demo_pill")}</span>` : "");
  const famClass = variant === "graphing" ? "g" : "s";
  $("d-fam").innerHTML = `<span class="fam ${famClass}">${t(famClass === "g" ? "fam_g" : "fam_s")}</span>`;
  $("d-mcu").textContent = i.mcu || "—";
  $("d-os").textContent = "Epsilon " + (i.os_version || "?");
  $("d-bcd").textContent = i.bcd_device;
  $("d-apps").textContent = i.has_external_apps ? t("region_present") : t("region_absent");
  // In demo mode be explicit that NO real calculator is attached (avoids "is it really detected?").
  $("d-hint").textContent = i.virtual
    ? t("demo_hint")
    : t("dfu_hint", { transport: t("transport_real") });
}

function renderCatalog() {
  const c = STATE.catalog;
  const up = c.up_to_date;
  $("c-badge").className = "badge " + (up ? "ok" : "up");
  $("c-badge").textContent = up ? t("uptodate") : t("update_avail");
  $("c-text").textContent = up ? t("uptodate_txt", { v: c.current })
    : t("updates_txt", { cur: c.current, n: c.updates.length });
  $("c-row").style.display = up ? "none" : "flex";
  $("c-select").innerHTML = c.updates.map((u, idx) =>
    `<option value="${esc(u.version)}">${esc(u.version)}${idx === 0 ? " — " + t("latest_opt") : ""}</option>`).join("");
  $("c-meterwrap").className = "meterwrap"; $("c-meter").className = "meter"; $("c-meter").style.width = "0";
  $("c-install").textContent = t("install");
  // The "written to the inactive slot…" hint only makes sense when an install is offered.
  const slot = STATE.identity.has_external_apps ? t("slot_ab", { slot: "B" }) : t("slot_single");
  const authed = !!(STATE.auth && STATE.auth.authenticated);
  const isReal = STATE.identity && !STATE.identity.virtual;
  const dl = $("c-download");
  if (isReal) {
    // Real calculator → official firmware is the ONLY valid choice (a demo image won't boot);
    // no checkbox, and installing requires being signed in.
    $("c-dl-toggle").style.display = "none";
    if (dl) dl.checked = true;
    $("c-install").disabled = up || !authed;
    $("c-slot").textContent = up ? "" : (authed ? slot : t("dl_need_auth"));
  } else {
    // Demo (virtual device) → demo image by default; real firmware optional once signed in.
    $("c-dl-toggle").style.display = up ? "none" : "inline-flex";
    if (dl) { dl.disabled = !authed; if (!authed) dl.checked = false; }
    $("c-dl-label").textContent = authed ? t("dl_label") : t("dl_need_auth");
    $("c-install").disabled = false;
    $("c-slot").textContent = up ? "" : slot;
  }
  renderResult();
}

// Persistent outcome of the last flash: what was written, that a reboot is required to run
// it (flashing the inactive slot doesn't switch the running OS), and a one-click boot action.
function renderResult() {
  const res = STATE.lastResult, el = $("c-result");
  if (!res) { el.className = "result"; el.innerHTML = ""; return; }
  const slotNote = res.slot ? t("fw_slot_note", { slot: res.slot }) : "";
  const rebootKey = (STATE.identity && STATE.identity.virtual) ? "fw_reboot_demo" : "fw_reboot";
  let html = `<span class="r-ok">${esc(t("fw_result", { v: res.version }) + slotNote)}</span>`
    + `<span class="r-reboot"><b>${esc(t(rebootKey))}</b></span>`;
  if (res.boot) html += `<div style="margin-top:9px"><button class="btn sm" onclick="bootNow()">${t("boot_now")}</button></div>`;
  el.className = "result on";
  el.innerHTML = html;
}
async function bootNow() {
  try {
    await post("/api/boot", {});
    toast(t((STATE.identity && STATE.identity.virtual) ? "boot_done_demo" : "boot_done"));
  } catch (e) { toast(t("fail", { msg: e.message }), true); }
}

function renderCache() {
  const c = STATE.cache, el = $("c-cache");
  const target = (STATE.catalog.updates[0] && STATE.catalog.updates[0].version) || STATE.catalog.current;
  if (c && c.version) {
    el.innerHTML = `<span class="chip">⭳ ${t("cached")}</span>
      <span class="ct">${t("cache_line", { v: esc(c.version), d: c.expires_in_days ?? 30 })}</span>
      <button class="btn ghost sm" onclick="clearCache()">${t("clear")}</button>`;
  } else {
    el.innerHTML = `<span class="ct"><b>${t("cache_mode")}</b> — ${t("cache_intro")}</span>
      <button class="btn ghost sm" onclick="preload('${esc(target)}')">${t("preload", { v: esc(target) })}</button>`;
  }
}

function renderApps() {
  const a = STATE.apps, b = $("apps-body");
  if (!a.has_external_apps) { b.innerHTML = `<p class="empty">${t("no_region")}</p>`; return; }
  let html = `<p class="hint" style="margin:0 0 4px;color:var(--accent-ink)">⚠️ ${esc(t("apps_warn"))}</p>
    <div class="sub-h">${t("local_file")}</div>
    <div class="drop">
      <input id="nwa-file" type="file" accept=".nwa" style="display:none" onchange="onLocal(this)">
      <label for="nwa-file">${t("choose_nwa")}</label>
      <div class="hint" style="margin-top:6px">${t("local_hint")}</div>
    </div>
    <div class="sub-h" title="${t("apps_api_note", { api: a.api_level })}">${t("compatible")}</div>`;
  const installed = new Set((a.installed || []).map(x => x.name));
  html += a.apps.length ? a.apps.map(app => appRow(app, installed.has(app.name))).join("")
    : `<p class="empty">${t("no_compat")}</p>`;
  b.innerHTML = html;
}
function appRow(app, done) {
  const color = APPCOLORS[app.name.charCodeAt(0) % APPCOLORS.length];
  const id = "app-" + app.name.replace(/\W/g, "");
  return `<div class="app"><div class="ic" style="background:${color}">${esc(app.name[0])}</div>
    <div class="grow"><div class="nm">${esc(app.name)} <span class="mt">v${esc(app.version)} · API ${app.api_level}</span></div>
    <div class="mt repo">${esc(app.source || "")}</div></div>
    <button class="btn ghost sm" id="${id}" ${done ? "disabled" : ""} onclick="installApp('${esc(app.name)}')">${done ? t("installed_mark") : t("install")}</button></div>`;
}

async function installFw() {
  const version = $("c-select").value, btn = $("c-install");
  const isReal = STATE.identity && !STATE.identity.virtual;
  // Real calculator → always the official firmware; demo → checkbox decides.
  const download = isReal
    ? true
    : !!($("c-download") && $("c-download").checked && !$("c-download").disabled);
  // Confirm before a REAL flash (real hardware or official download). Skipped in pure demo.
  const realConsequence = download || isReal;
  if (realConsequence) {
    if (!$("c-supervise").checked) { toast(t("supervise_need"), true); return; }
    if (!window.confirm(t("confirm_flash", { v: version }))) return;
  }
  const fromCache = !download && STATE.cache && STATE.cache.version === version;
  btn.disabled = true; btn.textContent = fromCache ? t("installing_cache") : t("installing");
  $("c-meterwrap").className = "meterwrap on"; $("c-meter").className = "meter"; $("c-meter").style.width = "0";
  try {
    const meterP = runMeter($("c-meter"));
    const r = await post("/api/install/firmware",
      { version, from_cache: !!fromCache, download, channel: "stable" });
    await meterP;
    STATE.identity = await api("/api/identity"); STATE.catalog = await api("/api/catalog");
    STATE.lastResult = { version: r.verified_version || version, slot: r.target_slot,
                         downloaded: !!r.downloaded, fromCache: !!r.from_cache,
                         boot: !!r.boot_address };
    toast(t("fw_done", { v: r.verified_version || version,
      slot: r.target_slot ? t("fw_slot_b") : "", cache: r.from_cache ? t("fw_from_cache") : "" }));
    renderDevice(); renderCatalog(); renderCache();
  } catch (e) {
    toast(t("fail", { msg: e.message }), true);
  } finally {
    btn.disabled = false; btn.textContent = t("install");
  }
}

async function preload(v) {
  try { STATE.cache = await post("/api/cache/preload", { version: v });
    toast(t("preloaded", { v })); renderCache(); }
  catch (e) { toast(t("fail", { msg: e.message }), true); }
}
async function clearCache() {
  try { STATE.cache = await post("/api/cache/clear", {}); toast(t("cache_cleared")); renderCache(); }
  catch (e) { toast(t("fail", { msg: e.message }), true); }
}

async function installApp(name) {
  const id = "app-" + name.replace(/\W/g, ""), btn = $(id);
  if (btn) { btn.disabled = true; btn.textContent = t("installing"); }
  try {
    if (!reduced) await new Promise(r => setTimeout(r, 500));
    await post("/api/install/app", { name });
    STATE.apps = await api("/api/apps");
    toast(t("installed_ok", { name })); renderApps();
  } catch (e) { toast(t("fail", { msg: e.message }), true); if (btn) { btn.disabled = false; btn.textContent = t("install"); } }
}

function onLocal(input) {
  const f = input.files[0]; if (!f) return;
  const reader = new FileReader();
  reader.onload = async () => {
    const b64 = reader.result.split(",")[1] || "";
    try {
      const r = await post("/api/install/app-local", { filename: f.name, data_b64: b64 });
      STATE.apps = await api("/api/apps");
      toast(t("installed_ok", { name: r.name })); renderApps();
    } catch (e) { toast(t("fail", { msg: e.message }), true); }
  };
  reader.readAsDataURL(f);
}

async function quitApp() {
  try { await post("/api/quit", {}); } catch (e) { /* server drops the connection */ }
  document.body.innerHTML = `<div style="max-width:520px;margin:18vh auto;text-align:center;
    font-family:var(--sans);color:var(--muted);padding:0 20px">
    <div style="font-size:40px">🧮</div><p style="font-size:16px;margin-top:10px">${t("quit_done")}</p></div>`;
}

// Heartbeat: while this tab is open, keep the app alive. When it closes, the pings stop
// and the server auto-quits after its idle timeout.
setInterval(() => { fetch("/api/ping").catch(() => {}); }, 30000);

document.documentElement.lang = LANG;
load().catch(e => toast(t("error", { msg: e.message }), true));
