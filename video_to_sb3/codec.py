"""Adaptive RGB24 keyframe and XOR-delta compression."""
from __future__ import annotations
import struct
import zlib
from enum import IntEnum
from typing import Optional

class CodecError(ValueError):
    """Raised when a frame or encoded payload is invalid."""

class FrameCodec(IntEnum):
    KEY_ZLIB_RAW = 0
    KEY_ZLIB_RLE = 1
    DELTA_ZLIB_XOR = 2
    DELTA_ZLIB_XOR_RLE = 3

_RLE_RECORD = struct.Struct("<I3s")
_MAX_RUN = 0xFFFFFFFF
_NUMPY = None
_NUMPY_LOOKED_UP = False

def _numpy_module():
    global _NUMPY, _NUMPY_LOOKED_UP
    if not _NUMPY_LOOKED_UP:
        _NUMPY_LOOKED_UP = True
        try:
            import numpy
            _NUMPY = numpy
        except ImportError:
            _NUMPY = None
    return _NUMPY

def validate_rgb24(frame: bytes | bytearray | memoryview) -> None:
    if not isinstance(frame, (bytes, bytearray, memoryview)):
        raise TypeError("RGB24フレームはbytes系で指定してください。")
    if len(frame) == 0 or len(frame) % 3 != 0:
        raise CodecError("RGB24フレームのサイズは3の倍数である必要があります。")

def xor_bytes(left: bytes, right: bytes) -> bytes:
    if len(left) != len(right):
        raise CodecError("XOR対象のフレームサイズが一致しません。")
    np = _numpy_module()
    if np is not None:
        a = np.frombuffer(left, dtype=np.uint8)
        b = np.frombuffer(right, dtype=np.uint8)
        return np.bitwise_xor(a, b).tobytes()
    return bytes(a ^ b for a, b in zip(left, right))

def rle_encode_rgb(data: bytes | bytearray | memoryview) -> bytes:
    """Encode consecutive equal RGB pixels as <uint32 run><RGB> records."""
    validate_rgb24(data)
    raw = bytes(data)
    np = _numpy_module()
    if np is not None:
        pixels = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        if len(pixels) == 1:
            starts = np.array([0], dtype=np.int64)
        else:
            boundaries = np.flatnonzero(np.any(pixels[1:] != pixels[:-1], axis=1)) + 1
            starts = np.empty(len(boundaries) + 1, dtype=np.int64)
            starts[0] = 0
            starts[1:] = boundaries
        ends = np.empty_like(starts)
        if len(starts) > 1:
            ends[:-1] = starts[1:]
        ends[-1] = len(pixels)
        lengths = ends - starts
        if int(lengths.max(initial=0)) > _MAX_RUN:
            raise CodecError("RLEの連続長が上限を超えています。")
        records = np.empty((len(starts), 7), dtype=np.uint8)
        records[:, :4] = lengths.astype("<u4", copy=False).view(np.uint8).reshape(-1, 4)
        records[:, 4:] = pixels[starts]
        return records.tobytes()

    output = bytearray()
    run_color = raw[:3]
    run_length = 1
    for offset in range(3, len(raw), 3):
        color = raw[offset:offset + 3]
        if color == run_color and run_length < _MAX_RUN:
            run_length += 1
            continue
        output.extend(_RLE_RECORD.pack(run_length, run_color))
        run_color = color
        run_length = 1
    output.extend(_RLE_RECORD.pack(run_length, run_color))
    return bytes(output)

def rle_decode_rgb(data: bytes, expected_size: Optional[int] = None) -> bytes:
    if len(data) == 0 or len(data) % _RLE_RECORD.size != 0:
        raise CodecError("RLEデータの長さが不正です。")
    output = bytearray()
    expected_pixels = expected_size // 3 if expected_size is not None else None
    decoded_pixels = 0
    for offset in range(0, len(data), _RLE_RECORD.size):
        run_length, color = _RLE_RECORD.unpack_from(data, offset)
        if run_length == 0:
            raise CodecError("RLEに長さ0のランがあります。")
        decoded_pixels += run_length
        if expected_pixels is not None and decoded_pixels > expected_pixels:
            raise CodecError("RLEの展開サイズが指定サイズを超えました。")
        output.extend(color * run_length)
    if expected_size is not None and len(output) != expected_size:
        raise CodecError(f"RLE展開サイズが一致しません: {len(output)} != {expected_size}")
    return bytes(output)

