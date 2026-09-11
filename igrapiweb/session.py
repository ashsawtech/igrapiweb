from __future__ import annotations
from typing import Dict, Optional
from .protocol import IG_WEB_APP_ID, _UA

def uqpp_cursor_from_web_inbox(cookies: Dict[str, str], proxy: Optional[str] = None,
                               user_agent: str = _UA) -> tuple:
    """Fetch the UQPP DM-sync cursor `(max uq_seq_id, snapshot_at_ms)` for the DGW lightspeed subscription."""
    import requests
    jar = {k: v for k, v in cookies.items()
           if k in ("sessionid", "ds_user_id", "csrftoken", "mid", "ig_did", "rur")}
    r = requests.get("https://www.instagram.com/api/v1/direct_v2/inbox/?persistentBadging=true&limit=20",
                     cookies=jar, headers={"User-Agent": user_agent, "X-IG-App-ID": str(IG_WEB_APP_ID),
                                           "Referer": "https://www.instagram.com/direct/inbox/"},
                     proxies=({"https": proxy, "http": proxy} if proxy else None), timeout=30, allow_redirects=False)
    d = r.json()
    snap = d.get("snapshot_at_ms")
    best = 0
    for t in d.get("inbox", {}).get("threads", []) or []:
        for cand in (t.get("uq_seq_id"), (t.get("last_permanent_item") or {}).get("uq_seq_id")):
            try:
                best = max(best, int(cand))
            except (TypeError, ValueError):
                pass
        for it in (t.get("items") or [])[:1]:
            try:
                best = max(best, int(it.get("uq_seq_id")))
            except (TypeError, ValueError):
                pass
    return best, snap

def web_dgw_identity(cookies: Dict[str, str], thread_id=None, proxy: Optional[str] = None,
                     user_agent: str = _UA) -> dict:
    """Fetch DGW realtime auth material `{appScopedIdentity, claim, ambientState, fbid}` from the direct-page HTML."""
    import requests, re as _re
    jar = {k: v for k, v in cookies.items()
           if k in ("sessionid", "ds_user_id", "csrftoken", "mid", "ig_did", "rur")}
    url = ("https://www.instagram.com/direct/t/%s/" % thread_id) if thread_id \
        else "https://www.instagram.com/direct/inbox/"
    r = requests.get(url, cookies=jar, headers={"User-Agent": user_agent},
                     proxies=({"https": proxy, "http": proxy} if proxy else None), timeout=40, allow_redirects=False)
    html = r.text
    out = {"appScopedIdentity": None, "claim": None, "ambientState": None, "fbid": None}
    m = _re.search(r'"identity":\{"appScopedIdentity":"(\d+)","claim":"(hmac_ttl\.\d+\.[^"]+)"\}', html)
    if m:
        out["appScopedIdentity"], out["claim"] = m.group(1), m.group(2)
    sb = _re.search(r'"state_for_br":"(fase\.[^"]+)"', html)
    if sb:
        out["ambientState"] = sb.group(1)

    qeids = _re.findall(r'\\"qeid\\":\\"(\d+)\\"', html)
    if qeids:
        from collections import Counter
        out["fbid"] = Counter(qeids).most_common(1)[0][0]
    return out

def iris_cursor_from_web_inbox(cookies: Dict[str, str], proxy: Optional[str] = None,
                               user_agent: str = _UA, timeout: int = 25):
    """Fetch the iris cursor `(seq_id, snapshot_at_ms)` from the web direct-inbox."""
    import requests
    h = {"User-Agent": user_agent, "X-IG-App-ID": str(IG_WEB_APP_ID),
         "X-CSRFToken": cookies.get("csrftoken", ""),
         "Referer": "https://www.instagram.com/direct/inbox/"}
    r = requests.get("https://www.instagram.com/api/v1/direct_v2/inbox/"
                     "?persistentBadging=true&limit=20&thread_message_limit=1",
                     headers=h, cookies={k: v for k, v in cookies.items() if v},
                     proxies=({"https": proxy, "http": proxy} if proxy else None), timeout=timeout, allow_redirects=False)
    j = r.json()
    return j.get("seq_id"), j.get("snapshot_at_ms")

