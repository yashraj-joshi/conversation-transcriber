# Tasks: Delete & Restore Transcripts; AI Titles and Summaries

- [x] T401 Spec, checklist, plan
- [x] T402 Core: trash key mapping, header parse/set, summary request build/parse in `backend/src/core.py` (+ tests)
- [x] T403 OpenRouter chat call in `backend/src/openrouter_client.py` (+ tests)
- [x] T404 Transcriber: summary after assembly; `retitle` action (+ tests)
- [x] T405 API: delete, list deleted, restore, trash-aware GET, titles/summaries in month list (+ tests)
- [x] T406 Infra: `summary-model` SSM parameter, `trash/` lifecycle, IAM, routes, env, outputs
- [x] T407 Frontend: Deleted chip, list with title/summary, Delete/Restore in viewer, Hide on device list, blank upload title
- [x] T408 Scripts (`retitle.sh`, `set-model.sh --summary`), README, contracts
- [x] T409 Gates, deploy, backfill existing transcripts, push
