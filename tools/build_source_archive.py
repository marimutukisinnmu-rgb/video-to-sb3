from __future__ import annotations
import argparse
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "video_to_sb3/__init__.py",
    "video_to_sb3/__main__.py",
    "video_to_sb3/cli.py",
    "video_to_sb3/codec.py",
    "video_to_sb3/container.py",
    "video_to_sb3/converter.py",
    "video_to_sb3/player.py",
    "video_to_sb3/restore.py",
    "video_to_sb3/scratch_sb3.py",
    "requirements.txt",
    "extensions/vtsb3player.js",
    "extensions/vtsb3_decoder.js",
    "tools/build_player.py",
    "tools/build_scratch_sb3.py",
    "tools/serve_player.py",
    "tools/build_source_archive.py",
    "tests/test_player_builder.py",
    "tests/test_scratch_sb3.py",
    "tests/test_player_js_decoder.cjs",
    "README.md",
)

def build(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        with zipfile.ZipFile(
            temp, "w", compression=zipfile.ZIP_DEFLATED,
            compresslevel=9, allowZip64=True
        ) as archive:
            for relative in FILES:
                source = ROOT / relative
                if not source.is_file():
                    raise FileNotFoundError(source)
                archive.write(source, arcname=relative)
        with zipfile.ZipFile(temp, "r") as archive:
            corrupt = archive.testzip()
            if corrupt:
                raise zipfile.BadZipFile(f"Corrupt ZIP member: {corrupt}")
            for name in FILES:
                archive.read(name)
        temp.replace(path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    return path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create and verify the VTSB3 player source archive.")
    parser.add_argument("-o", "--output", type=Path, default=ROOT / "dist" / "vtsb3_player_sources.zip")
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    result = build(output)
    print(f"Sources ZIP: {result}")
    print(f"Size: {result.stat().st_size:,} bytes")