def _best_keyframe(frame: bytes, compression_level: int) -> tuple[FrameCodec, bytes]:
    best_codec = FrameCodec.KEY_ZLIB_RAW
    best_payload = zlib.compress(frame, compression_level)
    rle_payload = zlib.compress(rle_encode_rgb(frame), compression_level)
    if len(rle_payload) < len(best_payload):
        best_codec, best_payload = FrameCodec.KEY_ZLIB_RLE, rle_payload
    return best_codec, best_payload

def encode_frame(frame: bytes, previous_frame: Optional[bytes], frame_index: int,
                 keyframe_interval: int, compression_level: int = 1) -> tuple[FrameCodec, bytes]:
    """Choose the smallest keyframe or XOR-delta representation."""
    validate_rgb24(frame)
    if previous_frame is not None:
        validate_rgb24(previous_frame)
        if len(previous_frame) != len(frame):
            raise CodecError("前フレームと現在フレームのサイズが一致しません。")
    if frame_index < 0:
        raise ValueError("frame_indexは0以上である必要があります。")
    if keyframe_interval < 1:
        raise ValueError("keyframe_intervalは1以上である必要があります。")
    if not 0 <= compression_level <= 9:
        raise ValueError("compression_levelは0〜9で指定してください。")

    force_keyframe = previous_frame is None or frame_index == 0 or frame_index % keyframe_interval == 0
    key_codec, key_payload = _best_keyframe(frame, compression_level)
    if force_keyframe:
        return key_codec, key_payload

    delta = xor_bytes(frame, previous_frame)
    delta_payload = zlib.compress(delta, compression_level)
    delta_codec = FrameCodec.DELTA_ZLIB_XOR
    delta_rle_payload = zlib.compress(rle_encode_rgb(delta), compression_level)
    if len(delta_rle_payload) < len(delta_payload):
        delta_payload, delta_codec = delta_rle_payload, FrameCodec.DELTA_ZLIB_XOR_RLE
    if len(delta_payload) < len(key_payload):
        return delta_codec, delta_payload
    return key_codec, key_payload

def decode_frame_payload(codec: FrameCodec | int, payload: bytes,
                         previous_frame: Optional[bytes], frame_size: int) -> bytes:
    try:
        codec = FrameCodec(codec)
    except ValueError as exc:
        raise CodecError(f"未対応のフレームCodecです: {codec}") from exc
    if frame_size <= 0 or frame_size % 3:
        raise CodecError("フレームサイズが不正です。")
    max_uncompressed = max(frame_size, (frame_size // 3) * _RLE_RECORD.size)
    decompressor = zlib.decompressobj()
    try:
        decoded = decompressor.decompress(payload, max_uncompressed + 1)
        if len(decoded) > max_uncompressed or decompressor.unconsumed_tail:
            raise CodecError("圧縮データの展開サイズが上限を超えました。")
        decoded += decompressor.flush()
    except zlib.error as exc:
        raise CodecError(f"zlibデータが壊れています: {exc}") from exc
    if len(decoded) > max_uncompressed:
        raise CodecError("圧縮データの展開サイズが上限を超えました。")
    if not decompressor.eof:
        raise CodecError("zlibストリームが途中で終了しています。")
    if decompressor.unused_data:
        raise CodecError("zlibストリームの後ろに余分なデータがあります。")

    if codec in (FrameCodec.KEY_ZLIB_RAW, FrameCodec.DELTA_ZLIB_XOR):
        if len(decoded) != frame_size:
            raise CodecError(f"展開サイズが一致しません: {len(decoded)} != {frame_size}")
        frame_data = decoded
    else:
        frame_data = rle_decode_rgb(decoded, frame_size)

    if codec in (FrameCodec.KEY_ZLIB_RAW, FrameCodec.KEY_ZLIB_RLE):
        return frame_data
    if previous_frame is None:
        raise CodecError("最初のフレームを差分形式で復元することはできません。")
    if len(previous_frame) != frame_size:
        raise CodecError("前フレームのサイズが不正です。")
    return xor_bytes(previous_frame, frame_data)
