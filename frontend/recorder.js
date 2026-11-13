// Microphone -> 16 kHz mono WAV parts (spec 002 FR-007, FR-008, FR-012).
// Audio is saved to IndexedDB every 10 s; every 5 min of audio a WAV part is closed and announced
// with a 'part' event so the app can upload it while recording continues (spec 001 FR-005).
import { createResampler, TARGET_RATE } from './wav.js';
import * as store from './store.js';

export const PART_SECONDS = 300;
export const MAX_SECONDS = 3 * 60 * 60; // must match backend core.MAX_DURATION_SECONDS
export const WARN_BEFORE_SECONDS = 5 * 60;
export const MIN_SECONDS = 1;
const FLUSH_SECONDS = 10;
const GAP_LIMIT_MS = 8000;

export function isSupported() {
  return !!(navigator.mediaDevices?.getUserMedia && window.AudioContext && window.AudioWorkletNode && window.indexedDB);
}

export class Recorder extends EventTarget {
  constructor() {
    super();
    this.state = 'idle'; // idle | recording | paused | stopping
    this.queue = Promise.resolve();
  }

  get elapsedSeconds() {
    return this.totalSamples ? this.totalSamples / TARGET_RATE : 0;
  }

  async start({ title } = {}) {
    if (this.state !== 'idle') throw new Error('already recording');
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    try {
      this.ctx = new AudioContext();
      await this.ctx.audioWorklet.addModule('pcm-worklet.js');
      this.source = this.ctx.createMediaStreamSource(this.stream);
      this.node = new AudioWorkletNode(this.ctx, 'pcm-capture', {
        numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1, channelCountMode: 'explicit',
      });
      this.mute = this.ctx.createGain();
      this.mute.gain.value = 0;
      this.source.connect(this.node).connect(this.mute).connect(this.ctx.destination);
      this.resampler = createResampler(this.ctx.sampleRate);
    } catch (err) {
      this._release();
      throw err;
    }

    const startedAt = new Date();
    this.id = crypto.randomUUID();
    this.partIndex = 0;
    this.seq = 0;
    this.pending = [];
    this.pendingSamples = 0;
    this.partSamples = 0;
    this.totalSamples = 0;
    this.warned = false;
    this.lastDataAt = Date.now();
    this.recording = {
      id: this.id,
      startedAt: startedAt.toISOString(),
      tzOffsetMinutes: -startedAt.getTimezoneOffset(),
      title: title || null,
      state: 'recording',
      partCount: null,
      durationSeconds: 0,
      closedParts: [],
      closedSamples: 0,
    };
    await store.putRecording(this.recording);

    this.node.port.onmessage = (e) => this._onFrames(e.data);
    if (this.ctx.state === 'suspended') await this.ctx.resume();
    this.state = 'recording';
    this._listen();
    await this._wakeLock();
    return this.recording;
  }

  async pause() {
    if (this.state !== 'recording') return;
    this.state = 'paused';
    this._flush();
    await this.ctx.suspend().catch(() => {});
  }

  async resume() {
    if (this.state !== 'paused') return;
    await this.ctx.resume().catch(() => {});
    this.lastDataAt = Date.now();
    this.state = 'recording';
  }

  /** Stop and finalise. reason: 'user' | 'limit' | 'interrupted'. */
  async stop(reason = 'user') {
    if (this.state === 'idle' || this.state === 'stopping') return null;
    this.state = 'stopping';
    if (this.node) this.node.port.onmessage = null;
    this._unlisten();
    this._release();
    this._flush();
    if (this.partSamples > 0) this._closePart();
    await this.queue;

    const id = this.id;
    const durationSeconds = Math.round((this.totalSamples / TARGET_RATE) * 10) / 10;
    let result;
    if (durationSeconds < MIN_SECONDS) {
      await store.deleteRecording(id);
      result = { id, discarded: true, reason };
    } else {
      await store.updateRecording(id, { state: 'uploading', partCount: this.partIndex, durationSeconds });
      result = { id, discarded: false, reason, durationSeconds, partCount: this.partIndex };
    }
    this.state = 'idle';
    this.totalSamples = 0;
    this.dispatchEvent(new CustomEvent('stopped', { detail: result }));
    return result;
  }

  // --- internals ---------------------------------------------------------------------------------

