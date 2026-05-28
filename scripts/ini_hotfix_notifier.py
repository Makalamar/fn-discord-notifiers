#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fortnite INI Hotfix Notifier
- Watches iFireMonkey/FortniteTracker for new commits touching .ini files
- Posts to Discord in the exact format requested:
    **Ver-XXXX_Filename.ini** a été mis à jour !
    ```diff
    ...
    ```
- Runs every 5 minutes via GitHub Actions for fastest possible notifications
"""

import os
import sys
import json
import time
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
MAX_FILES_PER_COMMIT = 25          # If more than this, post summary instead of spamming
MAX_DIFF_LENGTH = 1800             # Discord message limit safety
SLEEP_BETWEEN_MESSAGES = 1.2       # Seconds between Discord messages (rate limit)

force_val = os.environ.get("FORCE_LATEST", "0").lower()
FORCE_LATEST = force_val in ("1", "true", "yes")

HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "fortnite-ini-hotfix-notifier/1.0",
}

if "GITHUB_TOKEN" in os.environ:
    HEADERS["Authorization"] = f"token {os.environ['GITHUB_TOKEN']}"


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
    """Build the exact style of title the user wants."""
    short_sha = commit["sha"][:7]
    clean = clean_filename(filename)
    # Try to extract version from commit message (e.g. "v40.40 inis")
    msg = commit.get("commit", {}).get("message", "")
    version = ""
    if msg.lower().startswith("v"):
        # Take first word like "v40.40"
        version = msg.split()[0]
    if version:
        return f"**{version}_{clean}** a été mis à jour !"
    else:
        return f"**{short_sha}_{clean}** a été mis à jour !"


def extract_diff_for_file(commit_details: Dict, filename: str) -> Optional[str]:
    """Extract the unified diff for a specific file from the commit."""
    for f in commit_details.get("files", []):
        if f.get("filename") == filename and "patch" in f:
            patch = f["patch"]
            if len(patch) > MAX_DIFF_LENGTH:
                patch = patch[:MAX_DIFF_LENGTH] + "\n... (diff tronqué)"
            return patch
    return None


def send_discord_message(title: str, diff: str) -> bool:
    """Send a message using the exact format requested by the user."""
    content = f"{title}\n```diff\n{diff}\n```"

    if len(content) > 1990:  # Discord hard limit
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

    # Safety: too many files → post summary instead of spam
    if len(changed_files) > MAX_FILES_PER_COMMIT:
        title = f"**{sha[:7]}** — Gros commit avec {len(changed_files)} fichiers .ini"
        summary = f"Commit: https://github.com/{GITHUB_REPO}/commit/{sha}\n" \
                  f"Message: {details['commit']['message']}\n\n" \
                  f"Trop de fichiers pour tout lister ici. Va voir le commit."
        send_discord_message(title, summary)
        return 1

    sent = 0
    for f in changed_files:
        filename = f["filename"]
        diff = extract_diff_for_file(details, filename)
        if not diff:
            # Fallback: just mention the file was changed
            diff = f"(Pas de diff détaillé disponible)\nVoir: https://github.com/{GITHUB_REPO}/commit/{sha}"

        title = build_title(commit, filename)
        if send_discord_message(title, diff):
            sent += 1
            time.sleep(SLEEP_BETWEEN_MESSAGES)

    return sent


def main():
    print(f"=== Fortnite INI Hotfix Notifier ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print(f"Repo: {GITHUB_REPO}")
    print(f"DRY_RUN={DRY_RUN}")

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
