#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fortnite AES Keys Notifier
Polls https://fortnite-api.com/v2/aes for new dynamic AES keys and posts
a rich Discord embed for each new key detected.

Embed layout (mirrors the FortniteAPI reference style):
  title       : "New Dynamic AES Key Detected"
  description : version string
  fields      : pakchunk filename + key, File Id, File Count, File Size
  image       : featured image of the first decrypted cosmetic in the chunk
  footer      : "MakaStats • <timestamp>"
  color       : Fortnite purple 0x6B21A8

Required env vars:
  DISCORD_AES_WEBHOOK_URL   — Discord webhook URL for the AES channel
  FORTNITE_API_KEY          — API key for fortnite-api.com (optional but recommended)
"""

import os
import json
import math
import requests
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

# ==================== CONFIG ====================
DISCORD_WEBHOOK_URL: str = os.environ.get("DISCORD_AES_WEBHOOK_URL", "").strip()
FORTNITE_API_KEY: str    = os.environ.get("FORTNITE_API_KEY", "").strip()
DRY_RUN: bool            = os.environ.get("DRY_RUN", "0") == "1" or not DISCORD_WEBHOOK_URL
TEST_MODE: bool          = os.environ.get("TEST_AES", "0") == "1"

STATE_FILE = "data/notified_aes_keys.json"

AES_URL         = "https://fortnite-api.com/v2/aes"
COSMETICS_URL   = "https://fortnite-api.com/v2/cosmetics/br"
EMBED_COLOR     = 0x6B21A8   # Fortnite purple
FOOTER_TEXT     = "MakaStats"

# ==================== HELPERS ====================

def _api_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if FORTNITE_API_KEY:
        headers["Authorization"] = FORTNITE_API_KEY
    return headers


def _fmt_bytes(size_bytes: int) -> str:
    """Human-readable file size (KB / MB / GB)."""
    if size_bytes <= 0:
        return "0 B"
    units = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    return f"{size_bytes / p:.2f} {units[i]}"


def _short_key(key: str) -> str:
    """Truncate very long AES keys for embed readability (Discord 1024-char field limit)."""
    if not key:
        return "N/A"
    return key if len(key) <= 80 else key[:77] + "..."


# ==================== STATE ====================

def load_notified() -> Set[str]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data) if isinstance(data, list) else set()
        except Exception:
            pass
    return set()


def save_notified(ids: Set[str]) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(ids)), f, indent=2)


# ==================== API ====================

def fetch_aes() -> Optional[Dict[str, Any]]:
    """Fetch /v2/aes from fortnite-api.com.  Returns the full response data dict."""
    try:
        resp = requests.get(AES_URL, headers=_api_headers(), timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("status") == 200 and "data" in payload:
            return payload["data"]
        print(f"[API] Unexpected AES response: {payload}")
    except Exception as e:
        print(f"[API] Failed to fetch AES: {e}")
    return None


def fetch_cosmetic_for_pak(pak_filename: str) -> Optional[Dict[str, Any]]:
    """
    Try to find a cosmetic whose path references this pakchunk number.
    Falls back to fetching all cosmetics and filtering by path/added date.
    Returns the first matching cosmetic dict, or None.
    """
    # Extract chunk number from filename, e.g. "pakchunk1005-WindowsClient.utoc" -> "1005"
    chunk_id = None
    lower = pak_filename.lower()
    if lower.startswith("pakchunk"):
        rest = lower[len("pakchunk"):]
        chunk_id = rest.split("-")[0] if "-" in rest else rest.split(".")[0]

    try:
        resp = requests.get(COSMETICS_URL, headers=_api_headers(), timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        cosmetics: List[Dict] = payload.get("data", [])
    except Exception as e:
        print(f"[API] Failed to fetch cosmetics: {e}")
        return None

    if not cosmetics:
        return None

    # Priority 1: match by path containing the chunk id
    if chunk_id:
        for c in cosmetics:
            path = (c.get("path") or "").lower()
            if f"pakchunk{chunk_id}" in path or f"chunk{chunk_id}" in path:
                return c

    # Priority 2: most recently added cosmetic (last in list)
    # fortnite-api returns cosmetics in ascending added order
    return cosmetics[-1]


# ==================== EMBED ====================

def build_embed(key_entry: Dict[str, Any], version: str) -> Dict[str, Any]:
    """
    Build a Discord embed that mirrors the FortniteAPI reference screenshot.

    key_entry fields (from fortnite-api.com /v2/aes dynamicKeys[]):
      pakFilename   str   e.g. "pakchunk1005-WindowsClient.utoc"
      pakGuid       str   e.g. "376EED9E..."
      key           str   e.g. "0x23F6F8..."
      fileCount     int
      fileSize      int   (bytes)
      files         list[{name, uri}]  optional
    """
    pak_name:   str = key_entry.get("pakFilename", "Unknown")
    pak_guid:   str = key_entry.get("pakGuid", "N/A")
    aes_key:    str = key_entry.get("key", "N/A")
    file_count: int = key_entry.get("fileCount", 0)
    file_size:  int = key_entry.get("fileSize",  0)

    now_iso     = datetime.now(timezone.utc).isoformat()
    now_display = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    # ---- Resolve decrypted cosmetic image + name ----
    image_url:      Optional[str] = None
    cosmetic_name:  Optional[str] = None
    cosmetic_type:  Optional[str] = None

    cosmetic = fetch_cosmetic_for_pak(pak_name)
    if cosmetic:
        cosmetic_name = cosmetic.get("name")
        cosmetic_type = (cosmetic.get("type") or {}).get("displayValue")
        images: Dict = cosmetic.get("images") or {}
        # Prefer featured > icon > smallIcon
        image_url = (
            images.get("featured")
            or images.get("icon")
            or images.get("smallIcon")
        )
        if cosmetic_name:
            print(f"[INFO] Cosmetic matched: {cosmetic_name} ({cosmetic_type})")
    else:
        print("[INFO] No cosmetic matched for this pak.")

    # ---- Build description ----
    description = f"We've found a new dynamic AES key for version **{version}**."
    if cosmetic_name:
        type_label = f"{cosmetic_type} • " if cosmetic_type else ""
        description += f"\n\n**{type_label}{cosmetic_name}**"

    embed: Dict[str, Any] = {
        "title":       "New Dynamic AES Key Detected",
        "description": description,
        "color":       EMBED_COLOR,
        "timestamp":   now_iso,
        "footer":      {"text": f"{FOOTER_TEXT} • {now_display}"},
        "fields": [
            {
                "name":   pak_name,
                "value":  f"`{_short_key(aes_key)}`",
                "inline": False,
            },
            {
                "name":   "File Id",
                "value":  f"`{pak_guid}`" if pak_guid != "N/A" else "N/A",
                "inline": False,
            },
            {
                "name":   "File Count",
                "value":  str(file_count),
                "inline": True,
            },
            {
                "name":   "File Size",
                "value":  _fmt_bytes(file_size),
                "inline": True,
            },
        ],
    }

    if image_url:
        embed["image"] = {"url": image_url}

    return {"embeds": [embed]}


# ==================== DISCORD ====================

def send_discord(payload: Dict[str, Any]) -> None:
    if DRY_RUN:
        print("\n" + "=" * 60)
        print("DRY RUN — payload that would be sent:")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        print("=" * 60 + "\n")
        return

    if not DISCORD_WEBHOOK_URL:
        print("[ERROR] DISCORD_AES_WEBHOOK_URL not configured")
        return

    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        if resp.status_code in (200, 204):
            title = payload.get("embeds", [{}])[0].get("title", "")
            print(f"[OK] Embed sent: {title}")
        else:
            print(f"[ERROR] Discord returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[ERROR] Failed to send to Discord: {e}")


# ==================== MAIN ====================

def main() -> None:
    print("=== Fortnite AES Keys Notifier ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")

    data = fetch_aes()
    if not data:
        print("[ERROR] No AES data received")
        return

    version:      str             = data.get("version", "unknown")
    dynamic_keys: List[Dict]      = data.get("dynamicKeys", []) or []
    main_key:     Optional[str]   = data.get("mainKey")

    print(f"[INFO] Version: {version} | Dynamic keys: {len(dynamic_keys)}")

    notified = load_notified()

    # ---- TEST MODE: send all current keys regardless of state ----
    if TEST_MODE:
        print("[TEST] Mode activé — envoi de toutes les clés actuelles")
        if not dynamic_keys:
            print("[TEST] Aucune clé dynamique trouvée.")
            return
        # Send only the last key so we don't spam
        key_entry = dynamic_keys[-1]
        payload = build_embed(key_entry, version)
        original_dry = globals().get("DRY_RUN", DRY_RUN)
        globals()["DRY_RUN"] = False  # force real send in TEST mode
        send_discord(payload)
        globals()["DRY_RUN"] = original_dry
        print("[TEST] Terminé (state non modifié).")
        return
    # ---------------------------------------------------------------

    new_keys = [
        k for k in dynamic_keys
        if k.get("pakGuid") and k["pakGuid"] not in notified
    ]

    if not notified:
        # First run — seed state, no notifications
        seed_ids = {k["pakGuid"] for k in dynamic_keys if k.get("pakGuid")}
        save_notified(seed_ids)
        print(f"[SEED] First run — seeded {len(seed_ids)} existing keys. No notifications sent.")
        return

    if not new_keys:
        print("[INFO] No new AES keys detected.")
        # Always persist current full set to avoid re-notifying removed+re-added chunks
        save_notified({k["pakGuid"] for k in dynamic_keys if k.get("pakGuid")})
        return

    print(f"[INFO] {len(new_keys)} new AES key(s) detected")

    for key_entry in new_keys:
        payload = build_embed(key_entry, version)
        send_discord(payload)
        notified.add(key_entry["pakGuid"])

    save_notified(notified)
    print("Done.")


if __name__ == "__main__":
    main()
