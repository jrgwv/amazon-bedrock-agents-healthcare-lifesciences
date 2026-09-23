# Radiology Report Validator Agent — AgentCore

Validates radiology reports against American College of Radiology (ACR) guidance
documents. The agent stages the relevant ACR guideline PDF from S3 and grounds an
Amazon Bedrock `converse` call on it to produce terse, actionable feedback on a
report's adherence to ACR standards. Based on [agentcore_template](../../../agentcore_template).

Migrated from the notebook-driven Bedrock Agent + Lambda action group in the
[parent directory](../). The original Lambda carried unused SageMaker and AWS Batch
clients plus `BATCH_JOB_*` environment variables; that dead wiring was dropped in
this migration.

## Tools

| Tool | Purpose |
|------|---------|
| `download_guidance_document(anatomical_structure)` | Downloads the ACR guidance PDF(s) matching a modality/anatomical structure (e.g. `Chest`) from the S3 bucket into the local guidance directory. |
| `run_validator(report)` | Grounds a Bedrock `converse` call on the staged ACR guideline PDF and returns actionable validation feedback. |

## Prerequisites

The agent reads ACR guideline PDFs from an S3 bucket. Upload the PDFs from the
parent [`ACRdocs/`](../ACRdocs/) directory (e.g. `ACR_Chest.pdf`, `NormalChest.pdf`)
to the bucket, keying each object so the anatomical structure appears in the key
(e.g. `Chest/ACR_Chest.pdf`). The agent matches on the title-cased structure name.

## Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `MODEL_ID` | `global.anthropic.claude-sonnet-5` | Bedrock model (global inference profile) used for validation. |
| `BUCKET_NAME` | `radiologyreport-validator` | S3 bucket holding ACR guideline PDFs. |
| `GUIDANCE_DIR` | `<tmpdir>/acr_guidance` | Local directory where guideline PDFs are staged. |

The execution role needs `bedrock:InvokeModel` on the model and `s3:ListBucket` /
`s3:GetObject` on the guidance bucket.

## Deploy

```bash
# Option 1: Using deploy script (recommended)
npm install -g @aws/agentcore  # if not already installed
python deploy.py              # or: agentcore deploy -y

# Option 2: Using agentcore CLI directly
agentcore deploy
```

## Test

```bash
pytest tests/ -v
```
