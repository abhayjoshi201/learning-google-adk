# 🧠 Learning Google ADK (Agent Development Kit) — Living Agent Engineering Playbook

> **📌 About This Repository:**
> This is the **living repository I use to learn AI Agent Engineering** from the ground up. As I build, debug, and productionize real-world AI agents with [Google's Agent Development Kit (ADK)](https://google.github.io/adk-docs/), **I simultaneously update and document everything I learn here**—including architectural mental models, OAuth 2.0 handshakes, local vs. cloud runtime blueprints, Vertex AI Agent Engine deployments, Gemini Enterprise governance, and production debugging lessons.

It combines **5 step-by-step architecture & engineering guides** with **two runnable, production-ready multi-tool ADK agents** powered by **`gemini-3.7-flash`** and **automated deployment scripts** for **Vertex AI Agent Engine** and **Gemini Enterprise**.

---

## 📚 Curriculum & Documentation (`docs/`)

Every concept, architectural trade-off, and production failure discovered while building and deploying these agents is documented chronologically in [`docs/`](docs/):

| Lesson | Guide | What Is Documented |
| :--- | :--- | :--- |
| **Lesson 1** | [**`docs/01_adk_fundamentals.md`**](docs/01_adk_fundamentals.md) | Why plain LLMs fail in production, the 5 core ADK primitives (`LlmAgent`, `FunctionTool`, `ToolContext`, `Runner`, `SessionService`), and how the `oauth-user-consent-flow` sample works under the hood. |
| **Lesson 2** | [**`docs/02_architect_thought_process.md`**](docs/02_architect_thought_process.md) | How to think like an AI Agent Architect: decomposing business problems, designing tool boundaries (`search` → `inspect` → `execute`), anti-hallucination guardrails, and building the **DuckDB SQL Analytics Agent**. |
| **Lesson 3** | [**`docs/03_authentication_and_production_setup.md`**](docs/03_authentication_and_production_setup.md) | The complete authentication blueprint: **Model Auth** (Gemini API Key vs. Vertex AI IAM) vs. **User Data Auth** (3-Legged OAuth 2.0 PKCE), plus step-by-step GCP Console setup for Google Drive OAuth. |
| **Lesson 4** | [**`docs/04_production_deployment_gemini_enterprise.md`**](docs/04_production_deployment_gemini_enterprise.md) | End-to-end guide to packaging ADK agents into **Vertex AI Agent Engine (Reasoning Engine)**, creating **Gemini Enterprise Authorization Resources**, and linking managed OAuth 2.0 token brokering. |
| **Lesson 5** | [**`docs/05_key_engineering_learnings.md`**](docs/05_key_engineering_learnings.md) | **10 core production engineering takeaways** learned hands-on: decoupling LLM reasoning from deterministic compute (DuckDB), solving `redirect_uri_mismatch`, decoupling `GOOGLE_CLOUD_LOCATION=global` (`gemini-3.7-flash`) from regional Agent Engine (`us-central1`), pinning `cloudpickle` dependencies, and sanitizing Pandas `NaN` values for strict Vertex AI JSON schemas. |

---

## 🛠️ Runnable Agents Included in This Repo

| Agent Directory | Model | Purpose & Capabilities |
| :--- | :--- | :--- |
| [**`enterprise_data_agent/`**](enterprise_data_agent/) | `gemini-3.7-flash` | **Production Google Drive OAuth 2.0 + DuckDB SQL Analytics Agent** (deployed to both local `adk web` and **Vertex AI Agent Engine + Gemini Enterprise**). Searches the user's real Google Drive via OAuth 2.0, inspects CSV schemas/metadata, and runs deterministic in-memory **DuckDB SQL** queries (`SUM`, `AVG`, `GROUP BY`, `ORDER BY`) with zero math hallucination. |
| [**`google_drive_oauth_agent/`**](google_drive_oauth_agent/) | `gemini-3.7-flash` | **Official ADK OAuth 2.0 Reference Sample** (`core/python/oauth-user-consent-flow` from [`google/adk-samples`](https://github.com/google/adk-samples)) configured for `gemini-3.7-flash`. Demonstrates dual-mode OAuth 2.0 (`ToolContext.request_credential` locally vs. Gemini Enterprise `AUTH_ID` token injection in production). |

---

## 🚀 Production Deployment Scripts (`scripts/`)

| Script | Description |
| :--- | :--- |
| [**`scripts/deploy_agent_engine.py`**](scripts/deploy_agent_engine.py) | Packages `enterprise_data_agent` into a `AdkApp`, serializes it with `cloudpickle`, and deploys or updates the managed **Vertex AI Agent Engine (`ReasoningEngine`)** in `us-central1` while targeting `GOOGLE_CLOUD_LOCATION=global` for `gemini-3.7-flash`. |
| [**`scripts/register_gemini_enterprise.py`**](scripts/register_gemini_enterprise.py) | Registers the Google OAuth 2.0 `authorizations` resource (`https://vertexaisearch.cloud.google.com/static/oauth/oauth.html`) in the Gemini Enterprise Discovery Engine API and binds the deployed Vertex AI Reasoning Engine to the Gemini Enterprise Assistant portal. |

---

## ⚡ Quickstart (Run Locally in 60 Seconds)

### 1. Clone & Create Virtual Environment
```bash
git clone https://github.com/abhayjoshi201/learning-google-adk.git
cd learning-google-adk

python3 -m venv .venv
source .venv/bin/activate
pip install -r enterprise_data_agent/requirements.txt
```

### 2. Configure Your Environment (`.env`)
Copy `.env.example` inside `enterprise_data_agent/` (or `google_drive_oauth_agent/`) to `.env`:
```bash
cp enterprise_data_agent/.env.example enterprise_data_agent/.env
```
Update `enterprise_data_agent/.env` with your Vertex AI Project and Google OAuth 2.0 Client credentials:
```ini
GOOGLE_GENAI_USE_VERTEXAI=1
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=global
MODEL_NAME=gemini-3.7-flash

# Local OAuth 2.0 Flow (adk web)
OAUTH_CLIENT_ID=your-oauth-client-id.apps.googleusercontent.com
OAUTH_CLIENT_SECRET=your-oauth-client-secret

# Production Gemini Enterprise Auth Resource ID (set when deployed)
AUTH_ID=
```

### 3. Launch the Interactive ADK Developer UI (`adk web`)
From the root of the repository, run:
```bash
.venv/bin/adk web --port 8000 --reload_agents
```
Open **`http://localhost:8000`** in your browser, select **`enterprise_data_agent`** from the top-left dropdown, and try these prompts:
1. *"What files do I have in my Google Drive? List my CSV and spreadsheet files."* (Triggers the OAuth 2.0 consent button!)
2. *"Inspect the schema and sample rows of `<your_csv_filename>.csv`."*
3. *"Run a DuckDB SQL query on `<your_csv_filename>.csv` to calculate the summary metrics grouped by category."*
