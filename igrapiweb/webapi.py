"""Instagram web private-API helper (www.instagram.com/api/v1/…): follow/profile/reel/story via web session cookie + X-IG-App-ID."""
from __future__ import annotations
from typing import Dict, Optional
import json as _json
from .protocol import IG_WEB_APP_ID, _GQL_UA

WEB_BASE = "https://www.instagram.com"
_SESSIONS: dict = {}

def _session(cookies: Dict[str, str], proxy: Optional[str]):
    """Persistent requests.Session per web account (keyed by sessionid) so server-set cookies accumulate across calls."""
    key = cookies.get("sessionid", "")[:24]
    s = _SESSIONS.get(key)
    if s is None:
        import requests
        s = requests.Session()
        if proxy:
            s.proxies = {"https": proxy, "http": proxy}
        for k, v in _jar(cookies).items():
            s.cookies.set(k, v, domain=".instagram.com")
        _SESSIONS[key] = s
    return s

def _jar(cookies: Dict[str, str]) -> Dict[str, str]:
    return {k: v for k, v in cookies.items() if v and k in
            ("sessionid", "ds_user_id", "csrftoken", "mid", "ig_did", "rur", "shbid", "shbts")}

def ensure_csrftoken(cookies: Dict[str, str], proxy: Optional[str] = None, user_agent: str = _GQL_UA) -> str:
    """Return a csrftoken for POST auth, scraping and caching one into `cookies` if the session lacks it."""
    if cookies.get("csrftoken"):
        return cookies["csrftoken"]
    import requests, re
    r = requests.get(WEB_BASE + "/", headers={"User-Agent": user_agent},
                     cookies=_jar(cookies), proxies=({"https": proxy, "http": proxy} if proxy else None),
                     timeout=30, allow_redirects=False)
    tok = r.cookies.get("csrftoken")
    if not tok:
        m = re.search(r'"csrf_token":"([^"]+)"', r.text)
        tok = m.group(1) if m else ""
    if tok:
        cookies["csrftoken"] = tok
    return tok or ""

def ensure_claim(cookies: Dict[str, str], proxy: Optional[str] = None, user_agent: str = _GQL_UA) -> str:
    """Fetch and cache the X-IG-WWW-Claim once (from the friendships/show x-ig-set-www-claim response header)."""
    if cookies.get("_wwwclaim"):
        return cookies["_wwwclaim"]
    me = cookies.get("ds_user_id") or "25025320"
    try:
        s = _session(cookies, proxy)
        r = s.get(WEB_BASE + "/api/v1/friendships/show/%s/" % me,
                  headers={"User-Agent": user_agent, "X-IG-App-ID": str(IG_WEB_APP_ID),
                           "X-IG-WWW-Claim": "0", "X-Requested-With": "XMLHttpRequest",
                           "Referer": WEB_BASE + "/"}, timeout=30)
        c = r.headers.get("x-ig-set-www-claim")
        if c:
            cookies["_wwwclaim"] = c
        if s.cookies.get("csrftoken"):
            cookies["csrftoken"] = s.cookies.get("csrftoken")
    except Exception:
        pass
    return cookies.get("_wwwclaim", "")

