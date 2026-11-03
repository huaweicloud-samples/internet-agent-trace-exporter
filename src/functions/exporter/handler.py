"""
Agent Trace Exporter — FunctionGraph handler (Huawei Cloud).

This function is the serverless processor of a log sidecar ETL pipeline:
it receives trace spans that agent runtimes and frameworks write into a
log stream (Log Tank Service, LTS), filters them by configurable attribute
values, converts the matching spans to OTLP format, and exports them to
one or more OTLP-compatible backends (a self-built OpenTelemetry Collector,
Grafana Tempo, Jaeger, Datadog, Splunk, New Relic, etc.).

Architecture-equivalent port of the original streaming delivery pipeline
processor (log subscription -> delivery stream -> transformation function):

  * Decodes every supported event envelope (LTS trigger envelope,
    base64 + gzip delivery envelope, and directly posted span / OTLP batch).
  * Filters spans by attribute values (exact or prefix match, multi-value).
  * Converts matching spans to OTLP/HTTP JSON (default, zero dependencies)
    or OTLP/HTTP protobuf (when a dependency package is attached).
  * Fans out to all configured OTLP endpoints. DRY_RUN is enabled by default:
    the function logs input/output instead of making the HTTP calls.
  * Keeps the Ok / Dropped / ProcessingFailed record-disposition protocol
    in the logs and in the returned summary for troubleshooting.

The handler signature handler(event, context) matches the common serverless
function contract.
"""

from __future__ import annotations

import base64
import gzip
import json
import logging
import os
from typing import Any

from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Configuration (injected as function environment variables / user_data)
# ---------------------------------------------------------------------------

OTLP_ENDPOINTS_JSON = os.environ.get("OTLP_ENDPOINTS", "")
OTLP_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
OTLP_HEADERS = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "")
FILTER_ATTRIBUTES = os.environ.get("FILTER_SPAN_ATTRIBUTES", "")
# Encoding: "json" (default, zero deps) or "protobuf" (needs a dependency package).
OTLP_ENCODING = os.environ.get("OTLP_ENCODING", "json").lower()
# Dry run mode: logs input/output instead of sending to OTLP. Default "true".
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() in ("true", "1", "yes")

# Record disposition (kept from the original delivery protocol)
RESULT_OK = "Ok"
RESULT_DROPPED = "Dropped"
RESULT_FAILED = "ProcessingFailed"

# Span kind string-to-int mapping (OTLP uses integers)
_SPAN_KIND_MAP = {
    "INTERNAL": 1,
    "SERVER": 2,
    "CLIENT": 3,
    "PRODUCER": 4,
    "CONSUMER": 5,
    "SPAN_KIND_INTERNAL": 1,
    "SPAN_KIND_SERVER": 2,
    "SPAN_KIND_CLIENT": 3,
    "SPAN_KIND_PRODUCER": 4,
    "SPAN_KIND_CONSUMER": 5,
}

# Status code string-to-int mapping
_STATUS_CODE_MAP = {
    "UNSET": 0,
    "OK": 1,
    "ERROR": 2,
    "STATUS_CODE_UNSET": 0,
    "STATUS_CODE_OK": 1,
    "STATUS_CODE_ERROR": 2,
}


# ---------------------------------------------------------------------------
# Configuration parsing
# ---------------------------------------------------------------------------


def parse_otlp_headers(headers_str: str) -> dict[str, str]:
    """Parse OTEL_EXPORTER_OTLP_HEADERS format: key=value,key2=value2."""
    headers: dict[str, str] = {}
    if not headers_str:
        return headers
    for pair in headers_str.split(","):
        pair = pair.strip()
        if "=" in pair:
            key, value = pair.split("=", 1)
            headers[key.strip()] = value.strip()
    return headers


def parse_otlp_endpoints(
    endpoints_json: str, fallback_endpoint: str, fallback_headers: str
) -> list[dict[str, str]]:
    """
    Parse the OTLP_ENDPOINTS JSON config into a list of endpoint configs.

    Format: [{"endpoint": "https://...", "headers": "key=val,key2=val2"}, ...]

    Falls back to the single OTEL_EXPORTER_OTLP_ENDPOINT/HEADERS if the JSON
    is empty or not set.
    """
    if endpoints_json:
        try:
            endpoints = json.loads(endpoints_json)
            if isinstance(endpoints, list) and endpoints:
                return [
                    {
                        "endpoint": ep.get("endpoint", ""),
                        "headers": ep.get("headers", ""),
                    }
                    for ep in endpoints
                    if ep.get("endpoint")
                ]
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Failed to parse OTLP_ENDPOINTS JSON, "
                "falling back to the single endpoint"
            )

    if fallback_endpoint:
        return [{"endpoint": fallback_endpoint, "headers": fallback_headers}]
    return []


