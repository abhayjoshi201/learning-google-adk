"""
Real Google Drive + Gemini Enterprise OAuth Data Agent (`google_drive_oauth_agent`)
===================================================================================
Based on the official `core/python/oauth-user-consent-flow` recipe in `google/adk-samples`.

Notice what is GONE from this file compared to `enterprise_data_agent`:
- NO hardcoded `USER_PERMISSIONS` dictionary!
- NO hardcoded `DEFAULT_USER`!

Instead, this agent implements the 3-Stage `negotiate_creds(tool_context)` pattern:
- Stage 1 (Production Gemini Enterprise / Cached Token):
  Reads `tool_context.state["temp:google-drive-auth"]` injected automatically by Gemini Enterprise!
- Stage 2 & 3 (Local `adk web` OAuth Consent Flow):
  If `OAUTH_CLIENT_ID` and `OAUTH_CLIENT_SECRET` are configured, uses `tool_context.request_credential()`
  to pop up a "Sign in with Google" button inside `adk web` and caches the returned token via
  `tool_context.get_auth_response()`.
- Local Developer Fallback:
  If `OAUTH_CLIENT_ID` is not set locally, falls back to local `gcloud` Application Default Credentials (ADC)
  with the `drive.readonly` scope so you can test your own Google Drive immediately.
"""

import io
import os
import duckdb
import pandas as pd
import google.auth
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from fastapi.openapi.models import OAuth2, OAuthFlowAuthorizationCode, OAuthFlows
from google.adk.agents import Agent
from google.adk.auth import AuthConfig, AuthCredential, AuthCredentialTypes, OAuth2Auth
from google.adk.tools import ToolContext

# =====================================================================
# 1. OAUTH 2.0 CONFIGURATION (Matches Gemini Enterprise `AUTH_ID`)
# =====================================================================
AUTH_ID = os.getenv("AUTH_ID", "google-drive-auth")
TOKEN_CACHE_KEY = AUTH_ID

SCOPES = {
    "https://www.googleapis.com/auth/drive.readonly": "Read-only access to your Google Drive files"
}

AUTH_SCHEME = OAuth2(
    flows=OAuthFlows(
        authorizationCode=OAuthFlowAuthorizationCode(
            authorizationUrl="https://accounts.google.com/o/oauth2/v2/auth",
            tokenUrl="https://oauth2.googleapis.com/token",
            scopes=SCOPES,
        )
    )
)


