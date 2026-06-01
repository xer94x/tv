from pathlib import Path
import re
import sys

INPUT_FILE = Path("plutotv_it.m3u")
OUTPUT_FILE = Path("pluto.m3u")
BASE_URL = "https://plutotv.xer94x.workers.dev"

CHANNEL_ID_RE = re.compile(r'channel-id="([^"]+)"')

def build_url(channel_id: str) -> str:
    return f"{BASE_URL}/{channel_id}/index.m3u8"

def main():
    if not INPUT_FILE.exists():
        print(f"ERRORE: file non trovato: {INPUT_FILE}")
        sys.exit(1)

    lines = INPUT_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        print("ERRORE: playlist vuota")
        sys.exit(1)

    output_lines = []
    current_channel_id = None
    replaced = 0

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("#EXTINF"):
            output_lines.append(line)
            match = CHANNEL_ID_RE.search(line)
            current_channel_id = match.group(1) if match else None

            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()

                if next_line and not next_line.startswith("#"):
                    if current_channel_id:
                        output_lines.append(build_url(current_channel_id))
                        replaced += 1
                    else:
                        output_lines.append(lines[i + 1])
                    i += 2
                    continue

        else:
            output_lines.append(line)

        i += 1

    text = "\n".join(output_lines) + "\n"
    OUTPUT_FILE.write_text(text, encoding="utf-8")

    print(f"Canali aggiornati: {replaced}")
    print(f"Output scritto in: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
