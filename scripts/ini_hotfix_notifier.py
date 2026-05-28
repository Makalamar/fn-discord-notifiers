#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fortnite INI Hotfix Notifier

Two modes supported:
1. GitHub watcher (iFireMonkey/FortniteTracker) - legacy/slower
2. Direct Epic CloudStorage polling - faster and more accurate for real hotfixes

The script now prioritizes direct CloudStorage when credentials are provided.
"""

import os
import sys
import json
import time
import difflib
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import requests

# ==================== CONFIG ====================
GITHUB_REPO = "iFireMonkey/FortniteTracker"
GITHUB_API = "https://api.github.com"
STATE_FILE = "data/last_ini_commit.json"

# Discord webhook (reuse the same secret)
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1" or not WEBHOOK_URL

# Safety limits
MAX_FILES_PER_COMMIT = 60          # If more than this, we post a summary + as many individual diffs as reasonable
MAX_DIFF_LENGTH = 1800             # Discord message limit safety
SLEEP_BETWEEN_MESSAGES = 1.2       # Seconds between Discord messages (rate limit)

force_val = os.environ.get("FORCE_LATEST", "0").lower()
FORCE_LATEST = force_val in ("1", "true", "yes")

# Manual explanations / notes that the user can provide when triggering manually
MANUAL_NOTES = (
    os.environ.get("NOTES", "")
    or os.environ.get("EXPLANATIONS", "")
    or os.environ.get("MANUAL_NOTES", "")
)

HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "fortnite-ini-hotfix-notifier/1.0",
}

if "GITHUB_TOKEN" in os.environ:
    HEADERS["Authorization"] = f"token {os.environ['GITHUB_TOKEN']}"

# ====================== CLOUDSTORAGE (Epic direct) ======================
CLOUDSTORAGE_BASE = "https://fngw-mcp-gc-livefn.ol.epicgames.com/fortnite/api/cloudstorage/system"
EPIC_BEARER_TOKEN = os.environ.get("EPIC_BEARER_TOKEN", "").strip()

CLOUDSTORAGE_HEADERS = {
    "User-Agent": "Fortnite/++Fortnite+Release-34.00-CL-00000000 Windows/10.0.19045.1",
}
if EPIC_BEARER_TOKEN:
    CLOUDSTORAGE_HEADERS["Authorization"] = f"bearer {EPIC_BEARER_TOKEN}"

# Files we want to monitor for hotfixes (add/remove as needed)
MONITORED_CLOUDSTORAGE_FILES = [
    "DefaultEngine.ini",
    "DefaultGame.ini",
    "DefaultRuntimeOptions.ini",
    "DefaultJunoExclusiveGame.ini",
    "Switch_Engine.ini",
    "Switch_Game.ini",
    # Add more if needed (e.g. Android_Engine.ini, etc.)
]


def load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {"last_commit_sha": None}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_commit_sha": None}


def save_state(state: Dict[str, Any]):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def get_recent_commits(since_sha: Optional[str] = None, limit: int = 20) -> List[Dict]:
    """Get recent commits from the repo, newest first."""
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/commits"
    params = {"per_page": limit}

    resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    commits = resp.json()

    # If we have a last seen SHA, stop when we reach it
    result = []
    for c in commits:
        if since_sha and c["sha"] == since_sha:
            break
        result.append(c)

    return result


def get_commit_details(sha: str) -> Dict:
    """Get full commit details including file patches."""
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/commits/{sha}"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def is_ini_file(filename: str) -> bool:
    return filename.startswith("ini Files/") and filename.endswith(".ini")


def clean_filename(full_path: str) -> str:
    """Convert 'ini Files/SomethingGame.ini' → 'SomethingGame.ini'"""
    return full_path.replace("ini Files/", "", 1)


def build_title(commit: Dict, filename: str) -> str:
    """Build title in French, matching the user's preference."""
    short_sha = commit["sha"][:7]
    clean = clean_filename(filename)

    msg = commit.get("commit", {}).get("message", "")
    version = ""
    if msg.lower().startswith("v"):
        version = msg.split()[0]

    ver_part = version if version else short_sha
    return f"**Ver-{ver_part}_{clean}** a été mis à jour !"


