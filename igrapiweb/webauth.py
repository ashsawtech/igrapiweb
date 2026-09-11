"""Pure-web username/password login (instagram.com browser login, no mobile API); surfaces 2FA and checkpoints via callbacks."""
from __future__ import annotations
import base64
import os
import re
import struct
import time
import uuid
from typing import Callable, Dict, Optional

WEB_LOGIN_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36")
_IMPERSONATE = "chrome124"

def _make_session(proxy: Optional[str]):
    """Return a browser-TLS session (curl_cffi Chrome impersonation; plain requests gets flagged by JA3 fingerprinting)."""
    pr = {"https": proxy, "http": proxy} if proxy else None
    try:
        from curl_cffi import requests as creq
        return creq.Session(impersonate=_IMPERSONATE, proxies=pr), True
    except Exception:
        import requests
        s = requests.Session()
        s.proxies.update(pr or {})
        return s, False

def _cookie(s, name: str) -> str:
    try:
        v = s.cookies.get(name)
        return v or ""
    except Exception:
        return ""

def _cookies_dict(s) -> Dict:
    try:
        return s.cookies.get_dict()
    except Exception:
        try:
            return {c.name: c.value for c in s.cookies}
        except Exception:
            return {}
LOGIN_URL = "https://www.instagram.com/api/v1/web/accounts/login/ajax/"
TWOFA_URL = "https://www.instagram.com/api/v1/web/accounts/login/two_factor/"
LOGIN_PAGE = "https://www.instagram.com/accounts/login/"
SHARED_DATA = "https://www.instagram.com/data/shared_data/"

def _enc_password_v0(password: str) -> str:
    return "#PWD_INSTAGRAM_BROWSER:0:%d:%s" % (int(time.time()), password)

def _enc_password_v10(password: str, key_id: int, pub_key_hex: str) -> str:
    """Build the browser's v10 sealed-box enc_password (AES-256-GCM password, AES key sealed to the server X25519 key)."""
    from nacl.public import PublicKey, SealedBox
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    ts = str(int(time.time()))
    key = os.urandom(32)
    ct = AESGCM(key).encrypt(b"\x00" * 12, password.encode("utf-8"), ts.encode())
    enc, tag = ct[:-16], ct[-16:]
    sealed = SealedBox(PublicKey(bytes.fromhex(pub_key_hex))).encrypt(key)
    payload = bytes([1, int(key_id)]) + struct.pack("<H", len(sealed)) + sealed + tag + enc
    return "#PWD_INSTAGRAM_BROWSER:10:%s:%s" % (ts, base64.b64encode(payload).decode())

def _web_session_id() -> str:
    r = lambda: uuid.uuid4().hex[:6]
    return "%s:%s:%s" % (r(), r(), r())

def web_login(username: str, password: str, *, proxy: Optional[str] = None,
              twofa: Optional[Callable[[str], str]] = None, user_agent: str = WEB_LOGIN_UA) -> Dict:
    """Log in on the web; returns {ok, sessionid, user_id, cookies} or a dict flagging 2FA / checkpoint / error."""
    s, _browser_tls = _make_session(proxy)

    page = s.get(LOGIN_PAGE, headers={"User-Agent": user_agent}, timeout=30)
    csrf = _cookie(s, "csrftoken")
    key_id = pub_key = None
    try:
        enc = (s.get(SHARED_DATA, headers={"User-Agent": user_agent, "X-IG-App-ID": "936619743392459",
               "X-Requested-With": "XMLHttpRequest"}, timeout=30).json().get("encryption") or {})
        key_id, pub_key = enc.get("key_id"), enc.get("public_key")
        csrf = csrf or _cookie(s, "csrftoken")
    except Exception:
        pass
    if not csrf:
        m = re.search(r'"csrf_token":"([^"]+)"', page.text)
        csrf = m.group(1) if m else "missing"
    m = re.search(r'"rollout_hash":"([^"]+)"', page.text)
    ajax = m.group(1) if m else "1"

    if key_id and pub_key:
        try:
            enc_password = _enc_password_v10(password, int(key_id), pub_key)
        except Exception:
            enc_password = _enc_password_v0(password)
    else:
        enc_password = _enc_password_v0(password)

    h = {"User-Agent": user_agent, "X-IG-App-ID": "936619743392459", "X-ASBD-ID": "129477",
         "X-IG-WWW-Claim": "0", "X-CSRFToken": csrf, "X-Instagram-AJAX": ajax,
         "X-Web-Session-ID": _web_session_id(), "X-Requested-With": "XMLHttpRequest",
         "Content-Type": "application/x-www-form-urlencoded", "Accept": "*/*",
         "Origin": "https://www.instagram.com", "Referer": LOGIN_PAGE,
         "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}
    data = {"username": username, "enc_password": enc_password,
            "queryParams": "{}", "optIntoOneTap": "false", "trustedDeviceRecords": "{}"}
    r = s.post(LOGIN_URL, headers=h, data=data, timeout=30, allow_redirects=False)
    try:
        j = r.json()
    except Exception:
        return {"ok": False, "error": "non_json_%d" % r.status_code}

    if j.get("two_factor_required"):
        info = j.get("two_factor_info") or {}
        ident = info.get("two_factor_identifier") or ""
        if not twofa:
            return {"ok": False, "two_factor_required": True, "identifier": bool(ident)}
        r2 = s.post(TWOFA_URL, headers=h, timeout=30, allow_redirects=False,
                    data={"username": username, "verificationCode": str(twofa(ident)),
                          "identifier": ident, "queryParams": "{}"})
        try:
            j = r2.json()
        except Exception:
            return {"ok": False, "error": "2fa_non_json"}

    if j.get("authenticated"):
        return {"ok": True, "sessionid": _cookie(s, "sessionid"),
                "user_id": str(j.get("userId") or ""), "cookies": _cookies_dict(s)}
    if j.get("message") == "checkpoint_required" or j.get("checkpoint_url"):
        return {"ok": False, "checkpoint_required": True, "checkpoint_url": j.get("checkpoint_url")}
    if j.get("user") is False:
        return {"ok": False, "error": "unknown_user"}
    return {"ok": False, "error": j.get("message") or (("bad_password") if j.get("authenticated") is False else j)}
