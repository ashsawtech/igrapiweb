# igrapiweb · created by ashsawtech · https://github.com/ashsawtech/igrapiweb · attribution required (see _attrib.py)
"""Voice/video calls (Zenon RTC): rpsignaling for signaling, aiortc for media; call methods are async. Needs the `calls` extra."""
from __future__ import annotations
import threading
from typing import Optional, Dict
from .._common import *
from ..session import web_dgw_identity
from ..call import http as _ch, signaling as _cs, messages as _cm

class CallSession:
    """A live call: bundles the media (aiortc) + signaling channel so the caller can end it."""
    def __init__(self, room_id, media, signaling, thread_id):
        self.room_id = room_id
        self.media = media
        self.signaling = signaling
        self.thread_id = thread_id

    def mute(self):
        """Stop sending our audio (mic off)."""
        if self.media: self.media.set_mic(False)

    def unmute(self):
        """Resume sending our audio (mic on)."""
        if self.media: self.media.set_mic(True)

    def video_on(self, source):
        """Start sending video from `source` (a file/device path)."""
        if self.media: self.media.set_video(True, source)

    def video_off(self):
        """Stop sending video."""
        if self.media: self.media.set_video(False)

    async def end(self):
        try:
            if self.signaling:
                self.signaling.disconnect()
        finally:
            if self.media:
                await self.media.close()