def extract_diff_for_file(commit_details: Dict, filename: str) -> Optional[str]:
    """Extract the unified diff for a specific file from the commit."""
    for f in commit_details.get("files", []):
        if f.get("filename") == filename and "patch" in f:
            patch = f["patch"]
            if len(patch) > MAX_DIFF_LENGTH:
                patch = patch[:MAX_DIFF_LENGTH] + "\n... (diff tronqué)"
            return patch
    return None


def send_discord_message(title: str, diff: str, notes: str = "") -> bool:
    """
    Send message in the style requested by the user (French + NiteStats-like).
    Always includes an **__Explications__** section so the user can easily edit
    the Discord message afterward to add manual explanations.
    """
    content = f"{title}\n```diff\n{diff}\n```"

    # Always add the Explications section (empty if no notes)
    # This makes it very easy for the user to edit the message later and fill it
    if notes:
        content += f"\n**__Explications__**\n{notes}"
    else:
        content += "\n**__Explications__**"

    if len(content) > 1990:
        content = content[:1980] + "\n...```"

    payload = {"content": content}

    if DRY_RUN:
        print("=== DRY RUN ===")
        print(content)
        print("===============")
        return True

    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=15)
        if r.status_code in (200, 204, 201):
            return True
        print(f"[ERROR] Discord webhook failed: {r.status_code} - {r.text[:300]}")
        return False
    except Exception as e:
        print(f"[ERROR] Failed to send to Discord: {e}")
        return False


def process_commit(commit: Dict) -> int:
    """Process one commit and return number of messages sent."""
    sha = commit["sha"]
    print(f"Processing commit {sha[:7]} - {commit['commit']['message'][:60]}")

    details = get_commit_details(sha)
    changed_files = [f for f in details.get("files", []) if is_ini_file(f.get("filename", ""))]

    if not changed_files:
        return 0

    print(f"  → {len(changed_files)} .ini file(s) changed")

    # If too many files changed, post a summary header + as many individual diffs as reasonable
    if len(changed_files) > MAX_FILES_PER_COMMIT:
        title = f"**Ver-{sha[:7]}** — Gros hotfix ({len(changed_files)} fichiers .ini modifiés)"
        summary = (
            f"**Commit:** https://github.com/{GITHUB_REPO}/commit/{sha}\n"
            f"**Message:** {details['commit']['message']}\n\n"
            f"Trop de fichiers pour tout poster. Voici les premiers :\n"
            f"Voir le commit complet pour la liste exhaustive."
        )
        notes_to_use = MANUAL_NOTES if MANUAL_NOTES else ""
        send_discord_message(title, summary, notes=notes_to_use)

        # Still post individual diffs for the first N files
        sent = 1
        for f in changed_files[:45]:  # post up to 45 individual diffs even on big commits
            filename = f["filename"]
            diff = extract_diff_for_file(details, filename)
            if not diff:
                diff = f"(Pas de diff détaillé disponible)\nVoir: https://github.com/{GITHUB_REPO}/commit/{sha}"

            title = build_title(commit, filename)
            notes_to_use = MANUAL_NOTES if MANUAL_NOTES else ""
            if send_discord_message(title, diff, notes=notes_to_use):
                sent += 1
                time.sleep(SLEEP_BETWEEN_MESSAGES)

        return sent

    sent = 0
    for f in changed_files:
        filename = f["filename"]
        diff = extract_diff_for_file(details, filename)
        if not diff:
            # Fallback: just mention the file was changed
            diff = f"(Pas de diff détaillé disponible)\nVoir: https://github.com/{GITHUB_REPO}/commit/{sha}"

        title = build_title(commit, filename)
        notes_to_use = MANUAL_NOTES if MANUAL_NOTES else ""
        if send_discord_message(title, diff, notes=notes_to_use):
            sent += 1
            time.sleep(SLEEP_BETWEEN_MESSAGES)

    return sent


# ====================== CLOUDSTORAGE HELPERS ======================

def fetch_cloudstorage_file(filename: str) -> Optional[str]:
    """Download a specific system .ini file from Epic CloudStorage."""
    if not EPIC_BEARER_TOKEN:
        print(f"[CLOUDSTORAGE] No EPIC_BEARER_TOKEN provided, skipping {filename}")
        return None

    url = f"{CLOUDSTORAGE_BASE}/{filename}"
    try:
        resp = requests.get(url, headers=CLOUDSTORAGE_HEADERS, timeout=30)
        if resp.status_code == 200:
            return resp.text
        elif resp.status_code == 404:
            print(f"[CLOUDSTORAGE] {filename} not found (404)")
            return None
        else:
            print(f"[CLOUDSTORAGE] Failed to fetch {filename}: {resp.status_code} - {resp.text[:200]}")
            return None
    except Exception as e:
        print(f"[CLOUDSTORAGE] Error fetching {filename}: {e}")
        return None


