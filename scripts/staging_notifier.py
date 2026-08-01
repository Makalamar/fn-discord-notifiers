#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fortnite Staging Server Notifier

Poll the NiteStats staging API every N minutes and post a Discord embed
whenever a staging server changes its build.

Embed format (mirrors NiteStats Discord bot):
  Title  : <ServerName>  (bold)
  Fields : CLN / Build / Module  (old strikethrough, new plain)
           Build Date (UTC) / Version / Branch  (old strikethrough, new plain)

Colour code:
  Blue  (0x3498DB) - normal build update (same version)
  Red   (0xE74C3C) - version change
"""

import os
import json
import requests
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ==================== CONFIG ====================
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_STAGING_WEBHOOK_URL", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1" or not DISCORD_WEBHOOK_URL
TEST_LAST = os.environ.get("TEST_LAST_STAGING", "0") == "1"

STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "staging_state.json",
)

# NiteStats public API — returns an array of staging server objects
NITESTATS_URL = "https://api.nitestats.com/v1/staging"

HTTP_TIMEOUT = 30
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://nitestats.com/",
    "Origin": "https://nitestats.com",
}

COLOR_NORMAL = 0x3498DB   # blue
COLOR_VERSION_CHANGE = 0xE74C3C  # red


# ==================== STATE ====================

def load_state() -> Dict[str, Any]:
    """Return {serverName: {cln, build, module, buildDate, version, branch}}"""
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


# ==================== API ====================

def fetch_staging() -> Optional[List[Dict[str, Any]]]:
    try:
        resp = requests.get(NITESTATS_URL, headers=BROWSER_HEADERS, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        print(f"[API] Fetched {len(data)} server(s) from NiteStats")
        return data
    except Exception as e:
        print(f"[API] Failed to fetch staging data: {e}")
        return None


# ==================== EMBED ====================

def _s(text: Any) -> str:
    """Stringify a value, return '-' if None/empty."""
    return str(text).strip() if text not in (None, "") else "-"


def strikethrough(text: str) -> str:
    return f"~~{text}~~"


def build_embed(server_name: str, old: Dict[str, Any], new: Dict[str, Any]) -> dict:
    """
    Build a Discord embed that mirrors the NiteStats bot layout:

    **ServerName**
    Modification Detected: <serverKey>

    CLN           Build   Module
    ~~41401420~~  ~~387~~ ~~Fortnite-Core~~
    41444190      389     Fortnite-Core

    Build Date (UTC)           Version  Branch
    ~~04/06/25, 08:38:40 AM~~  ~~34.30~~ ~~Release-34.30~~
    04/08/25, 07:45:22.073 AM  34.30    Release-34.30
    """
    old_version = _s(old.get("version"))
    new_version = _s(new.get("version"))
    version_changed = old_version != new_version
    color = COLOR_VERSION_CHANGE if version_changed else COLOR_NORMAL

    # Row helpers
    def row(a, b, c):
        return f"`{a:<14}` `{b:<7}` `{c}`"

    old_cln = _s(old.get("cln"))
    old_build = _s(old.get("build"))
    old_module = _s(old.get("module"))
    old_date = _s(old.get("buildDate"))
    old_branch = _s(old.get("branch"))

    new_cln = _s(new.get("cln"))
    new_build = _s(new.get("build"))
    new_module = _s(new.get("module"))
    new_date = _s(new.get("buildDate"))
    new_branch = _s(new.get("branch"))

    # Build the description that replicates the embed table layout
    desc_lines = [
        f"**{server_name}**",
        "",
        "**CLN** · **Build** · **Module**",
        f"~~{old_cln}~~ · ~~{old_build}~~ · ~~{old_module}~~",
        f"{new_cln} · {new_build} · {new_module}",
        "",
        "**Build Date (UTC)** · **Version** · **Branch**",
        f"~~{old_date}~~ · ~~{old_version}~~ · ~~{old_branch}~~",
        f"{new_date} · {new_version} · {new_branch}",
    ]

    embed: Dict[str, Any] = {
        "description": "\n".join(desc_lines),
        "color": color,
        "footer": {"text": "nitestats.com/discord"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if version_changed:
        embed["title"] = "🔴 Version change detected"

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
            print(f"[OK] Embed sent")
        else:
            print(f"[ERROR] Discord returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[ERROR] Failed to send to Discord: {e}")


# ==================== MAIN ====================

def normalise_server(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the fields we care about from a NiteStats server object."""
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
        print("[ERROR] Could not fetch staging data — aborting.")
        return

    state = load_state()

    # TEST mode: re-send the last known server as if it changed
    if TEST_LAST:
        if not servers:
            print("[TEST] No servers found.")
            return
        raw = servers[-1]
        name = raw.get("name") or raw.get("serverName") or "UnknownServer"
        current = normalise_server(raw)
        # Fake a previous state slightly different so the embed shows a diff
        fake_old = {**current, "build": str(int(current["build"]) - 1) if current["build"].isdigit() else current["build"] + "-old"}
        print(f"[TEST] Sending test embed for: {name}")
        payload = build_embed(name, fake_old, current)
        send_discord(payload)
        print("[TEST] Done (state untouched).")
        return

    if not state:
        # First run — seed state, no notifications
        new_state = {}
        for raw in servers:
            name = raw.get("name") or raw.get("serverName") or "UnknownServer"
            new_state[name] = normalise_server(raw)
        save_state(new_state)
        print(f"[SEED] First run — seeded {len(new_state)} server(s). No notifications sent.")
        return

    new_state = {**state}
    notified = 0

    for raw in servers:
        name = raw.get("name") or raw.get("serverName") or "UnknownServer"
        current = normalise_server(raw)
        previous = state.get(name)

        if previous is None:
            # New server appeared — seed it silently
            print(f"[NEW] Server appeared: {name} — seeding (no notification).")
            new_state[name] = current
            continue

        # Detect change: any field different?
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
