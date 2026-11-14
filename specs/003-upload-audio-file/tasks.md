# Tasks: Transcribe an Uploaded Audio File

- [x] T301 Spec, checklist, plan
- [x] T302 [P] Pure helpers `mixToMono`, `floatToInt16`, `partRanges` in `frontend/wav.js` + tests in `frontend/tests/wav.test.mjs`
- [x] T303 `store.putPart`, cleanup of `importing` records in `frontend/store.js`
- [x] T304 `frontend/importer.js`: read/decode, validate limits, split into WAV parts, create the recording
- [x] T305 Upload UI (button, file picker, title/date form, progress, cancel) in `frontend/index.html`, `frontend/app.js`, `frontend/styles.css`
- [x] T306 Backend `sourceName` (validate, manifest, `Source file:` header) in `backend/src/core.py`; send it from `frontend/api.js`; tests
- [x] T307 README + 001 API contract; gates; deploy
