# Fortnite Discord Notifiers

**Automatic Discord notifications for Fortnite updates — fast, clean, and reliable.**

This repository contains two focused GitHub Actions bots that post to Discord:

- **INI Hotfix Notifier** — Real-time detection of all official `.ini` hotfixes (every 5 minutes)
- **Jam Tracks Notifier** — Detection of new Jam Tracks (Festival) with rich embeds + album art

---

## Features

### INI Hotfix Notifier
- Checks **every 5 minutes** (fastest possible on GitHub free tier)
- Tracks **every** `.ini` file from Epic's CloudStorage (via public mirror)
- Posts in the exact format you want:
  ```
  **Ver-20260603-4041_DefaultGame.ini a été mis à jour !**
  ```diff
  ...
  ```
  **__Explications__**
  ```
- Supports manual notes via workflow input
- Full diffs (no aggressive truncation)
- State persisted in the repository

### Jam Tracks Notifier
- Checks every **30 minutes**
- Posts rich **Discord embeds** with:
  - Track name + artist + year
  - Rating / Track ID / Duration
  - Key / Scale / Tempo + "New Until" date
  - Difficulty chart with visual bars (8 segments)
  - **Album art as thumbnail** (small image in the top-right)
- Dedicated webhook support (separate channel from hotfixes)
- Built-in **test mode**: manually trigger to send the latest added track for verification

---

## Repository Name Recommendation

This project is best referred to as:

> **Fortnite Discord Notifiers**

If you fork or rename the repository on GitHub, we recommend using one of these clear names:
- `Fortnite-Discord-Notifiers`
- `fn-discord-notifiers`
- `fortnite-notifiers`

---

## Quick Setup

### 1. Required GitHub Secrets

Go to your repository → **Settings → Secrets and variables → Actions** and add:

| Secret                        | Description                                      | Used by                  |
|-------------------------------|--------------------------------------------------|--------------------------|
| `DISCORD_WEBHOOK_URL`         | Webhook for INI Hotfix notifications             | INI Hotfix Notifier      |
| `DISCORD_JAM_WEBHOOK_URL`     | (Optional) Separate webhook for Jam Tracks       | Jam Tracks Notifier      |

### 2. Workflows

Both notifiers are independent:

- `Fortnite INI Hotfix Notifier` → runs every 5 minutes
- `Fortnite Jam Tracks Notifier` → runs every 30 minutes

You can trigger them manually anytime from the **Actions** tab.

---

## INI Hotfix Notifier

### Manual Testing

1. Go to **Actions** → "Fortnite INI Hotfix Notifier"
2. Click **Run workflow**
3. Options:
   - `dry_run` → Preview messages without posting
   - `notes` → Add custom text that will appear under **__Explications__**

### How it works
- Fetches the public Dilly mirror (`export-service-new.dillyapis.com`)
- Compares file hashes against the last known state in `last_cloudstorage/`
- On change: generates a clean diff and posts to Discord
- Commits the new state back to the repository (`[skip ci]`)

---

## Jam Tracks Notifier

### Special Test Feature (Recommended)

To verify that the embed + thumbnail work correctly:

1. Go to **Actions** → "Fortnite Jam Tracks Notifier"
2. Click **Run workflow**
3. Check **test_last_track**
4. (Optional) Also check **dry_run** the first time
5. Run

This will **force-send the most recently added Jam Track** from the API as a full embed (with album art thumbnail), without affecting the normal "new tracks only" logic.

### Normal Behavior
- Only posts when a truly new track ID appears
- Uses a dedicated state file: `data/notified_jam_tracks.json`
- Supports a separate Discord webhook

---

## Local Development / Testing

```bash
# Install dependencies
pip install -r requirements.txt

# Test INI notifier
DRY_RUN=1 python scripts/ini_hotfix_notifier.py

# Test Jam Tracks notifier
DRY_RUN=1 python scripts/jam_tracks_notifier.py

# Force test the latest Jam Track
TEST_LAST_TRACK=1 DRY_RUN=1 python scripts/jam_tracks_notifier.py
```

---

## Legacy Content

This repository originally contained:

- Full historical patch data (Chapter 1 to Chapter 6)
- An old official news/patch announcer
- Various authentication experiments (from the time we tried direct Epic CloudStorage)

All of this has been moved to the `legacy/` folder to keep the active project clean and focused.

**Active files (current tools):**
- `scripts/ini_hotfix_notifier.py`
- `scripts/jam_tracks_notifier.py`
- `.github/workflows/` (the two notifiers)

The active focus of the project is now the **Discord notifiers**.

---

## License

MIT — see [LICENSE](LICENSE)

---

**Maintained for speed and clarity.**  
If you find a faster public source for either hotfixes or Jam Tracks, feel free to open an issue or PR.