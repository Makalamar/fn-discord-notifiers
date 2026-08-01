#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fortnite Staging Server Notifier

Uses the official Epic Games Lightswitch Service to monitor staging servers.
No third-party scraping required — this is a public API (auth required, no
special permissions needed).

Endpoint:
  GET https://lightswitch-public-service-prod06.ol.epicgames.com
       /lightswitch/api/service/bulk/status
       ?serviceId=FortnitePublicTest&serviceId=FortnitePreview&...

Auth: Epic OAuth2 client_credentials (anonymous game client)
  clientId  : xyza7891muomRmynIIHaJB9COBKgwj4R
  secret    : listen to the sound of music
  grantType : client_credentials

Embed colour code:
  Blue  (0x3498DB) - status/message change on same service
  Red   (0xE74C3C) - service goes UP -> DOWN or DOWN -> UP
  Green (0x2ECC71) - service comes back UP
"""

import os
import json
import base64
import requests
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ==================== CONFIG ====================
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_STAGING_WEBHOOK_URL", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1" or not DISCORD_WEBHOOK_URL
TEST_LAST = os.environ.get("TEST_LAST_STAGING", "0") == "1"

# Optional: override Epic credentials via env (not needed for anonymous access)
EPIC_CLIENT_ID = os.environ.get(
    "EPIC_CLIENT_ID", "xyza7891muomRmynIIHaJB9COBKgwj4R"
).strip()
EPIC_CLIENT_SECRET = os.environ.get(
    "EPIC_CLIENT_SECRET", "Eh9K3uIh8MooKMkODRwTaLBIVnFJnEWuLwTaLBIVnFJnEWuL"
).strip()

STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "staging_state.json",
)

# Epic Lightswitch bulk status endpoint
LIGHTSWITCH_URL = (
    "https://lightswitch-public-service-prod06.ol.epicgames.com"
    "/lightswitch/api/service/bulk/status"
)
EPIC_TOKEN_URL = (
    "https://account-public-service-prod.ol.epicgames.com"
    "/account/api/oauth/token"
)

# Staging service IDs to monitor (from Epic's Lightswitch documentation)
STAGING_SERVICE_IDS: List[str] = [
    "FortnitePublicTest",
    "FortnitePreview",
    "FortniteLoadTest",
    "FortniteLiveBroadcasting",
    "FortniteLiveTesting",
    "FortnitePredeployA",
    "FortnitePredeployB",
    "FortniteReleasePlaytest",
    "FortnitePartners",
    "FortnitePartnersStable",
    "FortniteLocTesting",
    "FortniteExtQAReleaseTesting",
    "FortniteExtQAReleaseTestingB",
]

HTTP_TIMEOUT = 30

COLOR_CHANGE = 0x3498DB    # blue — message/details changed
COLOR_DOWN   = 0xE74C3C    # red  — went DOWN
COLOR_UP     = 0x2ECC71    # green — came back UP


# ==================== STATE ====================

def load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            print(f"[STATE] Could not read {STATE_FILE}: {e}")
    return {}


def save_state(state: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# ==================== AUTH ====================

def get_epic_token() -> Optional[str]:
    """
    Obtain an anonymous Epic OAuth2 access token via client_credentials.
    No user account is needed — this works with any registered game client.
    """
    credentials = base64.b64encode(
        f"{EPIC_CLIENT_ID}:{EPIC_CLIENT_SECRET}".encode()
    ).decode()
    try:
        resp = requests.post(
            EPIC_TOKEN_URL,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials"},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        token = resp.json().get("access_token")
        if token:
            print("[AUTH] Epic OAuth2 token obtained")
            return token
        print(f"[AUTH] Token response missing access_token: {resp.text[:200]}")
    except Exception as e:
        print(f"[AUTH] Failed to get Epic token: {e}")
    return None


# ==================== FETCHING ====================

def fetch_staging(token: str) -> Optional[List[Dict[str, Any]]]:
    """
    Query the Lightswitch bulk status endpoint for all staging service IDs.
    Returns a list of service status dicts, or None on failure.
    """
    params = [("serviceId", sid) for sid in STAGING_SERVICE_IDS]
    try:
        resp = requests.get(
            LIGHTSWITCH_URL,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            print(f"[API] Unexpected response shape: {type(data)}")
            return None
        # Filter to only the staging IDs we care about
        results = [
            s for s in data
            if s.get("serviceInstanceId", "").lower()
            in {sid.lower() for sid in STAGING_SERVICE_IDS}
        ]
        print(f"[API] Lightswitch: {len(results)} staging service(s) returned")
        return results
    except Exception as e:
        print(f"[API] Lightswitch request failed: {e}")
        return None


# ==================== NORMALISE ====================

def normalise(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status":  raw.get("status") or "UNKNOWN",
        "message": raw.get("message") or "",
    }


# ==================== EMBED ====================

def build_embed(service_id: str, old: Dict[str, Any], new: Dict[str, Any]) -> dict:
    old_status  = old["status"]
    new_status  = new["status"]
    old_message = old["message"]
    new_message = new["message"]

    status_changed = old_status != new_status

    if status_changed:
        if new_status == "UP":
            color = COLOR_UP
        elif new_status == "DOWN":
            color = COLOR_DOWN
        else:
            color = COLOR_CHANGE
    else:
        color = COLOR_CHANGE

    status_icon = "\u2705" if new_status == "UP" else "\u274c" if new_status == "DOWN" else "\u26a0\ufe0f"

    desc_lines = [
        f"**{service_id}**",
        "",
        f"**Status:** ~~{old_status}~~ \u2192 {status_icon} **{new_status}**",
    ]
    if old_message != new_message:
        desc_lines += [
            "",
            f"**Message:** ~~{old_message or '(none)'}~~",
            f"\u2192 {new_message or '(none)'}",
        ]

    embed: Dict[str, Any] = {
        "description": "\n".join(desc_lines),
        "color": color,
        "footer": {"text": "Epic Lightswitch Service"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if status_changed:
        if new_status == "UP":
            embed["title"] = "\U0001f7e2 Service back online"
        elif new_status == "DOWN":
            embed["title"] = "\U0001f534 Service went offline"

    return {"embeds": [embed]}


# ==================== DISCORD ====================

def send_discord(payload: dict) -> None:
    if DRY_RUN:
        print("\n" + "=" * 60)
        print("DRY RUN - Payload that would be sent:")
        print(json.dumps(payload, indent=2))
        print("=" * 60 + "\n")
        return

    if not DISCORD_WEBHOOK_URL:
        print("[ERROR] No webhook URL configured")
        return

    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        if resp.status_code in (200, 204):
            print("[OK] Embed sent")
        else:
            print(f"[ERROR] Discord returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[ERROR] Failed to send to Discord: {e}")


# ==================== MAIN ====================

def main():
    print("=== Fortnite Staging Server Notifier ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")

    token = get_epic_token()
    if not token:
        print("[ERROR] Could not obtain Epic auth token \u2014 aborting.")
        raise SystemExit(1)

    servers = fetch_staging(token)
    if servers is None:
        print("[ERROR] Could not fetch staging data \u2014 aborting.")
        raise SystemExit(1)

    state = load_state()

    if TEST_LAST:
        if not servers:
            print("[TEST] No servers found.")
            return
        raw = servers[-1]
        sid = raw.get("serviceInstanceId", "UnknownService")
        current = normalise(raw)
        fake_old = {
            **current,
            "status": "DOWN" if current["status"] == "UP" else "UP",
            "message": "Previous message (test)",
        }
        print(f"[TEST] Sending test embed for: {sid}")
        payload = build_embed(sid, fake_old, current)
        send_discord(payload)
        print("[TEST] Done (state untouched).")
        return

    if not state:
        new_state = {}
        for raw in servers:
            sid = raw.get("serviceInstanceId", "UnknownService")
            new_state[sid] = normalise(raw)
        save_state(new_state)
        print(f"[SEED] First run \u2014 seeded {len(new_state)} service(s). No notifications sent.")
        return

    new_state = {**state}
    notified = 0

    for raw in servers:
        sid = raw.get("serviceInstanceId", "UnknownService")
        current = normalise(raw)
        previous = state.get(sid)

        if previous is None:
            print(f"[NEW] Service appeared: {sid} \u2014 seeding (no notification).")
            new_state[sid] = current
            continue

        if current == previous:
            continue

        print(f"[CHANGE] {sid}: {previous['status']} \u2192 {current['status']}")
        payload = build_embed(sid, previous, current)
        send_discord(payload)
        new_state[sid] = current
        notified += 1

    if notified == 0:
        print("No staging changes detected.")

    save_state(new_state)
    print("Done.")


if __name__ == "__main__":
    main()
