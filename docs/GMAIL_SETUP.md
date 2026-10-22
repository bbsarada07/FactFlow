# Connecting a Gmail account (read-only)

FactFlow's mail agent can read a Gmail inbox and check every new message. It asks Google for one
permission only: **read your email** (`https://www.googleapis.com/auth/gmail.readonly`). It cannot
send, delete, label or change anything, even if a message manages to fool it.

> **Use a throwaway test Gmail account only.** Never connect a personal or work inbox to this
> prototype. Create a new Gmail account for the demo and send the test emails to it.

Without Gmail, the agent uses the **demo inbox** (the 14 emails in `backend/data/demo_emails/` and
anything uploaded), so the demo works even without Wi-Fi or OAuth.

## 1. Google Cloud project

1. Go to <https://console.cloud.google.com/> and sign in with any Google account (it does not need
   to be the test inbox).
2. Create a project, for example `factflow-demo`.
3. Open **APIs & Services → Library**, search for **Gmail API**, and click **Enable**.

## 2. OAuth consent screen

1. Open **APIs & Services → OAuth consent screen** (in newer consoles: **Google Auth Platform →
   Branding / Audience / Data access**).
2. User type: **External**. Publishing status: leave it in **Testing**.
3. App name `FactFlow (test)`, and your own address as the support and developer contact.
4. **Data access / Scopes**: add only `.../auth/gmail.readonly`. Do not add any other Gmail scope.
   FactFlow refuses and revokes a token that comes back with more than read-only access.
5. **Test users**: add the throwaway Gmail address. In Testing mode, only listed test users can
   connect.

## 3. OAuth client

1. Open **APIs & Services → Credentials → Create credentials → OAuth client ID**.
2. Application type: **Web application**.
3. **Authorized redirect URIs**: add
   `http://localhost:8000/api/mail/gmail/callback`
   (add `https://<your-backend-host>/api/mail/gmail/callback` too if you deploy the backend).
4. Copy the client ID and client secret.

## 4. Environment variables (`backend/.env`)

```
GOOGLE_CLIENT_ID=<client id>.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<client secret>
GOOGLE_REDIRECT_URI=http://localhost:8000/api/mail/gmail/callback
TOKEN_ENCRYPTION_KEY=<generated below>
OPERATOR_TOKEN=<generated below>
APPROVAL_SECRET=<generated below>
FRONTEND_URL=http://localhost:3000
```

Generate the keys (run inside `backend/` with the venv active):

```
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # TOKEN_ENCRYPTION_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"                                # OPERATOR_TOKEN
python -c "import secrets; print(secrets.token_urlsafe(32))"                                # APPROVAL_SECRET
```

- `TOKEN_ENCRYPTION_KEY` encrypts the stored Gmail tokens. If you change it, stored tokens can no
  longer be read and you must reconnect.
- Never commit `.env`. It is already git-ignored.

Restart the backend after changing `.env`.

## 5. Connect

1. In the app, enter the operator token, open the Inbox page and click **Connect Gmail**. (Without
   the UI: `POST /api/mail/gmail/connect` with the `X-Operator-Token` header, then open the
   returned `auth_url` in a browser.)
2. Sign in as the throwaway test account and allow **read** access. Google shows a warning that the
   app is unverified; that is expected for a Testing-mode app.
3. Google sends you back to `http://localhost:3000/inbox?gmail=connected`. On failure the page
   gets `gmail=error&reason=...`. The reasons are `denied`, `scope_not_allowed`, `auth_failed`,
   `not_configured`, `google_unreachable` and `missing_code`.

On the first connect the agent reads only the **20 most recent** inbox messages. After that it polls
every 45 seconds (`MAIL_POLL_SECONDS`) and takes at most 50 new messages per sync.

## 6. Reconnect, disconnect

- **Testing-mode refresh tokens can expire after about a week.** Google also revokes them if you
  remove FactFlow's access in the Google account. FactFlow then shows the account as
  `reconnect_required` (in `GET /api/mail/status`) and stops polling it; the poller keeps running.
  Click **Connect Gmail** again.
- **Disconnect** (`POST /api/mail/gmail/disconnect`) revokes the token at Google and deletes it
  from FactFlow's database.

## What to check against a live account

The tests use fixtures built from the documented Gmail API formats
(`backend/tests/fixtures/gmail/`); no live account existed when they were written. With the
throwaway account, check:

1. Consent shows read-only access only, and the callback lands on `?gmail=connected`.
2. `users.messages.list` with `labelIds=INBOX` and `q=after:<epoch seconds>` returns the expected
   messages, newest first.
3. `users.messages.get?format=raw` decodes to the exact bytes of a sent `.eml`. Send the demo
   emails as attachments-free raw mail, for example with a script or Thunderbird "Send Again".
4. A message that arrives after the first sync is picked up on the next poll, and only once.
5. Revoking access in the Google account turns the status into `reconnect_required`.
6. Disconnect removes FactFlow from the account's third-party access list.
