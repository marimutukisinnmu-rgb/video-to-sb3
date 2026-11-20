from __future__ import annotations

import json
import struct
import tempfile
import zlib
import unittest
import zipfile
from pathlib import Path

from video_to_sb3.container import VTSB3Writer
from video_to_sb3.scratch_sb3 import _rgb24_to_png, build_native_scratch_sb3


class NativeScratchSB3Tests(unittest.TestCase):
    def make_vtsb3(self, path: Path, frames: list[bytes], width: int = 480, height: int = 360):
        with VTSB3Writer(path, width, height, fps=30, keyframe_interval=2) as writer:
            for frame in frames:
                writer.write_frame(frame)

    def test_png_has_valid_signature_and_chunks(self):
        png = _rgb24_to_png(bytes([255, 0, 0] * 4), 2, 2)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        position = 8
        idat = bytearray()
        saw_iend = False
        while position < len(png):
            length = struct.unpack_from(">I", png, position)[0]
            kind = png[position + 4:position + 8]
            data_start = position + 8
            data = png[data_start:data_start + length]
            crc = struct.unpack_from(">I", png, data_start + length)[0]
            self.assertEqual(crc, zlib.crc32(kind + data) & 0xFFFFFFFF)
            if kind == b"IDAT":
                idat.extend(data)
            if kind == b"IEND":
                saw_iend = True
                break
            position = data_start + length + 4
        self.assertTrue(saw_iend)
        raw = zlib.decompress(bytes(idat))
        self.assertEqual(len(raw), 2 * (1 + 2 * 3))
        self.assertEqual(raw[0], 0)  # PNG row filter: None

    def test_builds_native_scratch_project_without_extensions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "tiny.vtsb3"
            output = root / "tiny.sb3"
            frame1 = bytes([10, 20, 30]) * (480 * 360)
            frame2 = bytearray(frame1)
            frame2[0:3] = bytes([200, 10, 40])
            self.make_vtsb3(source, [frame1, bytes(frame2), frame1])

            build_native_scratch_sb3(source, output)
            self.assertTrue(output.exists())
            with zipfile.ZipFile(output) as archive:
                self.assertIsNone(archive.testzip())
                project = json.loads(archive.read("project.json"))
                self.assertEqual(project["extensions"], [])
                self.assertEqual(len(project["targets"]), 2)
                sprite = project["targets"][1]
                self.assertEqual(len(sprite["costumes"]), 3)
                self.assertEqual(sprite["currentCostume"], 0)
                self.assertIn("event_whenflagclicked", {b["opcode"] for b in sprite["blocks"].values()})
                self.assertIn("control_repeat", {b["opcode"] for b in sprite["blocks"].values()})
                self.assertIn("looks_nextcostume", {b["opcode"] for b in sprite["blocks"].values()})
                self.assertEqual(len([n for n in archive.namelist() if n.endswith(".png")]), 2)

    def test_frame_sampling_and_loop_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "tiny.vtsb3"
            output = root / "sampled.sb3"
            frames = [bytes([i, 0, 0]) * (480 * 360) for i in range(4)]
            self.make_vtsb3(source, frames)
            build_native_scratch_sb3(source, output, every=2, loop=True)
            with zipfile.ZipFile(output) as archive:
                project = json.loads(archive.read("project.json"))
            sprite = project["targets"][1]
            self.assertEqual(len(sprite["costumes"]), 2)
            self.assertIn("control_forever", {b["opcode"] for b in sprite["blocks"].values()})

    def test_rejects_non_stage_resolution_and_preserves_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "wrong-size.vtsb3"
            output = root / "already-there.sb3"
            self.make_vtsb3(source, [b"\x00\x00\x00" * 2], width=2, height=1)
            output.write_bytes(b"keep")
            with self.assertRaises(ValueError):
                build_native_scratch_sb3(source, output, overwrite=True)
            self.assertEqual(output.read_bytes(), b"keep")

    def test_rejects_size_limit_and_cleans_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "tiny.vtsb3"
            output = root / "limited.sb3"
            frame = bytes([10, 20, 30]) * (480 * 360)
            self.make_vtsb3(source, [frame, frame])
            with self.assertRaises(ValueError):
                build_native_scratch_sb3(source, output, max_size_bytes=100)
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob("*.partial")), [])


if __name__ == "__main__":
    unittest.main()
