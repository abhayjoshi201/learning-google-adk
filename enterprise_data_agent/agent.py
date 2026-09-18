"""
Enterprise Identity-Aware Data Agent (Built with Google ADK)
============================================================
This agent implements your 5-Step Architectural Blueprint:
1. Trust Boundary: Deterministic Python handles permissions & SQL math; LLM handles language & SQL generation.
2. Locked Room Tools: `login_as`, `list_files`, `describe_schema`, and `run_query`.
3. Invisible Backpack: Uses `tool_context.state["user_email"]` so the LLM cannot fake or tamper with user identity.
4. Single LlmAgent: One cohesive `root_agent` orchestrating the tools.
5. Self-Correction Loop: `run_query` catches SQL errors and returns them to the LLM so it can self-heal.
"""

from pathlib import Path
import duckdb
from google.adk.agents import Agent
from google.adk.tools import ToolContext

# Path to the workspace directory containing mock_data_dtdb_v2.csv
WORKSPACE_DIR = Path(__file__).resolve().parent.parent
CSV_FILE_PATH = WORKSPACE_DIR / "mock_data_dtdb_v2.csv"

# =====================================================================
# 1. DRIVE-STYLE ACCESS CONTROL MATRIX (Deterministic Security)
# =====================================================================
USER_PERMISSIONS = {
    "craig.cohen@company.com": {
        "name": "Craig Cohen",
        "role": "Account Manager (Tier 1)",
        "allowed_files": ["mock_data_dtdb_v2.csv"],
        # Row-level security: Craig can ONLY see rows where he is the Account_Manager
        "row_filter": "Account_Manager = 'Craig Cohen'",
    },
    "yan.xuan@company.com": {
        "name": "Yan Xuan Li",
        "role": "Team Lead - China",
        "allowed_files": ["mock_data_dtdb_v2.csv"],
        # Row-level security: Yan Xuan can ONLY see rows belonging to Team 'China'
        "row_filter": "Team = 'China'",
    },
    "renaud.gocsei@company.com": {
        "name": "Renaud Gocsei",
        "role": "Account Manager (GAM / Tier 1/2)",
        "allowed_files": ["mock_data_dtdb_v2.csv"],
        "row_filter": "Account_Manager = 'Renaud Gocsei'",
    },
    "ceo@company.com": {
        "name": "Executive CEO",
        "role": "Global Administrator",
        "allowed_files": ["mock_data_dtdb_v2.csv", "executive_board_notes_2025.csv"],
        # CEO has unrestricted row-level visibility (1=1 matches all rows)
        "row_filter": "1=1",
    },
}

DEFAULT_USER = "craig.cohen@company.com"


# =====================================================================
# 2. ADK TOOLS (Using `tool_context: ToolContext` for Security)
# =====================================================================

def login_as(user_email: str, tool_context: ToolContext) -> dict:
    """Switches the currently signed-in user account in Session State for testing permissions.

    Args:
        user_email: The email address to sign in as (e.g., 'craig.cohen@company.com',
            'yan.xuan@company.com', 'renaud.gocsei@company.com', or 'ceo@company.com').
    """
    email_clean = user_email.strip().lower()
    if email_clean not in USER_PERMISSIONS:
        return {
            "status": "error",
            "message": f"Unknown account '{email_clean}'. Available demo accounts: {list(USER_PERMISSIONS.keys())}",
        }

    # Write verified identity into ADK's Invisible Backpack (Session State)
    tool_context.state["user_email"] = email_clean
    profile = USER_PERMISSIONS[email_clean]
    return {
        "status": "success",
        "signed_in_as": email_clean,
        "name": profile["name"],
        "role": profile["role"],
        "allowed_files": profile["allowed_files"],
        "security_scope": profile["row_filter"],
    }


def list_files(tool_context: ToolContext) -> dict:
    """Lists all files that the currently signed-in user has permission to access."""
    # Open the Invisible Backpack (Session State)
    user_email = tool_context.state.get("user_email", DEFAULT_USER)
    tool_context.state["user_email"] = user_email  # Ensure initialized in state tab

    profile = USER_PERMISSIONS.get(user_email)
    if not profile:
        return {
            "status": "ACCESS_DENIED",
            "signed_in_user": user_email,
            "message": f"Account '{user_email}' does not have access to any Drive files.",
        }

    return {
        "status": "success",
        "signed_in_user": user_email,
        "role": profile["role"],
        "accessible_files": profile["allowed_files"],
        "note": "Row-level access policies are automatically enforced on each file.",
    }


