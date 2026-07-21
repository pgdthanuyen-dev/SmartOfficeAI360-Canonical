"""Backend-only HTTP client for the Planner SmartOffice draft receiver."""

from __future__ import annotations

import json
import os
import socket
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .assignment_draft_planner_handoff import PLANNER_RECEIVER_PATH, PlannerDraftHandoff


class PlannerHandoffOutcome(StrEnum):
    CREATED = "CREATED"
    DUPLICATE = "DUPLICATE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTH_ERROR = "AUTH_ERROR"
    PLANNER_UNAVAILABLE = "PLANNER_UNAVAILABLE"
    UNKNOWN_RESULT = "UNKNOWN_RESULT"


@dataclass(frozen=True)
class PlannerHandoffConfig:
    enabled: bool
    base_url: str
    secret: str
    timeout_seconds: float = 10.0
    draft_url_template: str = ""

    @classmethod
    def from_environment(cls) -> "PlannerHandoffConfig":
        enabled = os.environ.get("SMARTOFFICE_PLANNER_HANDOFF_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
        base_url = os.environ.get("SMARTOFFICE_PLANNER_BASE_URL", "").strip()
        secret = os.environ.get("SMARTOFFICE_PLANNER_HANDOFF_SECRET", "").strip()
        template = os.environ.get("SMARTOFFICE_PLANNER_DRAFT_URL_TEMPLATE", "").strip()
        try:
            timeout = float(os.environ.get("SMARTOFFICE_PLANNER_HANDOFF_TIMEOUT_SECONDS", "10"))
        except ValueError:
            timeout = 10.0
        return cls(enabled, base_url, secret, max(1.0, min(timeout, 60.0)), template)

    def receiver_url(self) -> str | None:
        parsed = urlparse(self.base_url)
        if not self.enabled or not self.secret or parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        base = self.base_url.rstrip("/")
        path = PLANNER_RECEIVER_PATH
        if base.endswith("/api"):
            path = path.removeprefix("/api")
        return base + path


@dataclass(frozen=True)
class PlannerHandoffResult:
    outcome: PlannerHandoffOutcome
    correlation_id: str
    planner_draft_id: str | None = None
    planner_status: str | None = None
    planner_draft_url: str | None = None
    message: str = ""


HttpTransport = Callable[[str, dict[str, str], bytes, float], tuple[int, Any]]


class PlannerDraftHandoffClient:
    """Posts exactly once; uncertain delivery is deliberately not retried."""

    def __init__(self, config: PlannerHandoffConfig | None = None, transport: HttpTransport | None = None) -> None:
        self.config = config or PlannerHandoffConfig.from_environment()
        self._transport = transport or self._post_json

    def send(self, handoff: PlannerDraftHandoff) -> PlannerHandoffResult:
        correlation_id = uuid.uuid4().hex
        url = self.config.receiver_url()
        if not url:
            return PlannerHandoffResult(PlannerHandoffOutcome.PLANNER_UNAVAILABLE, correlation_id, message="Planner handoff is not configured.")
        payload = json.dumps(handoff.to_planner_receiver_payload(), ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json", "X-SmartOffice-Secret": self.config.secret}
        try:
            status, body = self._transport(url, headers, payload, self.config.timeout_seconds)
        except (TimeoutError, socket.timeout, URLError, ConnectionError):
            return PlannerHandoffResult(PlannerHandoffOutcome.UNKNOWN_RESULT, correlation_id, message="Planner response is uncertain; retry manually with the same draft.")
        except Exception:
            return PlannerHandoffResult(PlannerHandoffOutcome.UNKNOWN_RESULT, correlation_id, message="Planner response could not be verified.")
        return self._classify(status, body, correlation_id)

    def _classify(self, status: int, body: Any, correlation_id: str) -> PlannerHandoffResult:
        if status in {201, 200} and isinstance(body, dict) and body.get("success") is True:
            draft_id, planner_status, duplicate = body.get("draftId"), body.get("status"), body.get("duplicate")
            if isinstance(draft_id, str) and isinstance(planner_status, str) and isinstance(duplicate, bool):
                outcome = PlannerHandoffOutcome.DUPLICATE if duplicate else PlannerHandoffOutcome.CREATED
                if (status == 201 and not duplicate) or (status == 200 and duplicate):
                    return PlannerHandoffResult(outcome, correlation_id, draft_id, planner_status, self._draft_url(draft_id))
        if status in {400, 413}:
            return PlannerHandoffResult(PlannerHandoffOutcome.VALIDATION_ERROR, correlation_id, message="Planner rejected the draft payload.")
        if status in {401, 403}:
            return PlannerHandoffResult(PlannerHandoffOutcome.AUTH_ERROR, correlation_id, message="Planner handoff authentication failed.")
        if status == 503 or status >= 500:
            return PlannerHandoffResult(PlannerHandoffOutcome.PLANNER_UNAVAILABLE, correlation_id, message="Planner is unavailable.")
        return PlannerHandoffResult(PlannerHandoffOutcome.UNKNOWN_RESULT, correlation_id, message="Planner returned an unexpected result.")

    def _draft_url(self, planner_draft_id: str) -> str | None:
        template = self.config.draft_url_template
        if "{draft_id}" not in template:
            return None
        candidate = template.replace("{draft_id}", planner_draft_id)
        parsed = urlparse(candidate)
        return candidate if parsed.scheme in {"http", "https"} and parsed.netloc else None

    @staticmethod
    def _post_json(url: str, headers: dict[str, str], payload: bytes, timeout: float) -> tuple[int, Any]:
        request = Request(url, data=payload, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raw = exc.read(16_384).decode("utf-8", errors="replace")
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, None
