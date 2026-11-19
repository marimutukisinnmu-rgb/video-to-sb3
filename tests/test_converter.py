from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from video_to_sb3.converter import build_video_filter, convert_video
from video_to_sb3.container import VTSB3Reader


class ConverterUnitTests(unittest.TestCase):
    def test_video_filter_modes(self):
        contain = build_video_filter(480, 360, Fraction(30, 1), "contain")
        cover = build_video_filter(480, 360, Fraction(30, 1), "cover")
        stretch = build_video_filter(480, 360, Fraction(30, 1), "stretch")
        self.assertIn("fps=30/1", contain)
        self.assertIn("pad=480:360", contain)
        self.assertIn("crop=480:360", cover)
        self.assertIn("scale=480:360:flags=lanczos", stretch)

    def test_invalid_fit_is_rejected(self):
        with self.assertRaises(ValueError):
            build_video_filter(480, 360, Fraction(30, 1), "invalid")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "FFmpeg / FFprobe がないため統合テストをスキップ")
class FFmpegIntegrationTests(unittest.TestCase):
    def test_synthetic_video_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.mp4"
            output = root / "output.vtsb3"

            command = [
                shutil.which("ffmpeg"),
                "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=size=64x48:rate=5",
                "-frames:v", "5",
                "-c:v", "mpeg4",
                "-y", str(source),
            ]
            created = subprocess.run(command, capture_output=True, text=True, check=False)
            if created.returncode != 0:
                self.skipTest("テスト用動画をFFmpegで生成できません: " + created.stderr[-500:])

            result = convert_video(
                source,
                output,
                width=32,
                height=24,
                fps=5,
                fit="contain",
                keyframe_interval=2,
                compression_level=1,
            )
            self.assertEqual(result.width, 32)
            self.assertEqual(result.height, 24)
            self.assertEqual(result.frame_count, 5)
            self.assertTrue(output.exists())
            self.assertTrue(Path(result.manifest_path).exists())

            with VTSB3Reader(output) as reader:
                frames = list(reader)
                self.assertEqual(len(frames), 5)
                self.assertEqual(len(frames[0]), 32 * 24 * 3)
                self.assertEqual(reader.header.fps, Fraction(5, 1))


if __name__ == "__main__":
    unittest.main()
