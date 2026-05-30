#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fortnite INI Hotfix Notifier - Dilly Mirror (export-service-new.dillyapis.com)
Public, no-auth, fast updates for all .ini CloudStorage files.
"""

import os
import json
import difflib
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

import requests

# ==================== CONFIG ====================
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1" or not DISCORD_WEBHOOK_URL
NOTES = os.environ.get("NOTES", "").strip()

# Dilly public mirror (no auth required)
DILLY_LIST_URL = "https://export-service-new.dillyapis.com/v1/cloudstorage"
LAST_KNOWN_DIR = "last_cloudstorage"

# Timeout and limits
REQUEST_TIMEOUT = 30
MAX_DIFF_CHARS = 1800

# ==================== DILLY API ====================

def fetch_dilly_list() -> List[Dict[str, Any]]:
    """Fetch the complete list of available cloudstorage entries from Dilly mirror."""
    try:
        resp = requests.get(DILLY_LIST_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            print(f"[DILLY] Unexpected response type: {type(data)}")
            return []
        print(f"[DILLY] Received {len(data)} entries")
        return data
    except Exception as e:
        print(f"[DILLY] Failed to fetch list: {e}")
        return []


def pick_freshest_entries(entries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Group by fileName and keep only the most recent entry per logical file.
    This correctly handles the ~10 duplicate filenames that exist in the source.
    Skips entries without usable download URL.
    """
    freshest: Dict[str, Dict[str, Any]] = {}

    for entry in entries:
        file_name = entry.get("fileName")
        url = entry.get("url")
        size = entry.get("size", 0)

        if not file_name or not url or size == 0:
            continue

        current = freshest.get(file_name)
        if current is None:
            freshest[file_name] = entry
        else:
            # Keep the one with the latest updatedAt
            if entry.get("updatedAt", "") > current.get("updatedAt", ""):
                freshest[file_name] = entry

    return freshest


def download_ini(url: str) -> Optional[str]:
    """Download raw .ini content from the stormforge CDN."""
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            # Force text decoding (some .ini have mixed encodings)
            return resp.content.decode("utf-8", errors="replace")
        print(f"[DOWNLOAD] HTTP {resp.status_code} for {url[:80]}...")
        return None
    except Exception as e:
        print(f"[DOWNLOAD] Error: {e}")
        return None

# ==================== LOCAL STATE (last_cloudstorage/) ====================

def get_local_content(file_name: str) -> str:
    """Read previously seen content for this fileName (if any)."""
    os.makedirs(LAST_KNOWN_DIR, exist_ok=True)
    # Use the original filename (safe on all platforms for these .ini names)
    path = os.path.join(LAST_KNOWN_DIR, file_name)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception as e:
            print(f"[STATE] Failed to read {file_name}: {e}")
    return ""


def save_local_content(file_name: str, content: str) -> None:
    """Persist the new content we just notified about."""
    path = os.path.join(LAST_KNOWN_DIR, file_name)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"[STATE] Failed to write {file_name}: {e}")

# ==================== DIFF ====================

def generate_diff(old: str, new: str, file_name: str) -> str:
    diff_lines = list(difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{file_name}",
        tofile=f"b/{file_name}",
        n=3
    ))
    result = "".join(diff_lines)
    if not result.strip():
        return "(Aucun changement textuel détecté)"
    if len(result) > MAX_DIFF_CHARS:
        result = result[:MAX_DIFF_CHARS] + "\n... (diff tronqué)"
    return result

# ==================== DISCORD MESSAGE (exact user format) ====================

def build_discord_content(file_name: str, diff_text: str, notes: str = "") -> str:
    """
    Exact format requested by user:
    **<filename> a été mis à jour !**
    ```diff
    ...
    ```
    **__Explications__**
    (empty or pre-filled via workflow input)
    """
    title = f"**{file_name} a été mis à jour !**"
    content = f"{title}\n```diff\n{diff_text}\n```"

    if notes:
        content += f"\n**__Explications__**\n{notes}"
    else:
        content += "\n**__Explications__**"

    # Discord hard limit ~2000 chars for webhook content
    if len(content) > 1990:
        content = content[:1980] + "\n...(tronqué)```"
    return content


def send_discord(file_name: str, diff_text: str, notes: str = "") -> None:
    content = build_discord_content(file_name, diff_text, notes)

    if DRY_RUN:
        print("\n" + "=" * 60)
        print("DRY RUN - Message that would be sent:")
        print("=" * 60)
        print(content)
        print("=" * 60 + "\n")
        return

    if not DISCORD_WEBHOOK_URL:
        print("[ERROR] DISCORD_WEBHOOK_URL is not set")
        return

    try:
        r = requests.post(
            DISCORD_WEBHOOK_URL,
            json={"content": content},
            timeout=15
        )
        if r.status_code in (200, 204):
            print(f"[DISCORD] Sent notification for {file_name}")
        else:
            print(f"[DISCORD] Webhook error {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"[DISCORD] Exception: {e}")

# ==================== MAIN ====================

def main():
    print(f"=== Fortnite INI Hotfix Notifier (Dilly) ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print(f"DRY_RUN={DRY_RUN}")

    entries = fetch_dilly_list()
    if not entries:
        print("[ERROR] No entries received from Dilly. Aborting.")
        return

    candidates = pick_freshest_entries(entries)
    print(f"[INFO] {len(candidates)} unique files with usable content after filtering duplicates + stubs")

    changes_detected = 0

    for file_name, entry in sorted(candidates.items()):
        url = entry["url"]
        updated_at = entry.get("updatedAt", "")
        file_hash = entry.get("hash", "")[:16]

        old_content = get_local_content(file_name)
        is_first_time = old_content == ""

        # Download new content
        new_content = download_ini(url)
        if new_content is None:
            continue

        # First run for this file → seed state silently (do not spam Discord with 100+ messages)
        if is_first_time:
            save_local_content(file_name, new_content)
            print(f"[SEED] {file_name} (first time, state initialized, no notification)")
            continue

        # Real change?
        if new_content != old_content:
            print(f"[CHANGE] {file_name} (hash={file_hash}, updatedAt={updated_at})")
            diff_text = generate_diff(old_content, new_content, file_name)

            send_discord(file_name, diff_text, NOTES)
            save_local_content(file_name, new_content)
            changes_detected += 1
        else:
            # Silent - no change
            pass

    if changes_detected == 0:
        print("Aucun nouveau hotfix détecté.")
    else:
        print(f"{changes_detected} fichier(s) mis à jour → notifications envoyées.")

    print("Terminé.")


if __name__ == "__main__":
    main()
