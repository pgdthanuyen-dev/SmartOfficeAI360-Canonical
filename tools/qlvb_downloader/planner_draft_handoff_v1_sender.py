"""One-shot, lossless sender for the frozen Planner handoff v1 contract."""
from __future__ import annotations

import hashlib
import json
import math
from http.client import RemoteDisconnected, IncompleteRead
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlparse

import requests

from .planner_draft_handoff_v1_models import PlannerDraftHandoffEnvelopeV1


class PlannerSenderError(Exception):
    def __init__(self, code: str, safe_message: str, retryable: bool = False, http_status: int | None = None, correlation_id: str | None = None):
        super().__init__(safe_message)
        self.code, self.safe_message, self.retryable, self.http_status, self.correlation_id = code, safe_message, retryable, http_status, correlation_id


@dataclass(frozen=True)
class PlannerSenderConfig:
    endpoint_url: str = field(repr=False)
    issuer: str = field(repr=False)
    shared_secret: str = field(repr=False)
    connect_timeout_seconds: float = 3
    read_timeout_seconds: float = 10
    response_size_limit_bytes: int = 65536
    allow_insecure_loopback_for_tests: bool = False

    def __post_init__(self):
        parsed = urlparse(self.endpoint_url)
        if parsed.username or parsed.password or parsed.fragment or parsed.query or parsed.path != "/api/integrations/smartoffice/drafts": raise ValueError("Invalid Planner endpoint.")
        loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback and self.allow_insecure_loopback_for_tests): raise ValueError("Planner endpoint must use HTTPS.")
        if not self.issuer.strip() or not self.shared_secret.strip() or not all(math.isfinite(x) and x > 0 for x in (self.connect_timeout_seconds, self.read_timeout_seconds)) or self.response_size_limit_bytes <= 0: raise ValueError("Invalid sender configuration.")


class PlannerSendOutcome(str, Enum): CREATED="CREATED"; DUPLICATE="DUPLICATE"; UPDATED="UPDATED"

@dataclass(frozen=True)
class PlannerSendResult:
    outcome: PlannerSendOutcome; planner_draft_id: str; planner_status: str; source_document_id: str; accepted_source_draft_version: int; accepted_payload_fingerprint: str; contract_version: str; http_status: int; safe_correlation_id: str | None


def derive_idempotency_key(tenant_id: str, source_document_id: str) -> str:
    return hashlib.sha256(f"{tenant_id.strip().lower()}:SMARTOFFICE_AI360:{source_document_id.strip().lower()}".encode("utf-8")).hexdigest()

def _closed_connection(exc: BaseException) -> bool:
    pending, seen = [exc], set()
    while pending and len(seen) < 16:
        current = pending.pop()
        if id(current) in seen: continue
        seen.add(id(current))
        if isinstance(current, (RemoteDisconnected, IncompleteRead, ConnectionResetError, ConnectionAbortedError, BrokenPipeError, requests.exceptions.ChunkedEncodingError)): return True
        pending.extend(value for value in (getattr(current, "__cause__", None), getattr(current, "__context__", None), *[item for item in getattr(current, "args", ()) if isinstance(item, BaseException)]) if isinstance(value, BaseException))
    return False


def build_v1_request(envelope: PlannerDraftHandoffEnvelopeV1) -> tuple[dict, str]:
    payload_error = None
    try:
        payload = json.loads(envelope.canonical_payload_json)
    except (TypeError, json.JSONDecodeError):
        payload, payload_error = None, PlannerSenderError("INVALID_CANONICAL_PAYLOAD", "Canonical payload is invalid.")
    if payload_error is not None: raise payload_error
    if not isinstance(payload, dict) or any(k in payload for k in ("endpoint", "secret", "headers", "token")): raise PlannerSenderError("INVALID_CANONICAL_PAYLOAD", "Canonical payload is invalid.")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if hashlib.sha256(encoded).hexdigest() != envelope.payload_sha256: raise PlannerSenderError("PAYLOAD_FINGERPRINT_MISMATCH", "Canonical payload fingerprint is invalid.")
    return {"contractVersion": "v1", "payloadFingerprint": envelope.payload_sha256, "canonicalPayload": payload}, derive_idempotency_key(envelope.tenant_id, envelope.source_document_id)


def _transport_error(exc: requests.RequestException) -> PlannerSenderError:
    if isinstance(exc, requests.ConnectTimeout): return PlannerSenderError("PLANNER_CONNECT_TIMEOUT", "Planner connection timed out.", True)
    if isinstance(exc, requests.ReadTimeout): return PlannerSenderError("PLANNER_READ_TIMEOUT", "Planner response timed out.", True)
    if isinstance(exc, requests.Timeout): return PlannerSenderError("PLANNER_READ_TIMEOUT", "Planner request timed out.", True)
    if isinstance(exc, requests.exceptions.SSLError): return PlannerSenderError("PLANNER_TLS_FAILURE", "Planner TLS validation failed.", False)
    if _closed_connection(exc): return PlannerSenderError("PLANNER_CONNECTION_CLOSED", "Planner connection closed.", True)
    if isinstance(exc, requests.ConnectionError): return PlannerSenderError("PLANNER_CONNECTION_FAILED", "Planner connection failed.", True)
    return PlannerSenderError("PLANNER_TRANSPORT_FAILURE", "Planner transport failed.", True)


def _parse_response_json(raw: bytes, error_code: str, message: str, http_status: int | None) -> tuple[object | None, PlannerSenderError | None]:
    try:
        return json.loads(raw), None
    except json.JSONDecodeError:
        return None, PlannerSenderError(error_code, message, http_status=http_status)