def _build_auth_config() -> AuthConfig | None:
    """Builds ADK AuthConfig if OAUTH_CLIENT_ID & OAUTH_CLIENT_SECRET are set for local `adk web`."""
    client_id = os.getenv("OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None

    return AuthConfig(
        auth_scheme=AUTH_SCHEME,
        raw_auth_credential=AuthCredential(
            auth_type=AuthCredentialTypes.OAUTH2,
            oauth2=OAuth2Auth(
                client_id=client_id,
                client_secret=client_secret,
            ),
        ),
        credential_key=TOKEN_CACHE_KEY,
    )


# =====================================================================
# 2. THREE-STAGE CREDENTIAL NEGOTIATION (`negotiate_creds`)
# =====================================================================
def negotiate_creds(tool_context: ToolContext) -> Credentials | dict:
    """Resolves user Google Drive credentials across Gemini Enterprise, ADK OAuth, or local ADC.

    Stage 1: Check `tool_context.state` for `temp:<AUTH_ID>` (injected by Gemini Enterprise)
             or `<AUTH_ID>` (cached from previous turn).
    Stage 2: If `OAUTH_CLIENT_ID` is configured, check `tool_context.get_auth_response()`.
    Stage 3: Trigger `tool_context.request_credential()` consent screen in `adk web`
             (or fall back to local `gcloud` ADC if OAuth Client ID is not configured).
    """
    # --- STAGE 1: Production (Gemini Enterprise `temp:<AUTH_ID>`) or Cached Session Token ---
    cached_token = tool_context.state.get(f"temp:{TOKEN_CACHE_KEY}") or tool_context.state.get(
        TOKEN_CACHE_KEY
    )
    if cached_token:
        if isinstance(cached_token, str):
            return Credentials(token=cached_token)
        if isinstance(cached_token, dict):
            return Credentials.from_authorized_user_info(cached_token, list(SCOPES.keys()))

    # --- STAGE 2 & 3: Local `adk web` OAuth Flow (if OAUTH_CLIENT_ID is configured) ---
    auth_config = _build_auth_config()
    if auth_config is not None:
        auth_response = tool_context.get_auth_response(auth_config)
        if auth_response and getattr(auth_response, "oauth2", None):
            token_data = {
                "token": auth_response.oauth2.access_token,
                "refresh_token": auth_response.oauth2.refresh_token,
                "client_id": os.getenv("OAUTH_CLIENT_ID"),
                "client_secret": os.getenv("OAUTH_CLIENT_SECRET"),
                "token_uri": "https://oauth2.googleapis.com/token",
            }
            tool_context.state[TOKEN_CACHE_KEY] = token_data
            return Credentials.from_authorized_user_info(token_data, list(SCOPES.keys()))

        # Stage 3: Request interactive "Sign in with Google" button in ADK Web UI
        tool_context.request_credential(auth_config)
        return {
            "status": "pending_oauth_consent",
            "message": "Please click the 'Sign in with Google' button in the chat to grant read-only access to your Google Drive.",
        }

    # --- LOCAL DEVELOPER FALLBACK: Use `gcloud auth application-default login` ---
    try:
        creds, _ = google.auth.default(scopes=list(SCOPES.keys()))
        return creds
    except Exception as e:
        return {
            "status": "auth_setup_required",
            "message": (
                f"Could not obtain Google Drive credentials ({e}). "
                "Either set OAUTH_CLIENT_ID & OAUTH_CLIENT_SECRET in .env for the interactive OAuth popup, "
                "or run: gcloud auth application-default login --no-launch-browser "
                "--scopes='https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/drive.readonly'"
            ),
        }


def _download_drive_csv_to_df(drive_service, file_id: str) -> pd.DataFrame:
    """Downloads a CSV file (or exports a Google Sheet as CSV) from Google Drive into a DataFrame."""
    meta = drive_service.files().get(fileId=file_id, fields="id, name, mimeType").execute()
    mime_type = meta.get("mimeType", "")

    buffer = io.BytesIO()
    if mime_type == "application/vnd.google-apps.spreadsheet":
        request = drive_service.files().export_media(fileId=file_id, mimeType="text/csv")
    else:
        request = drive_service.files().get_media(fileId=file_id)

    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    buffer.seek(0)
    return pd.read_csv(buffer)


# =====================================================================
# 3. REAL GOOGLE DRIVE TOOLS (Zero Hardcoded Permissions!)
# =====================================================================
def list_drive_files(tool_context: ToolContext) -> dict:
    """Lists CSV and Google Sheets files in the signed-in user's real Google Drive."""
    creds_or_status = negotiate_creds(tool_context)
    if isinstance(creds_or_status, dict):
        return creds_or_status

    try:
        drive_service = build("drive", "v3", credentials=creds_or_status)
        query = (
            "trashed = false and ("
            "mimeType = 'text/csv' or "
            "mimeType = 'application/vnd.google-apps.spreadsheet'"
            ")"
        )
        results = (
            drive_service.files()
            .list(
                q=query,
                pageSize=25,
                fields="files(id, name, mimeType, owners(emailAddress))",
            )
            .execute()
        )
        files = results.get("files", [])
        return {
            "status": "success",
            "file_count": len(files),
            "accessible_drive_files": files,
            "note": "Permissions were enforced directly by the Google Drive API using the user's OAuth token.",
        }
    except Exception as e:
        return {"status": "drive_api_error", "error_message": str(e)}


def describe_drive_file_schema(file_id: str, tool_context: ToolContext) -> dict:
    """Inspects a CSV or Google Sheet in Google Drive and returns its column names and row count.

    Args:
        file_id: The Google Drive `id` of the file returned by `list_drive_files`.
    """
    creds_or_status = negotiate_creds(tool_context)
    if isinstance(creds_or_status, dict):
        return creds_or_status

    try:
        drive_service = build("drive", "v3", credentials=creds_or_status)
        df = _download_drive_csv_to_df(drive_service, file_id)

        con = duckdb.connect()
        con.register("authorized_data", df)
        schema_df = con.execute("DESCRIBE authorized_data").df()

        return {
            "status": "success",
            "file_id": file_id,
            "row_count": len(df),
            "table_name_for_queries": "authorized_data",
            "columns": schema_df[["column_name", "column_type"]].to_dict(orient="records"),
        }
    except Exception as e:
        return {
            "status": "ACCESS_DENIED_OR_ERROR",
            "file_id": file_id,
            "error_message": str(e),
        }


def run_drive_sql_query(file_id: str, sql_query: str, tool_context: ToolContext) -> dict:
    """Executes a DuckDB SQL query against a CSV or Google Sheet in the user's Google Drive.

    IMPORTANT: Always query from the table name `authorized_data` in your SQL statement!
    Example: `SELECT Product_Type, SUM(Net_Revenue_SGD) FROM authorized_data GROUP BY Product_Type`

    Args:
        file_id: The Google Drive `id` of the file returned by `list_drive_files`.
        sql_query: A valid SQL SELECT query referencing `authorized_data`.
    """
    creds_or_status = negotiate_creds(tool_context)
    if isinstance(creds_or_status, dict):
        return creds_or_status

    try:
        drive_service = build("drive", "v3", credentials=creds_or_status)
        df = _download_drive_csv_to_df(drive_service, file_id)
    except Exception as e:
        return {
            "status": "ACCESS_DENIED",
            "file_id": file_id,
            "message": f"Google Drive blocked access to file '{file_id}': {e}",
        }

    try:
        con = duckdb.connect()
        con.register("authorized_data", df)
        result_df = con.execute(sql_query).df()
        return {
            "status": "success",
            "file_id": file_id,
            "returned_rows": len(result_df),
            "data": result_df.head(50).to_dict(orient="records"),
        }
    except Exception as e:
        # Self-Correction Loop: Return the SQL error string so the LLM fixes its query automatically!
        return {
            "status": "sql_error",
            "failed_query": sql_query,
            "error_message": str(e),
            "self_correction_hint": (
                "Always query from table `authorized_data`. Call `describe_drive_file_schema` "
                "to check exact column names and retry `run_drive_sql_query`."
            ),
        }


# =====================================================================
# 4. ROOT AGENT DEFINITION
# =====================================================================
root_agent = Agent(
    name="google_drive_oauth_agent",
    model="gemini-2.5-flash",
    description="Production-pattern Google Drive OAuth + Gemini Enterprise Natural Language Data Agent.",
    instruction="""
    You are a Google Drive Enterprise Data Assistant powered by Google ADK.
    Unlike local mock demos, you connect directly to the user's real Google Drive via OAuth 2.0
    (supporting Gemini Enterprise `temp:<AUTH_ID>` token injection, ADK OAuth pop-ups, and ADC).

    Follow this workflow:
    1. Call `list_drive_files` first to discover which CSVs and Google Sheets the signed-in user
       has permission to access in their Google Drive.
    2. If a tool returns `pending_oauth_consent` or `auth_setup_required`, explain the message
       clearly so the user can complete sign-in.
    3. Before writing a SQL query on a Drive file, call `describe_drive_file_schema` with its `file_id`
       to inspect its exact column names.
    4. Call `run_drive_sql_query(file_id, sql_query)` querying from table `authorized_data`.
    5. If `run_drive_sql_query` returns `sql_error`, fix your SQL query automatically and retry!
    """,
    tools=[list_drive_files, describe_drive_file_schema, run_drive_sql_query],
)
