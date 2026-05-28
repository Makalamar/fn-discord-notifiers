# Fortnite INI Hotfix Tracker (Discord Notifications)

**Objectif principal** : Être notifié **le plus rapidement possible** quand Epic pousse des hotfixes .ini (tous les fichiers de configuration).

- Vérifie toutes les **5 minutes**
- Surveille principalement **iFireMonkey/FortniteTracker**
- Poste dans Discord avec le format exact que tu veux :
  ```
  **Ver-XXXX_Fichier.ini** a été mis à jour !
  ```diff
  ...
  ```

---

## Configuration rapide (INI Hotfix Notifier)

1. Assure-toi que le secret `DISCORD_WEBHOOK_URL` existe déjà dans :
   `Settings → Secrets and variables → Actions`

2. Le workflow tourne automatiquement toutes les 5 minutes.

3. Pour forcer une première exécution :
   - Va dans l’onglet **Actions**
   - Sélectionne **"Fortnite INI Hotfix Notifier"**
   - Clique sur **Run workflow**

---

## Ancien système (News)

L’ancien notifier d’annonces officielles (`fortnite_discord_notifier.py`) est toujours présent mais n’est plus la priorité. Tu peux le désactiver ou le supprimer si tu veux.

---

# Fortnite – Historique complet des mises à jour (patches) par Chapitre/Saison

> Ancien système de suivi historique des patches. Le nouveau tracker INI (ci-dessus) est maintenant la partie active.

Ce dépôt fournit un suivi chronologique **du Chapitre 1 → Chapitre 6**, trié par chapitre puis par saison, avec **toutes les versions de patch** et **leurs dates de déploiement** (lorsqu’elles sont connues publiquement).  
Les sources primaires sont les pages « Patch Notes » / « Saison » du **Fortnite Wiki (Fandom)** et, lorsqu’elles existent, les notes officielles d’Epic Games.  

## Contenu  
- `chapters/` : vue récapitulative par chapitre (Saisons, dates de début/fin, lien vers détail).    
- `seasons/` : une page par saison listant **toutes** les versions (vX.YY[.Z], « Content Update »…) et **la date exacte**.    
- `data/patches.csv` : export plat (chapitre, saison, version, date ISO 8601, type, URL source).    
- `scripts/scrape_patches.py` : script pour régénérer `patches.csv` et les `.md` à partir des pages du wiki.  

## Format CSV  
| chapter | season | season_code | patch_version | patch_type | release_date | source |  
|--------:|-------:|-------------|---------------|------------|--------------|--------|  
| 1 | 1 | ch1_s1 | v1.8 | Update | 2017-10-26 | https://fortnite.fandom.com/wiki/Season_1 |  
| 1 | 1 | ch1_s1 | v1.8.1 | Update | 2017-11-02 | https://fortnite.fandom.com/wiki/Season_1 |  
| … | … | … | … | … | … | … |  

> Remarque : certaines mises à jour « Content Update » sans binaire sont aussi incluses si datées.  

## Sources  
- Fortnite Wiki – **Season 1 (Chapitre 1)** : liste officielle des patches et dates (v1.8 → v1.10).    
- Fortnite Wiki – **Chapter 2 : Season 1** : v11.00 → v11.50 et dates détaillées.    
- Index « Patch Notes » (catégorie) pour navigation globale.    
- Notes Epic Games lorsque disponibles (ex. v2.2.0, v6.00).  

## Génération / mise à jour  

```
bash
python3 scripts/scrape_patches.py
```

Le script :  
1. parcourt les pages « Saison »/« Patch Notes » du wiki,    
2. extrait **version** + **date**,    
3. normalise les dates au format `YYYY-MM-DD`,    
4. écrit `data/patches.csv`,    
5. régénère les pages `chapters/*.md` et `seasons/*.md`.  

## Licence  
MIT – voir `LICENSE`.

---

## Discord Patch Notifier (Automatic)

This repository includes an automatic notifier that posts **every official Fortnite update** (Updates + Content Updates) to a Discord channel via webhook.

### Features
- Posts **all** patches (including small hotfixes)
- English only (as requested)
- Clean embed with direct link to the season's patch notes on the Fortnite Wiki
- Runs automatically every 20 minutes via GitHub Actions
- State is persisted in the repo (`data/last_notified.json`) so it never spams old patches

### Setup (one-time)

1. **Create a Discord webhook**
   - Go to your server → Channel settings → Integrations → Webhooks → New Webhook
   - Give it a name (e.g. "Fortnite Updates") and copy the webhook URL

2. **Add the secret to your GitHub repository**
   - Go to your repo → **Settings** → **Secrets and variables** → **Actions**
   - Click **New repository secret**
   - Name: `DISCORD_WEBHOOK_URL`
   - Value: paste the full webhook URL you copied

3. **Enable the workflow**
   - Go to the **Actions** tab
   - You should see "Fortnite Patch Notifier"
   - Run it manually once using **Run workflow** (this will post the latest known patch and bootstrap the state)

After that, it will automatically check for new patches every 20 minutes and post them.

### Manual testing (locally)

```bash
# Dry run (prints what would be sent, no Discord call)
DRY_RUN=1 python scripts/fortnite_discord_notifier.py

# Real run (requires the env var)
DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." \
python scripts/fortnite_discord_notifier.py
```

### How it works
- Uses the reliable public API `https://fortnite-api.com/v2/news` (Battle Royale section)
- Filters for items that look like real updates/events
- Posts rich Discord embeds (title + body + official image when available)
- Links to the official https://www.fortnite.com/news hub for full patch notes
- Tracks already-posted items via `data/last_notified.json` and commits the state back
- Never relies on fragile web scraping (Fandom blocks most bots)

### Customizing
- Want fewer notifications? Edit the schedule in `.github/workflows/fortnite-patch-notifier.yml`
- Want to change the embed style? Edit `scripts/fortnite_discord_notifier.py`
- New season launched? Add the new season URL to `SEASON_PAGES` in the notifier script

---

## Génération / mise à jour manuelle de l'historique

```bash
python3 scripts/scrape_patches.py
```

