from __future__ import annotations
import json
from typing import List

def _scrape_json_objects(buf: bytes) -> List[dict]:
    """Extract top-level JSON objects embedded in a DGW frame (best-effort)."""
    out = []
    i = 0
    while True:
        s = buf.find(b"{", i)
        if s < 0:
            break
        depth = 0
        j = s
        instr = False
        esc = False
        while j < len(buf):
            c = buf[j]
            if instr:
                if esc:
                    esc = False
                elif c == 0x5C:
                    esc = True
                elif c == 0x22:
                    instr = False
            else:
                if c == 0x22:
                    instr = True
                elif c == 0x7B:
                    depth += 1
                elif c == 0x7D:
                    depth -= 1
                    if depth == 0:
                        try:
                            out.append(json.loads(buf[s:j + 1].decode("utf-8", "replace")))
                        except Exception:
                            pass
                        break
            j += 1
        i = j + 1
    return out

def _patch_ops_to_wa(patches: list, source: str = "dgw", self_id=None) -> List[dict]:
    """Route Instagram JSON-patch ops (DGW `xdt_direct_realtime_event` / iris `/ig_message_sync`) into structured events."""
    out: List[dict] = []
    for p in patches:
        if not isinstance(p, dict):
            continue
        path = p.get("path") or ""
        raw = p.get("value")
        val = raw
        if isinstance(raw, str) and raw[:1] in "{[":
            try: val = json.loads(raw)
            except Exception: val = raw
        parts = path.split("/")
        thread = parts[3] if len(parts) > 3 and parts[1] == "direct_v2" and parts[2] == "threads" else None
        if "last_seen_at" in path or "/seen" in path:

            uid = path.rsplit("/", 1)[-1] if path.rsplit("/", 1)[-1].isdigit() else None
            v = val if isinstance(val, dict) else {}
            out.append({"_event": "message-receipt.update",
                        "payload": {"key": {"remoteJid": str(thread) if thread else None,
                                            "id": str(v.get("item_id")) if v.get("item_id") else None},
                                    "receipt": {"userId": uid, "readTimestamp": v.get("timestamp"), "type": "read"},
                                    "source": source, "_raw": p}})
            continue
        if "/reactions" in path or (isinstance(val, dict) and val.get("emoji") and "reaction" in path.lower()):

            item_id = None
            if "/items/" in path:
                item_id = path.split("/items/", 1)[1].split("/")[0]
            emoji = val.get("emoji") if isinstance(val, dict) else None

            sender = (val.get("sender_id") or val.get("user_id")) if isinstance(val, dict) else None
            if not sender and "/reactions/" in path:
                tail = path.rsplit("/", 1)[-1]
                if tail.isdigit():
                    sender = tail
            out.append({"_event": "messages.reaction",
                        "payload": {"key": {"remoteJid": str(thread) if thread else None,
                                            "id": str(item_id) if item_id else None},
                                    "reaction": {"text": emoji, "senderId": str(sender) if sender else None,
                                                 "removed": p.get("op") == "remove" or emoji in (None, "")},
                                    "source": source, "_raw": p}})
            continue
        if "/items/" in path:

            if not (isinstance(val, dict) and (val.get("item_type") or val.get("item_id"))):
                continue
            parts_after = path.split("/items/", 1)[1].split("/")
            item_id = parts_after[0] if parts_after else None
            if len(parts_after) > 1:
                continue
            sender = val.get("user_id")
            from_me = (self_id is not None and sender is not None and str(sender) == str(self_id))
            key = {"fromMe": bool(from_me), "remoteJid": str(thread) if thread else None,
                   "id": str(item_id) if item_id else str(val.get("item_id"))}
            out.append({"_event": "messages.upsert",
                        "msg": {"key": key, "message": val, "_raw": p, "op": p.get("op")}})
        elif "activity_indicator" in path:
            status = val.get("activity_status") if isinstance(val, dict) else None
            out.append({"_event": "presence.update",
                        "payload": {"source": source, "id": str(thread) if thread else None,
                                    "presences": {"composing" if status else "paused": True}, "_raw": p}})
        else:
            out.append({"_event": "presence.update", "payload": {"source": source, "_raw": p}})
    return out

def _dgw_direct_to_wa(obj: dict, self_id=None) -> List[dict]:
    """Translate one DGW `xdt_direct_realtime_event` object into structured events (typing/presence)."""
    ev = (((obj or {}).get("data") or {}).get("xdt_direct_realtime_event")
          or obj.get("xdt_direct_realtime_event") or obj)
    patches = ev.get("data") if isinstance(ev, dict) else None
    if not isinstance(patches, list):
        return []
    return _patch_ops_to_wa(patches, source="dgw", self_id=self_id)

def _uqpp_deltas(frame: bytes) -> List[dict]:
    """Extract the `slide_delta_processor` delta list from one DGW lightspeed `0d` frame."""
    import base64 as _b64
    j = frame.find(b"{")
    if j < 0:
        return []
    try:
        outer = json.loads(frame[j:].rstrip(b"\x00").decode("latin1"))
    except Exception:
        return []
    p = outer.get("payload") if isinstance(outer, dict) else None
    if not p:
        return []
    try:
        raw = _b64.b64decode(p)
    except Exception:
        return []
    txt = raw.decode("latin1", "replace")
    out: List[dict] = []
    start = 0
    while True:
        s = txt.find('[{"data"', start)
        if s < 0:
            break

        depth = 0; end = -1
        for k in range(s, len(txt)):
            c = txt[k]
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    end = k + 1; break
        if end < 0:
            break
        try:
            arr = json.loads(txt[s:end])
            for d in arr:
                for sd in (d.get("data", {}) or {}).get("slide_delta_processor", []) or []:
                    out.append(sd)
        except Exception:
            pass
        start = end
    return out

