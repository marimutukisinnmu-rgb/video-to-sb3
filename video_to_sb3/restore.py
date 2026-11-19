"""VTSB3 restoration helpers: exact RGB24 extraction and lossless Matroska output."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .container import VTSB3Reader


class RestorationError(ValueError):
    """Raised when a VTSB3 file cannot be restored."""


ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class RestorationResult:
    input_path: str
    output_path: str
    width: int
    height: int
    fps_num: int
    fps_den: int
    frame_count: int
    bytes_written: int
    output_format: str


def _prepare_paths(
    input_path: str | Path,
    output_path: str | Path,
    overwrite: bool,
) -> tuple[Path, Path, Path]:
    source = Path(input_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()

    if not source.exists():
        raise FileNotFoundError(f"入力VTSB3ファイルがありません: {source}")
    if not source.is_file():
        raise ValueError(f"入力パスがファイルではありません: {source}")
    if source == output:
        raise ValueError("入力ファイルと出力ファイルに同じパスは指定できません。")
    if output.exists() and not overwrite:
        raise FileExistsError(f"出力ファイルがすでに存在します: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=output.stem + ".",
        suffix=output.suffix,
        dir=str(output.parent),
    )
    os.close(fd)
    return source, output, Path(temporary_name)


def _result(
    source: Path,
    output: Path,
    width: int,
    height: int,
    fps_num: int,
    fps_den: int,
    frame_count: int,
    output_format: str,
) -> RestorationResult:
    return RestorationResult(
        input_path=str(source),
        output_path=str(output),
        width=width,
        height=height,
        fps_num=fps_num,
        fps_den=fps_den,
        frame_count=frame_count,
        bytes_written=output.stat().st_size,
        output_format=output_format,
    )


def restore_to_raw(
    input_path: str | Path,
    output_path: str | Path,
    *,
    overwrite: bool = False,
    progress_callback: Optional[ProgressCallback] = None,
) -> RestorationResult:
    """Restore every frame as a byte-exact, headerless RGB24 stream."""
    source, output, temporary_output = _prepare_paths(
        input_path, output_path, overwrite
    )
    frame_count = 0
    try:
        with VTSB3Reader(source) as reader:
            header = reader.header
            with temporary_output.open("wb") as stream:
                for frame in reader.frames():
                    stream.write(frame)
                    frame_count += 1
                    if progress_callback is not None:
                        progress_callback(frame_count, header.frame_count)
                stream.flush()
                os.fsync(stream.fileno())

            if frame_count != header.frame_count:
                raise RestorationError(
                    f"復元フレーム数が一致しません: {frame_count} != {header.frame_count}"
                )

        os.replace(temporary_output, output)
        return _result(
            source, output, header.width, header.height,
            header.fps_num, header.fps_den, frame_count, "RGB24 raw",
        )
    except Exception:
        temporary_output.unlink(missing_ok=True)
        raise


def _resolve_ffmpeg(ffmpeg_path: Optional[str]) -> str:
    candidate = ffmpeg_path or "ffmpeg"
    resolved = shutil.which(candidate)
    if resolved:
        return resolved

    possible_path = Path(candidate).expanduser()
    if possible_path.is_file():
        return str(possible_path.resolve())

    raise FileNotFoundError(
        f"FFmpegが見つかりません: {candidate}。PATHまたは--ffmpegを確認してください。"
    )


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def restore_to_mkv(
    input_path: str | Path,
    output_path: str | Path,
    *,
    ffmpeg_path: Optional[str] = None,
    overwrite: bool = False,
    progress_callback: Optional[ProgressCallback] = None,
) -> RestorationResult:
    """Restore VTSB3 as a lossless FFV1 Matroska video (video only).

    VTSB3 v1 stores RGB video frames but no audio. The FFV1 output preserves
    the decoded RGB pixel values; it does not recreate the source audio.
    """
    output_candidate = Path(output_path)
    if output_candidate.suffix.lower() != ".mkv":
        raise ValueError("可逆動画の出力先には .mkv を指定してください。")

    ffmpeg = _resolve_ffmpeg(ffmpeg_path)
    source, output, temporary_output = _prepare_paths(
        input_path, output_path, overwrite
    )

    process: subprocess.Popen | None = None
    stderr_file = tempfile.TemporaryFile()
    frame_count = 0

    try:
        with VTSB3Reader(source) as reader:
            header = reader.header
            command = [
                ffmpeg,
                "-hide_banner",
                "-loglevel", "error",
                "-nostdin",
                "-y",
                "-f", "rawvideo",
                "-pixel_format", "rgb24",
                "-video_size", f"{header.width}x{header.height}",
                "-framerate", f"{header.fps_num}/{header.fps_den}",
                "-i", "pipe:0",
                "-map", "0:v:0",
                "-an",
                "-c:v", "ffv1",
                "-level", "3",
                "-pix_fmt", "bgr0",
                str(temporary_output),
            ]
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
                bufsize=0,
            )
            assert process.stdin is not None

            broken_pipe = False
            for frame in reader.frames():
                try:
                    process.stdin.write(frame)
                except BrokenPipeError:
                    broken_pipe = True
                    break
                frame_count += 1
                if progress_callback is not None:
                    progress_callback(frame_count, header.frame_count)

            try:
                process.stdin.close()
            except BrokenPipeError:
                broken_pipe = True

            return_code = process.wait()
            stderr_file.seek(0)
            error_text = stderr_file.read().decode("utf-8", errors="replace").strip()

            if broken_pipe or return_code != 0:
                detail = error_text or f"終了コード {return_code}"
                raise RestorationError(
                    "FFmpegによるMKVエンコードに失敗しました: " + detail
                )
            if frame_count != header.frame_count:
                raise RestorationError(
                    f"復元フレーム数が一致しません: {frame_count} != {header.frame_count}"
                )

        os.replace(temporary_output, output)
        return _result(
            source, output, header.width, header.height,
            header.fps_num, header.fps_den, frame_count, "Matroska / FFV1",
        )
    except Exception:
        if process is not None:
            _stop_process(process)
        temporary_output.unlink(missing_ok=True)
        raise
    finally:
        stderr_file.close()
