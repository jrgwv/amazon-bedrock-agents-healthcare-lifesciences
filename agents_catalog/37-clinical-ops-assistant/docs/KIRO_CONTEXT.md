# Kiro CLI Context — Clinical Ops Assistant (Bedrock Agent + Veeva Vault)

This document is written **for the Kiro CLI agent** doing the build. Read this end-to-end before generating code. It describes what to build, what shape the build must take, and the gotchas that will silently break the integration if missed.

---

## What you are building

A **read-only AWS Bedrock Agent** named `clinical-ops-assistant` that answers clinical operations questions by calling the **Veeva Vault Clinical REST API v26.1**. It follows the pattern in `aws-samples/amazon-bedrock-agents-healthcare-lifesciences/agents_catalog/`.

**Out of scope for v1:**
- No write operations against Vault
- No subject-level PHI in responses (aggregate only)
- No federated user-impersonation auth (use a service account)
- No knowledge base / RAG (plain action-group agent only)

---

## Repository layout to produce

```
clinical-ops-assistant/
  README.md                          # User-facing docs
  agent_config.yaml                  # Bedrock Agent definition (model, instructions, action group refs)
  openapi_schema.yaml                # Action group API spec (Bedrock reads this to plan tool use)
  action_groups/
    vault_clinical/
      lambda/
        handler.py                   # Lambda entrypoint — Bedrock event → Vault REST → response
        vault_client.py              # Vault auth + session caching + HTTP client
        models.py                    # Pydantic v2 response models (mirror openapi_schema.yaml)
        operations.py                # One function per operationId in openapi_schema.yaml
        requirements.txt             # httpx, pydantic, aws-lambda-powertools, boto3
      Dockerfile                     # Container image base: public.ecr.aws/lambda/python:3.12
  cdk/
    bin/app.ts                       # CDK app entrypoint
    lib/clinical-ops-assistant-stack.ts  # CDK stack
    package.json
    tsconfig.json
    cdk.json
  tests/
    unit/
      test_vault_client.py
      test_operations.py
    integration/
      test_against_sandbox.py        # Optional, gated by env var
  .gitignore
```

---

## Tech stack — locked decisions

| Layer | Choice |
|---|---|
| Agent runtime | AWS Bedrock Agents (foundation model: Anthropic Claude Sonnet, latest available in Bedrock) |
| Lambda runtime | Python 3.12, container image |
| Lambda framework | AWS Lambda Powertools (Logger, Tracer, Metrics, Parameters) |
| HTTP client | `httpx` (sync, with timeout=10s) |
| Validation | Pydantic v2 |
| Package manager | `uv` |
| Secrets | AWS Secrets Manager (Vault credentials) |
| Session cache | DynamoDB single-table (TTL on session items) |
| IaC | AWS CDK v2, TypeScript |
| Region | `us-east-1` (override via context) |
| Tests | `pytest` for unit; integration tests are opt-in via `VAULT_RUN_INTEGRATION_TESTS=1` |
| Linting | `ruff` + `black` |

---

## Vault auth pattern (most-likely-to-be-missed details)

Vault uses **session-based auth**, not bearer tokens.