def thread_v2_id_from_web(cookies: Dict[str, str], thread_id, proxy: Optional[str] = None,
                          user_agent: str = _UA, timeout: int = 25) -> Optional[str]:
    """Resolve a direct thread id to its short `thread_v2_id` (DGW `thread_fbid`); returns None on failure."""
    import requests
    try:
        r = requests.get("https://www.instagram.com/api/v1/direct_v2/threads/%s/?limit=1" % thread_id,
                         headers={"User-Agent": user_agent, "X-IG-App-ID": str(IG_WEB_APP_ID),
                                  "X-CSRFToken": cookies.get("csrftoken", ""),
                                  "Referer": "https://www.instagram.com/direct/inbox/"},
                         cookies={k: v for k, v in cookies.items() if v},
                         proxies=({"https": proxy, "http": proxy} if proxy else None), timeout=timeout, allow_redirects=False)
        return (r.json().get("thread") or {}).get("thread_v2_id")
    except Exception:
        return None

def thread_last_seen_from_web(cookies: Dict[str, str], thread_id, proxy: Optional[str] = None,
                              user_agent: str = _UA, timeout: int = 25) -> Dict[str, dict]:
    """Fetch a thread's `last_seen_at` read-receipt map `{user_id: {item_id, timestamp,...}}` from the web thread endpoint."""
    import requests
    r = requests.get("https://www.instagram.com/api/v1/direct_v2/threads/%s/?limit=1" % thread_id,
                     headers={"User-Agent": user_agent, "X-IG-App-ID": str(IG_WEB_APP_ID),
                              "X-CSRFToken": cookies.get("csrftoken", ""),
                              "Referer": "https://www.instagram.com/direct/inbox/"},
                     cookies={k: v for k, v in cookies.items() if v},
                     proxies=({"https": proxy, "http": proxy} if proxy else None), timeout=timeout, allow_redirects=False)
    return (r.json().get("thread", {}) or {}).get("last_seen_at", {}) or {}

def thread_members(cookies: Dict[str, str], thread_id, proxy: Optional[str] = None,
                   user_agent: str = _UA, timeout: int = 25) -> Dict[str, dict]:
    """Per-sender identity map for a thread keyed by both pk and eimu; each entry {pk, eimu, username, full_name, nickname, name}."""
    import requests
    def _get(tid):
        rr = requests.get("https://www.instagram.com/api/v1/direct_v2/threads/%s/?limit=1" % tid,
                          headers={"User-Agent": user_agent, "X-IG-App-ID": str(IG_WEB_APP_ID),
                                   "X-CSRFToken": cookies.get("csrftoken", ""),
                                   "Referer": "https://www.instagram.com/direct/inbox/"},
                          cookies={k: v for k, v in cookies.items() if v},
                          proxies=({"https": proxy, "http": proxy} if proxy else None), timeout=timeout, allow_redirects=False)
        return (rr.json() or {}).get("thread", {}) or {}
    th = _get(thread_id)

    if not (th.get("users") or []) and th.get("thread_v2_id") and str(th["thread_v2_id"]) != str(thread_id):
        th = _get(th["thread_v2_id"])

    nickmap: Dict[str, str] = {}
    for e in (th.get("nicknames") or []):
        if isinstance(e, dict) and e.get("nickname"):
            for idk in ("igid", "eimu_id", "fbid_v2"):
                if e.get(idk):
                    nickmap[str(e[idk])] = e["nickname"]
    out: Dict[str, dict] = {}
    for u in th.get("users", []) or []:
        pk = str(u.get("pk")) if u.get("pk") else None
        eimu = str(u.get("interop_messaging_user_fbid")) if u.get("interop_messaging_user_fbid") else None
        fbv2 = str(u.get("fbid_v2")) if u.get("fbid_v2") else None
        nick = (u.get("nickname") or nickmap.get(pk or "") or nickmap.get(eimu or "") or nickmap.get(fbv2 or ""))
        info = {"pk": pk, "eimu": eimu, "username": u.get("username"), "full_name": u.get("full_name"),
                "nickname": nick, "name": nick or u.get("full_name") or u.get("username") or pk}
        for k in (pk, eimu, fbv2):
            if k:
                out[k] = info
    return out

def thread_display_names(cookies: Dict[str, str], thread_id, proxy: Optional[str] = None,
                         user_agent: str = _UA, timeout: int = 25) -> Dict[str, str]:
    """Map `sender_id → display name`, keyed by both pk and eimu (nickname → full_name → username)."""
    return {k: v["name"] for k, v in thread_members(cookies, thread_id, proxy=proxy,
                                                     user_agent=user_agent, timeout=timeout).items()}

def cookies_from_sessionid(sessionid: str, csrftoken: str = "") -> Dict[str, str]:
    """Build the web cookie set from a bare `sessionid` (ds_user_id derived from its leading digits)."""
    sid = sessionid.strip()
    lead = sid.split("%3A")[0].split(":")[0]
    ck = {"sessionid": sid}
    if lead.isdigit():
        ck["ds_user_id"] = lead
    if csrftoken:
        ck["csrftoken"] = csrftoken
    return ck
