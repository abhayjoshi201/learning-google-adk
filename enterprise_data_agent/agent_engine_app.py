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
"""Vertex AI Agent Engine entrypoint for `enterprise_data_agent`.

Strictly follows `app/agent_engine_app.py` from:
https://github.com/google/adk-samples/tree/main/core/python/oauth-user-consent-flow
"""

import logging
import os
from dotenv import load_dotenv
from google.adk.artifacts import InMemoryArtifactService
import vertexai
from vertexai.agent_engines.templates.adk import AdkApp

from enterprise_data_agent.agent import app as adk_app

load_dotenv()


class AgentEngineApp(AdkApp):
    """Wraps the ADK `App` for Vertex AI Agent Engine deployment."""

    def set_up(self) -> None:
        """Initialize the agent engine app with logging."""
        vertexai.init()
        super().set_up()
        logging.basicConfig(level=logging.INFO)
        if gemini_location:
            os.environ["GOOGLE_CLOUD_LOCATION"] = gemini_location


gemini_location = os.environ.get("GOOGLE_CLOUD_LOCATION")
agent_engine = AgentEngineApp(
    app=adk_app,
    artifact_service_builder=InMemoryArtifactService,
)
