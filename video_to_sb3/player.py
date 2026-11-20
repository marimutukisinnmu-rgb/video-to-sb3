"""Build a tiny TurboWarp project that hosts the external VTSB3 player."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

DEFAULT_EXTENSION_URL = "http://localhost:8000/extensions/vtsb3player.js"
PROJECT_SEMVER = "3.0.0"
_BLANK_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="480" height="360" '
    b'viewBox="0 0 480 360"></svg>'
)


def build_project_json(
    extension_url: str = DEFAULT_EXTENSION_URL,
    *,
    project_title: str = "VTSB3 Pen Player",
) -> dict[str, Any]:
    """Return a minimal Scratch 3 project with a blank stage and custom extension metadata."""
    if not isinstance(extension_url, str) or not extension_url.startswith(
        ("http://localhost:8000/", "https://extensions.turbowarp.org/")
    ):
        raise ValueError(
            "Unsandboxed extension URL must start with http://localhost:8000/ "
            "or https://extensions.turbowarp.org/."
        )

    asset_id = hashlib.md5(_BLANK_SVG).hexdigest()
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
            "name": "blank",
            "bitmapResolution": 1,
            "dataFormat": "svg",
            "assetId": asset_id,
            "md5ext": f"{asset_id}.svg",
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
    return {
        "targets": [stage],
        "monitors": [],
        "extensions": ["vtsb3player"],
        "extensionURLs": {"vtsb3player": extension_url},
        "meta": {
            "semver": PROJECT_SEMVER,
            "vm": "",
            "agent": project_title,
        },
    }


def build_player_sb3(
    output_path: str | Path,
    extension_url: str = DEFAULT_EXTENSION_URL,
    *,
    overwrite: bool = True,
) -> Path:
    """Build a small SB3 file; the video data is deliberately not embedded."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not overwrite:
        raise FileExistsError(output)
    project = build_project_json(extension_url)
    project_bytes = json.dumps(
        project, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")

    temp = output.with_suffix(output.suffix + ".tmp")
    try:
        with zipfile.ZipFile(
            temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            archive.writestr("project.json", project_bytes)
            archive.writestr(f"{hashlib.md5(_BLANK_SVG).hexdigest()}.svg", _BLANK_SVG)
        with zipfile.ZipFile(temp, "r") as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise zipfile.BadZipFile(f"Corrupt SB3 member: {bad_member}")
            json.loads(archive.read("project.json").decode("utf-8"))
        temp.replace(output)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    return output
