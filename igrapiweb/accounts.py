"""Run several Instagram Web accounts side by side, each with its own cookies, proxy, and User-Agent."""
from __future__ import annotations
from typing import Dict, List, Optional
from .facade import make_ig_web_socket, IGWebSocket


class AccountManager:
    """A registry of named, isolated :class:`IGWebSocket` accounts."""

    def __init__(self):
        self.accounts: Dict[str, IGWebSocket] = {}
        self.warnings: List[dict] = []

    def add(self, name: str, *, sessionid: Optional[str] = None, cookies: Optional[dict] = None,
            proxy: Optional[str] = None, user_agent: Optional[str] = None, connect: bool = False,
            **kwargs) -> IGWebSocket:
        """Register an account under `name` and return its socket; give each its own proxy/UA for isolation. Raises if `name` is taken."""
        if name in self.accounts:
            raise ValueError("account %r already added" % name)
        sock = make_ig_web_socket(sessionid=sessionid, cookies=cookies, proxy=proxy,
                                  user_agent=user_agent, **kwargs)
        self._check_isolation(name, sock)
        self.accounts[name] = sock
        if connect:
            sock.connect()
        return sock

    def _check_isolation(self, name: str, sock: IGWebSocket) -> None:
        for other, s in self.accounts.items():
            if sock.proxy and s.proxy == sock.proxy:
                self._warn(name, "shares_proxy_with", other, {"proxy": sock.proxy})
            if s.user_agent == sock.user_agent:
                self._warn(name, "shares_user_agent_with", other, {"user_agent": sock.user_agent})

    def _warn(self, name: str, kind: str, other: str, extra: dict) -> None:
        w = {"account": name, kind: other}
        w.update(extra)
        self.warnings.append(w)
        try:
            self.accounts.get(other, self.accounts.get(name)).ev.emit("account.warning", w)
        except Exception:
            pass

    def get(self, name: str) -> IGWebSocket:
        return self.accounts[name]

    def __getitem__(self, name: str) -> IGWebSocket:
        return self.accounts[name]

    def __contains__(self, name: str) -> bool:
        return name in self.accounts

    def __iter__(self):
        return iter(self.accounts.values())

    def __len__(self) -> int:
        return len(self.accounts)

    def items(self):
        return self.accounts.items()

    @property
    def names(self) -> List[str]:
        return list(self.accounts)

    def connect_all(self, **kwargs) -> "AccountManager":
        """Bring every account's realtime pipes up (each keeps its own keepalive)."""
        for s in self.accounts.values():
            s.connect(**kwargs)
        return self

    def disconnect_all(self) -> None:
        for s in self.accounts.values():
            try:
                s.disconnect()
            except Exception:
                pass

    def remove(self, name: str) -> None:
        """Disconnect and drop an account."""
        s = self.accounts.pop(name, None)
        if s is not None:
            try:
                s.disconnect()
            except Exception:
                pass

    def fingerprints(self) -> Dict[str, dict]:
        """Per-account isolation snapshot {name: {ds_user_id, user_agent, proxy}} to confirm no shared UA/proxy."""
        return {n: {"ds_user_id": s.user.get("id"), "user_agent": s.user_agent, "proxy": s.proxy}
                for n, s in self.accounts.items()}
