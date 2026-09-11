# igrapiweb

![Python](https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)
[![Docs](https://img.shields.io/badge/docs-latest-blue)](https://ashsawtech.github.io/igrapiweb/)

A pure-Python client for Instagram Web. It speaks Instagram's realtime WebSocket channels and private web
API directly from a logged-in `sessionid` cookie — no browser, no Selenium, no emulator. Give it a
session and it stays connected, streams events, and exposes the messaging, social, feed, story, and
calling surfaces of the web app.

```python
from igrapiweb import make_ig_web_socket

sock = make_ig_web_socket(sessionid="<your web sessionid>")

@sock.ev.on("messages.upsert")
def on_message(evt):
    for m in evt["messages"]:
        print(m["key"]["remoteJid"], m["message"])

sock.connect()
sock.listen()
```

Receive rides the DGW *lightspeed* channel the website itself uses — each DM is pushed down and acked
per frame, so nothing is dropped. Sends go over the same web GraphQL mutation the browser fires (or the
WebSocket send channel while it's up), and follow/like/comment/story actions call the same
`www.instagram.com` private endpoints the site does.

## Installation

```bash
pip install igrapiweb
```

The core (messaging, groups, presence, social graph, feed, stories) needs only `requests` and
`websocket-client`. Optional features pull in extra dependencies:

```bash
pip install "igrapiweb[calls]"   # voice/video calls
pip install "igrapiweb[login]"   # username/password login
pip install "igrapiweb[all]"
```

Importing the library never requires the extras; a call method or a credential login raises a clear
error if its extra is missing.

## Authentication

`make_ig_web_socket(...)` accepts one of:

```python
sock = make_ig_web_socket(sessionid="1234%3Aabcd%3A...")                       # a browser sessionid
sock = make_ig_web_socket(cookies={"sessionid": "...", "ds_user_id": "..."})   # a full cookie dict
sock = make_ig_web_socket(username="user", password="secret")                  # login (needs [login])
```

To get a `sessionid`, sign in at instagram.com, open the browser dev tools → Application → Cookies →
`https://www.instagram.com`, and copy the `sessionid` value. Treat it as a full credential.

Register resolvers before a credential login if the account is gated:

```python
sock.set_twofa_resolver(lambda two_factor_id: input("2FA code: "))
sock.set_challenge_resolver(lambda ctx: input("challenge code: "))
```

Pass `proxy="socks5h://127.0.0.1:40000"` to route the session through a proxy matching its region.

## Receiving events

`connect()` opens the realtime pipes on background threads and returns immediately. Subscribe on
`sock.ev`, which works as a decorator or a direct call:

```python
@sock.ev.on("messages.upsert")
def on_message(evt):
    for m in evt["messages"]:
        print(m["key"]["remoteJid"], m["message"])

sock.ev.on("presence.update", lambda e: print("presence", e))

sock.connect()
sock.listen()   # blocks; Ctrl-C disconnects cleanly
```

`sock.ev.off(event, handler)` unsubscribes; `sock.ev.process(handler)` receives every event as
`(event, payload)`. Incoming messages arrive in a stable shape:

```python
{"messages": [{"key": {"remoteJid": "<thread id>", "id": "<item id>", "fromMe": False},
               "message": {...}}],
 "type": "notify", "source": "dgw-lightspeed"}
```

| Event | Fires when |
| --- | --- |
| `connection.update` | connection state changes (`connecting` / `open` / `recovering` / `close`) |
| `connection.heartbeat` | keepalive beat, carrying a `health()` snapshot |
| `creds.update` | the user is identified, or re-auth is needed |
| `messages.upsert` | a direct message arrives |
| `messages.update` | a message is edited |
| `messages.delete` | a message is unsent |
| `message-receipt.update` | a participant's read receipt advances |
| `presence.update` | a contact starts/stops typing or changes presence |
| `send.ack` / `send.fallback` | a send is acked / fell back from GraphQL to WebSocket |
| `friendship.update` | a follow, accept, or reject completes |
| `groups.upsert` / `groups.update` | a group is created or changed |
| `story.posted` / `story.deleted` | one of your stories changes |
| `profile.updated` | your profile photo changes |
| `call` | an incoming call rings |
| `call.outgoing` / `call.connected` / `call.answered` / `call.declined` | call lifecycle |

## Sending and actions

```python
# Direct messages
sock.send_message(thread_id, {"text": "hello"})
sock.send_message(thread_id, {"text": "hi", "quoted": {"key": {"id": item_id}}})   # reply
sock.send_media(thread_id, "photo.jpg", kind="photo")
sock.send_voice(thread_id, "clip.mp3")                    # voice note
sock.send_message(thread_id, {"voice": "clip.mp3"})       # same, via a content dict
sock.unsend_message(thread_id, message_id="mid...")
sock.edit_message(thread_id, "fixed text", message_id="mid...")
sock.read_messages([{"remoteJid": thread_id, "id": item_id}])

# Groups
g = sock.create_group(["alice", "bob"], first_message="hi")
sock.rename_group(g["thread_id"], "Weekend plans")
sock.add_group_member(g["thread_id"], "carol")
sock.set_group_admin(g["thread_id"], "carol", admin=True)
sock.set_nickname(g["thread_id"], "Cazza", member="carol")

# Presence and receipts
sock.send_typing(thread_id, on=True)
sock.read_receipts(thread_id)
sock.mark_read(thread_id, item_id)

# Social graph
sock.get_user("instagram")
sock.follow("someone")
sock.accept_follow_request("pending_user")
sock.reject_follow_request("pending_user")
sock.change_profile_pic("avatar.jpg")

# Feed and reels
top = sock.most_viewed_reel("someone")
sock.like_media(top["id"])
sock.comment_media(top["id"], "great reel")
sock.watch_reel(top["id"], download_to="reel.mp4")
sock.share_reel(top["id"], thread_id)

# Stories
sock.add_story("story.jpg")
sock.story_viewers(story_media_id)
sock.delete_story(story_media_id)
```

Actions return a plain dict (usually with an `ok` flag and the raw response) and emit the matching event.

## Calls

Calls run over WebRTC and are async; install the `calls` extra first.

```python
import asyncio

async def main():
    sock = make_ig_web_socket(sessionid="...")
    sock.connect()
    session = await sock.place_call(thread_id, audio_source="audio.wav", record_to="incoming.wav")
    session.mute(); session.unmute()
    await asyncio.sleep(30)
    await session.end()

asyncio.run(main())
```

Answer incoming calls from the `call` event:

```python
sock.start_call_listener()

@sock.ev.on("call")
def on_ring(ring):
    asyncio.get_event_loop().create_task(sock.answer_call(ring, audio_source="audio.wav"))
```

## Staying connected

With `keep_alive=True` (the default), `connect()` holds the receive and send pipes open, reconnects
either one with backoff if it drops, refreshes the short-lived auth claim and resumes the message cursor
on reconnect, and emits `connection.heartbeat` on a regular beat.

```python
sock.connect(dm_receive="dgw", send="ws", keep_alive=True)
sock.health()   # {edge_chat, dgw_lightspeed, uptime_s, heartbeats, ...}
```

- `dm_receive`: `"dgw"` (default, lossless push) · `"iris"` (legacy) · `"both"`
- `send`: `"ws"` (down the open pipe) · `"graphql"` (HTTP)
- `presence`: subscribe to presence/typing (default `True`)
- `keep_alive`: run the reconnect watchdog (default `True`)

## Running multiple accounts

Several accounts sharing one User-Agent (or one IP) is a linking signal. `AccountManager` gives each
account its own session, proxy, tokens, sockets, and a distinct, stable User-Agent (auto-derived unless
you set one):

```python
from igrapiweb import AccountManager

mgr = AccountManager()
mgr.add("main", sessionid="<sid A>", proxy="socks5h://127.0.0.1:40000")
mgr.add("alt",  sessionid="<sid B>", proxy="socks5h://127.0.0.1:40001")
mgr.connect_all()

mgr["main"].send_message(thread_id, {"text": "hi"})
mgr["alt"].follow("someone")

mgr.fingerprints()   # {name: {ds_user_id, user_agent, proxy}}
mgr.warnings         # any two accounts sharing a UA or proxy
```

Give each account its own proxy for IP isolation. The identifying requests (page load, realtime, login)
use the per-account User-Agent; the private-API calls use a minimal shared UA. Override with
`user_agent=` on `make_ig_web_socket` or `mgr.add`.

## Persistence and recovery

```python
sock = make_ig_web_socket(sessionid="...", save_path="state.json")
sock.load_state()      # restore cookies and cursors from a previous run
sock.connect()
sock.save_state()      # also written on each heartbeat
```

Instagram rotates a web `sessionid` over time. `session_health()` reports the current state; if you built
the socket with credentials (or called `set_credentials`), `recover_session()` re-runs the web login and
adopts a fresh `sessionid`. Otherwise register a provider that returns one:

```python
sock.session_health()   # {"web": "ok" | "walled", "logged_out": bool}
sock.set_login_provider(lambda: fresh_sessionid())   # -> sessionid str or {"sessionid": ...}
sock.recover_session()
```

With `keep_alive` on, the watchdog calls `recover_session()` after repeated auth failures.

## API reference

| Area | Methods |
| --- | --- |
| Multi-account | `AccountManager`: `add`, `get`, `connect_all`, `disconnect_all`, `remove`, `fingerprints`, `warnings` |
| Lifecycle | `connect`, `listen`, `disconnect`, `end`, `logout`, `health` |
| Messages | `send_message`, `send_media`, `send_voice`, `unsend_message`, `edit_message`, `read_messages`, `mark_read` |
| Groups | `create_group`, `rename_group`, `add_group_member`, `remove_group_member`, `set_group_admin`, `set_nickname`, `am_i_admin` |
| Presence | `send_typing`, `send_presence_update`, `presence_subscribe`, `start_typing_receive` |
| Receipts | `read_receipts`, `poll_receipts`, `track_thread`, `reconcile_thread` |
| Social | `get_user`, `follow`, `unfollow`, `follow_back`, `accept_follow_request`, `reject_follow_request`, `pending_follow_requests`, `friendship_status`, `change_profile_pic` |
| Feed and reels | `media_info`, `user_reels`, `most_viewed_reel`, `reel_comments`, `like_media`, `unlike_media`, `save_media`, `comment_media`, `watch_reel`, `download_reel`, `open_reels`, `next_reel`, `share_reel` |
| Stories | `story_tray`, `get_user_story`, `story_viewers`, `add_story`, `like_story`, `delete_story` |
| Calls | `place_call`, `answer_call`, `decline_call`, `start_call_listener` |
| Session | `save_state`, `load_state`, `session_health`, `recover_session`, `auto_login`, `set_credentials`, `set_twofa_resolver`, `set_challenge_resolver`, `set_login_provider` |

## Requirements

- Python 3.9+
- `requests`, `websocket-client`, `python-socks`, `cryptography` (installed automatically)
- Optional: `calls` (aiortc, aioice), `login` (curl_cffi, pynacl)
- `ffmpeg` on `PATH` for `send_voice` (transcodes to opus and reads the waveform); pass an `.ogg`/`.opus`
  file with `waveform=` to skip it

## Disclaimer

Not affiliated with, endorsed by, or sponsored by Instagram or Meta. It automates a personal account
through Instagram's own web endpoints; use it within Instagram's Terms of Use and applicable law. You are
responsible for how you use it.

## License

[MIT](LICENSE)

## Attribution

Created by **ashsawtech** — Telegram [@ashsawtech](https://t.me/ashsawtech) · https://github.com/ashsawtech/igrapiweb

The author credit in `igrapiweb/_attrib.py` is required by the license and is enforced at import; it must
be kept intact.
