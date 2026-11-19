"""FFmpeg-based video decoding and VTSB3 encoding pipeline."""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Callable, Optional
from .container import EncodingStats, VTSB3Writer

class ConversionError(RuntimeError):
    """Raised when video probing, decoding, or encoding fails."""

@dataclass(frozen=True)
class VideoInfo:
    path: str
    width: int
    height: int
    fps: float
    frame_count: int
    duration: float
    codec: str
    pixel_format: str

@dataclass(frozen=True)
class ConversionResult:
    output_path: str
    manifest_path: Optional[str]
    width: int
    height: int
    fps_num: int
    fps_den: int
    frame_count: int
    duration_seconds: float
    compression: dict

ProgressCallback = Callable[[int, Optional[int], float], None]

def _fraction(value: str) -> Fraction:
    if not value or value in ("N/A", "0/0"):
        return Fraction(0, 1)
    try:
        result = Fraction(value)
        return result if result >= 0 else Fraction(0, 1)
    except (ValueError, ZeroDivisionError):
        return Fraction(0, 1)

def _find_executable(name: str, explicit: Optional[str] = None) -> str:
    candidate = explicit or shutil.which(name)
    if not candidate:
        raise ConversionError(f"{name}が見つかりません。FFmpegをインストールし、PATHに追加してください。")
    return str(candidate)

