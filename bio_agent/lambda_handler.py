"""
AWS Lambda handler for Bedrock Agent biodiversity tools.
Supports both OpenAPI schema (apiPath) and function-details (function) invocation.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from tools.get_hex_metrics import handler as get_hex_metrics
from tools.get_neighbor_hexes import handler as get_neighbor_hexes
from tools.get_neighbor_summary import handler as get_neighbor_summary
from tools.get_hex_species_context import handler as get_hex_species_context
from tools.get_osm_context import handler as get_osm_context
from tools.get_info_about_threatened_species import handler as get_info_about_threatened_species
from tools.get_species_profiles import handler as get_species_profiles

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Quick-action fallback: Bedrock sometimes sends action_group_quick_action1
QUICK_ACTION_NAMES = ("action_group_quick_action1", "action_group_quick_action", "quick_action")

# Map apiPath or function name to handler
TOOL_HANDLERS = {
    "GetHexMetrics": get_hex_metrics,
    "getHexMetrics": get_hex_metrics,
    "/getHexMetrics": get_hex_metrics,
    "GetNeighborHexes": get_neighbor_hexes,
    "getNeighborHexes": get_neighbor_hexes,
    "/getNeighborHexes": get_neighbor_hexes,
    "GetNeighborSummary": get_neighbor_summary,
    "getNeighborSummary": get_neighbor_summary,
    "/getNeighborSummary": get_neighbor_summary,
    "GetHexSpeciesContext": get_hex_species_context,
    "getHexSpeciesContext": get_hex_species_context,
    "/getHexSpeciesContext": get_hex_species_context,
    "GetOSMContext": get_osm_context,
    "getOSMContext": get_osm_context,
    "/getOSMContext": get_osm_context,
    "GetInfoAboutThreatenedSpecies": get_info_about_threatened_species,
    "getInfoAboutThreatenedSpecies": get_info_about_threatened_species,
    "/getInfoAboutThreatenedSpecies": get_info_about_threatened_species,
    "GetSpeciesProfiles": get_species_profiles,
    "getSpeciesProfiles": get_species_profiles,
    "/getSpeciesProfiles": get_species_profiles,
}


def _extract_params(event: dict) -> tuple[list[dict], dict | None]:
    """Extract parameters from OpenAPI or function-details event."""
    params = event.get("parameters") or []
    body = event.get("requestBody")
    return params, body


def _params_to_dict(params: list[dict], body: dict | None) -> dict[str, Any]:
    """Build flat dict of param name -> value from params and body."""
    p: dict[str, Any] = {}
    for x in (params or []):
        if isinstance(x, dict) and x.get("name"):
            p[x["name"]] = x.get("value")
    if body and isinstance(body, dict):
        props = body.get("content", {}).get("application/json", {}).get("properties", [])
        if isinstance(props, list):
            for x in props:
                if isinstance(x, dict) and x.get("name"):
                    p[x["name"]] = x.get("value", p.get(x["name"]))
        elif isinstance(props, dict):
            p.update(props)
    return p


def _infer_tool_from_params(params: list[dict], body: dict | None) -> str | None:
    """Infer tool name when Bedrock sends action_group_quick_action1."""
    p = _params_to_dict(params, body)
    h3_ids = p.get("h3_ids") or p.get("h3Ids")
    k_ring = p.get("k_ring") or p.get("kRing")
    species_ids = p.get("species_ids") or p.get("speciesIds")
    species_names = p.get("species_names") or p.get("speciesNames")
    species_ids_or_names = p.get("species_ids_or_names") or p.get("speciesIdsOrNames")
    h3_id = p.get("h3_id") or p.get("h3Id")
    h3_res = p.get("h3_res") or p.get("h3Res")

    if h3_ids is not None:
        return "GetNeighborSummary"
    if k_ring is not None:
        return "GetNeighborHexes"
    if species_ids or species_names:
        return "GetSpeciesProfiles"
    if species_ids_or_names:
        return "GetInfoAboutThreatenedSpecies"
    if h3_id and h3_res is not None:
        return "GetHexMetrics"
    return None


def _build_openapi_response(event: dict, body: dict, status: int = 200) -> dict:
    """Build response for OpenAPI schema action group."""
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup", ""),
            "apiPath": event.get("apiPath", ""),
            "httpMethod": event.get("httpMethod", "POST"),
            "httpStatusCode": status,
            "responseBody": {
                "application/json": {
                    "body": json.dumps(body),
                },
            },
        },
        "sessionAttributes": event.get("sessionAttributes") or {},
        "promptSessionAttributes": event.get("promptSessionAttributes") or {},
    }


def _build_function_response(event: dict, body: dict, state: str = "SUCCESS") -> dict:
    """Build response for function-details action group."""
    func_resp: dict[str, Any] = {
        "responseBody": {
            "TEXT": {
                "body": json.dumps(body),
            },
        },
    }
    if state != "SUCCESS":
        func_resp["responseState"] = state
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup", ""),
            "function": event.get("function", ""),
            "functionResponse": func_resp,
        },
        "sessionAttributes": event.get("sessionAttributes") or {},
        "promptSessionAttributes": event.get("promptSessionAttributes") or {},
    }


def lambda_handler(event: dict, context: Any) -> dict:
    """
    Main Lambda entry point for Bedrock Agent action group.
    Routes to the appropriate tool handler based on apiPath or function.
    """
    logger.info(
        "Bedrock invocation: apiPath=%s function=%s actionGroup=%s keys=%s",
        event.get("apiPath"),
        event.get("function"),
        event.get("actionGroup"),
        list(event.keys()),
    )
    try:
        # Determine tool: OpenAPI uses apiPath, function-details uses function
        api_path = event.get("apiPath", "").strip("/") or event.get("apiPath")
        func_name = event.get("function", "")
        tool_key = api_path or func_name

        if not tool_key:
            logger.error("Missing apiPath and function in event")
            err_body = {"error": "Missing apiPath or function", "message": "Invalid invocation"}
            if "function" in event:
                return _build_function_response(event, err_body, "FAILURE")
            return _build_openapi_response(event, err_body, 400)

        params, body = _extract_params(event)

        # Fallback for Bedrock quick-action (sends action_group_quick_action1)
        if tool_key in QUICK_ACTION_NAMES:
            inferred = _infer_tool_from_params(params, body)
            if inferred:
                tool_key = inferred
                logger.info("Inferred tool from params: %s", tool_key)
            else:
                logger.error("Quick action but could not infer tool from params")
                err_body = {"error": "Unknown tool", "tool": tool_key, "message": "Could not infer tool from parameters"}
                if "function" in event:
                    return _build_function_response(event, err_body, "FAILURE")
                return _build_openapi_response(event, err_body, 404)

        handler_fn = TOOL_HANDLERS.get(tool_key) or TOOL_HANDLERS.get("/" + tool_key)
        if not handler_fn:
            logger.error("Unknown tool: %s", tool_key)
            err_body = {"error": "Unknown tool", "tool": tool_key}
            if "function" in event:
                return _build_function_response(event, err_body, "FAILURE")
            return _build_openapi_response(event, err_body, 404)
        logger.info("Extracted params count=%d body=%s", len(params), "present" if body else "None")
        result = handler_fn(params, body)
        logger.info("Handler succeeded, returning response")

        if "function" in event:
            resp = _build_function_response(event, result)
        else:
            resp = _build_openapi_response(event, result)
        resp_size = len(json.dumps(resp))
        logger.info("Response size: %d bytes", resp_size)
        if resp_size > 5_000_000:
            logger.warning("Response very large (%d bytes), may exceed Lambda limit", resp_size)
        return resp

    except ValueError as e:
        logger.warning("Validation error: %s", e)
        err_body = {"error": "ValidationError", "message": str(e)}
        if event.get("function"):
            return _build_function_response(event, err_body, "REPROMPT")
        return _build_openapi_response(event, err_body, 400)
    except Exception as e:
        logger.exception("Tool execution failed: %s", e)
        err_body = {"error": "InternalError", "message": str(e)}
        if event.get("function"):
            return _build_function_response(event, err_body, "FAILURE")
        return _build_openapi_response(event, err_body, 500)
