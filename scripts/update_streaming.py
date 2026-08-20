#!/usr/bin/env python3
"""
update_streaming.py
Aggiorna streaming.m3u dalle fonti samsung.m3u, roku_all.m3u, plutotv.m3u, rakuten.m3u e wedotv.m3u.

Regole:
- Blocchi con gruppi normalizzati e ordinamento: RAKUTEN SAMSUNG PLUTO, WEDOTV, ROKU, PLEX, TUBI, REWARDEDTV, VIZIO.
- Blocchi pass-through con gruppi originali: DTT, SKY, SPORT, RADIO ITALIANE, SICILIA, FREELIVESPORTS, UKTV.
- UKTV: blocco aggiornato manualmente, non viene mai ricostruito dallo script (pass-through puro).
- Samsung/Roku/Rakuten/WedoTV: aggiornano completamente EXTINF e URL sui canali esistenti; per Samsung resta la logica speciale dei loghi jmp2.uk.
- Pluto: aggiorna solo l'URL sui canali esistenti, mantenendo EXTINF intatto, salvo normalizzazione group-title nei blocchi gestiti.
- Samsung con URL jmp2.uk: il logo viene ricostruito come
  https://raw.githubusercontent.com/xer94x/tv/main/loghi/<NomeCanaleSamsung>.png
- Nuovi canali: nel blocco corretto; se il gruppo non è mappabile, vanno in "Nuovi".
"""

import re
import sys
from pathlib import Path
from collections import defaultdict
from urllib.parse import quote

RE_EXTINF  = re.compile(r'^#EXTINF:')
RE_TVGID   = re.compile(r'tvg-id="([^"]*)"')
RE_LOGO    = re.compile(r'tvg-logo="([^"]*)"')
RE_GROUP   = re.compile(r'group-title="([^"]*)"')
RE_EXTREM  = re.compile(r'^#EXTREM\s+\[?(https?://[^\]\s]+)\]?', re.IGNORECASE)
RE_TVGURL  = re.compile(r'url-tvg="([^"]*)"', re.IGNORECASE)
RE_SAMSUNG = re.compile(r'^IT', re.IGNORECASE)
RE_ROKU    = re.compile(r'^[0-9a-f]{32}$', re.IGNORECASE)
RE_JMP2UK  = re.compile(r'https?://jmp2\.uk', re.IGNORECASE)

BLOCK_ORDER = [
    'DTT',
    'SKY',
    'SPORT',
    'RADIO ITALIANE',
    'SICILIA',
    'TGR SICILIA',
    'UKTV',
    'USATV',
    'LIVE EVENTS',
    'SVIZZERA',
    'RAKUTEN SAMSUNG PLUTO',
    'LG',
    'WEDOTV',
    'ROKU',
    'FREELIVESPORTS',
    'PLEX',
    'TUBI',
    'REWARDEDTV',
    'VIZIO',
]

BLOCK_ALIASES = {
    'RAKUTEN  LG SAMSUNG PLUTO': 'RAKUTEN SAMSUNG PLUTO',
    'RAKUTEN LG SAMSUNG PLUTO': 'RAKUTEN SAMSUNG PLUTO',
    'RAKUTEN SAMSUNG PLUTO': 'RAKUTEN SAMSUNG PLUTO',
    'LG': 'LG',
}

NORMALIZED_BLOCKS = {
    'RAKUTEN SAMSUNG PLUTO', 'WEDOTV', 'ROKU'
}

ORDER_ONLY_BLOCKS = {
    'PLEX', 'TUBI', 'REWARDEDTV', 'VIZIO'
}

# Blocchi ricostruiti interamente dalla sorgente (non usano tvg-id matching)
SOURCE_REBUILT_BLOCKS = {
    'SVIZZERA',
    'USATV',
    'LIVE EVENTS',
    'TGR SICILIA',
}

MANAGED_SORT_BLOCKS = NORMALIZED_BLOCKS

NORMALIZED_GROUPS = [
    'Animazione', 'Comedy', 'Crime', 'Documentari', 'Film', 'Intrattenimento',
    'Lifestyle', 'Musica', 'News', 'Nuovi', 'Serie TV', 'Sport'
]

