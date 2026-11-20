"""Video-to-SB3 conversion, compression, restoration, and player building."""
from .container import VTSB3Header, VTSB3Reader, VTSB3Writer
from .converter import ConversionResult, VideoInfo, convert_video, probe_video
from .restore import RestorationError, RestorationResult, restore_to_mkv, restore_to_raw
from .player import DEFAULT_EXTENSION_URL, build_player_sb3, build_project_json

__all__ = [
    "ConversionResult",
    "DEFAULT_EXTENSION_URL",
    "RestorationError",
    "RestorationResult",
    "VTSB3Header",
    "VTSB3Reader",
    "VTSB3Writer",
    "VideoInfo",
    "build_player_sb3",
    "build_project_json",
    "convert_video",
    "probe_video",
    "restore_to_mkv",
    "restore_to_raw",
]
__version__ = "0.3.0"
