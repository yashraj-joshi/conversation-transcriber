import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  createResampler, encodeWav, toInt16, concatInt16, mixToMono, floatToInt16, partRanges, TARGET_RATE,
} from '../wav.js';

test('WAV header is valid 16 kHz mono PCM', () => {
  const buf = encodeWav([new Int16Array([1, -2, 3]), new Int16Array([4]).buffer]);
  const v = new DataView(buf);
  const str = (o, n) => String.fromCharCode(...new Uint8Array(buf, o, n));
  assert.equal(buf.byteLength, 44 + 8);
  assert.equal(str(0, 4), 'RIFF');
  assert.equal(v.getUint32(4, true), 36 + 8);
  assert.equal(str(8, 8), 'WAVEfmt ');
  assert.equal(v.getUint16(20, true), 1);
  assert.equal(v.getUint16(22, true), 1);
  assert.equal(v.getUint32(24, true), 16000);
  assert.equal(v.getUint32(28, true), 32000);
  assert.equal(v.getUint16(34, true), 16);
  assert.equal(str(36, 4), 'data');
  assert.equal(v.getUint32(40, true), 8);
  assert.deepEqual(Array.from(new Int16Array(buf, 44)), [1, -2, 3, 4]);
});

test('5-minute part stays under the 18 MB upload cap', () => {
  const bytes = 44 + 300 * TARGET_RATE * 2;
  assert.ok(bytes < 18 * 1024 * 1024);
  assert.ok(Math.ceil(bytes / 3) * 4 < 25 * 1024 * 1024); // base64
});

for (const rate of [48000, 44100, 16000]) {
  test(`resampler ${rate} Hz -> 16 kHz keeps duration across calls`, () => {
    const r = createResampler(rate);
    let out = 0;
    for (let i = 0; i < 10; i++) out += r.process(new Float32Array(rate / 10).fill(0.5)).length;
    assert.ok(Math.abs(out - 16000) <= 1, `got ${out}`);
  });
}

test('resampler averages and clamps', () => {
  const r = createResampler(48000);
  const out = r.process(new Float32Array([1, 1, 1, -2, -2, -2]));
  assert.deepEqual(Array.from(out), [32767, -32768]);
  assert.equal(toInt16(0), 0);
  assert.throws(() => createResampler(8000));
});

test('concatInt16', () => {
  assert.deepEqual(Array.from(concatInt16([new Int16Array([1]), new Int16Array([2, 3])])), [1, 2, 3]);
});

test('mixToMono averages channels over a range', () => {
  const left = new Float32Array([1, 0.5, 0, -1]);
  const right = new Float32Array([0, 0.5, 1, -1]);
  assert.deepEqual(Array.from(mixToMono([left, right], 1, 4)), [0.5, 0.5, -1]);
  assert.deepEqual(Array.from(mixToMono([left], 0, 2)), [1, 0.5]);
});

test('floatToInt16', () => {
  assert.deepEqual(Array.from(floatToInt16(new Float32Array([0, 1, -1, 2]))), [0, 32767, -32768, 32767]);
});

test('partRanges splits into 5-minute parts', () => {
  const per = 300 * TARGET_RATE;
  assert.deepEqual(partRanges(per * 2 + 10, per), [[0, per], [per, per * 2], [per * 2, per * 2 + 10]]);
  assert.deepEqual(partRanges(per, per), [[0, per]]);
  assert.deepEqual(partRanges(0, per), []);
  assert.throws(() => partRanges(10, 0));
});
