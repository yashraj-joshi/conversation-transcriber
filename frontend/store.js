// IndexedDB queue for recordings, 10-second PCM chunks, and finished WAV parts (spec 001 FR-011, 002 FR-012).
import { encodeWav } from './wav.js';

const DB_NAME = 'conversation-transcriber';
const DB_VERSION = 1;
let dbPromise = null;

function req(r) {
  return new Promise((resolve, reject) => {
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

function done(tx) {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error || new Error('transaction aborted'));
  });
}

export function open() {
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      const r = indexedDB.open(DB_NAME, DB_VERSION);
      r.onupgradeneeded = () => {
        const db = r.result;
        db.createObjectStore('recordings', { keyPath: 'id' });
        db.createObjectStore('parts', { keyPath: ['recordingId', 'index'] });
        db.createObjectStore('chunks', { keyPath: ['recordingId', 'partIndex', 'seq'] });
      };
      r.onsuccess = () => resolve(r.result);
      r.onerror = () => reject(r.error);
    });
  }
  return dbPromise;
}

async function store(name, mode = 'readonly') {
  const db = await open();
  const tx = db.transaction(name, mode);
  return { tx, os: tx.objectStore(name) };
}

const partRange = (id) => IDBKeyRange.bound([id, 0], [id, Infinity]);
const chunkRange = (id, partIndex) =>
  partIndex === undefined
    ? IDBKeyRange.bound([id, 0, 0], [id, Infinity, Infinity])
    : IDBKeyRange.bound([id, partIndex, 0], [id, partIndex, Infinity]);

export async function putRecording(rec) {
  const { tx, os } = await store('recordings', 'readwrite');
  os.put(rec);
  await done(tx);
}

export async function getRecording(id) {
  const { os } = await store('recordings');
  return req(os.get(id));
}

export async function listRecordings() {
  const { os } = await store('recordings');
  const all = await req(os.getAll());
  return all.sort((a, b) => (a.startedAt < b.startedAt ? 1 : -1));
}

export async function updateRecording(id, patch) {
  const db = await open();
  const tx = db.transaction('recordings', 'readwrite');
  const os = tx.objectStore('recordings');
  const rec = await req(os.get(id));
  if (rec) os.put({ ...rec, ...patch });
  await done(tx);
  return rec ? { ...rec, ...patch } : null;
}

export async function deleteRecording(id) {
  const db = await open();
  const tx = db.transaction(['recordings', 'parts', 'chunks'], 'readwrite');
  tx.objectStore('recordings').delete(id);
  tx.objectStore('parts').delete(partRange(id));
  tx.objectStore('chunks').delete(chunkRange(id));
  await done(tx);
}

export async function addChunk(recordingId, partIndex, seq, data) {
  const { tx, os } = await store('chunks', 'readwrite');
  os.put({ recordingId, partIndex, seq, data });
  await done(tx);
}

/** Part indexes that still have unassembled chunks (left behind by a crash). */
export async function chunkPartIndexes(recordingId) {
  const { os } = await store('chunks');
  const keys = await req(os.getAllKeys(chunkRange(recordingId)));
  return [...new Set(keys.map((k) => k[1]))].sort((a, b) => a - b);
}

/** Combine a part's chunks into one WAV part, delete the chunks, and record progress, atomically.
 *  Returns the number of samples in the part (0 if there were no chunks). */
export async function assemblePart(recordingId, partIndex) {
  const db = await open();
  const read = db.transaction('chunks', 'readonly');
  const chunks = await req(read.objectStore('chunks').getAll(chunkRange(recordingId, partIndex)));
  if (chunks.length === 0) return 0;
  chunks.sort((a, b) => a.seq - b.seq);
  const samples = chunks.reduce((n, c) => n + c.data.byteLength / 2, 0);
  const wav = encodeWav(chunks.map((c) => c.data));

  const tx = db.transaction(['parts', 'chunks', 'recordings'], 'readwrite');
  tx.objectStore('parts').put({ recordingId, index: partIndex, data: wav, contentType: 'audio/wav', samples });
  tx.objectStore('chunks').delete(chunkRange(recordingId, partIndex));
  const recs = tx.objectStore('recordings');
  const getReq = recs.get(recordingId);
  getReq.onsuccess = () => {
    const rec = getReq.result;
    if (!rec) return;
    const closed = rec.closedParts || [];
    if (!closed.includes(partIndex)) {
      rec.closedParts = [...closed, partIndex];
      rec.closedSamples = (rec.closedSamples || 0) + samples;
    }
    recs.put(rec);
  };
  await done(tx);
  return samples;
}

export async function listParts(recordingId) {
  const { os } = await store('parts');
  return req(os.getAll(partRange(recordingId)));
}

export async function deletePart(recordingId, index) {
  const { tx, os } = await store('parts', 'readwrite');
  os.delete([recordingId, index]);
  await done(tx);
}