def parse_filter_attributes(filter_str: str) -> dict[str, list[str]]:
    """
    Parse FILTER_SPAN_ATTRIBUTES.

    Format: key1=value1|value2,key2=value3
    Values ending with '*' are treated as prefix matches.
    Special value "*" (alone) disables filtering — all spans pass through.
    Empty value also disables filtering.
    """
    if not filter_str or filter_str.strip() == "*":
        return {}
    filters: dict[str, list[str]] = {}
    for pair in filter_str.split(","):
        pair = pair.strip()
        if "=" in pair:
            key, values_str = pair.split("=", 1)
            filters[key.strip()] = [v.strip() for v in values_str.split("|")]
    return filters


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def span_matches_filter(
    span_data: dict[str, Any], filters: dict[str, list[str]]
) -> bool:
    """
    Check if a span matches the configured filter criteria.

    A span matches if ALL filter keys are present in the span attributes
    and at least one of the allowed values matches per key.
    Values ending with '*' are prefix matches.
    """
    if not filters:
        return True

    attributes = _extract_flat_attributes(span_data.get("attributes", {}))

    for filter_key, allowed_values in filters.items():
        attr_value = attributes.get(filter_key)
        if attr_value is None:
            return False
        if not _value_matches(attr_value, allowed_values):
            return False

    return True


def _value_matches(attr_value: str, allowed_values: list[str]) -> bool:
    """Check if an attribute value matches any allowed value (prefix or exact)."""
    for allowed in allowed_values:
        if allowed.endswith("*"):
            if attr_value.startswith(allowed[:-1]):
                return True
        elif attr_value == allowed:
            return True
    return False


def _extract_flat_attributes(
    attrs: dict[str, Any] | list[dict[str, Any]],
) -> dict[str, str]:
    """Extract a flat {key: string_value} dict from either format for filtering."""
    result: dict[str, str] = {}
    if isinstance(attrs, dict):
        for key, value in attrs.items():
            result[key] = str(value)
    elif isinstance(attrs, list):
        for attr in attrs:
            key = attr.get("key", "")
            value = attr.get("value", {})
            if isinstance(value, dict):
                for vtype in (
                    "stringValue",
                    "intValue",
                    "boolValue",
                    "doubleValue",
                ):
                    if vtype in value:
                        result[key] = str(value[vtype])
                        break
            else:
                result[key] = str(value)
    return result


# ---------------------------------------------------------------------------
# OTLP JSON normalization (zero-dependency encoder)
# ---------------------------------------------------------------------------


def _normalize_any_value(value: Any) -> dict[str, Any]:
    """Convert a Python value to an OTLP AnyValue JSON structure."""
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, list):
        return {"arrayValue": {"values": [_normalize_any_value(v) for v in value]}}
    if isinstance(value, dict):
        # Already in OTLP format
        if any(
            k in value
            for k in (
                "stringValue",
                "intValue",
                "doubleValue",
                "boolValue",
                "arrayValue",
                "kvlistValue",
                "bytesValue",
            )
        ):
            return value
        # Nested dict -> kvlistValue
        return {
            "kvlistValue": {
                "values": [
                    {"key": k, "value": _normalize_any_value(v)}
                    for k, v in value.items()
                ]
            }
        }
    return {"stringValue": str(value)}


