# Invite-beta local evidence (2026-09-10)

- `durable-worker-report.json`, `durable-worker-proof.png`: real isolated PostgreSQL tenant registration/owned job/artifact visibility → claim → supervised Python subprocess → Potrace/FontForge → downloaded TTF loaded by FreeType. Local filesystem storage, not hosted Supabase Storage. One glyph, one run; not throughput or cost evidence.
- `beta-browser-report.json`, `beta-login-mobile.png`: production Next build checks with runtime invite-beta configuration. Real unauthenticated/cross-origin rejections; session/login/logout **UI** portion uses explicit browser mocks. No real hosted account or refresh canary is claimed.

See [validation](../../VALIDATION.md) for fresh suite results and limitations, [deployment runbook](../../DEPLOYMENT.md) for the remaining hosted acceptance matrix, and [nature evidence](../nature-evidence/README.md) for real-photo successes and failures.

- `efficientsam-browser-report.json`, `slimsam-browser-report.json`: final production-preview browser flows against actual local ONNX weights, mask repair/undo/reset, generated FontFace, and real downloaded TTF. Synthetic diagnostic input, not real-photo accuracy evidence. The classical browser path also passed.
