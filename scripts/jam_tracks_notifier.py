#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fortnite Jam Tracks Notifier
Detects new Jam Tracks from the public API and posts them to Discord.
"""

import os
import json
import requests
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Set

# ==================== CONFIG ====================
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1" or not DISCORD_WEBHOOK_URL

STATE_FILE = "data/notified_jam_tracks.json"
API_URL = "https://fortnite-api.com/v2/cosmetics/tracks"

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

def save_notified(track_ids: Set[str]) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(track_ids)), f, indent=2)

# ==================== API ====================

def fetch_tracks() -> List[Dict[str, Any]]:
    try:
        resp = requests.get(API_URL, timeout=30)
        resp.raise_for_status()
        return resp.json().get("data", [])
    except Exception as e:
        print(f"[API] Failed to fetch tracks: {e}")
        return []

# ==================== HELPERS ====================

def format_duration(seconds: int) -> str:
    if not seconds:
        return "0:00"
    m = seconds // 60
    s = seconds % 60
    return f"{m}:{s:02d}"

def make_difficulty_bar(value: int, max_value: int = 5, length: int = 8) -> str:
    """Create a visual bar of 8 segments."""
    if value is None or value <= 0:
        filled = 0
    else:
        filled = min(length, max(0, int(round((value / max_value) * length))))
    return "▰" * filled + "▱" * (length - filled)

def format_new_until(added_str: str) -> str:
    if not added_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(added_str.replace("Z", "+00:00"))
        until = dt + timedelta(days=7)
        # Cross-platform formatting
        formatted = until.strftime("%B %d, %Y %I:%M %p")
        # Clean leading zero in hour
        formatted = formatted.replace(" 0", " ")
        return formatted
    except Exception:
        return "N/A"

def build_message(track: Dict[str, Any]) -> str:
    title = track.get("title", "Unknown Track")
    artist = track.get("artist", "Unknown Artist")
    year = track.get("releaseYear")
    name_line = f"{title} ({year}) - {artist}" if year else f"{title} - {artist}"

    tid = track.get("id", "N/A")
    duration = format_duration(track.get("duration", 0))
    bpm = track.get("bpm", 0)

    # Rating (not in public API - using placeholder to match requested format)
    rating = "E"

    # New Until (approximate: added + 7 days)
    new_until = format_new_until(track.get("added"))

    # Difficulty (6 values from API → bars of 8 segments)
    diff = track.get("difficulty", {})
    instruments = [
        ("Vocals", diff.get("vocals", 0)),
        ("Guitar", diff.get("guitar", 0)),
        ("Bass", diff.get("bass", 0)),
        ("Drums", diff.get("drums", 0)),
        ("Plastic Bass", diff.get("plasticBass", 0)),
        ("Plastic Drums", diff.get("plasticDrums", 0)),
    ]

    diff_lines = [f"{name}: {make_difficulty_bar(val)}" for name, val in instruments]

    # Key/Scale is not provided by the current public API.
    # We show BPM and a placeholder so the layout matches the requested format.
    key_scale_tempo = f"N/A ({bpm} BPM)"

    message = f"""**New Track Detected**

**{name_line}**

Rating          Track ID                  Duration
{rating}               {tid}       {duration}

Key / Scale / Tempo          New Until
{key_scale_tempo}           {new_until}

**Difficulty Chart**
""" + "\n".join(diff_lines)

    return message

# ==================== DISCORD ====================

def send_discord(content: str) -> None:
    if DRY_RUN:
        print("\n" + "=" * 60)
        print("DRY RUN - Message that would be sent:")
        print("=" * 60)
        print(content)
        print("=" * 60 + "\n")
        return

    if not DISCORD_WEBHOOK_URL:
        print("[ERROR] DISCORD_WEBHOOK_URL not set")
        return

    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=15)
        if r.status_code in (200, 204):
            print("[DISCORD] New track notification sent successfully")
        else:
            print(f"[DISCORD] Webhook error {r.status_code}: {r.text[:250]}")
    except Exception as e:
        print(f"[DISCORD] Exception: {e}")

# ==================== MAIN ====================

def main():
    print(f"=== Fortnite Jam Tracks Notifier ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")

    notified = load_notified()
    tracks = fetch_tracks()

    if not tracks:
        print("[ERROR] No tracks received from API")
        return

    current_ids: Set[str] = set()
    new_tracks: List[Dict[str, Any]] = []

    for track in tracks:
        tid = track.get("id")
        if not tid:
            continue
        current_ids.add(tid)
        if tid not in notified:
            new_tracks.append(track)

    if not notified:
        # First run ever: seed the state without spamming Discord with hundreds of old tracks
        save_notified(current_ids)
        print(f"[SEED] First run - seeded {len(current_ids)} existing tracks. No notifications sent.")
        return

    # Always keep the state up to date with current catalog
    save_notified(current_ids)

    if not new_tracks:
        print("No new Jam Tracks detected.")
        return

    print(f"[INFO] Detected {len(new_tracks)} new Jam Track(s)")

    for track in new_tracks:
        msg = build_message(track)
        send_discord(msg)
        # Add immediately so if one send fails we don't retry spam on next run
        notified.add(track["id"])

    # Final save with the newly notified ones
    save_notified(notified)
    print("Done.")

if __name__ == "__main__":
    main()
