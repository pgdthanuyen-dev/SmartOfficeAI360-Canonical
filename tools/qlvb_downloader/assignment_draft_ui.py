"""Read-only SmartOffice view of AI assignment drafts before Planner handoff."""

from __future__ import annotations

from tkinter import messagebox

import customtkinter as ctk

from .assignment_draft_planner_handoff import (
    PENDING_OFFICE_REVIEW,
    build_planner_handoff,
    planner_display_status,
    planner_handoff_configured,
)
from .assignment_draft_service import AssignmentDraftService, AssignmentDraftServiceError


class AssignmentDraftDetailDialog:
    """Displays an AI draft only; Planner KPI owns all Office edits and decisions."""

    def __init__(self, parent, service: AssignmentDraftService, tenant_id: str, draft_id: str, on_changed,
                 planner_url: str = "", planner_token: str = "") -> None:
        self.service = service
        self.tenant_id = tenant_id
        self.draft_id = draft_id
        self.on_changed = on_changed
        self.planner_url = planner_url
        self.planner_token = planner_token
        self.window = ctk.CTkToplevel(parent)
        self.window.title("Chi tiet du thao AI")
        self.window.geometry("760x620")

    def show(self) -> None:
        draft = self.service.get_draft_detail(self.tenant_id, self.draft_id)
        if not draft:
            raise AssignmentDraftServiceError("Khong tim thay du thao")
        body = ctk.CTkTextbox(self.window)
        body.pack(fill="both", expand=True, padx=16, pady=16)
        people = "\n".join(f"- {item.role_type}: {item.personnel_source_key}" for item in draft.personnel) or "Chua de xuat"
        warnings = "\n".join(f"- {item.get('code', '')}" for item in draft.warnings) or "Khong co"
        body.insert(
            "1.0",
            f"Van ban: {draft.source_document_id}\nDraft ID: {draft.id}\nPhien ban: {draft.draft_version}\n"
            f"Trang thai gui Planner: {planner_display_status(draft.current_status)}\n\n{draft.task_title}\n\n"
            f"{draft.task_description}\n\nDon vi AI de xuat: {draft.lead_unit_source_key or ''}\n"
            f"Bat dau: {draft.proposed_start_date or ''}\nThoi han: {draft.proposed_due_date or ''}\n"
            f"Uu tien: {draft.priority}\nMuc tin cay: {draft.overall_confidence}\n\nSan pham:\n"
            + "\n".join(draft.deliverables) + "\n\nChecklist:\n" + "\n".join(draft.checklist_items)
            + "\n\nMoc:\n" + "\n".join(draft.milestones) + f"\n\nNhan su AI de xuat:\n{people}\n\nCanh bao:\n{warnings}",
        )
        body.configure(state="disabled")
        controls = ctk.CTkFrame(self.window)
        controls.pack(fill="x", padx=16, pady=(0, 16))
        ctk.CTkButton(
            controls, text="Gui du thao sang Planner KPI", command=lambda: self.prepare_planner_handoff(draft),
            state="normal" if draft.current_status == PENDING_OFFICE_REVIEW else "disabled",
        ).pack(side="left", padx=6, pady=8)

    def prepare_planner_handoff(self, draft) -> None:
        if not planner_handoff_configured(self.planner_url, self.planner_token):
            messagebox.showwarning("Planner KPI", "Chua cau hinh ket noi Planner KPI", parent=self.window)
            return
        handoff = build_planner_handoff(draft)
        messagebox.showinfo(
            "Planner KPI",
            f"Payload draft da san sang cho Planner KPI. Idempotency key: {handoff.idempotency_key}",
            parent=self.window,
        )