GROUP_MAP = {
    'Animazione': {
        'animazione', 'animazione e bambini', 'teen', 'bambini', 'anime',
        'animated', 'children-music', 'other'
    },
    'Comedy': {'comedy'},
    'Crime': {'serie crime', 'true crime', 'crime drama'},
    'Lifestyle': {
        'cucina', 'cucina & viaggi', 'art', 'cooking', 'faith & family', 'food',
        'gaming & tech', 'gaming and tech', 'health', 'home improvement',
        'house/garden', 'music talk', 'shopping', 'religion'
    },
    'Documentari': {'animals', 'educational', 'environment', 'documentary'},
    'Film': {'horror e paranormale', 'notti di...', 'dark comedy', 'movies', 'romance'},
    'Intrattenimento': {
        'reality show', 'auction', 'biography', 'game show', 'law',
        'paranormal', 'entertainment', 'wedotv', 'novità su pluto tv'
    },
    'Musica': {'music', 'musica e ambient'},
    'News': {'news e mondo', 'bus./financial', 'weather'},
    'Serie TV': {
        'serie tv: sci-fi', 'serie tv sci-fi', 'sci-fi', 'sci fi', 'scifi', 'serie', 'serie classiche', 'tv & entertainment',
        'series', 'telenovela', 'serie tv'
    },
    'Sport': {'motori e sport', 'auto & motorsports', 'sports', 'calcio', 'pro wrestling', 'card games', '3X3 basketball'},
}

SOURCE_BLOCK = {
    'samsung': 'RAKUTEN SAMSUNG PLUTO',
    'pluto': 'RAKUTEN SAMSUNG PLUTO',
    'rakuten': 'RAKUTEN SAMSUNG PLUTO',
    'wedotv': 'WEDOTV',
    'roku': 'ROKU',
}


def canon_text(value: str) -> str:
    return ' '.join((value or '').replace('_', ' ').split()).strip().casefold()


def normalize_group(group: str, fallback='Nuovi') -> str:
    g = canon_text(group)
    if not g:
        return fallback
    for target in NORMALIZED_GROUPS:
        if canon_text(target) == g:
            return target
    for target, values in GROUP_MAP.items():
        if g in values:
            return target
    return fallback


def source_for_tvgid(tvg_id: str) -> str:
    if not tvg_id:
        return 'extra'
    if RE_SAMSUNG.match(tvg_id):
        return 'samsung'
    if RE_ROKU.match(tvg_id):
        return 'roku'
    return 'extra'


def parse_m3u(path: Path) -> list:
    channels = []
    lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    i = 0
    pending_orphans = []
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if line == '#EXTM3U':
            i += 1
            continue
        if RE_EXTINF.match(line):
            raw_lines = pending_orphans + [raw]
            pending_orphans = []
            extinf = raw.strip()
            url = ''
            j = i + 1
            while j < len(lines):
                stripped = lines[j].strip()
                if RE_EXTINF.match(stripped):
                    break
                m_extrem = RE_EXTREM.match(stripped)
                if m_extrem:
                    url = m_extrem.group(1)
                    raw_lines.append(lines[j])
                    i = j
                    break
                if stripped.startswith('#') or stripped == '':
                    raw_lines.append(lines[j])
                    j += 1
                    continue
                url = stripped
                raw_lines.append(lines[j])
                i = j
                break
            m = RE_TVGID.search(extinf)
            g = RE_GROUP.search(extinf)
            tvg_id = m.group(1) if m else ''
            display_name = extinf.rsplit(',', 1)[-1].strip()
            group = g.group(1).strip() if g else ''
            channels.append({
                'extinf': extinf,
                'url': url,
                'tvg_id': tvg_id,
                'display_name': display_name,
                'group': group,
                'raw_lines': raw_lines,
            })
        else:
            pending_orphans.append(raw)
        i += 1
    if pending_orphans and channels:
        channels[-1]['raw_lines'].extend(pending_orphans)
    return channels


def build_index_by_tvgid(channels: list) -> dict:
    return {c['tvg_id']: c for c in channels if c['tvg_id']}


