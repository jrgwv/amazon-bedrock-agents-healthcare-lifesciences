"""
Agent task runner for the Clinical Trial Protocol Assistant.

Provides the agent_task() coroutine that initializes the agent (if needed),
streams responses, and pushes chunks to the response queue.
"""

import logging
from .context import ClinicalTrialContext
from .memory_hook_provider import MemoryHook
from .utils import get_ssm_parameter
from .agent import ClinicalTrialAgent
from bedrock_agentcore.memory import MemoryClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

memory_client = MemoryClient()


async def agent_task(user_message: str, session_id: str, actor_id: str):
    """Run the agent for a single user message, streaming chunks to the response queue."""
    agent = ClinicalTrialContext.get_agent_ctx()
    response_queue = ClinicalTrialContext.get_response_queue_ctx()

    try:
        if agent is None:
            memory_hook = None
            try:
                memory_id = get_ssm_parameter("/app/clinical-trial-assistant/agentcore/memory_id")
                memory_hook = MemoryHook(
                    memory_client=memory_client,
                    memory_id=memory_id,
                    actor_id=actor_id,
                    session_id=session_id,
                )
            except Exception as e:
                logger.warning(f"Memory not configured, running without memory: {e}")

            agent = ClinicalTrialAgent(memory_hook=memory_hook)
            ClinicalTrialContext.set_agent_ctx(agent)

        async for chunk in agent.stream(user_query=user_message):
            await response_queue.put(chunk)

    except Exception as e:
        logger.exception("Agent execution failed.")
        await response_queue.put(f"Error: {str(e)}")
    finally:
        await response_queue.finish()
