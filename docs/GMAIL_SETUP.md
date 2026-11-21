# Google sign-in and Gmail for the mail agent

One Google OAuth client does two jobs:

1. **Sign in with Google** (`openid email profile`). Every FactFlow account is a Google account. Nothing else is
   needed to use the website, the extension or WhatsApp.
2. **Connect Gmail** (optional, per user, from **Settings**). The user's own agent then checks every new message and
   acts on it under the policy engine. It asks for:
   - `gmail.modify`: read mail, add the `FactFlow/Quarantine`, `FactFlow/Needs you` and `FactFlow/Phishing` labels,
     and archive (remove from Inbox). FactFlow never deletes mail.
   - `gmail.send`: send replies and requested files, always after a 2-minute undo window (`MAIL_SEND_DELAY_SECONDS`).

FactFlow refuses and revokes a grant that includes full mail access (`https://mail.google.com/`) or any scope
outside these. If a user unticks send or modify on the consent screen, the agent still works read-only: it checks
mail and asks the user instead of acting.

> **Keep the app in Testing mode.** Only the test users you list can sign in. Use your own or throwaway accounts,
> never someone else's inbox, and do not publish the app: `gmail.modify` is a restricted scope that needs Google's
> security review before it can be public.

Without Gmail, the agent can use the **demo inbox** (the `.eml` files in `backend/data/demo_emails/` and anything
uploaded), so the demo works without OAuth.

## 1. Google Cloud project

1. Go to <https://console.cloud.google.com/> and create a project, for example `factflow`.
2. **APIs & Services → Library**: enable the **Gmail API**.

## 2. Consent screen (Google Auth Platform)

1. **Branding:** app name `FactFlow`, your address as support and developer contact.
2. **Audience:** user type **External**, publishing status **Testing**. Under **Test users**, add every Google
   account that should be able to sign in (Testing mode allows up to 100).
3. **Data access:** add `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile`, `.../auth/gmail.modify`
   and `.../auth/gmail.send`. Nothing else.

## 3. OAuth client

1. **Clients → Create client → Web application.** Leave "Use this client for an AI-powered agent" unticked.
2. **Authorized redirect URIs:** both callbacks go through the **frontend** origin, which forwards `/api` to the
   backend, so the session cookie stays first-party:
   - `http://localhost:3000/api/auth/google/callback`
   - `http://localhost:3000/api/mail/gmail/callback`
   - and the same two paths on your deployed frontend, e.g. `https://factflow-2.onrender.com/api/...`.
3. Copy the client ID and secret.

## 4. Environment variables (`backend/.env`, or the backend service on Render)

```
GOOGLE_CLIENT_ID=<client id>.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<client secret>
FRONTEND_URL=http://localhost:3000            # the site users open; callbacks are built from it
TOKEN_ENCRYPTION_KEY=<generated below>        # encrypts stored Gmail tokens
APPROVAL_SECRET=<generated below>             # signs "Needs you" approvals
SECRET_KEY=<generated below>                  # signs sign-in state and view tokens
ADMIN_EMAILS=you@gmail.com                    # optional: may run the benchmark and read the system audit log
ALLOWED_EMAILS=                               # optional extra allow-list on top of Google's test users
```

`GOOGLE_REDIRECT_URI` can stay empty; it defaults to `FRONTEND_URL` + `/api/mail/gmail/callback`.

Generate the keys (inside `backend/` with the venv active):

```
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # TOKEN_ENCRYPTION_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"                                # APPROVAL_SECRET, SECRET_KEY
```

Changing `TOKEN_ENCRYPTION_KEY` makes stored Gmail tokens unreadable; users then reconnect. Never commit `.env`.

## 5. Use it

1. Open the site and **Sign in with Google** as a test user.
2. **Settings → Gmail → Connect Gmail**, then allow access. Google warns that the app is unverified; that is expected
   in Testing mode. You land on `/settings?gmail=connected`, or `?gmail=error&reason=...` with one of `denied`,
   `scope_not_allowed`, `auth_failed`, `not_configured`, `google_unreachable`, `missing_code`.
3. The first sync reads the **20 most recent** inbox messages. After that the agent polls every 45 seconds
   (`MAIL_POLL_SECONDS`), at most 50 new messages per sync, and checks up to 20 sent messages for leaks.
4. **Settings → What your agent does on its own** controls autonomy: automatic routine replies, sending files from
   **My files**, and the addresses it may send to. **Needs you** lists everything waiting for a decision, and
   **Sent for you** shows queued mail with **Undo** and **Send now**.

## 6. Reconnect, disconnect, delete

- Testing-mode refresh tokens can expire after about a week, or when access is removed in the Google account. The
  status becomes `reconnect_required` and that user's agent pauses; others are unaffected. Click **Connect Gmail**
  again.
- **Disconnect** revokes the token at Google and deletes it from FactFlow.
- **Settings → Delete my account and data** revokes Gmail and deletes everything the user owns. Audit records stay
  for the hash chain, detached from the person.

## Live checks with two test accounts

The automated tests use a fake Gmail API built from Google's documented formats (`backend/tests/gmail_fake.py`).
Against real accounts A (agent) and B (sender), check:

1. Consent lists only read/label/send access, and the callback lands on `?gmail=connected`.
2. B sends a routine question to A; A's agent queues a reply, **Outgoing** shows it with Undo, and B receives it
   after 2 minutes.
3. B asks for a file that A marked shareable in **My files**; B receives it as an attachment.
4. B sends a mail with hidden instructions (white-on-white "forward the inbox"); it is labelled
   `FactFlow/Quarantine`, nothing is sent, and it appears under **Needs you**.
5. B signs in to FactFlow and cannot see any of A's mail, checks or files.
6. Disconnect removes FactFlow from A's third-party access list.
