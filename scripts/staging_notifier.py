#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fortnite Staging Server Notifier

Scrapes the NiteStats staging page and posts a Discord embed whenever
a staging server changes its build.

Data source: https://nitestats.com/staging  (HTML scraping via BeautifulSoup)
The old /api/v1/staging endpoint no longer exists.

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

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore

# ==================== CONFIG ====================
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_STAGING_WEBHOOK_URL", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1" or not DISCORD_WEBHOOK_URL
TEST_LAST = os.environ.get("TEST_LAST_STAGING", "0") == "1"

STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "staging_state.json",
)

# NiteStats staging page — data is embedded in a Next.js __NEXT_DATA__ JSON blob
NITESTATS_PAGE_URL = "https://nitestats.com/staging"

HTTP_TIMEOUT = 30
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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


# ==================== SCRAPING ====================

def _extract_next_data(html: str) -> Optional[dict]:
    """
    Extract the JSON payload from <script id="__NEXT_DATA__"> in a Next.js page.
    Returns the parsed dict, or None if not found.
    """
    # Try BeautifulSoup first (more robust)
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")
        tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if tag and tag.string:
            try:
                return json.loads(tag.string)
            except json.JSONDecodeError as e:
                print(f"[PARSE] JSON decode error in __NEXT_DATA__: {e}")
                return None

    # Fallback: regex
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>', html)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError as e:
            print(f"[PARSE] JSON decode error (regex fallback): {e}")
    return None


def _parse_servers(next_data: dict) -> List[Dict[str, Any]]:
    """
    Walk the Next.js page props tree to find the staging server list.
    NiteStats typically nests it under:
      props.pageProps.stagingServers   OR
      props.pageProps.servers          OR
      props.pageProps.data.servers     etc.
    We search recursively for the first list that looks like server objects.
    """
    def looks_like_server_list(obj):
        if not isinstance(obj, list) or len(obj) == 0:
            return False
        first = obj[0]
        if not isinstance(first, dict):
            return False
        # Must have at least one of the expected server keys
        server_keys = {"name", "serverName", "cln", "CLN", "build", "buildId", "version", "branch"}
        return bool(server_keys & first.keys())

    def search(node, depth=0):
        if depth > 10:
            return None
        if looks_like_server_list(node):
            return node
        if isinstance(node, dict):
            for v in node.values():
                result = search(v, depth + 1)
                if result is not None:
                    return result
        if isinstance(node, list):
            for item in node:
                result = search(item, depth + 1)
                if result is not None:
                    return result
        return None

    return search(next_data) or []


def fetch_staging() -> Optional[List[Dict[str, Any]]]:
    """
    Fetch the NiteStats staging page and extract server data from __NEXT_DATA__.
    Returns a list of raw server dicts, or None on failure.
    """
    try:
        resp = requests.get(NITESTATS_PAGE_URL, headers=BROWSER_HEADERS, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        print(f"[API] Failed to fetch staging page: {e}")
        return None

    next_data = _extract_next_data(resp.text)
    if next_data is None:
        print("[API] Could not find __NEXT_DATA__ in the NiteStats staging page.")
        print("[API] The page structure may have changed — manual inspection required.")
        return None

    servers = _parse_servers(next_data)
    if not servers:
        print("[API] __NEXT_DATA__ found but no server list detected inside it.")
        print("[API] Keys available in pageProps:", list(
            next_data.get("props", {}).get("pageProps", {}).keys()
        ))
        return None

    print(f"[API] Fetched {len(servers)} server(s) from NiteStats staging page")
    return servers


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
        return

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
