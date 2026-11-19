from __future__ import annotations

import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from video_to_sb3.container import (
    ContainerError,
    HEADER_SIZE,
    VTSB3Reader,
    VTSB3Writer,
)


class ContainerTests(unittest.TestCase):
    def make_frames(self):
        first = b"\x10\x20\x30" * 6
        second = bytearray(first)
        second[0:3] = b"\xaa\xbb\xcc"
        third = b"\x00\x00\x00" * 6
        return [first, bytes(second), third]

    def test_writer_reader_round_trip(self):
        frames = self.make_frames()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.vtsb3"
            writer = VTSB3Writer(path, 3, 2, fps=Fraction(30, 1), keyframe_interval=2)
            for frame in frames:
                writer.write_frame(frame)
            stats = writer.finish()

            self.assertEqual(stats.frame_count, len(frames))
            self.assertGreater(path.stat().st_size, HEADER_SIZE)
            with VTSB3Reader(path) as reader:
                self.assertEqual(reader.header.width, 3)
                self.assertEqual(reader.header.height, 2)
                self.assertEqual(reader.header.fps, Fraction(30, 1))
                self.assertEqual(reader.header.frame_count, len(frames))
                self.assertEqual(list(reader), frames)

    def test_crc_detects_modified_record(self):
        frames = self.make_frames()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "crc.vtsb3"
            writer = VTSB3Writer(path, 3, 2)
            writer.write_frame(frames[0])
            writer.finish()

            with path.open("r+b") as stream:
                stream.seek(HEADER_SIZE + 10)
                original = stream.read(1)
                stream.seek(HEADER_SIZE + 10)
                stream.write(bytes([original[0] ^ 0x01]))

            with VTSB3Reader(path) as reader:
                with self.assertRaisesRegex(ContainerError, "CRC32"):
                    list(reader)

    def test_truncated_payload_is_rejected(self):
        frames = self.make_frames()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "truncated.vtsb3"
            writer = VTSB3Writer(path, 3, 2)
            writer.write_frame(frames[0])
            writer.finish()
            path.write_bytes(path.read_bytes()[:-1])

            with VTSB3Reader(path) as reader:
                with self.assertRaises(ContainerError):
                    list(reader)

    def test_empty_writer_does_not_leave_valid_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.vtsb3"
            writer = VTSB3Writer(path, 3, 2)
            with self.assertRaises(ContainerError):
                writer.finish()
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
