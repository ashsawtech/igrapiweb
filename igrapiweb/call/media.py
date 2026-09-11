"""WebRTC media plane via aiortc: a thin wrapper around RTCPeerConnection for IG call media (Opus audio)."""
from __future__ import annotations
from typing import List, Optional, Callable

class CallMedia:
    def __init__(self, ice_servers: List[dict], *, audio_source: Optional[str] = None,
                 record_to: Optional[str] = None, relay_only: bool = False, audio_only: bool = False):
        """ice_servers come from http.turn_discovery; relay_only routes all media through the TURN relay."""
        from . import turn_indications
        from aiortc import RTCPeerConnection, RTCConfiguration, RTCIceServer
        if relay_only:
            turn_indications.set_relay_only(True)
            ice_servers = [s for s in ice_servers if any("turn:" in u for u in s["urls"])]
        servers = []
        for s in ice_servers:
            servers.append(RTCIceServer(urls=s["urls"], username=s.get("username"),
                                        credential=s.get("credential")))
        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=servers))
        self._audio_source = audio_source
        self._record_to = record_to
        self._audio_only = audio_only
        self._recorder = None
        self.on_state: Optional[Callable[[str], None]] = None
        self.on_track: Optional[Callable] = None
        self._wire_events()

    def _wire_events(self):
        @self.pc.on("connectionstatechange")
        async def _():
            if self.on_state:
                self.on_state(self.pc.connectionState)

        @self.pc.on("track")
        async def _(track):
            if self._record_to and track.kind == "audio" and self._recorder is None:
                from aiortc.contrib.media import MediaRecorder
                self._recorder = MediaRecorder(self._record_to)
                self._recorder.addTrack(track)
                await self._recorder.start()
            if self.on_track:
                self.on_track(track)

    def _add_local_audio(self):

        if not self._audio_only:
            self.pc.createDataChannel("data")
        if self._audio_source:
            from aiortc.contrib.media import MediaPlayer
            player = MediaPlayer(self._audio_source)
            if player.audio:
                self.pc.addTrack(player.audio)
            else:
                from aiortc.mediastreams import AudioStreamTrack
                self.pc.addTrack(AudioStreamTrack())
        else:
            from aiortc.mediastreams import AudioStreamTrack
            self.pc.addTrack(AudioStreamTrack())
        if not self._audio_only:
            try:
                self.pc.addTransceiver("video", direction="recvonly")
            except Exception:
                pass

    async def create_offer(self) -> str:
        """Add the local audio track, create + set the local offer, return its SDP for signaling."""
        self._add_local_audio()
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)
        return self.pc.localDescription.sdp

    async def accept_answer(self, sdp: str) -> None:
        from aiortc import RTCSessionDescription
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="answer"))

    async def apply_sfu_sdp(self, sdp: str) -> str:
        """Apply an inbound SFU answer (provisional → `pranswer`, active → `answer`); returns the type applied."""
        from aiortc import RTCSessionDescription
        adir, cur = None, None
        for ln in sdp.replace("\r", "").split("\n"):
            if ln.startswith("m="):
                cur = ln[2:].split()[0]
            elif cur == "audio" and ln[:2] == "a=" and ln[2:] in ("sendrecv", "recvonly", "sendonly", "inactive"):
                adir = ln[2:]
                break
        active = adir not in (None, "inactive")
        typ = "answer" if (active or self.pc.signalingState != "have-local-offer") else "pranswer"
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=typ))
        return typ

    async def renegotiate(self, sdp: str) -> str:
        """Apply a mid-call renegotiation offer from the SFU and return our answer SDP."""
        from aiortc import RTCSessionDescription
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="offer"))
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        return self.pc.localDescription.sdp

    async def apply_remote_offer(self, sdp: str) -> str:
        """Answering side: set the caller's offer, attach our audio to the existing transceiver, return our answer SDP."""
        from aiortc import RTCSessionDescription
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="offer"))
        track = None
        if self._audio_source:
            from aiortc.contrib.media import MediaPlayer
            self._player = MediaPlayer(self._audio_source)
            track = self._player.audio
        if track is None:
            from aiortc.mediastreams import AudioStreamTrack
            track = AudioStreamTrack()
        for t in self.pc.getTransceivers():
            if t.kind == "audio":
                t.sender.replaceTrack(track)
                t.direction = "sendrecv"
                break
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        return self.pc.localDescription.sdp

    async def force_receive_audio(self) -> bool:
        """Force the audio receiver to start (aiortc otherwise drops the SFU's audio on the ``recvonly`` m-line)."""
        for t in self.pc.getTransceivers():
            if t.kind != "audio":
                continue
            if t.currentDirection in ("recvonly", "sendrecv"):
                return True
            try:
                t._setCurrentDirection("sendrecv")
                params = self.pc._RTCPeerConnection__remoteRtp(t)
                await t.receiver.receive(params)
                track = t.receiver.track
                if self._record_to and self._recorder is None and track is not None:
                    from aiortc.contrib.media import MediaRecorder
                    self._recorder = MediaRecorder(self._record_to)
                    self._recorder.addTrack(track)
                    await self._recorder.start()
                if self.on_track and track is not None:
                    self.on_track(track)
                return True
            except Exception:
                return False
        return False

    async def add_remote_candidate(self, cand_str: str) -> None:
        """Feed an ICE candidate the SFU trickled over rpsignaling into aiortc."""
        from aiortc.sdp import candidate_from_sdp
        s = cand_str.split("candidate:", 1)[-1].strip()
        try:
            c = candidate_from_sdp(s)
            c.sdpMid = "0"
            c.sdpMLineIndex = 0
            await self.pc.addIceCandidate(c)
        except Exception:
            pass

    def local_candidates(self):
        """Our gathered ICE candidate lines (from the offer SDP), for trickling over rpsignaling."""
        import re
        sdp = self.pc.localDescription.sdp if self.pc.localDescription else ""
        uf = re.search(r'a=ice-ufrag:(\S+)', sdp)
        return re.findall(r'a=candidate:(\S.*)', sdp), (uf.group(1) if uf else "")

    def set_mic(self, on: bool) -> None:
        """Mute/unmute our microphone by attaching/detaching the audio sender track."""
        tr = next((t for t in self.pc.getTransceivers() if t.kind == "audio"), None)
        if not tr or not tr.sender:
            return
        if on:
            track = None
            if self._audio_source:
                from aiortc.contrib.media import MediaPlayer
                self._player = MediaPlayer(self._audio_source)
                track = self._player.audio
            if track is None:
                from aiortc.mediastreams import AudioStreamTrack
                track = AudioStreamTrack()
            tr.sender.replaceTrack(track)
        else:
            tr.sender.replaceTrack(None)

    def set_video(self, on: bool, source: Optional[str] = None) -> None:
        """Turn our outgoing video on (from `source`) or off by attaching/detaching the local video track."""
        tr = next((t for t in self.pc.getTransceivers() if t.kind == "video"), None)
        if not tr or not tr.sender:
            return
        if on and source:
            from aiortc.contrib.media import MediaPlayer
            self._vplayer = MediaPlayer(source)
            if self._vplayer.video:
                tr.sender.replaceTrack(self._vplayer.video)
        else:
            tr.sender.replaceTrack(None)

    async def close(self) -> None:
        if self._recorder:
            try: await self._recorder.stop()
            except Exception: pass
        await self.pc.close()
