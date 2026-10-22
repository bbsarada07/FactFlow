# FactFlow for Android: floating overlay

Most misinformation in India travels inside WhatsApp, which no browser extension can reach on a phone. The Android client
puts a FactFlow bubble on top of **any** app, so a user can check a forward without copying, switching apps or
leaving the chat.

> **Status:** design prototype. `overlay_mockup.html` is an interactive mock of the full flow, used for the demo video.
> No APK has been built yet. The backend API it would call (`POST /api/verify` with `image_base64`) is complete and tested.

## How it works

1. **Floating bubble (no root needed).** A small red **V** bubble is drawn with `TYPE_APPLICATION_OVERLAY`
   (`SYSTEM_ALERT_WINDOW` permission, granted once in system settings). It can be dragged to any screen edge.
2. **Long press → draw a rectangle.** Tapping the bubble dims the screen and lets the user drag a rectangle around the
   message, post or image they want to check.
3. **Capture the region.** The app captures only that rectangle:
   - **Accessibility Service** (`AccessibilityService` + `takeScreenshot()` on Android 11+) when the user enables it, or
   - **MediaProjection** as a per-session fallback that needs no accessibility permission.
4. **On-device OCR.** ML Kit Text Recognition (Latin + Devanagari models) extracts the text locally. The pixels never
   leave the phone unless OCR finds nothing, in which case the cropped image is sent as `image_base64`.
5. **Verify.** The text is posted to `POST /api/verify` with `platform: "whatsapp"`. Progress streams from
   `GET /api/stream/{request_id}` (SSE).
6. **Verdict notification.** A bottom sheet slides up with the verdict, confidence, the true fact, and a
   **Reply in chat** button that shares the ready-made WhatsApp correction through the system share sheet.

## Planned architecture

| Component | Android API |
|---|---|
| Floating bubble and selection layer | `WindowManager` + `TYPE_APPLICATION_OVERLAY` in a foreground `Service` |
| Screen region capture | `AccessibilityService.takeScreenshot()` (API 30+), `MediaProjection` fallback |
| OCR | Google ML Kit Text Recognition v2 (on-device) |
| Networking | OkHttp + `okhttp-sse` for the live agent stream |
| Reply | `Intent.ACTION_SEND` targeted at `com.whatsapp` |

**Privacy:** nothing is captured until the user draws a rectangle, only the selected region is processed, and the
Accessibility Service only takes screenshots on demand. It does not read the screen continuously.

## Using the mockup

Open `overlay_mockup.html` in any browser (no server needed).

- Tap the red **V** bubble, then drag a rectangle over a forwarded message.
- Or press **▶ Auto demo** for a scripted run that is easy to screen-record.
- **Reply in chat** posts the generated correction into the mock chat.

The verdicts in the mockup are pre-filled from real FactFlow pipeline runs on the same text. They are not computed
live in the page.
