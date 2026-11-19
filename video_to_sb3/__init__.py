"""Video-to-SB3 conversion and VTSB3 frame compression."""
from .container import VTSB3Header, VTSB3Reader, VTSB3Writer
from .converter import ConversionResult, VideoInfo, convert_video, probe_video
from .restore import RestorationError, RestorationResult, restore_to_mkv, restore_to_raw

__all__ = [
    "ConversionResult",
    "RestorationError",
    "RestorationResult",
    "VTSB3Header",
    "VTSB3Reader",
    "VTSB3Writer",
    "VideoInfo",
    "convert_video",
    "probe_video",
    "restore_to_mkv",
    "restore_to_raw",
]
__version__ = "0.2.0"
