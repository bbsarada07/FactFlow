# WhatsApp checks: setup

People send FactFlow a message or a screenshot on WhatsApp. FactFlow checks it with the inbox pipeline
(hidden content, scam patterns, links, claims) and replies with a short verdict. This guide sets it up with the
**Twilio WhatsApp sandbox**, which needs no business verification. Use it for testing only.

What FactFlow stores: a salted SHA-256 of the sender's number and the result. It never stores or logs the
number or the message text (see docs/DECISIONS.md D77-D78).

## 1. Twilio sandbox

1. Create a Twilio account and open **Messaging → Try it out → Send a WhatsApp message**.
2. From your phone, join the sandbox by sending the shown `join <word>` code to the sandbox number.
3. Note the sandbox number (for example `+14155238886`), your **Account SID** and your **Auth Token**
   (Console home page). The Auth Token signs every webhook request and authorises replies: treat it as a secret.

## 2. A public https URL for the backend

Twilio must reach `POST /api/whatsapp/webhook` over https. For local testing use a tunnel (for example
`cloudflared tunnel --url http://localhost:8000`). Note the public origin, for example `https://abc.example`.
Tunnel binaries and config are git-ignored.

## 3. backend/.env

```
WHATSAPP_PROVIDER=twilio
TWILIO_ACCOUNT_SID=<Account SID>
TWILIO_AUTH_TOKEN=<Auth Token>
TWILIO_WHATSAPP_FROM=+14155238886
PUBLIC_BASE_URL=https://abc.example
WHATSAPP_HASH_SALT=<python -c "import secrets; print(secrets.token_urlsafe(32))">
FRONTEND_URL=https://<your frontend>     # optional: report links are added only for an https frontend
```

- `PUBLIC_BASE_URL` must be exactly the origin Twilio calls (scheme and host, no path). The signature covers the
  full URL, so a wrong value makes every request fail with 403.
- `WHATSAPP_HASH_SALT` must be at least 16 characters and must not change later; otherwise the same person gets a
  new hash, and their STOP and rate limit no longer apply.
- If any required value is missing, the webhook answers 503 and the backend logs one line naming the missing
  settings. The rest of the app runs normally.
- With the Auth Token but no Account SID or sandbox number, checks still run. Replies are then **not sent**:
  each one is written to the audit log as `DRY RUN`.

Restart the backend after editing `.env`.

## 4. Point the sandbox at FactFlow

In the sandbox settings, set **When a message comes in** to `https://abc.example/api/whatsapp/webhook`, method
`POST`. Save.

## 5. Try it

- Send a suspicious text, for example a fake KYC message, to the sandbox number. The first reply starts with the
  consent notice.
- Send a screenshot. FactFlow reads the text (Gemma when `GEMINI_API_KEY` is set, otherwise Tesseract) and any
  QR code. For Hindi or Telugu screenshots without Gemma, install the Tesseract `hin` and `tel` language data;
  without it, the reply says the check may be incomplete.
- Voice notes get "not supported yet".
- `STOP` turns replies off; `START` turns them back on.
- The operator can see the checks with `GET /api/inbox?source=whatsapp` (operator token).

## Limits and behaviour

| What | Value |
|---|---|
| Checks per sender | 10 per sliding hour (`WHATSAPP_MAX_PER_HOUR`); over the limit nothing is sent |
| Text | up to 4096 characters (`WHATSAPP_MAX_TEXT_CHARS`) |
| Media | the first item only, up to 5 MB (`WHATSAPP_MAX_MEDIA_BYTES`), fetched only from Twilio hosts |
| Reply | at most 900 characters: label, 2-3 reasons, next step, helpline for scam-like results, report link |
| AI unavailable or quota used up | a fixed template in English, Hindi or Telugu, marked "limited check" |
| Language | detected from the script: Devanagari = Hindi, Telugu = Telugu, otherwise English |

## Before a public launch

- **Hindi and Telugu reply texts need native-speaker review** (`backend/shield/config/whatsapp_templates.yml`).
- **Helplines are marked HUMAN MUST VERIFY** (`backend/shield/config/helplines.yml`). A person must confirm 1930
  and cybercrime.gov.in against the official source and fill in `verified_by` and `verified_on`.
- Leave the sandbox for an approved WhatsApp sender, and review Twilio's and WhatsApp's messaging policies.

## Meta Cloud API (not complete)

`WHATSAPP_PROVIDER=meta` with `META_APP_SECRET` makes the webhook check Meta's `X-Hub-Signature-256` and read
Meta's message JSON. Sending replies, downloading media and the `GET` verification handshake are **not
implemented**, so replies are recorded as DRY RUN. Use Twilio for now.

## Troubleshooting

| Symptom | Cause |
|---|---|
| 503 from the webhook, log line "WhatsApp webhook refused: missing setting(s) ..." | a required setting is empty, or the salt is shorter than 16 characters |
| 403 on every message | `PUBLIC_BASE_URL` differs from the URL set in Twilio (scheme, host, trailing path), or a wrong Auth Token |
| Check runs, but no reply arrives | `TWILIO_ACCOUNT_SID` or `TWILIO_WHATSAPP_FROM` missing (see the DRY RUN entries in the audit log), or your phone left the sandbox |
| No reply after 10 messages | the per-sender hourly limit |
