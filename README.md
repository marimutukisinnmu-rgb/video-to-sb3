# video-to-sb3

動画をRGB24フレームへ変換し、RLEとフレーム差分を使って独自形式のVTSB3データに圧縮する前処理エンジンです。VTSB3の復元機能と、TurboWarpで外部VTSB3ファイルをPenレイヤーに再生する小さなSB3プレイヤー試作を含みます。

動画データはSB3本体に埋め込まず、外部ファイルとして選択して読み込みます。

## 実装範囲

### 1. Python動画変換エンジン

- FFprobeで入力動画の情報を取得
- FFmpegで動画をフレーム単位にデコード
- RGB24（フルカラー）へ統一
- 出力FPSを指定可能（既定30 FPS）
- 出力解像度を指定可能（既定480 x 360）
- アスペクト比の処理にcontain / cover / stretchを選択可能
- フレームを全件RAMに保持せず、1フレームずつ圧縮して書き込み
- 途中失敗時は一時ファイルを破棄し、未完成ファイルを正式出力として残さない

動画フレーム取得のパイプライン設計は、既存のPySketchifyで使われているFFmpegのrawvideo / RGB24ストリーミング方式を参考にしています。描画処理そのものは流用していません。

### 2. RGB圧縮・差分データ生成

各フレームについて、次の方式を候補として圧縮し、より小さいデータを採用します。

| Codec ID | 種類 | 内容 |
|---:|---|---|
| 0 | KEY_ZLIB_RAW | RGB24フレームをそのままzlib圧縮 |
| 1 | KEY_ZLIB_RLE | 同じRGB画素の連続をRLE化してからzlib圧縮 |
| 2 | DELTA_ZLIB_XOR | 前フレームとのXOR差分をzlib圧縮 |
| 3 | DELTA_ZLIB_XOR_RLE | XOR差分をRLE化してからzlib圧縮 |

- 先頭フレームは必ずキーフレーム
- 既定では30フレームごとにキーフレームを強制
- それ以外のフレームはキーフレーム候補と差分候補を比較し、小さい方を採用
- CRC32で復元後のフレームを検証
- NumPyがインストールされている場合、RLEとXORの一部処理を高速化
- NumPyがなくても標準ライブラリだけで動作

圧縮率は動画の内容に依存します。細かいノイズや画面全体が毎フレーム変化する映像では、圧縮率が低くなる場合があります。

## 必要なもの

- Python 3.10以降
- FFmpeg
- FFprobe
- NumPy（任意。インストールすると一部処理が高速化します）

FFmpegとFFprobeの両方にPATHが通っていることを確認してください。

~~~powershell
ffmpeg -version
ffprobe -version
~~~

任意でNumPyをインストールできます。

~~~powershell
py -m pip install -r requirements.txt
~~~

## 使い方

標準設定（480 x 360 / 30 FPS / RGB24 / contain）で変換:

~~~powershell
py -m video_to_sb3 input.mp4 -o output.vtsb3
~~~

動画情報だけ確認:

~~~powershell
py -m video_to_sb3 input.mp4 --info
~~~

出力解像度とFPSを指定:

~~~powershell
py -m video_to_sb3 input.mp4 -o output.vtsb3 --width 480 --height 360 --fps 30
~~~

アスペクト比の処理:

~~~powershell
py -m video_to_sb3 input.mp4 -o output.vtsb3 --fit contain
~~~

- contain: 全体を表示し、余白を黒で埋める（既定）
- cover: 画面いっぱいに表示し、はみ出した部分を中央で切り取る
- stretch: 縦横比を無視して指定サイズに引き伸ばす

キーフレーム間隔と圧縮レベル:

~~~powershell
py -m video_to_sb3 input.mp4 -o output.vtsb3 --keyframe-interval 30 --compression-level 1
~~~

既存ファイルの上書き:

~~~powershell
py -m video_to_sb3 input.mp4 -o output.vtsb3 --overwrite
~~~

## 復元（デコード）

VTSB3を復元するには restore サブコマンドを使います。

### 可逆動画（推奨）

~~~powershell
py -m video_to_sb3 restore output.vtsb3 -o restored.mkv
~~~

- FFmpegを使ってMatroska（MKV）へ書き出します。
- 映像CodecはFFV1で、RGB画素値を保つ可逆出力です。
- VTSB3 v1には音声データがないため、復元されるのは映像のみです。
- 既存ファイルを上書きする場合は --overwrite を付けます。
- FFmpegの場所を明示する場合は --ffmpeg "C:\path\to\ffmpeg.exe" を指定できます。

### 生RGB24データ

FFmpegを使わず、全フレームを連続したRGB24バイト列として書き出すこともできます。

~~~powershell
py -m video_to_sb3 restore output.vtsb3 -o restored.rgb24
~~~

.rgb24 はヘッダーのない生データです。解像度・FPSは元のVTSB3ヘッダーに記録されている値を使ってください。

## 出力ファイル

変換後は次の2ファイルが生成されます。

- output.vtsb3: 圧縮されたRGB動画データ
- output.vtsb3.json: 解像度、FPS、フレーム数、圧縮統計などのマニフェスト

