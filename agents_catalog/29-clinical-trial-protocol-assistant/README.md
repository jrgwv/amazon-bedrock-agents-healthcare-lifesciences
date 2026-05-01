# Clinical Trial Protocol Assistant

An AI agent built with the [Strands SDK](https://github.com/strands-agents/sdk-python) and deployed on [Amazon Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/) that helps clinical researchers design evidence-based trial protocols.

> ⚠️ **Disclaimer:** This agent is for demonstrative and research-assistance purposes only. It is NOT a substitute for professional medical, regulatory, or clinical judgment. All generated protocol outlines MUST be reviewed by qualified clinical experts before use.

---

## Architecture

The agent uses three discrete Strands `@tool` functions:

1. **`search_clinical_trials`** — Searches ClinicalTrials.gov API v2 for completed trials matching the disease area and phase
2. **`analyze_protocols`** — Analyzes retrieved trials for common endpoints, eligibility criteria patterns, and sample size statistics
3. **`generate_protocol_outline`** — Generates a structured Markdown protocol outline with evidence-based recommendations and citations

No AgentCore Gateway is required — all tools are local Python functions calling the public ClinicalTrials.gov REST API.

---

## Prerequisites

- Python 3.9+
- AWS CLI configured with appropriate permissions
- Amazon Bedrock access with `us.anthropic.claude-sonnet-4-5-20250929-v1:0` enabled
- `bedrock-agentcore` CLI installed (`pip install bedrock-agentcore-starter-toolkit`)

---

## Setup

### 1. Install dependencies

```bash
pip install -r agent/requirements.txt
```

### 2. (Optional) Set up infrastructure prerequisites

If you want to use the Streamlit OAuth UI or AgentCore Memory:

```bash
bash scripts/prereq.sh
```

### 3. (Optional) Create AgentCore Memory

```bash
python scripts/agentcore_memory.py create
```

### 4. Configure the AgentCore runtime

```bash
agentcore configure
```

Follow the prompts to set the agent name (e.g., `clinical-trial-assistant`) and entry point (`main.py`).

### 5. Launch the agent

```bash
agentcore launch
```

---

## Running the Streamlit UI

### IAM auth (local development)

```bash
streamlit run app.py
```

### OAuth auth (deployed)

```bash
streamlit run app_oauth.py
```

---

## Sample Queries

Once the agent is running, try these prompts:

- `Generate a protocol outline for Phase 3 trials in non-small cell lung cancer`
- `What are common endpoints for Phase 2 type 2 diabetes trials?`
- `Create a draft protocol for Phase 1 breast cancer studies`
- `Analyze completed Phase 3 trials for Alzheimer's disease`

---

## Running Tests

```bash
python3 -m pytest tests/test_tools.py -v
```

---

## Cleanup

To delete the deployed agent runtime:

```bash
python scripts/agentcore_agent_runtime.py clinical-trial-assistant
```

To delete AgentCore Memory:

```bash
python scripts/agentcore_memory.py delete
```

To delete infrastructure stacks:

```bash
bash scripts/cleanup.sh
```

---

## Project Structure

```
agents_catalog/29-clinical-trial-protocol-assistant/
├── agent/
│   ├── agent_config/
│   │   ├── agent.py                    # ClinicalTrialAgent class
│   │   ├── agent_task.py               # Agent task runner
│   │   ├── context.py                  # Session context
│   │   ├── memory_hook_provider.py     # AgentCore Memory integration
│   │   ├── streaming_queue.py          # Async streaming queue
│   │   ├── utils.py                    # SSM parameter helper
│   │   └── tools/
│   │       ├── clinical_trials_tools.py  # All three @tool functions + data models
│   │       └── validation.py             # Input validation helpers
│   └── requirements.txt
├── app.py                              # Streamlit UI (IAM auth)
├── app_oauth.py                        # Streamlit UI (OAuth)
├── app_modules/                        # Streamlit UI modules
├── main.py                             # BedrockAgentCoreApp entrypoint
├── scripts/                            # Deployment scripts
├── tests/
│   ├── test_tools.py                   # Unit tests for all three tools
│   └── test_agent.py                   # Integration smoke tests
├── dev-requirements.txt
├── requirements.txt
└── pytest.ini
```
