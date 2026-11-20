(function (Scratch) {
    'use strict';
    if (!Scratch.extensions.unsandboxed) {
        throw new Error('VTSB3 Player requires an unsandboxed extension. Load it from http://localhost:8000/.');
    }

    const vm = Scratch.vm;
    const runtime = vm.runtime;
    const DECODER_URL = 'http://localhost:8000/extensions/vtsb3_decoder.js';

    const loadDecoder = () => new Promise((resolve, reject) => {
        if (window.VTSB3Decoder) return resolve(window.VTSB3Decoder);
        const existing = document.querySelector('script[data-vtsb3-decoder="1"]');
        if (existing) {
            existing.addEventListener('load', () => resolve(window.VTSB3Decoder), {once: true});
            existing.addEventListener('error', () => reject(new Error('VTSB3デコーダーを読み込めません。')), {once: true});
            return;
        }
        const script = document.createElement('script');
        script.src = DECODER_URL;
        script.async = true;
        script.dataset.vtsb3Decoder = '1';
        script.onload = () => window.VTSB3Decoder ? resolve(window.VTSB3Decoder) : reject(new Error('デコーダーAPIが見つかりません。'));
        script.onerror = () => reject(new Error('VTSB3デコーダーを読み込めません。'));
        document.head.appendChild(script);
    });

    class VTSB3Player {
        constructor () {
            this.decoderPromise = loadDecoder();
            this.file = null;
            this.indexed = null;
            this.currentFrame = -1;
            this.previousFrame = null;
            this.playing = false;
            this.penSkin = null;
            this.penSkinId = -1;
            this.penDrawableId = -1;
            this.panel = null;
            this.statusElement = null;
            this.fileElement = null;
            this.progressElement = null;
            this.fpsElement = null;
            this._mountPanel();
        }

        getInfo () {
            return {
                id: 'vtsb3player',
                name: 'VTSB3 Player',
                color1: '#4C97FF',
                color2: '#3373CC',
                blocks: [
                    {opcode: 'openFile', blockType: Scratch.BlockType.COMMAND, text: 'VTSB3ファイルを開く'},
                    {opcode: 'play', blockType: Scratch.BlockType.COMMAND, text: '動画を再生'},
                    {opcode: 'pause', blockType: Scratch.BlockType.COMMAND, text: '一時停止'},
                    {opcode: 'stop', blockType: Scratch.BlockType.COMMAND, text: '停止'},
                    {opcode: 'getStatus', blockType: Scratch.BlockType.REPORTER, text: 'プレイヤー状態'},
                    {opcode: 'getFrame', blockType: Scratch.BlockType.REPORTER, text: '現在のフレーム'}
                ]
            };
        }

        _mountPanel () {
            if (typeof document === 'undefined' || document.getElementById('vtsb3-player-panel')) return;
            const panel = document.createElement('section');
            panel.id = 'vtsb3-player-panel';
            panel.style.cssText = 'position:fixed;z-index:2147483000;top:12px;right:12px;width:270px;padding:12px;border:1px solid #64748b;border-radius:10px;background:#111827;color:#f8fafc;font:13px/1.45 system-ui,sans-serif;box-shadow:0 4px 18px #0006;';
            const title = document.createElement('div');
            title.textContent = 'VTSB3 Pen Player';
            title.style.cssText = 'font-weight:700;font-size:15px;margin-bottom:8px;';
            const file = document.createElement('div');
            file.textContent = '動画ファイル未選択';
            file.style.cssText = 'overflow-wrap:anywhere;color:#cbd5e1;margin-bottom:7px;';
            const status = document.createElement('div');
            status.textContent = 'VTSB3ファイルを選択してください';
            status.style.cssText = 'min-height:20px;margin-bottom:8px;';
            const progress = document.createElement('div');
            progress.textContent = '';
            progress.style.cssText = 'color:#93c5fd;min-height:18px;margin-bottom:7px;';
            const fps = document.createElement('div');
            fps.textContent = '';
            fps.style.cssText = 'color:#a7f3d0;min-height:18px;margin-bottom:8px;';
            const row = document.createElement('div');
            row.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;';
            const makeButton = (label, handler) => {
                const button = document.createElement('button');
                button.type = 'button';
                button.textContent = label;
                button.style.cssText = 'border:0;border-radius:6px;padding:7px 9px;background:#2563eb;color:white;cursor:pointer;font:inherit;';
                button.addEventListener('click', handler);
                row.appendChild(button);
                return button;
            };
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = '.vtsb3,application/octet-stream';
            input.style.display = 'none';
            input.addEventListener('change', async () => {
                const chosen = input.files && input.files[0];
                if (!chosen) return;
                try { await this._loadFile(chosen); }
                catch (error) { this._setStatus('エラー: ' + error.message); }
                input.value = '';
            });
            makeButton('VTSB3を選択', () => input.click());
            makeButton('▶ 再生', () => this.play().catch(error => this._setStatus('エラー: ' + error.message)));
            makeButton('一時停止', () => this.pause());
            makeButton('停止', () => this.stop());
            panel.append(title, file, status, progress, fps, row, input);
            document.body.appendChild(panel);
            this.panel = panel;
            this.fileElement = file;
            this.statusElement = status;
            this.progressElement = progress;
            this.fpsElement = fps;
        }

        _setStatus (message) {
            if (this.statusElement) this.statusElement.textContent = message;
        }

        async _loadFile (file) {
            this.pause();
            const decoder = await this.decoderPromise;
            this._setStatus('ヘッダーを確認中…');
            const indexed = await decoder.indexFile(file, (done, total) => {
                if (this.progressElement) this.progressElement.textContent =
                    'インデックス作成: ' + done.toLocaleString() + ' / ' + total.toLocaleString() + ' フレーム';
            });
            const h = indexed.header;
            if (h.width !== 480 || h.height !== 360) {
                throw new Error('現在は480×360専用です（ファイル: ' + h.width + '×' + h.height + '）。');
            }
            if (h.frameCount > 1000000) throw new Error('フレーム数が大きすぎます。');
            this.file = file;
            this.indexed = indexed;
            this.currentFrame = -1;
            this.previousFrame = null;
            this.fileElement.textContent = file.name + ' (' + (file.size / 1048576).toFixed(1) + ' MiB)';
            this._setStatus(h.width + '×' + h.height + ' / ' +
                (h.fpsNum / h.fpsDen).toFixed(3) + ' FPS / ' +
                h.frameCount.toLocaleString() + ' frames');
            if (this.progressElement) this.progressElement.textContent = '読み込み完了。再生できます。';
            this._ensurePenLayer();
        }

        _ensurePenLayer () {
            const renderer = vm.renderer;
            if (!renderer || !renderer.gl) throw new Error('TurboWarp WebGLレンダラーが利用できません。');
            if (!this.penSkin) {
                this.penSkinId = renderer.createPenSkin();
                this.penDrawableId = renderer.createDrawable('pen');
                renderer.updateDrawableSkinId(this.penDrawableId, this.penSkinId);
                this.penSkin = renderer._allSkins[this.penSkinId];
            }
            if (this.penSkin && typeof this.penSkin.setRenderQuality === 'function') this.penSkin.setRenderQuality(1);
            const size = this.penSkin && this.penSkin._size;
            if (!size || size[0] !== 480 || size[1] !== 360) {
                throw new Error('Penレイヤーが480×360ではありません。TurboWarpの標準ステージサイズで使用してください。');
            }
        }

        _drawFrame (rgb) {
            this._ensurePenLayer();
            const width = 480, height = 360;
            const rgba = new Uint8Array(width * height * 4);
            // WebGL texture rows start at the bottom. VTSB3 rows start at the top.
            for (let y = 0; y < height; y++) {
                const sourceRow = (height - 1 - y) * width * 3;
                const targetRow = y * width * 4;
                for (let x = 0; x < width; x++) {
                    const si = sourceRow + x * 3;
                    const di = targetRow + x * 4;
                    rgba[di] = rgb[si];
                    rgba[di + 1] = rgb[si + 1];
                    rgba[di + 2] = rgb[si + 2];
                    rgba[di + 3] = 255;
                }
            }
            const gl = vm.renderer.gl;
            gl.bindTexture(gl.TEXTURE_2D, this.penSkin._texture);
            gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
            gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
            gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
            gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, rgba);
            gl.bindTexture(gl.TEXTURE_2D, null);
            vm.renderer.dirty = true;
            runtime.requestRedraw();
        }

        async _decodeFrame (index) {
            const decoder = await this.decoderPromise;
            const record = this.indexed.records[index];
            const payload = new Uint8Array(await this.file.slice(record.offset, record.offset + record.size).arrayBuffer());
            const frame = await decoder.decodePayload(record.codec, payload, this.previousFrame, this.indexed.header.frameSize);
            if (decoder.crc32(frame) !== record.checksum) throw new Error('フレーム' + index + 'のCRC32が一致しません。');
            return frame;
        }

        async play () {
            if (!this.file || !this.indexed) throw new Error('先にVTSB3ファイルを選択してください。');
            if (this.playing) return;
            if (this.currentFrame >= this.indexed.header.frameCount - 1) {
                this.currentFrame = -1;
                this.previousFrame = null;
            }
            this.playing = true;
            const fps = this.indexed.header.fpsNum / this.indexed.header.fpsDen;
            const frameDuration = 1000 / fps;
            this._setStatus('再生中…');
            const tick = async () => {
                if (!this.playing) return;
                const started = performance.now();
                const next = this.currentFrame + 1;
                try {
                    const frame = await this._decodeFrame(next);
                    if (!this.playing) return;
                    this._drawFrame(frame);
                    this.currentFrame = next;
                    this.previousFrame = frame;
                    if (this.progressElement) this.progressElement.textContent =
                        'Frame ' + (next + 1) + ' / ' + this.indexed.header.frameCount;
                    const spent = performance.now() - started;
                    if (this.fpsElement) this.fpsElement.textContent =
                        '処理時間 ' + spent.toFixed(1) + ' ms / 目標 ' + fps.toFixed(1) + ' FPS';
                    if (this.currentFrame + 1 >= this.indexed.header.frameCount) {
                        this.playing = false;
                        this._setStatus('再生完了');
                        return;
                    }
                    setTimeout(tick, Math.max(0, frameDuration - spent));
                } catch (error) {
                    this.playing = false;
                    this._setStatus('再生エラー: ' + error.message);
                }
            };
            tick();
        }

        pause () {
            this.playing = false;
            if (this.file && this.indexed && this.currentFrame >= 0) this._setStatus('一時停止中');
        }

        stop () {
            this.playing = false;
            this.currentFrame = -1;
            this.previousFrame = null;
            if (this.penSkinId >= 0 && vm.renderer) vm.renderer.penClear(this.penSkinId);
            if (runtime) runtime.requestRedraw();
            if (this.file) this._setStatus('停止中');
        }

        openFile () {
            if (!this.panel) return;
            const input = this.panel.querySelector('input[type="file"]');
            if (input) input.click();
        }

        getStatus () { return this.playing ? 'playing' : (this.file ? 'ready' : 'empty'); }
        getFrame () { return this.currentFrame + 1; }
    }

    Scratch.extensions.register(new VTSB3Player());
}(Scratch));
