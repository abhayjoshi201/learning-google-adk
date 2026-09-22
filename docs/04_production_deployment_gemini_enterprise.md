# Lesson 4: Manual Production Deployment Guide (Vertex AI Agent Engine + Gemini Enterprise)

This guide walks through the **exact 5-step manual process** to deploy an ADK + OAuth 2.0 agent ([`enterprise_data_agent/`](../enterprise_data_agent/agent.py)) from your local workstation to **Vertex AI Agent Engine** and connect it to **Gemini Enterprise**.

---

## Architecture Overview: Why Zero Code Changes Are Needed

```text
  ┌────────────────────────────────────────────────────────────────────────────┐
  │                 LOCAL (`adk web`) vs. PRODUCTION (`Gemini Enterprise`)     │
  ├───────────────────────────────────────┬────────────────────────────────────┤
  │ Local Dev (`adk web`)                 │ Production (`Gemini Enterprise`)   │
  │                                       │                                    │
  │ 1. `negotiate_creds()` runs Stage 3   │ 1. Gemini Enterprise checks linked │
  │    (`request_credential`)             │    Authorization (`google-drive-auth`)│
  │ 2. Browser redirects to `/dev-ui/`    │ 2. Browser redirects to            │
  │ 3. Stage 2 exchanges code & caches    │    `vertexaisearch.../oauth.html`  │
  │    token in `state["google-drive-auth"]`│ 3. Gemini Enterprise injects live│
  │                                       │    token into:                     │
  │                                       │    `state["temp:google-drive-auth"]`│
  │                                       │ 4. `negotiate_creds()` Stage 1     │
  │                                       │    finds token immediately!        │
  └───────────────────────────────────────┴────────────────────────────────────┘
```

---

## Step 1: Configure Your OAuth 2.0 Web Client in GCP Console

