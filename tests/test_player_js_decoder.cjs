const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const zlib = require('node:zlib');

const source = fs.readFileSync(path.join(__dirname, '..', 'extensions', 'vtsb3_decoder.js'), 'utf8');
const sandbox = {module: {exports: {}}, globalThis: {}, Blob, DecompressionStream};
vm.runInNewContext(source, sandbox, {filename: 'vtsb3_decoder.js'});
const decoder = sandbox.module.exports;
const inflate = async payload => new Uint8Array(zlib.inflateSync(Buffer.from(payload)));

function makeRle(rgb) {
    const parts = [];
    for (let i = 0; i < rgb.length; i += 3) {
        let run = 1;
        while (
            i + run * 3 < rgb.length &&
            run < 0xffffffff &&
            rgb[i] === rgb[i + run * 3] &&
            rgb[i + 1] === rgb[i + run * 3 + 1] &&
            rgb[i + 2] === rgb[i + run * 3 + 2]
        ) run++;
        const head = Buffer.alloc(4);
        head.writeUInt32LE(run);
        parts.push(head, Buffer.from(rgb.subarray(i, i + 3)));
        i += (run - 1) * 3;
    }
    return Buffer.concat(parts);
}

(async () => {
    const frame0 = Buffer.from([10, 20, 30, 10, 20, 30, 10, 20, 30]);
    const frame1 = Buffer.from([10, 20, 30, 90, 80, 70, 10, 20, 30]);
    const delta = Buffer.alloc(frame0.length);
    for (let i = 0; i < delta.length; i++) delta[i] = frame0[i] ^ frame1[i];

    const cases = [
        [0, frame0, null, frame0],
        [1, makeRle(frame0), null, frame0],
        [2, delta, frame0, frame1],
        [3, makeRle(delta), frame0, frame1]
    ];
    for (const [codec, raw, previous, expected] of cases) {
        const packed = zlib.deflateSync(raw);
        const decoded = await decoder.decodePayload(
            codec,
            new Uint8Array(packed),
            previous && new Uint8Array(previous),
            expected.length,
            inflate
        );
        assert.deepEqual(Buffer.from(decoded), expected);
    }

    assert.equal(
        decoder.crc32(new Uint8Array(Buffer.from('123456789'))),
        0xcbf43926
    );

    if (typeof DecompressionStream !== 'undefined') {
        const packed = new Uint8Array(zlib.deflateSync(frame0));
        const nativeDecoded = await decoder.decodePayload(0, packed, null, frame0.length);
        assert.deepEqual(Buffer.from(nativeDecoded), frame0);
    }

    const sourceVideo = process.env.VTSB3_TEST_FILE;
    if (sourceVideo) {
        const blob = new Blob([fs.readFileSync(sourceVideo)]);
        const indexed = await decoder.indexFile(blob);
        let previous = null;
        for (let i = 0; i < indexed.records.length; i++) {
            const record = indexed.records[i];
            const payload = new Uint8Array(
                await blob.slice(record.offset, record.offset + record.size).arrayBuffer()
            );
            const frame = await decoder.decodePayload(
                record.codec, payload, previous, indexed.header.frameSize, inflate
            );
            assert.equal(decoder.crc32(frame), record.checksum, 'CRC frame ' + i);
            previous = frame;
        }
        console.log('Decoded and CRC-checked ' + indexed.header.frameCount + ' real VTSB3 frames.');
    }

    console.log('JavaScript VTSB3 codec tests passed.');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
