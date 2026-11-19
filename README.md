# video-to-sb3

動画をRGB24フレームへ変換し、RLEとフレーム差分を使って独自形式のVTSB3データに圧縮する前処理エンジンです。

この段階では、Scratchプロジェクト（SB3）や再生エンジンはまだ生成しません。動画データをSB3本体に埋め込まず、外部データとして分離するための基盤です。

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

## 出力ファイル

変換後は次の2ファイルが生成されます。

- output.vtsb3: 圧縮されたRGB動画データ
- output.vtsb3.json: 解像度、FPS、フレーム数、圧縮統計などのマニフェスト

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
from video_to_sb3 import VTSB3Reader, convert_video

result = convert_video(
    "input.mp4",
    "output.vtsb3",
    width=480,
    height=360,
    fps=30,
)

print(result.compression)

with VTSB3Reader("output.vtsb3") as reader:
    print(reader.header)
    first_frame = next(iter(reader))
    print(len(first_frame))  # 480 * 360 * 3
~~~

## 現在のスコープ

完了対象:
1. Python動画変換エンジン
2. RGB圧縮・差分データ生成

今後の工程:
3. 外部データのチャンク配信・読み込み
4. Pen専用Scratch/TurboWarpプレイヤー生成
5. SB3生成と再生ベンチマーク

SB3ファイル自体は3MB以下を目標とし、動画データは別ファイルとして扱う設計です。
