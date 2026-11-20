"""Video-to-SB3 conversion, restoration, and native Scratch project building."""
from .container import VTSB3Header, VTSB3Reader, VTSB3Writer
from .converter import ConversionResult, VideoInfo, convert_video, probe_video
from .restore import RestorationError, RestorationResult, restore_to_mkv, restore_to_raw
from .player import DEFAULT_EXTENSION_URL, build_player_sb3, build_project_json
from .scratch_sb3 import ScratchSB3Error, build_native_scratch_sb3

__all__ = [
    "ConversionResult",
    "DEFAULT_EXTENSION_URL",
    "RestorationError",
    "RestorationResult",
    "ScratchSB3Error",
    "VTSB3Header",
    "VTSB3Reader",
    "VTSB3Writer",
    "VideoInfo",
    "build_native_scratch_sb3",
    "build_player_sb3",
    "build_project_json",
    "convert_video",
    "probe_video",
    "restore_to_mkv",
    "restore_to_raw",
]
__version__ = "0.4.0"
