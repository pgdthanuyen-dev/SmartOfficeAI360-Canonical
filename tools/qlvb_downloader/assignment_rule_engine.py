from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .assignment_rule_models import (
    AssignmentRuleBundle,
    AssignmentRuleCondition,
    AssignmentRuleExclusion,
    AssignmentRuleMatch,
    AssignmentRuleRole,
    AssignmentRuleUnit,
    ConditionType,
    ExclusionType,
    MatchDecision,
    MatchMode,
    MatchWarningCode,
    RuleRoleType,
    RuleUnitType,
)
from .assignment_rule_repository import AssignmentRuleRepository
from .domain_models import compute_stable_hash


ASSIGNMENT_RULE_ENGINE_VERSION = "g05a.engine.1"
MAX_SIGNAL_TEXT_CHARS = 2000
MAX_SIGNAL_LIST_ITEMS = 100
MAX_EXPLANATION_CHARS = 2000
TOP_RULE_CONFLICT_DELTA = 3.0
MATCHED_THRESHOLD = 90.0
WARNING_THRESHOLD = 75.0


@dataclass
class DocumentAssignmentSignals:
    tenant_id: str
    document_id: str
    document_revision: str
    document_type: str | None = None
    issuer_name: str | None = None
    issuer_group: str | None = None
    domain_codes: list[str] = field(default_factory=list)
    subdomain_codes: list[str] = field(default_factory=list)
    required_actions: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    target_entities: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    title: str | None = None
    summary: str | None = None
    reference_date: str | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id or not self.document_id or not self.document_revision:
            raise ValueError("tenant_id, document_id and document_revision are required")
        self.document_type = _normalize_optional(self.document_type)
        self.issuer_name = _truncate_signal_text(self.issuer_name)
        self.issuer_group = _normalize_optional(self.issuer_group)
        self.domain_codes = normalize_signal_list(self.domain_codes)
        self.subdomain_codes = normalize_signal_list(self.subdomain_codes)
        self.required_actions = normalize_signal_list(self.required_actions)
        self.keywords = normalize_signal_list(self.keywords)
        self.target_entities = normalize_signal_list(self.target_entities)
        self.expected_outputs = normalize_signal_list(self.expected_outputs)
        self.title = _truncate_signal_text(self.title)
        self.summary = _truncate_signal_text(self.summary)
        self.reference_date = self.reference_date or datetime.now(UTC).date().isoformat()

    def input_fingerprint(self) -> str:
        return compute_stable_hash(
            {
                "engine_version": ASSIGNMENT_RULE_ENGINE_VERSION,
                "tenant_id": self.tenant_id,
                "document_id": self.document_id,
                "document_revision": self.document_revision,
                "reference_date": self.reference_date,
                "document_type": self.document_type,
                "issuer_group": self.issuer_group,
                "domain_codes": self.domain_codes,
                "subdomain_codes": self.subdomain_codes,
                "required_actions": self.required_actions,
                "keywords": self.keywords,
                "target_entities": self.target_entities,
                "expected_outputs": self.expected_outputs,
                "title": normalize_assignment_signal(self.title),
                "summary": normalize_assignment_signal(self.summary),
            }
        )


@dataclass(frozen=True)
class ConditionMatch:
    condition_id: str
    condition_type: str
    value: str
    weight: int
    matched: bool
    is_required: bool


@dataclass(frozen=True)
class ExclusionMatch:
    exclusion_id: str
    exclusion_type: str
    value: str
    penalty: int
    is_hard_exclusion: bool


@dataclass
class AssignmentRuleCandidate:
    rule_id: str
    rule_code: str
    rule_version: str
    score: float
    decision: MatchDecision
    matched_conditions: list[str]
    missing_required_conditions: list[str]
    matched_exclusions: list[str]
    soft_penalty_total: int
    lead_unit_keys: list[str]
    coordinating_unit_keys: list[str]
    required_role_codes: list[str]
    warnings: list[MatchWarningCode]
    explanation: str
    priority: int = 0
    required_condition_count: int = 0
    matched_required_condition_count: int = 0


