"""
BedrockAgentCoreApp entrypoint for the Clinical Trial Protocol Assistant.

Run with: agentcore launch (after agentcore configure)
"""

import asyncio
import logging
import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from agent.agent_config.context import ClinicalTrialContext
from agent.agent_config.agent_task import agent_task
from agent.agent_config.streaming_queue import StreamingQueue

# Enable Strands OTEL console export and tool console mode
os.environ["STRANDS_OTEL_ENABLE_CONSOLE_EXPORT"] = "true"
os.environ["STRANDS_TOOL_CONSOLE_MODE"] = "enabled"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()


@app.entrypoint
async def invoke(payload, context):
    """Main entrypoint: extract prompt, run agent, stream response."""
    if not ClinicalTrialContext.get_response_queue_ctx():
        ClinicalTrialContext.set_response_queue_ctx(StreamingQueue())

    user_message = payload["prompt"]
    actor_id = "default_user"
    session_id = context.session_id

    if not session_id:
        raise Exception("Context session_id is not set")

    task = asyncio.create_task(
        agent_task(
            user_message=user_message,
            session_id=session_id,
            actor_id=actor_id,
        )
    )

    response_queue = ClinicalTrialContext.get_response_queue_ctx()

    async def stream_output():
        async for event in response_queue.stream():
            logger.info(event)
            yield event
        await task  # Ensure task completion

    return stream_output()


if __name__ == "__main__":
    app.run()
