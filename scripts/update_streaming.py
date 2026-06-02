#!/usr/bin/env python3
"""
update_streaming.py
Aggiorna streaming.m3u dalle fonti samsung.m3u, roku_all.m3u e plutotv.m3u.

Logica:
- Samsung (tvg-id inizia con "IT"): aggiorna URL da samsung.m3u (logo conservato)
- Roku (tvg-id UUID hex 32 chars): aggiorna URL da roku_all.m3u (logo conservato)
- Pluto (tvg-id qualsiasi, presente in pluto.m3u): aggiorna SOLO URL, senza modificare extinf
- Extra: conservati invariati
- Commenti/righe orfane tra canali: conservati invariati
- Nuovi canali nelle fonti: aggiunti nel gruppo "Nuovi"
- group-title in streaming.m3u non viene mai modificato sui canali esistenti
"""

import re
import sys
from pathlib import Path

RE_EXTINF  = re.compile(r'^#EXTINF:')
RE_TVGID   = re.compile(r'tvg-id="([^"]*)"')
RE_LOGO    = re.compile(r'tvg-logo="([^"]*)"')
RE_GROUP   = re.compile(r'group-title="([^"]*)"')
RE_SAMSUNG = re.compile(r'^IT', re.IGNORECASE)
RE_ROKU    = re.compile(r'^[0-9a-f]{32}$', re.IGNORECASE)
RE_EXTREM  = re.compile(r'^#EXTREM\s+\[?(https?://[^\]\s]+)\]?', re.IGNORECASE)


def source_for_tvgid(tvg_id: str) -> str:
    """Restituisce 'samsung', 'roku' o 'extra' in base al tvg-id."""
    if not tvg_id:
        return 'extra'
    if RE_SAMSUNG.match(tvg_id):
        return 'samsung'
    if RE_ROKU.match(tvg_id):
        return 'roku'
    return 'extra'


def get_orphan_prefix(raw_lines: list) -> list:
    prefix = []
    for l in raw_lines:
        if RE_EXTINF.match(l.strip()):
            break
        prefix.append(l)
    return prefix


def parse_m3u(path: Path) -> list:
    channels = []
    lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    i = 0
    pending_orphans = []

    while i < len(lines):
        line = lines[i].strip()

        if line == '#EXTM3U':
            i += 1
            continue

        if RE_EXTINF.match(line):
            raw_lines = pending_orphans + [lines[i]]
            pending_orphans = []
            extinf = line
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

                if stripped.startswith('#'):
                    raw_lines.append(lines[j])
                    j += 1
                    continue

                if stripped:
                    url = stripped
                    raw_lines.append(lines[j])
                    i = j
                    break

                j += 1

            m = RE_TVGID.search(extinf)
            tvg_id = m.group(1) if m else ''
            display_name = extinf.rsplit(',', 1)[-1].strip()

            channels.append({
                'extinf': extinf,
                'url': url,
                'tvg_id': tvg_id,
                'display_name': display_name,
                'raw_lines': raw_lines,
            })

        else:
            pending_orphans.append(lines[i])

        i += 1

    if pending_orphans and channels:
        channels[-1]['raw_lines'].extend(pending_orphans)

    return channels


def build_index_by_tvgid(channels: list) -> dict:
    return {c['tvg_id']: c for c in channels if c['tvg_id']}


def update_extinf(old_extinf: str, new_source: dict, keep_group: str) -> str:
    """Per Samsung/Roku: prende extinf dalla fonte e mantiene group-title e logo originali."""
    new_extinf = new_source['extinf']

    if RE_GROUP.search(new_extinf):
        new_extinf = RE_GROUP.sub(f'group-title="{keep_group}"', new_extinf)
    else:
        comma = new_extinf.rfind(',')
        if comma != -1:
            new_extinf = new_extinf[:comma] + f' group-title="{keep_group}"' + new_extinf[comma:]

    old_logo_m = RE_LOGO.search(old_extinf)
    if old_logo_m:
        keep_logo = old_logo_m.group(1)
        if RE_LOGO.search(new_extinf):
            new_extinf = RE_LOGO.sub(f'tvg-logo="{keep_logo}"', new_extinf)
        else:
            comma = new_extinf.rfind(',')
            if comma != -1:
                new_extinf = new_extinf[:comma] + f' tvg-logo="{keep_logo}"' + new_extinf[comma:]

    return new_extinf


def new_extinf_for_new_channel(source_extinf: str, group: str = 'Nuovi') -> str:
    extinf = source_extinf
    if RE_GROUP.search(extinf):
        extinf = RE_GROUP.sub(f'group-title="{group}"', extinf)
    else:
        comma = extinf.rfind(',')
        if comma != -1:
            extinf = extinf[:comma] + f' group-title="{group}"' + extinf[comma:]
    return extinf


