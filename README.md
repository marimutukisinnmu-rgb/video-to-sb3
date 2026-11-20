# video-to-sb3

動画をRGB24フレームへ変換し、RLEとXORフレーム差分を使ってVTSB3へ圧縮するPythonツールです。VTSB3の復元機能と、TurboWarpのPenレイヤーへ外部VTSB3ファイルを再生するSB3プレイヤー試作を含みます。

動画データはSB3本体に埋め込まず、ユーザーがローカルファイルを選択して読み込みます。SB3は小さなプレイヤー本体だけを持つ構成です。

## 必要環境

- Python 3.10以降
- FFmpeg / FFprobe（動画変換・MKV復元に必要）
- NumPy（任意）
- Node.js 20以降（JavaScriptデコーダーのテスト用）
- TurboWarpと最新のChrome / Edgeなど

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

## TurboWarp SB3プレイヤー

このプレイヤーは**TurboWarp専用**です。Scratch公式サイトではカスタム拡張を実行できません。また、PenSkinの内部APIに直接アクセスするため、TurboWarpのレンダラー実装に依存します。

### 1. リポジトリを更新

\`\`\`powershell
git pull origin main
\`\`\`

### 2. ローカル拡張サーバーを起動

プロジェクトのルートで:

\`\`\`powershell
py tools/serve_player.py
\`\`\`

サーバーは必ず \`http://localhost:8000/\` で起動します。TurboWarpはこのURLプレフィックスから読み込んだ拡張をUnsandboxedとして実行できるため、\`127.0.0.1\` や別ポートに変更しないでください。再生中もサーバーを終了しないでください。

### 3. TurboWarpを開く

\`https://turbowarp.org/editor?extension=http%3A%2F%2Flocalhost%3A8000%2Fextensions%2Fvtsb3player.js\`

この拡張はPenレイヤーの内部にアクセスするUnsandboxed拡張です。TurboWarpがロード確認を表示した場合は、内容を確認して許可してください。

### 4. SB3を読み込む

TurboWarpエディターで **ファイル → コンピューターから読み込む** を選び、\`dist\\vtsb3_player.sb3\` を開きます。

画面右上のVTSB3 Playerパネルで **VTSB3を選択** をクリックし、\`output.vtsb3\` を選択してから **再生** を押します。

### プレイヤーの仕様と制限

- VTSB3 v1、480×360 RGB24が対象です。
- ファイル全体はRAMに展開せず、フレームレコードだけをインデックス化します。各フレームのpayloadは再生時に読み込みます。
- 4種類のCodec IDをデコードし、復元後にCRC32を検証します。
- 画面描画にはTurboWarpのPenSkinテクスチャを使い、スプライトのコスチューム、スタンプ、ビットマップ背景には動画を描画しません。
- VTSB3 v1には音声がありません。
- 30 FPSを目標としますが、実際の速度はPCやブラウザーに依存します。長尺での再生性能は実機で確認してください。

## SB3再生成

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

実データの全フレーム検証は、環境変数 \`VTSB3_TEST_FILE\` に実際のファイルパスを指定して実行できます。