def _normalize_attributes(attrs: Any) -> list[dict[str, Any]]:
    """
    Convert attributes from a flat dict or an OTLP array to an OTLP KeyValue array.

    Flat dict: {"key": value} -> [{"key": "key", "value": {"stringValue": ...}}]
    OTLP array: already in the correct format, passed through with value
    normalization.
    """
    if not attrs:
        return []

    if isinstance(attrs, dict):
        return [
            {"key": k, "value": _normalize_any_value(v)}
            for k, v in attrs.items()
        ]

    if isinstance(attrs, list):
        normalized = []
        for item in attrs:
            if isinstance(item, dict) and "key" in item:
                entry: dict[str, Any] = {"key": item["key"]}
                if "value" in item:
                    val = item["value"]
                    entry["value"] = (
                        val
                        if isinstance(val, dict)
                        and any(
                            k in val
                            for k in (
                                "stringValue",
                                "intValue",
                                "doubleValue",
                                "boolValue",
                                "arrayValue",
                                "kvlistValue",
                            )
                        )
                        else _normalize_any_value(val)
                    )
                else:
                    entry["value"] = {"stringValue": ""}
                normalized.append(entry)
            else:
                normalized.append(
                    {"key": str(item), "value": {"stringValue": str(item)}}
                )
        return normalized

    return []


def _normalize_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize span events to the OTLP Event JSON structure."""
    normalized = []
    for event in events:
        otlp_event: dict[str, Any] = {}
        if event.get("timeUnixNano") is not None:
            otlp_event["timeUnixNano"] = str(int(event["timeUnixNano"]))
        if "name" in event:
            otlp_event["name"] = event["name"]
        if "attributes" in event:
            otlp_event["attributes"] = _normalize_attributes(event["attributes"])
        if "droppedAttributesCount" in event:
            otlp_event["droppedAttributesCount"] = event["droppedAttributesCount"]
        normalized.append(otlp_event)
    return normalized


def _normalize_links(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize span links to the OTLP Link JSON structure."""
    normalized = []
    for link in links:
        otlp_link: dict[str, Any] = {}
        if "traceId" in link:
            otlp_link["traceId"] = link["traceId"]
        if "spanId" in link:
            otlp_link["spanId"] = link["spanId"]
        if "traceState" in link:
            otlp_link["traceState"] = link["traceState"]
        if "attributes" in link:
            otlp_link["attributes"] = _normalize_attributes(link["attributes"])
        normalized.append(otlp_link)
    return normalized


def _hex_to_base64(hex_str: str) -> str:
    """Convert a hex-encoded ID to base64 (required by protobuf JSON encoding)."""
    return base64.b64encode(bytes.fromhex(hex_str)).decode()


