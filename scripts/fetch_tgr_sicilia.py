"""
fetch_tgr_sicilia.py

Recupera l'ultimo VOD del TGR Sicilia dall'API JSON di rainews.it
e aggiunge la voce in coda a tgr_sicilia.m3u senza sovrascrivere.

Dipendenze: requests, beautifulsoup4
"""

import re
import sys
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

PLAYLIST_FILE = "tgr_sicilia.m3u"
LOGO = "https://i.ibb.co/rRjXmMZQ/images.jpg"

API_URL = "https://www.rainews.it/tgr/sicilia/notiziari.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "it-IT,it;q=0.9",
    "Referer": "https://www.rainews.it/tgr/sicilia/notiziari",
}


def data_italiana():
    """Restituisce la data odierna in formato italiano, es. '29 marzo 2026'."""
    tz_it = timezone(timedelta(hours=2))  # CEST; in inverno cambiare a hours=1
    now = datetime.now(tz_it)
    mesi = [
        "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
        "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
    ]
    return f"{now.day} {mesi[now.month - 1]} {now.year}"


def fix_title(raw):
    """
    Estrae solo l'orario dal titolo grezzo e lo combina con la data.
    Input esempio: 'TGR Sicilia del   Edizione delle ore 19:30'
    Output: '30 marzo 2026 - ore 19:30'
    """
    data = data_italiana()

    # Cerca l'orario nel titolo (es. "19:30")
    match = re.search(r'(\d{1,2}:\d{2})', raw)
    if match:
        orario = match.group(1)
        return f"{data} - ore {orario}"

    # Fallback: solo la data
    return data


def extract_title(soup):
    """Estrae e corregge il titolo dalla pagina."""
    for sel in ["h1", "h2.title", ".article-title", "h2", "title"]:
        el = soup.select_one(sel)
        if el:
            t = el.get_text(separator=" ").strip()
            if t:
                return fix_title(t)
    return data_italiana()


