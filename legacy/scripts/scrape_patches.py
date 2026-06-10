#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Scraper Fortnite patches par Chapitre/Saison (Fortnite Wiki – Fandom).

- Parcourt les URL de saisons (C1→C6)
- Extrait: version, type (Update/Content Update/Event), date
- Écrit data/patches.csv
- Regénère chapters/*.md et seasons/*.md

Dépendances: requests, beautifulsoup4, python-slugify
"""

import re, csv, os, sys, json, time
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from slugify import slugify

BASE = "https://fortnite.fandom.com"
SEASON_PAGES = [
    # Chapitre 1
    (1, 1, f"{BASE}/wiki/Season_1"),
    (1, 2, f"{BASE}/wiki/Season_2"),
    (1, 3, f"{BASE}/wiki/Season_3"),
    (1, 4, f"{BASE}/wiki/Season_4"),
    (1, 5, f"{BASE}/wiki/Season_5"),
    (1, 6, f"{BASE}/wiki/Season_6"),
    (1, 7, f"{BASE}/wiki/Season_7"),
    (1, 8, f"{BASE}/wiki/Season_8"),
    (1, 9, f"{BASE}/wiki/Season_9"),
    (1, 10, f"{BASE}/wiki/Season_X"),
    # Chapitre 2
    (2, 1, f"{BASE}/wiki/Chapter_2:_Season_1"),
    (2, 2, f"{BASE}/wiki/Chapter_2:_Season_2"),
    (2, 3, f"{BASE}/wiki/Chapter_2:_Season_3"),
    (2, 4, f"{BASE}/wiki/Chapter_2:_Season_4"),
    (2, 5, f"{BASE}/wiki/Chapter_2:_Season_5"),
    (2, 6, f"{BASE}/wiki/Chapter_2:_Season_6"),
    (2, 7, f"{BASE}/wiki/Chapter_2:_Season_7"),
    (2, 8, f"{BASE}/wiki/Chapter_2:_Season_8"),
    # Chapitre 3
    (3, 1, f"{BASE}/wiki/Chapter_3:_Season_1"),
    (3, 2, f"{BASE}/wiki/Chapter_3:_Season_2"),
    (3, 3, f"{BASE}/wiki/Chapter_3:_Season_3"),
    (3, 4, f"{BASE}/wiki/Chapter_3:_Season_4"),
    # Chapitre 4
    (4, 1, f"{BASE}/wiki/Chapter_4:_Season_1"),
    (4, 2, f"{BASE}/wiki/Chapter_4:_Season_2"),
    (4, 3, f"{BASE}/wiki/Chapter_4:_Season_3"),
    (4, 4, f"{BASE}/wiki/Chapter_4:_Season_4"),
    (4, "OG", f"{BASE}/wiki/Chapter_4:_Season_OG"),
    # Chapitre 5
    (5, 1, f"{BASE}/wiki/Chapter_5:_Season_1"),
    (5, 2, f"{BASE}/wiki/Chapter_5:_Season_2"),
    (5, 3, f"{BASE}/wiki/Chapter_5:_Season_3"),
    (5, 4, f"{BASE}/wiki/Chapter_5:_Season_4"),
    # Chapitre 6 (ex. 2025) – si pages dédiées
    (6, 1, f"{BASE}/wiki/Chapter_6:_Season_1"),
]

HEADERS = {"User-Agent": "fortnite-update-history-scraper/1.0"}

DATE_PAT = re.compile(r"\((?:[A-Za-z]+)\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4}\)")
ALT_DATE_PAT = re.compile(r"(\d{4}-\d{2}-\d{2})")

def to_iso(s):
    # convertit "October 26th 2017" → "2017-10-26"
    s = s.replace("(", "").replace(")", "").replace(",", "").replace("st","" ).replace("nd","" ).replace("rd","" ).replace("th","" )
    try:
        return datetime.strptime(s.strip(), "%B %d %Y").strftime("%Y-%m-%d")
    except:
        return None

def scrape_season(ch, se, url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    data = []

    # Titre des sections de patchs: "Update v11.10 (October 29th 2019)" etc.
    for hdr in soup.select("h3, h4"):
        text = hdr.get_text(" ", strip=True)
        if not text:
            continue
        m = re.search(r"(Content\s+Update|Update)\s+v?([0-9]+\.[0-9]+(?:\.[0-9]+)?)", text, flags=re.I)
        if m:
            ptype = "Content_Update" if "Content" in m.group(1) else "Update"
            ver = m.group(2)
            # Date dans le même titre
            mdate = re.search(r"\(([A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4})\)", text)
            date_iso = to_iso(mdate.group(1)) if mdate else None

            # fallback: parfois dates listées sous le titre dans un <p> ou <li>
            if not date_iso:
                sib = hdr.find_next()
                for _ in range(5):
                    if not sib: break
                    st = sib.get_text(" ", strip=True)
                    md = re.search(r"([A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4})", st)
                    if md:
                        date_iso = to_iso(md.group(1))
                        break
                    sib = sib.find_next_sibling()

            data.append({
                "chapter": ch,
                "season": se,
                "season_code": f"ch{ch}_s{se}".lower(),
                "patch_version": f"v{ver}",
                "patch_type": ptype if date_iso else ptype,
                "release_date": date_iso or "",
                "source": url
            })
    return data

def main():
    os.makedirs("data", exist_ok=True)
    os.makedirs("chapters", exist_ok=True)
    os.makedirs("seasons", exist_ok=True)

    rows = []
    by_chapter = {}

    for ch, se, url in SEASON_PAGES:
        try:
            season_rows = scrape_season(ch, se, url)
        except Exception as e:
            print(f"[WARN] {ch}-{se} : {e}", file=sys.stderr)
            continue

        rows.extend(season_rows)
        by_chapter.setdefault(ch, []).append(se)

        # saison → page détaillée
        code = f"ch{ch}_s{se}".lower()
        with open(f"seasons/{code}.md", "w", encoding="utf-8") as f:
            f.write(f"# Chapitre {ch} – Saison {se}\n\n")
            f.write("| Date | Version | Type |\n|------|---------|------|\n")
            for r in sorted(season_rows, key=lambda x: ((x["release_date"] or "9999-99-99"), x["patch_version"])):
                d = r["release_date"] or "N/A"
                f.write(f"| {d} | {r['patch_version']} | {r['patch_type'].replace('_',' ')} |\n")
            f.write(f"\nSource : {url}\n")

    # CSV global
    rows.sort(key=lambda x: (int(x["chapter"]), str(x["season"]), x["release_date"] or "9999-99-99", x["patch_version"]))
    with open("data/patches.csv", "w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=["chapter","season","season_code","patch_version","patch_type","release_date","source"])
        w.writeheader()
        w.writerows(rows)

    # pages chapitre
    for ch in sorted(by_chapter.keys()):
        seasons = sorted(by_chapter[ch], key=lambda s: (str(s)))
        with open(f"chapters/chapter{ch}.md", "w", encoding="utf-8") as f:
            f.write(f"# Chapitre {ch} — Récapitulatif des saisons\n\n")
            f.write("| Saison | Détail patches |\n|---:|---|\n")
            for se in seasons:
                code = f"ch{ch}_s{se}".lower()
                f.write(f"| {se} | [CH{ch}-S{se}](../seasons/{code}.md) |\n")

if __name__ == "__main__":
    main()