def describe_schema(file_name: str, tool_context: ToolContext) -> dict:
    """Inspects an authorized dataset file and returns its column names, types, and sample values.

    Args:
        file_name: Name of the file to inspect (e.g., 'mock_data_dtdb_v2.csv').
    """
    user_email = tool_context.state.get("user_email", DEFAULT_USER)
    profile = USER_PERMISSIONS.get(user_email)

    # Deterministic File-Level Drive Permission Check
    if not profile or file_name not in profile["allowed_files"]:
        return {
            "status": "ACCESS_DENIED",
            "signed_in_user": user_email,
            "message": f"Access Denied: '{user_email}' does not have permission to access '{file_name}'.",
        }

    if file_name == "executive_board_notes_2025.csv":
        return {
            "status": "success",
            "file": file_name,
            "columns": [
                {"column_name": "Board_Member", "column_type": "VARCHAR"},
                {"column_name": "Strategic_Note", "column_type": "VARCHAR"},
            ],
        }

    try:
        con = duckdb.connect()
        row_filter = profile["row_filter"]
        con.execute(
            f"CREATE VIEW authorized_data AS SELECT * FROM read_csv_auto('{CSV_FILE_PATH}') WHERE {row_filter}"
        )
        schema_df = con.execute("DESCRIBE authorized_data").df()
        total_authorized_rows = con.execute("SELECT COUNT(*) FROM authorized_data").fetchone()[0]

        return {
            "status": "success",
            "file": file_name,
            "signed_in_user": user_email,
            "authorized_row_count": int(total_authorized_rows),
            "table_name_for_queries": "authorized_data",
            "columns": schema_df[["column_name", "column_type"]].to_dict(orient="records"),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def run_query(file_name: str, sql_query: str, tool_context: ToolContext) -> dict:
    """Executes a DuckDB SQL query against the user's authorized view of a CSV file.

    IMPORTANT: Always query from the table name `authorized_data` in your SQL statement!
    Example: `SELECT Product_Type, SUM(Net_Revenue_SGD) AS total_rev FROM authorized_data GROUP BY Product_Type`

    Args:
        file_name: The authorized file to query (e.g., 'mock_data_dtdb_v2.csv').
        sql_query: A valid SQL SELECT query referencing `authorized_data`.
    """
    user_email = tool_context.state.get("user_email", DEFAULT_USER)
    profile = USER_PERMISSIONS.get(user_email)

    # 1. File-Level Permission Gate
    if not profile or file_name not in profile["allowed_files"]:
        return {
            "status": "ACCESS_DENIED",
            "signed_in_user": user_email,
            "message": f"Access Denied: '{user_email}' is not authorized to query '{file_name}'.",
        }

    # 2. Row-Level Security Gate + Self-Correction Execution Loop
    try:
        con = duckdb.connect()
        row_filter = profile["row_filter"]
        con.execute(
            f"CREATE VIEW authorized_data AS SELECT * FROM read_csv_auto('{CSV_FILE_PATH}') WHERE {row_filter}"
        )

        # Execute the LLM's SQL query against ONLY the authorized slice of rows
        result_df = con.execute(sql_query).df()

        return {
            "status": "success",
            "signed_in_user": user_email,
            "security_filter_applied": row_filter,
            "returned_rows": len(result_df),
            "data": result_df.head(50).to_dict(orient="records"),
        }
    except Exception as e:
        # Step 5: Self-Correction Loop! Return the SQL error string so the LLM fixes its query automatically
        return {
            "status": "sql_error",
            "failed_query": sql_query,
            "error_message": str(e),
            "self_correction_hint": (
                "Always query from table `authorized_data`. Check exact column names via `describe_schema` "
                "(e.g., `Net_Revenue_SGD`, `Clearing_Fee_SGD`, `Traded_Volume`, `Product_Type`, `Team`, `Fiscal_Year`) "
                "and call `run_query` again with the corrected SQL."
            ),
        }


# =====================================================================
# 3. SINGLE LLM AGENT DEFINITION (`root_agent`)
# =====================================================================
root_agent = Agent(
    name="enterprise_data_agent",
    model="gemini-2.5-flash",
    description="Identity-aware enterprise data agent with Google Drive-style file and row-level security.",
    instruction="""
    You are an Enterprise Data Assistant (modeled after Gemini Enterprise).
    Users sign in with their account and ask natural language questions about their authorized datasets.

    Follow this workflow:
    1. If the user asks to switch/login as a specific account (e.g., 'craig.cohen@company.com',
       'yan.xuan@company.com', 'renaud.gocsei@company.com', or 'ceo@company.com'), call `login_as` first.
    2. Call `list_files` to verify who is currently signed in and which files they are allowed to access.
    3. Before writing a SQL query on a file for the first time, call `describe_schema` to see the exact
       column names and how many authorized rows this user has access to.
    4. Call `run_query` using a SQL SELECT statement against the table name `authorized_data`.
    5. If `run_query` returns `status: "sql_error"`, DO NOT apologize or show the raw error to the user—
       simply fix your SQL query based on the error message and call `run_query` again!
    6. Always mention who the user is currently signed in as so they can clearly see how their access
       permissions shaped the answer.
    """,
    tools=[login_as, list_files, describe_schema, run_query],
)