def probe_video(input_path: str | Path, ffprobe_path: Optional[str] = None) -> VideoInfo:
    path = Path(input_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"入力動画がありません: {path}")
    if not path.is_file():
        raise ValueError(f"入力パスがファイルではありません: {path}")
    ffprobe = _find_executable("ffprobe", ffprobe_path)
    command = [
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate,r_frame_rate,nb_frames,codec_name,pix_fmt,duration:format=duration",
        "-of", "json", str(path),
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", check=False)
    if result.returncode != 0:
        raise ConversionError("FFprobeで動画情報を取得できませんでした: " + result.stderr.strip())
    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ConversionError("FFprobeのJSONを解析できませんでした。") from exc
    streams = metadata.get("streams") or []
    if not streams:
        raise ConversionError("入力ファイルに動画ストリームがありません。")
    stream = streams[0]
    width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    if width < 1 or height < 1:
        raise ConversionError("動画の幅または高さを取得できませんでした。")
    fps = _fraction(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "")
    if fps <= 0:
        raise ConversionError("動画のFPSを取得できませんでした。")
    duration_value = stream.get("duration")
    if duration_value in (None, "N/A"):
        duration_value = (metadata.get("format") or {}).get("duration", 0)
    try:
        duration = max(0.0, float(duration_value or 0))
    except (TypeError, ValueError):
        duration = 0.0
    try:
        frame_count = int(stream.get("nb_frames") or 0)
    except (TypeError, ValueError):
        frame_count = 0
    if frame_count < 1 and duration > 0:
        frame_count = round(float(fps) * duration)
    return VideoInfo(str(path), width, height, float(fps), max(0, frame_count),
                     duration, str(stream.get("codec_name") or "unknown"),
                     str(stream.get("pix_fmt") or "unknown"))

def _normalize_fps(value: Fraction | int | float | str) -> Fraction:
    try:
        fps = value if isinstance(value, Fraction) else Fraction(str(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"FPSの値が不正です: {value}") from exc
    if fps <= 0:
        raise ValueError("FPSは0より大きい値を指定してください。")
    if fps.numerator > 1_000_000 or fps.denominator > 1_000_000:
        raise ValueError("FPSの分子・分母が大きすぎます。")
    return fps

def build_video_filter(width: int, height: int, fps: Fraction, fit: str) -> str:
    if width < 1 or height < 1:
        raise ValueError("出力幅と高さは1以上である必要があります。")
    if fit not in {"contain", "cover", "stretch"}:
        raise ValueError("fitはcontain / cover / stretchのいずれかです。")
    fps_filter = f"fps={fps.numerator}/{fps.denominator}"
    if fit == "stretch":
        scale_filter = f"scale={width}:{height}:flags=lanczos"
    elif fit == "cover":
        scale_filter = (f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
                        f"crop={width}:{height}")
    else:
        scale_filter = (f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
                        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black")
    return f"{fps_filter},{scale_filter},setsar=1"

def _read_exact(stream, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)

def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)

def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".partial", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise

def convert_video(input_path: str | Path, output_path: str | Path, *,
                  width: int = 480, height: int = 360,
                  fps: Fraction | int | float | str = Fraction(30, 1),
                  fit: str = "contain", keyframe_interval: int = 30,
                  compression_level: int = 1, ffmpeg_path: Optional[str] = None,
                  ffprobe_path: Optional[str] = None, overwrite: bool = False,
                  write_manifest: bool = True,
                  progress_callback: Optional[ProgressCallback] = None) -> ConversionResult:
    """Decode a source video with FFmpeg and write a compressed VTSB3 file."""
    source = Path(input_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"入力動画がありません: {source}")
    if not source.is_file():
        raise ValueError(f"入力パスがファイルではありません: {source}")
    if source == output:
        raise ValueError("入力動画と出力ファイルに同じパスは指定できません。")
    if width < 1 or height < 1:
        raise ValueError("widthとheightは1以上である必要があります。")
    if width * height > 100_000_000:
        raise ValueError("出力解像度が大きすぎます。")
    if keyframe_interval < 1:
        raise ValueError("keyframe_intervalは1以上である必要があります。")
    if not 0 <= compression_level <= 9:
        raise ValueError("compression_levelは0〜9で指定してください。")
    target_fps = _normalize_fps(fps)
    if fit not in {"contain", "cover", "stretch"}:
        raise ValueError("fitはcontain / cover / stretchのいずれかです。")

    manifest = output.with_suffix(output.suffix + ".json")
    if output.exists() and not overwrite:
        raise FileExistsError(f"出力ファイルがすでに存在します: {output}")
    if write_manifest and manifest.exists() and not overwrite:
        raise FileExistsError(f"マニフェストがすでに存在します: {manifest}")

    ffmpeg = _find_executable("ffmpeg", ffmpeg_path)
    source_info = probe_video(source, ffprobe_path=ffprobe_path)
    video_filter = build_video_filter(width, height, target_fps, fit)
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(source),
               "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", video_filter,
               "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]

    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=output.name + ".", suffix=".partial", dir=str(output.parent))
    os.close(fd)
    temporary_output = Path(temporary_name)
    frame_size = width * height * 3
    estimated_frames = max(1, round(source_info.duration * float(target_fps))) if source_info.duration > 0 else None
    progress_total = estimated_frames or None
    process = None
    writer = None
    frame_count = 0
    started = time.perf_counter()
    last_progress = started
    stderr_file = tempfile.TemporaryFile()
    try:
        writer = VTSB3Writer(temporary_output, width=width, height=height,
                             fps=target_fps, keyframe_interval=keyframe_interval,
                             compression_level=compression_level)
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=stderr_file, bufsize=0)
        assert process.stdout is not None
        while True:
            frame = _read_exact(process.stdout, frame_size)
            if not frame:
                break
            if len(frame) != frame_size:
                raise ConversionError(f"FFmpegから不完全なフレームを受信しました: {len(frame)} / {frame_size} bytes")
            writer.write_frame(frame)
            frame_count += 1
            now = time.perf_counter()
            if progress_callback is not None:
                progress_callback(frame_count, progress_total, now - started)
            elif now - last_progress >= 1.0:
                rate = frame_count / max(0.001, now - started)
                progress_text = f"{frame_count:,}/{progress_total:,}" if progress_total else f"{frame_count:,}"
                print(f"\r変換中: {progress_text} frame | {rate:.1f} frame/s",
                      end="", file=sys.stderr, flush=True)
                last_progress = now
        process.stdout.close()
        return_code = process.wait()
        stderr_file.seek(0)
        ffmpeg_error = stderr_file.read().decode("utf-8", errors="replace").strip()
        if return_code != 0:
            raise ConversionError("FFmpegの動画デコードに失敗しました: " +
                                  (ffmpeg_error or f"終了コード {return_code}"))
        if frame_count < 1:
            raise ConversionError("FFmpegから動画フレームを取得できませんでした。")
        stats: EncodingStats = writer.finish()
        writer = None
        os.replace(temporary_output, output)
    except Exception:
        if process is not None:
            _stop_process(process)
        if writer is not None:
            writer.abort()
        try:
            temporary_output.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    finally:
        stderr_file.close()

    elapsed = max(0.001, time.perf_counter() - started)
    duration_seconds = frame_count / float(target_fps)
    output_size = output.stat().st_size
    compression = stats.to_dict()
    compression["output_file_bytes"] = output_size
    compression["encoding_seconds"] = elapsed
    compression["average_encode_fps"] = frame_count / elapsed

    manifest_path: Optional[str] = None
    if write_manifest:
        manifest_data = {
            "format": "VTSB3",
            "format_version": 1,
            "source": {
                "file": source.name, "width": source_info.width, "height": source_info.height,
                "fps": source_info.fps, "frame_count_estimate": source_info.frame_count,
                "duration_seconds": source_info.duration, "codec": source_info.codec,
                "pixel_format": source_info.pixel_format,
            },
            "video": {
                "file": output.name, "width": width, "height": height,
                "fps_num": target_fps.numerator, "fps_den": target_fps.denominator,
                "fps": float(target_fps), "frame_count": frame_count,
                "duration_seconds": duration_seconds, "fit": fit,
                "keyframe_interval": keyframe_interval,
                "compression_level": compression_level, "pixel_format": "RGB24",
            },
            "compression": compression,
        }
        _write_json_atomic(manifest, manifest_data)
        manifest_path = str(manifest)

    if progress_callback is None:
        print(f"\r完了: {frame_count:,} frames | {width}x{height} @ {float(target_fps):g} FPS" + " " * 24,
              file=sys.stderr)
    return ConversionResult(str(output), manifest_path, width, height,
                            target_fps.numerator, target_fps.denominator,
                            frame_count, duration_seconds, compression)
