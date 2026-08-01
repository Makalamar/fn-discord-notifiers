#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fortnite Radio Station Notifier

Monitors Fortnite in-game radio stations and posts to Discord when:
  - A new station is added
  - A station is modified (name, description, image, stream URL)
  - A station is removed

Sources (in priority order):
  1. fortnite-api.com  -> /v1/radio-stations (primary, community-maintained)
  2. BenBot API        -> https://benbot.app/api/v2/radio (fallback)
  3. Epic content API  -> radio-stations endpoint (legacy, likely 404)

Refs:
  https://dash.fortnite-api.com/endpoints/radio-stations
  https://github.com/LeleDerGrasshalmi/FortniteEndpointsDocumentation
"""

import os
import json
import hashlib
import requests
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ==================== CONFIG ====================
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_RADIO_WEBHOOK_URL", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1" or not DISCORD_WEBHOOK_URL
TEST_MODE = os.environ.get("TEST_MODE", "0") == "1"

STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "radio_stations_cache.json",
)

HTTP_TIMEOUT = 30
EMBED_COLOR_NEW = 0x57F287      # green  – new station
EMBED_COLOR_MODIFIED = 0xFEE75C  # yellow – modified station
EMBED_COLOR_REMOVED = 0xED4245   # red    – removed station

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ==================== SOURCE URLS ====================
FORTNITE_API_URL = "https://fortnite-api.com/v1/radio"
BENBOT_API_URL   = "https://benbot.app/api/v2/radio"
EPIC_API_URL     = (
    "https://fortnitecontent-website-prod07.ol.epicgames.com"
    "/content/api/pages/fortnite-game/radio-stations"
)


# ==================== DATA TYPES ====================

class Station:
    """Normalised radio station."""
    __slots__ = ("id", "title", "description", "image", "stream_url", "raw")

    def __init__(
        self,
        station_id: str,
        title: str,
        description: str,
        image: str,
        stream_url: str,
        raw: Dict[str, Any],
    ):
        self.id          = station_id
        self.title       = title
        self.description = description
        self.image       = image
        self.stream_url  = stream_url
        self.raw         = raw

    def fingerprint(self) -> str:
        """SHA-1 of the fields that matter for change detection."""
        blob = json.dumps(
            {
                "title": self.title,
                "description": self.description,
                "image": self.image,
                "stream_url": self.stream_url,
            },
            sort_keys=True,
        )
        return hashlib.sha1(blob.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "image": self.image,
            "stream_url": self.stream_url,
            "fingerprint": self.fingerprint(),
            "last_seen": datetime.now(timezone.utc).isoformat(),
        }


# ==================== FETCHERS ====================

def _fetch_fortnite_api() -> Optional[List[Station]]:
    """Primary source: fortnite-api.com community API."""
    try:
        resp = requests.get(FORTNITE_API_URL, headers=BROWSER_HEADERS, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[API] fortnite-api.com failed: {e}")
        return None

    stations: List[Station] = []
    items = data.get("data") or []
    for item in items:
        try:
            sid   = item.get("id") or item.get("devName") or str(item)
            title = (
                item.get("title")
                or (item.get("text") or {}).get("title")
                or sid
            )
            desc  = (
                item.get("description")
                or (item.get("text") or {}).get("description")
                or ""
            )
            # image: prefer "image" > first key ending in "image" > empty
            image = item.get("image") or ""
            if not image:
                for k, v in item.items():
                    if "image" in k.lower() and isinstance(v, str) and v.startswith("http"):
                        image = v
                        break
            # stream: prefer "streamUrl" > "audioUrl" > "url"
            stream = (
                item.get("streamUrl")
                or item.get("audioUrl")
                or item.get("url")
                or ""
            )
            stations.append(Station(str(sid), str(title), str(desc), str(image), str(stream), item))
        except Exception as e:
            print(f"[API] Could not parse station entry: {e}")
            continue

    print(f"[API] fortnite-api.com -> {len(stations)} station(s)")
    return stations if stations else None


def _fetch_benbot() -> Optional[List[Station]]:
    """Fallback source: BenBot asset API."""
    try:
        resp = requests.get(BENBOT_API_URL, headers=BROWSER_HEADERS, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[API] BenBot failed: {e}")
        return None

    stations: List[Station] = []
    items = data if isinstance(data, list) else (data.get("radioStations") or [])
    for item in items:
        try:
            sid    = item.get("id") or item.get("name") or str(item)
            title  = item.get("title") or item.get("name") or str(sid)
            desc   = item.get("description") or ""
            image  = item.get("image") or item.get("largeIcon") or item.get("icon") or ""
            stream = item.get("streamUrl") or item.get("audioUrl") or item.get("url") or ""
            stations.append(Station(str(sid), str(title), str(desc), str(image), str(stream), item))
        except Exception as e:
            print(f"[API] BenBot parse error: {e}")
            continue

    print(f"[API] BenBot -> {len(stations)} station(s)")
    return stations if stations else None


def _fetch_epic_legacy() -> Optional[List[Station]]:
    """Legacy Epic CMS endpoint (likely 404 but worth trying)."""
    try:
        resp = requests.get(EPIC_API_URL, headers=BROWSER_HEADERS, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[API] Epic legacy endpoint failed: {e}")
        return None

    stations: List[Station] = []
    # Epic CMS wraps data in a top-level key matching the page slug
    for key, section in data.items():
        if not isinstance(section, dict):
            continue
        items = section.get("radioStations") or section.get("stations") or []
        for item in items:
            try:
                sid    = item.get("stationName") or item.get("id") or str(item)
                title  = item.get("title") or sid
                desc   = item.get("description") or ""
                image  = item.get("image") or ""
                stream = item.get("streamUrl") or item.get("audioUrl") or ""
                stations.append(Station(str(sid), str(title), str(desc), str(image), str(stream), item))
            except Exception:
                continue

    print(f"[API] Epic legacy -> {len(stations)} station(s)")
    return stations if stations else None


def fetch_stations() -> List[Station]:
    """Try each source in order, return first non-empty result."""
    for fetcher in (_fetch_fortnite_api, _fetch_benbot, _fetch_epic_legacy):
        result = fetcher()
        if result:
            return result
    print("[ERROR] All sources exhausted — no stations fetched.")
    return []


# ==================== STATE ====================

def load_cache() -> Dict[str, Dict[str, Any]]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[STATE] Could not read cache: {e}")
    return {}


def save_cache(cache: Dict[str, Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


# ==================== DISCORD ====================

def _audio_link(stream_url: str) -> str:
    """Return a markdown-formatted audio link when a URL is available."""
    if not stream_url or stream_url in ("", "None"):
        return "_Audio non disponible_"
    return f"[▶ Écouter le flux]({stream_url})"


def build_new_embed(station: Station) -> dict:
    fields = [
        {"name": "🎵 Flux audio", "value": _audio_link(station.stream_url), "inline": False},
    ]
    if station.description and station.description not in ("", "None"):
        fields.insert(0, {"name": "📻 Description", "value": station.description[:1024], "inline": False})

    embed: Dict[str, Any] = {
        "title": f"📻 Nouvelle station radio : {station.title}",
        "color": EMBED_COLOR_NEW,
        "fields": fields,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": f"ID: {station.id}"},
    }
    if station.image and station.image not in ("", "None"):
        embed["thumbnail"] = {"url": station.image}
        embed["image"]     = {"url": station.image}

    return {"embeds": [embed]}


def build_modified_embed(station: Station, old: Dict[str, Any]) -> dict:
    changes: List[str] = []
    if old.get("title") != station.title:
        changes.append(f"**Nom** : `{old.get('title')}` → `{station.title}`")
    if old.get("description") != station.description:
        changes.append(
            f"**Description** : `{(old.get('description') or '')[:80]}` → `{station.description[:80]}`"
        )
    if old.get("image") != station.image:
        changes.append("**Image** : mise à jour")
    if old.get("stream_url") != station.stream_url:
        changes.append(f"**Flux** : mis à jour")

    fields = [
        {
            "name": "🔄 Modifications",
            "value": "\n".join(changes) or "Changement détecté",
            "inline": False,
        },
        {"name": "🎵 Flux audio", "value": _audio_link(station.stream_url), "inline": False},
    ]

    embed: Dict[str, Any] = {
        "title": f"✏️ Station modifiée : {station.title}",
        "color": EMBED_COLOR_MODIFIED,
        "fields": fields,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": f"ID: {station.id}"},
    }
    if station.image and station.image not in ("", "None"):
        embed["thumbnail"] = {"url": station.image}

    return {"embeds": [embed]}


def build_removed_embed(station_id: str, old: Dict[str, Any]) -> dict:
    embed: Dict[str, Any] = {
        "title": f"🗑️ Station supprimée : {old.get('title', station_id)}",
        "description": f"La station **{old.get('title', station_id)}** n'est plus disponible.",
        "color": EMBED_COLOR_REMOVED,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": f"ID: {station_id}"},
    }
    if old.get("image") and old["image"] not in ("", "None"):
        embed["thumbnail"] = {"url": old["image"]}
    return {"embeds": [embed]}


def send_discord(payload: dict, label: str = "") -> None:
    if DRY_RUN:
        print("\n" + "=" * 60)
        print(f"DRY RUN [{label}] — payload:")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        print("=" * 60 + "\n")
        return

    if not DISCORD_WEBHOOK_URL:
        print("[ERROR] DISCORD_RADIO_WEBHOOK_URL not set")
        return

    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        if resp.status_code in (200, 204):
            print(f"[OK] Sent: {label}")
        else:
            print(f"[ERROR] Discord {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[ERROR] {e}")


# ==================== MAIN ====================

def main():
    print("=== Fortnite Radio Station Notifier ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")

    stations = fetch_stations()

    if not stations:
        print("[ERROR] No stations fetched from any source — aborting.")
        return

    print(f"[INFO] {len(stations)} station(s) fetched")

    # TEST_MODE: dump the first station as an embed without touching state
    if TEST_MODE:
        s = stations[0]
        print(f"[TEST] Sending embed for station: {s.title} (id={s.id})")
        global DRY_RUN
        original_dry = DRY_RUN
        DRY_RUN = False
        send_discord(build_new_embed(s), label=f"TEST:{s.title}")
        DRY_RUN = original_dry
        print("[TEST] Done (state untouched).")
        return

    cache = load_cache()
    current_ids = {s.id for s in stations}

    # Seed on first run
    if not cache:
        new_cache = {s.id: s.to_dict() for s in stations}
        save_cache(new_cache)
        print(f"[SEED] First run — seeded {len(new_cache)} station(s). No notifications sent.")
        return

    notifications_sent = 0

    # Detect new & modified stations
    for station in stations:
        if station.id not in cache:
            print(f"[NEW] {station.title} ({station.id})")
            send_discord(build_new_embed(station), label=f"NEW:{station.title}")
            notifications_sent += 1
        else:
            cached = cache[station.id]
            if cached.get("fingerprint") != station.fingerprint():
                print(f"[MODIFIED] {station.title} ({station.id})")
                send_discord(
                    build_modified_embed(station, cached),
                    label=f"MODIFIED:{station.title}",
                )
                notifications_sent += 1

    # Detect removed stations
    for sid, old in cache.items():
        if sid not in current_ids:
            print(f"[REMOVED] {old.get('title', sid)} ({sid})")
            send_discord(build_removed_embed(sid, old), label=f"REMOVED:{old.get('title', sid)}")
            notifications_sent += 1

    if notifications_sent == 0:
        print("[INFO] No changes detected.")

    # Update cache with current state (keep removed stations for 1 cycle)
    new_cache = {s.id: s.to_dict() for s in stations}
    save_cache(new_cache)
    print(f"[INFO] Cache updated — {len(new_cache)} station(s).")


if __name__ == "__main__":
    main()