  _onFrames(float32) {
    if (this.state !== 'recording') return;
    const pcm = this.resampler.process(float32);
    if (pcm.length === 0) return;
    this.pending.push(pcm.slice());
    this.pendingSamples += pcm.length;
    this.partSamples += pcm.length;
    this.totalSamples += pcm.length;
    this.lastDataAt = Date.now();

    if (this.pendingSamples >= FLUSH_SECONDS * TARGET_RATE) this._flush();
    if (this.partSamples >= PART_SECONDS * TARGET_RATE) this._closePart();
    if (!this.warned && this.totalSamples >= (MAX_SECONDS - WARN_BEFORE_SECONDS) * TARGET_RATE) {
      this.warned = true;
      this.dispatchEvent(new CustomEvent('warning', { detail: { remainingSeconds: WARN_BEFORE_SECONDS } }));
    }
    if (this.totalSamples >= MAX_SECONDS * TARGET_RATE) this.stop('limit');
  }

  _enqueue(fn) {
    this.queue = this.queue.then(fn).catch((err) => {
      console.error('[recorder]', err);
      this.dispatchEvent(new CustomEvent('error', { detail: err }));
    });
    return this.queue;
  }

  _flush() {
    if (!this.pending || this.pendingSamples === 0) return;
    const total = this.pendingSamples;
    const data = new Int16Array(total);
    let o = 0;
    for (const p of this.pending) {
      data.set(p, o);
      o += p.length;
    }
    this.pending = [];
    this.pendingSamples = 0;
    const id = this.id;
    const part = this.partIndex;
    const seq = this.seq++;
    this._enqueue(() => store.addChunk(id, part, seq, data.buffer));
  }

  _closePart() {
    this._flush();
    const id = this.id;
    const index = this.partIndex;
    this.partIndex += 1;
    this.partSamples = 0;
    this.seq = 0;
    this._enqueue(async () => {
      const samples = await store.assemblePart(id, index);
      if (samples > 0) this.dispatchEvent(new CustomEvent('part', { detail: { recordingId: id, index } }));
    });
  }

  _listen() {
    this.onTrackEnded = () => this.stop('interrupted');
    this.stream.getAudioTracks().forEach((t) => t.addEventListener('ended', this.onTrackEnded));
    this.onVisibility = async () => {
      if (document.visibilityState === 'hidden') {
        this._flush();
      } else {
        await this._wakeLock();
        if (this.state === 'recording' && this.ctx.state !== 'running') await this.ctx.resume().catch(() => {});
      }
    };
    this.onPageHide = () => this._flush();
    document.addEventListener('visibilitychange', this.onVisibility);
    window.addEventListener('pagehide', this.onPageHide);
    // Laptop sleep / iOS backgrounding: audio stops arriving. Keep what we have and stop.
    this.gapTimer = setInterval(() => {
      if (this.state === 'recording' && Date.now() - this.lastDataAt > GAP_LIMIT_MS) this.stop('interrupted');
    }, 2000);
  }

  _unlisten() {
    clearInterval(this.gapTimer);
    document.removeEventListener('visibilitychange', this.onVisibility);
    window.removeEventListener('pagehide', this.onPageHide);
    this.stream?.getAudioTracks().forEach((t) => t.removeEventListener('ended', this.onTrackEnded));
  }

  _release() {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close().catch(() => {});
    this.wakeLock?.release().catch(() => {});
    this.wakeLock = null;
  }

  async _wakeLock() {
    if (!('wakeLock' in navigator) || document.visibilityState !== 'visible') return;
    if (this.state !== 'recording' && this.state !== 'paused') return;
    try {
      this.wakeLock = await navigator.wakeLock.request('screen');
    } catch {
      /* not fatal */
    }
  }
}

/** Finalise recordings left in state 'recording' by a crash or closed tab (except the active one). */
export async function recoverInterrupted(activeId) {
  const recovered = [];
  for (const rec of await store.listRecordings()) {
    if (rec.state !== 'recording' || rec.id === activeId) continue;
    for (const idx of await store.chunkPartIndexes(rec.id)) await store.assemblePart(rec.id, idx);
    const fresh = await store.getRecording(rec.id);
    const closed = fresh.closedParts || [];
    const durationSeconds = Math.round(((fresh.closedSamples || 0) / TARGET_RATE) * 10) / 10;
    if (closed.length === 0 || durationSeconds < MIN_SECONDS) {
      await store.deleteRecording(rec.id);
      continue;
    }
    const partCount = Math.max(...closed) + 1;
    await store.updateRecording(rec.id, { state: 'uploading', partCount, durationSeconds, recovered: true });
    recovered.push(rec.id);
  }
  return recovered;
}
