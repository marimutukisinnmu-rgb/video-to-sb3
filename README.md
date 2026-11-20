# video-to-sb3

動画をRGB24フレームへ変換し、RLEとXORフレーム差分を使ってVTSB3へ圧縮するPythonツールです。VTSB3の復元機能に加え、標準Scratchブロックだけで再生するネイティブSB3生成機能と、TurboWarpのPenレイヤーを使う外部プレイヤー試作を含みます。

## 必要環境

- Python 3.10以降
- FFmpeg / FFprobe（動画変換・MKV復元に必要）
- NumPy（任意。圧縮処理を高速化）
- Node.js 20以降（JavaScriptデコーダーのテスト用）

インストール:

\`\`\`powershell
py -m pip install -r requirements.txt
\`\`\`

## 動画変換・復元

\`\`\`powershell
py -m video_to_sb3 input.mp4 -o output.vtsb3
py -m video_to_sb3 restore output.vtsb3 -o restored.mkv
\`\`\`

VTSB3 v1には音声トラックがないため、復元されるのは映像のみです。

## 本家Scratch対応SB3を生成する

VTSB3ファイルから、標準Scratchブロックだけで動くSB3を作成できます。

\`\`\`powershell
py -m video_to_sb3 build-scratch output.vtsb3 -o output_scratch.sb3
\`\`\`

生成した \`output_scratch.sb3\` をScratch公式エディターの「ファイル → コンピューターから読み込む」で開き、緑の旗を押すと再生します。TurboWarpでも利用できる標準プロジェクト構成です。

オプション:

\`\`\`powershell
# 2フレームごとに1枚を採用して容量を抑える（再生FPSも半分になる）
py -m video_to_sb3 build-scratch output.vtsb3 -o output_scratch.sb3 --every 2

# 最後まで再生したら先頭に戻って繰り返す
py -m video_to_sb3 build-scratch output.vtsb3 -o output_scratch.sb3 --loop

# 出力が100MiBを超えたら中止
py -m video_to_sb3 build-scratch output.vtsb3 -o output_scratch.sb3 --max-size-mib 100
\`\`\`

### ネイティブScratch版の制限

- カスタム拡張、PenSkin内部API、ローカルHTTPサーバーは使いません。
- 各フレームをPNGコスチュームとしてSB3内に格納し、\`待つ → 次のコスチューム\` という標準ブロックで再生します。
- そのため、全フレームを含めるとSB3はVTSB3よりかなり大きくなる場合があります。従来の「SB3を3MiB以下にする」方式ではありません。
- \`--every\` でフレームを間引けます。間引くほど動きは粗くなります。
- 現在は480×360専用です。音声は含みません。
- 標準ブロックだけの構成を生成・検証していますが、実際のScratch公式エディターでの読み込みと再生は別途実機確認が必要です。

## TurboWarp専用Penプレイヤー

従来の外部VTSB3プレイヤーは**TurboWarp専用**です。Scratch公式サイトではカスタム拡張を実行できません。また、PenSkinの内部APIに直接アクセスするため、TurboWarpのレンダラー実装に依存します。

### 起動

リポジトリのルートでローカル拡張サーバーを起動:

\`\`\`powershell
py tools/serve_player.py
\`\`\`

TurboWarpを開く:

\`https://turbowarp.org/editor?extension=http%3A%2F%2Flocalhost%3A8000%2Fextensions%2Fvtsb3player.js\`

エディターで \`dist\\vtsb3_player.sb3\` を読み込み、VTSB3 Playerパネルから \`.vtsb3\` を選んで再生します。

## TurboWarpプレイヤーSB3再生成

\`\`\`powershell
py tools/build_player.py
\`\`\`

生成先は \`dist\\vtsb3_player.sb3\` です。動画データはSB3に含まれません。

## テスト

\`\`\`powershell
py -m compileall -q video_to_sb3 tools tests
py -m unittest discover -s tests -v
node --check extensions/vtsb3_decoder.js
node --check extensions/vtsb3player.js
node tests/test_player_js_decoder.cjs
\`\`\`
