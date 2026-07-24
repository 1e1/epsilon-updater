"""Recording HTTP transport for capture sessions.

Wraps the ``auth`` transport and logs every request/response so we can analyse the
Mac↔server (my.numworks.com) dialogue offline. **Redacts every secret** — password, CSRF
token, `Cookie`/`Set-Cookie` (remember_user_token) — and never stores firmware binaries
(only size + sha256) — so the dump is safe to share.
"""

from __future__ import annotations

import hashlib
import re
import urllib.parse

from .catalog.auth import Response

_REDACT = "[REDACTED]"
_SECRET_HEADERS = {"cookie", "authorization", "set-cookie"}
_SECRET_FORM_KEYS = {"user[password]", "authenticity_token", "utf8"}
_MAX_BODY = 4096  # bytes of a text body to keep; larger/binary bodies -> metadata only

# -- HTML form inspection (to document a POST endpoint from a captured page) -----------
_FORM_RE = re.compile(r"<form\b([^>]*)>(.*?)</form>", re.IGNORECASE | re.DOTALL)
_FIELD_RE = re.compile(r'<(?:input|select|textarea)\b[^>]*?\bname\s*=\s*"([^"]+)"', re.IGNORECASE)
_CAPTCHA_RE = re.compile(r"recaptcha|hcaptcha|turnstile", re.IGNORECASE)


def _attr(attrs: str, name: str) -> str | None:
    m = re.search(rf'\b{name}\s*=\s*"([^"]*)"', attrs, re.IGNORECASE)
    return m.group(1) if m else None


def inspect_forms(html: str) -> list[dict]:
    """Extract the shape of every ``<form>`` in ``html`` (action, method, field names,
    CAPTCHA presence). Pure/regex-based, no dependency — enough to document the POST a
    headless replay would need to reproduce (e.g. the device-enrollment form). We never
    submit anything; this only reads what the page already exposes."""
    forms = []
    for attrs, inner in _FORM_RE.findall(html or ""):
        forms.append(
            {
                "action": _attr(attrs, "action"),
                "method": (_attr(attrs, "method") or "GET").upper(),
                "fields": sorted(set(_FIELD_RE.findall(inner))),
                "captcha": bool(_CAPTCHA_RE.search(inner) or _CAPTCHA_RE.search(attrs)),
                "file_input": bool(re.search(r'type\s*=\s*"file"', inner, re.IGNORECASE)),
            }
        )
    return forms


def _redact_headers(headers) -> dict:
    out = {}
    for k, v in (headers or {}).items():
        out[k] = _REDACT if k.lower() in _SECRET_HEADERS else v
    return out


def _summarize_request_body(data: bytes | None) -> dict | None:
    if not data:
        return None
    # Devise login is form-encoded: redact password/CSRF, keep field names.
    try:
        pairs = urllib.parse.parse_qsl(data.decode("utf-8"), keep_blank_values=True)
        if pairs:
            return {"form": {k: (_REDACT if k in _SECRET_FORM_KEYS else v) for k, v in pairs}}
    except (UnicodeDecodeError, ValueError):
        pass
    return {"bytes": len(data)}


def _summarize_response_body(body: bytes, content_type: str | None) -> dict:
    sha = hashlib.sha256(body).hexdigest()
    ct = (content_type or "").lower()
    is_text = any(t in ct for t in ("json", "text", "html", "xml")) or not ct
    info = {"size": len(body), "sha256": sha, "content_type": content_type}
    if is_text:
        text = body.decode("utf-8", "replace")
        if len(body) <= _MAX_BODY:
            info["text"] = text
        else:
            info["text_head"] = text[:_MAX_BODY]
            info["truncated"] = True
        # Document any HTML form on the page (e.g. the device-enrollment portal), even when
        # the body is truncated — this is what makes the capture reveal the POST endpoint.
        if "<form" in text.lower():
            info["forms"] = inspect_forms(text)
    else:
        info["binary"] = True  # e.g. the .dfu firmware — never stored, only size+sha256
    return info


class RecordingTransport:
    def __init__(self, inner):
        self._inner = inner
        self.transfers: list[dict] = []

    def open(
        self, method, url, *, headers=None, data=None, timeout=20.0, allow_redirects=False
    ) -> Response:
        resp = self._inner.open(
            method,
            url,
            headers=headers,
            data=data,
            timeout=timeout,
            allow_redirects=allow_redirects,
        )
        ct = resp.header("Content-Type")
        self.transfers.append(
            {
                "seq": len(self.transfers),
                "request": {
                    "method": method,
                    "url": url,
                    "headers": _redact_headers(headers),
                    "body": _summarize_request_body(data),
                },
                "response": {
                    "status": resp.status,
                    "headers": {
                        k: (_REDACT if k.lower() in _SECRET_HEADERS else v) for k, v in resp.headers
                    },
                    "body": _summarize_response_body(resp.body, ct),
                },
            }
        )
        return resp
