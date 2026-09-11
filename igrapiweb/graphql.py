# igrapiweb · created by ashsawtech · https://github.com/ashsawtech/igrapiweb · attribution required (see _attrib.py)
from __future__ import annotations
import json, time, uuid
from typing import Dict, Optional
from .protocol import IG_WEB_APP_ID, _UA, _GQL_UA

IG_WEB_DOC_IDS = {
    "text_send":        "26911679871773184",
    "reaction_send":    "24374451552236906",
    "reactions_dialog": "27046967008309131",
    "media_send":       "25766288509716264",
    "edit_message":     "32480262318254796",
    "unsend_message":   "26948700068153789",
    "create_group":     "27529949946640544",
    "optimistic_user":  "35274961328786258",
    "add_member":       "28505413572388771",
    "remove_member":    "27974649738797533",
    "make_admin":       "35563011113312213",
    "remove_admin":     "26688907887428172",
    "rename_thread":    "26508340268868683",
    "edit_nickname":    "26698632706416151",
    "nickname_setting": "26600555296271156",
    "mark_read":        "27399783383056109",
    "mark_read_validate": "35211594988486314",
}
IG_WEB_FRIENDLY_NAMES = {
    "text_send": "IGDirectTextSendMutation",
    "reaction_send": "IGDirectReactionSendMutation",
    "reactions_dialog": "IGDReactionsDialogOffMsysQuery",
    "media_send": "IGDirectMediaSendMutation",
    "edit_message": "IGDirectEditMessageMutation",
    "unsend_message": "IGDMessageUnsendDialogOffMsysMutation",
    "create_group": "useCreateOpenGroupThreadOffMsysMutation",
    "optimistic_user": "useIGDCreateOptimisticThreadUserQuery",
    "mark_read": "useIGDMarkThreadAsReadMutation",
    "mark_read_validate": "useIGDMarkThreadAsReadValidationMutation",

    "rename_thread": "IGDEditThreadNameDialogOffMsysMutation",
    "edit_nickname": "useIGDEditNicknameMutation",
    "nickname_setting": "IGDNicknameSettingsPageMutation",
    "add_member": "IGDAddParticipantSubmitBarMutation",
    "remove_member": "IGDRemoveFromGroupDialogItemOffMsysMutation",
    "make_admin": "IGDAddAdminDialogItemOffMsysMutation",
    "remove_admin": "IGDRemoveAdminDialogItemOffMsysMutation",
    "unsend_message": "IGDMessageUnsendDialogOffMsysMutation",
    "edit_message": "IGDirectEditMessageMutation",
}

def build_create_group_variables(recipient_eimu_fbids, offline_threading_id: Optional[str] = None) -> dict:
    """Build create-group mutation `variables`; `recipient_eimu_fbids` are eimu (messaging-user) fbids, not user pks."""
    if offline_threading_id is None:
        offline_threading_id = str(int(time.time() * 1000) * 1000 + int(uuid.uuid4().int % 1000000))
    return {"recipient_eimu_fbids": [str(x) for x in recipient_eimu_fbids],
            "offline_threading_id": offline_threading_id, "entry_point": None}

IG_WEB_MERCURY_UPLOAD_URL = "https://www.instagram.com/ajax/mercury/upload.php"

def build_media_send_variables(thread_igid, attachment_fbid, *, offline_threading_id: Optional[str] = None,
                               reply_to_message_id: Optional[str] = None) -> dict:
    """Build IGDirectMediaSendMutation `variables`: send an uploaded media by its Mercury attachment_fbid."""
    if offline_threading_id is None:
        offline_threading_id = str(int(time.time() * 1000) * 1000 + int(uuid.uuid4().int % 1000000))
    return {"attachment_fbid": str(attachment_fbid), "thread_id": str(thread_igid),
            "offline_threading_id": offline_threading_id,
            "reply_to_message_id": str(reply_to_message_id) if reply_to_message_id else None,
            "forwarded_from_thread_id": None, "is_forwarded_from_own_message": None}

