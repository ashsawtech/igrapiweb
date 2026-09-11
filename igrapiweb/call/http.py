"""Call-setup HTTP: Zenon call mutations to ``/call/api/graphql/`` and TURN discovery."""
from __future__ import annotations
import json
from typing import Dict, List, Optional
from ..protocol import IG_WEB_APP_ID, _GQL_UA
from ..graphql import web_graphql_scrape_tokens, _gql_query_tokens

CALL_DOC_IDS = {
    "start_call_peer_details": "37262966273349353",
    "enter_call":              "28121577240779920",
    "participants_state":      "27997664523220942",
}
CALL_FRIENDLY = {
    "start_call_peer_details": "ZenonUnifiedStartCallPeerDetailsQuery",
    "enter_call":              "InstagramEnterCallMutation",
    "participants_state":      "ZenonParticipantsQueryStateQuery",
}
STUN_URL = "stun:stun.fbsbx.com:3478"

def _call_referer(short_thread: str) -> str:
    return "https://www.instagram.com/call/?has_video=false&ig_thread_id=%s" % short_thread

def call_graphql(cookies: Dict[str, str], key: str, variables: dict, *, short_thread: str,
                 tokens: Optional[dict] = None, proxy: Optional[str] = None,
                 user_agent: str = _GQL_UA) -> dict:
    """POST a Zenon call mutation/query to ``/call/api/graphql/``."""
    import requests
    tok = tokens or web_graphql_scrape_tokens(cookies, proxy=proxy, user_agent=user_agent)
    dtsg = tok.get("fb_dtsg") or ""
    form = {
        "av": tok.get("fbid") or cookies.get("ds_user_id", ""), "__user": "0",
        "__a": "1", "__req": "a", "__comet_req": "7", "dpr": "1",
        "fb_dtsg": dtsg, "jazoest": "2" + str(sum(ord(c) for c in dtsg)),
        "lsd": tok.get("lsd") or "", "__rev": str(tok.get("rev") or ""),
        "__hs": tok.get("hs") or "", "__hsi": tok.get("hsi") or "",
        "__spin_r": str(tok.get("rev") or ""), "__spin_b": tok.get("spin_b") or "trunk",
        "__spin_t": str(tok.get("spin_t") or ""), "__ccg": "EXCELLENT", "__d": "www",
        "fb_api_caller_class": "RelayModern", "fb_api_req_friendly_name": CALL_FRIENDLY[key],
        "server_timestamps": "true", "doc_id": CALL_DOC_IDS[key],
        "variables": json.dumps(variables, separators=(",", ":")),
    }
    h = {"User-Agent": user_agent, "X-IG-App-ID": str(IG_WEB_APP_ID), "X-FB-LSD": tok.get("lsd") or "",
         "X-FB-Friendly-Name": CALL_FRIENDLY[key], "X-ASBD-ID": "359341",
         "Content-Type": "application/x-www-form-urlencoded", "Origin": "https://www.instagram.com",
         "Referer": _call_referer(short_thread), "X-Requested-With": "XMLHttpRequest"}
    if cookies.get("csrftoken"):
        h["X-CSRFToken"] = cookies["csrftoken"]
    r = requests.post("https://www.instagram.com/call/api/graphql/", headers=h,
                      cookies={k: v for k, v in cookies.items() if v}, data=form,
                      proxies=({"https": proxy, "http": proxy} if proxy else None), timeout=30, allow_redirects=False)
    txt = r.text
    if txt.startswith("for (;;);"):
        txt = txt[len("for (;;);"):]
    try:
        return json.loads(txt)
    except Exception:
        return {"_status": r.status_code, "_body": r.text[:300]}

