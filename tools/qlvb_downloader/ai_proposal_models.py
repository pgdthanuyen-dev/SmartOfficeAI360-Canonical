from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .domain_models import DomainModel, StrEnum, compute_stable_hash, new_id, utc_now_iso


AI_PROPOSAL_SCHEMA_VERSION = "1.0.0"
MAX_AI_PROPOSAL_JSON_BYTES = 512 * 1024
MAX_AI_PROPOSALS = 20
MAX_AI_PROPOSAL_TITLE_CHARS = 300
MAX_AI_PROPOSAL_DESCRIPTION_CHARS = 5000
MAX_AI_PROPOSAL_CITATIONS = 10
MAX_AI_PROPOSAL_EXCERPT_CHARS = 2000
MAX_AI_PROPOSAL_REASONING_CHARS = 1000
MAX_AI_PROPOSAL_WARNING_CHARS = 500
MAX_WARNING_LENGTH = MAX_AI_PROPOSAL_WARNING_CHARS
MAX_ERROR_LENGTH = 1000
MAX_REASONING_SUMMARY_LENGTH = MAX_AI_PROPOSAL_REASONING_CHARS
MAX_WARNINGS_PER_ENVELOPE = 20
MAX_WARNINGS_PER_PROPOSAL = 10
IDEMPOTENCY_CONFLICT_ERROR_CODE = "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD"


class ProposalDedupeStatus(StrEnum):
    NEW = "NEW"
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"


class ProposalPersistStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    DUPLICATE = "DUPLICATE"


@dataclass
class AiCitation(DomainModel):
    attachment_id: str
    page_start: int
    page_end: int
    excerpt: str
    char_start: int | None = None
    char_end: int | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class AiProposal(DomainModel):
    external_proposal_id: str
    title: str
    description: str | None
    proposed_unit_id: str | None
    proposed_assignee_id: str | None
    proposed_supervisor_id: str | None
    proposed_due_date: str | None
    expected_output: str | None
    expected_output_type: str | None
    priority: str | None
    complexity: str | None
    confidence: float | None
    citations: list[AiCitation]
    reasoning_summary: str | None
    warnings: list[str] = field(default_factory=list)


@dataclass
class AiProposalEnvelope(DomainModel):
    schema_version: str
    document_id: str
    attachment_ids: list[str]
    model_name: str
    model_version: str
    prompt_version: str
    generated_at: str
    proposals: list[AiProposal]
    warnings: list[str] = field(default_factory=list)


@dataclass
class AiProposalIngestResult(DomainModel):
    batch_id: str
    received_count: int
    accepted_count: int
    rejected_count: int
    duplicate_count: int
    warning_count: int
    action_item_ids: list[str]
    errors: list[str]
    error_code: str | None = None
    idempotency_key: str | None = None
    existing_batch_id: str | None = None


def normalize_for_fingerprint(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value)).casefold()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compact_warning(value: str) -> str:
    return str(value or "").strip()[:MAX_WARNING_LENGTH]


def compact_error(value: str) -> str:
    return str(value or "").strip()[:MAX_ERROR_LENGTH]


def proposal_fingerprint(document_id: str, proposal: AiProposal) -> str:
    citation_ranges = [
        {
            "attachment_id": citation.attachment_id,
            "page_start": citation.page_start,
            "page_end": citation.page_end,
            "char_start": citation.char_start,
            "char_end": citation.char_end,
        }
        for citation in proposal.citations
    ]
    return compute_stable_hash(
        {
            "document_id": document_id,
            "title": normalize_for_fingerprint(proposal.title),
            "description": normalize_for_fingerprint(proposal.description),
            "proposed_unit_id": normalize_for_fingerprint(proposal.proposed_unit_id),
            "proposed_due_date": normalize_for_fingerprint(proposal.proposed_due_date),
            "expected_output": normalize_for_fingerprint(proposal.expected_output),
            "citations": citation_ranges,
        }
    )


def new_batch_id() -> str:
    return new_id()


def now_for_ai_proposal() -> str:
    return utc_now_iso()