def main():
    base = Path(__file__).parent.parent
    streaming_path = base / 'streaming.m3u'
    samsung_path = base / 'samsung.m3u'
    roku_path = base / 'roku_all.m3u'
    pluto_path = base / 'pluto.m3u'

    if not streaming_path.exists():
        print('ERRORE: streaming.m3u non trovato.', file=sys.stderr)
        sys.exit(1)

    samsung_idx = {}
    roku_idx = {}
    pluto_idx = {}

    if samsung_path.exists():
        samsung_channels = parse_m3u(samsung_path)
        samsung_idx = build_index_by_tvgid(samsung_channels)
        print(f'Samsung: {len(samsung_channels)} canali caricati ({len(samsung_idx)} con tvg-id)')
    else:
        print('AVVISO: samsung.m3u non trovato, skip aggiornamento Samsung.')

    if roku_path.exists():
        roku_channels = parse_m3u(roku_path)
        roku_idx = build_index_by_tvgid(roku_channels)
        print(f'Roku: {len(roku_channels)} canali caricati ({len(roku_idx)} con tvg-id)')
    else:
        print('AVVISO: roku_all.m3u non trovato, skip aggiornamento Roku.')

    if pluto_path.exists():
        pluto_channels = parse_m3u(pluto_path)
        pluto_idx = build_index_by_tvgid(pluto_channels)
        print(f'PlutoTV: {len(pluto_channels)} canali caricati ({len(pluto_idx)} con tvg-id)')
    else:
        print('AVVISO: plutotv.m3u non trovato, skip aggiornamento PlutoTV.')

    current_channels = parse_m3u(streaming_path)
    print(f'streaming.m3u: {len(current_channels)} canali correnti')

    present_ids = {c['tvg_id'] for c in current_channels if c['tvg_id']}

    updated_count = 0
    output_entries = []

    for ch in current_channels:
        tid = ch['tvg_id']
        src = source_for_tvgid(tid)
        group_m = RE_GROUP.search(ch['extinf'])
        current_group = group_m.group(1) if group_m else ''
        orphans = get_orphan_prefix(ch['raw_lines'])

        if src == 'samsung' and tid in samsung_idx:
            new_extinf = update_extinf(ch['extinf'], samsung_idx[tid], current_group)
            new_url = samsung_idx[tid]['url']
            if new_extinf != ch['extinf'] or new_url != ch['url']:
                updated_count += 1
            output_entries.append(('updated', new_extinf, new_url, orphans))

        elif src == 'roku' and tid in roku_idx:
            new_extinf = update_extinf(ch['extinf'], roku_idx[tid], current_group)
            new_url = roku_idx[tid]['url']
            if new_extinf != ch['extinf'] or new_url != ch['url']:
                updated_count += 1
            output_entries.append(('updated', new_extinf, new_url, orphans))

        elif tid in pluto_idx:
            # Pluto: aggiorna SOLO URL, mantiene extinf intatto (tvg-id, nome, logo, group)
            new_url = pluto_idx[tid]['url']
            if new_url != ch['url']:
                updated_count += 1
            output_entries.append(('updated', ch['extinf'], new_url, orphans))

        else:
            output_entries.append(('raw', ch['raw_lines']))

    new_channels = []

    for tid, ch in samsung_idx.items():
        if tid not in present_ids:
            extinf = new_extinf_for_new_channel(ch['extinf'])
            new_channels.append(('updated', extinf, ch['url'], []))
            present_ids.add(tid)

    for tid, ch in roku_idx.items():
        if tid not in present_ids:
            extinf = new_extinf_for_new_channel(ch['extinf'])
            new_channels.append(('updated', extinf, ch['url'], []))
            present_ids.add(tid)

    for tid, ch in pluto_idx.items():
        if tid not in present_ids:
            extinf = new_extinf_for_new_channel(ch['extinf'])
            new_channels.append(('updated', extinf, ch['url'], []))
            present_ids.add(tid)

    all_entries = output_entries + new_channels
    out_lines = ['#EXTM3U']

    for entry in all_entries:
        if entry[0] == 'raw':
            out_lines.extend(entry[1])
        else:
            _, extinf, url, orphans = entry
            out_lines.extend(orphans)
            out_lines.append(extinf)
            out_lines.append(url)

    streaming_path.write_text('\n'.join(out_lines) + '\n', encoding='utf-8')

    total_channels = len(output_entries) + len(new_channels)
    print(f'\n── Riepilogo ────────────────────────────────')
    print(f'   Canali aggiornati:             {updated_count}')
    print(f'   Nuovi canali aggiunti:         {len(new_channels)}')
    print(f'   Totale canali in output:       {total_channels}')
    if new_channels:
        print(f'\n   Nuovi canali aggiunti nel gruppo "Nuovi":')
        for entry in new_channels:
            name = entry[1].rsplit(',', 1)[-1].strip()
            print(f'     + {name}')


if __name__ == '__main__':
    main()
