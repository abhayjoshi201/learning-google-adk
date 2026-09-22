# Lesson 5: Capstone Retrospective — 10 Real-World Engineering Learnings (From Zero to Production Gemini Enterprise)

This document captures the **10 critical architectural and operational lessons** learned while building, debugging, and deploying our **Enterprise Google Drive OAuth 2.0 + DuckDB SQL Data Agent** from local `adk web` to **Vertex AI Agent Engine** and **Gemini Enterprise**.

---

## 🏗️ Pillar 1: Agent Architecture & Tool Design

### 1. Don't Ask LLMs to Do Mental Math on Raw Files — Give Them a SQL Engine (`DuckDB`)
* **The Trap**: A naive agent (`read_drive_file` alone) dumps raw CSV/Sheet text into the LLM prompt and asks the model to count rows or sum columns in its head—which fails or hallucinates on thousands of rows.
* **The Solution**: In [`enterprise_data_agent/tools.py`](../enterprise_data_agent/tools.py#L242-L270), we built `query_drive_csv(file_id, sql_query)`, which loads the user's Google Drive CSV into an in-memory **DuckDB** table (`drive_data`) and lets Gemini write deterministic SQL (`SELECT`, `SUM`, `GROUP BY`).
* **Takeaway**: **LLMs should write queries, not compute aggregations.**

### 2. Always Sanitize Pandas/SQL Tool Outputs to Strict JSON (`NaN -> null`)
* **The Bug We Hit**:
  `ClientError: 400 INVALID_ARGUMENT: Invalid JSON payload received. Unexpected token. "Net_Revenue_Factor": NaN`
* **Why It Happened**: When a CSV/SQL result contains `NULL` numeric values, `result_df.to_dict(orient="records")` leaves Python `float('nan')` inside the dictionary. Python serializes `float('nan')` as `NaN`, which violates strict RFC 8259 JSON required by Vertex AI.
* **The Fix**: Always serialize DataFrames via:
  ```python
  json.loads(result_df.head(50).to_json(orient="records", date_format="iso"))
  ```
  which converts every `NaN`, `Infinity`, `NaT`, and `Timestamp` into valid JSON `null` and ISO strings.

---

## 🔐 Pillar 2: OAuth 2.0 & Identity Across Local vs. Production

### 3. One 3-Stage Function (`negotiate_creds`) Powers Both Local Dev and Gemini Enterprise
* **Why Zero Code Changes Were Needed for Prod**:
  ```text
  ┌─────────────────────────┬──────────────────────────────────────────────────┐
  │ Stage 1 (`state` check) │ Checks `state["google-drive-auth"]` AND          │
  │                         │ `state["temp:google-drive-auth"]`.               │
  │                         │ 👉 Used by Production Gemini Enterprise on Turn 1│
  │                         │    (and by Local `adk web` on Turn 2+).          │
  ├─────────────────────────┼──────────────────────────────────────────────────┤
  │ Stage 2 (Code exchange) │ Calls `tool_context.get_auth_response()` after   │
  │                         │ the user clicks Authorize in `adk web`.          │
  ├─────────────────────────┼──────────────────────────────────────────────────┤
  │ Stage 3 (Consent popup) │ Calls `tool_context.request_credential()` to     │
  │                         │ render the Sign-In card in `adk web`.            │
  └─────────────────────────┴──────────────────────────────────────────────────┘
  ```
* **Key Contract**: The `AUTH_ID` (`"google-drive-auth"`) in [`auths.py`](../enterprise_data_agent/auths.py#L60) **must match** the `authorizationId` registered in Gemini Enterprise so Stage 1 finds `tool_context.state["temp:google-drive-auth"]`.

### 4. OAuth 2.0 Redirect URIs Are Character-by-Character Strict (Trailing Slash Matters!)
* **The Bug We Hit**: `Error 400: redirect_uri_mismatch` on both local and prod until the exact URIs were added.
* **The Rule**:
  * Local `adk web` sends `http://127.0.0.1:8000/dev-ui/` (**with a trailing slash**—registering `/dev-ui` without `/` will fail!).
  * Production Gemini Enterprise sends `https://vertexaisearch.cloud.google.com/static/oauth/oauth.html`.
  * Register **both** on the same Web OAuth Client ID so one credential works everywhere.

### 5. Separate Workstation CLI Auth (`gcloud`) from Application Default Credentials (`ADC`)
* **What We Saw**: Your workstation's `gcloud` CLI was logged into `abhayjoshi@google.com`, while your GCP project (`rdang-test-464810`) belonged to `abhay@rishabhdang.altostrat.com` in ADC (`~/.config/gcloud/application_default_credentials.json`).
* **The Takeaway**: Python SDKs (`vertexai`, `google-auth`, `google-adk`) always use **ADC** (`gcloud auth application-default login`), whereas `gcloud` shell commands use `gcloud auth login`.

---

## ☁️ Pillar 3: Vertex AI Agent Engine & Gemini Enterprise Deployment

### 6. Deploy with `AdkApp` (`client.agent_engines.create`) Instead of Custom Dockerfiles
* **What We Discovered**: Running `adk deploy agent_engine` generated an experimental custom `Dockerfile` (`image_spec={}`) that failed on startup with `{'code': 13, 'message': 'INTERNAL'}`.
* **The `adk-samples` Solution**: Wrap your `App` in `vertexai.agent_engines.templates.adk.AdkApp` ([`agent_engine_app.py`](../enterprise_data_agent/agent_engine_app.py)) and deploy with `AgentEngineConfig(source_packages=["enterprise_data_agent"])` ([`scripts/deploy_agent_engine.py`](../scripts/deploy_agent_engine.py)).

### 7. Pin Container Runtime Versions in `requirements.txt` for Agent Engine
* **The Bug We Hit**: Unpinned `google-adk>=2.9` pulled `google-adk==2.9.2` + `pydantic==2.13.5` inside Cloud Build, which conflicted with Vertex AI Agent Engine's managed worker runtime.
* **The Fix**: Pinning the exact tested runtime versions in [`enterprise_data_agent/requirements.txt`](../enterprise_data_agent/requirements.txt) made the Agent Engine build succeed in 3 minutes:
  ```text
  google-cloud-aiplatform[agent_engines, reasoning_engine]==2.0.1
  google-adk==2.8.0
  pydantic==2.12.5
  cloudpickle==3.1.2
  ```

### 8. Regional Agent Engine (`us-central1`) vs. Global Model Endpoint (`global`) for Gemini 3.7
* **What We Discovered**:
  * Reasoning Engines (`client.agent_engines`) must be deployed in a regional endpoint (`us-central1`).
  * However, frontier models like **`gemini-3.7-flash`** are served on Vertex AI's **`global`** endpoint (`locations/global/publishers/google/models/gemini-3.7-flash`) and return `404 NOT_FOUND` if called in `us-central1`.
* **The Fix**: Deploy the Reasoning Engine in `location="us-central1"`, while setting `os.environ["GOOGLE_CLOUD_LOCATION"] = "global"` inside [`agent.py`](../enterprise_data_agent/agent.py) and `agent_engine_app.py`.

### 9. Use Numeric `PROJECT_NUMBER` (Not `PROJECT_ID`) in Discovery Engine `toolAuthorizations`
* **The Bug We Hit**: Passing `"projects/rdang-test-464810/locations/global/authorizations/google-drive-auth"` in `toolAuthorizations` failed with `HTTP 400: Invalid Authorization name`.
* **The Fix**: Always pass the numeric **`PROJECT_NUMBER` (`624784087790`)**:
  `"projects/624784087790/locations/global/authorizations/google-drive-auth"`.

### 10. Use `client.agent_engines.update()` for Zero-Downtime In-Place Upgrades
* **Why It Matters**: Once your Reasoning Engine (`448499039307038720`) is linked to a Gemini Enterprise App (`Gemini-Application-POC`), calling `client.agent_engines.update(name=existing_id, config=config)` updates the model (`gemini-3.7-flash`) or tool code (`NaN` fix) **in place**—so you never have to delete and re-register the agent in Gemini Enterprise!
