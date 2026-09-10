# Private alpha API contract

The browser uses only same-origin Next `/api/*` routes. Next forwards the opaque
session as `Authorization: Bearer …` and a server-only `x-internal-api-key` to
Python. Python independently verifies the active account/session on **every**
protected request. Neither an account ID nor a plan sent by the browser grants
access. The Python port and local object volume must not be public.

## Auth and commercial boundary

All JSON responses use `Cache-Control: no-store`. Errors use
`{"error":{"code":"…","message":"…"}}`. Mutation requests require an exact
`Origin` matching `SITE_URL` at Next. The internal key is required for the Python
auth routes too; it is never a browser credential.

| Browser endpoint | Method/body | Success | Other expected statuses |
|---|---|---|---|
| `/api/auth/login` | POST `{email,password}` | 200 `{authenticated:true,mode:"private_alpha",user:{id,email}}`; session cookie | 400 malformed, 401 invalid credentials, 403 origin, 429 rate limited, 503 backend unavailable |
| `/api/auth/session` | GET | 200 authenticated user/mode | 401 missing/expired/revoked session |
| `/api/auth/logout` | POST | Session revoked and cookie cleared | 403 origin, 503 revocation unavailable; do not pretend server logout succeeded |
| `/api/auth/password` | POST `{currentPassword,newPassword}` | 200 `{ok:true,authenticated:false}`; revoke **all** sessions, clear current cookie, sign in again | 400 password policy, 401 current password/session, 403 origin, 429 throttled |
| `/api/billing/catalog` | GET, public | Catalog below | 503 if alpha backend unavailable |
| `/api/account` | GET, authenticated | Account/limits below | 401 session, 503 backend unavailable |
| `/api/billing/checkout` | POST `{offerId:"single"\|"three_pack"}`, authenticated | **None in this release** | 400 invalid offer, 401 session, 403 origin, **503 PAYMENT_NOT_CONFIGURED** |

Python routes omit `/api`, except existing capture aliases. Python login returns
`{accessToken,expiresIn:86400,user}` **only to Next**; Next must strip tokens from
browser JSON. Logout/password change use the same bearer credential. There is no
public signup, email delivery, password-reset link, webhook endpoint or payment
success callback. Operator account creation/reset is a trusted-host CLI action.
Passwords are 12–256 characters and at most 1024 UTF-8 bytes. The alpha uses salted
scrypt (N=32768, r=8, p=3), random opaque 256-bit sessions stored only as hashes,
24-hour expiry and persistent per-account authentication budgets and bounded KDF concurrency. Password
change/reset and disabling an account revoke existing sessions. An incorrect current
password preserves the session; an expired/revoked session clears the browser
cookie. Password-policy errors remain 400, and throttling remains 429.

On HTTPS, use a Secure/HttpOnly/SameSite host-only cookie. Explicit loopback HTTP
uses a different non-Secure cookie name for development; never use that exception
on a public origin. There is no session token in localStorage.

Catalog shape:

```json
{
  "currency": "USD",
  "billingEnabled": false,
  "offers": [
    {"id":"single","name":"Make one font","priceCents":1200,"projects":1},
    {"id":"three_pack","name":"Make three fonts","priceCents":2900,"projects":3}
  ],
  "alpha": {"name":"Private alpha","priceCents":0,"inviteOnly":true},
  "notice":"Private alpha is free for invited accounts. Paid offers are planned, not available to purchase. No card is collected."
}
```

Account shape (limits are configuration values, not remaining balances):

```json
{
  "user":{"id":"server-assigned-uuid","email":"invited@example.test"},
  "plan":{"id":"private_alpha","name":"Private alpha","billingEnabled":false},
  "limits":{"dailyUploads":300,"dailyUploadBytes":524288000,"dailyPreviews":200,"dailyBuilds":10,"activeJobs":2},
  "retention":{"projectDays":7,"downloadHours":24}
}
```