@dataclass
class AssignmentRecommendation:
    document_id: str
    document_revision: str
    input_fingerprint: str
    evaluated_rule_count: int
    eligible_rule_count: int
    excluded_rule_count: int
    primary_rule: AssignmentRuleCandidate | None
    alternative_rules: list[AssignmentRuleCandidate]
    conflicting_rules: list[AssignmentRuleCandidate]
    decision: MatchDecision
    confidence: float
    lead_unit_key: str | None
    coordinating_unit_keys: list[str]
    required_roles: list[str]
    unresolved_fields: list[str]
    warnings: list[MatchWarningCode]
    explanation: str
    engine_version: str
    evaluated_at: str


@dataclass
class AssignmentRuleEvaluation:
    signals: DocumentAssignmentSignals
    candidates: list[AssignmentRuleCandidate]
    recommendation: AssignmentRecommendation


class AssignmentRuleEngine:
    def __init__(self, repository: AssignmentRuleRepository):
        self.repository = repository

    def evaluate(
        self,
        signals: DocumentAssignmentSignals,
        *,
        persist_matches: bool = False,
    ) -> AssignmentRuleEvaluation:
        active_rules = self.repository.list_active_rules(
            as_of_date=signals.reference_date or datetime.now(UTC).date().isoformat(),
            tenant_id=signals.tenant_id,
        )
        candidates: list[AssignmentRuleCandidate] = []
        for row in active_rules:
            bundle = self.repository.get_rule_bundle(row["id"])
            if bundle is None:
                continue
            try:
                candidates.append(self.evaluate_rule(bundle, signals))
            except Exception as exc:
                candidates.append(
                    AssignmentRuleCandidate(
                        rule_id=row["id"],
                        rule_code=row["rule_code"],
                        rule_version=row["version"],
                        score=0.0,
                        decision=MatchDecision.NO_MATCH,
                        matched_conditions=[],
                        missing_required_conditions=[],
                        matched_exclusions=[],
                        soft_penalty_total=0,
                        lead_unit_keys=[],
                        coordinating_unit_keys=[],
                        required_role_codes=[],
                        warnings=[MatchWarningCode.MISSING_REQUIRED_SIGNAL],
                        explanation=_bounded_explanation(f"Rule configuration error: {type(exc).__name__}"),
                        priority=int(row["priority"]),
                    )
                )
        ranked = self.rank_candidates(candidates)
        recommendation = self.build_recommendation(signals, ranked, evaluated_rule_count=len(active_rules))
        evaluation = AssignmentRuleEvaluation(signals=signals, candidates=ranked, recommendation=recommendation)
        if persist_matches:
            self.persist_evaluation(evaluation)
        return evaluation

    def evaluate_rule(self, bundle: AssignmentRuleBundle, signals: DocumentAssignmentSignals) -> AssignmentRuleCandidate:
        hard_matches = _matched_exclusions(bundle.exclusions, signals, hard_only=True)
        all_exclusion_matches = _matched_exclusions(bundle.exclusions, signals, hard_only=False)
        soft_matches = [match for match in all_exclusion_matches if not match.is_hard_exclusion]
        if hard_matches:
            return AssignmentRuleCandidate(
                rule_id=bundle.rule.id,
                rule_code=bundle.rule.rule_code,
                rule_version=bundle.rule.version,
                score=0.0,
                decision=MatchDecision.EXCLUDED,
                matched_conditions=[],
                missing_required_conditions=[],
                matched_exclusions=[match.exclusion_id for match in hard_matches],
                soft_penalty_total=0,
                lead_unit_keys=[],
                coordinating_unit_keys=[],
                required_role_codes=[],
                warnings=[],
                explanation=_bounded_explanation(f"Hard exclusion matched: {hard_matches[0].value}"),
                priority=bundle.rule.priority,
            )

        condition_matches = [_evaluate_condition(condition, signals) for condition in bundle.conditions]
        total_weight = sum(max(match.weight, 0) for match in condition_matches)
        matched_weight = sum(max(match.weight, 0) for match in condition_matches if match.matched)
        if total_weight <= 0:
            return _candidate_from_conditions(
                bundle,
                score=0.0,
                decision=MatchDecision.NO_MATCH,
                condition_matches=condition_matches,
                exclusion_matches=soft_matches,
                warnings=[MatchWarningCode.MISSING_REQUIRED_SIGNAL],
                explanation="No positive conditions configured.",
            )

        base_score = round(100 * matched_weight / total_weight, 2)
        soft_penalty_total = sum(match.penalty for match in soft_matches)
        final_score = _clamp_score(base_score - soft_penalty_total)
        missing_required = [match for match in condition_matches if match.is_required and not match.matched]
        warnings: list[MatchWarningCode] = []
        if missing_required:
            warnings.append(MatchWarningCode.MISSING_REQUIRED_SIGNAL)
        decision = _decision_for_score(final_score, minimum_confidence=bundle.rule.minimum_confidence, missing_required=bool(missing_required))
        if final_score < bundle.rule.minimum_confidence:
            warnings.append(MatchWarningCode.LOW_CONFIDENCE)

        units = _effective_units(bundle.units, signals.reference_date or "")
        roles = _effective_roles(bundle.roles, signals.reference_date or "")
        lead_units = [unit.source_unit_key for unit in units if unit.unit_type == RuleUnitType.LEAD_UNIT]
        if len(lead_units) > 1:
            warnings.append(MatchWarningCode.UNIT_UNRESOLVED)
            decision = MatchDecision.NEEDS_CLASSIFICATION if final_score >= WARNING_THRESHOLD else decision
        required_roles = [role.role_code for role in roles if role.is_required]
        if any(role.is_required for role in bundle.roles) and not required_roles:
            warnings.append(MatchWarningCode.ROLE_UNRESOLVED)
            decision = MatchDecision.NEEDS_CLASSIFICATION if final_score >= WARNING_THRESHOLD else decision

        explanation_parts = [
            f"Matched weight {matched_weight}/{total_weight}.",
            f"Base score {base_score}.",
        ]
        if soft_penalty_total:
            explanation_parts.append(f"Soft exclusion penalty {soft_penalty_total}.")
        if missing_required:
            explanation_parts.append(f"Missing required signals: {len(missing_required)}.")
        return _candidate_from_conditions(
            bundle,
            score=final_score,
            decision=decision,
            condition_matches=condition_matches,
            exclusion_matches=soft_matches,
            warnings=warnings,
            explanation=" ".join(explanation_parts),
            units=units,
            roles=roles,
        )

    def rank_candidates(self, candidates: list[AssignmentRuleCandidate]) -> list[AssignmentRuleCandidate]:
        return sorted(
            candidates,
            key=lambda candidate: (
                _decision_rank(candidate.decision),
                candidate.score,
                candidate.priority,
                candidate.matched_required_condition_count,
                len(candidate.matched_conditions),
                _version_sort_key(candidate.rule_version),
                _invert_string(candidate.rule_code),
            ),
            reverse=True,
        )

    def build_recommendation(
        self,
        signals: DocumentAssignmentSignals,
        candidates: list[AssignmentRuleCandidate],
        *,
        evaluated_rule_count: int,
    ) -> AssignmentRecommendation:
        primary_candidates = [
            candidate
            for candidate in candidates
            if candidate.decision in {MatchDecision.MATCHED, MatchDecision.MATCHED_WITH_WARNING, MatchDecision.NEEDS_CLASSIFICATION}
        ]
        eligible = [candidate for candidate in candidates if candidate.decision in {MatchDecision.MATCHED, MatchDecision.MATCHED_WITH_WARNING}]
        excluded_count = sum(1 for candidate in candidates if candidate.decision == MatchDecision.EXCLUDED)
        primary = primary_candidates[0] if primary_candidates else None
        conflicts = _find_top_conflicts(eligible)
        warnings: list[MatchWarningCode] = []
        unresolved_fields: list[str] = []
        decision = primary.decision if primary else _fallback_decision(candidates)
        lead_unit_key = primary.lead_unit_keys[0] if primary and len(primary.lead_unit_keys) == 1 else None
        if primary and len(primary.lead_unit_keys) != 1:
            warnings.append(MatchWarningCode.UNIT_UNRESOLVED)
            unresolved_fields.append("lead_unit_key")
        if conflicts:
            decision = MatchDecision.NEEDS_CLASSIFICATION
            warnings.extend([MatchWarningCode.MULTIPLE_TOP_RULES, MatchWarningCode.CONFLICTING_RULES])
            lead_unit_key = None
            unresolved_fields.append("conflicting_rules")
        if primary:
            warnings.extend(primary.warnings)
        warnings = _dedupe_warnings(warnings)
        explanation = _recommendation_explanation(primary, conflicts)
        return AssignmentRecommendation(
            document_id=signals.document_id,
            document_revision=signals.document_revision,
            input_fingerprint=signals.input_fingerprint(),
            evaluated_rule_count=evaluated_rule_count,
            eligible_rule_count=len(eligible),
            excluded_rule_count=excluded_count,
            primary_rule=primary,
            alternative_rules=[candidate for candidate in primary_candidates if candidate is not primary][:5],
            conflicting_rules=conflicts,
            decision=decision,
            confidence=primary.score if primary else 0.0,
            lead_unit_key=lead_unit_key,
            coordinating_unit_keys=primary.coordinating_unit_keys if primary else [],
            required_roles=primary.required_role_codes if primary else [],
            unresolved_fields=_dedupe_strings(unresolved_fields),
            warnings=warnings,
            explanation=explanation,
            engine_version=ASSIGNMENT_RULE_ENGINE_VERSION,
            evaluated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        )

    def persist_evaluation(self, evaluation: AssignmentRuleEvaluation) -> None:
        fingerprint = evaluation.signals.input_fingerprint()
        for candidate in evaluation.candidates:
            self.repository.append_match(
                AssignmentRuleMatch(
                    tenant_id=evaluation.signals.tenant_id,
                    document_id=evaluation.signals.document_id,
                    document_revision=evaluation.signals.document_revision,
                    rule_id=candidate.rule_id,
                    rule_code=candidate.rule_code,
                    rule_version=candidate.rule_version,
                    score=int(round(candidate.score)),
                    decision=candidate.decision,
                    matched_condition_count=len(candidate.matched_conditions),
                    required_condition_count=candidate.required_condition_count,
                    exclusion_count=len(candidate.matched_exclusions),
                    explanation=candidate.explanation,
                    warnings_json=json.dumps([warning.value for warning in candidate.warnings], ensure_ascii=False),
                    input_fingerprint=fingerprint,
                )
            )


