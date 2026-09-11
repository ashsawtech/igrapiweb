# igrapiweb · created by ashsawtech · https://github.com/ashsawtech/igrapiweb · attribution required (see _attrib.py)
from __future__ import annotations
from typing import Optional, List
from ..webapi import web_api, resolve_user_id, WEB_BASE
from ..graphql import web_graphql_call
from ..protocol import _GQL_UA

WEB_MUT = {
    "follow":   ("26508036048874888", "usePolarisFollowMutation"),
    "unfollow": ("9469841143062773",  "usePolarisUnfollowMutation"),
    "like":     ("27182485238052618", "usePolarisLikeMediaXIGLikeMutation"),
    "unlike":   ("27345296031770102", "usePolarisLikeMediaXIGUnlikeMutation"),
    "save":     ("27365486596441074", "usePolarisSaveMediaSaveMutation"),
    "unsave":   ("27371251859134880", "usePolarisSaveMediaUnsaveMutation"),
    "comment":  ("27261905640092552", "PolarisPostCommentInputRevampedMutation"),
}
_COMMENT_CONN = ('client:root:__PolarisPostComments__xdt_api__v1__media__media_id__comments__'
                 'connection_connection(data:{},media_id:"%s",sort_order:"popular")')
_WEB_REELS_DOC = "37945290971781723"

