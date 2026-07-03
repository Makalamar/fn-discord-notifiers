#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fortnite Image/Video URL Notifier
Detects new image and video URLs from Fortnite-only endpoints and posts them
as embeds via a dedicated Discord webhook.

Sources used (all Fortnite-scoped only):
  - fortnite-api.com/v2/news
  - fortnitecontent-website-prod07.ol.epicgames.com (BR news, STW news, Creative, dynamic BG)
  - epicgames.com/fortnite/api/blog (patch notes)

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

# ── Fortnite-API wrapper (news) ──────────────────────────────────────────────
NEWS_API_URL = "https://fortnite-api.com/v2/news"

# ── Official Fortnite-only content endpoints ─────────────────────────────────
# Source: https://github.com/LeleDerGrasshalmi/FortniteEndpointsDocumentation
# All of these are scoped exclusively to Fortnite; no cross-game pollution.
FORTNITE_CONTENT_ENDPOINTS = [
    # Dynamic backgrounds (launcher blade images, season keyarts)
    "https://fortnitecontent-website-prod07.ol.epicgames.com/content/api/pages/fortnite-game/dynamicbackgrounds",
    # BR in-game news / MOTD
    "https://fortnitecontent-website-prod07.ol.epicgames.com/content/api/pages/fortnite-game/battleroyal-news",
    # Save the World news
    "https://fortnitecontent-website-prod07.ol.epicgames.com/content/api/pages/fortnite-game/save-the-world-news",
    # Creative news
    "https://fortnitecontent-website-prod07.ol.epicgames.com/content/api/pages/fortnite-game/creative-news",
    # Fortnite blog / patch notes (keyarts + gameplay screenshots)
    "https://www.epicgames.com/fortnite/api/blog/getPosts?locale=en-US&postsPerPage=5",
]

# Supported media extensions
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
VIDEO_EXTS = (".mp4", ".webm", ".mov", ".mpd", ".m3u8")

# ── CDN allow-list: domains that serve Fortnite media ────────────────────────
# Based on real examples observed in Discord output (cf. screenshots)
FORTNITE_CDN_DOMAINS = (
    "cdn2.unrealengine.com",
    "media.fortniteapi.io",
    "fortnitecontent-website-prod07.ol.epicgames.com",
    "epic-games-store-cdn.qstv.on.epicgames.com",
)

# ── URL slug patterns that confirm Fortnite origin ───────────────────────────
# Derived from observed CDN URL structures (cdn2.unrealengine.com paths)
FORTNITE_URL_PATTERNS = (
    "fortnite",
    "fnbr-",           # e.g. fnbr-41-00-c7s3-egs-launcher-blade
    "brfnbr-",         # Battle Royale variant
    "fn-og-",          # OG season
    "fn-og/",
    "/fn-",            # generic /fn- prefix in path
    "fn-c",            # fn-c1s1 etc.
    "gameplayscreenshot",
    "egs-launcher-blade",
    "keyart",
    "discovertile",
    "festivalpass",
    "rocketracing",
    "lego-fortnite",
    "legofortnite",
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

    This dual check avoids false positives from CDNs that host multi-game assets
    (e.g. cdn2.unrealengine.com hosts non-Fortnite games too).
    """
    u = url.lower()

    # Pass 1 - domain must be a known Fortnite CDN
    if not any(domain in u for domain in FORTNITE_CDN_DOMAINS):
        return False

    # Pass 2 - for Fortnite-exclusive domains, no slug check needed
    fortnite_exclusive_domains = (
        "fortnitecontent-website-prod07.ol.epicgames.com",
        "epic-games-store-cdn.qstv.on.epicgames.com",
        "media.fortniteapi.io",
    )
    if any(domain in u for domain in fortnite_exclusive_domains):
        return True

    # For shared CDNs (cdn2.unrealengine.com), require a Fortnite path slug
    return any(pattern in u for pattern in FORTNITE_URL_PATTERNS)


def fetch_news() -> Dict[str, Any]:
    try:
        resp = requests.get(NEWS_API_URL, timeout=30)
        resp.raise_for_status()
        return resp.json().get("data", {})
    except Exception as e:
        print(f"[API] Failed to fetch news: {e}")
        return {}

def fetch_fortnite_content_endpoints() -> Dict[str, Any]:
    """Fetch all Fortnite-scoped content endpoints and merge results."""
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

def build_embed(url: str) -> Dict[str, Any]:
    is_video = any(url.lower().endswith(ext) for ext in VIDEO_EXTS)
    is_image = any(url.lower().endswith(ext) for ext in IMAGE_EXTS)

    embed: Dict[str, Any] = {
        "title": "New Image/Video URL Detected",
        "description": f"[View / Download]({url})",
        "url": url,
        "color": 0x00b0f4,
        "footer": {
            "text": "Fortnite Image/Video Tracker"
        }
    }

    if is_image:
        embed["image"] = {"url": url}
    elif is_video:
        embed["video"] = {"url": url}

    return embed

def send_discord(embed: Dict[str, Any]) -> None:
    if DRY_RUN:
        print("\n" + "=" * 60)
        print("DRY RUN - Embed that would be sent:")
        print("=" * 60)
        print(json.dumps({"embeds": [embed]}, indent=2, ensure_ascii=False))
        print("=" * 60 + "\n")
        return

    if not DISCORD_WEBHOOK_URL:
        print("[ERROR] DISCORD_IMAGE_URL_WEBHOOK_URL not set")
        return

    try:
        payload = {"embeds": [embed]}
        r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        if r.status_code in (200, 204):
            print("[DISCORD] New media URL posted successfully")
        else:
            print(f"[DISCORD] Webhook error {r.status_code}: {r.text[:300]}")
    except Exception as e:
        print(f"[DISCORD] Exception: {e}")

def main():
    global DRY_RUN
    print(f"=== Fortnite Image/Video URL Notifier ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")

    notified = load_notified()

    news_data = fetch_news()
    content_data = fetch_fortnite_content_endpoints()

    if not news_data and not content_data:
        print("[ERROR] No data received from any source")
        return

    all_data = {"news": news_data, "content": content_data}

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
        embed = build_embed(latest_url)
        original_dry = DRY_RUN
        DRY_RUN = False
        send_discord(embed)
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
        embed = build_embed(url)
        send_discord(embed)
        notified.add(url)

    save_notified(notified)
    print("Done.")

if __name__ == "__main__":
    main()
