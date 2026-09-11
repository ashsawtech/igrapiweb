# igrapiweb · created by ashsawtech · https://github.com/ashsawtech/igrapiweb · attribution required (see _attrib.py)
"""Social graph handler: follow management + rich profile lookup (pure-Python web private API)."""
from __future__ import annotations
from typing import List
from ..webapi import web_api, resolve_user_id, WEB_BASE

class SocialMixin:

    def get_user(self, who) -> dict:
        """Rich profile for a username or pk (id, name, bio, counts, verification, relationship flags)."""
        pk, u = resolve_user_id(self.cookies, who, proxy=self.proxy)
        if not u:
            u = ((web_api(self.cookies, "/api/v1/users/%s/info/" % pk, proxy=self.proxy) or {}).get("user") or {})
        fr = u.get("friendship_status") or {}
        el = (u.get("edge_followed_by") or {}).get("count")
        ef = (u.get("edge_follow") or {}).get("count")
        return {
            "pk": str(u.get("id") or u.get("pk") or pk),
            "username": u.get("username"),
            "full_name": u.get("full_name"),
            "biography": u.get("biography"),
            "is_private": u.get("is_private"),
            "is_verified": u.get("is_verified"),
            "category": u.get("category") or u.get("category_name"),
            "external_url": u.get("external_url"),
            "profile_pic_url": u.get("profile_pic_url_hd") or u.get("profile_pic_url"),
            "follower_count": u.get("follower_count", el),
            "following_count": u.get("following_count", ef),
            "media_count": u.get("media_count") or (u.get("edge_owner_to_timeline_media") or {}).get("count"),
            "followed_by_viewer": u.get("followed_by_viewer", fr.get("following")),
            "follows_viewer": u.get("follows_viewer", fr.get("followed_by")),
            "requested_by_viewer": u.get("requested_by_viewer", fr.get("outgoing_request")),
            "raw": u,
        }

    _FOLLOW_MUT = {"follow": ("26508036048874888", "usePolarisFollowMutation"),
                   "unfollow": ("27789106940691111", "usePolarisUnfollowMutation")}

    def _follow_gql(self, kind: str, who) -> dict:
        from ..graphql import web_graphql_call
        pk, _ = resolve_user_id(self.cookies, who, proxy=self.proxy)
        if not pk:
            return {"ok": False, "reason": "user_not_found", "who": who}
        did, fname = self._FOLLOW_MUT[kind]
        r = web_graphql_call(self.cookies, None, {"target_user_id": str(pk), "container_module": "profile",
                             "nav_chain": ""}, tokens=self._gql_token_bundle(), proxy=self.proxy,
                             doc_id=did, friendly_name=fname, referer=WEB_BASE + "/")
        fs = (((r.get("data") or {}).get("xdt_create_friendship")
               or (r.get("data") or {}).get("xdt_destroy_friendship") or {}).get("friendship_status"))
        ok = bool(fs) and not r.get("errors")
        self.ev.emit("friendship.update", {"action": kind, "pk": str(pk), "friendship_status": fs})
        return {"ok": ok, "pk": str(pk), "friendship_status": fs, "raw": r}

    def follow(self, who) -> dict:
        """Follow (or follow-back / send a request to a private account)."""
        return self._follow_gql("follow", who)

    def unfollow(self, who) -> dict:
        return self._follow_gql("unfollow", who)

    def _resolve_pk_any(self, who) -> str:
        w = str(who)
        if w.isdigit():
            return w
        pk, _ = resolve_user_id(self.cookies, w, proxy=self.proxy)
        return str(pk or "")

    _WEB_FR = {"approve": "approve", "ignore": "ignore"}

    def _fr_action(self, action: str, who) -> dict:
        pk = self._resolve_pk_any(who)
        if not pk:
            return {"ok": False, "reason": "user_not_found"}
        r = web_api(self.cookies, "/api/v1/web/friendships/%s/%s/" % (pk, self._WEB_FR[action]),
                    method="POST", data={}, referer=WEB_BASE + "/", proxy=self.proxy)
        ok = r.get("status") == "ok" or "friendship_status" in r or r.get("result") == "success"
        self.ev.emit("friendship.update", {"action": action, "pk": pk, "raw": r})
        return {"ok": ok, "pk": pk, "friendship_status": r.get("friendship_status"), "raw": r}

    def accept_follow_request(self, who) -> dict:
        """Approve an incoming follow request."""
        return self._fr_action("approve", who)

    def reject_follow_request(self, who) -> dict:
        """Deny an incoming follow request."""
        return self._fr_action("ignore", who)

    def follow_back(self, who) -> dict:
        """Follow someone who follows you."""
        return self.follow(who)

    def pending_follow_requests(self) -> List[dict]:
        """Incoming follow requests awaiting your approval."""
        r = web_api(self.cookies, "/api/v1/friendships/pending/", proxy=self.proxy)
        return [{"pk": str(u.get("pk") or u.get("id")), "username": u.get("username"),
                 "full_name": u.get("full_name")} for u in (r.get("users") or [])]

    def friendship_status(self, who) -> dict:
        pk, _ = resolve_user_id(self.cookies, who, proxy=self.proxy)
        return web_api(self.cookies, "/api/v1/friendships/show/%s/" % pk, proxy=self.proxy)

    def change_profile_pic(self, image_path: str = None, image_bytes: bytes = None) -> dict:
        """Set the account's profile photo from a local JPEG (multipart web endpoint)."""
        import requests
        from ..webapi import ensure_claim, ensure_csrftoken, _jar
        from ..protocol import IG_WEB_APP_ID, _GQL_UA
        if image_bytes is None:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
        ensure_claim(self.cookies, proxy=self.proxy); ensure_csrftoken(self.cookies, proxy=self.proxy)
        h = {"User-Agent": _GQL_UA, "X-IG-App-ID": str(IG_WEB_APP_ID),
             "X-CSRFToken": self.cookies.get("csrftoken", ""), "X-Requested-With": "XMLHttpRequest",
             "X-IG-WWW-Claim": self.cookies.get("_wwwclaim") or "0",
             "Referer": WEB_BASE + "/accounts/edit/", "Origin": WEB_BASE}
        r = requests.post(WEB_BASE + "/api/v1/web/accounts/web_change_profile_picture/", headers=h,
                          cookies=_jar(self.cookies),
                          files={"profile_pic": ("profile.jpg", image_bytes, "image/jpeg")},
                          proxies=({"https": self.proxy, "http": self.proxy} if self.proxy else None),
                          timeout=60, allow_redirects=False)
        if r.status_code in (301, 302, 303, 307, 308):
            j = {"_status": r.status_code, "_redirect": True}
        else:
            try:
                j = r.json()
            except Exception:
                j = {"_status": r.status_code, "_body": r.text[:200]}
        ok = j.get("status") == "ok" or bool(j.get("changed_profile"))
        self.ev.emit("profile.updated", {"field": "profile_pic", "ok": ok})
        return {"ok": ok, "raw": j}

    def copy_profile_pic_from(self, who) -> dict:
        """Copy another account's profile photo onto this one (their id/name are unchanged)."""
        import requests
        u = self.get_user(who)
        url = u.get("profile_pic_url")
        if not url:
            return {"ok": False, "reason": "no_source_pic"}
        img = requests.get(url, proxies=({"https": self.proxy, "http": self.proxy} if self.proxy else None),
                           timeout=60).content
        return self.change_profile_pic(image_bytes=img)