def get_latest_vod():
    """
    Prova prima l'endpoint JSON; se fallisce, fa scraping HTML della pagina.
    Restituisce (stream_url, title) o (None, None).
    """

    # --- Tentativo 1: endpoint JSON ---
    try:
        r = requests.get(API_URL, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            data = r.json()
            items = data if isinstance(data, list) else data.get("items", data.get("data", []))
            if items:
                item = items[0]
                raw_title = item.get("title", "")
                title = fix_title(raw_title)
                video_url = (
                    item.get("videoUrl")
                    or item.get("url")
                    or item.get("streamUrl")
                    or item.get("mediaUrl")
                )
                if video_url:
                    print(f"  📺 Trovato via JSON: {title}")
                    return resolve_stream(video_url), title
    except Exception as e:
        print(f"  ℹ️  JSON endpoint non disponibile: {e}")

    # --- Tentativo 2: scraping HTML della pagina notiziari ---
    print("  🔄 Provo scraping HTML...")
    try:
        page_url = "https://www.rainews.it/tgr/sicilia/notiziari"
        r = requests.get(page_url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        for tag in soup.find_all(attrs={"data-mediapolicontenturl": True}):
            url = tag["data-mediapolicontenturl"]
            raw_title = tag.get("data-title", "")
            title = fix_title(raw_title)
            print(f"  📺 Trovato via HTML attr: {title}")
            return resolve_stream(url), title

        for script in soup.find_all("script"):
            text = script.string or ""
            if "m3u8" in text or "relinker" in text or "mediapolis" in text:
                match = re.search(r'https://mediapolis[^\s"\']+', text)
                if match:
                    url = match.group(0).rstrip("\\,;")
                    print(f"  📺 Trovato via script embedded")
                    return resolve_stream(url), extract_title(soup)
                match = re.search(r'https://[^\s"\']+\.m3u8[^\s"\']*', text)
                if match:
                    url = match.group(0).rstrip("\\,;")
                    print(f"  ✅ m3u8 trovato direttamente")
                    return url, extract_title(soup)

        article_link = soup.select_one("a[href*='/tgr/sicilia/articoli']")
        if article_link:
            article_url = "https://www.rainews.it" + article_link["href"]
            print(f"  🔄 Seguo link articolo: {article_url}")
            return get_stream_from_article(article_url)

    except Exception as e:
        print(f"  ⚠️  Errore scraping HTML: {e}")

    return None, None


def get_stream_from_article(url):
    """Apre la pagina di un singolo articolo/notiziario e cerca il video."""
    try:
        headers = HEADERS.copy()
        headers["Referer"] = "https://www.rainews.it/tgr/sicilia/notiziari"
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        title = extract_title(soup)
        text = r.text

        match = re.search(r'https://[^\s"\']+\.m3u8[^\s"\']*', text)
        if match:
            return match.group(0).rstrip("\\,;"), title

        match = re.search(r'https://mediapolis[^\s"\']+', text)
        if match:
            return resolve_stream(match.group(0).rstrip("\\,;")), title

        for tag in soup.find_all(attrs={"data-mediapolicontenturl": True}):
            return resolve_stream(tag["data-mediapolicontenturl"]), title

    except Exception as e:
        print(f"  ⚠️  Errore articolo: {e}")

    return None, None


def resolve_stream(url):
    """Segue il redirect del relinker RAI per ottenere l'm3u8 reale."""
    if not url:
        return None
    if ".m3u8" in url:
        return url
    try:
        r = requests.get(url, headers=HEADERS, allow_redirects=True, timeout=15)
        if ".m3u8" in r.url:
            print(f"  ✅ Stream risolto: {r.url[:80]}...")
            return r.url
        match = re.search(r'https://[^\s"\']+\.m3u8[^\s"\']*', r.text)
        if match:
            return match.group(0)
    except Exception as e:
        print(f"  ⚠️  Errore resolving stream: {e}")
    return url


MAX_VOD = 50


def parse_entries(content):
    """
    Analizza il contenuto del file .m3u e restituisce una lista di tuple
    (extinf_line, url_line) per ogni voce, ignorando l'header #EXTM3U.
    """
    entries = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            extinf = line
            if i + 1 < len(lines):
                url = lines[i + 1].strip()
                if url and not url.startswith("#"):
                    entries.append((extinf, url))
                    i += 2
                    continue
        i += 1
    return entries


def append_to_playlist(stream_url, title):
    try:
        with open(PLAYLIST_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        content = ""

    entries = parse_entries(content)

    # Controllo duplicati: confronta la parte base dell'URL (senza token temporanei)
    base_url = stream_url.split("?")[0]
    for _, existing_url in entries:
        if existing_url.split("?")[0] == base_url:
            print(f"  ℹ️  Stream già presente nella playlist, salto.")
            return

    # Nuova voce in cima
    new_entry = (
        f'#EXTINF:-1 tvg-logo="{LOGO}",{title}',
        stream_url,
    )
    entries.insert(0, new_entry)

    # Limite MAX_VOD: elimina i più vecchi (in fondo alla lista)
    if len(entries) > MAX_VOD:
        rimossi = len(entries) - MAX_VOD
        entries = entries[:MAX_VOD]
        print(f"  🗑️  Rimossi {rimossi} VOD più vecchi (limite {MAX_VOD}).")

    # Ricostruisce il file
    lines = ["#EXTM3U"]
    for extinf, url in entries:
        lines.append(extinf)
        lines.append(url)

    with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"  ✅ Aggiunto in cima: {title} ({len(entries)}/{MAX_VOD} VOD)")


def main():
    print("🔍 Cerco VOD TGR Sicilia...")
    stream_url, title = get_latest_vod()

    if not stream_url:
        print("  ❌ Nessun stream trovato, esco.")
        sys.exit(1)

    if not title:
        title = data_italiana()

    append_to_playlist(stream_url, title)


if __name__ == "__main__":
    main()
