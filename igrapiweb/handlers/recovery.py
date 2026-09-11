# igrapiweb · created by ashsawtech · https://github.com/ashsawtech/igrapiweb · attribution required (see _attrib.py)
from __future__ import annotations
from typing import Callable, Optional
from ..session import cookies_from_sessionid

class RecoveryMixin:
    """Session self-healing: re-authenticate from stored credentials or a registered login_provider callback."""

    def set_login_provider(self, fn: Callable[[], object]) -> None:
        """Register a callback the recoverer calls when it can't self-heal (returns a fresh session)."""
        self._login_provider = fn

    def set_credentials(self, username: str, password: str) -> None:
        """Credentials for the auto re-login tier (kept in memory only; never persisted by the library)."""
        self._cred = (username, password)

    def set_twofa_resolver(self, fn: Callable[[str], str]) -> None:
        """Register a callback ``fn(two_factor_identifier) -> code`` for a 2FA login."""
        self._twofa = fn

    def set_challenge_resolver(self, fn: Callable[[dict], str]) -> None:
        """Callback ``fn(challenge_context) -> code`` for a checkpoint challenge."""
        self._challenge = fn

    def session_health(self) -> dict:
        """Quick classification of the current session → {web, logged_out}."""
        web = self._web_alive()
        return {"web": web, "logged_out": web != "ok"}

    def _web_alive(self) -> str:
        from ..graphql import web_graphql_scrape_tokens
        try:
            tok = web_graphql_scrape_tokens(self.cookies, proxy=self.proxy)
            return "ok" if tok.get("fbid") else "walled"
        except Exception:
            return "walled"

    def recover_session(self, reason: str = "") -> dict:
        """Restore a working session: stored credentials, then a login_provider callback, else flag needs_reauth."""
        self.ev.emit("connection.update", {"connection": "recovering", "reason": reason})

        al = self.auto_login()
        if al.get("ok"):
            return al

        prov = getattr(self, "_login_provider", None)
        if prov:
            try:
                if self._apply_recovered(prov()):
                    self.ev.emit("creds.update", {"recovered": True, "tier": "login_provider"})
                    return {"ok": True, "tier": "login_provider"}
            except Exception as e:
                self.ev.emit("connection.update", {"connection": "recover_failed", "error": repr(e)})

        reason = al.get("reason") if al.get("reason") not in (None, "no_credentials") else reason
        self.ev.emit("creds.update", {"needs_reauth": True, "reason": reason or "session_logged_out"})
        return {"ok": False, "needs_reauth": True, "reason": reason or "session_logged_out"}

    def auto_login(self) -> dict:
        """Re-authenticate from stored credentials via the pure-web login and adopt the fresh sessionid."""
        cred = getattr(self, "_cred", None)
        if not cred:
            return {"ok": False, "reason": "no_credentials"}
        from ..webauth import web_login
        user, pw = cred
        try:
            r = web_login(user, pw, proxy=self.proxy, twofa=getattr(self, "_twofa", None))
        except Exception as e:
            return {"ok": False, "reason": repr(e)[:120]}
        if r.get("ok") and r.get("sessionid"):
            self._apply_sessionid(r["sessionid"], extra=r.get("cookies"))
            self.ev.emit("creds.update", {"recovered": True, "tier": "web_login"})
            return {"ok": True, "tier": "web_login"}
        if r.get("two_factor_required"):
            self.ev.emit("creds.update", {"needs_2fa": True})
        elif r.get("checkpoint_required"):
            self.ev.emit("creds.update", {"needs_challenge": True, "checkpoint_url": r.get("checkpoint_url")})
        return {"ok": False, "reason": r.get("error") or ("2fa" if r.get("two_factor_required")
                                                          else "checkpoint" if r.get("checkpoint_required")
                                                          else "login_failed")}

    def _apply_recovered(self, fresh) -> bool:
        if not fresh:
            return False
        if isinstance(fresh, str):
            self._apply_sessionid(fresh)
            return True
        if isinstance(fresh, dict) and fresh.get("sessionid"):
            self._apply_sessionid(fresh["sessionid"], extra=fresh.get("cookies"))
            return True
        return False

    def _apply_sessionid(self, sid: str, extra: Optional[dict] = None) -> None:
        """Swap in a fresh sessionid across every channel and drop derived tokens."""
        fresh = cookies_from_sessionid(sid)
        self.cookies["sessionid"] = sid
        if fresh.get("ds_user_id"):
            self.cookies["ds_user_id"] = fresh["ds_user_id"]
        if extra:
            self.cookies.update(extra)
        self.cookies.pop("_wwwclaim", None)
        self.cookies.pop("csrftoken", None)
        for ch in (getattr(self, "edge", None), getattr(self, "dgw", None), getattr(self, "dgw_typing", None)):
            if ch is not None:
                ch.cookies = self.cookies
        self._gql_tokens = None
