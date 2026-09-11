from __future__ import annotations
from typing import List
from ..webapi import web_api, rupload_photo, resolve_user_id
import time as _time

class StoriesMixin:
    """Stories: read the tray, a user's active story, viewers/likers; add, delete, like a story."""

    def story_tray(self) -> List[dict]:
        d = web_api(self.cookies, "/api/v1/feed/reels_tray/", proxy=self.proxy)
        out = []
        for t in (d.get("tray") or []):
            u = t.get("user") or {}
            out.append({"user": u.get("username"), "pk": str(u.get("pk") or ""),
                        "item_count": t.get("media_count"), "seen": t.get("seen"),
                        "latest_ts": t.get("latest_reel_media")})
        return out

    def get_user_story(self, who) -> List[dict]:
        """A user's active story items → [{id, taken_at, type, view_count}]."""
        pk, _ = resolve_user_id(self.cookies, who, proxy=self.proxy)
        d = web_api(self.cookies, "/api/v1/feed/user/%s/story/" % pk, proxy=self.proxy)
        reel = (d.get("reel") or {})
        return [{"id": str(i.get("pk") or i.get("id")), "taken_at": i.get("taken_at"),
                 "type": i.get("media_type"), "view_count": i.get("view_count"),
                 "expiring_at": i.get("expiring_at")} for i in (reel.get("items") or [])]

    def story_viewers(self, story_media_id) -> dict:
        """Who viewed (and liked) one of YOUR story items. → {total, viewers:[{pk,username,liked}]}."""
        d = web_api(self.cookies, "/api/v1/media/%s/list_reel_media_viewer/" % story_media_id,
                    params={"supported_capabilities_new": "[]"}, proxy=self.proxy)
        viewers = [{"pk": str(u.get("pk")), "username": u.get("username"),
                    "full_name": u.get("full_name"), "liked": bool(u.get("reel_reaction"))}
                   for u in (d.get("users") or [])]
        return {"total": d.get("user_count") or d.get("total_viewer_count") or len(viewers),
                "viewers": viewers}

    story_likers = story_viewers

    def like_story(self, story_media_id) -> dict:
        """Like/react to a story."""
        return self.like_media(story_media_id, container_module="reel_feed_timeline")

    def delete_story(self, story_media_id) -> dict:
        """Delete one of your story items."""
        r = web_api(self.cookies, "/api/v1/media/%s/delete/" % story_media_id, method="POST",
                    data={"media_type": "STORY"}, proxy=self.proxy)
        ok = r.get("status") == "ok"
        self.ev.emit("story.deleted", {"media_id": str(story_media_id), "ok": ok})
        return {"ok": ok, "raw": r}

    def add_story(self, image_path: str) -> dict:
        """Post a photo to your story. Uploads the JPEG then configures it as a story."""
        with open(image_path, "rb") as f:
            data = f.read()
        upload_id = rupload_photo(self.cookies, data, proxy=self.proxy)
        if not upload_id:
            return {"ok": False, "reason": "upload_failed"}
        r = web_api(self.cookies, "/api/v1/media/configure_to_story/", method="POST",
                    data={"upload_id": upload_id, "source_type": "3",
                          "configure_mode": "1", "client_shared_at": str(int(_time.time())),
                          "client_timestamp": str(int(_time.time()))}, proxy=self.proxy)
        mid = (r.get("media") or {}).get("pk") or (r.get("media") or {}).get("id")
        ok = r.get("status") == "ok"
        self.ev.emit("story.posted", {"media_id": str(mid) if mid else None, "ok": ok})
        return {"ok": ok, "media_id": str(mid) if mid else None, "raw": r}