def turn_discovery(cookies: Dict[str, str], *, short_thread: str, tokens: Optional[dict] = None,
                   proxy: Optional[str] = None, user_agent: str = _GQL_UA) -> List[dict]:
    """POST ``/videocall/turndiscovery/`` → the aiortc ICE-server list [{urls[], username?, credential?}]."""
    import requests
    tok = tokens or web_graphql_scrape_tokens(cookies, proxy=proxy, user_agent=user_agent)
    form = _gql_query_tokens(tok)
    h = {"User-Agent": user_agent, "X-IG-App-ID": str(IG_WEB_APP_ID), "X-FB-LSD": tok.get("lsd") or "",
         "Content-Type": "application/x-www-form-urlencoded", "Origin": "https://www.instagram.com",
         "Referer": _call_referer(short_thread), "X-Requested-With": "XMLHttpRequest"}
    if cookies.get("csrftoken"):
        h["X-CSRFToken"] = cookies["csrftoken"]
    r = requests.post("https://www.instagram.com/videocall/turndiscovery/?call_id=ZenonPlatform&version=1",
                      headers=h, cookies={k: v for k, v in cookies.items() if v}, data=form,
                      proxies=({"https": proxy, "http": proxy} if proxy else None), timeout=30, allow_redirects=False)
    txt = r.text
    if txt.startswith("for (;;);"):
        txt = txt[len("for (;;);"):]
    ice = [{"urls": [STUN_URL]}]
    try:
        p = (json.loads(txt) or {}).get("payload") or {}
    except Exception:
        return ice

    ip = p.get("ip")
    user, pw = p.get("username"), p.get("password")
    urls = []
    if ip:
        if p.get("udp_port"):
            urls.append("turn:%s:%s?transport=udp" % (ip, p["udp_port"]))
        if p.get("tcp_port"):
            urls.append("turn:%s:%s?transport=tcp" % (ip, p["tcp_port"]))
        if p.get("ssl_tcp_port"):
            urls.append("turn:%s:%s?transport=tcp" % (ip, p["ssl_tcp_port"]))
    if urls:
        ice.append({"urls": urls, "username": user, "credential": pw})
    return ice

def enter_call(cookies: Dict[str, str], *, ig_thread_id: str, peer_id: str, actor_id: str,
               server_info_data: Optional[str] = None, tokens: Optional[dict] = None,
               proxy: Optional[str] = None) -> Optional[str]:
    """InstagramEnterCallMutation (ring/join); pass ``server_info_data`` to answer, None to originate → room_id."""
    variables = {"input": {"ig_thread_id": str(ig_thread_id), "peer_id": str(peer_id),
                           "server_info_data": server_info_data, "actor_id": str(actor_id),
                           "client_mutation_id": "1"}}
    resp = call_graphql(cookies, "enter_call", variables, short_thread=str(ig_thread_id),
                        tokens=tokens, proxy=proxy)
    try:
        return resp["data"]["instagram_enter_call_mutation"]["room_id"]
    except Exception:
        return None

def participants_state(cookies: Dict[str, str], *, ig_thread_id: str, peer_id: str, user_id: str,
                       server_info_data: Optional[str] = None, tokens: Optional[dict] = None,
                       proxy: Optional[str] = None) -> dict:
    """ZenonParticipantsQueryStateQuery — fire immediately before sending the SDP offer to arm the media session."""
    variables = {"appContext": {"is_e2ee_mandated": False, "joining_context": {
        "group_thread_id": None, "peer_id": str(peer_id), "link_url": None,
        "call_trigger": "ig_lobby_start_call", "meeting_id": None, "server_info_data": server_info_data,
        "ig_thread_id": str(ig_thread_id), "live_broadcast_id": None, "calling_tags": None,
        "hide_e2ee_attributions": False}}, "scale": 1, "userID": str(user_id)}
    return call_graphql(cookies, "participants_state", variables, short_thread=str(ig_thread_id),
                        tokens=tokens, proxy=proxy)

def start_call_peer_details(cookies: Dict[str, str], *, ig_thread_id: str, peer_id: str,
                            tokens: Optional[dict] = None, proxy: Optional[str] = None) -> dict:
    """ZenonUnifiedStartCallPeerDetailsQuery — the lobby "door": participants + display info (optional)."""
    variables = {"appContext": {"is_e2ee_mandated": False, "joining_context": {
        "group_thread_id": None, "peer_id": str(peer_id), "link_url": None,
        "call_trigger": "ig_lobby_start_call", "meeting_id": None, "server_info_data": None,
        "ig_thread_id": str(ig_thread_id), "live_broadcast_id": None, "calling_tags": None,
        "hide_e2ee_attributions": False}}, "scale": 1}
    return call_graphql(cookies, "start_call_peer_details", variables, short_thread=str(ig_thread_id),
                        tokens=tokens, proxy=proxy)
