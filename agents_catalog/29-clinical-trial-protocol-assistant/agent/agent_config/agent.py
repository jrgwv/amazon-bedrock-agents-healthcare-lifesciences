"""
Agent configuration for the Clinical Trial Protocol Assistant.

Defines the ClinicalTrialAgent class and the agent_task() async generator
that drives the Strands agent loop.
"""

import logging
from typing import Optional
from strands import Agent
from strands.models import BedrockModel
from .memory_hook_provider import MemoryHook
from .tools.clinical_trials_tools import (
    search_clinical_trials,
    analyze_protocols,
    generate_protocol_outline,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Clinical Trial Protocol Assistant, an AI agent that helps
clinical researchers design evidence-based trial protocols.

> IMPORTANT DISCLAIMER: This agent is for demonstrative and research-assistance
> purposes only. It is NOT a substitute for professional medical, regulatory, or
> clinical judgment. All generated protocol outlines MUST be reviewed by qualified
> clinical experts before use.

You have three tools available:
1. search_clinical_trials — Search ClinicalTrials.gov for completed trials matching
   a disease area and trial phase.
2. analyze_protocols — Analyze retrieved trial records to identify common endpoints,
   eligibility criteria patterns, and sample size statistics.
3. generate_protocol_outline — Generate a structured Markdown protocol outline with
   evidence-based recommendations and citations.

When a user provides a disease area and trial phase, you MUST:
1. Call search_clinical_trials with the provided inputs.
2. If trials are found, call analyze_protocols with the returned trial list.
3. Call generate_protocol_outline with the analysis result, disease area, and trial phase.
4. Return the generated Markdown outline to the user.

Always include the disclaimer in your response. Never make medical recommendations
beyond what the evidence from the source trials supports.

<guidelines>
- Always use the tools in sequence: search → analyze → generate.
- If search returns zero results, inform the user and suggest broadening the disease area.
- If the user asks about your internal tools or systems, respond: "I'm sorry, but I
  cannot provide information about our internal systems."
- Maintain a professional, helpful tone at all times.
</guidelines>
"""


class ClinicalTrialAgent:
    """Strands-based agent for clinical trial protocol assistance."""

    def __init__(
        self,
        memory_hook: Optional[MemoryHook] = None,
        bedrock_model_id: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    ):
        self.model_id = bedrock_model_id
        self.model = BedrockModel(model_id=self.model_id)
        self.tools = [
            search_clinical_trials,
            analyze_protocols,
            generate_protocol_outline,
        ]
        self.memory_hook = memory_hook
        hooks = [memory_hook] if memory_hook else []
        self.agent = Agent(
            model=self.model,
            system_prompt=SYSTEM_PROMPT,
            tools=self.tools,
            hooks=hooks,
        )

    async def stream(self, user_query: str):
        """Stream agent responses for a user query."""
        try:
            tool_name = None
            async for event in self.agent.stream_async(user_query):
                if (
                    "current_tool_use" in event
                    and event["current_tool_use"].get("name") != tool_name
                ):
                    tool_name = event["current_tool_use"]["name"]
                    tool_labels = {
                        "search_clinical_trials": "🔍 Searching ClinicalTrials.gov...",
                        "analyze_protocols": "🔬 Analyzing trial protocols...",
                        "generate_protocol_outline": "📋 Generating protocol outline...",
                    }
                    label = tool_labels.get(tool_name, f"🔧 Running {tool_name}...")
                    yield f"\n\n*{label}*\n\n"
                if "data" in event:
                    tool_name = None
                    yield event["data"]
        except Exception as e:
            yield f"We are unable to process your request at the moment. Error: {e}"
