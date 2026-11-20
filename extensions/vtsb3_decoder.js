/* VTSB3 v1 decoder. CommonJS exports are used by the Node test; browser API is also exposed. */
(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.VTSB3Decoder = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    const HEADER_SIZE = 40;
    const RECORD_SIZE = 14;
    const MAGIC = [0x56, 0x54, 0x53, 0x42, 0x33, 0x0d, 0x0a, 0x1a];
    const CRC_TABLE = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
        let c = n;
        for (let k = 0; k < 8; k++) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
        CRC_TABLE[n] = c >>> 0;
    }

    const crc32 = (bytes) => {
        let crc = 0xffffffff;
        for (let i = 0; i < bytes.length; i++) crc = CRC_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
        return (crc ^ 0xffffffff) >>> 0;
    };

    const parseHeader = (buffer) => {
        const bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
        if (bytes.length !== HEADER_SIZE) throw new Error('VTSB3ヘッダーが40バイトではありません。');
        for (let i = 0; i < MAGIC.length; i++) if (bytes[i] !== MAGIC[i]) throw new Error('VTSB3ファイルではありません。');
        const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
        const version = view.getUint16(8, true);
        const flags = view.getUint16(10, true);
        const width = view.getUint32(12, true);
        const height = view.getUint32(16, true);
        const fpsNum = view.getUint32(20, true);
        const fpsDen = view.getUint32(24, true);
        const keyframeInterval = view.getUint32(28, true);
        const frameCountBig = view.getBigUint64(32, true);
        if (version !== 1) throw new Error('未対応のVTSB3バージョン: ' + version);
        if (flags !== 0) throw new Error('未対応のヘッダーフラグ: ' + flags);
        if (!width || !height || !fpsNum || !fpsDen || !keyframeInterval || frameCountBig < 1n) {
            throw new Error('VTSB3ヘッダー内の値が不正です。');
        }
        if (frameCountBig > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error('フレーム数が大きすぎます。');
        const frameCount = Number(frameCountBig);
        const frameSize = width * height * 3;
        if (!Number.isSafeInteger(frameSize) || frameSize < 3) throw new Error('フレームサイズが不正です。');
        return {version, flags, width, height, fpsNum, fpsDen, keyframeInterval, frameCount, frameSize};
    };

    const indexFile = async (file, onProgress) => {
        const headerBytes = await file.slice(0, HEADER_SIZE).arrayBuffer();
        const header = parseHeader(headerBytes);
        const maxPayload = Math.ceil((header.frameSize / 3) * 7 + 65536);
        const records = new Array(header.frameCount);
        let offset = HEADER_SIZE;
        for (let i = 0; i < header.frameCount; i++) {
            if (offset + RECORD_SIZE > file.size) throw new Error('フレーム' + i + 'のレコードが途中で終了しています。');
            const recordBytes = await file.slice(offset, offset + RECORD_SIZE).arrayBuffer();
            const view = new DataView(recordBytes);
            const frameIndex = view.getUint32(0, true);
            const codec = view.getUint8(4);
            const flags = view.getUint8(5);
            const payloadSize = view.getUint32(6, true);
            const checksum = view.getUint32(10, true);
            if (frameIndex !== i) throw new Error('フレーム番号が不連続です: ' + frameIndex);
            if (codec > 3) throw new Error('未対応のCodec ID: ' + codec);
            if (flags !== 0) throw new Error('未対応のフレームフラグ: ' + flags);
            if (!payloadSize || payloadSize > maxPayload || offset + RECORD_SIZE + payloadSize > file.size) {
                throw new Error('フレーム' + i + 'のpayloadサイズが不正です。');
            }
            records[i] = {index: i, codec, checksum, offset: offset + RECORD_SIZE, size: payloadSize};
            offset += RECORD_SIZE + payloadSize;
            if (onProgress && (i === header.frameCount - 1 || i % 60 === 0)) onProgress(i + 1, header.frameCount);
        }
        if (offset !== file.size) throw new Error('最終フレームの後ろに余分なデータがあります。');
        return {header, records};
    };

    const inflateZlib = async (payload) => {
        if (typeof DecompressionStream === 'undefined') throw new Error('このブラウザーはDecompressionStreamに対応していません。');
        const stream = new Blob([payload]).stream().pipeThrough(new DecompressionStream('deflate'));
        const chunks = [];
        const reader = stream.getReader();
        let length = 0;
        while (true) {
            const item = await reader.read();
            if (item.done) break;
            chunks.push(item.value);
            length += item.value.length;
        }
        const output = new Uint8Array(length);
        let cursor = 0;
        for (const chunk of chunks) { output.set(chunk, cursor); cursor += chunk.length; }
        return output;
    };

    const decodeRle = (bytes, expectedSize) => {
        if (!bytes.length || bytes.length % 7 !== 0) throw new Error('RLEデータの長さが不正です。');
        const output = new Uint8Array(expectedSize);
        let cursor = 0;
        for (let i = 0; i < bytes.length; i += 7) {
            const view = new DataView(bytes.buffer, bytes.byteOffset + i, 7);
            const run = view.getUint32(0, true);
            if (!run || run > (expectedSize - cursor) / 3) throw new Error('RLEの連続長が不正です。');
            const r = bytes[i + 4], g = bytes[i + 5], b = bytes[i + 6];
            for (let p = 0; p < run; p++) {
                output[cursor++] = r;
                output[cursor++] = g;
                output[cursor++] = b;
            }
        }
        if (cursor !== expectedSize) throw new Error('RLE展開サイズが一致しません。');
        return output;
    };

    const decodePayload = async (codec, payload, previousFrame, frameSize, inflate = inflateZlib) => {
        const expanded = await inflate(payload);
        let data;
        if (codec === 0 || codec === 2) {
            if (expanded.length !== frameSize) throw new Error('展開サイズが一致しません。');
            data = expanded;
        } else if (codec === 1 || codec === 3) {
            data = decodeRle(expanded, frameSize);
        } else {
            throw new Error('未対応のCodec ID: ' + codec);
        }
        if (codec === 0 || codec === 1) return data;
        if (!previousFrame || previousFrame.length !== frameSize) throw new Error('差分フレームの直前フレームがありません。');
        const output = new Uint8Array(frameSize);
        for (let i = 0; i < frameSize; i++) output[i] = previousFrame[i] ^ data[i];
        return output;
    };

    return {HEADER_SIZE, RECORD_SIZE, crc32, parseHeader, indexFile, inflateZlib, decodeRle, decodePayload};
}));