def send_planner_handoff_v1(envelope: PlannerDraftHandoffEnvelopeV1, config: PlannerSenderConfig, session: requests.Session | None = None) -> PlannerSendResult:
    body, idem = build_v1_request(envelope); client = session or requests.Session(); response = None; transport_error = None
    try:
        response = client.post(config.endpoint_url, data=json.dumps(body, ensure_ascii=False, separators=(",", ":")), headers={"Content-Type":"application/json", "X-SmartOffice-Issuer":config.issuer, "X-SmartOffice-Secret":config.shared_secret, "Idempotency-Key":idem}, timeout=(config.connect_timeout_seconds, config.read_timeout_seconds), allow_redirects=False, stream=True, verify=True)
    except requests.RequestException as exc:
        transport_error = _transport_error(exc)
    if transport_error is not None: raise transport_error
    try:
        try:
            raw = b"".join(response.iter_content(8192))
        except requests.RequestException as exc:
            transport_error = _transport_error(exc)
        if transport_error is not None: pass
        elif len(raw) > config.response_size_limit_bytes: raise PlannerSenderError("PLANNER_RESPONSE_TOO_LARGE", "Planner response exceeded the limit.")
        elif 300 <= response.status_code < 400: raise PlannerSenderError("PLANNER_REDIRECT_REJECTED", "Planner redirect was rejected.", http_status=response.status_code)
        else:
            content_type = response.headers.get("Content-Type", "").lower()
            if response.status_code not in (200, 201):
                data, parse_error = _parse_response_json(raw, "PLANNER_RESPONSE_JSON_INVALID", "Planner response JSON is invalid.", response.status_code) if "json" in content_type else (None, None)
                if parse_error is not None: raise parse_error
                known = {"PAYLOAD_FINGERPRINT_MISMATCH", "IDEMPOTENCY_KEY_REQUIRED", "IDEMPOTENCY_KEY_INVALID", "IDEMPOTENCY_KEY_MISMATCH", "SOURCE_VERSION_PAYLOAD_CONFLICT", "STALE_SOURCE_VERSION", "SOURCE_DOCUMENT_ALREADY_FINALIZED", "INVALID_AUTHENTICATION", "INVALID_ISSUER", "TENANT_MISMATCH", "UNSUPPORTED_CONTRACT_VERSION"}
                fallback = {400:"PLANNER_BAD_REQUEST",401:"PLANNER_AUTHENTICATION_FAILED",403:"PLANNER_TENANT_FORBIDDEN",404:"PLANNER_NOT_FOUND",413:"PLANNER_PAYLOAD_TOO_LARGE",415:"PLANNER_UNSUPPORTED_MEDIA_TYPE",422:"PLANNER_VALIDATION_FAILED",429:"PLANNER_RATE_LIMITED"}.get(response.status_code, "PLANNER_TEMPORARY_FAILURE" if response.status_code >= 500 else "PLANNER_PERMANENT_FAILURE")
                code = data.get("errorCode") if isinstance(data, dict) and data.get("errorCode") in known else fallback
                correlation = data.get("correlationId") if isinstance(data, dict) else None
                safe_correlation = correlation.strip() if isinstance(correlation, str) and 0 < len(correlation.strip()) <= 128 and correlation.strip().isprintable() else None
                raise PlannerSenderError(code, "Planner rejected the handoff.", response.status_code == 429 or response.status_code >= 500, response.status_code, safe_correlation)
            if "json" not in content_type: raise PlannerSenderError("PLANNER_RESPONSE_CONTENT_TYPE_INVALID", "Planner response content type is invalid.", http_status=response.status_code)
            data, parse_error = _parse_response_json(raw, "PLANNER_RESPONSE_JSON_INVALID", "Planner response JSON is invalid.", response.status_code)
            if parse_error is not None: raise parse_error
    finally:
        response.close()
    if transport_error is not None: raise transport_error
    if not isinstance(data, dict) or data.get("success") is not True: raise PlannerSenderError("PLANNER_RESPONSE_SHAPE_INVALID", "Planner response is invalid.", http_status=response.status_code)
    duplicate, updated = data.get("duplicate"), data.get("updated")
    valid_identity = data.get("acceptedSourceDocumentId") == envelope.source_document_id and data.get("acceptedSourceDraftVersion") == envelope.source_draft_version and data.get("acceptedPayloadFingerprint") == envelope.payload_sha256 and data.get("contractVersion") == "v1"
    if not valid_identity: raise PlannerSenderError("PLANNER_RESPONSE_IDENTITY_MISMATCH", "Planner response identity is invalid.", http_status=response.status_code)
    if response.status_code == 201 and duplicate is False and updated is False: outcome = PlannerSendOutcome.CREATED
    elif response.status_code == 200 and duplicate is True and updated is False: outcome = PlannerSendOutcome.DUPLICATE
    elif response.status_code == 200 and updated is True and duplicate is False: outcome = PlannerSendOutcome.UPDATED
    else: raise PlannerSenderError("PLANNER_RESPONSE_INVALID", "Planner response is invalid.", http_status=response.status_code)
    if not isinstance(data.get("draftId"), str) or not data["draftId"].strip() or not isinstance(data.get("status"), str) or not data["status"].strip(): raise PlannerSenderError("PLANNER_RESPONSE_INVALID", "Planner response is invalid.", http_status=response.status_code)
    correlation = data.get("correlationId")
    return PlannerSendResult(outcome, data["draftId"], data["status"], envelope.source_document_id, envelope.source_draft_version, envelope.payload_sha256, "v1", response.status_code, correlation.strip() if isinstance(correlation, str) and 0 < len(correlation.strip()) <= 128 and correlation.strip().isprintable() else None)