def build_text_send_variables(thread_igid, text: str, *, offline_threading_id: Optional[str] = None,
                              recipient_igids=None, replied_to_item_id: Optional[str] = None,
                              reply_to_message_id: Optional[str] = None,
                              send_attribution: str = "igd_web_chat_tab:in_thread") -> dict:
    """Build IGDirectTextSendMutation `variables`; target is `thread_igid` or `recipient_igids`, quote reply when replied_to set."""
    if offline_threading_id is None:
        offline_threading_id = str(int(time.time() * 1000) * 1000 + int(uuid.uuid4().int % 1000000))
    return {
        "ig_thread_igid": str(thread_igid) if thread_igid else None,
        "offline_threading_id": offline_threading_id,
        "recipient_igids": ([str(x) for x in recipient_igids] if recipient_igids else None),
        "replied_to_client_context": None,
        "replied_to_item_id": str(replied_to_item_id) if replied_to_item_id else None,
        "reply_to_message_id": str(reply_to_message_id) if reply_to_message_id else None,
        "sampled": None,
        "text": {"sensitive_string_value": text},
        "mentions": [], "mentioned_user_ids": [], "commands": None,
        "forwarded_from_thread_id": None, "is_forwarded_from_own_message": None,
        "send_attribution": send_attribution,
    }

def build_reaction_variables(thread_id, message_id: str, emoji: str = "❤", *, created: bool = True) -> dict:
    """Build IGDirectReactionSendMutation `variables.input`; keyed by message_id (item_id empty), reaction_status created|deleted."""
    return {"input": {
        "emoji": emoji if created else "",
        "item_id": "",
        "message_id": str(message_id),
        "reaction_status": "created" if created else "deleted",
        "thread_id": str(thread_id),
    }}

def web_graphql_scrape_tokens(cookies: Dict[str, str], proxy: Optional[str] = None,
                              user_agent: str = _UA) -> dict:
    """Scrape the Meta web-GraphQL token bundle (fb_dtsg, lsd, rev, av=viewer FBID, user=pk, ...) from a logged-in inbox page."""
    import re, requests
    from collections import Counter
    r = requests.get("https://www.instagram.com/direct/inbox/", headers={"User-Agent": user_agent},
                     cookies={k: v for k, v in cookies.items() if v},
                     proxies=({"https": proxy, "http": proxy} if proxy else None), timeout=25,
                     allow_redirects=False)
    if r.status_code in (301, 302, 303, 307, 308):
        return {"user": cookies.get("ds_user_id")}
    h = r.text
    def find(pats):
        for p in pats:
            m = re.search(p, h)
            if m: return m.group(1)
        return None
    qeids = re.findall(r'\\"qeid\\":\\"(\d+)\\"', h)
    fbid = Counter(qeids).most_common(1)[0][0] if qeids else None
    return {
        "fb_dtsg": find([r'"DTSGInitData",\[\],\{"token":"([^"]+)"', r'"dtsg":\{"token":"([^"]+)"',
                         r'DTSGInitData[^}]*?"token":"([^"]+)"']),
        "lsd": find([r'"LSD",\[\],\{"token":"([^"]+)"', r'"lsd":"([^"]+)"']),
        "rev": find([r'"__spin_r":(\d+)', r'"client_revision":(\d+)', r',"rev":(\d+)']),
        "hs": find([r'"haste_session":"([^"]+)"']),
        "spin_b": find([r'"__spin_b":"([^"]+)"']) or "trunk",
        "spin_t": find([r'"__spin_t":(\d+)']),
        "hsi": find([r'"hsi":"(\d+)"', r'"__hsi":"?(\d+)"?']),
        "fbid": fbid,
        "user": cookies.get("ds_user_id"),
    }

