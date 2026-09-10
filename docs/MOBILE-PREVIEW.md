# Mobile-only alpha over public HTTPS

Use `/mobile` for the focused phone interface. It reuses the existing authenticated
capture, upload, project and font-build APIs; there is no duplicate ML service or
native-app implementation. The desktop studio at `/` stays unchanged on the normal
local server. On the dedicated public preview, `/` redirects to `/mobile`.

## Start

Keep the normal alpha stack running (API/worker on loopback):

```sh
./scripts/alpha-dev.sh --api-port 8000 --web-port 3001
```

Then run the temporary phone preview in a separate terminal:

```sh
python3 scripts/alpha_mobile.py
```

The launcher requires the official `cloudflared` CLI at `.alpha/bin/cloudflared`;
pass `--cloudflared /path/to/cloudflared` for another installation. It validates
private-alpha configuration first, starts a temporary HTTPS tunnel to loopback port
3009, obtains its exact public origin, then builds and starts Next in **production
mode** using an isolated `.next-mobile` directory. It does not expose Next dev or
Python port 8000. No CORS wildcard or request-derived auth origin is introduced.

The ready URL is printed and saved in ignored `.alpha/mobile-preview.json`. Open
its `/mobile` URL in Safari on iPhone and Chrome on Android. Use your existing
alpha invitation credentials; secrets are not written to this document or the URL.
Automated canary credentials can be stored privately in `.alpha/local-test-login.json`; this file is not shipped or created for a fresh clone. See the setup below.

The temporary link uses publicly trusted HTTPS: **no local CA installation and no
same-Wi-Fi requirement**. Keep the computer awake, online, and both launchers running.
Ctrl-C in the preview terminal stops the web preview and tunnel, leaving the normal
alpha stack alone. Each new run usually gets a different URL and needs a fresh login.

## API surface

All browser traffic is same-origin at the printed HTTPS host:

| Route | Purpose |
| --- | --- |
| `POST /api/auth/login` | Start the alpha session; email + password, exact Origin |
| `GET /api/auth/session` | Check session |
| `POST /api/uploads` then returned `PUT /api/objects/...` | Upload photo/mask |
| `POST /api/capture/foreground` | Advanced foreground/ML extraction |
| `POST /api/capture/candidates` | Automatic ink/object SVG alternatives |
| `POST /api/capture/page` | Existing page-corner detection |
| `/api/projects` | Existing saved projects |
| `POST /api/jobs`, `GET /api/jobs/:jobId` | Build and poll font |
| `POST /api/auth/logout` | Revoke session |

Account, uploads, extraction, projects and builds remain session-gated, with
owner checks and existing quotas. See [alpha API contracts](ALPHA-API.md) for request
schemas. The camera frames are captured by the browser, then passed into this same
pipeline; exposing an API alone would not provide a phone camera UI.

## Security and limitations

- The URL is publicly reachable; the invitation login is the access gate. Do not
  publish test credentials. Anyone who has them can use that test account.
- Cloudflare terminates HTTPS and proxies traffic. This is a third-party test
  transport, not a permanent production deployment or an end-to-end encryption claim.
- Upload no highly sensitive material for this test. Production privacy, domain,
  monitoring, abuse controls and hosting still need their normal launch review.
- Quick Tunnels are temporary/testing-only, have no availability SLA, limit
  concurrent in-flight requests and do not support SSE. This app polls jobs, so
  it does not depend on SSE.
- Camera hardware/lens exposure is browser-controlled. Test rear default, camera
  selection, focus, rotation, capture/redo, gallery fallback, and stopping the camera
  when closing/hiding. The [phone checklist](PHONE-TESTING.md) applies; its local
  certificate setup is unnecessary for this public HTTPS link.

## Official tooling references

- [Cloudflare Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)
- [Official cloudflared downloads](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/)

The development machine's ignored tool install was verified against the GitHub
release asset SHA-256: cloudflared **2026.9.0**, Darwin arm64 archive,
`c0eccb3758420d1f4e46cbf2b8ecde01d9802a154232a817f25133340009fcc7`.
This is a local test tool, not a new application package dependency.


## Automated phone canary

First provision a disposable invited account in the **host-local** alpha database
using `scripts/alpha_admin.py create-user --email ...` (see the main runbook).
Start both launchers above. This test uses a real account, consumes preview/build
allowances and writes real images/fonts to that account. Use nonsensitive fixtures;
do not point it at a production account.

Create the ignored test-login file interactively—no shipped default password:

```sh
python3 -c 'import getpass,json,os; from pathlib import Path; Path(".alpha").mkdir(exist_ok=True); data={"email":input("Disposable alpha email: "),"password":getpass.getpass("Password: ")}; fd=os.open(".alpha/local-test-login.json",os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600); os.fchmod(fd,0o600); stream=os.fdopen(fd,"w"); json.dump(data,stream); stream.close()'
cd web
npx playwright install chromium
npm run test:e2e:mobile
# Optional: use a real permissioned test photo instead of the synthetic camera frame.
HFM_E2E_PHOTO=/absolute/path/to/your-letter.jpg npm run test:e2e:mobile
```

The suite reads `.alpha/mobile-preview.json`, verifies HTTPS/login/origin gates,
exercises camera access and font generation, and logs out. The real-photo variant
also selects and downloads a true SVG candidate. Traces are disabled to avoid
recording session credentials. Screenshots/fonts are in ignored `web/test-results`;
protect and remove them when finished. Disable the disposable account afterward.
These tests emulate mobile Chromium; actual Android/iOS camera acceptance remains
manual. `cloudflared` and the temporary public tunnel are testing tools, not required
for permanent HTTPS deployment.
