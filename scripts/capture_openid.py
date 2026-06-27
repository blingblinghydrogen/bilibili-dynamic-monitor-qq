#!/usr/bin/env python3
"""Capture QQ openid by temporarily connecting to QQ Bot WebSocket."""
import json
import sys
import asyncio
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
OPENID_PATH = SCRIPT_DIR / "openid.txt"
CONFIG_PATH = SCRIPT_DIR / "config.json"

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    cfg = json.load(f)

APP_ID = cfg.get("qq_app_id", "")
APP_SECRET = cfg.get("qq_app_secret", "")
TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
WS_GATEWAY_URL = "https://api.sgroup.qq.com/gateway"


def get_access_token():
    data = json.dumps({"appId": APP_ID, "clientSecret": APP_SECRET}).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=10)
    return json.loads(resp.read())["access_token"]


def get_ws_url(token):
    req = urllib.request.Request(WS_GATEWAY_URL, headers={"Authorization": f"QQBot {token}"})
    resp = urllib.request.urlopen(req, timeout=10)
    return json.loads(resp.read())["url"]


async def capture():
    import websockets

    print("[1/3] Getting access token...")
    token = get_access_token()
    print(f"  Token: {token[:30]}...")

    print("[2/3] Getting WebSocket URL...")
    ws_url = get_ws_url(token)
    print(f"  URL: {ws_url[:60]}...")

    print("[3/3] Connecting to QQ WebSocket...")
    print("  NOTE: WorkBuddy's QQ connection may temporarily disconnect.")
    print("  >>> Send ANY message to your bot on QQ now! <<<")
    print()

    headers = {"Authorization": f"QQBot {token}", "User-Agent": "WorkBuddy-Skill/1.0"}

    async with websockets.connect(ws_url, additional_headers=headers) as ws:
        # Receive Hello
        hello = json.loads(await ws.recv())
        print(f"  Hello: op={hello.get('op')}")
        heartbeat_interval = hello.get("d", {}).get("heartbeat_interval", 30000)

        # Send Identify
        identify = {
            "op": 2,
            "d": {
                "token": f"QQBot {token}",
                "intents": 1 << 25 | 1 << 30,
                "shard": [0, 1],
            }
        }
        await ws.send(json.dumps(identify))
        print("  Identify sent. Waiting for your QQ message...")

        # Heartbeat task
        async def heartbeat():
            while True:
                await asyncio.sleep(heartbeat_interval / 1000)
                try:
                    await ws.send(json.dumps({"op": 1, "d": None}))
                except Exception:
                    break

        hb_task = asyncio.create_task(heartbeat())

        # Listen for messages (120 second timeout)
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=120)
                msg = json.loads(raw)
                op = msg.get("op")
                t = msg.get("t")
                d = msg.get("d", {})

                if op == 0 and t == "READY":
                    print(f"  Ready: bot online")
                    continue

                if op == 0 and t == "C2C_MESSAGE_CREATE":
                    openid = d.get("author", {}).get("user_openid", "")
                    content = d.get("content", "").strip()
                    print(f"  >>> Message received: '{content}'")
                    print(f"  >>> OpenID: {openid}")

                    if openid:
                        OPENID_PATH.write_text(openid, encoding="utf-8")
                        print(f"\n  ✅ OpenID saved to {OPENID_PATH}")
                        hb_task.cancel()
                        return True

                if op == 0 and t == "GROUP_AT_MESSAGE_CREATE":
                    group_openid = d.get("group_openid", "")
                    author_openid = d.get("author", {}).get("member_openid", "")
                    content = d.get("content", "").strip()
                    print(f"  >>> Group message: '{content}'")
                    print(f"  >>> group_openid: {group_openid}")
                    print(f"  >>> member_openid: {author_openid}")
                    print(f"  (This is a group message, not C2C. Need a private message.)")

                if op == 11:
                    continue

                if t:
                    print(f"  Event: {t} (op={op})")

            except asyncio.TimeoutError:
                print("\n  ⏰ No message in 120 seconds. Timeout.")
                hb_task.cancel()
                return False


if __name__ == "__main__":
    success = asyncio.run(capture())
    if success:
        print("\n✅ Done! OpenID captured. WorkBuddy will reconnect QQ automatically.")
    else:
        print("\n❌ No message received. Try again or send a private message to the bot.")
        sys.exit(1)