def web_api(cookies: Dict[str, str], path: str, *, method: str = "GET", params: Optional[dict] = None,
            data: Optional[dict] = None, referer: str = WEB_BASE + "/", proxy: Optional[str] = None,
            user_agent: str = _GQL_UA, timeout: int = 30, _retry: bool = False) -> dict:
    """Call a web private-API endpoint (`path` starts /api/v1/...); GET uses `params`, POST uses `data`. Returns parsed JSON."""
    import requests
    ensure_claim(cookies, proxy=proxy, user_agent=user_agent)
    h = {"User-Agent": user_agent, "X-IG-App-ID": str(IG_WEB_APP_ID), "Referer": referer,
         "X-Requested-With": "XMLHttpRequest", "Origin": WEB_BASE, "X-ASBD-ID": "359341",
         "X-IG-WWW-Claim": cookies.get("_wwwclaim") or "0"}
    if cookies.get("csrftoken"):
        h["X-CSRFToken"] = cookies["csrftoken"]
    if method.upper() == "POST":
        h["Content-Type"] = "application/x-www-form-urlencoded"
    url = WEB_BASE + path
    pr = ({"https": proxy, "http": proxy} if proxy else None)

    if method.upper() == "POST":
        r = requests.post(url, headers=h, cookies=_jar(cookies), data=(data or {}), proxies=pr,
                          timeout=timeout, allow_redirects=False)
    else:
        r = requests.get(url, headers=h, cookies=_jar(cookies), params=(params or {}), proxies=pr,
                         timeout=timeout, allow_redirects=False)
    if r.status_code in (301, 302, 303, 307, 308):
        return {"_status": r.status_code, "_redirect": r.headers.get("location", "")[:80],
                "_error": "auth_or_rate_wall"}
    had_claim = bool(cookies.get("_wwwclaim"))
    claim = r.headers.get("x-ig-set-www-claim")
    if claim:
        cookies["_wwwclaim"] = claim
    if r.cookies.get("csrftoken"):
        cookies["csrftoken"] = r.cookies.get("csrftoken")
    txt = r.text
    if txt.startswith("for (;;);"):
        txt = txt[len("for (;;);"):]
    try:
        return _json.loads(txt)
    except Exception:

        if not had_claim and cookies.get("_wwwclaim") and not _retry:
            return web_api(cookies, path, method=method, params=params, data=data,
                           referer=referer, proxy=proxy, user_agent=user_agent, timeout=timeout, _retry=True)
        return {"_status": r.status_code, "_body": r.text[:400]}

def rupload_photo(cookies: Dict[str, str], image_bytes: bytes, *, proxy: Optional[str] = None,
                  user_agent: str = _GQL_UA) -> Optional[str]:
    """Upload a JPEG to the web resumable uploader → upload_id (for change_profile_picture / story configure)."""
    import requests, time as _t, random, json
    upload_id = str(int(_t.time() * 1000))
    name = "%s_0_%d" % (upload_id, random.randint(1000000000, 9999999999))
    params = {"media_type": "1", "upload_id": upload_id, "image_compression":
              json.dumps({"lib_name": "moz-jpeg", "lib_version": "3.1.m", "quality": "80"})}
    h = {"User-Agent": user_agent, "X-IG-App-ID": str(IG_WEB_APP_ID),
         "X-Instagram-Rupload-Params": json.dumps(params), "X-Entity-Name": name,
         "X-Entity-Length": str(len(image_bytes)), "Offset": "0",
         "X-Entity-Type": "image/jpeg", "Content-Type": "application/octet-stream",
         "X-IG-WWW-Claim": ensure_claim(cookies, proxy=proxy, user_agent=user_agent) or "0"}
    if cookies.get("csrftoken"):
        h["X-CSRFToken"] = cookies["csrftoken"]
    r = requests.post("https://www.instagram.com/rupload_igphoto/%s" % name, headers=h,
                      cookies=_jar(cookies), data=image_bytes,
                      proxies=({"https": proxy, "http": proxy} if proxy else None), timeout=60, allow_redirects=False)
    try:
        return r.json().get("upload_id") or upload_id
    except Exception:
        return upload_id if r.status_code == 200 else None

def resolve_user_id(cookies: Dict[str, str], who, proxy: Optional[str] = None, user_agent: str = _GQL_UA):
    """username or numeric pk → (pk, profile_dict) via web_profile_info."""
    w = str(who)
    if w.isdigit():
        return w, {}
    d = web_api(cookies, "/api/v1/users/web_profile_info/", params={"username": w},
                referer=WEB_BASE + "/" + w + "/", proxy=proxy, user_agent=user_agent)
    user = (d.get("data") or {}).get("user") or d.get("user") or {}
    return (user.get("id") or user.get("pk")), user
