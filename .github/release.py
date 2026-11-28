"""Store steps for the Sompio Vault release workflow.

  python .github/release.py check            tests that the Chrome Web Store and Firefox Add-ons keys work
  python .github/release.py chrome  ZIP      uploads a new version to the Chrome Web Store and submits it
  python .github/release.py firefox ZIP NOTES  submits a new version to Firefox Add-ons with its notes

Keys come from the repository secrets (see release.yml). Nothing secret is ever printed.
"""
import json, os, sys, time, uuid

import jwt
import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

CWS_ITEM = "ibhofkgjkbhmmlmfcnehfknokeipmijp"
AMO_ADDON = "browser@sompio.org"
CWS = "https://chromewebstore.googleapis.com"
AMO = "https://addons.mozilla.org/api/v5"


def fail(msg):
    print(f"::error::{msg}")
    sys.exit(1)


# ---------- Chrome Web Store ----------

def cws_token():
    raw = os.environ.get("CWS_SERVICE_ACCOUNT_JSON", "")
    if not raw.strip():
        fail("The CWS_SERVICE_ACCOUNT_JSON secret is missing.")
    try:
        info = json.loads(raw)
    except ValueError:
        fail("The CWS_SERVICE_ACCOUNT_JSON secret isn't the whole key file. Paste the full .json contents.")
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/chromewebstore"])
    creds.refresh(Request())
    print(f"::add-mask::{creds.token}")
    return creds.token


def cws_publisher():
    p = os.environ.get("CWS_PUBLISHER_ID", "").strip()
    if not p:
        fail("The CWS_PUBLISHER_ID secret is missing.")
    return p


def cws_status(token):
    r = requests.get(f"{CWS}/v2/publishers/{cws_publisher()}/items/{CWS_ITEM}:fetchStatus",
                     headers={"Authorization": f"Bearer {token}"}, timeout=60)
    if r.status_code == 403:
        fail("Chrome Web Store refused the service account (403). Check its email is added in the "
             "dashboard's Settings, and that the Chrome Web Store API is enabled in the same Google Cloud project.")
    if r.status_code == 404:
        fail("Chrome Web Store didn't find the item (404). Check the CWS_PUBLISHER_ID secret.")
    if not r.ok:
        fail(f"Chrome Web Store status check failed: HTTP {r.status_code} {r.text[:300]}")
    return r.json()


def chrome(zip_path):
    token = cws_token()
    with open(zip_path, "rb") as f:
        r = requests.post(f"{CWS}/upload/v2/publishers/{cws_publisher()}/items/{CWS_ITEM}:upload",
                          headers={"Authorization": f"Bearer {token}"}, data=f, timeout=300)
    if not r.ok:
        fail(f"Chrome upload failed: HTTP {r.status_code} {r.text[:500]}")
    state = r.json().get("uploadState")
    for _ in range(30):
        if state != "IN_PROGRESS":
            break
        time.sleep(10)
        state = cws_status(token).get("lastAsyncUploadState", state)
    if state not in ("SUCCEEDED", "SUCCESS"):
        fail(f"Chrome upload didn't go through (state: {state}). {r.text[:500]}")
    print("Chrome: package uploaded.")
    r = requests.post(f"{CWS}/v2/publishers/{cws_publisher()}/items/{CWS_ITEM}:publish",
                      headers={"Authorization": f"Bearer {token}"}, json={}, timeout=60)
    if not r.ok:
        fail(f"Chrome submit for review failed: HTTP {r.status_code} {r.text[:500]}")
    print("Chrome: submitted for review. It goes live automatically once approved.")


# ---------- Firefox Add-ons ----------

def amo_headers():
    iss = os.environ.get("AMO_JWT_ISSUER", "").strip()
    sec = os.environ.get("AMO_JWT_SECRET", "").strip()
    if not iss or not sec:
        fail("The AMO_JWT_ISSUER or AMO_JWT_SECRET secret is missing.")
    now = int(time.time())
    token = jwt.encode({"iss": iss, "jti": str(uuid.uuid4()), "iat": now, "exp": now + 240}, sec, algorithm="HS256")
    return {"Authorization": f"JWT {token}"}


def amo_versions():
    r = requests.get(f"{AMO}/addons/addon/{AMO_ADDON}/versions/", params={"filter": "all_with_unlisted"},
                     headers=amo_headers(), timeout=60)
    if r.status_code in (401, 403):
        fail(f"Firefox Add-ons refused the keys (HTTP {r.status_code}). Check AMO_JWT_ISSUER and AMO_JWT_SECRET.")
    if not r.ok:
        fail(f"Firefox Add-ons check failed: HTTP {r.status_code} {r.text[:300]}")
    return [v["version"] for v in r.json().get("results", [])]


def firefox(zip_path, notes):
    with open(zip_path, "rb") as f:
        r = requests.post(f"{AMO}/addons/upload/", headers=amo_headers(),
                          files={"upload": (os.path.basename(zip_path), f, "application/zip")},
                          data={"channel": "listed"}, timeout=300)
    if not r.ok:
        fail(f"Firefox upload failed: HTTP {r.status_code} {r.text[:500]}")
    up = r.json()
    for _ in range(60):
        if up.get("processed"):
            break
        time.sleep(5)
        up = requests.get(f"{AMO}/addons/upload/{up['uuid']}/", headers=amo_headers(), timeout=60).json()
    if not up.get("processed"):
        fail("Firefox didn't finish checking the upload in time.")
    if not up.get("valid"):
        fail(f"Firefox rejected the package: {json.dumps(up.get('validation', {}).get('messages', []))[:1500]}")
    print("Firefox: package uploaded and checked.")
    r = requests.post(f"{AMO}/addons/addon/{AMO_ADDON}/versions/", headers=amo_headers(),
                      json={"upload": up["uuid"], "release_notes": {"en-US": notes}}, timeout=120)
    if not r.ok:
        fail(f"Firefox submit failed: HTTP {r.status_code} {r.text[:500]}")
    print("Firefox: submitted for review. It goes live automatically once approved.")


# ---------- check ----------

def check():
    status = cws_status(cws_token())
    print("Chrome Web Store status fields:", ", ".join(sorted(status)))
    live = [v.get("version") for v in status.get("publishedItemRevisionStatus", {}).get("distributionChannels", [])]
    print("Chrome Web Store: keys work. Live version:", ", ".join(v for v in live if v) or "(not shown)")
    versions = amo_versions()
    print("Firefox Add-ons: keys work. Versions on file:", ", ".join(versions) or "(none)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "check":
        check()
    elif cmd == "chrome":
        chrome(sys.argv[2])
    elif cmd == "firefox":
        firefox(sys.argv[2], sys.argv[3])
    else:
        fail(__doc__)