def web_graphql_call(cookies: Dict[str, str], key: Optional[str], variables: dict, *, proxy: Optional[str] = None,
                     user_agent: str = _GQL_UA, tokens: Optional[dict] = None,
                     referer: Optional[str] = None, doc_id: Optional[str] = None,
                     friendly_name: Optional[str] = None) -> dict:
    """POST a DM mutation (`key` in IG_WEB_DOC_IDS) to /api/graphql; `referer` must be the thread page URL or the server rejects."""
    import requests
    tok = tokens or web_graphql_scrape_tokens(cookies, proxy=proxy, user_agent=user_agent)
    fb_dtsg = tok.get("fb_dtsg") or ""
    fname = friendly_name or IG_WEB_FRIENDLY_NAMES[key]
    did = doc_id or IG_WEB_DOC_IDS[key]
    av = tok.get("fbid") or cookies.get("ds_user_id", "")
    form = {
        "av": av, "__user": "0",
        "__a": "1", "__req": "a", "__comet_req": "7", "dpr": "1",
        "fb_dtsg": fb_dtsg, "jazoest": "2" + str(sum(ord(c) for c in fb_dtsg)),
        "lsd": tok.get("lsd") or "", "__rev": str(tok.get("rev") or ""),
        "__hs": tok.get("hs") or "", "__hsi": tok.get("hsi") or "",
        "__spin_r": str(tok.get("rev") or ""), "__spin_b": tok.get("spin_b") or "trunk",
        "__spin_t": str(tok.get("spin_t") or ""), "__ccg": "GOOD",
        "__crn": "comet.igweb.PolarisDirectInboxRoute", "__d": "www",
        "fb_api_caller_class": "RelayModern",
        "fb_api_req_friendly_name": fname,
        "server_timestamps": "true", "doc_id": did,
        "variables": json.dumps(variables, separators=(",", ":")),
    }

    h = {"User-Agent": user_agent, "X-IG-App-ID": str(IG_WEB_APP_ID), "X-FB-LSD": tok.get("lsd") or "",
         "X-FB-Friendly-Name": fname, "X-ASBD-ID": "359341",
         "Content-Type": "application/x-www-form-urlencoded", "Origin": "https://www.instagram.com",
         "Referer": referer or "https://www.instagram.com/direct/inbox/", "X-Requested-With": "XMLHttpRequest"}
    if cookies.get("csrftoken"): h["X-CSRFToken"] = cookies["csrftoken"]
    r = requests.post("https://www.instagram.com/api/graphql", headers=h,
                      cookies={k: v for k, v in cookies.items() if v}, data=form,
                      proxies=({"https": proxy, "http": proxy} if proxy else None), timeout=30, allow_redirects=False)
    txt = r.text
    if txt.startswith("for (;;);"):
        txt = txt[len("for (;;);"):]
    try:
        return json.loads(txt)
    except Exception:
        return {"_status": r.status_code, "_body": r.text[:300]}

IG_WEB_MERCURY_UPLOAD_URL = "https://www.instagram.com/ajax/mercury/upload.php"

def _gql_query_tokens(tok: dict) -> dict:
    dtsg = tok.get("fb_dtsg") or ""
    return {"__d": "www", "__user": "0", "__a": "1", "__req": "a", "__hs": tok.get("hs") or "",
            "dpr": "1", "__ccg": "GOOD", "__rev": str(tok.get("rev") or ""), "__hsi": tok.get("hsi") or "",
            "__comet_req": "7", "fb_dtsg": dtsg, "jazoest": "2" + str(sum(ord(c) for c in dtsg)),
            "lsd": tok.get("lsd") or "", "__spin_r": str(tok.get("rev") or ""),
            "__spin_b": tok.get("spin_b") or "trunk", "__spin_t": str(tok.get("spin_t") or "")}

def web_mercury_upload(cookies: Dict[str, str], file_path: str, *, kind: str = "photo",
                       content_type: Optional[str] = None, proxy: Optional[str] = None,
                       user_agent: str = _GQL_UA, tokens: Optional[dict] = None,
                       referer: Optional[str] = None, extra_fields: Optional[dict] = None,
                       filename: Optional[str] = None) -> Optional[str]:
    """Upload PHOTO/VIDEO/VOICE to Instagram-web's Mercury uploader; returns the attachment_fbid for IGDirectMediaSendMutation."""
    import requests, os
    if content_type is None:
        content_type = "image/jpeg" if kind == "photo" else "application/octet-stream"
    tok = tokens or web_graphql_scrape_tokens(cookies, proxy=proxy, user_agent=user_agent)
    q = _gql_query_tokens(tok)
    h = {"User-Agent": user_agent, "X-FB-LSD": tok.get("lsd") or "", "X-ASBD-ID": "359341",
         "Origin": "https://www.instagram.com", "X-Requested-With": "XMLHttpRequest",
         "Referer": referer or "https://www.instagram.com/direct/inbox/"}
    if cookies.get("csrftoken"):
        h["X-CSRFToken"] = cookies["csrftoken"]
    data = file_path if isinstance(file_path, (bytes, bytearray)) else open(file_path, "rb").read()
    fname = filename or (("upload." + ("jpg" if kind == "photo" else "mp4")) if isinstance(file_path, (bytes, bytearray))
                         else os.path.basename(file_path))
    r = requests.post(IG_WEB_MERCURY_UPLOAD_URL, params=q, headers=h,
                      cookies={k: v for k, v in cookies.items() if v}, data=(extra_fields or None),
                      files={"farr": (fname, bytes(data), content_type)},
                      proxies=({"https": proxy, "http": proxy} if proxy else None), timeout=120, allow_redirects=False)
    txt = r.text[9:] if r.text.startswith("for (;;);") else r.text
    try:
        md = json.loads(txt).get("payload", {}).get("metadata", {})
        for v in md.values():
            fid = v.get("fbid") or v.get("file_id") or v.get("video_id") or v.get("audio_id")
            if fid:
                return fid
    except Exception:
        pass
    return None
