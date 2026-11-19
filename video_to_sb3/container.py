"""VTSB3 binary container reader and writer."""
from __future__ import annotations
import os
import struct
import zlib
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import BinaryIO, Iterator
from .codec import CodecError, FrameCodec, encode_frame, decode_frame_payload

MAGIC = b"VTSB3\r\n\x1a"
FORMAT_VERSION = 1
HEADER_STRUCT = struct.Struct("<8sHHIIIIIQ")
FRAME_STRUCT = struct.Struct("<IBBII")
HEADER_SIZE = HEADER_STRUCT.size

class ContainerError(ValueError):
    """Raised when a VTSB3 file is invalid or incomplete."""

@dataclass(frozen=True)
class VTSB3Header:
    version: int
    flags: int
    width: int
    height: int
    fps_num: int
    fps_den: int
    keyframe_interval: int
    frame_count: int

    @property
    def fps(self) -> Fraction:
        return Fraction(self.fps_num, self.fps_den)

    @property
    def frame_size(self) -> int:
        return self.width * self.height * 3

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / float(self.fps)

@dataclass
class EncodingStats:
    frame_count: int = 0
    keyframes: int = 0
    delta_frames: int = 0
    rle_frames: int = 0
    raw_rgb_bytes: int = 0
    payload_bytes: int = 0
    record_bytes: int = 0

    @property
    def total_file_bytes(self) -> int:
        return HEADER_SIZE + self.record_bytes

    @property
    def compression_ratio(self) -> float:
        return self.raw_rgb_bytes / self.total_file_bytes if self.total_file_bytes else 0.0

    @property
    def percent_saved(self) -> float:
        if not self.raw_rgb_bytes:
            return 0.0
        return (1.0 - self.total_file_bytes / self.raw_rgb_bytes) * 100.0

    def to_dict(self) -> dict:
        return {
            "frame_count": self.frame_count,
            "keyframes": self.keyframes,
            "delta_frames": self.delta_frames,
            "rle_frames": self.rle_frames,
            "raw_rgb_bytes": self.raw_rgb_bytes,
            "payload_bytes": self.payload_bytes,
            "record_bytes": self.record_bytes,
            "total_file_bytes": self.total_file_bytes,
            "compression_ratio": self.compression_ratio,
            "percent_saved": self.percent_saved,
        }

def _make_header(width: int, height: int, fps_num: int, fps_den: int,
                 keyframe_interval: int, frame_count: int) -> bytes:
    if width < 1 or height < 1:
        raise ContainerError("動画の幅と高さは1以上である必要があります。")
    if fps_num < 1 or fps_den < 1:
        raise ContainerError("FPSの分子と分母は1以上である必要があります。")
    if keyframe_interval < 1 or frame_count < 0:
        raise ContainerError("キーフレーム間隔またはフレーム数が不正です。")
    return HEADER_STRUCT.pack(MAGIC, FORMAT_VERSION, 0, width, height,
                              fps_num, fps_den, keyframe_interval, frame_count)

def _read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)

