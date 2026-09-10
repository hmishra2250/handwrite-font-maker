# Web dependency safety review

Reviewed 2026-09-10 using the actual lockfile, npm registry and upstream advisories. The isolated dependency experiment reported zero audit findings with the patch set below; integrated verification is recorded in `../VALIDATION.md`.

## Decision

No new packages and no `npm audit fix --force`. Replace existing `latest` versions with exact versions, and update affected packages within current major versions:

- Next + eslint-config-next: 16.3.4.
- Vitest + mocker: 4.1.11, not a forced migration to Vitest 5.
- PostCSS: 8.5.28.
- Existing React/Supabase/testing/types packages pinned to their current lockfile versions; compatible transitive security fixes via non-force lockfile update.

## Primary evidence

- [Next advisory GHSA-p293-qw3h-jr36](https://github.com/advisories/GHSA-p293-qw3h-jr36)
- [Next advisory GHSA-2xp9-vwfh-vxw4](https://github.com/advisories/GHSA-2xp9-vwfh-vxw4)
- [Vitest mocker advisory](https://github.com/advisories/GHSA-82fw-gwwq-j7x9)
- [PostCSS advisory](https://github.com/advisories/GHSA-fxqj-rqcc-2cmp)
- npm registry metadata for resolved versions and peers; `npm audit` against the generated lockfile.

The baseline audit was 14 affected packages (1 critical, 9 high, 3 moderate, 1 low). Zero audit findings only means no known registry advisories for the scanned dependency graph at that time; it is not a security certification or a replacement for tenant isolation and input/abuse testing.