def get_cloudstorage_changes() -> List[Dict[str, str]]:
    """
    Check monitored files against last known versions stored in the repo.
    Returns list of changed files with old/new content for diffing.
    """
    changes = []
    last_known_dir = "last_cloudstorage"

    os.makedirs(last_known_dir, exist_ok=True)

    for filename in MONITORED_CLOUDSTORAGE_FILES:
        current = fetch_cloudstorage_file(filename)
        if current is None:
            continue

        last_path = os.path.join(last_known_dir, filename)

        old_content = ""
        if os.path.exists(last_path):
            with open(last_path, "r", encoding="utf-8", errors="ignore") as f:
                old_content = f.read()

        if current != old_content:
            print(f"[CLOUDSTORAGE] Change detected in {filename}")
            changes.append({
                "filename": filename,
                "old": old_content,
                "new": current
            })

            # Save new version
            with open(last_path, "w", encoding="utf-8") as f:
                f.write(current)

    return changes


def generate_diff(old: str, new: str, filename: str) -> str:
    """Generate a unified diff."""
    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        n=3
    )
    result = "".join(diff)
    if not result.strip():
        return "(No textual diff - binary or whitespace only change)"
    return result[:1800]  # safety


# ====================== MAIN ======================

def main():
    print(f"=== Fortnite INI Hotfix Notifier ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print(f"DRY_RUN={DRY_RUN}")

    run_mode = os.environ.get("GITHUB_EVENT_NAME", "unknown")
    print(f"Trigger: {run_mode}")

    # ==================== CLOUDSTORAGE MODE (preferred) ====================
    if EPIC_BEARER_TOKEN:
        print("[MODE] Using direct Epic CloudStorage (fastest)")
        changes = get_cloudstorage_changes()

        if not changes:
            print("No CloudStorage changes detected since last run.")
            return

        print(f"Found {len(changes)} changed file(s) in CloudStorage.")

        for change in changes:
            filename = change["filename"]
            diff = generate_diff(change["old"], change["new"], filename)

            title = f"**{filename}** was updated!"

            notes = MANUAL_NOTES if MANUAL_NOTES else ""
            send_discord_message(title, diff, notes=notes)
            time.sleep(1.5)

        print("Done (CloudStorage mode).")
        return

    # ==================== FALLBACK: GitHub watcher (iFireMonkey) ====================
    print("[MODE] No EPIC_BEARER_TOKEN found → falling back to GitHub watcher (iFireMonkey)")
    print(f"Repo: {GITHUB_REPO}")

    state = load_state()
    last_sha = state.get("last_commit_sha")

    print(f"Last seen commit: {last_sha or 'None (first run)'}")
    print(f"FORCE_LATEST={FORCE_LATEST}")

    try:
        if FORCE_LATEST:
            print("FORCE_LATEST enabled → will process the latest commit even if already seen")
            commits = get_recent_commits(since_sha=None, limit=1)
        elif last_sha is None:
            print("First run detected → only processing the latest commit")
            commits = get_recent_commits(since_sha=None, limit=1)
        else:
            commits = get_recent_commits(since_sha=last_sha, limit=20)
    except Exception as e:
        print(f"[ERROR] Failed to fetch commits: {e}")
        return

    if not commits:
        print("No new commits since last check.")
        return

    print(f"Found {len(commits)} new commit(s) to check")

    # Process from oldest to newest
    commits.reverse()

    total_sent = 0
    newest_sha = None

    for c in commits:
        sent = process_commit(c)
        total_sent += sent
        newest_sha = c["sha"]

    if newest_sha:
        state["last_commit_sha"] = newest_sha
        state["last_updated"] = datetime.now(timezone.utc).isoformat()
        save_state(state)
        print(f"State saved. Last commit: {newest_sha[:7]}")

    print(f"Done. Sent {total_sent} Discord message(s).")


if __name__ == "__main__":
    main()
