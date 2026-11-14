// UI, views, background upload pipeline, and status polling.
import * as auth from './auth.js';
import * as api from './api.js';
import * as store from './store.js';
import { Recorder, recoverInterrupted, isSupported } from './recorder.js';
import * as importer from './importer.js';

const $ = (id) => document.getElementById(id);
const recorder = new Recorder();
const POLL_MS = 4000;
const KEEP_DONE = 20;
const STALE_MS = 20 * 60 * 1000; // transcriber Lambda max runtime is 15 min

// --- helpers -------------------------------------------------------------------------------------

function fmtClock(seconds) {
  const s = Math.floor(seconds);
  return [Math.floor(s / 3600), Math.floor((s % 3600) / 60), s % 60].map((n) => String(n).padStart(2, '0')).join(':');
}

function fmtWhen(iso) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) node.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) if (c != null) node.append(c);
  return node;
}

let noticeTimer = null;
function notify(text, { sticky = false } = {}) {
  $('notice-text').textContent = text;
  $('notice').hidden = false;
  clearTimeout(noticeTimer);
  if (!sticky) noticeTimer = setTimeout(() => ($('notice').hidden = true), 8000);
}

const isTouchApple = () => 'standalone' in navigator && navigator.maxTouchPoints > 1;
const isStandalone = () => navigator.standalone === true || matchMedia('(display-mode: standalone)').matches;

function micHelp() {
  return isTouchApple()
    ? 'Microphone access is blocked. On iPhone: Settings → Apps → Safari → Microphone (or Settings → Privacy & Security → Microphone), then reopen the app.'
    : 'Microphone access is blocked. Allow it with the site-settings icon in the address bar. On a Mac also check System Settings → Privacy & Security → Microphone.';
}

// --- views ---------------------------------------------------------------------------------------

let currentView = null;

function show(view) {
  currentView = view;
  for (const v of ['signin', 'record', 'transcripts']) $(`view-${v}`).hidden = v !== view;
  const signedIn = view !== 'signin';
  $('tabs').hidden = !signedIn;
  $('signout').hidden = !signedIn;
  document.querySelectorAll('.tab').forEach((t) => {
    if (t.dataset.view === view) t.setAttribute('aria-current', 'page');
    else t.removeAttribute('aria-current');
  });
  if (view === 'transcripts') loadMonths();
  if (view === 'record') renderDeviceList();
}

function requireSignIn(message) {
  if (recorder.state !== 'idle') return; // never interrupt a recording; uploads resume after sign-in
  show('signin');
  if (message) showSignInError(message);
}

function showSignInError(message) {
  $('signin-error').textContent = message;
  $('signin-error').hidden = !message;
}

// --- recording UI --------------------------------------------------------------------------------

let tick = null;

function renderRecorder() {
  const s = recorder.state;
  $('btn-record').hidden = s !== 'idle';
  $('btn-record').disabled = importing;
  $('btn-upload').disabled = s !== 'idle' || importing || !$('import-panel').hidden;
  $('btn-pause').hidden = s === 'idle' || s === 'stopping';
  $('btn-stop').hidden = s === 'idle';
  $('btn-stop').disabled = s === 'stopping';
  $('btn-pause').textContent = s === 'paused' ? 'Resume' : 'Pause';
  $('title').disabled = s !== 'idle';
  $('rec-state').textContent = { idle: 'Ready', recording: 'Recording', paused: 'Paused', stopping: 'Saving…' }[s];
  $('rec-state').dataset.state = s;
  $('timer').textContent = fmtClock(recorder.elapsedSeconds);
}

async function startRecording() {
  if (importing || !$('import-panel').hidden) return notify('Finish or cancel the file upload first.');
  if (!isSupported()) {
    notify('This browser cannot record audio. Use Safari on iPhone, or Chrome, Edge, or Safari on a computer.', { sticky: true });
    return;
  }
  try {
    await recorder.start({ title: $('title').value.trim() || null });
  } catch (err) {
    console.error(err);
    if (err && (err.name === 'NotAllowedError' || err.name === 'SecurityError')) notify(micHelp(), { sticky: true });
    else if (err && err.name === 'NotFoundError') notify('No microphone was found.', { sticky: true });
    else notify(`Could not start recording: ${err?.message || err}`, { sticky: true });
    renderRecorder();
    return;
  }
  tick = setInterval(renderRecorder, 250);
  renderRecorder();
  renderDeviceList();
}

