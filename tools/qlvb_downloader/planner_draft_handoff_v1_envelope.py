"""Canonical, immutable local envelope for a verified handoff projection."""
from __future__ import annotations

import hashlib
import json
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import uuid4

from .planner_draft_handoff_v1_models import CONTRACT_VERSION, SOURCE_SYSTEM, PlannerDraftHandoffEnvelopeV1, PlannerDraftHandoffProjectionV1


def _canonical_value(value):
    if is_dataclass(value):
        return {item.name: _canonical_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, (dict, MappingProxyType)):
        return {str(key): _canonical_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    return value


def canonical_business_payload(projection: PlannerDraftHandoffProjectionV1) -> str:
    if not isinstance(projection, PlannerDraftHandoffProjectionV1):
        raise TypeError("projection must be PlannerDraftHandoffProjectionV1")
    return json.dumps(_canonical_value(projection), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def build_planner_draft_handoff_envelope_v1(projection: PlannerDraftHandoffProjectionV1) -> PlannerDraftHandoffEnvelopeV1:
    payload = canonical_business_payload(projection)
    return PlannerDraftHandoffEnvelopeV1(
        envelope_id=str(uuid4()), contract_version=CONTRACT_VERSION, source_system=SOURCE_SYSTEM,
        tenant_id=projection.tenant_id, tenant_key=projection.tenant_key,
        source_document_id=projection.source_document_id, source_draft_id=projection.source_draft_id,
        source_draft_version=projection.source_draft_version, canonical_payload_json=payload,
        payload_sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        created_at=datetime.now(UTC).replace(microsecond=0).isoformat(), projection=projection,
    )