_UQPP_ITEM_TYPE = {"TEXT": "text", "IMAGES": "media", "VIDEOS": "media", "AUDIOS": "voice_media",
                   "STICKER": "placeholder", "ANIMATED_IMAGE": "animated_media",
                   "LINK": "link", "GENERIC_XMA": "xma"}

def _uqpp_media(content: dict) -> List[dict]:
    """Extract normalized media attachments from a UQPP message `content` object."""
    if not isinstance(content, dict):
        return []
    tn = content.get("__typename") or ""
    if "Image" in tn:
        kind, atts = "image", content.get("attachments") or []
    elif "Video" in tn:
        kind, atts = "video", content.get("videos") or []
    elif "Audio" in tn:
        kind, atts = "voice", content.get("audio_attachments") or []
    else:
        atts = content.get("attachments") or content.get("videos") or content.get("audio_attachments") or []
        kind = "media"
    out = []
    for a in atts:
        if not isinstance(a, dict):
            continue
        out.append({"kind": kind,
                    "url": a.get("attachment_cdn_url") or a.get("attachment_cdn_fallback_url"),
                    "preview_url": a.get("preview_cdn_url") or a.get("preview_cdn_fallback_url"),
                    "fbid": a.get("attachment_fbid"),
                    "width": a.get("preview_width"), "height": a.get("preview_height"),
                    "duration_ms": a.get("playable_duration_ms"),
                    "waveform": a.get("waveform_data"),
                    "dash_manifest": a.get("dash_manifest")})
    return out

def _dgw_lightspeed_to_wa(frame: bytes, self_id=None) -> List[dict]:
    """Translate one DGW lightspeed frame's UQPP deltas into structured events (ids are FBID-space; pass a FBID for self_id)."""
    out: List[dict] = []
    for sd in _uqpp_deltas(frame):
        tn = sd.get("__typename")
        if tn == "SlideUQPPNewMessage":
            msg = sd.get("message", {}) or {}
            ct = (msg.get("content_type") or "").upper()
            item_type = _UQPP_ITEM_TYPE.get(ct, ct.lower() or "text")
            sender = msg.get("sender_fbid")
            thread = msg.get("thread_fbid")
            from_me = (self_id is not None and sender is not None and str(sender) == str(self_id))
            media = _uqpp_media(msg.get("content") or {})
            body = dict(msg)
            body.update({"item_type": item_type, "text": msg.get("text_body"),
                         "user_id": sender, "message_id": msg.get("message_id"),
                         "reply_to_message_id": msg.get("replied_to_message_id"),
                         "media": media, "url": (media[0]["url"] if media else None)})
            key = {"fromMe": bool(from_me), "remoteJid": str(thread) if thread else None,
                   "id": str(msg.get("message_id")) if msg.get("message_id") else None}
            out.append({"_event": "messages.upsert",
                        "msg": {"key": key, "message": body, "_raw": sd, "op": "add"}})
        elif tn in ("SlideUQPPCreateReaction", "SlideUQPPDeleteReaction") or "Reaction" in (tn or ""):

            rc = sd.get("reaction") or {}
            emoji = rc.get("reaction") if isinstance(rc, dict) else None
            removed = (tn == "SlideUQPPDeleteReaction") or not emoji
            out.append({"_event": "messages.reaction",
                        "payload": {"key": {"remoteJid": str(sd.get("thread_fbid")) if sd.get("thread_fbid") else None,
                                            "id": str(sd.get("message_id")) if sd.get("message_id") else None},
                                    "reaction": {"text": emoji, "senderId": str(rc.get("sender_fbid")) if rc.get("sender_fbid") else None,
                                                 "timestamp": rc.get("reaction_timestamp_ms"), "removed": bool(removed)},
                                    "source": "dgw-lightspeed", "_raw": sd}})
        elif tn in ("SlideUQPPMarkRead", "SlideUQPPIGMarkThreadUnread") or "MarkRead" in (tn or ""):
            out.append({"_event": "message-receipt.update",
                        "payload": {"key": {"remoteJid": str(sd.get("thread_fbid")) if sd.get("thread_fbid") else None,
                                            "id": None},
                                    "receipt": {"userId": None, "readTimestamp": sd.get("read_timestamp_ms"),
                                                "type": "read"},
                                    "source": "dgw-lightspeed", "_raw": sd}})
    return out

def _message_sync_to_wa(payload: bytes, self_id=None) -> List[dict]:
    """Parse an iris `/ig_message_sync` publish into structured events."""
    if isinstance(payload, (bytes, bytearray)):
        b = bytes(payload)
        i = min((k for k in (b.find(b"[{"), b.find(b"[ "), b.find(b"{\"")) if k >= 0), default=-1)
        if i < 0:
            i = b.find(b"[")
        try:
            data = json.loads(b[i:].decode("utf-8", "replace")) if i >= 0 else None
        except Exception:
            data = None
    else:
        data = payload
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    out: List[dict] = []
    for entry in data:
        ops = entry.get("data") if isinstance(entry, dict) else None
        if isinstance(ops, list):
            out.extend(_patch_ops_to_wa(ops, source="iris", self_id=self_id))
    return out