async function stopRecording(reason = 'user') {
  await recorder.stop(reason);
}

recorder.addEventListener('part', () => pump());
recorder.addEventListener('warning', () =>
  notify('Recording will stop automatically in 5 minutes (3-hour limit).', { sticky: true }));
recorder.addEventListener('error', (e) => notify(`Saving audio on this device failed: ${e.detail?.message || e.detail}`, { sticky: true }));
recorder.addEventListener('stopped', (e) => {
  clearInterval(tick);
  const r = e.detail;
  if (r.discarded) notify('Recording was shorter than 1 second and was discarded.');
  else if (r.reason === 'interrupted') notify('Recording stopped because the app was interrupted (background, sleep, or microphone lost). The audio captured so far was saved.', { sticky: true });
  else if (r.reason === 'limit') notify('Recording reached the 3-hour limit and was stopped. It is being transcribed.', { sticky: true });
  $('title').value = '';
  renderRecorder();
  renderDeviceList();
  pump();
});

// --- device list ---------------------------------------------------------------------------------

const STATE_LABEL = {
  importing: 'Preparing',
  recording: 'Recording',
  uploading: 'Uploading',
  submitted: 'Transcribing',
  done: 'Done',
  failed: 'Failed',
};

async function renderDeviceList() {
  const list = $('device-list');
  let recs;
  try {
    recs = await store.listRecordings();
  } catch {
    return;
  }
  list.replaceChildren();
  $('device-empty').hidden = recs.length > 0;
  for (const rec of recs) {
    let label = STATE_LABEL[rec.state] || rec.state;
    if (rec.state === 'uploading' || (rec.state === 'recording' && rec.id !== recorder.id)) {
      const left = (await store.listParts(rec.id)).length;
      label = left ? `Uploading (${left} part${left === 1 ? '' : 's'} left)` : 'Uploading';
    }
    const actions = [];
    if (rec.state === 'done' && rec.transcriptKey) {
      actions.push(el('button', { type: 'button', class: 'btn small', onclick: () => openTranscript(rec.transcriptKey) }, 'Open'));
    }
    if (rec.state === 'failed') {
      actions.push(el('button', { type: 'button', class: 'btn small primary', onclick: () => retry(rec.id) }, 'Retry'));
    }
    if (rec.state === 'done' || rec.state === 'failed') {
      actions.push(el('button', { type: 'button', class: 'btn small subtle', onclick: () => forget(rec.id) }, 'Remove'));
    }
    list.append(el('li', { class: 'device-item' },
      el('div', { class: 'device-main' },
        el('span', { class: 'device-title' }, rec.title || fmtWhen(rec.startedAt)),
        el('span', { class: 'device-meta' },
          `${rec.sourceName ? 'File · ' : ''}${rec.title ? `${fmtWhen(rec.startedAt)} · ` : ''}${rec.durationSeconds ? fmtClock(rec.durationSeconds) : ''}`),
        rec.error ? el('span', { class: 'device-error' }, rec.error) : null),
      el('span', { class: `chip ${rec.state}` }, label),
      el('div', { class: 'device-actions' }, actions)));
  }
}

async function forget(id) {
  await store.deleteRecording(id);
  renderDeviceList();
}

async function retry(id) {
  await store.updateRecording(id, { state: 'uploading', error: null, completeError: null });
  renderDeviceList();
  pump();
}

// --- upload pipeline -----------------------------------------------------------------------------

let pumping = false;
let pumpAgain = false;
let retryTimer = null;

async function pump() {
  if (pumping) {
    pumpAgain = true;
    return;
  }
  if (!auth.isSignedIn()) return;
  pumping = true;
  try {
    do {
      pumpAgain = false;
      await pumpOnce();
    } while (pumpAgain);
  } finally {
    pumping = false;
  }
}

async function pumpOnce() {
  const recs = await store.listRecordings();
  for (const rec of recs) {
    if (rec.state !== 'recording' && rec.state !== 'uploading') continue;
    const parts = (await store.listParts(rec.id)).sort((a, b) => a.index - b.index);
    for (const part of parts) {
      try {
        await api.uploadPart(rec.id, part);
        await store.deletePart(rec.id, part.index);
        renderDeviceList();
      } catch (err) {
        return handleTransient(err, 'Upload');
      }
    }
    if (rec.state === 'uploading') await submit(rec);
  }
  ensurePolling();
  // Keep a small history only.
  const finished = recs.filter((r) => r.state === 'done');
  for (const r of finished.slice(KEEP_DONE)) await store.deleteRecording(r.id);
}

