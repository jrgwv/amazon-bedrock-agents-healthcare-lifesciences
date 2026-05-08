# Clinical Ops Assistant

Read-only AWS Bedrock Agent that answers clinical operations questions by querying a **Veeva Vault Clinical** environment (CTMS / eTMF) via the Vault REST API v26.1.

## Capabilities

- Look up studies by name, status, phase, or therapeutic area
- List sites for a study with enrollment metrics
- View study milestones and timelines
- Search eTMF documents and retrieve metadata
- Provide Vault deep links for all records

## Architecture

```
User → Bedrock Agent → Lambda (action group) → Veeva Vault REST API v26.1
                                    ↕
                          DynamoDB (session cache)
                          Secrets Manager (credentials)
```

- **Model**: Claude Sonnet 4.5
- **Auth**: Vault session-based auth with DynamoDB caching + 401 retry
- **Scope**: Read-only (no writes to Vault)
- **PHI**: No subject-level data returned

## Operations

| Operation | Description |
|-----------|-------------|
| `listStudies` | List studies with optional filters (status, phase, therapeutic area) |
| `getStudyByName` | Get full metadata for a specific study |
| `listSitesForStudy` | List sites for a study with enrollment data |
| `listMilestonesForStudy` | List milestones with planned/actual dates |
| `searchDocuments` | Search eTMF documents by study, type, or keyword |
| `getDocumentMetadata` | Get metadata for a specific document |

## Prerequisites

- AWS account with Bedrock access
- Veeva Vault Clinical environment with API access
- Service account credentials for Vault

## Deploy

```bash
# 1. Install CDK dependencies
cd cdk && npm install

# 2. Set Vault URL in context
# Edit cdk/cdk.json → context.vaultBaseUrl

# 3. Deploy
cdk deploy

# 4. Store Vault credentials in Secrets Manager
aws secretsmanager put-secret-value \
  --secret-id clinical-ops-assistant/vault-credentials \
  --secret-string '{"username":"svc_bedrock","password":"YOUR_PASSWORD"}'
```

## Test

```bash
# Unit tests (no AWS needed)
cd tests/unit
pip install pytest pydantic httpx
pytest -v

# Integration tests (requires Vault sandbox)
VAULT_RUN_INTEGRATION_TESTS=1 pytest tests/integration/ -v
```

## Example Prompts

- "What active phase 3 studies do I have?"
- "Show me the milestones for study BMS-986365-001"
- "Which sites in Germany are below 50% enrollment?"
- "Find the latest investigator brochure for study X"
- "What's the status of site 042 in the ONCO-2025 study?"

## Configuration

| Variable | Description |
|----------|-------------|
| `VAULT_BASE_URL` | Customer Vault URL (e.g., `https://customer.veevavault.com`) |
| `VAULT_API_VERSION` | Pinned API version (`v26.1`) |
| `VAULT_AUTH_SECRET_ARN` | Secrets Manager ARN for credentials |
| `SESSION_CACHE_TABLE` | DynamoDB table for session caching |

## Notes

- Vault object/field names (e.g., `study__v`, `status__v`) may vary by customer configuration. Confirm with your Vault admin.
- Rate limits: Vault enforces 2,000 requests/5 min per user. The agent caches sessions and uses VQL to minimize calls.
- This is a v1 read-only agent. Write operations are intentionally excluded per GxP/21 CFR Part 11 considerations.