復元出力:
- restored.mkv: FFV1で可逆復元した映像
- restored.rgb24: ヘッダーなしのRGB24データ

SB3本体に動画フレームを埋め込む処理は、今回の実装範囲外です。

## VTSB3バイナリ仕様 v1

すべてリトルエンディアンです。

### ファイルヘッダー

構造体: <8sHHIIIIIQ>（40 bytes）

| フィールド | 型 | 説明 |
|---|---|---|
| magic | 8 bytes | VTSB3識別子 |
| version | uint16 | 1 |
| flags | uint16 | v1では0 |
| width | uint32 | 幅 |
| height | uint32 | 高さ |
| fps_num | uint32 | FPS分子 |
| fps_den | uint32 | FPS分母 |
| keyframe_interval | uint32 | 最大キーフレーム間隔 |
| frame_count | uint64 | フレーム数 |

### フレームレコード

構造体: <IBBII>（14 bytes）

| フィールド | 型 | 説明 |
|---|---|---|
| frame_index | uint32 | 0から始まる連番 |
| codec | uint8 | 上記Codec ID |
| flags | uint8 | v1では0 |
| payload_size | uint32 | 圧縮payloadのサイズ |
| crc32 | uint32 | 復元後RGB24データのCRC32 |

レコードの直後にpayloadが続きます。フレームのRGBデータは上から下、各行は左から右のRGB順です。

RLEレコードは <uint32 run_length><R><G><B> で構成されます。Deltaは前フレームとのバイト単位XORです。キーフレームから順番に復号すれば、各フレームを完全なRGB24データへ復元できます。

## Pythonからの利用

~~~python
from video_to_sb3 import (
    VTSB3Reader,
    convert_video,
    restore_to_mkv,
    restore_to_raw,
)

result = convert_video("input.mp4", "output.vtsb3", width=480, height=360, fps=30)
print(result.compression)

# 可逆MKVへの復元（FFmpegが必要）
restored = restore_to_mkv("output.vtsb3", "restored.mkv")
print(restored)

# またはヘッダーなしRGB24データへの復元（FFmpeg不要）
raw = restore_to_raw("output.vtsb3", "restored.rgb24")
print(raw.bytes_written)

# 低レベルAPIでフレームを1枚ずつ読むこともできます
with VTSB3Reader("output.vtsb3") as reader:
    print(reader.header)
    first_frame = next(iter(reader))
    print(len(first_frame))  # 480 * 360 * 3
~~~

## 現在のスコープ

完了対象:
1. Python動画変換エンジン
2. RGB圧縮・差分データ生成
3. VTSB3復元・デコード機能

今後の工程:
4. TurboWarpブラウザー上での表示確認・向き/色の検証
5. 30 FPSを目標にした再生ベンチマークと最適化
6. チャンク先読み・シーク・安定性の改善

SB3ファイル自体は3MB以下を目標とし、動画データは別ファイルとして扱う設計です。


## SB3 player generation (TurboWarp)

The player is a TurboWarp-only prototype. It updates the renderer Pen layer directly and keeps the VTSB3 video file external to the SB3.

### Install the player source bundle and build the SB3

After pulling the repository, extract the player source bundle into the repository root. It adds the extension, builder, local server, decoder verifier, and tests without embedding the VTSB3 video.

```powershell
git pull origin main
Expand-Archive -LiteralPath .\dist\vtsb3_player_sources.zip -DestinationPath .\ -Force
py tools/build_player.py
```

The generated project is `dist\vtsb3_player.sb3`. The checked-in SB3 is also only 1,269 bytes.

### Start the local extension server

In a separate PowerShell window, run:

```powershell
py tools/serve_player.py
```

Keep the server window open while using the project. It serves the extension at `http://localhost:8000/extensions/vtsb3player.js`.

### Open and play

1. Open this TurboWarp editor URL while the local server is running:

   `https://turbowarp.org/editor?extension=http%3A%2F%2Flocalhost%3A8000%2Fextensions%2Fvtsb3player.js`

2. In TurboWarp, load `dist\vtsb3_player.sb3` using **File → Load from your computer**.
3. Press the green flag, click **VTSB3を選択**, and select the `.vtsb3` file.

The prototype supports VTSB3 v1 at 480×360 RGB24. It indexes frame records, reads compressed payloads on demand, decodes all four codec IDs, validates CRC32, and updates the renderer's PenSkin texture. Video frames are not drawn from sprite costumes, bitmap backdrops, or stamps; the hidden controller sprite only hosts the project script.

### Limitations

- TurboWarp only; the custom extension is not compatible with the Scratch website.
- Requires the local extension server and a modern browser with `DecompressionStream`.
- VTSB3 v1 has no audio, so playback is video-only.
- The extension accesses TurboWarp renderer internals. This prototype is tied to TurboWarp's renderer implementation.
- JavaScript decoding and CRC32 have been checked against all 4,396 frames of the supplied VTSB3 file. Browser/Pen rendering and sustained 30 FPS still require a visual run-time benchmark on the target PC.
