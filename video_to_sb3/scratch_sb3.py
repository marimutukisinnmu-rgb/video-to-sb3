"""Build a native Scratch 3 project from a VTSB3 video.

The generated project contains one PNG costume per selected frame and uses only
standard Scratch blocks. It does not load external JavaScript or local files.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import tempfile
import uuid
import zipfile
import zlib
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

from .container import VTSB3Reader

STAGE_WIDTH = 480
STAGE_HEIGHT = 360
MAX_COSTUMES = 60_000
BLANK_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="480" height="360" '
    b'viewBox="0 0 480 360"></svg>'
)

ProgressCallback = Callable[[int, int, int], None]


class ScratchSB3Error(ValueError):
    """Raised when a native Scratch SB3 cannot be built."""


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def _rgb24_to_png(rgb: bytes, width: int, height: int, compression_level: int = 6) -> bytes:
    """Encode RGB24 data as a minimal valid PNG without third-party packages."""
    expected = width * height * 3
    if len(rgb) != expected:
        raise ScratchSB3Error(f"RGBデータのサイズが不正です: {len(rgb)} != {expected}")
    compressor = zlib.compressobj(compression_level)
    compressed_parts: list[bytes] = []
    row_bytes = width * 3
    for y in range(height):
        start = y * row_bytes
        # PNG filter type 0: no filtering. The outer SB3 ZIP stores PNGs directly.
        part = compressor.compress(b"\x00" + rgb[start:start + row_bytes])
        if part:
            compressed_parts.append(part)
    tail = compressor.flush()
    if tail:
        compressed_parts.append(tail)
    compressed = b"".join(compressed_parts)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", compressed)
        + _png_chunk(b"IEND", b"")
    )


def _new_id() -> str:
    return uuid.uuid4().hex


def _block(
    opcode: str,
    *,
    next_id: str | None = None,
    parent_id: str | None = None,
    inputs: dict[str, Any] | None = None,
    top_level: bool = False,
    x: int | None = None,
    y: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "opcode": opcode,
        "next": next_id,
        "parent": parent_id,
        "inputs": inputs or {},
        "fields": {},
        "shadow": False,
        "topLevel": top_level,
    }
    if top_level:
        result["x"] = x if x is not None else 40
        result["y"] = y if y is not None else 40
    return result


def _animation_blocks(frame_count: int, fps: Fraction, loop: bool) -> dict[str, Any]:
    """Create a compact green-flag script using repeat/forever + wait + next costume."""
    blocks: dict[str, Any] = {}
    hat_id = _new_id()
    blocks[hat_id] = _block("event_whenflagclicked", top_level=True)

    if frame_count <= 1:
        return blocks

    container_id = _new_id()
    wait_id = _new_id()
    next_costume_id = _new_id()
    duration = Fraction(1, 1) / fps
    duration_text = f"{float(duration):.10f}".rstrip("0").rstrip(".")

    if loop:
        container_opcode = "control_forever"
        container_inputs = {"SUBSTACK": [2, wait_id]}
    else:
        container_opcode = "control_repeat"
        container_inputs = {
            "TIMES": [1, [4, str(frame_count - 1)]],
            "SUBSTACK": [2, wait_id],
        }

    blocks[hat_id]["next"] = container_id
    blocks[container_id] = _block(
        container_opcode,
        parent_id=hat_id,
        inputs=container_inputs,
    )
    blocks[wait_id] = _block(
        "control_wait",
        next_id=next_costume_id,
        parent_id=container_id,
        inputs={"DURATION": [1, [4, duration_text]]},
    )
    blocks[next_costume_id] = _block(
        "looks_nextcostume",
        parent_id=wait_id,
    )
    return blocks


def build_native_scratch_sb3(
    input_path: str | Path,
    output_path: str | Path,
    *,
    every: int = 1,
    loop: bool = False,
    overwrite: bool = False,
    max_size_bytes: int | None = None,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    """Build an SB3 that plays VTSB3 frames using native Scratch costumes.

    Frames are embedded as PNG costumes. The project is compatible with the
    standard Scratch 3 runtime and TurboWarp; it does not use extensions.
    """
    source = Path(input_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"入力VTSB3ファイルがありません: {source}")
    if source == output:
        raise ScratchSB3Error("入力ファイルと出力ファイルに同じパスは指定できません。")
    if not isinstance(every, int) or isinstance(every, bool) or every < 1:
        raise ScratchSB3Error("everyは1以上の整数で指定してください。")
    if max_size_bytes is not None and max_size_bytes < 1:
        raise ScratchSB3Error("max_size_bytesは1以上で指定してください。")
    if output.exists() and not overwrite:
        raise FileExistsError(f"出力ファイルがすでに存在します: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=output.name + ".", suffix=".partial", dir=str(output.parent)
    )
    os.close(fd)
    temporary = Path(temp_name)

    try:
        with VTSB3Reader(source) as reader:
            header = reader.header
            if (header.width, header.height) != (STAGE_WIDTH, STAGE_HEIGHT):
                raise ScratchSB3Error(
                    f"現在のネイティブSB3版は480×360専用です。入力: {header.width}×{header.height}"
                )
            selected_count = (header.frame_count + every - 1) // every
            if selected_count > MAX_COSTUMES:
                raise ScratchSB3Error(
                    f"コスチューム数が上限を超えます: {selected_count:,} > {MAX_COSTUMES:,}。"
                    "--everyを大きくしてフレーム数を減らしてください。"
                )
            costumes: list[dict[str, Any]] = []
            included_assets: set[str] = set()
            selected_index = 0

            with zipfile.ZipFile(
                temporary,
                mode="w",
                compression=zipfile.ZIP_STORED,
                allowZip64=True,
            ) as archive:
                blank_id = hashlib.md5(BLANK_SVG).hexdigest()
                archive.writestr(f"{blank_id}.svg", BLANK_SVG)

                for frame_index, rgb in enumerate(reader.frames()):
                    if frame_index % every != 0:
                        continue
                    png = _rgb24_to_png(rgb, header.width, header.height)
                    asset_id = hashlib.md5(png).hexdigest()
                    filename = f"{asset_id}.png"
                    if filename not in included_assets:
                        archive.writestr(filename, png)
                        included_assets.add(filename)
                    costumes.append({
                        "name": f"frame_{selected_index + 1:06d}",
                        "bitmapResolution": 1,
                        "dataFormat": "png",
                        "assetId": asset_id,
                        "md5ext": filename,
                        "rotationCenterX": header.width / 2,
                        "rotationCenterY": header.height / 2,
                    })
                    selected_index += 1
                    if progress_callback is not None:
                        progress_callback(frame_index + 1, header.frame_count, selected_index)
                    if max_size_bytes is not None and temporary.stat().st_size > max_size_bytes:
                        raise ScratchSB3Error(
                            f"SB3が指定上限を超えました: {temporary.stat().st_size:,} > {max_size_bytes:,} bytes"
                        )

                if selected_index != selected_count:
                    raise ScratchSB3Error(
                        f"出力フレーム数が一致しません: {selected_index} != {selected_count}"
                    )

                stage = {
                    "isStage": True,
                    "name": "Stage",
                    "variables": {},
                    "lists": {},
                    "broadcasts": {},
                    "blocks": {},
                    "comments": {},
                    "currentCostume": 0,
                    "costumes": [{
                        "name": "backdrop1",
                        "bitmapResolution": 1,
                        "dataFormat": "svg",
                        "assetId": blank_id,
                        "md5ext": f"{blank_id}.svg",
                        "rotationCenterX": 240,
                        "rotationCenterY": 180,
                    }],
                    "sounds": [],
                    "volume": 100,
                    "layerOrder": 0,
                    "tempo": 60,
                    "videoTransparency": 50,
                    "videoState": "on",
                    "textToSpeechLanguage": None,
                }
                sprite = {
                    "isStage": False,
                    "name": "VTSB3 Video",
                    "variables": {},
                    "lists": {},
                    "broadcasts": {},
                    "blocks": _animation_blocks(selected_count, header.fps / every, loop),
                    "comments": {},
                    "currentCostume": 0,
                    "costumes": costumes,
                    "sounds": [],
                    "volume": 100,
                    "layerOrder": 1,
                    "visible": True,
                    "x": 0,
                    "y": 0,
                    "size": 100,
                    "direction": 90,
                    "draggable": False,
                    "rotationStyle": "all around",
                }
                project = {
                    "targets": [stage, sprite],
                    "monitors": [],
                    "extensions": [],
                    "meta": {
                        "semver": "3.0.0",
                        "vm": "",
                        "agent": "video-to-sb3 native Scratch builder",
                    },
                }
                project_bytes = json.dumps(
                    project, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
                archive.writestr("project.json", project_bytes)

        with zipfile.ZipFile(temporary, "r") as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise zipfile.BadZipFile(f"壊れたSB3メンバーです: {bad_member}")
            loaded = json.loads(archive.read("project.json").decode("utf-8"))
            if loaded.get("extensions") != []:
                raise ScratchSB3Error("ネイティブScratchプロジェクトに拡張が含まれています。")
            if len(loaded["targets"][1]["costumes"]) != selected_count:
                raise ScratchSB3Error("SB3内のコスチューム数が一致しません。")

        final_size = temporary.stat().st_size
        if max_size_bytes is not None and final_size > max_size_bytes:
            raise ScratchSB3Error(
                f"最終SB3サイズが指定上限を超えました: {final_size:,} > {max_size_bytes:,} bytes"
            )
        os.replace(temporary, output)
        return output
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