def set_attr(extinf: str, regex: re.Pattern, attr_name: str, value: str) -> str:
    if regex.search(extinf):
        return regex.sub(f'{attr_name}="{value}"', extinf)
    comma = extinf.rfind(',')
    if comma != -1:
        return extinf[:comma] + f' {attr_name}="{value}"' + extinf[comma:]
    return extinf


def samsung_logo_from_name(name: str) -> str:
    clean_name = name.strip().replace('/', '_')
    safe_name = quote(clean_name, safe="()&!'+,._-")
    return f'https://raw.githubusercontent.com/xer94x/tv/main/loghi/{safe_name}.png'


def apply_samsung_logo_rule(extinf: str, src_channel: dict) -> str:
    if RE_JMP2UK.search(src_channel.get('url', '')):
        return set_attr(extinf, RE_LOGO, 'tvg-logo', samsung_logo_from_name(src_channel['display_name']))
    return extinf


def update_extinf(old_extinf: str, new_source: dict, normalized_group=None, keep_logo=False, source_name='') -> str:
    new_extinf = new_source['extinf']
    if normalized_group is not None:
        new_extinf = set_attr(new_extinf, RE_GROUP, 'group-title', normalized_group)
    old_logo_m = RE_LOGO.search(old_extinf)
    if keep_logo and old_logo_m:
        new_extinf = set_attr(new_extinf, RE_LOGO, 'tvg-logo', old_logo_m.group(1))
    if source_name == 'samsung':
        new_extinf = apply_samsung_logo_rule(new_extinf, new_source)
    return new_extinf


def rebuild_group(extinf: str, group: str) -> str:
    return set_attr(extinf, RE_GROUP, 'group-title', group)


def channel_sort_key(ch):
    return (canon_text(ch.get('group_norm', 'Nuovi')), canon_text(ch.get('display_name', '')))


def split_streaming_blocks(lines: list):
    prefix = []
    blocks = []
    current_name = None
    current_lines = []
    header_tvgurl = ''
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith('#EXTM3U'):
            m = RE_TVGURL.search(stripped)
            if m:
                header_tvgurl = m.group(1)
            continue
        if stripped.startswith('#') and not RE_EXTINF.match(stripped):
            tag = stripped.lstrip('#').strip().strip('"')
            canonical = BLOCK_ALIASES.get(tag, tag)
            if canonical in BLOCK_ORDER:
                if current_name is not None:
                    blocks.append((current_name, current_lines))
                current_name = canonical
                current_lines = [f'# {canonical}']
                continue
        if current_name is None:
            prefix.append(raw)
        else:
            current_lines.append(raw)
    if current_name is not None:
        blocks.append((current_name, current_lines))
    return prefix, blocks, header_tvgurl


def parse_block_channels(block_lines: list):
    temp = Path('_tmp_block_parse.m3u')
    temp.write_text('#EXTM3U\n' + '\n'.join(block_lines) + '\n', encoding='utf-8')
    try:
        return parse_m3u(temp)
    finally:
        if temp.exists():
            temp.unlink()


def source_from_indexes(tid: str, source_indexes: dict):
    src_guess = source_for_tvgid(tid)
    if src_guess in ('samsung', 'roku') and tid in source_indexes[src_guess]:
        return src_guess, source_indexes[src_guess][tid]
    for candidate in ('pluto', 'rakuten', 'wedotv'):
        if tid and tid in source_indexes[candidate]:
            return candidate, source_indexes[candidate][tid]
    return None, None


