#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fortnite INI Hotfix Notifier - Direct CloudStorage Mode
"""

import os
import json
import time
import difflib
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import requests

# ==================== CONFIG ====================
EPIC_REFRESH_TOKEN = os.environ.get("EPIC_REFRESH_TOKEN", "").strip()
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1" or not DISCORD_WEBHOOK_URL

# Fichiers qu'on surveille (ajoute/enlève ce dont tu as besoin)
MONITORED_FILES = [
    "DefaultEngine.ini",
    "DefaultGame.ini",
    "DefaultJunoExclusiveGame.ini",
    "DefaultRuntimeOptions.ini",
    "Switch_Engine.ini",
]

CLOUDSTORAGE_BASE = "https://fngw-mcp-gc-livefn.ol.epicgames.com/fortnite/api/cloudstorage/system"
LAST_KNOWN_DIR = "last_cloudstorage"

# ==================== TOKEN ====================

def get_access_token(refresh_token: str) -> Optional[str]:
    if not refresh_token:
        print("[ERROR] EPIC_REFRESH_TOKEN manquant")
        return None

    try:
        r = requests.post(
            "https://account-public-service-prod.ol.epicgames.com/account/api/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            auth=("34a02cf8f4414e29b15921876da36f9a", "daafbccc737745039dffe53d94fc76cf"),
            timeout=30
        )
        r.raise_for_status()
        return r.json()["access_token"]
    except Exception as e:
        print(f"[ERROR] Impossible de rafraîchir le token: {e}")
        return None

# ==================== CLOUDSTORAGE ====================

def fetch_cloudstorage_file(filename: str, access_token: str) -> Optional[str]:
    url = f"{CLOUDSTORAGE_BASE}/{filename}"
    headers = {
        "Authorization": f"bearer {access_token}",
        "User-Agent": "Fortnite/++Fortnite+Release-34.00-CL-00000000 Windows/10.0.19045.1",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            return resp.text
        elif resp.status_code == 404:
            return None
        else:
            print(f"[CLOUDSTORAGE] Erreur {filename}: {resp.status_code}")
            return None
    except Exception as e:
        print(f"[CLOUDSTORAGE] Exception {filename}: {e}")
        return None

def get_changes(access_token: str) -> List[Dict[str, str]]:
    os.makedirs(LAST_KNOWN_DIR, exist_ok=True)
    changes = []

    for filename in MONITORED_FILES:
        current = fetch_cloudstorage_file(filename, access_token)
        if current is None:
            continue

        last_path = os.path.join(LAST_KNOWN_DIR, filename)
        old = ""
        if os.path.exists(last_path):
            with open(last_path, "r", encoding="utf-8", errors="ignore") as f:
                old = f.read()

        if current != old:
            print(f"[CLOUDSTORAGE] Changement détecté: {filename}")
            changes.append({
                "filename": filename,
                "old": old,
                "new": current
            })
            with open(last_path, "w", encoding="utf-8") as f:
                f.write(current)

    return changes

def generate_diff(old: str, new: str, filename: str) -> str:
    diff = list(difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        n=3
    ))
    result = "".join(diff)
    return result[:1800] if result else "(Aucun diff textuel)"

# ==================== DISCORD ====================

def send_discord(title: str, diff: str, notes: str = ""):
    content = f"{title}\n```diff\n{diff}\n```"
    if notes:
        content += f"\n**__Explications__**\n{notes}"
    else:
        content += "\n**__Explications__**"

    if len(content) > 1990:
        content = content[:1980] + "\n...```"

    if DRY_RUN:
        print("=== DRY RUN ===")
        print(content)
        return

    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=15)
        if r.status_code not in (200, 204):
            print(f"[ERROR] Discord webhook: {r.status_code}")
    except Exception as e:
        print(f"[ERROR] Discord: {e}")

# ==================== MAIN ====================

def main():
    print(f"=== Fortnite INI Hotfix Notifier (CloudStorage) ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")

    if not EPIC_REFRESH_TOKEN:
        print("[ERROR] EPIC_REFRESH_TOKEN manquant dans les secrets")
        return

    access_token = get_access_token(EPIC_REFRESH_TOKEN)
    if not access_token:
        print("[ERROR] Impossible d'obtenir un access token")
        return

    print("[INFO] Access token récupéré")

    changes = get_changes(access_token)

    if not changes:
        print("Aucun changement détecté dans les fichiers surveillés.")
        return

    print(f"{len(changes)} fichier(s) modifié(s)")

    for change in changes:
        diff = generate_diff(change["old"], change["new"], change["filename"])
        title = f"**{change['filename']}** was updated!"
        send_discord(title, diff)

    print("Terminé.")

if __name__ == "__main__":
    main()