function handleTransient(err, what) {
  if (err instanceof auth.AuthError) {
    requireSignIn(err.message);
    return;
  }
  console.warn(`[${what}]`, err);
  clearTimeout(retryTimer);
  retryTimer = setTimeout(pump, navigator.onLine ? 30_000 : 120_000);
}

async function submit(rec) {
  try {
    const { status, data } = await api.completeRecording(rec);
    if (status === 200 && data.state === 'done') {
      await store.updateRecording(rec.id, { state: 'done', transcriptKey: data.transcriptKey });
    } else {
      await store.updateRecording(rec.id, {
        state: 'submitted', submittedServerAt: data.updatedAt || '', submittedLocalAt: Date.now(),
      });
    }
  } catch (err) {
    if (err instanceof api.ApiError && (err.status === 400 || err.status === 409)) {
      const msg = err.status === 409
        ? `Some audio parts never reached the server (${(err.body?.missing || []).join(', ')}).`
        : err.message;
      await store.updateRecording(rec.id, { state: 'failed', error: msg });
    } else {
      handleTransient(err, 'Submit');
    }
  }
  renderDeviceList();
}

// --- status polling ------------------------------------------------------------------------------

let pollTimer = null;

function ensurePolling() {
  if (!pollTimer) pollTimer = setTimeout(poll, POLL_MS);
}

async function poll() {
  pollTimer = null;
  let active = false;
  try {
    for (const rec of await store.listRecordings()) {
      if (rec.state !== 'submitted') continue;
      active = true;
      const status = await api.getStatus(rec.id);
      if (status.state === 'done') {
        await store.updateRecording(rec.id, { state: 'done', transcriptKey: status.transcriptKey, error: null });
        notify(`Transcript ready: ${rec.title || fmtWhen(rec.startedAt)}`);
        if (currentView === 'transcripts') loadMonths();
      } else if (status.state === 'failed' && (status.updatedAt || '') >= (rec.submittedServerAt || '')) {
        await store.updateRecording(rec.id, { state: 'failed', error: status.error || 'Transcription failed.' });
      } else if (Date.now() - (rec.submittedLocalAt || Date.now()) > STALE_MS) {
        await store.updateRecording(rec.id, { state: 'failed', error: 'Transcription did not finish in time. Tap Retry.' });
      }
    }
  } catch (err) {
    if (err instanceof auth.AuthError) return requireSignIn(err.message);
    console.warn('[poll]', err);
    active = true;
  }
  renderDeviceList();
  if (active) ensurePolling();
}

// --- transcripts ---------------------------------------------------------------------------------

let selectedMonth = null;
let openKey = null;
let openText = '';

async function loadMonths() {
  let months;
  try {
    months = await api.listMonths();
  } catch (err) {
    if (err instanceof auth.AuthError) return requireSignIn(err.message);
    notify(`Could not load transcripts: ${err.message}`);
    return;
  }
  const box = $('months');
  box.replaceChildren();
  $('tx-empty').hidden = months.length > 0;
  if (!months.includes(selectedMonth)) selectedMonth = months[0] || null;
  for (const m of months) {
    const label = new Date(`${m}-01T12:00:00`).toLocaleDateString(undefined, { month: 'short', year: 'numeric' });
    box.append(el('button', {
      type: 'button', class: 'month', role: 'tab', 'aria-selected': m === selectedMonth ? 'true' : 'false',
      onclick: () => { selectedMonth = m; loadMonths(); },
    }, label));
  }
  if (selectedMonth) loadItems(selectedMonth);
  else $('tx-items').replaceChildren();
}

async function loadItems(month) {
  let items;
  try {
    items = await api.listTranscripts(month);
  } catch (err) {
    if (err instanceof auth.AuthError) return requireSignIn(err.message);
    notify(`Could not load ${month}: ${err.message}`);
    return;
  }
  const list = $('tx-items');
  list.replaceChildren();
  for (const item of items) {
    const [date, time] = item.recordedAt.split(' ');
    const when = new Date(`${date}T${time}`);
    list.append(el('li', {},
      el('button', {
        type: 'button', class: `tx-item${item.key === openKey ? ' active' : ''}`,
        onclick: () => openTranscript(item.key),
      },
      el('span', { class: 'tx-item-date' }, when.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })),
      el('span', { class: 'tx-item-time' }, when.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })))));
  }
}