class VTSB3Writer:
    """Write compressed RGB24 frames to a VTSB3 file."""

    def __init__(self, path: str | Path, width: int, height: int,
                 fps: Fraction | int | float | str = Fraction(30, 1),
                 keyframe_interval: int = 30, compression_level: int = 1) -> None:
        self.path = Path(path)
        self.width = int(width)
        self.height = int(height)
        self.fps = fps if isinstance(fps, Fraction) else Fraction(str(fps))
        self.keyframe_interval = int(keyframe_interval)
        self.compression_level = int(compression_level)
        if self.width < 1 or self.height < 1:
            raise ValueError("widthとheightは1以上である必要があります。")
        if self.fps <= 0:
            raise ValueError("FPSは0より大きい必要があります。")
        if self.keyframe_interval < 1:
            raise ValueError("keyframe_intervalは1以上である必要があります。")
        if not 0 <= self.compression_level <= 9:
            raise ValueError("compression_levelは0〜9で指定してください。")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w+b")
        self._file.write(_make_header(self.width, self.height, self.fps.numerator,
                                      self.fps.denominator, self.keyframe_interval, 0))
        self.stats = EncodingStats()
        self._previous_frame: bytes | None = None
        self._closed = False

    def write_frame(self, frame: bytes) -> None:
        if self._closed:
            raise RuntimeError("Writerはすでに終了しています。")
        expected_size = self.width * self.height * 3
        if len(frame) != expected_size:
            raise ValueError(f"フレームサイズが一致しません: {len(frame)} != {expected_size}")
        frame_index = self.stats.frame_count
        codec, payload = encode_frame(frame, self._previous_frame, frame_index,
                                      self.keyframe_interval, self.compression_level)
        crc = zlib.crc32(frame) & 0xFFFFFFFF
        record = FRAME_STRUCT.pack(frame_index, int(codec), 0, len(payload), crc)
        self._file.write(record)
        self._file.write(payload)
        self.stats.frame_count += 1
        self.stats.raw_rgb_bytes += expected_size
        self.stats.payload_bytes += len(payload)
        self.stats.record_bytes += len(record) + len(payload)
        if codec in (FrameCodec.KEY_ZLIB_RAW, FrameCodec.KEY_ZLIB_RLE):
            self.stats.keyframes += 1
        else:
            self.stats.delta_frames += 1
        if codec in (FrameCodec.KEY_ZLIB_RLE, FrameCodec.DELTA_ZLIB_XOR_RLE):
            self.stats.rle_frames += 1
        self._previous_frame = bytes(frame)

    def finish(self) -> EncodingStats:
        if self._closed:
            return self.stats
        if self.stats.frame_count < 1:
            self.abort()
            raise ContainerError("動画にフレームがありません。")
        self._file.seek(0)
        self._file.write(_make_header(self.width, self.height, self.fps.numerator,
                                      self.fps.denominator, self.keyframe_interval,
                                      self.stats.frame_count))
        self._file.flush()
        os.fsync(self._file.fileno())
        self._file.close()
        self._closed = True
        return self.stats

    def abort(self) -> None:
        if not self._closed:
            try:
                self._file.close()
            finally:
                self._closed = True
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass

    def __enter__(self) -> "VTSB3Writer":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if exc_type is None:
            self.finish()
        else:
            self.abort()

class VTSB3Reader:
    """Read and verify frames from a VTSB3 file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._file = self.path.open("rb")
        try:
            raw_header = _read_exact(self._file, HEADER_SIZE)
            if len(raw_header) != HEADER_SIZE:
                raise ContainerError("VTSB3ヘッダーが途中で終わっています。")
            values = HEADER_STRUCT.unpack(raw_header)
            magic, version, flags, width, height, fps_num, fps_den, interval, count = values
            if magic != MAGIC:
                raise ContainerError("VTSB3ファイルではありません。")
            if version != FORMAT_VERSION:
                raise ContainerError(f"未対応のVTSB3バージョンです: {version}")
            if flags != 0:
                raise ContainerError(f"未対応のヘッダーフラグです: {flags}")
            if min(width, height, fps_num, fps_den, interval) < 1:
                raise ContainerError("ヘッダー内の数値が不正です。")
            if count < 1:
                raise ContainerError("フレーム数が0です。ファイルが未完成の可能性があります。")
            self.header = VTSB3Header(version, flags, width, height, fps_num,
                                      fps_den, interval, count)
        except Exception:
            self._file.close()
            raise

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()

    def __enter__(self) -> "VTSB3Reader":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def frames(self) -> Iterator[bytes]:
        previous: bytes | None = None
        frame_size = self.header.frame_size
        max_payload_size = (frame_size // 3) * 7 + 65536
        for expected_index in range(self.header.frame_count):
            raw_record = _read_exact(self._file, FRAME_STRUCT.size)
            if len(raw_record) != FRAME_STRUCT.size:
                raise ContainerError(f"フレーム{expected_index}のレコードが途中で終わっています。")
            frame_index, codec_value, flags, payload_size, expected_crc = FRAME_STRUCT.unpack(raw_record)
            if frame_index != expected_index:
                raise ContainerError(f"フレーム番号が不連続です: {frame_index} (expected {expected_index})")
            if flags != 0:
                raise ContainerError(f"未対応のフレームフラグです: {flags}")
            if payload_size < 1 or payload_size > max_payload_size:
                raise ContainerError(f"フレーム{expected_index}のpayloadサイズが不正です。")
            payload = _read_exact(self._file, payload_size)
            if len(payload) != payload_size:
                raise ContainerError(f"フレーム{expected_index}のpayloadが途中で終わっています。")
            try:
                frame = decode_frame_payload(codec_value, payload, previous, frame_size)
            except CodecError as exc:
                raise ContainerError(f"フレーム{expected_index}を復元できません: {exc}") from exc
            if (zlib.crc32(frame) & 0xFFFFFFFF) != expected_crc:
                raise ContainerError(f"フレーム{expected_index}のCRC32が一致しません。")
            previous = frame
            yield frame
        if self._file.read(1):
            raise ContainerError("最終フレームの後ろに余分なデータがあります。")

    def __iter__(self) -> Iterator[bytes]:
        return self.frames()