def normalize_span_to_otlp_json(span_data: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize a log span dict into the OTLP JSON Span structure.

    The result follows the OTLP protobuf JSON encoding conventions
    (IDs base64-encoded, fixed64 timestamps as strings).
    """
    otlp_span: dict[str, Any] = {}

    # IDs: hex -> base64 (protobuf JSON convention)
    if "traceId" in span_data:
        otlp_span["traceId"] = _hex_to_base64(span_data["traceId"])
    if "spanId" in span_data:
        otlp_span["spanId"] = _hex_to_base64(span_data["spanId"])
    if "parentSpanId" in span_data:
        otlp_span["parentSpanId"] = _hex_to_base64(span_data["parentSpanId"])
    if "traceState" in span_data:
        otlp_span["traceState"] = span_data["traceState"]

    if "name" in span_data:
        otlp_span["name"] = span_data["name"]

    # Span kind: normalize string to int
    if "kind" in span_data:
        kind = span_data["kind"]
        if isinstance(kind, str):
            otlp_span["kind"] = _SPAN_KIND_MAP.get(kind, 0)
        else:
            otlp_span["kind"] = kind

    # Timestamps as strings (OTLP JSON uses fixed64 as string)
    if span_data.get("startTimeUnixNano") is not None:
        otlp_span["startTimeUnixNano"] = str(int(span_data["startTimeUnixNano"]))
    if span_data.get("endTimeUnixNano") is not None:
        otlp_span["endTimeUnixNano"] = str(int(span_data["endTimeUnixNano"]))

    # Attributes
    if "attributes" in span_data:
        otlp_span["attributes"] = _normalize_attributes(span_data["attributes"])

    # Events
    if "events" in span_data and span_data["events"]:
        otlp_span["events"] = _normalize_events(span_data["events"])

    # Links
    if "links" in span_data and span_data["links"]:
        otlp_span["links"] = _normalize_links(span_data["links"])

    # Status
    if "status" in span_data:
        status = span_data["status"]
        otlp_status: dict[str, Any] = {}
        if "code" in status:
            code = status["code"]
            if isinstance(code, str):
                otlp_status["code"] = _STATUS_CODE_MAP.get(code, 0)
            else:
                otlp_status["code"] = code
        if "message" in status:
            otlp_status["message"] = status["message"]
        otlp_span["status"] = otlp_status

    # Flags
    if "flags" in span_data:
        otlp_span["flags"] = span_data["flags"]

    return otlp_span


def build_export_request_json(spans_data: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Build an OTLP ExportTraceServiceRequest JSON dict from a list of spans.

    Groups spans by resource and scope, normalizes to the OTLP JSON structure.
    """
    # Group spans by resource -> scope
    resource_spans_map: dict[str, dict[str, Any]] = {}

    for span_data in spans_data:
        resource_data = span_data.get("resource", {})
        resource_key = json.dumps(
            resource_data.get("attributes", {}), sort_keys=True
        )

        if resource_key not in resource_spans_map:
            resource_spans_map[resource_key] = {
                "resource": resource_data,
                "scope_spans": {},
            }

        scope_data = span_data.get("instrumentationScope", {})
        scope_key = json.dumps(scope_data, sort_keys=True)

        if scope_key not in resource_spans_map[resource_key]["scope_spans"]:
            resource_spans_map[resource_key]["scope_spans"][scope_key] = {
                "scope": scope_data,
                "spans": [],
            }

        resource_spans_map[resource_key]["scope_spans"][scope_key][
            "spans"
        ].append(span_data)

    # Build the OTLP JSON structure
    resource_spans_list = []
    for entry in resource_spans_map.values():
        resource_attrs = _normalize_attributes(
            entry["resource"].get("attributes", {})
        )
        scope_spans_list = []
        for scope_entry in entry["scope_spans"].values():
            scope_data = scope_entry["scope"]
            spans_json = [
                normalize_span_to_otlp_json(s) for s in scope_entry["spans"]
            ]
            scope_span: dict[str, Any] = {"spans": spans_json}
            if scope_data:
                scope_span["scope"] = {}
                if "name" in scope_data:
                    scope_span["scope"]["name"] = scope_data["name"]
                if "version" in scope_data:
                    scope_span["scope"]["version"] = scope_data["version"]
            scope_spans_list.append(scope_span)

        resource_spans_list.append(
            {
                "resource": {"attributes": resource_attrs},
                "scopeSpans": scope_spans_list,
            }
        )

    return {"resourceSpans": resource_spans_list}


# ---------------------------------------------------------------------------
# OTLP export
# ---------------------------------------------------------------------------


def _send_to_endpoint_json(
    endpoint_config: dict[str, str],
    payload_dict: dict[str, Any],
    resource_span_count: int,
) -> bool:
    """Send the OTLP JSON payload to a single endpoint. Returns True on success."""
    endpoint = endpoint_config["endpoint"].rstrip("/")
    if not endpoint.endswith("/v1/traces"):
        endpoint = f"{endpoint}/v1/traces"

    headers = {"Content-Type": "application/json"}
    headers.update(parse_otlp_headers(endpoint_config.get("headers", "")))

    body = json.dumps(payload_dict).encode("utf-8")

    try:
        req = urllib_request.Request(endpoint, data=body, headers=headers)
        with urllib_request.urlopen(req, timeout=30) as resp:
            status = resp.getcode()
            if status in (200, 202):
                logger.info(
                    "Exported %d resource spans (%d bytes) to %s",
                    resource_span_count,
                    len(body),
                    endpoint,
                )
                return True
            logger.error(
                "OTLP export failed for %s: status=%d",
                endpoint,
                status,
            )
            return False
    except (URLError, HTTPError, TimeoutError) as e:
        logger.error("OTLP export request failed for %s: %s", endpoint, str(e))
        return False


def _send_to_endpoint_protobuf(
    endpoint_config: dict[str, str],
    request_obj: Any,
    resource_span_count: int,
) -> bool:
    """Send the OTLP protobuf payload (requires a dependency package)."""
    endpoint = endpoint_config["endpoint"].rstrip("/")
    if not endpoint.endswith("/v1/traces"):
        endpoint = f"{endpoint}/v1/traces"

    headers = {"Content-Type": "application/x-protobuf"}
    headers.update(parse_otlp_headers(endpoint_config.get("headers", "")))

    try:
        payload = request_obj.SerializeToString()
        req = urllib_request.Request(endpoint, data=payload, headers=headers)
        with urllib_request.urlopen(req, timeout=30) as resp:
            status = resp.getcode()
            if status in (200, 202):
                logger.info(
                    "Exported %d resource spans (%d bytes) to %s",
                    resource_span_count,
                    len(payload),
                    endpoint,
                )
                return True
            logger.error(
                "OTLP export failed for %s: status=%d",
                endpoint,
                status,
            )
            return False
    except (URLError, HTTPError, TimeoutError) as e:
        logger.error("OTLP export request failed for %s: %s", endpoint, str(e))
        return False


def export_to_otlp(
    payload: Any,
    raw_spans: list[dict[str, Any]],
    resource_span_count: int,
) -> bool:
    """
    Export traces to all configured OTLP endpoints.

    In dry-run mode, logs the incoming spans and the serialized payload
    instead of making the HTTP calls.

    Returns True if at least one endpoint succeeds (or in dry-run mode).
    """
    endpoints = parse_otlp_endpoints(
        OTLP_ENDPOINTS_JSON, OTLP_ENDPOINT, OTLP_HEADERS
    )

    if DRY_RUN:
        logger.info("[DRY RUN] Incoming spans (%d):", len(raw_spans))
        for i, span in enumerate(raw_spans):
            logger.info("[DRY RUN] Span %d: %s", i, json.dumps(span))
        if OTLP_ENCODING == "json":
            size = len(json.dumps(payload).encode("utf-8"))
        else:
            size = len(payload.SerializeToString())
        logger.info(
            "[DRY RUN] OTLP request (%d resource_spans, %d bytes)",
            resource_span_count,
            size,
        )
        endpoint_list = (
            [ep["endpoint"] for ep in endpoints] if endpoints else ["(not configured)"]
        )
        logger.info("[DRY RUN] Would send to: %s", ", ".join(endpoint_list))
        return True

    if not endpoints:
        logger.error(
            "No OTLP endpoints configured "
            "(set OTLP_ENDPOINTS or OTEL_EXPORTER_OTLP_ENDPOINT)"
        )
        return False

    any_success = False
    for ep in endpoints:
        if OTLP_ENCODING == "protobuf":
            ok = _send_to_endpoint_protobuf(ep, payload, resource_span_count)
        else:
            ok = _send_to_endpoint_json(ep, payload, resource_span_count)
        if ok:
            any_success = True

    return any_success


# ---------------------------------------------------------------------------
# Event envelope decoding
# ---------------------------------------------------------------------------


def decode_gzip_b64(data: str) -> dict[str, Any]:
    """Decode base64 + gzip compressed log data."""
    compressed = base64.b64decode(data)
    decompressed = gzip.decompress(compressed)
    return json.loads(decompressed)


def _extract_log_events(event: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Normalize the incoming event into a flat list of {message: ...} log events.

    Supports:
      1. LTS trigger envelope: {"lts": {"data": <base64-gzip>}}
      2. Delivery-stream envelope: {"records": [{"recordId":..., "data": <base64-gzip>}]}
      3. Direct POST of an OTLP batch / single span (no envelope).
    """
    # 1. LTS trigger envelope
    lts = event.get("lts")
    if isinstance(lts, dict) and lts.get("data"):
        try:
            decoded = decode_gzip_b64(lts["data"])
        except Exception as e:  # noqa: BLE001 - defensive decode
            logger.warning("Failed to decode LTS trigger data: %s", e)
            return []
        log_events = []
        # LTS trigger envelope uses log_events (underscore); the delivery
        # envelope uses logEvents (camelCase). Accept both.
        for log_event in decoded.get("log_events", decoded.get("logEvents", [])):
            if isinstance(log_event, dict) and log_event.get("message"):
                log_events.append(log_event)
        return log_events

    # 2. Delivery-stream envelope
    records = event.get("records")
    if isinstance(records, list):
        log_events = []
        for record in records:
            try:
                decoded = decode_gzip_b64(record.get("data", ""))
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to decode delivery record: %s", e)
                continue
            for log_event in decoded.get("logEvents", []):
                if isinstance(log_event, dict) and log_event.get("message"):
                    log_events.append(log_event)
        return log_events

    # 3. Direct POST
    if event.get("resourceSpans") or "traceId" in event or "spans" in event:
        return [{"message": json.dumps(event)}]

    return []


def _extract_spans(span_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract individual spans from either batch or single-span format."""
    spans: list[dict[str, Any]] = []

    if "resourceSpans" in span_data:
        # OTLP batch format
        for rs in span_data["resourceSpans"]:
            resource = rs.get("resource", {})
            for ss in rs.get("scopeSpans", []):
                scope = ss.get("scope", {})
                for span in ss.get("spans", []):
                    span["resource"] = resource
                    span["instrumentationScope"] = scope
                    spans.append(span)
    elif "traceId" in span_data:
        # Single span (flat log format)
        if "scope" in span_data and "instrumentationScope" not in span_data:
            span_data["instrumentationScope"] = span_data["scope"]
        spans.append(span_data)

    return spans


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    FunctionGraph handler for the trace exporter pipeline.

    1. Normalizes the incoming event into log events
    2. Extracts spans, filters them by configured attribute values
    3. Converts matching spans to OTLP (JSON by default)
    4. Exports to the configured OTLP endpoints (or logs in dry-run mode)
    5. Returns a summary with Ok / Dropped / ProcessingFailed disposition
    """
    filters = parse_filter_attributes(FILTER_ATTRIBUTES)

    log_events = _extract_log_events(event)
    spans_to_export: list[dict[str, Any]] = []
    dropped_records = 0
    failed_records = 0
    processed_records = 0

    for log_event in log_events:
        processed_records += 1
        try:
            message = log_event.get("message", "")
            span_data = json.loads(message)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Skipping non-JSON log event")
            dropped_records += 1
            continue

        spans = _extract_spans(span_data)
        record_has_matching_spans = False
        for span in spans:
            if span_matches_filter(span, filters):
                spans_to_export.append(span)
                record_has_matching_spans = True

        if record_has_matching_spans:
            logger.info("Record %s: %s", processed_records, RESULT_OK)
        else:
            dropped_records += 1

    summary = {
        "processed": processed_records,
        "matched": len(spans_to_export),
        "dropped": dropped_records,
        "failed": failed_records,
    }

    # Export collected spans
    if spans_to_export:
        logger.info(
            "%sExporting %d spans",
            "[DRY RUN] " if DRY_RUN else "",
            len(spans_to_export),
        )
        if OTLP_ENCODING == "protobuf":
            try:
                from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (  # noqa: E501
                    ExportTraceServiceRequest,
                )
                from google.protobuf.json_format import ParseDict  # noqa: E501

                request = ParseDict(
                    build_export_request_json(spans_to_export),
                    ExportTraceServiceRequest(),
                )
                ok = export_to_otlp(request, spans_to_export, len(request.resource_spans))
            except ImportError:
                logger.error(
                    "protobuf encoding requested but dependency package "
                    "is not attached — set OTLP_ENCODING=json or build the "
                    "dependency package (see src/tools/build-dependency.sh)"
                )
                ok = False
        else:
            payload = build_export_request_json(spans_to_export)
            resource_span_count = len(payload.get("resourceSpans", []))
            ok = export_to_otlp(payload, spans_to_export, resource_span_count)

        if not ok:
            logger.error("Failed to export spans")
            summary["failed"] = failed_records + 1
    else:
        logger.info("No spans matched the filter criteria")

    logger.info("Summary: %s", json.dumps(summary))
    return summary


if __name__ == "__main__":
    # Local smoke test: run against a sample span batch in dry-run mode.
    import sys

    sample = {
        "lts": {
            "data": base64.b64encode(
                gzip.compress(
                    json.dumps(
                        {
                            "log_group_id": "demo",
                            "log_stream_id": "demo",
                            "log_events": [
                                {
                                    "id": "1",
                                    "message": json.dumps(
                                        {
                                            "traceId": "a" * 32,
                                            "spanId": "b" * 16,
                                            "name": "demo.span",
                                            "kind": "INTERNAL",
                                            "startTimeUnixNano": "1000",
                                            "endTimeUnixNano": "2000",
                                            "attributes": {
                                                "service.name": "demo",
                                                "demo.filter.key": "hit",
                                            },
                                        }
                                    ),
                                }
                            ],
                        }
                    ).encode("utf-8")
                )
            ).decode()
        }
    }
    os.environ.setdefault("DRY_RUN", "true")
    os.environ.setdefault("OTLP_ENCODING", "json")
    result = handler(sample, None)
    print(json.dumps(result, indent=2))
    sys.exit(0)
