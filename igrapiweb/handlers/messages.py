# igrapiweb · created by ashsawtech · https://github.com/ashsawtech/igrapiweb · attribution required (see _attrib.py)
from __future__ import annotations
import time, uuid
from typing import Any, Dict, Optional
from .._common import *

class MessagesMixin:
    """DM send: text/quote/react (graphql default), photo/video/voice (pure-Python), unsend/edit."""
    def send_message(self, thread_id, content: Dict[str, Any], options: Optional[dict] = None) -> Any:
        options = options or {}

        transport = options.get("transport") or self.default_send
        ws_up = getattr(self.edge, "_alive", False) and self.edge.transport is not None

        if "voice" in content or ("audio" in content and content.get("ptt")):
            return {"transport": "graphql", "response": self.send_voice(thread_id, content.get("voice") or content.get("audio"))}
        if "image" in content or "video" in content or "audio" in content:
            f = content.get("video") or content.get("image") or content.get("audio")
            kind = "photo" if "image" in content else ("voice" if "audio" in content else "video")
            return {"transport": "graphql", "response": self.send_media(thread_id, f, kind=kind)}

        if "delete" in content:
            d = content["delete"]
            mid = (d.get("message_id") or d.get("id")) if isinstance(d, dict) else str(d)
            return {"transport": "graphql", "response": self.unsend_message(thread_id, message_id=mid)}
        if "edit" in content:
            e = content["edit"]
            mid = (e.get("message_id") or e.get("id")) if isinstance(e, dict) else str(e)
            return {"transport": "graphql", "response": self.edit_message(thread_id, str(content.get("text", "")), message_id=mid)}

        quoted = (options.get("quoted") or content.get("quoted") or {})
        qk = quoted.get("key", {}) if isinstance(quoted, dict) else {}
        qmsg = quoted.get("message", {}) if isinstance(quoted, dict) else {}

        if transport == "graphql" and ("text" in content or "react" in content):
            big = str(options.get("referer_thread") or thread_id)
            short = self._short_thread_id(thread_id)
            if str(thread_id) != short:
                big = str(thread_id)
            referer = "https://www.instagram.com/direct/t/%s/" % big
            if "text" in content:
                key = "text_send"
                v = build_text_send_variables(
                    short, str(content["text"]),
                    replied_to_item_id=(qk.get("id") if qk else None),
                    reply_to_message_id=(qmsg.get("message_id") if isinstance(qmsg, dict) else None))
            else:
                r = content["react"]
                mid = (r.get("key", {}).get("message_id") or r.get("message_id")
                       or (r.get("message") or {}).get("message_id"))
                key = "reaction_send"
                v = build_reaction_variables(short, mid, r.get("text", "❤"),
                                             created=(r.get("text", "❤") != ""))

            resp = None
            for force in (False, True):
                resp = web_graphql_call(self.cookies, key, v, proxy=self.proxy, referer=referer,
                                        tokens=self._gql_token_bundle(force=force))
                if isinstance(resp, dict) and "data" in resp and not resp.get("errors"):
                    return {"transport": "graphql", "response": resp}
                if not (isinstance(resp, dict) and resp.get("error") in (1357054, 1357001)):
                    break

            if not options.get("no_fallback"):
                self.ev.emit("send.fallback", {"from": "graphql", "to": "ws", "response": resp})
            else:
                return {"transport": "graphql", "response": resp, "ok": False}
        if ws_up:
            if "text" in content:
                cc = self.edge.send_direct_text(
                    str(thread_id), str(content["text"]),
                    replied_to_item_id=(qk.get("id") if qk else None),
                    reply_to_message_id=(qmsg.get("message_id") if isinstance(qmsg, dict) else None))
                return {"transport": "ws", "client_context": cc, "reply": bool(qk)}
            if "react" in content:
                r = content["react"]
                cc = self.edge.send_reaction(
                    str(thread_id),
                    r.get("key", {}).get("id") or r.get("item_id", ""),
                    r.get("text", "❤️"),
                    created=(r.get("text", "❤️") != ""),
                    target_item_type=r.get("target_item_type", "text"))
                return {"transport": "ws", "client_context": cc}

        return {"ok": False, "error": "no send transport available (graphql failed and edge socket is down)"}

    def send_media(self, thread_id, file, kind: str = "photo") -> Any:
        """Send a photo or video DM (`file` = path or bytes)."""
        short = self._short_thread_id(thread_id)
        big = str(thread_id) if str(thread_id) != short else short
        ref = "https://www.instagram.com/direct/t/%s/" % big
        tok = self._gql_token_bundle()
        fbid = web_mercury_upload(self.cookies, file, kind=kind, proxy=self.proxy, tokens=tok, referer=ref)
        if not fbid:
            return {"ok": False, "error": "mercury upload returned no attachment id"}
        r = web_graphql_call(self.cookies, "media_send", build_media_send_variables(short, fbid),
                             proxy=self.proxy, referer=ref, tokens=tok)
        ok = bool(isinstance(r, dict) and r.get("data")) and not r.get("errors")
        self.ev.emit("media.send", {"thread_id": big, "kind": kind, "attachment_fbid": fbid,
                                    "ok": ok, "transport": "graphql"})
        return {"ok": ok, "transport": "graphql", "attachment_fbid": fbid, "response": r}

    def _voice_waveform(self, wav_path, hz: int = 9):
        import wave, audioop
        w = wave.open(wav_path, "rb")
        frames, sw, fr = w.getnframes(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(frames); w.close()
        dur = frames / float(fr) if fr else 0.0
        n = max(1, int(round(dur * hz)))
        if not frames or not raw:
            return [0.0] * n, hz
        buck = max(1, frames // n); amps = []
        for i in range(n):
            frag = raw[i * buck * sw:(i + 1) * buck * sw]
            if not frag:
                break
            amps.append(audioop.max(frag, sw) / 32768.0)
        mx = max(amps) or 1.0
        return [round(a / mx, 4) for a in amps], hz

    def send_voice(self, thread_id, audio, *, max_seconds: int = 60, waveform=None) -> dict:
        """Send a voice note from `audio` (any audio file, transcoded to opus/ogg, capped at `max_seconds`)."""
        import os, json as _json, subprocess, tempfile, time as _t
        short = self._short_thread_id(thread_id)
        big = str(thread_id) if str(thread_id) != short else short
        ref = "https://www.instagram.com/direct/t/%s/" % big
        is_opus = isinstance(audio, str) and audio.lower().endswith((".ogg", ".opus"))
        pcm_wav = None
        if is_opus and waveform is not None:
            ogg_bytes = open(audio, "rb").read()
        else:
            tmp = tempfile.mkdtemp()
            ogg_p, wav_p = os.path.join(tmp, "v.ogg"), os.path.join(tmp, "v.wav")
            try:
                subprocess.run(["ffmpeg", "-y", "-i", str(audio), "-t", str(max_seconds), "-c:a", "libopus",
                                "-b:a", "48k", ogg_p], capture_output=True, timeout=180, check=True)
                subprocess.run(["ffmpeg", "-y", "-i", str(audio), "-t", str(max_seconds), "-ac", "1",
                                "-ar", "16000", wav_p], capture_output=True, timeout=180, check=True)
            except (OSError, subprocess.SubprocessError) as e:
                return {"ok": False, "error": "ffmpeg needed to send this audio as a voice note (%s)" % type(e).__name__}
            ogg_bytes = open(ogg_p, "rb").read()
            pcm_wav = wav_p
        if waveform is not None:
            amps = [max(0.0, min(1.0, float(a))) for a in waveform]
            hz = 9
        else:
            amps, hz = self._voice_waveform(pcm_wav)
        wf = _json.dumps({"amplitudes": amps, "sampling_freq": int(hz)})
        tok = self._gql_token_bundle()
        fid = web_mercury_upload(self.cookies, ogg_bytes, kind="voice", content_type="audio/ogg",
                                 filename="audioclip-%d.ogg" % int(_t.time() * 1000),
                                 extra_fields={"voice_clip": "true", "voice_clip_waveform_data": wf},
                                 proxy=self.proxy, tokens=tok, referer=ref)
        if not fid:
            return {"ok": False, "error": "voice upload returned no audio id"}
        r = web_graphql_call(self.cookies, "media_send", build_media_send_variables(short, fid),
                             proxy=self.proxy, referer=ref, tokens=tok)
        ok = bool(isinstance(r, dict) and r.get("data")) and not r.get("errors")
        self.ev.emit("media.send", {"thread_id": big, "kind": "voice", "attachment_fbid": fid,
                                    "ok": ok, "transport": "graphql"})
        return {"ok": ok, "transport": "graphql", "attachment_fbid": fid, "response": r}

    def unsend_message(self, thread_id, message_id: str = None) -> dict:
        """Unsend (delete for everyone) a message by `message_id`."""
        if not message_id:
            return {"ok": False, "error": "unsend_message needs a message_id (mid.$…)"}
        big = str(thread_id)
        r = web_graphql_call(self.cookies, "unsend_message",
                             {"message_id": str(message_id), "send_data": {"thread_id": big}},
                             proxy=self.proxy, referer="https://www.instagram.com/direct/t/%s/" % big,
                             tokens=self._gql_token_bundle())
        ok = bool(isinstance(r, dict) and r.get("data")) and not r.get("errors")
        self.ev.emit("messages.delete", {"thread_id": big, "message_id": str(message_id), "ok": ok})
        return {"ok": ok, "transport": "graphql", "response": r}

    def edit_message(self, thread_id, new_text: str, message_id: str = None) -> dict:
        """Edit a sent message to `new_text` (by `message_id`)."""
        if not message_id:
            return {"ok": False, "error": "edit_message needs a message_id (mid.$…)"}
        big = str(thread_id)
        oti = str(int(time.time() * 1000) * 1000 + int(uuid.uuid4().int % 1000000))
        r = web_graphql_call(self.cookies, "edit_message",
                             {"body": str(new_text), "offline_threading_id": oti, "target_item_id": "",
                              "target_message_id": str(message_id), "thread_id": big},
                             proxy=self.proxy, referer="https://www.instagram.com/direct/t/%s/" % big,
                             tokens=self._gql_token_bundle())
        ok = bool(isinstance(r, dict) and r.get("data")) and not r.get("errors")
        self.ev.emit("messages.update", {"thread_id": big, "message_id": str(message_id),
                                         "editText": new_text, "ok": ok})
        return {"ok": ok, "transport": "graphql", "response": r}
