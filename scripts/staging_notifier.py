#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fortnite Staging Server Notifier

Fetches staging server data from NiteStats JSON API endpoints and posts
a Discord embed whenever a staging server changes its build.

Data sources (tried in order):
  1. https://nitestats.com/v1/epic/staging          (primary JSON API)
  2. https://nitestats.com/api/v1/staging           (legacy alias)
  3. https://fortniteapi.io/v1/status?lang=en       (fallback, staging field)

Embed colour code:
  Blue  (0x3498DB) - normal build update (same version)
  Red   (0xE74C3C) - version change
"""

import os
import re
import json
import requests
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ==================== CONFIG ====================
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_STAGING_WEBHOOK_URL", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1" or not DISCORD_WEBHOOK_URL
TEST_LAST = os.environ.get("TEST_LAST_STAGING", "0") == "1"
FORTNITE_API_KEY = os.environ.get("FORTNITE_API_KEY", "").strip()

STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "staging_state.json",
)

# API endpoints tried in order
NITESTATS_API_URLS = [
    "https://nitestats.com/v1/epic/staging",
    "https://nitestats.com/api/v1/staging",
]
FORTNITEAPI_IO_STATUS = "https://fortniteapi.io/v1/status"

HTTP_TIMEOUT = 30
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

COLOR_NORMAL = 0x3498DB
COLOR_VERSION_CHANGE = 0xE74C3C


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


# ==================== FETCHING ====================

def _try_nitestats_api() -> Optional[List[Dict[str, Any]]]:
    """Try NiteStats JSON API endpoints directly."""
    for url in NITESTATS_API_URLS:
        try:
            resp = requests.get(url, headers=BROWSER_HEADERS, timeout=HTTP_TIMEOUT)
            if resp.status_code == 403:
                print(f"[API] {url} → 403 Forbidden, trying next...")
                continue
            resp.raise_for_status()
            data = resp.json()
            # Response may be a list or a dict with a servers/staging key
            if isinstance(data, list):
                print(f"[API] Fetched {len(data)} server(s) from {url}")
                return data
            if isinstance(data, dict):
                for key in ("staging", "servers", "stagingServers", "data"):
                    val = data.get(key)
                    if isinstance(val, list) and len(val) > 0:
                        print(f"[API] Fetched {len(val)} server(s) from {url} (key: {key})")
                        return val
                # Single-server dict?
                server_keys = {"name", "serverName", "cln", "CLN", "build", "buildId", "version"}
                if server_keys & data.keys():
                    print(f"[API] Fetched 1 server from {url}")
                    return [data]
                print(f"[API] {url} → unexpected JSON shape, keys: {list(data.keys())}")
        except requests.exceptions.JSONDecodeError:
            print(f"[API] {url} → response is not JSON")
        except Exception as e:
            print(f"[API] {url} → {e}")
    return None


def _try_fortniteapi_io() -> Optional[List[Dict[str, Any]]]:
    """
    Fallback: fortniteapi.io /v1/status — may contain a staging section.
    Requires FORTNITE_API_KEY env var if the endpoint is auth-gated.
    """
    headers = {**BROWSER_HEADERS}
    if FORTNITE_API_KEY:
        headers["Authorization"] = FORTNITE_API_KEY
    try:
        resp = requests.get(
            FORTNITEAPI_IO_STATUS,
            headers=headers,
            params={"lang": "en"},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        for key in ("staging", "stagingServers", "servers"):
            val = data.get(key)
            if isinstance(val, list) and len(val) > 0:
                print(f"[API] Fetched {len(val)} server(s) from fortniteapi.io (key: {key})")
                return val
        print(f"[API] fortniteapi.io → no staging data found. Keys: {list(data.keys())}")
    except Exception as e:
        print(f"[API] fortniteapi.io → {e}")
    return None


def fetch_staging() -> Optional[List[Dict[str, Any]]]:
    """
    Try all known data sources in order.
    Returns a list of raw server dicts, or None on total failure.
    """
    servers = _try_nitestats_api()
    if servers is not None:
        return servers

    print("[API] All NiteStats endpoints failed — trying fortniteapi.io fallback...")
    servers = _try_fortniteapi_io()
    if servers is not None:
        return servers

    print("[API] All data sources exhausted.")
    return None


# ==================== EMBED ====================

def _s(text: Any) -> str:
    return str(text).strip() if text not in (None, "") else "-"


def build_embed(server_name: str, old: Dict[str, Any], new: Dict[str, Any]) -> dict:
    old_version = _s(old.get("version"))
    new_version = _s(new.get("version"))
    version_changed = old_version != new_version
    color = COLOR_VERSION_CHANGE if version_changed else COLOR_NORMAL

    old_cln    = _s(old.get("cln") or old.get("CLN"))
    old_build  = _s(old.get("build") or old.get("buildId"))
    old_module = _s(old.get("module"))
    old_date   = _s(old.get("buildDate") or old.get("date"))
    old_branch = _s(old.get("branch"))

    new_cln    = _s(new.get("cln") or new.get("CLN"))
    new_build  = _s(new.get("build") or new.get("buildId"))
    new_module = _s(new.get("module"))
    new_date   = _s(new.get("buildDate") or new.get("date"))
    new_branch = _s(new.get("branch"))

    desc_lines = [
        f"**{server_name}**",
        "",
        "**CLN** \u00b7 **Build** \u00b7 **Module**",
        f"~~{old_cln}~~ \u00b7 ~~{old_build}~~ \u00b7 ~~{old_module}~~",
        f"{new_cln} \u00b7 {new_build} \u00b7 {new_module}",
        "",
        "**Build Date (UTC)** \u00b7 **Version** \u00b7 **Branch**",
        f"~~{old_date}~~ \u00b7 ~~{old_version}~~ \u00b7 ~~{old_branch}~~",
        f"{new_date} \u00b7 {new_version} \u00b7 {new_branch}",
    ]

    embed: Dict[str, Any] = {
        "description": "\n".join(desc_lines),
        "color": color,
        "footer": {"text": "nitestats.com/staging"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if version_changed:
        embed["title"] = "\U0001f534 Version change detected"

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

def normalise_server(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "cln":       raw.get("cln") or raw.get("CLN") or "-",
        "build":     raw.get("build") or raw.get("buildId") or "-",
        "module":    raw.get("module") or raw.get("Module") or "-",
        "buildDate": raw.get("buildDate") or raw.get("date") or "-",
        "version":   raw.get("version") or "-",
        "branch":    raw.get("branch") or "-",
    }


def main():
    print("=== Fortnite Staging Server Notifier ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")

    servers = fetch_staging()
    if servers is None:
        print("[ERROR] Could not fetch staging data \u2014 aborting.")
        raise SystemExit(1)

    state = load_state()

    if TEST_LAST:
        if not servers:
            print("[TEST] No servers found.")
            return
        raw = servers[-1]
        name = raw.get("name") or raw.get("serverName") or "UnknownServer"
        current = normalise_server(raw)
        fake_old = {
            **current,
            "build": str(int(current["build"]) - 1)
            if current["build"].isdigit()
            else current["build"] + "-old",
        }
        print(f"[TEST] Sending test embed for: {name}")
        payload = build_embed(name, fake_old, current)
        send_discord(payload)
        print("[TEST] Done (state untouched).")
        return

    if not state:
        new_state = {}
        for raw in servers:
            name = raw.get("name") or raw.get("serverName") or "UnknownServer"
            new_state[name] = normalise_server(raw)
        save_state(new_state)
        print(f"[SEED] First run \u2014 seeded {len(new_state)} server(s). No notifications sent.")
        return

    new_state = {**state}
    notified = 0

    for raw in servers:
        name = raw.get("name") or raw.get("serverName") or "UnknownServer"
        current = normalise_server(raw)
        previous = state.get(name)

        if previous is None:
            print(f"[NEW] Server appeared: {name} \u2014 seeding (no notification).")
            new_state[name] = current
            continue

        if current == previous:
            continue

        print(f"[CHANGE] {name}")
        payload = build_embed(name, previous, current)
        send_discord(payload)
        new_state[name] = current
        notified += 1

    if notified == 0:
        print("No staging changes detected.")

    save_state(new_state)
    print("Done.")


if __name__ == "__main__":
    main()
