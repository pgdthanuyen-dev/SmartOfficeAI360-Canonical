from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Protocol

from .ai_proposal_models import (
    AI_PROPOSAL_SCHEMA_VERSION,
    AiCitation,
    AiProposal,
    AiProposalEnvelope,
    AiProposalIngestResult,
    ProposalDedupeStatus,
    ProposalPersistStatus,
    normalize_for_fingerprint,
    proposal_fingerprint,
)
from .ai_proposal_repository import AiProposalRepository, source_text_sha256_for_pages
from .ai_proposal_validation import AiProposalValidationError, parse_ai_proposal_json
from .domain_models import (
    ActionItem,
    ActionItemStatus,
    Complexity,
    ExpectedOutputType,
    Priority,
    SourceCitation,
    compute_stable_hash,
)
from .extraction_models import normalize_extracted_text


class AiProposalProvider(Protocol):
    def generate_proposals(self, *, document_id: str, attachment_ids: list[str]) -> dict[str, Any] | str:
        ...


class FakeAiProposalProvider:
    def __init__(self, response: dict[str, Any] | str):
        self.response = response

    def generate_proposals(self, *, document_id: str, attachment_ids: list[str]) -> dict[str, Any] | str:
        return self.response


class AiProposalService:
    def __init__(self, repository: AiProposalRepository):
        self.repository = repository

    def ingest_ai_proposal_response(
        self,
        document_id: str,
        response_json: str | bytes | dict[str, Any],
        idempotency_key: str,
        strict: bool = True,
    ) -> AiProposalIngestResult:
        existing_batch = self.repository.get_batch_by_idempotency_key(idempotency_key)
        if existing_batch is not None:
            return self._result_from_existing_batch(existing_batch)

        try:
            envelope = parse_ai_proposal_json(response_json, strict=strict)
            raw_response_sha256 = _stable_response_hash(response_json)
            if envelope.document_id != document_id:
                raise AiProposalValidationError("envelope document_id does not match requested document_id")
            if not self.repository.document_exists(document_id):
                raise AiProposalValidationError("document does not exist")
        except (AiProposalValidationError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            return AiProposalIngestResult(
                batch_id="",
                received_count=0,
                accepted_count=0,
                rejected_count=1,
                duplicate_count=0,
                warning_count=0,
                action_item_ids=[],
                errors=[str(exc)],
            )

        batch_id = self.repository.create_batch(
            document_id=document_id,
            idempotency_key=idempotency_key,
            schema_version=envelope.schema_version,
            model_name=envelope.model_name,
            model_version=envelope.model_version,
            prompt_version=envelope.prompt_version,
            generated_at=envelope.generated_at,
            raw_response_sha256=raw_response_sha256,
            received_count=len(envelope.proposals),
        )

        accepted_count = 0
        rejected_count = 0
        duplicate_count = 0
        warning_count = len(envelope.warnings)
        action_item_ids: list[str] = []
        errors: list[str] = []
        seen_fingerprints: set[str] = set()
        seen_titles: set[str] = set()
        existing_items = self.repository.list_existing_proposal_items(document_id)
        existing_fingerprints = {item["fingerprint"] for item in existing_items}
        existing_titles = {item["normalized_title"] for item in existing_items if item["normalized_title"]}

        for proposal in envelope.proposals:
            fingerprint = proposal_fingerprint(document_id, proposal)
            title_norm = normalize_for_fingerprint(proposal.title)
            proposal_warnings = list(proposal.warnings)
            if fingerprint in existing_fingerprints or fingerprint in seen_fingerprints:
                duplicate_count += 1
                item_id = self.repository.record_item(
                    batch_id=batch_id,
                    document_id=document_id,
                    external_proposal_id=proposal.external_proposal_id,
                    action_item_id=None,
                    fingerprint=fingerprint,
                    dedupe_status=ProposalDedupeStatus.EXACT_DUPLICATE,
                    persist_status=ProposalPersistStatus.DUPLICATE,
                    title=proposal.title,
                    normalized_title=title_norm,
                    confidence=proposal.confidence,
                    warnings=proposal_warnings,
                    error_code="EXACT_DUPLICATE",
                    error_message="exact duplicate proposal",
                )
                self._record_item_warnings(batch_id, item_id, proposal_warnings)
                continue

            dedupe_status = ProposalDedupeStatus.NEW
            if title_norm in existing_titles or title_norm in seen_titles:
                dedupe_status = ProposalDedupeStatus.POSSIBLE_DUPLICATE
                proposal_warnings.append("POSSIBLE_DUPLICATE")

            try:
                citations = self._build_source_citations(document_id, proposal)
                if not citations:
                    proposal_warnings.append("NO_VALID_CITATION")
                action_item = self._build_action_item(document_id, proposal, envelope)
                for citation in citations:
                    citation.action_item_id = action_item.id
                self.repository.save_action_item_with_citations(action_item, citations)
                accepted_count += 1
                warning_count += len(proposal_warnings)
                action_item_ids.append(action_item.id)
                item_id = self.repository.record_item(
                    batch_id=batch_id,
                    document_id=document_id,
                    external_proposal_id=proposal.external_proposal_id,
                    action_item_id=action_item.id,
                    fingerprint=fingerprint,
                    dedupe_status=dedupe_status,
                    persist_status=ProposalPersistStatus.ACCEPTED,
                    title=proposal.title,
                    normalized_title=title_norm,
                    confidence=proposal.confidence,
                    warnings=proposal_warnings,
                    error_code=None,
                    error_message=None,
                )
                self._record_item_warnings(batch_id, item_id, proposal_warnings)
                seen_fingerprints.add(fingerprint)
                seen_titles.add(title_norm)
                existing_fingerprints.add(fingerprint)
            except AiProposalValidationError as exc:
                rejected_count += 1
                warning_count += len(proposal_warnings)
                errors.append(f"{proposal.external_proposal_id}: {exc}")
                item_id = self.repository.record_item(
                    batch_id=batch_id,
                    document_id=document_id,
                    external_proposal_id=proposal.external_proposal_id,
                    action_item_id=None,
                    fingerprint=fingerprint,
                    dedupe_status=dedupe_status,
                    persist_status=ProposalPersistStatus.REJECTED,
                    title=proposal.title,
                    normalized_title=title_norm,
                    confidence=proposal.confidence,
                    warnings=proposal_warnings,
                    error_code="VALIDATION_ERROR",
                    error_message=str(exc),
                )
                self._record_item_warnings(batch_id, item_id, proposal_warnings)
            except Exception as exc:
                rejected_count += 1
                warning_count += len(proposal_warnings)
                errors.append(f"{proposal.external_proposal_id}: persistence failed: {exc}")
                item_id = self.repository.record_item(
                    batch_id=batch_id,
                    document_id=document_id,
                    external_proposal_id=proposal.external_proposal_id,
                    action_item_id=None,
                    fingerprint=fingerprint,
                    dedupe_status=dedupe_status,
                    persist_status=ProposalPersistStatus.REJECTED,
                    title=proposal.title,
                    normalized_title=title_norm,
                    confidence=proposal.confidence,
                    warnings=proposal_warnings,
                    error_code="PERSISTENCE_ERROR",
                    error_message=str(exc),
                )
                self._record_item_warnings(batch_id, item_id, proposal_warnings)

        for warning in envelope.warnings:
            self.repository.record_warning(
                batch_id=batch_id,
                proposal_item_id=None,
                warning_code="ENVELOPE_WARNING",
                message=warning,
            )

        status = "FAILED" if accepted_count == 0 and rejected_count > 0 else "COMPLETED"
        self.repository.complete_batch(
            batch_id=batch_id,
            status=status,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            duplicate_count=duplicate_count,
            warning_count=warning_count,
        )
        return AiProposalIngestResult(
            batch_id=batch_id,
            received_count=len(envelope.proposals),
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            duplicate_count=duplicate_count,
            warning_count=warning_count,
            action_item_ids=action_item_ids,
            errors=errors,
        )

    def _result_from_existing_batch(self, batch: dict[str, Any]) -> AiProposalIngestResult:
        action_item_ids = self.repository.get_batch_action_ids(batch["id"])
        return AiProposalIngestResult(
            batch_id=batch["id"],
            received_count=batch["received_count"],
            accepted_count=batch["accepted_count"],
            rejected_count=batch["rejected_count"],
            duplicate_count=batch["duplicate_count"],
            warning_count=batch["warning_count"],
            action_item_ids=action_item_ids,
            errors=[],
        )

    def _build_action_item(
        self,
        document_id: str,
        proposal: AiProposal,
        envelope: AiProposalEnvelope,
    ) -> ActionItem:
        return ActionItem(
            document_id=document_id,
            ordinal=self.repository.next_action_ordinal(document_id),
            title=proposal.title,
            description=proposal.description,
            proposed_unit_id=proposal.proposed_unit_id,
            proposed_assignee_id=proposal.proposed_assignee_id,
            proposed_supervisor_id=proposal.proposed_supervisor_id,
            proposed_due_date=proposal.proposed_due_date,
            expected_output=proposal.expected_output,
            expected_output_type=ExpectedOutputType(proposal.expected_output_type)
            if proposal.expected_output_type
            else None,
            priority=Priority(proposal.priority) if proposal.priority else Priority.NORMAL,
            complexity=Complexity(proposal.complexity) if proposal.complexity else Complexity.MEDIUM,
            ai_confidence=proposal.confidence,
            ai_model=f"{envelope.model_name}:{envelope.model_version}",
            ai_prompt_version=envelope.prompt_version,
            status=ActionItemStatus.PROPOSED,
        )

    def _build_source_citations(self, document_id: str, proposal: AiProposal) -> list[SourceCitation]:
        citations: list[SourceCitation] = []
        for ai_citation in proposal.citations:
            citations.append(self._verify_citation(document_id, ai_citation))
            proposal.warnings.extend(ai_citation.warnings)
        return citations

    def _verify_citation(self, document_id: str, citation: AiCitation) -> SourceCitation:
        attachment_doc_id = self.repository.attachment_document_id(citation.attachment_id)
        if attachment_doc_id is None:
            raise AiProposalValidationError("citation attachment does not exist")
        if attachment_doc_id != document_id:
            raise AiProposalValidationError("citation attachment belongs to another document")
        pages = self.repository.get_successful_page_texts(
            document_id=document_id,
            attachment_id=citation.attachment_id,
            page_start=citation.page_start,
            page_end=citation.page_end,
        )
        expected_pages = set(range(citation.page_start, citation.page_end + 1))
        if set(pages) != expected_pages:
            raise AiProposalValidationError("citation page does not exist in extracted text")
        combined_text = "\n\f\n".join(normalize_extracted_text(pages[number]) for number in sorted(pages))
        if not _excerpt_matches(citation.excerpt, combined_text, citation):
            raise AiProposalValidationError("citation excerpt does not match extracted page text")
        return SourceCitation(
            action_item_id="",
            document_id=document_id,
            attachment_id=citation.attachment_id,
            page_start=citation.page_start,
            page_end=citation.page_end,
            char_start=citation.char_start,
            char_end=citation.char_end,
            excerpt=citation.excerpt,
            source_text_sha256=source_text_sha256_for_pages(pages),
        )

    def _record_item_warnings(self, batch_id: str, item_id: str, warnings: list[str]) -> None:
        for warning in warnings:
            self.repository.record_warning(
                batch_id=batch_id,
                proposal_item_id=item_id,
                warning_code=warning,
                message=warning,
            )


def ingest_ai_proposal_response(
    repository: AiProposalRepository,
    document_id: str,
    response_json: str | bytes | dict[str, Any],
    idempotency_key: str,
    strict: bool = True,
) -> AiProposalIngestResult:
    return AiProposalService(repository).ingest_ai_proposal_response(
        document_id=document_id,
        response_json=response_json,
        idempotency_key=idempotency_key,
        strict=strict,
    )


def _stable_response_hash(response_json: str | bytes | dict[str, Any]) -> str:
    if isinstance(response_json, bytes):
        payload = json.loads(response_json.decode("utf-8"))
    elif isinstance(response_json, str):
        payload = json.loads(response_json)
    else:
        payload = response_json
    return compute_stable_hash(payload)


def _excerpt_matches(excerpt: str, source_text: str, citation: AiCitation) -> bool:
    normalized_excerpt = normalize_extracted_text(excerpt)
    normalized_source = normalize_extracted_text(source_text)
    if normalized_excerpt in normalized_source:
        return True
    collapsed_excerpt = _collapse_ws(normalized_excerpt)
    collapsed_source = _collapse_ws(normalized_source)
    if collapsed_excerpt and collapsed_excerpt in collapsed_source:
        return True
    loose_excerpt = _loose_text(collapsed_excerpt)
    loose_source = _loose_text(collapsed_source)
    if loose_excerpt and loose_excerpt in loose_source:
        citation.warnings.append("CITATION_FUZZY_MATCH")
        return True
    return False


def _collapse_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _loose_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    no_marks = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return _collapse_ws(unicodedata.normalize("NFC", no_marks))


def build_empty_ai_proposal_envelope(document_id: str) -> dict[str, Any]:
    return {
        "schema_version": AI_PROPOSAL_SCHEMA_VERSION,
        "document_id": document_id,
        "attachment_ids": [],
        "model_name": "fake",
        "model_version": "fake",
        "prompt_version": "test",
        "generated_at": "2026-07-19T00:00:00+00:00",
        "proposals": [],
        "warnings": [],
    }