async function openTranscript(key) {
  if (currentView !== 'transcripts') {
    selectedMonth = key.split('/')[1];
    show('transcripts');
  }
  openKey = key;
  $('tx-title').textContent = 'Loading…';
  $('tx-text').textContent = '';
  $('tx-layout').classList.add('has-selection');
  try {
    openText = await api.getTranscript(key);
  } catch (err) {
    if (err instanceof auth.AuthError) return requireSignIn(err.message);
    $('tx-title').textContent = 'Could not load transcript';
    $('tx-text').textContent = err.message;
    return;
  }
  const title = (openText.match(/^Title: (.+)$/m) || [])[1];
  $('tx-title').textContent = title || key.split('/').pop().replace(/\.txt$/, '');
  $('tx-text').textContent = openText;
  const canShare = typeof navigator.share === 'function';
  $('tx-copy').disabled = false;
  $('tx-share').hidden = !canShare;
  $('tx-share').disabled = false;
  $('tx-download').hidden = canShare;
  $('tx-download').disabled = false;
  document.querySelectorAll('.tx-item').forEach((b) => b.classList.remove('active'));
  if (selectedMonth) loadItems(selectedMonth);
}

async function copyTranscript() {
  try {
    await navigator.clipboard.writeText(openText);
    notify('Transcript copied.');
  } catch {
    const range = document.createRange();
    range.selectNodeContents($('tx-text'));
    getSelection().removeAllRanges();
    getSelection().addRange(range);
    notify('Press Cmd/Ctrl+C to copy the selected text.');
  }
}

async function shareTranscript() {
  try {
    await navigator.share({ title: $('tx-title').textContent, text: openText });
  } catch (err) {
    if (err?.name !== 'AbortError') downloadTranscript();
  }
}

