from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from video_to_sb3.player import DEFAULT_EXTENSION_URL, build_player_sb3


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the external-data TurboWarp VTSB3 player SB3.")
    parser.add_argument("-o", "--output", type=Path, default=ROOT / "dist" / "vtsb3_player.sb3")
    parser.add_argument("--extension-url", default=DEFAULT_EXTENSION_URL)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    path = build_player_sb3(output, args.extension_url)
    print(f"SB3: {path}")
    print(f"Size: {path.stat().st_size:,} bytes")
    if path.stat().st_size >= 3 * 1024 * 1024:
        raise SystemExit("SB3 exceeds the 3 MiB target.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
