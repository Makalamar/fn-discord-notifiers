#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fortnite Image/Video URL Notifier
Detects new image and video URLs from Fortnite-only endpoints and posts them
via a dedicated Discord webhook.

Sources used (all Fortnite-scoped only):
  - fortnitecontent-website-prod07.ol.epicgames.com/content/api/pages/fortnite-game
      -> dynamicbackgrounds  (lobby/vault keyarts — still active)
      -> battleroyalnews     (BR news images — extracted from full page response)
      -> savetheworld        (STW news images — extracted from full page response)
      -> creative            (Creative news images — extracted from full page response)

The old /fortnite-game/<subkey> routes (battleroyal-news, save-the-world-news,
creative-news) return 404. The correct approach per the official docs is to
fetch /content/api/pages/fortnite-game once and navigate into the JSON keys.

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

# ── Official Epic CMS — single call, all sections extracted from JSON ────────
# Fetching /fortnite-game once is more efficient and avoids the 404 sub-key issue.
# Keys below are the top-level JSON properties present in the response.
FN_CONTENT_BASE_URL = (
    "https://fortnitecontent-website-prod07.ol.epicgames.com"
    "/content/api/pages/fortnite-game"
)

# Sub-sections we want to extract from the full fortnite-game response.
# Each tuple is (label_for_logs, dot-separated path inside the JSON).
# e.g. "battleroyalnews.news.messages" means data["battleroyalnews"]["news"]["messages"]
FN_CONTENT_SECTIONS = [
    ("dynamicbackgrounds", "dynamicbackgrounds"),
    ("battleroyalnews",    "battleroyalnews"),
    ("savetheworld",       "savetheworld"),
    ("creative",           "creative"),
]

# Supported media extensions
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
VIDEO_EXTS = (".mp4", ".webm", ".mov", ".mpd", ".m3u8")

# ── CDN allow-list: domains that serve Fortnite media ─────────────────────────
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


def fetch_fortnite_content() -> Dict[str, Any]:
    """
    Fetch the full /content/api/pages/fortnite-game response once and extract
    the relevant sub-sections (dynamicbackgrounds, battleroyalnews, savetheworld,
    creative).  This replaces the old per-subkey calls that return 404.
    """
    result: Dict[str, Any] = {}
    try:
        resp = requests.get(FN_CONTENT_BASE_URL, timeout=30)
        resp.raise_for_status()
        page_data = resp.json()
    except Exception as e:
        print(f"[API] Failed to fetch {FN_CONTENT_BASE_URL}: {e}")
        return result

    for label, key in FN_CONTENT_SECTIONS:
        section = page_data.get(key)
        if section is not None:
            result[label] = section
            print(f"[API] Fetched section: {label}")
        else:
            print(f"[API] Section '{label}' not found in fortnite-game response")

    return result


def is_video(url: str) -> bool:
    """Return True if the URL points to a video file."""
    return any(url.lower().endswith(ext) for ext in VIDEO_EXTS)


def build_embed(url: str) -> dict:
    """
    Build a Discord embed payload for the given media URL.

    Layout (mirrors the url-tracker screenshot):
      - title   : the raw URL, clickable (links to the media)
      - image   : thumbnail rendered inline (images only)
      - color   : Fortnite blue accent
      - footer  : detection date/time
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    now_display = datetime.now().strftime("%d/%m/%Y %H:%M")

    embed: Dict[str, Any] = {
        "title": url,
        "url": url,
        "color": 0x6B21A8,          # Fortnite purple accent
        "footer": {
            "text": now_display,
        },
        "timestamp": now_iso,
    }

    # Attach image preview for image files; videos get a plain link embed
    if not is_video(url):
        embed["image"] = {"url": url}

    return {"embeds": [embed]}


def send_discord(payload: dict) -> None:
    if DRY_RUN:
        print("\n" + "=" * 60)
        print("DRY RUN - Payload that would be sent:")
        print("=" * 60)
        print(json.dumps(payload, indent=2))
        print("=" * 60 + "\n")
        return

    if not DISCORD_WEBHOOK_URL:
        print("[ERROR] No webhook URL configured")
        return

    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        if resp.status_code in (200, 204):
            title = payload.get("embeds", [{}])[0].get("title", "")
            print(f"[OK] Sent embed: {title[:80]}...")
        else:
            print(f"[ERROR] Discord returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[ERROR] Failed to send to Discord: {e}")

def main():
    global DRY_RUN
    print(f"=== Fortnite Image/Video URL Notifier ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")

    notified = load_notified()

    content_data = fetch_fortnite_content()

    if not content_data:
        print("[ERROR] No data received from any source")
        return

    raw_urls = extract_media_urls(content_data)
    current_urls = [u for u in raw_urls if is_fortnite_media(u)]

    print(f"[INFO] {len(raw_urls)} raw URLs found -> {len(current_urls)} passed Fortnite filter")

    # ===================== TEST MODE =====================
    if TEST_LAST_MEDIA:
        print("[TEST] Mode activé : envoi de la dernière image/vidéo détectée")
        if not current_urls:
            print("[TEST] Aucune URL trouvée.")
            return
        latest_url = current_urls[-1]
        print(f"[TEST] Dernière URL : {latest_url}")
        payload = build_embed(latest_url)
        original_dry = DRY_RUN
        DRY_RUN = False
        send_discord(payload)
        DRY_RUN = original_dry
        print("[TEST] Terminé (le state 'notified' n'a pas été modifié).")
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
        payload = build_embed(url)
        send_discord(payload)
        notified.add(url)

    save_notified(notified)
    print("Done.")

if __name__ == "__main__":
    main()
