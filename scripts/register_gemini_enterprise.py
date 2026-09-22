"""Register OAuth 2.0 Authorization & ADK Agent in Gemini Enterprise.

Strictly follows the registration pattern from:
https://github.com/google/adk-samples/tree/main/core/python/oauth-user-consent-flow

Uses Application Default Credentials (ADC) so it authenticates as the
project owner (`rdang-test-464810`) even if `gcloud` CLI is set to another account.
"""

import argparse
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request
from dotenv import load_dotenv
import google.auth
from google.auth.transport.requests import Request

# Load OAuth credentials and project config from enterprise_data_agent/.env
ENV_PATH = Path(__file__).resolve().parent.parent / "enterprise_data_agent" / ".env"
load_dotenv(ENV_PATH)

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "rdang-test-464810")
AUTH_ID = "google-drive-auth"
GEMINI_ENTERPRISE_REDIRECT_URI = (
    "https://vertexaisearch.cloud.google.com/static/oauth/oauth.html"
)
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


def get_adc_access_token() -> str:
    """Fetches a bearer token from Application Default Credentials (ADC)."""
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    creds.refresh(Request())
    return creds.token


def api_request(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    """Helper to make authenticated Discovery Engine REST API calls."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": PROJECT_ID,
    }
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        print(f"HTTP {e.code} Error calling {url}:\n{err_body}")
        raise


def register_oauth_resource(token: str) -> str:
    """Step 3a: Register the `google-drive-auth` OAuth 2.0 resource in Discovery Engine."""
    client_id = os.environ.get("OAUTH_CLIENT_ID")
    client_secret = os.environ.get("OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError("OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET must be set in .env")

    auth_uri = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        + urllib.parse.urlencode(
            {
                "client_id": client_id,
                "redirect_uri": GEMINI_ENTERPRISE_REDIRECT_URI,
                "scope": DRIVE_SCOPE,
                "include_granted_scopes": "true",
                "response_type": "code",
                "access_type": "offline",
                "prompt": "consent",
            }
        )
    )

    url = (
        f"https://discoveryengine.googleapis.com/v1alpha/projects/{PROJECT_ID}"
        f"/locations/global/authorizations?authorizationId={AUTH_ID}"
    )
    payload = {
        "name": f"projects/{PROJECT_ID}/locations/global/authorizations/{AUTH_ID}",
        "serverSideOauth2": {
            "clientId": client_id,
            "clientSecret": client_secret,
            "authorizationUri": auth_uri,
            "tokenUri": "https://oauth2.googleapis.com/token",
        },
    }

    print(f"1. Registering OAuth resource '{AUTH_ID}' in project '{PROJECT_ID}'...")
    try:
        res = api_request("POST", url, token, payload)
        print(f"   Created OAuth Authorization: {res.get('name')}")
        return res.get("name")
    except urllib.error.HTTPError as e:
        if e.code == 409:
            auth_name = f"projects/624784087790/locations/global/authorizations/{AUTH_ID}"
            print(f"   OAuth Authorization already exists: {auth_name}")
            return auth_name
        raise


def list_gemini_enterprise_apps(token: str) -> list[dict]:
    """Lists Gemini Enterprise (Discovery Engine) Apps in the project."""
    url = (
        f"https://discoveryengine.googleapis.com/v1alpha/projects/{PROJECT_ID}"
        "/locations/global/collections/default_collection/engines"
    )
    res = api_request("GET", url, token)
    return res.get("engines", [])


def register_agent_in_app(
    token: str, app_id: str, reasoning_engine: str, auth_resource_name: str
) -> dict:
    """Step 3b: Register the Reasoning Engine + OAuth resource onto Gemini Enterprise."""
    url = (
        f"https://discoveryengine.googleapis.com/v1alpha/projects/{PROJECT_ID}"
        f"/locations/global/collections/default_collection/engines/{app_id}"
        "/assistants/default_assistant/agents"
    )
    payload = {
        "displayName": "Enterprise Drive Data Agent",
        "description": (
            "Lists, reads, and runs SQL analytics (DuckDB) on Google Drive "
            "CSVs, Sheets, and Docs on behalf of the authenticated user."
        ),
        "adkAgentDefinition": {
            "toolSettings": {
                "toolDescription": (
                    "Use this agent to list files in the user's Google Drive, "
                    "read documents, or execute SQL queries over CSVs and Sheets."
                )
            },
            "provisionedReasoningEngine": {
                "reasoningEngine": reasoning_engine,
            },
        },
        "authorizationConfig": {
            "toolAuthorizations": [auth_resource_name],
        },
    }
    print(f"2. Registering agent onto Gemini Enterprise App '{app_id}'...")
    res = api_request("POST", url, token, payload)
    print(f"   Successfully registered Agent: {res.get('name')}")
    return res


def main():
    parser = argparse.ArgumentParser(
        description="Register OAuth & Agent Engine with Gemini Enterprise"
    )
    parser.add_argument(
        "--reasoning-engine",
        default="projects/624784087790/locations/us-central1/reasoningEngines/448499039307038720",
        help="Full Reasoning Engine resource name from `deploy_agent_engine.py`",
    )
    parser.add_argument(
        "--app-id",
        default=None,
        help="Gemini Enterprise App (Engine) ID. If omitted, lists available apps.",
    )
    args = parser.parse_args()

    token = get_adc_access_token()
    auth_name = register_oauth_resource(token)

    apps = list_gemini_enterprise_apps(token)
    if not args.app_id:
        if not apps:
            print(
                "\nNo Gemini Enterprise App found in project yet. Create one at:\n"
                f"https://console.cloud.google.com/gen-app-builder/engines?project={PROJECT_ID}\n"
                "Then re-run with: --app-id=<YOUR_APP_ID>"
            )
            return
        print("\nFound Gemini Enterprise Apps in project:")
        for app in apps:
            print(f"  - {app.get('name')} (displayName: {app.get('displayName')})")
        app_id = apps[0]["name"].split("/")[-1]
        print(f"\nAuto-selecting first app: {app_id}")
    else:
        app_id = args.app_id

    register_agent_in_app(token, app_id, args.reasoning_engine, auth_name)


if __name__ == "__main__":
    main()
