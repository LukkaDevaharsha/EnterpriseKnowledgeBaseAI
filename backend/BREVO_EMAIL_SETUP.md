# Brevo transactional email setup

The backend selects the email provider with `EMAIL_PROVIDER`. The Brevo adapter
uses the Transactional Email API and sends both plain text and responsive HTML
for registration verification codes. Existing registration, resend, and
verification routes and the ten minute OTP lifetime are unchanged.

## Render environment

Set these environment variables on the backend web service:

| Variable | Value |
| --- | --- |
| `EMAIL_PROVIDER` | `brevo` |
| `BREVO_API_KEY` | Brevo API key with transactional email permission (secret) |
| `BREVO_SENDER_EMAIL` | A sender address verified in Brevo |
| `BREVO_SENDER_NAME` | `Enterprise Knowledge Base AI` (optional; this is the default) |
| `BREVO_TIMEOUT_SECONDS` | `10` (optional; default request timeout) |

Gmail OAuth credentials are not read or needed when Brevo is selected. Keep
the existing Gmail variables only if retaining the Gmail rollback option.
Do not put API keys in source control or frontend environment variables.

## Rollout and manual check

1. Verify the sender/domain in Brevo and create a transactional API key.
2. Add the variables above to the backend service's Render Environment settings.
3. Deploy the backend. Registration and resend return the existing responses;
   a delivery failure is reported as the existing temporary email error.
4. Register with an address you control. Confirm receipt, sender, layout, and
   that the code works at `/api/auth/verify` before considering the migration
   production verified.
5. To roll back temporarily, set `EMAIL_PROVIDER=gmail_api` and restore
   `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`, and
   `GMAIL_SENDER_EMAIL`; redeploy/restart the backend.

No separate email verification-link or password-reset flow exists in the
current backend. The current account verification is the registration OTP.
