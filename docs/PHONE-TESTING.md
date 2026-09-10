# Test the alpha on a real phone

For immediate testing without certificates or same-Wi-Fi setup, use the
[public HTTPS mobile preview](MOBILE-PREVIEW.md). The LAN-only alternative below
remains available when you do not want public sharing.

Desktop stays upload-only. Touch-first mobile browsers offer live rear-camera
capture and upload. The browser—not Handwrite—decides which physical/logical
cameras it exposes. No camera permission is requested until **Take photo**.

## Local HTTPS, without a public tunnel

The normal private-alpha stack must already be running:

```sh
./scripts/alpha-dev.sh --api-port 8000 --web-port 3001
```

On the same computer, find its **Wi-Fi IPv4 address** (`ipconfig getifaddr en0`
on many Macs). Use the actual address, not the example below. Connect both phone
and computer to the same trusted Wi-Fi; guest-network client isolation can prevent
connections. No router port forwarding is needed or recommended.

```sh
# One-time preparation. Creates certificates only; installs no system trust.
python3 scripts/alpha_phone.py --host 192.168.1.3 --prepare

# Run alongside the existing localhost alpha. Stop with Ctrl-C when finished.
python3 scripts/alpha_phone.py --host 192.168.1.3
```

Open **https://192.168.1.3:3443** on your phone after installing/trusting the test
certificate below. Sign in with your existing alpha account. The localhost desktop
studio remains at http://localhost:3001 with its own session cookie.

Only the web preview listens on the private LAN address. The API stays loopback-only.
The preview uses an isolated `.next-phone` build directory, the same backend,
exact HTTPS `SITE_URL`, secure cookies and the existing origin/login gates. It is a
**development preview for trusted Wi-Fi**, not production hosting or an internet URL.

## Trust the dedicated test certificate

Transfer **only** `.alpha/phone-tls/handwrite-phone-ca.cer` to your phone (AirDrop,
USB, or another private transfer). The `.crt` copy contains the same public CA
certificate and can be used if an Android certificate picker expects that extension.
**Never transfer `ca.key` or `server.key`.** Do not upload the TLS directory to Git.

Installing a CA is a security-sensitive, user-controlled device action. This tool
never installs it automatically. Use this dedicated CA only for testing, keep its
private key on your computer, and remove the installed CA from your phone afterwards.
The server certificate lasts 7 days; the CA lasts 30 days. Trusting the CA does not
make the alpha production-ready.

- **iPhone:** open the transferred certificate, install its downloaded profile in
  Settings, then enable full trust for **Handwrite phone testing ONLY** under
  Settings → General → About → Certificate Trust Settings.
- **Android/Samsung:** use Settings search for **Install a certificate** or
  **CA certificate**, choose the CA certificate option and the transferred file.
  Menu names vary with Android/One UI. This is not a Wi-Fi client certificate.
- Do not use “proceed anyway” as the setup: the camera needs a genuinely trusted
  secure context. If the certificate is expired or the computer IP changed, stop
  the preview and prepare a fresh directory with `--tls-dir .alpha/phone-tls-new`.
  Install that new public CA and remove the old test CA.

For wider alpha sharing, use a real HTTPS deployment with publicly trusted TLS
instead of asking customers to install test CAs. No public tunnel is opened by this
script, and no device-trust policy is weakened.

## S23 Ultra / iPhone 14 Pro acceptance checklist

Use Chrome on the S23 Ultra and Safari on the iPhone first. Record OS/browser
versions and report the exact camera labels shown; do not assume numbered cameras
are wide/ultrawide/telephoto.

1. **Login:** unauthenticated users cannot capture/build. Existing invitation works.
2. **Rear default:** Take photo opens a live rear-facing view after permission.
   Permission is requested only on tap. No microphone permission is needed.
3. **Cameras:** try every listed camera; preview must change or show a recoverable
   error. Reopening should prefer the rear camera again.
4. **Capture:** photograph a dark handwritten A, accept its mask, move to B, and
   retake. Also try a markerless sheet and a distinct leaf/object.
5. **Orientation:** portrait and landscape photos remain upright and contain what
   the preview showed. Capture uses the actual video dimensions, not screen size.
6. **Cleanup:** close the camera, change tabs/lock the phone, then return. The
   browser camera indicator should turn off; starting again requires a tap.
7. **Failure:** deny camera permission, cancel native camera fallback, then upload
   a gallery image. Existing accepted characters must remain intact.
8. **Build:** accept a few glyphs, build and download. Save/open a project to test
   continuation on desktop; unsaved drafts are not automatically synchronized.
9. **Layout:** no horizontal overflow; capture/close controls stay reachable with
   browser bars visible and in landscape.

Browser-automated fake cameras test stream lifecycle, permission errors and image
handoff, **not physical lenses, autofocus, exposure, native pickers or image quality**.
Do not call physical-device support verified until these checks are completed.

## Troubleshooting

- **Page unreachable:** same Wi-Fi, correct IP, no client isolation, computer awake,
  local firewall permits this LAN port, both alpha and phone-preview processes running.
- **Login fails:** use the exact printed HTTPS URL, not another hostname/IP. Origin
  validation is intentionally strict. No changes to CORS or cookie security needed.
- **Camera unavailable:** check certificate trust, browser camera permission and
  whether another app is using the camera. Keep gallery upload as the fallback.
- **Few camera choices:** browsers may expose fewer cameras than the hardware has;
  a logical rear camera may select its physical lens internally.
- **After testing:** stop the phone preview and remove the dedicated test CA/profile
  from the phones. The ordinary localhost alpha is independent and can remain running.

## Official references

- [Apple: trust a manually installed root certificate](https://support.apple.com/en-us/102390)
- [Google: Android/Samsung certificate installation](https://support.google.com/device-usage-study-help/answer/15713321?co=GENIE.Platform%3DAndroid&hl=en)
- [Google: add/remove individual user certificates](https://support.google.com/pixelphone/answer/2844832?hl=en)
- [MDN: getUserMedia, constraints and secure contexts](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)
- [MDN: enumerateDevices](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/enumerateDevices)

Remove **only the Handwrite test certificate/profile** when finished, not all device
credentials. Device menus vary by OS/One UI version. The Android instructions are
for browser testing, not a claim that a future native app will trust user-installed CAs.
