from __future__ import annotations

import unittest

import video_to_sb3.codec as codec_module
from video_to_sb3.codec import (
    CodecError,
    FrameCodec,
    decode_frame_payload,
    encode_frame,
    rle_decode_rgb,
    rle_encode_rgb,
    xor_bytes,
)


class CodecTests(unittest.TestCase):
    def test_rle_round_trip(self):
        pixels = (
            b"\x00\x00\x00" * 12
            + b"\xff\x10\x20" * 3
            + b"\x01\x02\x03"
            + b"\x01\x02\x04" * 4
        )
        encoded = rle_encode_rgb(pixels)
        self.assertEqual(rle_decode_rgb(encoded, len(pixels)), pixels)

    def test_rle_round_trip_without_numpy_acceleration(self):
        old_numpy = codec_module._NUMPY
        old_looked_up = codec_module._NUMPY_LOOKED_UP
        try:
            codec_module._NUMPY = None
            codec_module._NUMPY_LOOKED_UP = True
            pixels = b"\x11\x22\x33" * 20 + b"\xaa\xbb\xcc" * 2
            encoded = rle_encode_rgb(pixels)
            self.assertEqual(rle_decode_rgb(encoded, len(pixels)), pixels)
        finally:
            codec_module._NUMPY = old_numpy
            codec_module._NUMPY_LOOKED_UP = old_looked_up

    def test_rle_rejects_invalid_input(self):
        with self.assertRaises(CodecError):
            rle_encode_rgb(b"\x00\x01")
        with self.assertRaises(CodecError):
            rle_decode_rgb(b"\x00\x00")

    def test_xor_round_trip(self):
        before = bytes(range(60))
        after = bytearray(before)
        after[3:6] = b"\xff\xee\xdd"
        delta = xor_bytes(before, bytes(after))
        self.assertEqual(xor_bytes(before, delta), bytes(after))

    def test_delta_frame_round_trip(self):
        previous = b"\x10\x20\x30" * 100
        current = bytearray(previous)
        current[30:33] = b"\x90\x80\x70"
        current = bytes(current)
        selected_codec, payload = encode_frame(
            current, previous, frame_index=1, keyframe_interval=30, compression_level=1
        )
        self.assertIn(
            selected_codec,
            (FrameCodec.DELTA_ZLIB_XOR, FrameCodec.DELTA_ZLIB_XOR_RLE,
             FrameCodec.KEY_ZLIB_RAW, FrameCodec.KEY_ZLIB_RLE),
        )
        restored = decode_frame_payload(selected_codec, payload, previous, len(current))
        self.assertEqual(restored, current)

    def test_keyframe_interval_forces_keyframe(self):
        previous = b"\x00\x00\x00" * 64
        current = b"\x00\x00\x00" * 64
        selected_codec, _ = encode_frame(
            current, previous, frame_index=30, keyframe_interval=30, compression_level=1
        )
        self.assertIn(selected_codec, (FrameCodec.KEY_ZLIB_RAW, FrameCodec.KEY_ZLIB_RLE))

    def test_delta_cannot_be_decoded_without_previous_frame(self):
        current = b"\x01\x02\x03" * 4
        selected_codec, payload = encode_frame(
            current, None, frame_index=0, keyframe_interval=30, compression_level=1
        )
        with self.assertRaises(CodecError):
            decode_frame_payload(
                FrameCodec.DELTA_ZLIB_XOR, payload, None, len(current)
            )


if __name__ == "__main__":
    unittest.main()