def evaluate_assignment_rules(
    repository: AssignmentRuleRepository,
    signals: DocumentAssignmentSignals,
    *,
    persist_matches: bool = False,
) -> AssignmentRuleEvaluation:
    return AssignmentRuleEngine(repository).evaluate(signals, persist_matches=persist_matches)


def normalize_assignment_signal(value: Any) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFC", str(value))
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    chars: list[str] = []
    for char in normalized:
        category = unicodedata.category(char)
        if char in "\n\t":
            chars.append(char)
        elif category.startswith("C"):
            continue
        else:
            chars.append(char)
    return re.sub(r"\s+", " ", "".join(chars).casefold()).strip()


def normalize_signal_list(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values[:MAX_SIGNAL_LIST_ITEMS]:
        normalized = normalize_assignment_signal(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _evaluate_condition(condition: AssignmentRuleCondition, signals: DocumentAssignmentSignals) -> ConditionMatch:
    haystacks = _signals_for_condition(condition.condition_type, signals)
    matched = any(_match_value(condition.normalized_value, haystack, condition.match_mode) for haystack in haystacks)
    return ConditionMatch(
        condition_id=condition.id,
        condition_type=condition.condition_type.value,
        value=condition.normalized_value,
        weight=condition.weight,
        matched=matched,
        is_required=bool(condition.is_required),
    )


def _matched_exclusions(
    exclusions: list[AssignmentRuleExclusion],
    signals: DocumentAssignmentSignals,
    *,
    hard_only: bool,
) -> list[ExclusionMatch]:
    matches: list[ExclusionMatch] = []
    for exclusion in exclusions:
        if hard_only and not exclusion.is_hard_exclusion:
            continue
        haystacks = _signals_for_exclusion(exclusion.exclusion_type, signals)
        if any(_match_value(exclusion.normalized_value, haystack, MatchMode.CONTAINS) for haystack in haystacks):
            matches.append(
                ExclusionMatch(
                    exclusion_id=exclusion.id,
                    exclusion_type=exclusion.exclusion_type.value,
                    value=exclusion.normalized_value,
                    penalty=exclusion.penalty,
                    is_hard_exclusion=bool(exclusion.is_hard_exclusion),
                )
            )
    return matches


def _match_value(needle: str, haystack: str, mode: MatchMode) -> bool:
    if not needle or not haystack:
        return False
    if mode == MatchMode.EXACT:
        return haystack == needle
    if mode == MatchMode.CONTAINS:
        return needle in haystack
    if mode == MatchMode.TOKEN:
        return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None
    if mode == MatchMode.PREFIX:
        return haystack.startswith(needle)
    if mode == MatchMode.REGEX_SAFE:
        try:
            return re.search(needle, haystack) is not None
        except re.error:
            return False
    return False


def _signals_for_condition(condition_type: ConditionType, signals: DocumentAssignmentSignals) -> list[str]:
    if condition_type == ConditionType.DOMAIN:
        return signals.domain_codes
    if condition_type == ConditionType.SUBDOMAIN:
        return signals.subdomain_codes
    if condition_type == ConditionType.DOCUMENT_TYPE:
        return [signals.document_type or ""]
    if condition_type == ConditionType.ISSUER_GROUP:
        return [signals.issuer_group or ""]
    if condition_type == ConditionType.REQUIRED_ACTION:
        return signals.required_actions
    if condition_type in {ConditionType.REQUIRED_KEYWORD, ConditionType.PREFERRED_KEYWORD}:
        return [normalize_assignment_signal(signals.title), normalize_assignment_signal(signals.summary), *signals.keywords]
    if condition_type == ConditionType.TARGET_ENTITY:
        return signals.target_entities
    if condition_type == ConditionType.EXPECTED_OUTPUT:
        return signals.expected_outputs
    return []


def _signals_for_exclusion(exclusion_type: ExclusionType, signals: DocumentAssignmentSignals) -> list[str]:
    if exclusion_type == ExclusionType.EXCLUDED_KEYWORD:
        return [normalize_assignment_signal(signals.title), normalize_assignment_signal(signals.summary), *signals.keywords]
    if exclusion_type == ExclusionType.EXCLUDED_ACTION:
        return signals.required_actions
    if exclusion_type == ExclusionType.EXCLUDED_ISSUER:
        return [normalize_assignment_signal(signals.issuer_name), signals.issuer_group or ""]
    if exclusion_type == ExclusionType.EXCLUDED_DOCUMENT_TYPE:
        return [signals.document_type or ""]
    return []


def _candidate_from_conditions(
    bundle: AssignmentRuleBundle,
    *,
    score: float,
    decision: MatchDecision,
    condition_matches: list[ConditionMatch],
    exclusion_matches: list[ExclusionMatch],
    warnings: list[MatchWarningCode],
    explanation: str,
    units: list[AssignmentRuleUnit] | None = None,
    roles: list[AssignmentRuleRole] | None = None,
) -> AssignmentRuleCandidate:
    units = units if units is not None else _effective_units(bundle.units, "")
    roles = roles if roles is not None else _effective_roles(bundle.roles, "")
    lead_unit_keys = [unit.source_unit_key for unit in units if unit.unit_type == RuleUnitType.LEAD_UNIT]
    coordinating_unit_keys = [unit.source_unit_key for unit in units if unit.unit_type == RuleUnitType.COORDINATING_UNIT]
    required_roles = [role.role_code for role in roles if role.is_required]
    return AssignmentRuleCandidate(
        rule_id=bundle.rule.id,
        rule_code=bundle.rule.rule_code,
        rule_version=bundle.rule.version,
        score=score,
        decision=decision,
        matched_conditions=[match.condition_id for match in condition_matches if match.matched],
        missing_required_conditions=[match.condition_id for match in condition_matches if match.is_required and not match.matched],
        matched_exclusions=[match.exclusion_id for match in exclusion_matches],
        soft_penalty_total=sum(match.penalty for match in exclusion_matches if not match.is_hard_exclusion),
        lead_unit_keys=lead_unit_keys,
        coordinating_unit_keys=coordinating_unit_keys,
        required_role_codes=required_roles,
        warnings=_dedupe_warnings(warnings),
        explanation=_bounded_explanation(explanation),
        priority=bundle.rule.priority,
        required_condition_count=sum(1 for match in condition_matches if match.is_required),
        matched_required_condition_count=sum(1 for match in condition_matches if match.is_required and match.matched),
    )


def _decision_for_score(score: float, *, minimum_confidence: int, missing_required: bool) -> MatchDecision:
    if missing_required and score >= WARNING_THRESHOLD:
        return MatchDecision.NEEDS_CLASSIFICATION
    if score < WARNING_THRESHOLD:
        return MatchDecision.NO_MATCH
    if score < minimum_confidence:
        return MatchDecision.NEEDS_CLASSIFICATION if score >= WARNING_THRESHOLD else MatchDecision.NO_MATCH
    if score >= MATCHED_THRESHOLD and not missing_required:
        return MatchDecision.MATCHED
    if not missing_required:
        return MatchDecision.MATCHED_WITH_WARNING
    return MatchDecision.NO_MATCH


def _find_top_conflicts(eligible: list[AssignmentRuleCandidate]) -> list[AssignmentRuleCandidate]:
    if len(eligible) < 2:
        return []
    top = eligible[0]
    conflicts = []
    for candidate in eligible[1:]:
        if top.score - candidate.score > TOP_RULE_CONFLICT_DELTA:
            break
        if set(top.lead_unit_keys) != set(candidate.lead_unit_keys) or set(top.required_role_codes) != set(candidate.required_role_codes):
            conflicts.append(candidate)
    return conflicts


def _fallback_decision(candidates: list[AssignmentRuleCandidate]) -> MatchDecision:
    if candidates and all(candidate.decision == MatchDecision.EXCLUDED for candidate in candidates):
        return MatchDecision.EXCLUDED
    return MatchDecision.NO_MATCH


def _effective_units(units: list[AssignmentRuleUnit], as_of_date: str) -> list[AssignmentRuleUnit]:
    if not as_of_date:
        return sorted(units, key=lambda unit: (-unit.priority, unit.source_unit_key, unit.id))
    return sorted(
        [unit for unit in units if _is_effective(unit.effective_from, unit.effective_to, as_of_date)],
        key=lambda unit: (-unit.priority, unit.source_unit_key, unit.id),
    )


def _effective_roles(roles: list[AssignmentRuleRole], as_of_date: str) -> list[AssignmentRuleRole]:
    role_order = {
        RuleRoleType.LEADER: 0,
        RuleRoleType.MONITOR: 1,
        RuleRoleType.LEAD_EXECUTOR: 2,
        RuleRoleType.CO_EXECUTOR: 3,
    }
    if not as_of_date:
        return sorted(roles, key=lambda role: (-role.priority, role_order.get(role.role_type, 99), role.role_code, role.id))
    return sorted(
        [role for role in roles if _is_effective(role.effective_from, role.effective_to, as_of_date)],
        key=lambda role: (-role.priority, role_order.get(role.role_type, 99), role.role_code, role.id),
    )


def _is_effective(effective_from: str | None, effective_to: str | None, as_of_date: str) -> bool:
    return (not effective_from or effective_from <= as_of_date) and (not effective_to or effective_to >= as_of_date)


def _decision_rank(decision: MatchDecision) -> int:
    ranks = {
        MatchDecision.MATCHED: 5,
        MatchDecision.MATCHED_WITH_WARNING: 4,
        MatchDecision.NEEDS_CLASSIFICATION: 3,
        MatchDecision.NO_MATCH: 2,
        MatchDecision.EXCLUDED: 1,
    }
    return ranks[decision]


def _version_sort_key(version: str) -> tuple[int, str]:
    numbers = re.findall(r"\d+", version or "")
    return (int(numbers[-1]) if numbers else 0, version or "")


def _invert_string(value: str) -> str:
    return "".join(chr(255 - ord(char)) for char in value)


def _clamp_score(value: float) -> float:
    return min(100.0, max(0.0, round(value, 2)))


def _normalize_optional(value: str | None) -> str | None:
    normalized = normalize_assignment_signal(value)
    return normalized or None


def _truncate_signal_text(value: str | None) -> str | None:
    if value is None:
        return None
    return str(value)[:MAX_SIGNAL_TEXT_CHARS]


def _bounded_explanation(value: str) -> str:
    cleaned = normalize_assignment_signal(value)
    return cleaned[:MAX_EXPLANATION_CHARS]


def _recommendation_explanation(primary: AssignmentRuleCandidate | None, conflicts: list[AssignmentRuleCandidate]) -> str:
    if primary is None:
        return "no active assignment rule matched"
    if conflicts:
        return _bounded_explanation(
            f"Top rule {primary.rule_code} conflicts with {len(conflicts)} rule(s) within {TOP_RULE_CONFLICT_DELTA} points."
        )
    return _bounded_explanation(f"Top rule {primary.rule_code} selected with score {primary.score}.")


def _dedupe_warnings(warnings: list[MatchWarningCode]) -> list[MatchWarningCode]:
    result: list[MatchWarningCode] = []
    seen: set[MatchWarningCode] = set()
    for warning in warnings:
        if warning not in seen:
            seen.add(warning)
            result.append(warning)
    return result


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
