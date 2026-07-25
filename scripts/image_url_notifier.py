#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fortnite Image URL Notifier

Tracks the storefront artwork Epic swaps in when a new Fortnite version ships,
and posts every newly seen image to a dedicated Discord webhook.

Sources:
  1. EGS Platform Service product endpoint -> EGS launcher blades + logo
  2. Fortnite content API / dynamicbackgrounds -> lobby & vault key art
  3. Microsoft Store product page -> store-images.s-microsoft.com artwork
  4. PlayStation Store product pages -> PDP cover art

Refs:
  https://github.com/LeleDerGrasshalmi/FortniteEndpointsDocumentation
"""

import os
import re
import json
import requests
from datetime import datetime, timezone
from typing import Set, Dict, Any, List, Tuple

# ==================== CONFIG ====================
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_IMAGE_URL_WEBHOOK_URL", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1" or not DISCORD_WEBHOOK_URL
TEST_LAST_MEDIA = os.environ.get("TEST_LAST_MEDIA", "0") == "1"

STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "notified_image_urls.json",
)

EMBED_COLOR = 0x6B21A8
FOOTER_TEXT = "MakaStats"
HTTP_TIMEOUT = 30

# Epic and the console stores both reject requests without a browser User-Agent.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

EGS_PRODUCT_URL = (
    "https://egs-platform-service.store.epicgames.com"
    "/api/v1/egs/products/prod-fn?country=US&locale=en&store=EGS"
)

DYNAMIC_BACKGROUNDS_URL = (
    "https://fortnitecontent-website-prod07.ol.epicgames.com"
    "/content/api/pages/fortnite-game/dynamicbackgrounds?lang=en"
)

MS_STORE_URL = "https://www.microsoft.com/en-us/p/fortnite/9nblggh537bp"

PS_STORE_URLS = (
    "https://store.playstation.com/en-us/product/UP2005-CUSA07677_00-FORTNITEPS5FULL0",
    "https://store.playstation.com/en-us/product/UP2005-CUSA07022_00-FORTNITEPS4FULL0",
)

# Human-readable labels for the EGS media slots.
EGS_MEDIA_LABELS = {
    "card16x9": "EGS Launcher Blade (16:9)",
    "card3x4": "EGS Launcher Blade (3:4)",
    "logo": "EGS Launcher Logo",
}

# Only these hosts may produce a notification.
ALLOWED_IMAGE_DOMAINS = (
    "cdn2.unrealengine.com",
    "cdn1.epicgames.com",
    "store-images.s-microsoft.com",
    "image.api.np.ac.playstation.net",
    "image.api.playstation.com",
)

MS_IMAGE_RE = re.compile(r"https://store-images\.s-microsoft\.com/image/apps\.[A-Za-z0-9._\-]+")
PS_IMAGE_RE = re.compile(
    r"https://(?:image\.api\.np\.ac\.playstation\.net|image\.api\.playstation\.com"
    r"|cdn2\.unrealengine\.com)/[A-Za-z0-9._\-/]+"
)

# A URL plus the label describing where it came from.
Media = Tuple[str, str]


def load_notified() -> Set[str]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data) if isinstance(data, list) else set()
        except Exception as e:
            print(f"[STATE] Could not read {STATE_FILE}: {e}")
    return set()


def save_notified(urls: Set[str]) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(urls), f, indent=2)


def is_allowed_image(url: str) -> bool:
    return any(domain in url.lower() for domain in ALLOWED_IMAGE_DOMAINS)


def strip_query(url: str) -> str:
    return url.split("?", 1)[0]


def fetch_egs_product_images() -> List[Media]:
    """EGS launcher blades and logo — these swap on every new Fortnite version."""
    try:
        resp = requests.get(EGS_PRODUCT_URL, headers=BROWSER_HEADERS, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        media = resp.json().get("media") or {}
    except Exception as e:
        print(f"[EGS] Failed to fetch product media: {e}")
        return []

    results: List[Media] = []
    for slot, label in EGS_MEDIA_LABELS.items():
        entry = media.get(slot)
        src = entry.get("imageSrc") if isinstance(entry, dict) else None
        if src:
            results.append((strip_query(src), label))

    print(f"[EGS] {len(results)} image(s)")
    return results


def fetch_dynamic_backgrounds() -> List[Media]:
    """Lobby / vault key art from the Fortnite content API."""
    try:
        resp = requests.get(
            DYNAMIC_BACKGROUNDS_URL, headers=BROWSER_HEADERS, timeout=HTTP_TIMEOUT
        )
        resp.raise_for_status()
        backgrounds = (resp.json().get("backgrounds") or {}).get("backgrounds") or []
    except Exception as e:
        print(f"[BACKGROUNDS] Failed to fetch dynamic backgrounds: {e}")
        return []

    results: List[Media] = []
    for background in backgrounds:
        if not isinstance(background, dict):
            continue
        image = background.get("backgroundimage")
        if not image:
            continue
        key = (background.get("key") or "dynamic").capitalize()
        results.append((strip_query(image), f"{key} Background"))

    print(f"[BACKGROUNDS] {len(results)} image(s)")
    return results


def fetch_ms_store_images() -> List[Media]:
    """Microsoft Store artwork, scraped from the product page HTML."""
    try:
        resp = requests.get(MS_STORE_URL, headers=BROWSER_HEADERS, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print(f"[MS-STORE] Failed to fetch product page: {e}")
        return []

    # Sizing hints (?h=253) vary per viewport, so key off the base URL only.
    urls = sorted({strip_query(u) for u in MS_IMAGE_RE.findall(html)})
    print(f"[MS-STORE] {len(urls)} image(s)")
    return [(u, "Microsoft Store") for u in urls]


def fetch_ps_store_images() -> List[Media]:
    """
    PlayStation Store PDP cover art.

    The store renders client-side and serves a content-free shell to non-browser
    clients, so this often finds nothing; that is expected, not an error.
    """
    found: Set[str] = set()
    for page_url in PS_STORE_URLS:
        try:
            resp = requests.get(page_url, headers=BROWSER_HEADERS, timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
        except Exception as e:
            print(f"[PS-STORE] Failed to fetch {page_url}: {e}")
            continue
        found.update(strip_query(u) for u in PS_IMAGE_RE.findall(resp.text))

    urls = sorted(u for u in found if len(u.rstrip("/").split("/")) > 3)
    print(f"[PS-STORE] {len(urls)} image(s)")
    return [(u, "PlayStation Store") for u in urls]


def collect_media() -> List[Media]:
    """Run every source and return deduplicated, allow-listed media."""
    collected: List[Media] = []
    for fetch in (
        fetch_egs_product_images,
        fetch_dynamic_backgrounds,
        fetch_ms_store_images,
        fetch_ps_store_images,
    ):
        collected.extend(fetch())

    seen: Set[str] = set()
    results: List[Media] = []
    for url, label in collected:
        if url in seen or not is_allowed_image(url):
            continue
        seen.add(url)
        results.append((url, label))
    return results


def build_embed(url: str, label: str) -> dict:
    now = datetime.now(timezone.utc)
    embed: Dict[str, Any] = {
        "title": label,
        "url": url,
        "description": f"[{url}]({url})",
        "color": EMBED_COLOR,
        "image": {"url": url},
        "footer": {"text": FOOTER_TEXT},
        "timestamp": now.isoformat(),
    }
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
            print(f"[OK] Sent embed: {title}")
        else:
            print(f"[ERROR] Discord returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[ERROR] Failed to send to Discord: {e}")


def main():
    global DRY_RUN
    print("=== Fortnite Image URL Notifier ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")

    notified = load_notified()
    current = collect_media()

    if not current:
        print("[ERROR] No images received from any source")
        return

    print(f"[INFO] {len(current)} image(s) currently published")

    if TEST_LAST_MEDIA:
        url, label = current[-1]
        print(f"[TEST] Sending last detected image: {url}")
        original_dry, DRY_RUN = DRY_RUN, False
        send_discord(build_embed(url, label))
        DRY_RUN = original_dry
        print("[TEST] Done (state untouched).")
        return

    current_urls = {url for url, _ in current}

    if not notified:
        save_notified(current_urls)
        print(f"[SEED] First run - seeded {len(current_urls)} URLs. No notifications sent.")
        return

    new_media = [(url, label) for url, label in current if url not in notified]
    if not new_media:
        print("No new image URLs detected.")
        save_notified(notified | current_urls)
        return

    print(f"[INFO] Detected {len(new_media)} new image URL(s)")
    for url, label in new_media:
        send_discord(build_embed(url, label))

    save_notified(notified | current_urls)
    print("Done.")


if __name__ == "__main__":
    main()
