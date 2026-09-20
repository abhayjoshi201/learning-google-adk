# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os

import google.auth
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

from .tools import list_drive_files, query_drive_csv, read_drive_file

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id or "rdang-test-464810")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model=os.getenv("MODEL_NAME", "gemini-2.5-flash"),
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""You are a helpful AI assistant that can read and query files from Google Drive.

When a user wants to read or query a file from Google Drive:
1. Use `list_drive_files` to find the file ID, or ask for the file ID if they have a sharing URL:
   https://drive.google.com/file/d/<FILE_ID>/view
2. Use `read_drive_file` with the file ID to inspect the file, or `query_drive_csv` (querying table `drive_data`)
   to run SQL aggregations over CSVs or Google Sheets.
3. Present the file content or query results to the user in a clear, readable format.
4. If a tool returns a "pending" status, let the user know that
   authentication is required and they should complete the OAuth consent.
""",
    tools=[list_drive_files, read_drive_file, query_drive_csv],
)

app = App(
    root_agent=root_agent,
    name="app",
)
