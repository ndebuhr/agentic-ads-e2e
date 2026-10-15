#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["google-auth-oauthlib>=1.2", "pyyaml>=6", "google-ads>=32,<33"]
# ///
"""One-time OAuth consent flow that writes ~/google-ads.yaml for the Google Ads
client library. Uses the web OAuth client from terraform.tfvars (no developer
token; Google Ads API access is project-based via OAuth).

Prerequisite: in the Cloud Console, add http://127.0.0.1:8085 to the web
client's "Authorized redirect URIs".

Usage:
  scripts/setup_oauth.py [--tfvars PATH] [--client-id ID --client-secret SECRET]
                         [--login-customer-id MCC_ID] [--port 8085]
  scripts/setup_oauth.py --check      # verify ~/google-ads.yaml by listing accessible customers
"""
import argparse, os, re, socket, sys, webbrowser
from urllib.parse import parse_qs, urlparse
import yaml
from google_auth_oauthlib.flow import Flow

os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

SCOPES = ["https://www.googleapis.com/auth/adwords"]
HERE = os.path.dirname(os.path.realpath(__file__))
DEFAULT_TFVARS = os.path.normpath(os.path.join(HERE, "../../../../google-ads-e2e/terraform/terraform.tfvars"))
ALT_TFVARS = os.path.normpath(os.path.join(HERE, "../../../../agentic-ads-e2e/google-ads-e2e/terraform/terraform.tfvars"))

def read_tfvars(path):
    vals = {}
    for line in open(path):
        m = re.match(r'\s*(oauth_client_id|oauth_client_secret)\s*=\s*"([^"]*)"', line)
        if m: vals[m.group(1)] = m.group(2)
    return vals.get("oauth_client_id"), vals.get("oauth_client_secret")

def wait_for_code(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port)); s.listen(5)
        while True:
            conn, _ = s.accept()
            with conn:
                req = conn.recv(4096).decode(errors="ignore")
                path = req.split(" ")[1] if " " in req else "/"
                qs = parse_qs(urlparse(path).query)
                if "code" in qs:
                    body = "Authorized. You can close this tab."
                    conn.sendall(f"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: {len(body)}\r\n\r\n{body}".encode())
                    return qs.get("code")[0]
                elif "error" in qs:
                    body = f"OAuth Error: {qs.get('error')}"
                    conn.sendall(f"HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain\r\nContent-Length: {len(body)}\r\n\r\n{body}".encode())
                    sys.exit(f"OAuth error received: {qs}")
                else:
                    body = "Waiting for Google authorization redirect..."
                    conn.sendall(f"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: {len(body)}\r\n\r\n{body}".encode())

def check(path):
    if not os.path.exists(path):
        sys.exit(f"{path} not found; run this script without --check to create it")
    from google.ads.googleads.client import GoogleAdsClient
    from google.auth.exceptions import RefreshError
    try:
        client = GoogleAdsClient.load_from_storage(path)
        ids = [rn.rsplit("/", 1)[1] for rn in client.get_service("CustomerService").list_accessible_customers().resource_names]
    except RefreshError as e:
        sys.exit(explain_refresh_error(e, path))
    print("OK: token valid; accessible customer IDs:", ", ".join(ids) or "(none)")

def explain_refresh_error(e, path):
    msg = str(e)
    if "rapt" in msg.lower() or "Reauthentication is needed" in msg:
        return (f"Refresh token in {path} was rejected with invalid_rapt: the Workspace org enforces Google Cloud "
                "session control, so user refresh tokens expire after the admin-set session length. Options: "
                "re-run this script to consent again (short-term), have the Workspace admin exempt this OAuth client "
                "from session control or lengthen the session, or switch to a service account with domain-wide "
                "delegation (see the google-ads-auth skill).")
    if "invalid_grant" in msg:
        return f"Refresh token in {path} is invalid or revoked; re-run this script to create a new one."
    return f"Auth failed: {msg}"

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tfvars", default=DEFAULT_TFVARS)
    ap.add_argument("--client-id"); ap.add_argument("--client-secret")
    ap.add_argument("--login-customer-id", help="MCC customer ID (digits only), if accessing via a manager account")
    ap.add_argument("--port", type=int, default=8085)
    ap.add_argument("--code", help="Authorization code or redirect URL from the browser")
    ap.add_argument("--out", default=os.path.expanduser("~/google-ads.yaml"))
    ap.add_argument("--check", action="store_true", help="verify the existing config instead of creating one")
    a = ap.parse_args()
    if a.check:
        return check(a.out)
    cid, csec = a.client_id, a.client_secret
    if not (cid and csec):
        tfpath = a.tfvars if os.path.exists(a.tfvars) else (ALT_TFVARS if os.path.exists(ALT_TFVARS) else None)
        if not tfpath:
            sys.exit(f"no client id/secret given and tfvars not found at {a.tfvars} or {ALT_TFVARS}")
        cid, csec = read_tfvars(tfpath)
    if not (cid and csec):
        sys.exit("could not determine oauth_client_id / oauth_client_secret")

    redirect = f"http://127.0.0.1:{a.port}"
    flow = Flow.from_client_config(
        {"web": {"client_id": cid, "client_secret": csec,
                 "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                 "token_uri": "https://oauth2.googleapis.com/token"}},
        scopes=SCOPES, redirect_uri=redirect)
    url, _ = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    print("Open this URL in a browser signed in to the Google Ads account:\n\n" + url + "\n")
    if a.code:
        raw = a.code.strip()
        if "code=" in raw:
            code = parse_qs(urlparse(raw).query).get("code", [raw])[0]
        else:
            code = raw
    else:
        print(f"Waiting for the redirect on {redirect} ... (this URI must be authorized on the web client)")
        webbrowser.open(url)
        code = wait_for_code(a.port)
    if not code:
        sys.exit("no authorization code received")
    flow.fetch_token(code=code)
    rt = flow.credentials.refresh_token
    if not rt:
        sys.exit("no refresh token returned; revoke prior consent at myaccount.google.com/permissions and retry")

    cfg = {"client_id": cid, "client_secret": csec, "refresh_token": rt, "use_proto_plus": True}
    if a.login_customer_id:
        cfg["login_customer_id"] = re.sub(r"\D", "", a.login_customer_id)
    if os.path.exists(a.out):
        os.replace(a.out, a.out + ".bak")
    with open(a.out, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    os.chmod(a.out, 0o600)
    print(f"wrote {a.out} (mode 600). Test with: scripts/experiments.py list --customer <ID>")

if __name__ == "__main__":
    main()