class FeedMixin:
    """Reels/posts: browse, read metadata, and act (like, save, comment, share)."""

    def _mut(self, name: str, variables: dict, referer: Optional[str] = None) -> dict:
        did, fname = WEB_MUT[name]
        tok = self._gql_token_bundle()
        return web_graphql_call(self.cookies, None, variables, tokens=tok, proxy=self.proxy,
                                doc_id=did, friendly_name=fname,
                                referer=referer or (WEB_BASE + "/"))

    def _actor(self) -> str:
        return (self._gql_token_bundle() or {}).get("fbid") or str(self.web_user_id or "")

    def media_info(self, media_id) -> dict:
        """Full media/reel metadata (owner, id, type, view/like/comment counts, caption, video URL)."""
        d = web_api(self.cookies, "/api/v1/media/%s/info/" % media_id, proxy=self.proxy)
        m = ((d.get("items") or [{}])[0]) if d.get("items") else {}
        u = m.get("user") or {}
        return {
            "id": str(m.get("pk") or m.get("id") or media_id),
            "code": m.get("code"),
            "owner": u.get("username"),
            "owner_id": str(u.get("pk") or u.get("id") or ""),
            "owner_name": u.get("full_name"),
            "type": {1: "photo", 2: "video/reel", 8: "album"}.get(m.get("media_type"), m.get("media_type")),
            "view_count": m.get("view_count") or m.get("play_count"),
            "play_count": m.get("play_count"),
            "like_count": m.get("like_count"),
            "comment_count": m.get("comment_count"),
            "caption": (m.get("caption") or {}).get("text"),
            "taken_at": m.get("taken_at"),
            "video_url": ((m.get("video_versions") or [{}])[0]).get("url") if m.get("video_versions") else None,
            "raw": m,
        }

    def _norm_reel(self, m: dict) -> dict:
        u = m.get("user") or {}
        return {"id": str(m.get("pk") or m.get("id")), "code": m.get("code"),
                "owner": u.get("username"), "owner_id": str(u.get("pk") or ""),
                "type": m.get("media_type"), "view_count": m.get("play_count") or m.get("view_count"),
                "play_count": m.get("play_count"), "like_count": m.get("like_count"),
                "comment_count": m.get("comment_count"),
                "video_url": ((m.get("video_versions") or [{}])[0]).get("url") if m.get("video_versions") else None,
                "caption": (m.get("caption") or {}).get("text")}

    def user_reels(self, who, count: int = 12) -> List[dict]:
        """A user's reels → [{id, code, owner, view_count, ...}]."""
        pk = (self._resolve_pk_any(who) if hasattr(self, "_resolve_pk_any") else None) \
            or resolve_user_id(self.cookies, who, proxy=self.proxy)[0]
        if pk:
            try:
                v = {"data": {"include_feed_video": True, "page_size": count, "target_user_id": str(pk)},
                     "user_id": str(pk),
                     "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": False}
                r = web_graphql_call(self.cookies, None, v, tokens=self._gql_token_bundle(), proxy=self.proxy,
                                     doc_id=_WEB_REELS_DOC, friendly_name="PolarisProfileReelsTabContentQuery",
                                     referer=WEB_BASE + "/")
                edges = (((r.get("data") or {}).get("fetch__XDTUserDict") or {}).get("clips_connection") or {}).get("edges") or []
                if edges:
                    return [self._norm_reel((e.get("node") or {}).get("media") or e.get("node") or {}) for e in edges]
            except Exception:
                pass
        pk2, _ = resolve_user_id(self.cookies, who, proxy=self.proxy)
        d = web_api(self.cookies, "/api/v1/feed/user/%s/" % (pk or pk2), params={"count": count}, proxy=self.proxy)
        return [self._norm_reel(it) for it in (d.get("items") or [])]

    def most_viewed_reel(self, who) -> Optional[dict]:
        reels = [r for r in self.user_reels(who, count=50) if (r.get("view_count") or r.get("play_count"))]
        return max(reels, key=lambda r: r.get("view_count") or r.get("play_count") or 0, default=None)

    def reel_comments(self, media_id, count: int = 20) -> List[dict]:
        d = web_api(self.cookies, "/api/v1/media/%s/comments/" % media_id, params={"count": count}, proxy=self.proxy)
        return [{"id": str(c.get("pk")), "text": c.get("text"), "user": (c.get("user") or {}).get("username"),
                 "like_count": c.get("comment_like_count")} for c in (d.get("comments") or [])]

    def like_media(self, media_id, container_module: str = "feed_timeline") -> dict:
        v = {"input": {"media_id": str(media_id), "actor_id": self._actor(),
                       "container_module": container_module, "client_mutation_id": "1"}}
        return self._act("like", v, media_id)

    def unlike_media(self, media_id, container_module: str = "feed_timeline") -> dict:
        v = {"input": {"media_id": str(media_id), "actor_id": self._actor(),
                       "container_module": container_module, "client_mutation_id": "1"}}
        return self._act("unlike", v, media_id)

    def save_media(self, media_id, container_module: str = "feed_timeline") -> dict:
        v = {"input": {"media_id": str(media_id), "actor_id": self._actor(),
                       "container_module": container_module, "client_mutation_id": "1"}}
        return self._act("save", v, media_id)

    def unsave_media(self, media_id, container_module: str = "feed_timeline") -> dict:
        v = {"input": {"media_id": str(media_id), "actor_id": self._actor(),
                       "container_module": container_module, "client_mutation_id": "1"}}
        return self._act("unsave", v, media_id)

    def comment_media(self, media_id, text: str) -> dict:
        """Post a comment on a reel/post."""
        v = {"connections": [_COMMENT_CONN % str(media_id)],
             "data": {"comment_text": text, "media_id": str(media_id)}}
        r = self._mut("comment", v, referer=WEB_BASE + "/")
        d = r.get("data") or {}
        cid = (((d.get("xdt_media_add_comment") or {}).get("comment") or {}).get("pk"))
        ok = bool(d) and not r.get("errors")
        self.ev.emit("media.action", {"action": "comment", "media_id": str(media_id), "ok": ok})
        return {"ok": ok, "comment_id": cid, "raw": r}

    def share_reel(self, media_id, thread_id, *, note: str = "") -> dict:
        """Share a reel/post into a DM thread by sending its permalink; `note` is optional text."""
        info = self.media_info(media_id)
        code = info.get("code")
        url = ("https://www.instagram.com/reel/%s/" % code) if code else ("https://www.instagram.com/p/%s/" % media_id)
        text = (note + " " + url).strip() if note else url
        res = self.send_message(thread_id, {"text": text})
        self.ev.emit("media.action", {"action": "share", "media_id": str(media_id),
                                      "thread": str(thread_id), "ok": True})
        return {"ok": True, "via": "link", "shared": url, "send_result": res}

    def watch_reel(self, media_id, *, download_to: Optional[str] = None,
                   max_bytes: int = 2_000_000) -> dict:
        """Watch a reel: resolve its video URL and stream the media (registers a view); `download_to` saves the mp4."""
        info = self.media_info(media_id)
        url = info.get("video_url")
        streamed = 0
        if url:
            import requests
            pr = {"https": self.proxy, "http": self.proxy} if self.proxy else None
            try:
                with requests.get(url, stream=True, timeout=60, proxies=pr,
                                  headers={"User-Agent": _GQL_UA}) as resp:
                    f = open(download_to, "wb") if download_to else None
                    for chunk in resp.iter_content(65536):
                        streamed += len(chunk)
                        if f:
                            f.write(chunk)
                        elif streamed >= max_bytes:
                            break
                    if f:
                        f.close()
            except Exception:
                pass
        self.ev.emit("media.action", {"action": "watch", "media_id": str(media_id)})
        return {"media_id": str(media_id), "owner": info.get("owner"), "video_url": url,
                "view_count": info.get("view_count"), "bytes_streamed": streamed}

    download_reel = lambda self, media_id, path: self.watch_reel(media_id, download_to=path)

    def reels_feed(self, who, *, max_id: Optional[str] = None, amount: int = 12) -> dict:
        """A page of a user's reels → {reels:[...], next_max_id, more}."""
        items = self.user_reels(who, count=amount)
        reels = [{**r, "owner": r.get("owner") or (who if isinstance(who, str) else None)} for r in items]
        return {"reels": reels, "next_max_id": None, "more": False, "status": "ok"}

    def open_reels(self, who) -> Optional[dict]:
        """Open a user's reels and return the first; call next_reel() to advance."""
        page = self.reels_feed(who)
        self._reel_buf = page.get("reels") or []
        self._reel_who = who
        self._reel_next = None
        return self._reel_buf.pop(0) if self._reel_buf else None

    def next_reel(self, who=None) -> Optional[dict]:
        """Return the next reel for `who` (or a prior open_reels); None at the end."""
        who = who if who is not None else getattr(self, "_reel_who", None)
        if who is None:
            return None
        if not getattr(self, "_reel_buf", None):
            page = self.reels_feed(who, max_id=getattr(self, "_reel_next", None))
            self._reel_buf = page.get("reels") or []
            self._reel_next = page.get("next_max_id")
            self._reel_who = who
            if not self._reel_buf:
                return None
        return self._reel_buf.pop(0)

    save_reel = save_media
    like_reel = like_media
    comment_reel = comment_media

    def _act(self, name: str, variables: dict, media_id) -> dict:
        r = self._mut(name, variables, referer=WEB_BASE + "/reels/")
        d = r.get("data") or {}
        ok = bool(d) and not r.get("errors")
        self.ev.emit("media.action", {"action": name, "media_id": str(media_id), "ok": ok})
        return {"ok": ok, "raw": r}
