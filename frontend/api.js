// Authenticated client for the HTTP API (contracts/api.openapi.yaml) and direct-to-S3 part uploads.
import { getIdToken } from './auth.js';

const base = () => (window.APP_CONFIG?.apiUrl || '').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(status, message, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function call(method, path, body, retried = false) {
  const token = await getIdToken({ force: retried });
  const resp = await fetch(base() + path, {
    method,
    headers: { Authorization: `Bearer ${token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (resp.status === 401 && !retried) return call(method, path, body, true);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new ApiError(resp.status, data.error || `Request failed (${resp.status})`, data);
  return { status: resp.status, data };
}

export const presignPart = (recordingId, index) =>
  call('POST', '/uploads', { recordingId, index, contentType: 'audio/wav' }).then((r) => r.data);

export const completeRecording = (rec) =>
  call('POST', `/recordings/${rec.id}/complete`, {
    startedAt: rec.startedAt,
    tzOffsetMinutes: rec.tzOffsetMinutes,
    durationSeconds: rec.durationSeconds,
    partCount: rec.partCount,
    ...(rec.title ? { title: rec.title } : {}),
    ...(rec.sourceName ? { sourceName: rec.sourceName } : {}),
  });

export const getStatus = (id) => call('GET', `/recordings/${id}`).then((r) => r.data);
export const listMonths = () => call('GET', '/transcripts/months').then((r) => r.data.months);
export const listTranscripts = (month) =>
  call('GET', `/transcripts?month=${encodeURIComponent(month)}`).then((r) => r.data.items);
export const getTranscript = (key) =>
  call('GET', `/transcript?key=${encodeURIComponent(key)}`).then((r) => r.data.text);

/** POST one WAV part straight to S3 with a presigned POST (fields first, then the file). */
export async function uploadPart(recordingId, part) {
  const post = await presignPart(recordingId, part.index);
  const form = new FormData();
  for (const [k, v] of Object.entries(post.fields)) form.append(k, v);
  form.append('file', new Blob([part.data], { type: 'audio/wav' }), `part-${String(part.index).padStart(3, '0')}.wav`);
  const resp = await fetch(post.url, { method: 'POST', body: form });
  if (!resp.ok) {
    const text = await resp.text().catch(() => '');
    const code = (text.match(/<Code>([^<]+)<\/Code>/) || [])[1] || '';
    throw new ApiError(resp.status, `Upload failed (${resp.status}${code ? ` ${code}` : ''})`);
  }
}
