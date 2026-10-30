# Gmail API sender setup

Install the local backend requirements, then run this command from the project root on the Windows computer that has the OAuth Desktop client:

```powershell
python backend/tools/authorize_gmail_sender.py
```

Enter the OAuth Client ID when prompted and the Client Secret at the hidden prompt. In the browser, sign in as `webmanagerepm01@gmail.com` and grant the `gmail.send` permission. The utility saves only the refresh token and sender metadata to `backend/.secrets/gmail_refresh_token.json`; that directory is ignored by Git.

Copy only the `refresh_token` string from that JSON file into Render's `GMAIL_REFRESH_TOKEN` secret. Do not upload or commit the local JSON file. Set `EMAIL_PROVIDER=gmail_api`, `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_SENDER_EMAIL=webmanagerepm01@gmail.com`, and `GMAIL_TIMEOUT_SECONDS=10` in Render.

For a Google OAuth consent screen in External / Testing mode, the refresh token expires after seven days for this Gmail scope. Publish the OAuth app before relying on it for production email delivery.
