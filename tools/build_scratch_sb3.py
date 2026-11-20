from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from video_to_sb3.cli import build_scratch_main

if __name__ == "__main__":
    raise SystemExit(build_scratch_main(sys.argv[1:]))
