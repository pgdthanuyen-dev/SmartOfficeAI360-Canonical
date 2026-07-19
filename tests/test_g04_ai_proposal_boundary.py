from __future__ import annotations

import copy
import json
import sqlite3

import pytest

from tools.qlvb_downloader.ai_proposal_models import (
    AI_PROPOSAL_SCHEMA_VERSION,
    IDEMPOTENCY_CONFLICT_ERROR_CODE,
    MAX_ERROR_LENGTH,
    MAX_WARNING_LENGTH,
    MAX_WARNINGS_PER_ENVELOPE,
    MAX_WARNINGS_PER_PROPOSAL,
    now_for_ai_proposal,
)
from tools.qlvb_downloader.ai_proposal_repository import (
    AI_PROPOSAL_MIGRATION_VERSION,
    AiProposalRepository,
    init_ai_proposal_schema,
)
from tools.qlvb_downloader.ai_proposal_service import (
    AiProposalIdempotencyConflict,
    AiProposalService,
    FakeAiProposalProvider,
    build_empty_ai_proposal_envelope,
)
from tools.qlvb_downloader.ai_proposal_validation import AiProposalValidationError, parse_ai_proposal_json
from tools.qlvb_downloader.domain_models import (
    Attachment,
    AttachmentValidationStatus,
    Document,
    compute_stable_hash,
)
from tools.qlvb_downloader.domain_repository import DomainRepository
from tools.qlvb_downloader.extraction_models import (
    EXTRACTOR_NAME,
    EXTRACTOR_VERSION,
    ExtractionMethod,
    ExtractionResult,
    ExtractionStatus,
    ExtractedPage,
    combined_text_hash,
)
from tools.qlvb_downloader.extraction_repository import ExtractionRepository


PAGE_1 = "Noi dung xu ly van ban. Don vi A hoan thanh bao cao truoc 2026-08-01."
PAGE_2 = "Phoi hop don vi B cung cap phu luc va bang bieu."


class FailingCitationRepository(AiProposalRepository):
    def _insert_citation(self, citation):  # noqa: ANN001
        raise sqlite3.IntegrityError("simulated citation insert failure")


class LongFailingCitationRepository(AiProposalRepository):
    def _insert_citation(self, citation):  # noqa: ANN001
        raise sqlite3.IntegrityError("x" * (MAX_ERROR_LENGTH + 50))


