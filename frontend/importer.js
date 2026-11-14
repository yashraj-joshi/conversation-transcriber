// Transcribe an uploaded audio file (spec 003): decode in the browser, convert to the same 16 kHz mono
// WAV parts as recordings, and queue them for the normal upload pipeline.
import { createResampler, encodeWav, mixToMono, floatToInt16, partRanges, TARGET_RATE } from './wav.js';
import { PART_SECONDS, MAX_SECONDS, MIN_SECONDS } from './recorder.js';
import * as store from './store.js';

export const MAX_FILE_BYTES = 500 * 1024 * 1024;
const SLICE_SECONDS = 10;

export class ImportError extends Error {}

/** Read and decode a File. Returns { buffer, durationSeconds }. */
export async function decodeFile(file) {
  if (!window.OfflineAudioContext) throw new ImportError('This browser cannot convert audio files.');
  if (file.size > MAX_FILE_BYTES) throw new ImportError('The file is larger than 500 MB.');
  if (file.size === 0) throw new ImportError('The file is empty.');

  let bytes;
  try {
    bytes = await file.arrayBuffer();
  } catch {
    throw new ImportError('The file could not be read.');
  }
  let ctx;
  try {
    ctx = new OfflineAudioContext(1, 1, TARGET_RATE); // decode + resample to 16 kHz natively
  } catch {
    ctx = new OfflineAudioContext(1, 1, 44100); // older Safari: resample in JS afterwards
  }
  let buffer;
  try {
    buffer = await ctx.decodeAudioData(bytes);
  } catch (err) {
    if (err && (err.name === 'RangeError' || /memory/i.test(String(err.message)))) {
      throw new ImportError('The device ran out of memory reading this file. Try a shorter file, or use a computer for files over about an hour.');
    }
    throw new ImportError("This browser can't read this file. Try MP3, M4A, WAV, or FLAC.");
  }
  const durationSeconds = buffer.length / buffer.sampleRate;
  if (durationSeconds < MIN_SECONDS) throw new ImportError('The file is shorter than 1 second.');
  if (durationSeconds > MAX_SECONDS) {
    throw new ImportError(`The file is ${formatHours(durationSeconds)} long; the limit is ${formatHours(MAX_SECONDS)}.`);
  }
  return { buffer, durationSeconds };
}

function formatHours(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return h ? `${h} h ${m} min` : `${m} min`;
}

/** Default recording start: the file's modified time minus its duration. */
export function defaultStart(file, durationSeconds) {
  const modified = file.lastModified ? new Date(file.lastModified) : new Date();
  return new Date(modified.getTime() - durationSeconds * 1000);
}

export function titleFromName(name) {
  return name.replace(/\.[^.]+$/, '').replace(/[_]+/g, ' ').trim().slice(0, 120);
}

/** Convert a decoded buffer into WAV parts in IndexedDB and queue it for upload.
 *  onProgress(done, total) is called after each part. Returns the recording id. */
export async function prepare(buffer, { title, startedAt, sourceName }, onProgress = () => {}) {
  const rate = buffer.sampleRate;
  const channels = Array.from({ length: buffer.numberOfChannels }, (_, i) => buffer.getChannelData(i));
  const ranges = partRanges(buffer.length, Math.round(PART_SECONDS * rate));
  const resampler = rate === TARGET_RATE ? null : createResampler(rate);
  const id = crypto.randomUUID();

  await store.putRecording({
    id,
    startedAt: startedAt.toISOString(),
    tzOffsetMinutes: -startedAt.getTimezoneOffset(),
    title: title || null,
    sourceName: (sourceName || '').slice(0, 200) || null,
    state: 'importing',
    partCount: null,
    durationSeconds: Math.round((buffer.length / rate) * 10) / 10,
  });

  try {
    for (let i = 0; i < ranges.length; i++) {
      const [start, end] = ranges[i];
      const pieces = [];
      let samples = 0;
      for (let o = start; o < end; o += SLICE_SECONDS * rate) {
        const mono = mixToMono(channels, o, Math.min(end, o + SLICE_SECONDS * rate));
        const pcm = resampler ? resampler.process(mono).slice() : floatToInt16(mono);
        pieces.push(pcm);
        samples += pcm.length;
      }
      await store.putPart(id, i, encodeWav(pieces), samples);
      onProgress(i + 1, ranges.length);
      await new Promise((r) => setTimeout(r, 0)); // keep the page responsive
    }
    await store.updateRecording(id, { state: 'uploading', partCount: ranges.length });
  } catch (err) {
    await store.deleteRecording(id).catch(() => {});
    throw err;
  }
  return id;
}
