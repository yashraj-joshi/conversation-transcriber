// Runs frontend/tests/importer.test.html in headless Chrome and checks the result (spec 003).
// Usage: node frontend/tests/run-browser-test.mjs   (needs Google Chrome; set CHROME=/path/to/chrome to override)
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { readFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, extname, dirname, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const chrome = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const types = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript' };

const server = createServer(async (req, res) => {
  const path = normalize(join(root, decodeURIComponent(new URL(req.url, 'http://x').pathname)));
  if (!path.startsWith(root)) return res.writeHead(403).end();
  let body;
  try {
    body = await readFile(path);
  } catch {
    return res.writeHead(404).end();
  }
  res.writeHead(200, { 'Content-Type': types[extname(path)] || 'application/octet-stream' }).end(body);
}).listen(0, '127.0.0.1');
await new Promise((r) => server.once('listening', r));
const url = `http://127.0.0.1:${server.address().port}/tests/importer.test.html`;

const profile = await mkdtemp(join(tmpdir(), 'ct-chrome-'));
const proc = spawn(chrome, ['--headless=new', '--disable-gpu', '--no-first-run', `--user-data-dir=${profile}`,
  '--remote-debugging-port=0', 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'] });
const wsUrl = await new Promise((resolve, reject) => {
  let buf = '';
  proc.stderr.on('data', (d) => {
    buf += d;
    const m = buf.match(/DevTools listening on (ws:\/\/\S+)/);
    if (m) resolve(m[1]);
  });
  proc.on('exit', () => reject(new Error('Chrome exited')));
  setTimeout(() => reject(new Error('Chrome did not start')), 15000);
});

const browser = new WebSocket(wsUrl);
await new Promise((r) => browser.addEventListener('open', r, { once: true }));
let nextId = 1;
const pending = new Map();
const pageErrors = [];
browser.addEventListener('message', (e) => {
  const msg = JSON.parse(e.data);
  if (msg.id && pending.has(msg.id)) pending.get(msg.id)(msg);
  if (msg.method === 'Runtime.exceptionThrown') pageErrors.push(msg.params.exceptionDetails?.exception?.description || msg.params.exceptionDetails?.text);
  if (msg.method === 'Log.entryAdded' && msg.params.entry.level === 'error' && !/favicon|config\.js/.test(msg.params.entry.url || '')) pageErrors.push(msg.params.entry.text);
});
const send = (method, params = {}, sessionId) => new Promise((resolve) => {
  const id = nextId++;
  pending.set(id, resolve);
  browser.send(JSON.stringify({ id, method, params, sessionId }));
});

let result;
let appState;
try {
  // 1. The real app page loads with no JavaScript errors and shows the sign-in view.
  const app = await send('Target.createTarget', { url: 'about:blank' });
  const appSession = (await send('Target.attachToTarget', { targetId: app.result.targetId, flatten: true })).result.sessionId;
  await send('Runtime.enable', {}, appSession);
  await send('Log.enable', {}, appSession);
  await send('Page.navigate', { url: url.replace('tests/importer.test.html', 'index.html') }, appSession);
  await new Promise((r) => setTimeout(r, 3000));
  appState = (await send('Runtime.evaluate', {
    expression: "JSON.stringify({ signin: !document.getElementById('view-signin').hidden, upload: !!document.getElementById('btn-upload'), notice: document.getElementById('notice-text').textContent })",
    returnByValue: true,
  }, appSession)).result.result.value;

  // 2. The importer test page.
  const { result: { targetId } } = await send('Target.createTarget', { url });
  const { result: { sessionId } } = await send('Target.attachToTarget', { targetId, flatten: true });
  const deadline = Date.now() + 120000;
  while (Date.now() < deadline) {
    const r = await send('Runtime.evaluate', {
      expression: "document.getElementById('result') && document.getElementById('result').textContent",
      returnByValue: true,
    }, sessionId);
    const text = r.result?.result?.value;
    if (text && text !== 'running') { result = JSON.parse(text); break; }
    await new Promise((r2) => setTimeout(r2, 500));
  }
} finally {
  browser.close();
  proc.kill();
  server.close();
  await rm(profile, { recursive: true, force: true }).catch(() => {});
}

console.log('app page:', appState, 'errors:', pageErrors);
assert.deepEqual(pageErrors, [], 'app page threw errors');
assert.equal(JSON.parse(appState).signin, true);
console.log(JSON.stringify(result, null, 1));
assert.ok(result, 'test page did not finish');
assert.equal(result.ok, true, result.error);
assert.equal(result.duration, 330);
assert.equal(result.title, 'Team sync');
assert.equal(result.defaultStartUtc, '2026-10-02T09:15:00.000Z');
assert.deepEqual(result.progress, ['1/2', '2/2']);
assert.deepEqual(result.rec, { state: 'uploading', partCount: 2, durationSeconds: 330, sourceName: 'Team_sync.wav' });
assert.deepEqual(result.parts.map((p) => [p.index, p.rate, p.channels, p.seconds]), [[0, 16000, 1, 300], [1, 16000, 1, 30]]);
assert.ok(result.parts[0].bytes < 18 * 1024 * 1024);
assert.match(result.junk, /^ImportError: This browser can't read this file/);
assert.equal(result.short, 'The file is shorter than 1 second.');
console.log('importer browser test: PASS');
