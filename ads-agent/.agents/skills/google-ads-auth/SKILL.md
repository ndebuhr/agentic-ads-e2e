---
name: google-ads-auth
description: >-
  One-time OAuth setup and health check for Google Ads API write scripts:
  creates ~/google-ads.yaml (client id, secret, refresh token) from the
  project's OAuth web client, with no developer token. Use this skill whenever
  a Google Ads script reports a missing google-ads.yaml, an invalid or expired
  refresh token, or an authentication error, or when setting up a new machine.
---

# Google Ads Auth Skill

Google Ads API access is project-based via OAuth (developer tokens were
retired in September 2026). Read-only work goes through the `google-ads-mcp`
server, which has its own sign-in. Write scripts in the `google-ads-experiments`
and `google-ads-asset-groups` skills use the official Python client, which
reads `~/google-ads.yaml`. This skill creates and verifies that file.

```bash
S=.agents/skills/google-ads-auth/scripts/setup_oauth.py
```

## Workflow

### 1. Check First
`$S --check` loads the config and lists the accessible customer IDs. If it
prints `OK`, nothing else is needed. A missing file or an
`invalid_grant` error means run the setup below.

### 2. One-Time Prerequisite (user action)
In the Cloud Console for your Google Cloud project, open the web OAuth client
used by `google-ads-e2e/terraform/terraform.tfvars` and add
`http://127.0.0.1:8085` to its Authorized redirect URIs. The consent screen
must include the `https://www.googleapis.com/auth/adwords` scope.

### 3. Run the Consent Flow
```bash
$S                       # reads oauth_client_id / oauth_client_secret from terraform.tfvars
$S --login-customer-id 1234567890   # add when accessing through a manager (MCC) account
```
The script prints a consent URL, opens it, waits on port 8085 for the
redirect, exchanges the code, and writes `~/google-ads.yaml` (mode 600, prior
file kept as `.bak`). Sign in as the Google account that has access to the
Ads customer. If no refresh token comes back, revoke the app at
myaccount.google.com/permissions and rerun (Google only issues one on a
fresh consent).

### 4. Verify
`$S --check` again. Then any write script works: for example
`google-ads-experiments/scripts/experiments.py list --customer ID`.

### If `--check` reports `invalid_rapt`
Google Workspace orgs can enforce Google Cloud session control, which makes
user refresh tokens for any OAuth app with Cloud scopes expire
after the admin-set session length (1 to 24 hours). Re-running the consent
flow works but only until the next expiry. Durable fixes, in order:
1. **Exempt the app** (admin): Admin console → Security → Access and data
   control → API controls → App access control, mark this OAuth client as
   Trusted; then Security → Google Cloud session control, tick "Exempt
   trusted apps".
2. **Service account** (no session control): create one in your project,
   grant domain-wide delegation for the `adwords` scope in the Admin console,
   and put `json_key_file_path` plus `impersonated_email` in
   `~/google-ads.yaml` instead of the refresh token.
3. **Lengthen the session** to 24 hours as a stopgap.

## Notes
* The client id and secret can also be passed explicitly with `--client-id`
  and `--client-secret` when tfvars is not on the machine.
* Never commit `google-ads.yaml` or paste its contents into a chat; it grants
  full account access.
* Refresh tokens last until revoked, unless the consent screen is in
  Testing mode, where they expire after 7 days; publish the app to avoid that.