def main():
    base = Path(__file__).resolve().parent.parent
    streaming_path = base / 'streaming.m3u'
    source_paths = {
        'samsung': base / 'samsung.m3u',
        'roku': base / 'roku_all.m3u',
        'pluto': base / 'pluto.m3u',
        'rakuten': base / 'rakuten.m3u',
        'wedotv': base / 'wedotv.m3u',
        'netplus': base / 'netplus.m3u',
        'usatv': base / 'usaTV.m3u',
        'tgr_sicilia': base / 'tgr_sicilia.m3u',
    }
    if not streaming_path.exists():
        print('ERRORE: streaming.m3u non trovato.', file=sys.stderr)
        sys.exit(1)

    source_channels = {}
    source_indexes = {}
    for src, path in source_paths.items():
        if path.exists():
            chs = parse_m3u(path)
            source_channels[src] = chs
            source_indexes[src] = build_index_by_tvgid(chs)
            print(f'{src}: {len(chs)} canali caricati ({len(source_indexes[src])} con tvg-id)')
        else:
            source_channels[src] = []
            source_indexes[src] = {}
            print(f'AVVISO: {path.name} non trovato, skip.')

    raw_streaming = streaming_path.read_text(encoding='utf-8', errors='replace').splitlines()
    prefix, blocks, header_tvgurl = split_streaming_blocks(raw_streaming)
    current_channels = parse_m3u(streaming_path)
    present_ids = {c['tvg_id'] for c in current_channels if c['tvg_id']}

    passthrough_blocks = {}
    normalized_blocks = {k: [] for k in MANAGED_SORT_BLOCKS}

    for block_name, block_lines in blocks:
        if block_name in MANAGED_SORT_BLOCKS:
            # I blocchi gestiti vengono sempre ricostruiti da zero: il vecchio contenuto viene ignorato
            continue
        else:
            passthrough_blocks[block_name] = block_lines

    updated_count = 0

    matched_by_source = defaultdict(int)
    existing_in_managed_blocks = defaultdict(int)

    def update_existing_channel(ch):
        nonlocal updated_count
        tid = ch['tvg_id']
        src, src_ch = source_from_indexes(tid, source_indexes)
        if ch.get('block') in NORMALIZED_BLOCKS:
            existing_in_managed_blocks[ch.get('block')] += 1
        if src:
            matched_by_source[src] += 1
        group_norm = normalize_group(ch.get('group', ''), 'Nuovi')

        if ch['block'] in NORMALIZED_BLOCKS:
            effective_group = group_norm
        else:
            effective_group = ch.get('group', '')

        if src == 'pluto' and src_ch:
            new_extinf = rebuild_group(ch['extinf'], effective_group) if ch['block'] in NORMALIZED_BLOCKS else ch['extinf']
            new_url = src_ch['url']
            if RE_JMP2UK.search(src_ch.get('url', '')):
                new_extinf = apply_samsung_logo_rule(new_extinf, src_ch)
        elif src_ch:
            new_extinf = update_extinf(
                ch['extinf'], src_ch,
                normalized_group=effective_group if ch['block'] in NORMALIZED_BLOCKS else None,
                keep_logo=False,
                source_name=src
            )
            new_url = src_ch['url']
        else:
            new_extinf = rebuild_group(ch['extinf'], effective_group) if ch['block'] in NORMALIZED_BLOCKS else ch['extinf']
            new_url = ch['url']

        if new_extinf != ch['extinf'] or new_url != ch['url']:
            updated_count += 1
        out = dict(ch)
        out['extinf'] = new_extinf
        out['url'] = new_url
        out['group_norm'] = group_norm
        return out

    for block_name in list(normalized_blocks):
        normalized_blocks[block_name] = []

    new_channels = []
    for src in ('samsung', 'pluto', 'rakuten', 'wedotv', 'roku'):
        for tid, ch in source_indexes[src].items():
            group_norm = normalize_group(ch.get('group', ''), 'Nuovi')
            block_name = SOURCE_BLOCK[src]
            extinf = rebuild_group(ch['extinf'], group_norm)
            if src == 'pluto':
                extinf = rebuild_group(ch['extinf'], group_norm)
            if src == 'samsung':
                extinf = apply_samsung_logo_rule(extinf, ch)
            new_ch = dict(ch)
            new_ch['extinf'] = extinf
            new_ch['group_norm'] = group_norm
            new_ch['block'] = block_name
            normalized_blocks[block_name].append(new_ch)
            new_channels.append(new_ch)
            present_ids.add(tid)

    updated_count = sum(len(normalized_blocks[b]) for b in NORMALIZED_BLOCKS)

    # ── Blocchi ricostruiti da sorgente ──────────────────────────────────────
    # SVIZZERA: tutti i canali di netplus.m3u, group-title forzato a "Svizzera"
    svizzera_channels = []
    for ch in source_channels.get('netplus', []):
        new_extinf = set_attr(ch['extinf'], RE_GROUP, 'group-title', 'Svizzera')
        svizzera_channels.append((new_extinf, ch['url']))

    # USATV: canali di usaTV.m3u con group-title originale == "TV", rinominato "usaTV"
    usatv_channels = []
    for ch in source_channels.get('usatv', []):
        if ch.get('group', '').strip() == 'TV':
            new_extinf = set_attr(ch['extinf'], RE_GROUP, 'group-title', 'usaTV')
            usatv_channels.append((new_extinf, ch['url']))

    # LIVE EVENTS: canali di usaTV.m3u con group-title originale == "Live Events" (invariato)
    # Si usano raw_lines per preservare le righe #EXTVLCOPT presenti nella sorgente
    liveevents_channels = []
    for ch in source_channels.get('usatv', []):
        if ch.get('group', '').strip() == 'Live Events':
            liveevents_channels.append(ch['raw_lines'])

    # TGR SICILIA: tutti i VOD di tgr_sicilia.m3u, group-title forzato a "TGR Sicilia"
    tgr_sicilia_channels = []
    for ch in source_channels.get('tgr_sicilia', []):
        new_extinf = set_attr(ch['extinf'], RE_GROUP, 'group-title', 'TGR Sicilia')
        tgr_sicilia_channels.append((new_extinf, ch['url']))

    extm3u_header = f'#EXTM3U url-tvg="{header_tvgurl}"' if header_tvgurl else '#EXTM3U'
    out_lines = [extm3u_header]

    source_rebuilt = {
        'SVIZZERA': svizzera_channels,
        'USATV': usatv_channels,
        'LIVE EVENTS': liveevents_channels,
        'TGR SICILIA': tgr_sicilia_channels,
    }

    for block_name in BLOCK_ORDER:
        if block_name in source_rebuilt:
            out_lines.append(f'# {block_name}')
            if block_name == 'LIVE EVENTS':
                # raw_lines contiene EXTINF + #EXTVLCOPT + URL nell'ordine corretto
                for raw_lines in source_rebuilt[block_name]:
                    out_lines.extend(raw_lines)
            else:
                for extinf, url in source_rebuilt[block_name]:
                    out_lines.append(extinf)
                    if url:
                        out_lines.append(url)
        elif block_name in MANAGED_SORT_BLOCKS:
            out_lines.append(f'# {block_name}')
            for ch in sorted(normalized_blocks[block_name], key=channel_sort_key):
                out_lines.append(ch['extinf'])
                if ch['url']:
                    out_lines.append(ch['url'])
        elif block_name in passthrough_blocks:
            out_lines.extend(passthrough_blocks[block_name])

    streaming_path.write_text('\n'.join(out_lines) + '\n', encoding='utf-8')

    print('\nâ”€â”€ Riepilogo â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€')
    print(f'Canali aggiornati: {updated_count}')
    print(f'Nuovi canali aggiunti: {len(new_channels)}')
    print('Match canali esistenti per fonte: ' + ', '.join(f'{k}={matched_by_source[k]}' for k in ('samsung','pluto','rakuten','wedotv','roku')))
    print(f'Totale canali con tvg-id presenti: {len(present_ids)}')
    by_block = defaultdict(int)
    for ch in new_channels:
        by_block[ch['block']] += 1
    for block_name in BLOCK_ORDER:
        if block_name in MANAGED_SORT_BLOCKS:
            print(f'{block_name}: {len(normalized_blocks[block_name])} canali, nuovi {by_block[block_name]}')
    print(f'SVIZZERA: {len(svizzera_channels)} canali')
    print(f'USATV: {len(usatv_channels)} canali')
    print(f'LIVE EVENTS: {len(liveevents_channels)} canali')
    print(f'TGR SICILIA: {len(tgr_sicilia_channels)} VOD')

    if updated_count == 0 and len(new_channels) == 0:
        print('Nessuna modifica rilevata: o i canali sono giÃ  allineati, oppure i tvg-id dei blocchi gestiti non trovano corrispondenza nelle playlist sorgenti, oppure le playlist sorgenti non sono presenti/in root.')

if __name__ == '__main__':
    main()