class RacingBatchRepository(AiProposalRepository):
    winning_hash: str | None = None

    def create_batch(self, **kwargs):  # noqa: ANN003
        raw_hash = self.winning_hash or kwargs["raw_response_sha256"]
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO ai_proposal_batches (
                    id, document_id, idempotency_key, schema_version, model_name,
                    model_version, prompt_version, generated_at, raw_response_sha256,
                    status, received_count, accepted_count, rejected_count, duplicate_count,
                    warning_count, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, ?, ?)
                """,
                (
                    "race-winning-batch",
                    kwargs["document_id"],
                    kwargs["idempotency_key"],
                    kwargs["schema_version"],
                    kwargs["model_name"],
                    kwargs["model_version"],
                    kwargs["prompt_version"],
                    kwargs["generated_at"],
                    raw_hash,
                    "COMPLETED",
                    kwargs["received_count"],
                    now_for_ai_proposal(),
                    now_for_ai_proposal(),
                ),
            )
        raise sqlite3.IntegrityError("simulated idempotency race")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, title TEXT)")
    return conn


def _seed(repo_cls=AiProposalRepository):
    conn = _connect()
    domain_repo = DomainRepository(conn)
    extraction_repo = ExtractionRepository(conn)
    ai_repo = repo_cls(conn)
    domain_repo.save_document(
        Document(id="doc-1", tenant_id="tenant-a", source_system="QLVB", source_document_id="qlvb-1")
    )
    domain_repo.save_attachment(
        Attachment(
            id="att-1",
            document_id="doc-1",
            file_name="van-ban.pdf",
            sha256="a" * 64,
            validation_status=AttachmentValidationStatus.VALIDATED,
        )
    )
    result = ExtractionResult(
        document_id="doc-1",
        attachment_id="att-1",
        extractor_name=EXTRACTOR_NAME,
        extractor_version=EXTRACTOR_VERSION,
        extraction_method=ExtractionMethod.DIRECT_TEXT,
        status=ExtractionStatus.SUCCEEDED,
        source_file_sha256="a" * 64,
        page_count=2,
    )
    pages = [
        ExtractedPage(
            extraction_result_id=result.id,
            page_number=1,
            text=PAGE_1,
            extraction_method=ExtractionMethod.DIRECT_TEXT,
        ),
        ExtractedPage(
            extraction_result_id=result.id,
            page_number=2,
            text=PAGE_2,
            extraction_method=ExtractionMethod.DIRECT_TEXT,
        ),
    ]
    result.normalized_text_sha256 = combined_text_hash(pages)
    extraction_repo.save_success_result_with_pages(result, pages)
    return conn, domain_repo, extraction_repo, ai_repo


def _proposal(**overrides):
    payload = {
        "external_proposal_id": "p-1",
        "title": "Lap bao cao xu ly van ban",
        "description": "Don vi A lap bao cao xu ly van ban.",
        "proposed_unit_id": "unit-a",
        "proposed_assignee_id": None,
        "proposed_supervisor_id": None,
        "proposed_due_date": "2026-08-01",
        "expected_output": "Bao cao xu ly",
        "expected_output_type": "REPORT",
        "priority": "HIGH",
        "complexity": "MEDIUM",
        "confidence": 0.91,
        "citations": [
            {
                "attachment_id": "att-1",
                "page_start": 1,
                "page_end": 1,
                "excerpt": "Don vi A hoan thanh bao cao",
                "char_start": None,
                "char_end": None,
            }
        ],
        "reasoning_summary": "Rut ra tu cau chi dao trong van ban.",
        "warnings": [],
    }
    payload.update(overrides)
    return payload


def _envelope(*proposals, **overrides):
    payload = build_empty_ai_proposal_envelope("doc-1")
    payload.update(
        {
            "attachment_ids": ["att-1"],
            "model_name": "fake-model",
            "model_version": "v1",
            "prompt_version": "prompt-v1",
            "proposals": list(proposals) if proposals else [_proposal()],
        }
    )
    payload.update(overrides)
    return payload


def _ingest(ai_repo, payload, key="batch-1"):
    return AiProposalService(ai_repo).ingest_ai_proposal_response(
        "doc-1",
        payload,
        idempotency_key=key,
        strict=True,
    )


def test_json_envelope_valid():
    envelope = parse_ai_proposal_json(_envelope())
    assert envelope.schema_version == AI_PROPOSAL_SCHEMA_VERSION
    assert envelope.proposals[0].title == "Lap bao cao xu ly van ban"


def test_json_invalid_syntax():
    with pytest.raises(json.JSONDecodeError):
        parse_ai_proposal_json("{bad json")


def test_schema_version_unsupported():
    with pytest.raises(AiProposalValidationError):
        parse_ai_proposal_json(_envelope(schema_version="0.9.0"))


def test_required_field_missing():
    payload = _envelope()
    del payload["model_name"]
    with pytest.raises(AiProposalValidationError):
        parse_ai_proposal_json(payload)


def test_unknown_field_rejected_in_strict_mode():
    payload = _envelope(extra="nope")
    with pytest.raises(AiProposalValidationError):
        parse_ai_proposal_json(payload, strict=True)


def test_document_with_no_proposal_creates_empty_batch():
    conn, _, _, ai_repo = _seed()
    try:
        result = _ingest(ai_repo, _envelope(proposals=[]), key="empty")
        assert result.received_count == 0
        assert result.accepted_count == 0
    finally:
        conn.close()


def test_one_valid_proposal():
    conn, _, _, ai_repo = _seed()
    try:
        result = _ingest(ai_repo, _envelope(), key="one")
        assert result.accepted_count == 1
        assert len(result.action_item_ids) == 1
    finally:
        conn.close()


def test_multiple_valid_proposals():
    conn, _, _, ai_repo = _seed()
    try:
        second = _proposal(external_proposal_id="p-2", title="Cung cap phu luc", description="Don vi B cung cap phu luc.")
        second["citations"][0]["page_start"] = 2
        second["citations"][0]["page_end"] = 2
        second["citations"][0]["excerpt"] = "cung cap phu luc"
        result = _ingest(ai_repo, _envelope(_proposal(), second), key="multi")
        assert result.accepted_count == 2
    finally:
        conn.close()


def test_action_item_always_proposed():
    conn, _, _, ai_repo = _seed()
    try:
        result = _ingest(ai_repo, _envelope(), key="proposed")
        row = conn.execute("SELECT status FROM action_items WHERE id = ?", (result.action_item_ids[0],)).fetchone()
        assert row["status"] == "PROPOSED"
    finally:
        conn.close()


def test_ai_attempt_to_set_approved_is_rejected():
    proposal = _proposal(status="APPROVED")
    with pytest.raises(AiProposalValidationError):
        parse_ai_proposal_json(_envelope(proposal), strict=False)


def test_confidence_out_of_range():
    with pytest.raises(AiProposalValidationError):
        parse_ai_proposal_json(_envelope(_proposal(confidence=1.1)))


def test_due_date_invalid():
    with pytest.raises(AiProposalValidationError):
        parse_ai_proposal_json(_envelope(_proposal(proposed_due_date="01/08/2026")))


def test_citation_right_page_creates_source_citation():
    conn, _, _, ai_repo = _seed()
    try:
        result = _ingest(ai_repo, _envelope(), key="cite-page")
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM source_citations WHERE action_item_id = ?",
            (result.action_item_ids[0],),
        ).fetchone()["n"]
        assert count == 1
    finally:
        conn.close()


def test_citation_wrong_document_rejected():
    conn, domain_repo, _, ai_repo = _seed()
    try:
        domain_repo.save_document(
            Document(id="doc-2", tenant_id="tenant-a", source_system="QLVB", source_document_id="qlvb-2")
        )
        domain_repo.save_attachment(Attachment(id="att-2", document_id="doc-2", file_name="other.pdf"))
        bad = _proposal()
        bad["citations"][0]["attachment_id"] = "att-2"
        result = _ingest(ai_repo, _envelope(bad), key="wrong-doc")
        assert result.rejected_count == 1
    finally:
        conn.close()


def test_citation_wrong_attachment_rejected():
    conn, _, _, ai_repo = _seed()
    try:
        bad = _proposal()
        bad["citations"][0]["attachment_id"] = "missing-att"
        result = _ingest(ai_repo, _envelope(bad), key="wrong-att")
        assert result.rejected_count == 1
    finally:
        conn.close()


def test_citation_wrong_page_rejected():
    conn, _, _, ai_repo = _seed()
    try:
        bad = _proposal()
        bad["citations"][0]["page_start"] = 9
        bad["citations"][0]["page_end"] = 9
        result = _ingest(ai_repo, _envelope(bad), key="wrong-page")
        assert result.rejected_count == 1
    finally:
        conn.close()


def test_excerpt_exact_match():
    conn, _, _, ai_repo = _seed()
    try:
        result = _ingest(ai_repo, _envelope(), key="exact")
        assert result.accepted_count == 1
        assert result.warning_count == 0
    finally:
        conn.close()


def test_excerpt_normalized_match():
    conn, _, _, ai_repo = _seed()
    try:
        proposal = _proposal()
        proposal["citations"][0]["excerpt"] = "Noi dung   xu ly van ban."
        result = _ingest(ai_repo, _envelope(proposal), key="normalized")
        assert result.accepted_count == 1
    finally:
        conn.close()


def test_excerpt_missing_rejected():
    conn, _, _, ai_repo = _seed()
    try:
        bad = _proposal()
        bad["citations"][0]["excerpt"] = "khong co trong trang"
        result = _ingest(ai_repo, _envelope(bad), key="missing-excerpt")
        assert result.rejected_count == 1
    finally:
        conn.close()


def test_exact_duplicate_does_not_create_second_action_item():
    conn, _, _, ai_repo = _seed()
    try:
        payload = _envelope()
        first = _ingest(ai_repo, payload, key="dup-1")
        second = _ingest(ai_repo, copy.deepcopy(payload), key="dup-2")
        count = conn.execute("SELECT COUNT(*) AS n FROM action_items").fetchone()["n"]
        assert first.accepted_count == 1
        assert second.duplicate_count == 1
        assert count == 1
    finally:
        conn.close()


def test_possible_duplicate_is_saved_with_warning():
    conn, _, _, ai_repo = _seed()
    try:
        _ingest(ai_repo, _envelope(), key="possible-1")
        proposal = _proposal(external_proposal_id="p-2", description="Noi dung khac.")
        result = _ingest(ai_repo, _envelope(proposal), key="possible-2")
        row = conn.execute(
            "SELECT warnings FROM ai_proposal_items WHERE action_item_id = ?",
            (result.action_item_ids[0],),
        ).fetchone()
        assert result.accepted_count == 1
        assert "POSSIBLE_DUPLICATE" in row["warnings"]
    finally:
        conn.close()


def test_idempotency_second_run_does_not_duplicate():
    conn, _, _, ai_repo = _seed()
    try:
        first = _ingest(ai_repo, _envelope(), key="same-key")
        second = _ingest(ai_repo, _envelope(), key="same-key")
        batch_count = conn.execute("SELECT COUNT(*) AS n FROM ai_proposal_batches").fetchone()["n"]
        count = conn.execute("SELECT COUNT(*) AS n FROM action_items").fetchone()["n"]
        assert first.batch_id == second.batch_id
        assert batch_count == 1
        assert count == 1
    finally:
        conn.close()


def test_same_key_different_body_returns_conflict():
    conn, _, _, ai_repo = _seed()
    try:
        first = _ingest(ai_repo, _envelope(), key="conflict-key")
        changed = _proposal(external_proposal_id="p-2", title="Viec khac")
        second = _ingest(ai_repo, _envelope(changed), key="conflict-key")
        assert first.batch_id
        assert second.batch_id == ""
        assert second.error_code == IDEMPOTENCY_CONFLICT_ERROR_CODE
        assert second.idempotency_key == "conflict-key"
        assert second.existing_batch_id == first.batch_id
        assert IDEMPOTENCY_CONFLICT_ERROR_CODE in second.errors[0]
    finally:
        conn.close()


def test_same_key_different_body_does_not_change_existing_batch():
    conn, _, _, ai_repo = _seed()
    try:
        original = _envelope()
        first = _ingest(ai_repo, original, key="conflict-preserve")
        changed = _envelope(_proposal(external_proposal_id="p-2", title="Viec khac"))
        _ingest(ai_repo, changed, key="conflict-preserve")
        row = conn.execute(
            "SELECT raw_response_sha256 FROM ai_proposal_batches WHERE id = ?",
            (first.batch_id,),
        ).fetchone()
        assert row["raw_response_sha256"] == compute_stable_hash(original)
    finally:
        conn.close()


def test_same_key_different_body_does_not_create_action_item_or_citation():
    conn, _, _, ai_repo = _seed()
    try:
        _ingest(ai_repo, _envelope(), key="conflict-no-write")
        item_before = conn.execute("SELECT COUNT(*) AS n FROM action_items").fetchone()["n"]
        citation_before = conn.execute("SELECT COUNT(*) AS n FROM source_citations").fetchone()["n"]
        changed = _envelope(_proposal(external_proposal_id="p-2", title="Viec khac"))
        _ingest(ai_repo, changed, key="conflict-no-write")
        item_after = conn.execute("SELECT COUNT(*) AS n FROM action_items").fetchone()["n"]
        citation_after = conn.execute("SELECT COUNT(*) AS n FROM source_citations").fetchone()["n"]
        assert item_after == item_before
        assert citation_after == citation_before
    finally:
        conn.close()


def test_idempotency_race_same_body_returns_winning_batch():
    conn, _, _, ai_repo = _seed(RacingBatchRepository)
    try:
        result = _ingest(ai_repo, _envelope(), key="race-same")
        batch_count = conn.execute("SELECT COUNT(*) AS n FROM ai_proposal_batches").fetchone()["n"]
        item_count = conn.execute("SELECT COUNT(*) AS n FROM action_items").fetchone()["n"]
        assert result.batch_id == "race-winning-batch"
        assert result.error_code is None
        assert batch_count == 1
        assert item_count == 0
    finally:
        conn.close()


def test_idempotency_race_different_body_returns_conflict():
    conn, _, _, ai_repo = _seed(RacingBatchRepository)
    try:
        ai_repo.winning_hash = "b" * 64
        result = _ingest(ai_repo, _envelope(), key="race-different")
        batch_count = conn.execute("SELECT COUNT(*) AS n FROM ai_proposal_batches").fetchone()["n"]
        item_count = conn.execute("SELECT COUNT(*) AS n FROM action_items").fetchone()["n"]
        assert result.error_code == IDEMPOTENCY_CONFLICT_ERROR_CODE
        assert result.existing_batch_id == "race-winning-batch"
        assert batch_count == 1
        assert item_count == 0
    finally:
        conn.close()


def test_citation_insert_failure_rolls_back_action_item():
    conn, _, _, ai_repo = _seed(FailingCitationRepository)
    try:
        result = _ingest(ai_repo, _envelope(), key="rollback")
        count = conn.execute("SELECT COUNT(*) AS n FROM action_items").fetchone()["n"]
        assert result.rejected_count == 1
        assert count == 0
    finally:
        conn.close()


def test_persisted_internal_error_is_bounded():
    conn, _, _, ai_repo = _seed(LongFailingCitationRepository)
    try:
        result = _ingest(ai_repo, _envelope(), key="bounded-error")
        row = conn.execute("SELECT error_message FROM ai_proposal_items").fetchone()
        assert result.rejected_count == 1
        assert len(result.errors[0]) <= MAX_ERROR_LENGTH
        assert len(row["error_message"]) <= MAX_ERROR_LENGTH
    finally:
        conn.close()


def test_batch_partial_success():
    conn, _, _, ai_repo = _seed()
    try:
        bad = _proposal(external_proposal_id="p-bad", title="Viec sai citation")
        bad["citations"][0]["page_start"] = 7
        bad["citations"][0]["page_end"] = 7
        result = _ingest(ai_repo, _envelope(_proposal(), bad), key="partial")
        assert result.accepted_count == 1
        assert result.rejected_count == 1
    finally:
        conn.close()


def test_raw_response_hash_is_stable():
    conn, _, _, ai_repo = _seed()
    try:
        payload = _envelope()
        result = _ingest(ai_repo, payload, key="hash")
        row = conn.execute("SELECT raw_response_sha256 FROM ai_proposal_batches WHERE id = ?", (result.batch_id,)).fetchone()
        assert row["raw_response_sha256"] == compute_stable_hash(payload)
    finally:
        conn.close()


def test_warning_at_limit_is_accepted():
    proposal = _proposal(warnings=["w" * MAX_WARNING_LENGTH])
    envelope = _envelope(proposal, warnings=["e" * MAX_WARNING_LENGTH])
    parsed = parse_ai_proposal_json(envelope)
    assert parsed.warnings == ["e" * MAX_WARNING_LENGTH]
    assert parsed.proposals[0].warnings == ["w" * MAX_WARNING_LENGTH]


def test_warning_over_limit_is_rejected():
    with pytest.raises(AiProposalValidationError):
        parse_ai_proposal_json(_envelope(_proposal(warnings=["w" * (MAX_WARNING_LENGTH + 1)])))


def test_too_many_warnings_rejected():
    with pytest.raises(AiProposalValidationError):
        parse_ai_proposal_json(_envelope(warnings=["w"] * (MAX_WARNINGS_PER_ENVELOPE + 1)))
    with pytest.raises(AiProposalValidationError):
        parse_ai_proposal_json(_envelope(_proposal(warnings=["w"] * (MAX_WARNINGS_PER_PROPOSAL + 1))))


def test_json_schema_has_warning_bounds():
    schema_path = "docs/architecture/G04_AI_OUTPUT_SCHEMA.json"
    with open(schema_path, encoding="utf-8") as handle:
        schema = json.load(handle)
    envelope_warnings = schema["properties"]["warnings"]
    proposal_warnings = schema["properties"]["proposals"]["items"]["properties"]["warnings"]
    assert envelope_warnings["maxItems"] == MAX_WARNINGS_PER_ENVELOPE
    assert envelope_warnings["items"]["maxLength"] == MAX_WARNING_LENGTH
    assert proposal_warnings["maxItems"] == MAX_WARNINGS_PER_PROPOSAL
    assert proposal_warnings["items"]["maxLength"] == MAX_WARNING_LENGTH


def test_prompt_and_model_metadata_saved():
    conn, _, _, ai_repo = _seed()
    try:
        result = _ingest(ai_repo, _envelope(), key="metadata")
        row = conn.execute(
            "SELECT ai_model, ai_prompt_version FROM action_items WHERE id = ?",
            (result.action_item_ids[0],),
        ).fetchone()
        assert row["ai_model"] == "fake-model:v1"
        assert row["ai_prompt_version"] == "prompt-v1"
    finally:
        conn.close()


def test_no_token_or_raw_body_columns_are_stored():
    conn, _, _, _ = _seed()
    try:
        columns = {
            row["name"]
            for table in ("ai_proposal_batches", "ai_proposal_items", "ai_proposal_warnings")
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        assert "token" not in columns
        assert "raw_response_body" not in columns
    finally:
        conn.close()


def test_migration_first_run_records_version():
    conn = _connect()
    try:
        init_ai_proposal_schema(conn)
        row = conn.execute(
            "SELECT version FROM schema_migrations WHERE version = ?",
            (AI_PROPOSAL_MIGRATION_VERSION,),
        ).fetchone()
        assert row["version"] == AI_PROPOSAL_MIGRATION_VERSION
    finally:
        conn.close()


def test_migration_second_run_is_idempotent():
    conn = _connect()
    try:
        init_ai_proposal_schema(conn)
        init_ai_proposal_schema(conn)
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM schema_migrations WHERE version = ?",
            (AI_PROPOSAL_MIGRATION_VERSION,),
        ).fetchone()["n"]
        assert count == 1
    finally:
        conn.close()


def test_legacy_g03_extracted_pages_survive_migration():
    conn, _, _, _ = _seed()
    try:
        init_ai_proposal_schema(conn)
        rows = conn.execute("SELECT page_number, text FROM extracted_pages ORDER BY page_number").fetchall()
        assert [row["page_number"] for row in rows] == [1, 2]
        assert rows[0]["text"] == PAGE_1
    finally:
        conn.close()


def test_fake_provider_contract_returns_fixture_without_api():
    payload = _envelope()
    provider = FakeAiProposalProvider(payload)
    assert provider.generate_proposals(document_id="doc-1", attachment_ids=["att-1"]) is payload


def test_g02_domain_tables_remain_usable_after_g04_migration():
    conn, domain_repo, _, _ = _seed()
    try:
        domain_repo.save_attachment(
            Attachment(
                id="att-extra",
                document_id="doc-1",
                file_name="extra.pdf",
                validation_status=AttachmentValidationStatus.VALIDATED,
            )
        )
        row = conn.execute("SELECT file_name FROM attachments WHERE id = 'att-extra'").fetchone()
        assert row["file_name"] == "extra.pdf"
    finally:
        conn.close()
