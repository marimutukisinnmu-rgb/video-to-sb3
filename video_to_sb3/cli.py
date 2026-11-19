"""Command-line interface for the video-to-SB3 preprocessing stage."""
from __future__ import annotations
import argparse
import sys
from fractions import Fraction
from pathlib import Path
from .converter import ConversionError, convert_video, probe_video
from .restore import RestorationError, restore_to_mkv, restore_to_raw

def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("整数を指定してください。") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("1以上の値を指定してください。")
    return number

def _fps_value(value: str) -> Fraction:
    try:
        fps = Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise argparse.ArgumentTypeError("FPSは30、29.97、30000/1001のように指定してください。") from exc
    if fps <= 0:
        raise argparse.ArgumentTypeError("FPSは0より大きい値を指定してください。")
    return fps

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video-to-sb3",
        description="動画をRGB24フレームへ変換し、RLE・XOR差分圧縮したVTSB3データを生成します。",
    )
    parser.add_argument("input", type=Path, help="入力動画（MP4 / MOV / WebMなど）")
    parser.add_argument("-o", "--output", type=Path, help="出力ファイル（例: output.vtsb3）")
    parser.add_argument("--width", type=_positive_int, default=480, help="出力幅（既定: 480）")
    parser.add_argument("--height", type=_positive_int, default=360, help="出力高さ（既定: 360）")
    parser.add_argument("--fps", type=_fps_value, default=Fraction(30, 1), help="出力FPS（既定: 30）")
    parser.add_argument("--fit", choices=("contain", "cover", "stretch"), default="contain",
                        help="画面比率: contain=黒帯 / cover=中央クロップ / stretch=引き伸ばし")
    parser.add_argument("--keyframe-interval", type=_positive_int, default=30,
                        help="最大キーフレーム間隔（既定: 30フレーム）")
    parser.add_argument("--compression-level", type=int, choices=range(0, 10), default=1,
                        metavar="0-9", help="zlib圧縮レベル（既定: 1。高速寄り）")
    parser.add_argument("--ffmpeg", help="FFmpeg実行ファイルのパス")
    parser.add_argument("--ffprobe", help="FFprobe実行ファイルのパス")
    parser.add_argument("--overwrite", action="store_true", help="既存の出力ファイルを上書きする")
    parser.add_argument("--no-manifest", action="store_true", help="JSONマニフェストを生成しない")
    parser.add_argument("--info", action="store_true", help="変換せずに入力動画の情報だけを表示する")
    return parser

def restore_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="video-to-sb3 restore",
        description="VTSB3をRGB24データまたは可逆FFV1/MKV動画に復元します。",
    )
    parser.add_argument("input", type=Path, help="入力VTSB3ファイル")
    parser.add_argument("-o", "--output", type=Path, required=True,
                        help="出力先（.mkv または .rgb24）")
    parser.add_argument("--ffmpeg", help="FFmpeg実行ファイルのパス（.mkv出力時）")
    parser.add_argument("--overwrite", action="store_true", help="既存の出力ファイルを上書きする")
    args = parser.parse_args(argv)

    try:
        suffix = args.output.suffix.lower()
        if suffix == ".mkv":
            result = restore_to_mkv(
                args.input, args.output, ffmpeg_path=args.ffmpeg,
                overwrite=args.overwrite,
            )
        elif suffix in {".rgb24", ".rgb"}:
            result = restore_to_raw(
                args.input, args.output, overwrite=args.overwrite,
            )
        else:
            parser.error("出力拡張子は .mkv または .rgb24 を指定してください。")
            return 2

        print("復元完了")
        print(f"出力: {result.output_path}")
        print(f"形式: {result.output_format}")
        print(f"解像度: {result.width} x {result.height}")
        print(f"FPS: {result.fps_num}/{result.fps_den}")
        print(f"フレーム数: {result.frame_count:,}")
        print(f"サイズ: {result.bytes_written:,} bytes")
        if result.output_format == "Matroska / FFV1":
            print("音声: VTSB3には含まれていないため復元されません。")
        return 0
    except (RestorationError, OSError, ValueError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2

def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "restore":
        return restore_main(argv[1:])

    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.info and args.output is None:
        parser.error("--output を指定してください。")
    try:
        if args.info:
            info = probe_video(args.input, ffprobe_path=args.ffprobe)
            print(f"ファイル: {Path(info.path).name}")
            print(f"解像度: {info.width} x {info.height}")
            print(f"FPS: {info.fps:g}")
            print(f"フレーム数: {info.frame_count:,}" if info.frame_count else "フレーム数: 不明")
            print(f"長さ: {info.duration:.3f} 秒")
            print(f"映像Codec: {info.codec}")
            print(f"Pixel Format: {info.pixel_format}")
            return 0
        result = convert_video(
            args.input, args.output, width=args.width, height=args.height, fps=args.fps,
            fit=args.fit, keyframe_interval=args.keyframe_interval,
            compression_level=args.compression_level, ffmpeg_path=args.ffmpeg,
            ffprobe_path=args.ffprobe, overwrite=args.overwrite,
            write_manifest=not args.no_manifest,
        )
        print("\n変換結果")
        print(f"出力: {result.output_path}")
        if result.manifest_path:
            print(f"Manifest: {result.manifest_path}")
        print(f"フレーム数: {result.frame_count:,}")
        print(f"再生時間: {result.duration_seconds:.3f} 秒")
        print(f"キーフレーム: {result.compression['keyframes']:,}")
        print(f"差分フレーム: {result.compression['delta_frames']:,}")
        print(f"圧縮前RGB: {result.compression['raw_rgb_bytes']:,} bytes")
        print(f"出力サイズ: {result.compression['output_file_bytes']:,} bytes")
        print(f"圧縮率: {result.compression['compression_ratio']:.3f}x")
        print(f"サイズ削減率: {result.compression['percent_saved']:.2f}%")
        return 0
    except KeyboardInterrupt:
        print("\n中断しました。", file=sys.stderr)
        return 130
    except (ConversionError, OSError, ValueError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
