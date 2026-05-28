#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fortnite Official Patch / News Notifier (Discord Webhook)
- Uses the reliable public API: https://fortnite-api.com/v2/news
- Detects new official announcements and updates from Epic
- Posts rich English embeds to Discord (with images when available)
- Runs reliably via GitHub Actions (no scraping anti-bot issues)

Environment:
  DISCORD_WEBHOOK_URL   (required to actually post)
  DRY_RUN=1             (optional - prints what would be sent)
"""

import os
import sys
import json
import time
from datetime import datetime, timezone
from typing import List, Dict, Any

import requests

API_URL = "https://fortnite-api.com/v2/news?language=en"
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1" or not WEBHOOK_URL

STATE_FILE = "data/last_notified.json"
HEADERS = {
    "User-Agent": "fortnite-patch-notifier/2.0 (github-actions)",
    "Accept": "application/json",
}


def load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {"last_ids": []}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Support both old "last_patch" and new "last_ids" format
            if "last_ids" not in data:
                data["last_ids"] = []
            return data
    except Exception:
        return {"last_ids": []}


def save_state(state: Dict[str, Any]):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def fetch_news() -> List[Dict[str, Any]]:
    """Fetch current Battle Royale news from the public API."""
    try:
        resp = requests.get(API_URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        br = data.get("data", {}).get("br", {})
        motds = br.get("motds", []) or []
        return motds
    except Exception as e:
        print(f"[ERROR] Failed to fetch news API: {e}", file=sys.stderr)
        return []


def is_update_relevant(item: Dict[str, Any]) -> bool:
    """Heuristic: keep items that look like actual game updates."""
    title = (item.get("title") or "").lower()
    body = (item.get("body") or "").lower()
    tab = (item.get("tabTitle") or "").lower()

    keywords = [
        "update", "patch", "hotfix", "season", "chapter",
        "v3", "v4", "v5", "v6", "v7", "v8", "v9",   # version numbers
        "downtime", "maintenance", "content update"
    ]
    text = f"{title} {body} {tab}"
    return any(k in text for k in keywords)


def send_to_discord(item: Dict[str, Any]) -> bool:
    """Send a rich embed for one news item."""
    title = item.get("title", "Fortnite Update")
    body = item.get("body", "")
    image = item.get("image") or item.get("tileImage")

    # Truncate body for Discord (embeds have limits)
    if len(body) > 1800:
        body = body[:1797] + "..."

    embed: Dict[str, Any] = {
        "title": title,
        "description": body or "New official Fortnite update / announcement.",
        "color": 0x00b0f4,
        "url": "https://www.fortnite.com/news",   # Best general direct link to official patch notes hub
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": "Fortnite Official News"},
    }

    if image:
        embed["image"] = {"url": image}

    # Add tab title as a small field if useful
    if item.get("tabTitle"):
        embed.setdefault("fields", []).append({
            "name": "Category",
            "value": item["tabTitle"],
            "inline": True
        })

    payload = {"embeds": [embed]}

    if DRY_RUN:
        print("=== DRY RUN - Would send to Discord ===")
        print(json.dumps(payload, indent=2))
        return True

    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=15)
        if r.status_code in (200, 204):
            return True
        print(f"[ERROR] Webhook failed ({r.status_code}): {r.text[:300]}")
        return False
    except Exception as e:
        print(f"[ERROR] Failed to call Discord webhook: {e}")
        return False


def main():
    print("=== Fortnite Discord Notifier (fortnite-api.com) ===")
    print(f"UTC time: {datetime.now(timezone.utc).isoformat()}")
    print(f"DRY_RUN={DRY_RUN}")

    news_items = fetch_news()
    if not news_items:
        print("No news items returned. Exiting.")
        return

    print(f"Fetched {len(news_items)} BR news items from API.")

    state = load_state()
    seen_ids = set(state.get("last_ids", []))

    # Filter to relevant update-style items + not yet notified
    candidates = []
    for item in news_items:
        nid = item.get("id")
        if not nid:
            continue
        if nid in seen_ids:
            continue
        if is_update_relevant(item):
            candidates.append(item)

    if not candidates:
        print("No new relevant updates since last run.")
        return

    print(f"Found {len(candidates)} new update(s) to post.")

    # Post oldest first (API usually returns newest first)
    candidates.sort(key=lambda x: x.get("sortingPriority", 0), reverse=True)

    posted_ids = []
    for item in candidates:
        print(f"  → Posting: {item.get('title')[:70]}...")
        if send_to_discord(item):
            posted_ids.append(item["id"])
            time.sleep(1.0)  # rate limit safety between messages
        else:
            print("     Failed — will try again next run.")

    if posted_ids:
        # Update state with newly posted IDs (keep last 50 to avoid unbounded growth)
        new_seen = list(seen_ids) + posted_ids
        state["last_ids"] = new_seen[-50:]
        state["last_updated"] = datetime.now(timezone.utc).isoformat()
        save_state(state)
        print(f"State saved. Total tracked IDs: {len(state['last_ids'])}")

    print("Done.")


if __name__ == "__main__":
    main()
