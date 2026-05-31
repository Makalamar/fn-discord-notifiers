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

# Manual override (via workflow input or env). If empty, we auto-detect below.
FORTNITE_VERSION_OVERRIDE = os.environ.get("FORTNITE_VERSION", "").strip()

# Dilly public mirror (no auth required)
DILLY_LIST_URL = "https://export-service-new.dillyapis.com/v1/cloudstorage"
AES_API_URL = "https://fortnite-api.com/v2/aes"   # Public, no key, gives current build
LAST_KNOWN_DIR = "last_cloudstorage"

# Timeout and limits
REQUEST_TIMEOUT = 30
# Discord webhook content max is ~2000 chars. We try to send full diffs.
# If a diff is extremely large, we will truncate only at the final message stage.
DISCORD_MAX_CHARS = 1950

# ==================== VERSION DETECTION ====================

def get_current_fortnite_version() -> str:
    """
    Automatically fetches the current Fortnite version from a public API.
    Returns something like "4041" from "++Fortnite+Release-40.41-CL-..."
    Falls back to "4041" if the API fails.
    """
    try:
        resp = requests.get(AES_API_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        build = data.get("build", "")   # Example: "++Fortnite+Release-40.41-CL-54326946"

        if "Release-" in build:
            # Extract "40.41"
            version_part = build.split("Release-")[1].split("-")[0]
            # Turn "40.41" into "4041" (the format you want)
            short_version = version_part.replace(".", "")
            if short_version:
                print(f"[VERSION] Auto-detected from AES API: {short_version} (full: {build})")
                return short_version

        print(f"[VERSION] Could not parse build string: {build}")
    except Exception as e:
        print(f"[VERSION] Failed to fetch from {AES_API_URL}: {e}")

    # Fallback
    fallback = "4041"
    print(f"[VERSION] Using fallback version: {fallback}")
    return fallback


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
    """Returns the FULL unified diff (no early truncation)."""
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
    return result  # full diff - truncation happens later only if the whole Discord message is too long


# ==================== DISCORD MESSAGE (exact user format) ====================

def build_versioned_title(file_name: str, version: str) -> str:
    """Builds the exact title format requested: Ver-YYYYMMDD-XXXX_filename"""
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    v = version or "4041"
    return f"**Ver-{date_str}-{v}_{file_name} a été mis à jour !**"


def build_discord_content(file_name: str, diff_text: str, version: str, notes: str = "") -> str:
    """
    Produces the exact layout the user wants:

    **Ver-20260531-4041_DefaultForbiddenFruitGame.ini a été mis à jour !**
    ```diff
    --- a/...
    +++ b/...
    @@ ...
    ```
    **__Explications__**
    """
    title = build_versioned_title(file_name, version)

    # Build with proper code block
    content = f"{title}\n```diff\n{diff_text}\n```"

    if notes and notes.strip():
        content += f"\n**__Explications__**\n{notes}"
    else:
        content += "\n**__Explications__**"

    # Final safety: if still too long for Discord, truncate the diff part gracefully
    if len(content) > DISCORD_MAX_CHARS:
        # Keep the title + opening of the code block + as much diff as possible
        header = f"{title}\n```diff\n"
        footer = "\n```\n**__Explications__** (diff trop long pour Discord - voir last_cloudstorage/ après mise à jour)"
        max_diff_len = DISCORD_MAX_CHARS - len(header) - len(footer)
        truncated_diff = diff_text[:max_diff_len].rsplit('\n', 1)[0]  # cut at line boundary
        content = header + truncated_diff + footer

    return content



def send_discord(file_name: str, diff_text: str, version: str, notes: str = "") -> None:
    content = build_discord_content(file_name, diff_text, version, notes)

    if DRY_RUN:
        print("\n" + "=" * 60)
        print("DRY RUN - Message that would be sent to Discord:")
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
            print(f"[DISCORD] ✅ Notification sent for {file_name}")
        else:
            print(f"[DISCORD] ❌ Webhook error {r.status_code}: {r.text[:300]}")
            # If Discord rejected because too long, give hint
            if r.status_code == 400 and "content" in r.text.lower():
                print("[DISCORD] Hint: Le diff est probablement trop long pour Discord (limite ~2000 caractères).")
    except Exception as e:
        print(f"[DISCORD] Exception: {e}")

# ==================== MAIN ====================

def main():
    print(f"=== Fortnite INI Hotfix Notifier (Dilly) ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print(f"DRY_RUN={DRY_RUN}")

    # Determine the version number for titles (Ver-YYYYMMDD-XXXX)
    if FORTNITE_VERSION_OVERRIDE:
        fortnite_version = FORTNITE_VERSION_OVERRIDE
        print(f"[VERSION] Using manual override: {fortnite_version}")
    else:
        fortnite_version = get_current_fortnite_version()

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

            send_discord(file_name, diff_text, fortnite_version, NOTES)
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