class CallsMixin:
    """Instagram web calls (Zenon RTC) — pure-Python signaling over rpsignaling + aiortc media."""

    def _my_eimu(self, thread_id) -> Optional[str]:
        mm = self._member_map(thread_id)
        me = mm.get(str(self.web_user_id)) or mm.get(str(self.cookies.get("ds_user_id")))
        return me.get("eimu") if me else None

    def _peer_eimu(self, thread_id) -> Optional[str]:
        """The other participant's eimu in a 1:1 thread."""
        mine = str(self.web_user_id or self.cookies.get("ds_user_id"))
        seen = set()
        for info in self._member_map(thread_id).values():
            eimu, pk = info.get("eimu"), info.get("pk")
            if not eimu or eimu in seen:
                continue
            seen.add(eimu)
            if str(pk) != mine:
                return eimu
        return None

    def _my_participant_id(self, short_thread, peer_eimu, tokens):
        """My Zenon participant id (== the offer envelope's f19.f1) = StartCallPeerDetails all_participants
        minus the peer. Distinct from the viewer FBID (actor_id) and the pk."""
        try:
            spd = _ch.start_call_peer_details(self.cookies, ig_thread_id=short_thread, peer_id=peer_eimu,
                                              tokens=tokens, proxy=self.proxy)
            ids = [n["id"] for n in spd["data"]["zenon_app"]["door"]["all_participants"]["nodes"]]
            return next((i for i in ids if i != peer_eimu), None)
        except Exception:
            return None

    async def place_call(self, thread_id, *, audio_source: Optional[str] = None,
                         record_to: Optional[str] = None, relay_only: bool = False,
                         audio_only: bool = False) -> "CallSession":
        """Ring a 1:1 thread and negotiate media. Returns a :class:`CallSession` (end with ``await s.end()``)."""
        import random
        from ..call.media import CallMedia
        short = self._short_thread_id(thread_id)
        tokens = self._gql_token_bundle()
        identity = web_dgw_identity(self.cookies, thread_id, proxy=self.proxy)
        actor = identity.get("fbid") or tokens.get("fbid")
        peer_eimu = self._peer_eimu(thread_id)
        if not (actor and peer_eimu):
            raise RuntimeError("could not resolve actor/peer for thread %s" % thread_id)
        my_part = self._my_participant_id(short, peer_eimu, tokens)
        ice = _ch.turn_discovery(self.cookies, short_thread=short, tokens=tokens, proxy=self.proxy)
        room_id = _ch.enter_call(self.cookies, ig_thread_id=short, peer_id=peer_eimu,
                                 actor_id=actor, tokens=tokens, proxy=self.proxy)
        if not room_id:
            raise RuntimeError("InstagramEnterCallMutation returned no room_id")
        if my_part:
            _ch.participants_state(self.cookies, ig_thread_id=short, peer_id=peer_eimu,
                                   user_id=my_part, tokens=tokens, proxy=self.proxy)
        media = CallMedia(ice, audio_source=audio_source, record_to=record_to, relay_only=relay_only, audio_only=audio_only)
        offer_sdp = await media.create_offer()
        sig = _cs.IGWebCallSignaling(self.cookies, actor, proxy=self.proxy,
                                     user_agent=getattr(self, 'user_agent', None) or _UA)
        sig.connect(identity, short)

        import asyncio
        loop = asyncio.get_event_loop()
        old = _cm.OFFER_TEMPLATE_OLD
        try:
            _t6 = _cm.load_type6_template()
        except Exception:
            _t6 = None
        sess_id = str(random.randint(10**9, 10**10 - 1))
        sender = str(random.randint(10**9, 10**10 - 1))
        part = my_part or old["participant_eimu"]
        cand_sent = [False]

        def _send_sdp(sdp_out):
            sig.send_offer(_cm.load_offer_template(), room_id=room_id, sdp=sdp_out,
                           old_room_id=old["room_id"],
                           session_id=sess_id, old_session_id=old["session_id"],
                           sender_eimu=sender, old_sender_eimu=old["sender_eimu"],
                           participant_eimu=part, old_participant_eimu=old["participant_eimu"])

        def _trickle(ids):

            if cand_sent[0]:
                return
            cand_sent[0] = True
            cands, ufrag = media.local_candidates()
            tmpl = _cm.load_candidate_template()
            for line in cands:
                cstr = "candidate:" + line.strip()
                if "ufrag" not in cstr and ufrag:
                    cstr += " generation 0 ufrag %s network-id 1 network-cost 50" % ufrag
                try:
                    sig.send_raw(_cm.build_candidate_frame(
                        tmpl, candidate=cstr, room_id=ids.get("room_id") or room_id,
                        session_id=ids.get("session_id") or sess_id, token=ids.get("token") or "",
                        id9=ids.get("id9") or "", eimu=ids.get("eimu") or part))
                except Exception as e:
                    self.ev.emit("call.error", {"room_id": room_id, "error": "cand:" + repr(e)[:60]})
            self.ev.emit("call.trickle", {"room_id": room_id, "sent": len(cands)})

        def _on_msg(parsed, raw):
            if parsed.get("sdp") and parsed.get("room_id") == room_id:
                async def _apply():
                    if media.pc.signalingState not in ("have-local-offer", "have-remote-pranswer"):
                        return
                    try:
                        typ = await media.apply_sfu_sdp(parsed["sdp"])
                        _trickle(_cm.answer_ids(raw))
                        if typ == "answer":
                            self.ev.emit("call.connected", {"room_id": room_id})
                            async def _recv():
                                for _ in range(6):
                                    await asyncio.sleep(1.0)
                                    if await media.force_receive_audio():
                                        self.ev.emit("call.receiving", {"room_id": room_id})
                                        break
                            asyncio.ensure_future(_recv())
                        else:
                            self.ev.emit("call.provisional", {"room_id": room_id})
                    except Exception as e:
                        self.ev.emit("call.error", {"room_id": room_id, "error": repr(e)})
                asyncio.run_coroutine_threadsafe(_apply(), loop)
            elif _t6 is not None and _cm.is_type6(raw):
                ids = _cm.parse_type6(raw)
                try:
                    sig.send_raw(_cm.build_type6_ack(_t6, room_id=ids.get("room_id") or room_id,
                        msg_id=ids.get("msg_id") or "", token=ids.get("token") or "",
                        id9=ids.get("id9") or "", eimu=part))
                    self.ev.emit("call.keepalive", {"room_id": room_id})
                except Exception:
                    pass
            elif b"candidate:" in raw:
                for c in _cm.parse_candidates(raw):
                    asyncio.run_coroutine_threadsafe(media.add_remote_candidate(c), loop)
        sig.on_message = _on_msg
        threading.Thread(target=sig.listen, daemon=True).start()
        _send_sdp(offer_sdp)
        self.ev.emit("call.outgoing", {"room_id": room_id, "thread_id": thread_id, "peer": peer_eimu})
        return CallSession(room_id, media, sig, thread_id)

    def start_call_listener(self, thread_id=None) -> "CallsMixin":
        """Connect rpsignaling and emit a structured ``call`` event on each incoming ring."""
        ident_thread = thread_id
        identity = web_dgw_identity(self.cookies, ident_thread, proxy=self.proxy)
        short = self._short_thread_id(thread_id) if thread_id else ""
        sig = _cs.IGWebCallSignaling(self.cookies, identity.get("fbid") or self.web_user_id,
                                     proxy=self.proxy, user_agent=getattr(self, 'user_agent', None) or _UA)
        sig.connect(identity, short)
        self._call_signaling = sig

        def _on_msg(parsed, raw):
            rd = parsed.get("ring_data")
            if rd:
                self.ev.emit("call", {
                    "room_id": parsed.get("room_id"),
                    "from": parsed.get("peer_id"),
                    "from_name": rd.get("display_name"),
                    "from_avatar": rd.get("display_uri"),
                    "ig_thread_id": rd.get("ig_thread_id"),
                    "msgr_thread_id": rd.get("msgr_thread_id"),
                    "is_video": None,
                    "server_info_data": parsed.get("server_info_data"),
                    "status": "offer",
                })
        sig.on_message = _on_msg
        threading.Thread(target=sig.listen, daemon=True).start()
        return self

    async def answer_call(self, ring: Dict, *, audio_source: Optional[str] = None,
                          record_to: Optional[str] = None, relay_only: bool = False) -> "CallSession":
        """Answer an incoming ``call`` event: join the room and negotiate media with the SFU."""
        import asyncio, random
        from ..call.media import CallMedia
        thread_id = ring.get("ig_thread_id")
        short = self._short_thread_id(thread_id)
        tokens = self._gql_token_bundle()
        identity = web_dgw_identity(self.cookies, thread_id, proxy=self.proxy)
        actor = identity.get("fbid") or tokens.get("fbid")
        peer = ring.get("from")
        room_id = _ch.enter_call(self.cookies, ig_thread_id=short, peer_id=peer, actor_id=actor,
                                 server_info_data=ring.get("server_info_data"),
                                 tokens=tokens, proxy=self.proxy) or ring.get("room_id")
        my_part = self._my_participant_id(short, peer, tokens) if peer else None
        if my_part:
            _ch.participants_state(self.cookies, ig_thread_id=short, peer_id=peer, user_id=my_part,
                                   server_info_data=ring.get("server_info_data"), tokens=tokens, proxy=self.proxy)
        ice = _ch.turn_discovery(self.cookies, short_thread=short, tokens=tokens, proxy=self.proxy)
        media = CallMedia(ice, audio_source=audio_source, record_to=record_to, relay_only=relay_only)
        offer_sdp = await media.create_offer()
        sig = getattr(self, "_call_signaling", None)
        started_here = sig is None
        if started_here:
            sig = _cs.IGWebCallSignaling(self.cookies, actor, proxy=self.proxy,
                                         user_agent=getattr(self, 'user_agent', None) or _UA)
            sig.connect(identity, short)
        loop = asyncio.get_event_loop()

        def _on_msg(parsed, raw):
            if parsed.get("sdp") and parsed.get("room_id") == room_id:
                async def _apply():
                    if media.pc.signalingState != "have-local-offer":
                        return
                    try:
                        await media.accept_answer(parsed["sdp"])
                        self.ev.emit("call.connected", {"room_id": room_id})
                    except Exception as e:
                        self.ev.emit("call.error", {"room_id": room_id, "error": repr(e)})
                asyncio.run_coroutine_threadsafe(_apply(), loop)
        sig.on_message = _on_msg
        if started_here:
            threading.Thread(target=sig.listen, daemon=True).start()
        old = _cm.OFFER_TEMPLATE_OLD
        sig.send_offer(_cm.load_offer_template(), room_id=room_id, sdp=offer_sdp,
                       old_room_id=old["room_id"],
                       session_id=str(random.randint(10**9, 10**10 - 1)), old_session_id=old["session_id"],
                       sender_eimu=str(random.randint(10**9, 10**10 - 1)), old_sender_eimu=old["sender_eimu"],
                       participant_eimu=my_part or old["participant_eimu"], old_participant_eimu=old["participant_eimu"])
        self.ev.emit("call.answered", {"room_id": room_id, "thread_id": thread_id})
        return CallSession(room_id, media, sig, thread_id)

    def decline_call(self, ring: Dict) -> None:
        """Decline an incoming ring. Emits ``call.declined`` locally and lets the ring lapse; the server
        times it out on its side."""
        self.ev.emit("call.declined", {"room_id": ring.get("room_id"), "from": ring.get("from")})