function downloadTranscript() {
  const url = URL.createObjectURL(new Blob([openText], { type: 'text/plain;charset=utf-8' }));
  const a = el('a', { href: url, download: (openKey || 'transcript.txt').split('/').pop() });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// --- file upload (spec 003) ---------------------------------------------------------------------

let importing = false;
let pendingImport = null; // { file, buffer, durationSeconds }

function toLocalInput(date) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function resetImport() {
  pendingImport = null;
  importing = false;
  $('import-panel').hidden = true;
  $('import-form').hidden = true;
  $('import-go').hidden = true;
  $('import-go').disabled = false;
  $('import-cancel').disabled = false;
  $('import-error').hidden = true;
  $('file-input').value = '';
  renderRecorder();
}

function importError(message) {
  $('import-error').textContent = message;
  $('import-error').hidden = false;
  $('import-status').textContent = '';
  $('import-form').hidden = true;
  $('import-go').hidden = true;
}

async function onFileChosen() {
  const file = $('file-input').files[0];
  if (!file) return;
  pendingImport = null;
  $('import-panel').hidden = false;
  $('import-file').textContent = file.name;
  $('import-error').hidden = true;
  $('import-form').hidden = true;
  $('import-go').hidden = true;
  $('import-status').textContent = `Reading ${(file.size / 1048576).toFixed(1)} MB…`;
  renderRecorder();
  try {
    const decoded = await importer.decodeFile(file);
    if ($('import-panel').hidden) return; // cancelled meanwhile
    pendingImport = { file, ...decoded };
    $('import-status').textContent = `Length ${fmtClock(decoded.durationSeconds)}. Check the title and date, then tap Transcribe.`;
    $('import-title').value = importer.titleFromName(file.name);
    $('import-when').value = toLocalInput(importer.defaultStart(file, decoded.durationSeconds));
    $('import-form').hidden = false;
    $('import-go').hidden = false;
  } catch (err) {
    console.error('[import]', err);
    importError(err instanceof importer.ImportError ? err.message : `The file could not be read: ${err?.message || err}`);
  }
}

async function startImport() {
  if (!pendingImport || importing) return;
  const when = new Date($('import-when').value);
  if (Number.isNaN(when.getTime())) return importError('Enter a valid date and time.');
  if (when.getTime() > Date.now() + 5 * 60 * 1000) {
    $('import-error').textContent = 'The recording date cannot be in the future.';
    $('import-error').hidden = false;
    return;
  }
  importing = true;
  $('import-go').disabled = true;
  $('import-cancel').disabled = true;
  $('import-error').hidden = true;
  renderRecorder();
  try {
    await importer.prepare(pendingImport.buffer, {
      title: $('import-title').value.trim(),
      startedAt: when,
      sourceName: pendingImport.file.name,
    }, (done, total) => {
      $('import-status').textContent = `Preparing part ${done} of ${total}…`;
    });
    notify('File queued. It uploads and transcribes like a recording.');
    resetImport();
    renderDeviceList();
    pump();
  } catch (err) {
    console.error('[import]', err);
    importing = false;
    $('import-cancel').disabled = false;
    importError(`Preparing the file failed: ${err?.message || err}`);
    renderRecorder();
  }
}

// --- wiring --------------------------------------------------------------------------------------

function wire() {
  document.querySelectorAll('.tab').forEach((t) => t.addEventListener('click', () => show(t.dataset.view)));
  $('signout').addEventListener('click', () => {
    if (recorder.state !== 'idle') return notify('Stop the recording before signing out.');
    auth.signOut();
    show('signin');
  });
  $('notice-dismiss').addEventListener('click', () => ($('notice').hidden = true));
  $('install-dismiss').addEventListener('click', () => {
    $('install-hint').hidden = true;
    try { localStorage.setItem('ct.installHintDismissed', '1'); } catch { /* ignore */ }
  });

  $('signin-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    showSignInError('');
    $('signin-submit').disabled = true;
    try {
      await auth.signIn($('signin-email').value.trim(), $('signin-password').value);
      $('signin-password').value = '';
      show('record');
      pump();
    } catch (err) {
      showSignInError(err.message || 'Sign-in failed.');
    } finally {
      $('signin-submit').disabled = false;
    }
  });

  $('btn-record').addEventListener('click', startRecording);
  $('btn-upload').addEventListener('click', () => $('file-input').click());
  $('file-input').addEventListener('change', onFileChosen);
  $('import-go').addEventListener('click', startImport);
  $('import-cancel').addEventListener('click', () => { if (!importing) resetImport(); });
  $('btn-stop').addEventListener('click', () => stopRecording('user'));
  $('btn-pause').addEventListener('click', async () => {
    if (recorder.state === 'paused') await recorder.resume();
    else await recorder.pause();
    renderRecorder();
  });

  document.addEventListener('keydown', (e) => {
    if (e.code !== 'Space' || currentView !== 'record' || e.repeat || importing || !$('import-panel').hidden) return;
    if (e.target.closest('input, textarea, select, button, a')) return;
    e.preventDefault();
    if (recorder.state === 'idle') startRecording();
    else if (recorder.state === 'recording' || recorder.state === 'paused') stopRecording('user');
  });

  $('tx-back').addEventListener('click', () => $('tx-layout').classList.remove('has-selection'));
  $('tx-copy').addEventListener('click', copyTranscript);
  $('tx-share').addEventListener('click', shareTranscript);
  $('tx-download').addEventListener('click', downloadTranscript);

  window.addEventListener('online', pump);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') pump();
  });
  window.addEventListener('beforeunload', (e) => {
    if (recorder.state === 'recording' || recorder.state === 'paused' || importing) {
      e.preventDefault();
      e.returnValue = '';
    }
  });
}

async function init() {
  wire();
  renderRecorder();
  if (!window.APP_CONFIG?.apiUrl) {
    notify('Missing config.js. Deploy with Terraform, or copy config.example.js to config.js for local use.', { sticky: true });
  }
  let dismissed = false;
  try { dismissed = localStorage.getItem('ct.installHintDismissed') === '1'; } catch { /* ignore */ }
  $('install-hint').hidden = !(isTouchApple() && !isStandalone() && !dismissed);

  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});

  try {
    if (await store.discardInterruptedImports()) notify('A file upload was interrupted while being prepared. Please choose the file again.');
  } catch (err) {
    console.warn('[import cleanup]', err);
  }
  try {
    const recovered = await recoverInterrupted(recorder.id);
    if (recovered.length) notify('A recording that was interrupted has been recovered and will be uploaded.', { sticky: true });
  } catch (err) {
    console.warn('[recover]', err);
  }

  if (auth.isSignedIn()) {
    $('signin-email').value = auth.email();
    show('record');
    pump();
  } else {
    $('signin-email').value = auth.email();
    show('signin');
  }
}

init();
