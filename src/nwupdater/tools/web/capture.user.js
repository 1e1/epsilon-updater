// ==UserScript==
// @name         nwupdater capture (NumWorks web features)
// @namespace    nwupdater
// @version      1.2
// @description  Capture CONTINUE de fetch/XHR/WebUSB sur *.numworks.com (+ iframes tierces) → serveur local. Le panneau (bas à droite) sert à poser des MARQUES (scénarios). Projet indépendant, non officiel.
// @match        *://*.numworks.com/*
// @match        *://*.gvt2.com/*
// @run-at       document-start
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @connect      127.0.0.1
// @connect      localhost
// ==/UserScript==
//
// IMPORTANT : « Installer nw-capture » sur la page locale = installation une seule fois.
// Le CHOIX DU SCÉNARIO se fait ensuite dans le panneau flottant EN BAS À DROITE, sur
// my.numworks.com (pas sur la page locale). Ce script s'injecte tout seul sur chaque page
// NumWorks et pousse les trames au serveur local (magasin durable → aucune perte entre pages).
(function () {
  "use strict";
  var PORT = 8766, BASE = "http://127.0.0.1:" + PORT;
  var w = (typeof unsafeWindow !== "undefined") ? unsafeWindow : window;
  var SCENARIOS = [
    ["idle", "— (repos)"], ["pair", "1. Appairage"], ["scripts-list", "2. Lister scripts"],
    ["scripts-read", "3. Lire un script"], ["scripts-edit", "4. Créer/pousser script"],
    ["apps-list", "5. Lister apps"], ["app-install", "6. Charger une app"],
    ["app-delete", "7. Supprimer une app"], ["updates-list", "8. Lister MAJ (ne pas appliquer)"],
    ["unpair", "9. Désappairage"], ["other", "Autre / exploration"],
  ];
  var MAX_BODY = 65536;
  var log = function (m) { try { console.log("[nwupdater] " + m); } catch (e) {} };

  function gv(k, d) { try { return GM_getValue(k, d); } catch (e) { return d; } }
  function sv(k, v) { try { GM_setValue(k, v); } catch (e) {} }
  function on() { return gv("nw_capturing", true); }
  function post(path, obj) {
    try {
      GM_xmlhttpRequest({ method: "POST", url: BASE + path,
        headers: { "Content-Type": "application/json" }, data: JSON.stringify(obj) });
    } catch (e) { /* serveur absent : on ignore */ }
  }
  function rec(kind, r) { if (on()) post("/rec", { kind: kind, rec: r }); }
  function hex(buf) {
    var b = buf instanceof ArrayBuffer ? new Uint8Array(buf)
          : (buf && buf.buffer) ? new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength)
          : new Uint8Array(0);
    var s = ""; for (var i = 0; i < b.length; i++) s += (b[i] < 16 ? "0" : "") + b[i].toString(16);
    return s;
  }
  async function sha256(buf) { try { return hex(await w.crypto.subtle.digest("SHA-256", buf)); } catch (e) { return null; } }
  function redact(t) {
    if (!t) return t;
    try {
      return t.replace(/([?&]?[\w\[\]]*(?:pass\w*|token|authenticity\w*|secret|otp)[\w\[\]]*=)[^&\s"]*/gi, "$1[REDACTED]")
              .replace(/("(?:\w*(?:pass\w*|token|secret|otp)\w*)"\s*:\s*)"[^"]*"/gi, '$1"[REDACTED]"');
    } catch (e) { return t; }
  }

  // ---- hooks (chacun isolé : une erreur ne doit jamais empêcher le panneau) ----
  function hookFetch() {
    var _fetch = w.fetch; if (!_fetch) return;
    w.fetch = async function (input, init) {
      var url = (typeof input === "string") ? input : (input && input.url) || String(input);
      var method = (init && init.method) || (input && input.method) || "GET";
      var reqBody = init && init.body ? String(init.body).slice(0, MAX_BODY) : null;
      var resp = await _fetch.apply(this, arguments);
      try {
        var buf = await resp.clone().arrayBuffer();
        var ct = resp.headers.get("content-type") || "";
        var body = (/json|text|xml|javascript|urlencoded/i.test(ct) && buf.byteLength <= MAX_BODY)
          ? redact(new TextDecoder("utf-8").decode(buf)) : null;
        rec("web", { method: method, url: url, status: resp.status, content_type: ct,
          resp_len: buf.byteLength, resp_sha256: await sha256(buf), resp_body: body, req_body: redact(reqBody) });
      } catch (e) { rec("web", { method: method, url: url, status: resp.status, note: "body?" }); }
      return resp;
    };
  }
  function hookXHR() {
    var P = w.XMLHttpRequest && w.XMLHttpRequest.prototype; if (!P) return;
    var _open = P.open, _send = P.send;
    P.open = function (m, u) { this.__nw = { method: m, url: u }; return _open.apply(this, arguments); };
    P.send = function (body) {
      var xhr = this, info = xhr.__nw || {};
      xhr.addEventListener("loadend", async function () {
        var text = null, len = 0, sha = null;
        try {
          if (xhr.responseType === "" || xhr.responseType === "text") {
            text = String(xhr.responseText || "").slice(0, MAX_BODY); len = text.length;
            sha = await sha256(new TextEncoder().encode(xhr.responseText || ""));
          } else if (xhr.response && xhr.response.byteLength != null) { len = xhr.response.byteLength; sha = await sha256(xhr.response); }
        } catch (e) {}
        rec("web", { method: info.method, url: info.url, status: xhr.status,
          resp_len: len, resp_sha256: sha, resp_body: redact(text), req_body: redact(body ? String(body).slice(0, MAX_BODY) : null) });
      });
      return _send.apply(this, arguments);
    };
  }
  function hookUSB() {
    function wrap(proto) {
      if (!proto || proto.__nw) return; proto.__nw = true;
      var cIn = proto.controlTransferIn, cOut = proto.controlTransferOut, tIn = proto.transferIn, tOut = proto.transferOut;
      if (cIn) proto.controlTransferIn = async function (s) { var r = await cIn.apply(this, arguments);
        rec("usb", { via: "control", dir: "in", request: s.request, value: s.value, index: s.index, requestType: s.requestType, len: r && r.data ? r.data.byteLength : 0, data: r && r.data ? hex(r.data) : "" }); return r; };
      if (cOut) proto.controlTransferOut = async function (s, data) { var r = await cOut.apply(this, arguments);
        rec("usb", { via: "control", dir: "out", request: s.request, value: s.value, index: s.index, requestType: s.requestType, len: data ? data.byteLength : 0, data: data ? hex(data) : "" }); return r; };
      if (tIn) proto.transferIn = async function (ep) { var r = await tIn.apply(this, arguments);
        rec("usb", { via: "bulk", dir: "in", endpoint: ep, len: r && r.data ? r.data.byteLength : 0, data: r && r.data ? hex(r.data) : "" }); return r; };
      if (tOut) proto.transferOut = async function (ep, data) { var r = await tOut.apply(this, arguments);
        rec("usb", { via: "bulk", dir: "out", endpoint: ep, len: data ? data.byteLength : 0, data: data ? hex(data) : "" }); return r; };
    }
    if (w.USBDevice) wrap(w.USBDevice.prototype);
    if (w.navigator && w.navigator.usb && w.navigator.usb.requestDevice) {
      var _req = w.navigator.usb.requestDevice;
      w.navigator.usb.requestDevice = async function () { var d = await _req.apply(this, arguments); if (d) wrap(Object.getPrototypeOf(d)); return d; };
    }
  }
  [["fetch", hookFetch], ["xhr", hookXHR], ["usb", hookUSB]].forEach(function (h) {
    try { h[1](); } catch (e) { log("hook " + h[0] + " échoué: " + e); }
  });
  log("hooks installés");

  // ---- Panneau (auto-réparant : réapparaît si la SPA le retire) ----
  function ensurePanel() {
    try {
      if (!document.body || document.getElementById("nw-cap-panel")) return;
      var scenario = gv("nw_scenario", "idle");
      var box = document.createElement("div");
      box.id = "nw-cap-panel";
      box.style.cssText = "position:fixed;z-index:2147483647;right:12px;bottom:12px;background:#1f2228;color:#eceef1;" +
        "font:13px/1.4 -apple-system,sans-serif;padding:10px 12px;border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.5);width:250px";
      var title = document.createElement("div"); title.textContent = "nwupdater · SCÉNARIO de capture"; title.style.fontWeight = "700";
      var state = document.createElement("div"); state.style.cssText = "margin:5px 0;color:#969aa2;font-size:12px"; state.textContent = "…";
      var sel = document.createElement("select"); sel.style.cssText = "width:100%;margin:4px 0;padding:6px;border-radius:8px;font-size:13px";
      SCENARIOS.forEach(function (s) { var o = document.createElement("option"); o.value = s[0]; o.textContent = s[1]; if (s[0] === scenario) o.selected = true; sel.appendChild(o); });
      sel.addEventListener("change", function () { sv("nw_scenario", sel.value); post("/mark", { scenario: sel.value }); log("scénario → " + sel.value); });
      var btn = document.createElement("button"); btn.style.cssText = "width:100%;padding:7px;border:0;border-radius:8px;cursor:pointer;font-weight:700";
      function paint() { var c = on(); btn.textContent = c ? "⏸ Pause capture" : "▶︎ Reprendre capture"; btn.style.background = c ? "#3fbd77" : "#e8930c"; }
      btn.addEventListener("click", function () { sv("nw_capturing", !on()); paint(); }); paint();
      box.appendChild(title); box.appendChild(state); box.appendChild(sel); box.appendChild(btn);
      document.body.appendChild(box);
      log("panneau affiché (bas à droite)");
      post("/mark", { scenario: scenario });
      setInterval(function () {
        try {
          GM_xmlhttpRequest({ method: "GET", url: BASE + "/state",
            onload: function (r) { try { var s = JSON.parse(r.responseText); state.textContent = s.web + " web · " + s.usb + " usb · « " + s.scenario + " »"; } catch (e) {} },
            onerror: function () { state.textContent = "serveur local injoignable — lance « nwupdater-capture serve »"; } });
        } catch (e) {}
      }, 3000);
    } catch (e) { log("panneau: " + e); }
  }
  // Panneau seulement sur numworks.com ; ailleurs (iframes tierces : gvt2, captcha…) on
  // capture sans afficher de panneau.
  var IS_NW = /(^|\.)numworks\.com$/i.test(location.hostname);
  if (IS_NW) {
    ensurePanel();
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ensurePanel);
    setInterval(ensurePanel, 1500);
  } else {
    log("hooks actifs (sans panneau) sur " + location.hostname);
  }
})();
