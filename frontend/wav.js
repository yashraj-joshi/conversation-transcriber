// Pure audio helpers (no DOM): resample to 16 kHz mono Int16 and encode WAV. Unit-tested with node --test.

export const TARGET_RATE = 16000;

/** Returns a stateful resampler: Float32 samples at inputRate -> Int16 samples at outputRate.
 *  Uses box-filter averaging (a cheap low-pass), which is adequate for speech. */
export function createResampler(inputRate, outputRate = TARGET_RATE) {
  const ratio = inputRate / outputRate;
  if (!(ratio >= 1)) throw new Error(`input rate ${inputRate} must be >= ${outputRate}`);
  let acc = 0;
  let count = 0;
  let t = 0;
  return {
    process(input) {
      const out = new Int16Array(Math.ceil(input.length / ratio) + 1);
      let n = 0;
      for (let i = 0; i < input.length; i++) {
        acc += input[i];
        count++;
        t += 1;
        if (t >= ratio) {
          out[n++] = toInt16(acc / count);
          t -= ratio;
          acc = 0;
          count = 0;
        }
      }
      return out.subarray(0, n);
    },
  };
}

export function toInt16(sample) {
  const s = Math.max(-1, Math.min(1, sample));
  return s < 0 ? Math.round(s * 0x8000) : Math.round(s * 0x7fff);
}

/** Concatenate Int16 chunks (Int16Array or ArrayBuffer) into one Int16Array. */
export function concatInt16(chunks) {
  const arrays = chunks.map((c) => (c instanceof Int16Array ? c : new Int16Array(c)));
  const total = arrays.reduce((sum, a) => sum + a.length, 0);
  const out = new Int16Array(total);
  let offset = 0;
  for (const a of arrays) {
    out.set(a, offset);
    offset += a.length;
  }
  return out;
}

/** Encode mono 16-bit PCM chunks as a WAV file. Returns an ArrayBuffer. */
export function encodeWav(chunks, sampleRate = TARGET_RATE) {
  const pcm = concatInt16(chunks);
  const dataBytes = pcm.length * 2;
  const buffer = new ArrayBuffer(44 + dataBytes);
  const view = new DataView(buffer);
  const ascii = (offset, text) => {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
  };
  ascii(0, 'RIFF');
  view.setUint32(4, 36 + dataBytes, true);
  ascii(8, 'WAVE');
  ascii(12, 'fmt ');
  view.setUint32(16, 16, true); // fmt chunk size
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // byte rate
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  ascii(36, 'data');
  view.setUint32(40, dataBytes, true);
  new Int16Array(buffer, 44).set(pcm);
  return buffer;
}

/** Average channels [start, end) into one mono Float32Array. */
export function mixToMono(channels, start = 0, end = channels[0].length) {
  const out = new Float32Array(Math.max(0, end - start));
  if (channels.length === 1) {
    out.set(channels[0].subarray(start, end));
    return out;
  }
  for (const ch of channels) {
    for (let i = start; i < end; i++) out[i - start] += ch[i];
  }
  const n = channels.length;
  for (let i = 0; i < out.length; i++) out[i] /= n;
  return out;
}

/** Float32 samples -> Int16Array (no resampling). */
export function floatToInt16(input) {
  const out = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) out[i] = toInt16(input[i]);
  return out;
}

/** Split [0, total) into consecutive [start, end) ranges of at most perPart samples. */
export function partRanges(total, perPart) {
  if (!(perPart > 0)) throw new Error('perPart must be > 0');
  const ranges = [];
  for (let s = 0; s < total; s += perPart) ranges.push([s, Math.min(total, s + perPart)]);
  return ranges;
}
