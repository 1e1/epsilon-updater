/* nwupdater — capture-hook.js  (projet indépendant, non officiel)
 *
 * Injecté dans https://my.numworks.com pour DÉCOUVRIR les fonctions web de la calculatrice.
 * Capture, dans le contexte de la page (donc HTTPS déjà déchiffré, sans proxy ni CA) :
 *   - WEB : window.fetch + XMLHttpRequest (méthode, URL, statut, corps texte, taille, sha256)
 *   - USB : navigator.usb (controlTransferIn/Out, transferIn/Out) — les trames WebUSB brutes
 * Chaque enregistrement est estampillé du SCÉNARIO courant (sélecteur flottant), pour obtenir
 * une carte d'API par fonctionnalité.
 *
 * Secrets : le hook ne peut PAS lire Cookie/Set-Cookie (httpOnly, en-têtes interdits à JS) ; on
 * caviarde en plus les champs de corps sensibles (password, token, authenticity_token).
 * Rien n'est envoyé ailleurs : "Télécharger" produit un capture.json local ; le mode "live"
 * (optionnel) POSTe vers http://127.0.0.1:<port> de l'exécutable de capture.
 */
(function () {
  "use strict";
  if (window.__nwCapture) { window.__nwCapture.toggle(); return; }

  var SCENARIOS = [
    ["idle", "— (repos)"], ["pair", "1. Appairage"], ["scripts-list", "2. Lister scripts"],
    ["scripts-read", "3. Lire un script"], ["scripts-edit", "4. Créer/pousser script"],
    ["apps-list", "5. Lister apps"], ["app-install", "6. Charger une app"],
    ["app-delete", "7. Supprimer une app"], ["updates-list", "8. Lister MAJ (ne pas appliquer)"],
    ["unpair", "9. Désappairage"], ["other", "Autre / exploration"],
  ];
  var MAX_BODY = 65536;                 // octets de corps texte conservés
  var REDACT_KEYS = /pass(word)?|token|authenticity|secret|otp/i;

  var store = { tool: "nwupdater-capture-hook", version: 1, started: Date.now(),
                markers: [], web: [], usb: [] };
  var scenario = "idle";
  var live = false, livePort = 8766;

  function now() { return Date.now() - store.started; }
  function hex(buf) {
    var b = buf instanceof ArrayBuffer ? new Uint8Array(buf)
          : buf && buf.buffer ? new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength)
          : new Uint8Array(0);
    var s = ""; for (var i = 0; i < b.length; i++) s += (b[i] < 16 ? "0" : "") + b[i].toString(16);
    return s;
  }
  async function sha256Hex(buf) {
    try { var h = await crypto.subtle.digest("SHA-256", buf);
      return hex(h); } catch (e) { return null; }
  }
  function redactBody(text) {
    if (!text) return text;
    // form-encoded or JSON: blank out sensitive values, keep field names/structure
    try {
      return text.replace(/([?&]?[\w\[\]]*(?:pass\w*|token|authenticity\w*|secret|otp)[\w\[\]]*=)[^&\s"]*/gi, "$1[REDACTED]")
                 .replace(/("(?:\w*(?:pass\w*|token|secret|otp)\w*)"\s*:\s*)"[^"]*"/gi, '$1"[REDACTED]"');
    } catch (e) { return text; }
  }
  function push(kind, rec) {
    rec.t = now(); rec.scenario = scenario; store[kind].push(rec);
    if (live) fetch("http://127.0.0.1:" + livePort + "/rec", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: kind, rec: rec }) }).catch(function () {});
    render();
  }

  /* ---- WEB: fetch ---- */
  var _fetch = window.fetch;
  window.fetch = async function (input, init) {
    var url = (typeof input === "string") ? input : (input && input.url) || String(input);
    var method = (init && init.method) || (input && input.method) || "GET";
    var reqBody = init && init.body ? String(init.body).slice(0, MAX_BODY) : null;
    var resp;
    try { resp = await _fetch.apply(this, arguments); }
    catch (e) { push("web", { method: method, url: url, error: String(e),
                              req_body: redactBody(reqBody) }); throw e; }
    try {
      var clone = resp.clone(); var buf = await clone.arrayBuffer();
      var ct = resp.headers.get("content-type") || "";
      var isText = /json|text|xml|javascript|urlencoded/i.test(ct) || buf.byteLength <= MAX_BODY;
      var body = null;
      if (/json|text|xml|javascript|urlencoded/i.test(ct) && buf.byteLength <= MAX_BODY)
        body = redactBody(new TextDecoder("utf-8").decode(buf));
      push("web", { method: method, url: url, status: resp.status,
        content_type: ct, resp_len: buf.byteLength, resp_sha256: await sha256Hex(buf),
        resp_body: body, req_body: redactBody(reqBody) });
    } catch (e) { push("web", { method: method, url: url, status: resp.status, note: "body?" }); }
    return resp;
  };

  /* ---- WEB: XMLHttpRequest ---- */
  var _open = XMLHttpRequest.prototype.open, _send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u) { this.__nw = { method: m, url: u }; return _open.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function (body) {
    var xhr = this, info = xhr.__nw || {};
    xhr.addEventListener("loadend", async function () {
      var text = null, len = 0, sha = null;
      try {
        if (xhr.responseType === "" || xhr.responseType === "text") {
          text = String(xhr.responseText || "").slice(0, MAX_BODY); len = text.length;
          sha = await sha256Hex(new TextEncoder().encode(xhr.responseText || ""));
        } else if (xhr.response && xhr.response.byteLength != null) {
          len = xhr.response.byteLength; sha = await sha256Hex(xhr.response);
        }
      } catch (e) {}
      push("web", { method: info.method, url: info.url, status: xhr.status,
        resp_len: len, resp_sha256: sha, resp_body: redactBody(text),
        req_body: redactBody(body ? String(body).slice(0, MAX_BODY) : null) });
    });
    return _send.apply(this, arguments);
  };

  /* ---- USB: navigator.usb (WebUSB) ---- */
  function wrapUsb(proto) {
    if (!proto || proto.__nwWrapped) return; proto.__nwWrapped = true;
    var cIn = proto.controlTransferIn, cOut = proto.controlTransferOut,
        tIn = proto.transferIn, tOut = proto.transferOut;
    if (cIn) proto.controlTransferIn = async function (setup, length) {
      var r = await cIn.apply(this, arguments);
      push("usb", { via: "control", dir: "in", request: setup.request, value: setup.value,
        index: setup.index, requestType: setup.requestType, len: r && r.data ? r.data.byteLength : 0,
        data: r && r.data ? hex(r.data) : "", status: r && r.status });
      return r;
    };
    if (cOut) proto.controlTransferOut = async function (setup, data) {
      var r = await cOut.apply(this, arguments);
      push("usb", { via: "control", dir: "out", request: setup.request, value: setup.value,
        index: setup.index, requestType: setup.requestType, len: data ? data.byteLength : 0,
        data: data ? hex(data) : "", status: r && r.status });
      return r;
    };
    if (tIn) proto.transferIn = async function (ep, length) {
      var r = await tIn.apply(this, arguments);
      push("usb", { via: "bulk", dir: "in", endpoint: ep, len: r && r.data ? r.data.byteLength : 0,
        data: r && r.data ? hex(r.data) : "" });
      return r;
    };
    if (tOut) proto.transferOut = async function (ep, data) {
      var r = await tOut.apply(this, arguments);
      push("usb", { via: "bulk", dir: "out", endpoint: ep, len: data ? data.byteLength : 0,
        data: data ? hex(data) : "" });
      return r;
    };
  }
  if (window.USBDevice) wrapUsb(window.USBDevice.prototype);
  if (navigator.usb) {
    var _req = navigator.usb.requestDevice;
    if (_req) navigator.usb.requestDevice = async function () {
      var d = await _req.apply(this, arguments);
      if (d) wrapUsb(Object.getPrototypeOf(d)); return d;
    };
  }

  /* ---- download / overlay ---- */
  function download() {
    var blob = new Blob([JSON.stringify(store)], { type: "application/json" });
    var a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = "capture.json"; a.click();
  }
  var box, counter;
  function render() {
    if (counter) counter.textContent = store.web.length + " web · " + store.usb.length + " usb";
  }
  function build() {
    box = document.createElement("div");
    box.style.cssText = "position:fixed;z-index:2147483647;right:12px;bottom:12px;background:#1f2228;" +
      "color:#eceef1;font:13px/1.4 -apple-system,sans-serif;padding:12px;border-radius:12px;" +
      "box-shadow:0 8px 30px rgba(0,0,0,.5);width:250px";
    var sel = document.createElement("select");
    sel.style.cssText = "width:100%;margin:6px 0;padding:6px;border-radius:8px";
    SCENARIOS.forEach(function (s) { var o = document.createElement("option"); o.value = s[0]; o.textContent = s[1]; sel.appendChild(o); });
    sel.onchange = function () { scenario = sel.value; store.markers.push({ t: now(), scenario: scenario }); };
    counter = document.createElement("div"); counter.style.cssText = "margin:6px 0;color:#969aa2";
    var dl = document.createElement("button"); dl.textContent = "⬇︎ Télécharger capture.json";
    dl.style.cssText = "width:100%;padding:8px;border:0;border-radius:8px;background:#f7b53d;font-weight:700;cursor:pointer";
    dl.onclick = download;
    var lv = document.createElement("label"); lv.style.cssText = "display:block;margin-top:8px;color:#969aa2;font-size:12px";
    var cb = document.createElement("input"); cb.type = "checkbox"; cb.onchange = function () { live = cb.checked; };
    lv.appendChild(cb); lv.appendChild(document.createTextNode(" live → 127.0.0.1:" + livePort));
    var title = document.createElement("div"); title.textContent = "nwupdater · capture"; title.style.fontWeight = "700";
    box.appendChild(title); box.appendChild(sel); box.appendChild(counter); box.appendChild(dl); box.appendChild(lv);
    document.body.appendChild(box); render();
  }
  window.__nwCapture = { store: store, download: download,
    toggle: function () { box.style.display = box.style.display === "none" ? "block" : "none"; } };
  build();
  console.log("[nwupdater] capture-hook actif — choisis un scénario, joue-le, puis Télécharger.");
})();