1. Open **[Google Cloud Console -> APIs & Services -> Credentials](https://console.cloud.google.com/apis/credentials)**.
2. Click **+ Create Credentials -> OAuth client ID** (Application type: **Web application**).
3. Under **Authorized redirect URIs**, add **both** local and Gemini Enterprise redirect URIs:
   ```text
   http://127.0.0.1:8000/dev-ui/
   https://vertexaisearch.cloud.google.com/static/oauth/oauth.html
   ```
4. Click **Save** and copy your **Client ID** and **Client Secret** into [`enterprise_data_agent/.env`](../enterprise_data_agent/.env.example):
   ```env
   GOOGLE_GENAI_USE_VERTEXAI=1
   GOOGLE_CLOUD_PROJECT=rdang-test-464810
   GOOGLE_CLOUD_LOCATION=us-central1
   OAUTH_CLIENT_ID=YOUR_CLIENT_ID.apps.googleusercontent.com
   OAUTH_CLIENT_SECRET=GOCSPX-YOUR_CLIENT_SECRET
   AUTH_ID=google-drive-auth
   ```
5. Make sure the **Google Drive API** and **Vertex AI API** are enabled in your project:
   ```bash
   gcloud services enable drive.googleapis.com aiplatform.googleapis.com discoveryengine.googleapis.com --project=rdang-test-464810
   ```

---

## Step 2: Prepare the Agent Engine Entrypoint & Dependencies

To run inside Vertex AI Agent Engine's managed container runtime, your agent folder needs two files alongside `agent.py`, `tools.py`, and `auths.py`:

1. **[`enterprise_data_agent/agent_engine_app.py`](../enterprise_data_agent/agent_engine_app.py)** — Wraps your ADK `app` in `vertexai.agent_engines.templates.adk.AdkApp`:
   ```python
   import vertexai
   from vertexai.agent_engines.templates.adk import AdkApp
   from google.adk.artifacts import InMemoryArtifactService
   from enterprise_data_agent.agent import app as adk_app

   class AgentEngineApp(AdkApp):
       def set_up(self) -> None:
           vertexai.init()
           super().set_up()

   agent_engine = AgentEngineApp(
       app=adk_app,
       artifact_service_builder=InMemoryArtifactService,
   )
   ```

2. **[`enterprise_data_agent/requirements.txt`](../enterprise_data_agent/requirements.txt)** — Pins the exact runtime versions compatible with Vertex AI Agent Engine's container worker:
   ```text
   google-cloud-aiplatform[agent_engines, reasoning_engine]==2.0.1
   google-adk==2.8.0
   pydantic==2.12.5
   cloudpickle==3.1.2
   google-api-python-client>=2.160.0
   google-auth>=2.38.0
   duckdb>=1.2.0
   pandas>=2.2.0
   python-dotenv>=1.0.1
   ```

---

## Step 3: Deploy the Agent to Vertex AI Agent Engine

1. Authenticate Application Default Credentials (ADC) with your GCP project account:
   ```bash
   gcloud auth application-default login
   ```
2. Run the deployment script ([`scripts/deploy_agent_engine.py`](../scripts/deploy_agent_engine.py)), which packages `enterprise_data_agent/` and calls `client.agent_engines.create(config=AgentEngineConfig(...))`:
   ```bash
   .venv/bin/python -m scripts.deploy_agent_engine
   ```
3. After ~3 minutes, Vertex AI outputs your **Reasoning Engine Resource Name**:
   ```text
   projects/624784087790/locations/us-central1/reasoningEngines/448499039307038720
   ```
   *(You can also view and test it in the GCP Console at **Vertex AI -> Agent Engine**).*

---

## Step 4: Register the OAuth 2.0 Authorization Resource in Gemini Enterprise

Before linking the agent to Gemini Enterprise, register a server-side OAuth 2.0 resource in Discovery Engine with **`authorizationId=google-drive-auth`** (matching `TOKEN_CACHE_KEY = "google-drive-auth"` in `auths.py`).

### Manual `curl` Command:
```bash
export PROJECT_ID="rdang-test-464810"
export PROJECT_NUMBER="624784087790"
export AUTH_ID="google-drive-auth"
export OAUTH_CLIENT_ID="YOUR_OAUTH_CLIENT_ID"
export OAUTH_CLIENT_SECRET="YOUR_OAUTH_CLIENT_SECRET"

curl -X POST \
  -H "Authorization: Bearer $(gcloud auth application-default print-access-token)" \
  -H "Content-Type: application/json" \
  -H "X-Goog-User-Project: ${PROJECT_ID}" \
  "https://discoveryengine.googleapis.com/v1alpha/projects/${PROJECT_ID}/locations/global/authorizations?authorizationId=${AUTH_ID}" \
  -d '{
    "name": "projects/'"${PROJECT_NUMBER}"'/locations/global/authorizations/'"${AUTH_ID}"'",
    "serverSideOauth2": {
      "clientId": "'"${OAUTH_CLIENT_ID}"'",
      "clientSecret": "'"${OAUTH_CLIENT_SECRET}"'",
      "authorizationUri": "https://accounts.google.com/o/oauth2/v2/auth?client_id='"${OAUTH_CLIENT_ID}"'&redirect_uri=https%3A%2F%2Fvertexaisearch.cloud.google.com%2Fstatic%2Foauth%2Foauth.html&scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fdrive.readonly&include_granted_scopes=true&response_type=code&access_type=offline&prompt=consent",
      "tokenUri": "https://oauth2.googleapis.com/token"
    }
  }'
```

---

## Step 5: Attach the Reasoning Engine + OAuth Resource to Your Gemini Enterprise App

Finally, link your deployed **Reasoning Engine (`Step 3`)** and your **OAuth Authorization Resource (`Step 4`)** to your Gemini Enterprise App (`APP_ID`).

> **Important Gotcha**: Always use the numeric **`PROJECT_NUMBER` (`624784087790`)** inside `reasoningEngine` and `toolAuthorizations`—Discovery Engine rejects string project IDs in `toolAuthorizations` with `HTTP 400: Invalid Authorization name`.

### Manual `curl` Command:
```bash
export APP_ID="gemini-application-poc_1775452662124"
export REASONING_ENGINE_ID="448499039307038720"

curl -X POST \
  -H "Authorization: Bearer $(gcloud auth application-default print-access-token)" \
  -H "Content-Type: application/json" \
  -H "X-Goog-User-Project: ${PROJECT_ID}" \
  "https://discoveryengine.googleapis.com/v1alpha/projects/${PROJECT_ID}/locations/global/collections/default_collection/engines/${APP_ID}/assistants/default_assistant/agents" \
  -d '{
    "displayName": "Enterprise Drive Data Agent",
    "description": "Lists, reads, and runs SQL analytics (DuckDB) on Google Drive CSVs, Sheets, and Docs on behalf of the authenticated user.",
    "adkAgentDefinition": {
      "toolSettings": {
        "toolDescription": "Use this agent to list files in the user'\''s Google Drive, read documents, or execute SQL queries over CSVs and Sheets."
      },
      "provisionedReasoningEngine": {
        "reasoningEngine": "projects/'"${PROJECT_NUMBER}"'/locations/us-central1/reasoningEngines/'"${REASONING_ENGINE_ID}"'"
      }
    },
    "authorizationConfig": {
      "toolAuthorizations": [
        "projects/'"${PROJECT_NUMBER}"'/locations/global/authorizations/'"${AUTH_ID}"'"
      ]
    }
  }'
```

*(Or run both Step 4 and Step 5 automatically via: `.venv/bin/python -m scripts.register_gemini_enterprise --app-id <YOUR_APP_ID>`)*
