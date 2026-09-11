# igrapiweb · created by ashsawtech · https://github.com/ashsawtech/igrapiweb · attribution required (see _attrib.py)
from __future__ import annotations
import json, time
from typing import Dict, List, Optional
from .._common import *

class GroupsMixin:
    """Group management: create, add/remove member, admin +/-, rename, nicknames + permission."""
    def _resolve_eimu(self, who) -> Optional[str]:
        """Resolve a username → `interop_messaging_user_fbid` (eimu fbid), cached from inbox participant lists."""
        w = str(who)
        if w.isdigit() and len(w) >= 15:
            return w
        if not hasattr(self, "_eimu_cache"):
            self._eimu_cache = {}
            try:
                import requests
                d = requests.get("https://www.instagram.com/api/v1/direct_v2/inbox/?persistentBadging=true&limit=50",
                                 cookies={k: v for k, v in self.cookies.items() if v},
                                 headers={"User-Agent": _GQL_UA, "X-IG-App-ID": str(IG_WEB_APP_ID),
                                          "Referer": "https://www.instagram.com/direct/inbox/"},
                                 proxies=({"https": self.proxy, "http": self.proxy} if self.proxy else None), timeout=30, allow_redirects=False).json()
                for t in d.get("inbox", {}).get("threads", []) or []:
                    for u in t.get("users", []) or []:
                        e = u.get("interop_messaging_user_fbid")
                        if u.get("username") and e:
                            self._eimu_cache[u["username"]] = str(e)
            except Exception:
                pass
        return self._eimu_cache.get(w)

    def _diagnose_blocked(self, eimus: List, name_by_eimu: Dict) -> Optional[List]:
        """Isolate which recipient(s) Instagram rejects via leave-one-out group creates; needs 3+ recipients."""
        if len(eimus) < 3:
            return None
        blocked = []
        for i, e in enumerate(eimus):
            rest = eimus[:i] + eimus[i + 1:]
            try:
                r = web_graphql_call(self.cookies, "create_group", build_create_group_variables(rest),
                                     proxy=self.proxy, referer="https://www.instagram.com/direct/inbox/",
                                     tokens=self._gql_token_bundle())
                if isinstance(r, dict) and r.get("data") and not r.get("errors"):
                    blocked.append(name_by_eimu.get(e, e))
            except Exception:
                pass
            time.sleep(1.0)
        return blocked

    def create_group(self, usernames, first_message: str = "", *, diagnose: bool = False, **_kw) -> dict:
        """Create a group DM from `usernames`; pass diagnose=True to name a blocked recipient on failure, and `first_message` to send an opening message."""
        us = list(usernames)
        if len(us) < 2:
            raise ValueError("a group needs at least 2 recipients")
        eimus, unresolved, name_by_eimu = [], [], {}
        for u in us:
            e = self._resolve_eimu(u)
            if e:
                eimus.append(e); name_by_eimu[e] = u
            else:
                unresolved.append(u)
        if unresolved:
            return {"ok": False, "error": "could not resolve eimu fbid for %s (need an existing thread, or pass eimu fbids)" % unresolved}
        r = web_graphql_call(self.cookies, "create_group", build_create_group_variables(eimus),
                             proxy=self.proxy, referer="https://www.instagram.com/direct/inbox/",
                             tokens=self._gql_token_bundle())
        ok = bool(isinstance(r, dict) and r.get("data")) and not r.get("errors")
        tid = None
        try:
            tid = r["data"]["xig_ig_direct_create_thread"]["id"]
        except Exception:
            pass
        result = {"ok": ok, "thread_id": tid, "resolved_eimus": eimus, "transport": "graphql", "response": r}
        if not ok:
            result["error"] = "group_create_failed"
            if diagnose:
                blocked = self._diagnose_blocked(eimus, name_by_eimu)
                if blocked is None:
                    result["hint"] = ("need 3+ recipients to isolate the culprit; one of %s is likely "
                                      "banned/deactivated/blocked" % us)
                elif blocked:
                    result["blocked_recipients"] = blocked
                    result["hint"] = ("recipient(s) %s are banned/deactivated/blocked and can't be added — one "
                                      "bad member fails the whole create; remove them and retry" % blocked)
                else:
                    result["blocked_recipients"] = []
                    result["hint"] = "couldn't isolate a single culprit (possibly multiple bad members or a transient throttle); retry"
            else:
                result["hint"] = ("Instagram rejected the create — usually one banned/deactivated/blocked "
                                  "recipient fails the whole group. Recipients: %s. Pass diagnose=True to name "
                                  "the culprit, or retry if transient." % us)
        self.ev.emit("groups.upsert", {"ok": ok, "thread_id": tid, "members": us, "eimus": eimus})
        if ok and tid and first_message:
            try: self.send_message(tid, {"text": first_message})
            except Exception: pass
        return result

    def _thread_meta(self, thread_id) -> dict:
        """Fetch a group's live meta: admin_user_ids, users{username:{pk,eimu}}, thread ids, nickname_setting."""
        import requests
        def _get(tid):
            try:
                r = requests.get("https://www.instagram.com/api/v1/direct_v2/threads/%s/?limit=1" % tid,
                                 cookies={k: v for k, v in self.cookies.items() if v},
                                 headers={"User-Agent": _GQL_UA, "X-IG-App-ID": str(IG_WEB_APP_ID),
                                          "X-CSRFToken": self.cookies.get("csrftoken", ""),
                                          "Referer": "https://www.instagram.com/direct/inbox/"},
                                 proxies=({"https": self.proxy, "http": self.proxy} if self.proxy else None), timeout=25, allow_redirects=False)
                return r.json().get("thread", {}) or {}
            except Exception:
                return {}
        t = _get(thread_id)

        if not (t.get("users") or []) and t.get("thread_v2_id") and str(t["thread_v2_id"]) != str(thread_id):
            t = _get(t["thread_v2_id"])
        users = {}
        for u in t.get("users", []) or []:
            users[u.get("username")] = {"pk": u.get("pk"), "eimu": u.get("interop_messaging_user_fbid")}
        return {"admin_user_ids": [str(x) for x in (t.get("admin_user_ids") or [])],
                "users": users, "thread_v2_id": t.get("thread_v2_id"), "thread_id": t.get("thread_id"),
                "nickname_setting": t.get("nickname_setting")}

    def am_i_admin(self, thread_id) -> bool:
        """True if the logged-in user is an admin of this group (checked live). Admin ops require this."""
        me = str(self.cookies.get("ds_user_id") or self.web_user_id)
        return me in self._thread_meta(thread_id).get("admin_user_ids", [])

    def _resolve_pk(self, username) -> str:
        """Resolve an IG username → numeric pk (cached)."""
        u = str(username)
        if u.isdigit():
            return u
        if not hasattr(self, "_pk_cache"):
            self._pk_cache = {}
        if u not in self._pk_cache:
            import requests
            try:
                r = requests.get("https://www.instagram.com/api/v1/users/web_profile_info/?username=%s" % u,
                                 cookies={k: v for k, v in self.cookies.items() if v},
                                 headers={"User-Agent": _GQL_UA, "X-IG-App-ID": str(IG_WEB_APP_ID),
                                          "Referer": "https://www.instagram.com/%s/" % u},
                                 proxies=({"https": self.proxy, "http": self.proxy} if self.proxy else None), timeout=25, allow_redirects=False)
                self._pk_cache[u] = (r.json().get("data", {}).get("user", {}) or {}).get("id")
            except Exception:
                self._pk_cache[u] = None
        return self._pk_cache[u]

    _ADD_PROVIDERS = {"__relay_internal__pv__IGDMaxUnreadMessagesCountrelayprovider": 20,
                      "__relay_internal__pv__IGDPinnedThreadsRenderEnabledGKrelayprovider": True,
                      "__relay_internal__pv__IGDThreadListActionsEnabledGKrelayprovider": True}

    def _member_mutation(self, key, short_thread, variables, event, username=None) -> dict:
        r = web_graphql_call(self.cookies, key, variables, proxy=self.proxy,
                             referer=self._group_referer(short_thread), tokens=self._gql_token_bundle())
        ok = bool(isinstance(r, dict) and r.get("data")) and not r.get("errors")
        self.ev.emit(event, {"thread_id": str(short_thread), "username": username, "ok": ok})
        return {"ok": ok, "transport": "graphql", "response": r}

    def _member_ids(self, thread_id, username):
        """Return (pk, eimu, short_thread) for a member `username` (or a raw id)."""
        meta = self._thread_meta(thread_id)
        short = meta.get("thread_v2_id") or self._short_thread_id(thread_id)
        u = meta.get("users", {}).get(str(username), {})
        pk, eimu = (str(u["pk"]) if u.get("pk") else None), (str(u["eimu"]) if u.get("eimu") else None)
        if not pk:
            pk = self._resolve_pk(username)
        if not eimu:
            eimu = self._resolve_eimu(username)
        return pk, eimu, short

    def add_group_member(self, thread_id, username: str, **_kw) -> dict:
        """Add a member to a group (`username` → pk auto-resolved)."""
        pk, eimu, short = self._member_ids(thread_id, username)
        if not pk:
            return {"ok": False, "error": "could not resolve pk for %s" % username}
        v = {"thread_fbid": str(short), "user_igids": [str(pk)]}
        v.update(self._ADD_PROVIDERS)
        return self._member_mutation("add_member", short, v, "participants.add", username)

    def remove_group_member(self, thread_id, username: str, **_kw) -> dict:
        """Remove a member from a group; checks you are an admin first."""
        if not self.am_i_admin(thread_id):
            return {"ok": False, "reason": "not_admin", "detail": "you must be an admin to remove members"}
        pk, eimu, short = self._member_ids(thread_id, username)
        if not pk:
            return {"ok": False, "error": "could not resolve pk for %s" % username}
        return self._member_mutation("remove_member", short,
                                     {"thread_fbid": str(short), "user_igid": str(pk)},
                                     "participants.remove", username)

    def set_group_admin(self, thread_id, username: str, admin: bool = True, **_kw) -> dict:
        """Promote or demote a group admin; checks you are an admin first."""
        if not self.am_i_admin(thread_id):
            return {"ok": False, "reason": "not_admin",
                    "detail": "you must be an admin of this group to change admins"}
        pk, eimu, short = self._member_ids(thread_id, username)
        if not eimu:
            return {"ok": False, "error": "could not resolve eimu fbid for %s" % username}
        return self._member_mutation("make_admin" if admin else "remove_admin", short,
                                     {"thread_fbid": str(short), "user_igids": [str(eimu)]},
                                     "participants.promote" if admin else "participants.demote", username)

    def _group_referer(self, thread_id) -> str:
        return "https://www.instagram.com/direct/t/%s/" % thread_id

    def rename_group(self, thread_id, name: str, **_kw) -> dict:
        """Rename a group to `name`."""
        big = str(thread_id)
        r = web_graphql_call(self.cookies, "rename_thread", {"thread_fbid": big, "new_title": str(name)},
                             proxy=self.proxy, referer=self._group_referer(big), tokens=self._gql_token_bundle())
        ok = bool(isinstance(r, dict) and r.get("data")) and not r.get("errors")
        self.ev.emit("groups.update", {"thread_id": big, "name": name, "ok": ok})
        return {"ok": ok, "transport": "graphql", "response": r}

    def set_nickname(self, thread_id, nickname: str, member: Optional[str] = None, **_kw) -> dict:
        """Set a nickname in a group (omit `member` for your own; else that member must allow 'Everyone')."""
        big = str(thread_id)
        if member:
            pk, _eimu, _short = self._member_ids(thread_id, member)
        else:
            pk = self.cookies.get("ds_user_id") or str(self.web_user_id)
        if not pk:
            return {"ok": False, "error": "could not resolve pk for %s" % member}
        r = web_graphql_call(self.cookies, "edit_nickname",
                             {"metadata": {"ig_thread_igid": big}, "data": {"nickname": str(nickname), "user_igid": str(pk)}},
                             proxy=self.proxy, referer=self._group_referer(big), tokens=self._gql_token_bundle())
        ok = bool(isinstance(r, dict) and r.get("data")) and not r.get("errors")
        out = {"ok": ok, "transport": "graphql", "nickname": nickname, "member": member, "response": r}
        if not ok and member and "field_exception" in json.dumps(r):
            out["reason"] = "edit_not_allowed"
            out["detail"] = "%s hasn't allowed everyone to edit their nickname (only they can)" % member
        self.ev.emit("nickname.update", {"thread_id": big, "nickname": nickname, "member": member, "ok": ok})
        return out

    def can_edit_nickname(self, thread_id, member: str) -> dict:
        """Pre-check whether you can set `member`'s nickname → {allowed, reason}."""
        meta = self._thread_meta(thread_id)
        setting = meta.get("nickname_setting")

        return {"allowed": None if not setting else True, "nickname_setting": setting,
                "note": "authoritative check is set_nickname(); a field_exception means not allowed"}

    def set_nickname_permission(self, thread_id, who: str = "everyone", **_kw) -> dict:
        """Set who can edit your nickname in this thread — `who`: 'everyone' | 'following' | 'only_you'."""
        big = str(thread_id)
        want = {"everyone": "EVERYONE", "following": "FOLLOWING", "only_you": "ONLY_YOU"}.get(who.lower(), "EVERYONE")
        r = web_graphql_call(self.cookies, "nickname_setting",
                             {"metadata": {"ig_thread_igid": big}, "data": {"nickname_setting": want}},
                             proxy=self.proxy, referer=self._group_referer(big), tokens=self._gql_token_bundle())
        ok = bool(isinstance(r, dict) and r.get("data")) and not r.get("errors") and want in json.dumps(r)
        self.ev.emit("nickname.permission", {"thread_id": big, "who": who, "ok": ok})
        return {"ok": ok}
