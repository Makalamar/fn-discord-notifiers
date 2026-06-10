#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fortnite Image/Video URL Notifier
Detects new image and video URLs from Fortnite news and posts them as embeds
via a dedicated Discord webhook.
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
NEWS_API_URL = "https://fortnite-api.com/v2/news"
EGS_STOREFRONT_URL = "https://store-site-backend-static-ipv4.ak.epicgames.com/storefrontLayout?locale=en-US"

# Supported extensions for images and videos
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
VIDEO_EXTS = (".mp4", ".webm", ".mov", ".avi", ".mkv")

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
    """Recursively find all HTTP URLs that look like images or videos, preserving encounter order."""
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

def fetch_news() -> Dict[str, Any]:
    try:
        resp = requests.get(NEWS_API_URL, timeout=30)
        resp.raise_for_status()
        return resp.json().get("data", {})
    except Exception as e:
        print(f"[API] Failed to fetch news: {e}")
        return {}

def fetch_egs_storefront() -> Dict[str, Any]:
    """Fetch Epic Games Store storefront layout, which contains many launcher/keyart images and promos."""
    try:
        resp = requests.get(EGS_STOREFRONT_URL, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[API] Failed to fetch EGS storefront: {e}")
        return {}

def build_embed(url: str) -> Dict[str, Any]:
    is_video = any(url.lower().endswith(ext) for ext in VIDEO_EXTS)
    is_image = any(url.lower().endswith(ext) for ext in IMAGE_EXTS)

    embed: Dict[str, Any] = {
        "title": "New Image/Video URL Detected",
        "description": f"[View / Download]({url})",
        "url": url,
        "color": 0x00b0f4,  # Nice blue
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
    print(f"=== Fortnite Image/Video URL Notifier ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")

    notified = load_notified()
    news_data = fetch_news()
    store_data = fetch_egs_storefront()

    if not news_data and not store_data:
        print("[ERROR] No data received from any source")
        return

    all_data = {"news": news_data, "store": store_data}
    current_urls = extract_media_urls(all_data)

    # ===================== TEST MODE =====================
    if TEST_LAST_MEDIA:
        print("[TEST] Mode activé : envoi de la dernière image/vidéo détectée (pour vérification)")
        if not current_urls:
            print("[TEST] Aucune URL trouvée.")
            return

        latest_url = current_urls[-1]
        print(f"[TEST] Dernière URL : {latest_url}")

        embed = build_embed(latest_url)

        if DRY_RUN:
            print("\n" + "=" * 60)
            print("DRY RUN - Embed that would be sent:")
            print("=" * 60)
            print(json.dumps({"embeds": [embed]}, indent=2, ensure_ascii=False))
            print("=" * 60 + "\n")
        else:
            send_discord(embed)

        print("[TEST] Terminé (le state 'notified' n'a pas été modifié).")
        return
    # =====================================================

    new_urls = [u for u in current_urls if u not in notified]

    if not notified:
        # First run: seed without posting
        save_notified(set(current_urls))
        print(f"[SEED] First run - seeded {len(current_urls)} existing URLs. No notifications sent.")
        return

    # Keep state up to date
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