Do not treat these free-alpha safety limits as prepaid credits. The $12/$29
catalog is planned packaging only. `BILLING_ENABLED=true` still fails startup;
a gateway adapter, verified webhooks and a transactional purchase/reservation/
refund ledger must be implemented and tested together before that restriction
can be removed. Browser redirects must never grant paid entitlements.

## Existing font contracts, now behind alpha login

- `POST /api/uploads`: `{filename,contentType,sizeBytes}` → a single-use upload
  intent `{objectKey,uploadUrl,method:"PUT",…}`. PUT bytes to the same-origin
  `uploadUrl`; registered type and byte count must match. Ownership is assigned
  from the verified account, not the path supplied by a caller.
- `POST /api/capture/page` and `/api/capture/foreground`: reference an uploaded
  image owned by this user. Page detection and foreground options retain their
  existing validation. Optional ML runs in the Python backend with local weights.
- `POST /api/capture/candidates`: `{inputPhoto,rectangle,stage,context?}` where
  `stage` is `ink` or `objects`. Returns `{stage,candidates,failures}`. Each
  candidate has an ID/label, true path-based `svgDataUrl`, binary `maskDataUrl`,
  normalized width/height, actual method, optional polarity and warnings. Context
  accepts character, baseline, threshold, invert and current method/style settings
  for private diagnostics. Both stages validate source ownership and each consumes
  one preview allowance. Ink returns first; optional object work runs separately
  with per-method deadlines. Accepting a fast choice never requires ML completion.
  Proxy errors distinguish invalid output (502), upstream unavailable (502) and
  timeout (504). A busy optional worker does not discard existing candidates.
- `POST /api/jobs`: `{inputPhoto,font,capture}` → queued job. Guided capture uses
  `mode:"guided",format:"mask-v1",glyphs:[{char,inputPhoto,baseline,scale,spacing}]`.
  One to 94 unique printable non-space ASCII labels; accepted PNG masks only.
  Metadata, aggregate size, reference ownership and quota are server-validated.
- `GET /api/jobs/:id`: poll status, stage, warnings, error and artifacts. Successful
  artifacts have same-origin owner-gated URLs. No guessed demo success in alpha.
- `GET/POST /api/projects`, `GET/PUT/DELETE /api/projects/:id`: persist the current
  accepted masks/settings. PUT carries `revision`; stale edits return 409
  `PROJECT_REVISION_CONFLICT`, not last-writer-wins data loss.
- `GET /api/objects/*`: authenticated private source/artifact access.
- `DELETE /api/jobs/:id`: revoke the job/attempt and schedule safe object cleanup.
- Feedback/events retain existing consent and bounded-input rules.

Unknown/other-owner jobs and projects are not disclosed; object access is denied
without confirming another user's file contents. Quotas use 429; retrying should
respect the displayed limits. Session expiry requires signing in, not switching
to an anonymous local mode. Existing detailed types and validation live in
`web/lib/contracts.ts`, `web/lib/projects.ts`, and
`src/handwrite_font_maker/web/contracts.py` / `project_store.py`.

## Verification contract

`tests/test_alpha_auth.py` exercises real Python HTTP auth/account/checkout plus
session persistence, revocation and concurrent rate reservations.
`tests/test_alpha_sqlite.py` exercises durable storage, leases and tenant boundaries.
Web unit tests validate the cookie/proxy boundary. The independent
`web/playwright.alpha.config.ts` starts real Next + Python + a leased worker with
throwaway SQLite data; its tests exercise login and an actual exported font, not
mock API success. See [deployment instructions](PRIVATE-ALPHA.md) for commands and
remaining host/provider acceptance checks.

Security references: [Python scrypt](https://docs.python.org/3/library/hashlib.html#hashlib.scrypt),
[OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html),
[OWASP sessions](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html),
[OWASP CSRF](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html),
[SQLite WAL](https://www.sqlite.org/wal.html). This is a bounded private-alpha
implementation, not a claim of a comprehensive independent security audit.
