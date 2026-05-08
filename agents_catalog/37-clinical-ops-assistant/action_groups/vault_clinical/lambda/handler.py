"""Lambda handler for Bedrock Agent action group — routes to Vault operations."""

from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext

import operations

logger = Logger()
tracer = Tracer()

ROUTES = {
    ("GET", "/studies"): operations.list_studies,
    ("GET", "/studies/{studyName}"): operations.get_study_by_name,
    ("GET", "/studies/{studyName}/sites"): operations.list_sites_for_study,
    ("GET", "/studies/{studyName}/milestones"): operations.list_milestones_for_study,
    ("GET", "/documents/search"): operations.search_documents,
    ("GET", "/documents/{documentId}"): operations.get_document_metadata,
}


def _extract_params(event: dict) -> dict:
    """Extract parameters from Bedrock Agent event into a flat dict."""
    params = {}
    for p in event.get("parameters", []):
        params[p["name"]] = p["value"]
    if event.get("requestBody"):
        body = event["requestBody"].get("content", {}).get("application/json", {})
        if body.get("properties"):
            for prop in body["properties"]:
                params[prop["name"]] = prop["value"]
    return params


def _build_response(event: dict, status_code: int, body: str) -> dict:
    """Build Bedrock Agent response in the required format."""
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup", "vault_clinical"),
            "apiPath": event.get("apiPath", ""),
            "httpMethod": event.get("httpMethod", "GET"),
            "httpStatusCode": status_code,
            "responseBody": {
                "application/json": {"body": body}
            },
        },
    }


@tracer.capture_lambda_handler
@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> dict:
    """Bedrock Agent action group Lambda handler."""
    api_path = event.get("apiPath", "")
    http_method = event.get("httpMethod", "GET").upper()

    logger.info("Received request", extra={"apiPath": api_path, "httpMethod": http_method})

    route_key = (http_method, api_path)
    operation_fn = ROUTES.get(route_key)

    if not operation_fn:
        return _build_response(event, 404, '{"error": "Operation not found"}')

    try:
        params = _extract_params(event)
        result = operation_fn(params)
        body = result.model_dump_json()
        return _build_response(event, 200, body)
    except Exception as e:
        logger.exception("Operation failed")
        return _build_response(event, 500, f'{{"error": "{str(e)}"}}')
