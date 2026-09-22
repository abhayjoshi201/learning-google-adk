"""Deploy `enterprise_data_agent` to Vertex AI Agent Engine using `AdkApp`.

Strictly follows `app/app_utils/deploy.py` from:
https://github.com/google/adk-samples/tree/main/core/python/oauth-user-consent-flow
"""

import datetime
import importlib
import json
import logging
import os
from pathlib import Path
from typing import Any
from dotenv import load_dotenv
import vertexai
from vertexai._genai import _agent_engines_utils
from vertexai._genai.types import AgentEngineConfig

ENV_PATH = Path(__file__).resolve().parent.parent / "enterprise_data_agent" / ".env"
load_dotenv(ENV_PATH)


def generate_class_methods_from_agent(agent_instance: Any) -> list[dict[str, Any]]:
    """Generate method specifications with schemas from agent's register_operations()."""
    registered_operations = _agent_engines_utils._get_registered_operations(
        agent=agent_instance
    )
    class_methods_spec = _agent_engines_utils._generate_class_methods_spec_or_raise(
        agent=agent_instance,
        operations=registered_operations,
    )
    return [
        _agent_engines_utils._to_dict(method_spec)
        for method_spec in class_methods_spec
    ]


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "rdang-test-464810")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    display_name = "Enterprise Drive Data Agent"
    description = (
        "Enterprise Google Drive OAuth 2.0 + DuckDB SQL Data Agent built with ADK"
    )
    entrypoint_module = "enterprise_data_agent.agent_engine_app"
    entrypoint_object = "agent_engine"
    requirements_file = "enterprise_data_agent/requirements.txt"

    print(f"Deploying '{display_name}' to project={project}, location={location}...")
    client = vertexai.Client(project=project, location=location)
    vertexai.init(project=project, location=location)

    module = importlib.import_module(entrypoint_module)
    agent_instance = getattr(module, entrypoint_object)
    class_methods_list = generate_class_methods_from_agent(agent_instance)

    env_vars = {
        "GOOGLE_CLOUD_REGION": location,
        "GOOGLE_CLOUD_LOCATION": "global",
        "MODEL_NAME": "gemini-3.7-flash",
        "GOOGLE_GENAI_USE_VERTEXAI": "1",
        "NUM_WORKERS": "1",
    }

    config = AgentEngineConfig(
        display_name=display_name,
        description=description,
        source_packages=["enterprise_data_agent"],
        entrypoint_module=entrypoint_module,
        entrypoint_object=entrypoint_object,
        class_methods=class_methods_list,
        env_vars=env_vars,
        requirements_file=requirements_file,
        min_instances=1,
        max_instances=10,
        resource_limits={"cpu": "4", "memory": "8Gi"},
        container_concurrency=9,
        agent_framework="google-adk",
    )

    existing_id = "projects/624784087790/locations/us-central1/reasoningEngines/448499039307038720"
    print(f"Updating existing Reasoning Engine in place: {existing_id}...")
    remote_agent = client.agent_engines.update(name=existing_id, config=config)
    resource_name = remote_agent.api_resource.name
    print(f"\n✅ Deployment successful! Reasoning Engine:\n{resource_name}")

    metadata = {
        "remote_agent_engine_id": resource_name,
        "deployment_target": "agent_engine",
        "deployment_timestamp": datetime.datetime.now().isoformat(),
    }
    with open("deployment_metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)


if __name__ == "__main__":
    main()
