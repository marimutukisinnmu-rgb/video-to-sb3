from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from video_to_sb3.cli import main
from video_to_sb3.container import VTSB3Writer
from video_to_sb3.restore import restore_to_mkv, restore_to_raw


def make_video(path: Path):
    frames = [
        bytes((index, 20, 40, 255 - index, 60, 80) * 4)
        for index in range(6)
    ]
    with VTSB3Writer(path, 2, 4, fps=Fraction(30, 1), keyframe_interval=3) as writer:
        for frame in frames:
            writer.write_frame(frame)
    return frames


class RestoreTests(unittest.TestCase):
    def test_restore_to_raw_is_byte_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.vtsb3"
            output = root / "restored.rgb24"
            frames = make_video(source)

            result = restore_to_raw(source, output)

            self.assertEqual(output.read_bytes(), b"".join(frames))
            self.assertEqual(result.frame_count, len(frames))
            self.assertEqual(result.bytes_written, sum(map(len, frames)))
            self.assertEqual((result.width, result.height), (2, 4))
            self.assertEqual(result.output_format, "RGB24 raw")

    def test_restore_raw_does_not_overwrite_without_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.vtsb3"
            output = root / "restored.rgb24"
            make_video(source)
            output.write_bytes(b"keep-this")
            with self.assertRaises(FileExistsError):
                restore_to_raw(source, output)
            self.assertEqual(output.read_bytes(), b"keep-this")

    def test_restore_cli_raw(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.vtsb3"
            output = root / "restored.rgb24"
            frames = make_video(source)

            code = main(["restore", str(source), "-o", str(output)])

            self.assertEqual(code, 0)
            self.assertEqual(output.read_bytes(), b"".join(frames))


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpegがないためMKV統合テストをスキップ")
class RestoreFFmpegTests(unittest.TestCase):
    def test_restore_to_mkv_is_rgb_lossless(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.vtsb3"
            output = root / "restored.mkv"
            frames = make_video(source)

            result = restore_to_mkv(source, output)
            decoded = subprocess.run(
                [
                    shutil.which("ffmpeg"),
                    "-hide_banner", "-loglevel", "error",
                    "-i", str(output),
                    "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
                ],
                capture_output=True,
                check=True,
            ).stdout

            self.assertEqual(decoded, b"".join(frames))
            self.assertEqual(result.frame_count, len(frames))
            self.assertEqual(result.output_format, "Matroska / FFV1")


if __name__ == "__main__":
    unittest.main()
