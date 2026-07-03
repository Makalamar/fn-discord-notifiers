#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fortnite Image/Video URL Notifier
Detects new image and video URLs from Fortnite-only endpoints and posts them
via a dedicated Discord webhook.

Sources used (all Fortnite-scoped only):
  - fortnite-api.com/v2/news        (aggregated BR + STW + Creative)
  - fortnite-api.com/v2/news/br     (BR news images)
  - fortnite-api.com/v2/news/stw    (STW news images)
  - fortnite-api.com/v2/news/creative (Creative news images)
  - fortnitecontent-website-prod07.ol.epicgames.com/content/api/pages/fortnite-game/dynamicbackgrounds

Ref: https://github.com/LeleDerGrasshalmi/FortniteEndpointsDocumentation
"""

import os
import json
import requests
from datetime import datetime, timezone
from typing import Set, Dict, Any, List

# ==================== CONFIG ====================
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_IMAGE_URL_WEBHOOK_URL", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1" or not DISCORD_WEBHOOK_URL
TEST_LAST_MEDIA = os.environ.get("TEST_LAST_MEDIA", "0") == "1"

STATE_FILE = "data/notified_image_urls.json"

# ── fortnite-api.com endpoints (news, by gamemode) ──────────────────────────
NEWS_API_URL = "https://fortnite-api.com/v2/news"

# Individual gamemode news endpoints (same API, finer granularity)
NEWS_GAMEMODE_ENDPOINTS = [
    ("news_br",       "https://fortnite-api.com/v2/news/br"),
    ("news_stw",      "https://fortnite-api.com/v2/news/stw"),
    ("news_creative", "https://fortnite-api.com/v2/news/creative"),
]

# ── Official Fortnite-only content endpoints (Epic CMS) ─────────────────────
# Only endpoints confirmed active are kept here.
# battleroyal-news, save-the-world-news, creative-news and the blog
# endpoint all return 404 and have been replaced by fortnite-api.com above.
FORTNITE_CONTENT_ENDPOINTS = [
    # Dynamic backgrounds (launcher blade images, season keyarts) — still active
    "https://fortnitecontent-website-prod07.ol.epicgames.com/content/api/pages/fortnite-game/dynamicbackgrounds",
]

# Supported media extensions
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
VIDEO_EXTS = (".mp4", ".webm", ".mov", ".mpd", ".m3u8")

# ── CDN allow-list: domains that serve Fortnite media ─────────────────────────
# media.fortniteapi.io is the CDN used by fortnite-api.com for news images.
FORTNITE_CDN_DOMAINS = (
    "cdn2.unrealengine.com",
    "media.fortniteapi.io",
    "fortnitecontent-website-prod07.ol.epicgames.com",
    "epic-games-store-cdn.qstv.on.epicgames.com",
)

# ── URL slug patterns that confirm Fortnite origin ───────────────────────────
FORTNITE_URL_PATTERNS = (
    "fortnite",
    "fnbr-",
    "brfnbr-",
    "fn-og-",
    "fn-og/",
    "/fn-",
    "fn-c",
    "gameplayscreenshot",
    "egs-launcher-blade",
    "keyart",
    "discovertile",
    "festivalpass",
    "rocketracing",
    "lego-fortnite",
    "legofortnite",
    "savetheworldnews",
    "battleroyal",
    "creativenews",
)


def load_notified() -> Set[str]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data) if isinstance(data, list) else set()
        except Exception:
            pass
    return set()

def save_notified(urls: Set[str]) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(urls)), f, indent=2)

def extract_media_urls(data: Any) -> List[str]:
    """Recursively find all HTTP URLs that look like images or videos."""
    urls: List[str] = []
    seen: Set[str] = set()

    def recurse(obj: Any):
        if isinstance(obj, dict):
            for value in obj.values():
                recurse(value)
        elif isinstance(obj, list):
            for item in obj:
                recurse(item)
        elif isinstance(obj, str):
            if obj.startswith("http"):
                lower = obj.lower()
                if any(lower.endswith(ext) for ext in IMAGE_EXTS + VIDEO_EXTS):
                    if obj not in seen:
                        seen.add(obj)
                        urls.append(obj)

    recurse(data)
    return urls


def is_fortnite_media(url: str) -> bool:
    """
    Two-pass filter:
      1. Domain allow-list  -> CDN must be a known Fortnite CDN.
      2. Path slug check    -> URL path must contain at least one Fortnite pattern.
    """
    u = url.lower()

    if not any(domain in u for domain in FORTNITE_CDN_DOMAINS):
        return False

    # Fortnite-exclusive domains: no additional slug check needed
    fortnite_exclusive_domains = (
        "fortnitecontent-website-prod07.ol.epicgames.com",
        "epic-games-store-cdn.qstv.on.epicgames.com",
        "media.fortniteapi.io",
    )
    if any(domain in u for domain in fortnite_exclusive_domains):
        return True

    # Shared CDNs (cdn2.unrealengine.com): require a Fortnite path slug
    return any(pattern in u for pattern in FORTNITE_URL_PATTERNS)


def fetch_news() -> Dict[str, Any]:
    """Fetch aggregated news from fortnite-api.com (BR + STW + Creative combined)."""
    try:
        resp = requests.get(NEWS_API_URL, timeout=30)
        resp.raise_for_status()
        return resp.json().get("data", {})
    except Exception as e:
        print(f"[API] Failed to fetch news: {e}")
        return {}

def fetch_news_by_gamemode() -> Dict[str, Any]:
    """Fetch per-gamemode news from fortnite-api.com (finer granularity)."""
    merged: Dict[str, Any] = {}
    for key, url in NEWS_GAMEMODE_ENDPOINTS:
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            merged[key] = resp.json().get("data", {})
            print(f"[API] Fetched: {key}")
        except Exception as e:
            print(f"[API] Failed to fetch {url}: {e}")
    return merged

def fetch_fortnite_content_endpoints() -> Dict[str, Any]:
    """Fetch active Epic CMS content endpoints (currently: dynamicbackgrounds only)."""
    merged: Dict[str, Any] = {}
    for url in FORTNITE_CONTENT_ENDPOINTS:
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            key = url.split("/")[-1].split("?")[0]
            merged[key] = resp.json()
            print(f"[API] Fetched: {key}")
        except Exception as e:
            print(f"[API] Failed to fetch {url}: {e}")
    return merged

def build_message(url: str) -> str:
    """Build a plain-text message: URL on first line, bold date/time on second line.
    Discord automatically renders image previews for image URLs.
    """
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    return f"{url}\n**{now}**"

def send_discord(message: str) -> None:
    if DRY_RUN:
        print("\n" + "=" * 60)
        print("DRY RUN - Message that would be sent:")
        print("=" * 60)
        print(message)
        print("=" * 60 + "\n")
        return

    if not DISCORD_WEBHOOK_URL:
        print("[ERROR] No webhook URL configured")
        return

    payload = {"content": message}
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        if resp.status_code in (200, 204):
            print(f"[OK] Sent: {message[:80]}...")
        else:
            print(f"[ERROR] Discord returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[ERROR] Failed to send to Discord: {e}")

def main():
    global DRY_RUN
    print(f"=== Fortnite Image/Video URL Notifier ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")

    notified = load_notified()

    news_data = fetch_news()
    gamemode_data = fetch_news_by_gamemode()
    content_data = fetch_fortnite_content_endpoints()

    if not news_data and not gamemode_data and not content_data:
        print("[ERROR] No data received from any source")
        return

    all_data = {
        "news": news_data,
        "gamemode": gamemode_data,
        "content": content_data,
    }

    raw_urls = extract_media_urls(all_data)
    current_urls = [u for u in raw_urls if is_fortnite_media(u)]

    print(f"[INFO] {len(raw_urls)} raw URLs found -> {len(current_urls)} passed Fortnite filter")

    # ===================== TEST MODE =====================
    if TEST_LAST_MEDIA:
        print("[TEST] Mode activ\u00e9 : envoi de la derni\u00e8re image/vid\u00e9o d\u00e9tect\u00e9e")
        if not current_urls:
            print("[TEST] Aucune URL trouv\u00e9e.")
            return
        latest_url = current_urls[-1]
        print(f"[TEST] Derni\u00e8re URL : {latest_url}")
        message = build_message(latest_url)
        original_dry = DRY_RUN
        DRY_RUN = False
        send_discord(message)
        DRY_RUN = original_dry
        print("[TEST] Termin\u00e9 (le state 'notified' n'a pas \u00e9t\u00e9 modifi\u00e9).")
        return
    # =====================================================

    new_urls = [u for u in current_urls if u not in notified]

    if not notified:
        save_notified(set(current_urls))
        print(f"[SEED] First run - seeded {len(current_urls)} existing URLs. No notifications sent.")
        return

    save_notified(set(current_urls))

    if not new_urls:
        print("No new image/video URLs detected.")
        return

    print(f"[INFO] Detected {len(new_urls)} new media URL(s)")

    for url in new_urls:
        message = build_message(url)
        send_discord(message)
        notified.add(url)

    save_notified(notified)
    print("Done.")

if __name__ == "__main__":
    main()