1. **Auth call:** `POST https://{vault_subdomain}.veevavault.com/api/v26.1/auth` with form-encoded body `username=...&password=...`. Returns `sessionId` and `vaultIds`.
2. **Authenticated calls:** include header `Authorization: <sessionId>` (no `Bearer ` prefix — that's not a typo; Vault deviates from RFC 6750 here).
3. **Session expiry:** sessions expire after inactivity (default 20 minutes) or absolute lifetime. On `401`, re-authenticate and retry **once**. Do not loop.
4. **Session caching:** cache `sessionId` in DynamoDB with TTL set to ~15 minutes from issue (under the inactivity window). Use a partition key like `SESSION#<vault_subdomain>`. This avoids logging in on every Lambda invocation.
5. **Concurrent Lambda safety:** if two Lambda invocations race to refresh the session, the second login wins; the first session is silently invalidated. Use conditional writes on the cache item (`attribute_not_exists` or version stamp) to avoid thundering-herd logins.
6. **Never log session IDs or credentials.** Powertools logger should redact `Authorization`, `password`, `sessionId` keys.

```python
# Conceptual flow inside vault_client.py
def get_session() -> str:
    cached = ddb.get_item(...)
    if cached and not_expired(cached):
        return cached["sessionId"]
    creds = secrets_manager.get_secret_value(...)
    resp = httpx.post(f"{base_url}/api/v26.1/auth", data=creds, timeout=10)
    session = resp.json()["sessionId"]
    ddb.put_item(..., ttl=now + 900)  # 15 min
    return session
```

---

## Vault REST API specifics

- **Base URL pattern:** `https://{subdomain}.veevavault.com/api/v26.1/...` — the subdomain is per-customer-Vault and must come from config, not be hardcoded.
- **VQL (Vault Query Language):** the search/listing endpoints use a SQL-like `q` parameter. For example:
  - `SELECT id, name__v, status__v, phase__v FROM study__v WHERE status__v = 'active__c' LIMIT 25`
  - VQL field names end in `__v` (system) or `__c` (custom). Don't omit the suffix.
- **Object names:** `study__v`, `study_site__v`, `milestone__v`, `document__v` (and variants). The customer's Vault may have custom objects; treat object names as configurable.
- **Pagination:** Vault returns `responseDetails.next_page` URLs. Implement pagination only if needed for v1; otherwise honor `limit` and document the cap.
- **Rate limits:** Vault enforces per-user burst limits (default 2,000 requests/5 min). Cache aggressively. Add jittered exponential backoff on `429`.
- **Error shape:** Vault errors come back as `{ "responseStatus": "FAILURE", "errors": [{ "type": "...", "message": "..." }] }`. Lambda must translate these into Bedrock-friendly responses (don't leak raw Vault errors to the user — log them, return a sanitized summary).

---

## Lambda → Bedrock contract

Bedrock Agents invoke the Lambda with a specific event shape and expect a specific response shape. **Get this wrong and the agent will appear "broken" with no helpful error.**

**Inbound event (relevant fields):**
```json
{
  "messageVersion": "1.0",
  "agent": { ... },
  "actionGroup": "vault_clinical",
  "apiPath": "/studies/{studyName}",
  "httpMethod": "GET",
  "parameters": [{ "name": "studyName", "type": "string", "value": "BMS-986365-001" }],
  "requestBody": { ... }  // present on POST/PUT
}
```

**Outbound response shape (required):**
```json
{
  "messageVersion": "1.0",
  "response": {
    "actionGroup": "vault_clinical",
    "apiPath": "/studies/{studyName}",
    "httpMethod": "GET",
    "httpStatusCode": 200,
    "responseBody": {
      "application/json": {
        "body": "{ \"study_name\": \"BMS-986365-001\", ... }"  // STRING, not object
      }
    }
  }
}
```

**Critical: `body` is a JSON string, not a JSON object.** Pydantic models must be `.model_dump_json()` then placed in `body` as a string.

---

## Routing pattern in `handler.py`

Use one Lambda for the whole action group; route by `apiPath` + `httpMethod`:

```python
ROUTES = {
    ("GET", "/studies"): operations.list_studies,
    ("GET", "/studies/{studyName}"): operations.get_study_by_name,
    ("GET", "/studies/{studyName}/sites"): operations.list_sites_for_study,
    ("GET", "/studies/{studyName}/milestones"): operations.list_milestones_for_study,
    ("GET", "/documents/search"): operations.search_documents,
    ("GET", "/documents/{documentId}"): operations.get_document_metadata,
}
```

Each operation function takes a typed `params` dict and returns a Pydantic model. The handler serializes to the Bedrock response shape.

---

## Agent instructions (system prompt) — write into `agent_config.yaml`

```
You are Clinical Ops Assistant, a read-only assistant that helps clinical operations
team members query our Veeva Vault Clinical environment.

Capabilities:
- Look up studies, sites, milestones, and documents
- Summarize enrollment, timelines, and site performance
- Find documents in the eTMF and provide Vault deep links

Constraints:
- You have read-only access. If a user asks you to update, edit, create, or delete
  anything in Vault, explain that you cannot make changes and direct them to open
  the record in the Vault UI.
- Do not return individual subject identifiers, names, or other PHI. Aggregate
  metrics (counts, percentages) are fine. If a user explicitly requests subject-
  level data, decline and explain why.
- If a study, site, or document is not found, say so clearly. Do not fabricate.
- When you cite information, include the Vault deep link the user can open
  (the `vault_url` field in responses).
- If a user's request is ambiguous (e.g., a partial study name matches several
  studies), list the candidates and ask the user to confirm before continuing.
- All numbers you cite must come from Vault responses, not from your training data.

Tone: concise, factual, professional. Use bullet points for lists of studies,
sites, or milestones. Do not editorialize.
```

---

## CDK stack — what to provision

| Resource | Purpose |
|---|---|
| Bedrock Agent | The agent itself, with the `agent_config.yaml` instructions |
| Bedrock Agent Action Group | Pointed at the Lambda + the OpenAPI schema |
| Bedrock Agent Alias | Stable alias for invocation (e.g., `prod`, `dev`) |
| Lambda function (container image) | The action-group Lambda |
| ECR repository | Holds the Lambda container image |
| DynamoDB table | Single-table for session cache, TTL enabled |
| Secrets Manager secret | Vault service-account credentials |
| IAM role for Lambda | Least privilege: `bedrock:*` (caller side handled), `secretsmanager:GetSecretValue` (the one secret), `dynamodb:GetItem`/`PutItem` (the one table), `logs:*`, `xray:*` |
| CloudWatch Log group | Lambda logs, 30-day retention |

**Do NOT** provision:
- A VPC (the Lambda only calls public HTTPS endpoints)
- A Cognito pool (no end-user auth on this agent for v1)
- Any frontend (the agent is invoked via the Bedrock console, the SDK, or a downstream chat UI)

---

## Configuration values the build needs

These should be CDK context or environment variables, not hardcoded:

| Name | Description | Example |
|---|---|---|
| `VAULT_BASE_URL` | The customer's Vault subdomain root | `https://my-vault.veevavault.com` |
| `VAULT_API_VERSION` | Pinned API version | `v26.1` |
| `VAULT_AUTH_SECRET_ARN` | ARN of the Secrets Manager secret holding `{username, password}` | populated by CDK |
| `SESSION_CACHE_TABLE` | DynamoDB table name | populated by CDK |
| `LOG_LEVEL` | Powertools log level | `INFO` |
| `BEDROCK_MODEL_ID` | Foundation model for the agent | `anthropic.claude-3-7-sonnet-20250219-v1:0` (or latest available) |

---

## Hard rules for the Kiro CLI

1. **Do not invent Vault object or field names.** When in doubt, leave a `# TODO: confirm Vault object name with customer` comment instead of guessing. The customer's Vault may have custom objects.
2. **Do not write any operation that mutates Vault data** (`POST`, `PUT`, `DELETE` against Vault) in v1. If a user-facing capability requires writes, stub it out with a clear `NotImplementedError` and a comment.
3. **Do not log credentials, session IDs, or PHI.** Configure Powertools logger to redact `password`, `sessionId`, `Authorization`, `subject_id`, `subject_name` keys.
4. **All HTTP calls must have explicit timeouts.** Default `httpx` timeout is None (forever). Use `httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0))`.
5. **Pin the Vault API version in URLs.** Use the `VAULT_API_VERSION` config; don't sprinkle `v26.1` literals throughout.
6. **The Lambda response `body` is a JSON string, not an object.** Use `model.model_dump_json()`, not `model.model_dump()`.
7. **Treat the OpenAPI schema as the contract.** Operation IDs in `openapi_schema.yaml` must match function names in `operations.py` exactly. Bedrock uses operation descriptions to plan tool calls — keep them clear and intent-focused.
8. **Don't add new endpoints to `openapi_schema.yaml` without updating `handler.py` routes, `operations.py` functions, AND the agent instructions if relevant.** All four move together.
9. **No subject-level PHI fields in any response model**, even if Vault returns them. Filter at the operations layer before constructing the Pydantic model.
10. **Tests are required for `vault_client.py`** (auth + session caching + 401 retry). Mock `httpx` and `boto3`. Integration tests are optional and gated by env var.

---

## Suggested build order

1. CDK skeleton (empty stack that synthesizes)
2. DynamoDB table + Secrets Manager secret + IAM role
3. `vault_client.py` with auth + session caching + tests
4. One operation end-to-end: `getStudyByName`, including its Pydantic model and unit test
5. Lambda handler with routing, deployed via container image
6. Bedrock Agent + action group + alias, pointed at the Lambda and the OpenAPI schema
7. Test in the Bedrock console with a few prompts ("show me study X", "what's the status of...")
8. Add remaining operations one at a time
9. README with setup, deploy, and example prompts

Stop after step 7 and validate before scaling out — that's where most integration bugs show up.

---

## What "done" looks like for v1

- A Bedrock Agent that, when invoked in the AWS console, can answer:
  - "What active phase 3 studies do I have?"
  - "Show me the milestones for study BMS-986365-001"
  - "Which sites in Germany are below 50% enrollment?"
  - "Find the latest investigator brochure for study X"
- All responses cite a Vault deep link
- No subject-level PHI in any response
- Lambda cold start under 8 seconds; warm latency under 2 seconds
- `cdk deploy` from a clean account succeeds
- Unit tests pass; integration tests pass against a Vault sandbox if `VAULT_RUN_INTEGRATION_TESTS=1`

---

## When the build is done, hand back

- The deployed Bedrock Agent ID and alias ARN
- A list of the operations exposed (mirrors `openapi_schema.yaml`)
- Example prompts that work
- Any Vault object/field names that were guessed and need customer confirmation
