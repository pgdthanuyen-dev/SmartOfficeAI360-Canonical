"""Read-only SmartOffice view of AI assignment drafts before Planner handoff."""

from __future__ import annotations

import webbrowser
from tkinter import messagebox

import customtkinter as ctk

from .assignment_draft_planner_handoff import (
    PENDING_OFFICE_REVIEW,
    planner_display_status,
)
from .assignment_draft_service import AssignmentDraftService, AssignmentDraftServiceError
from .planner_draft_handoff_client import PlannerHandoffOutcome


class AssignmentDraftDetailDialog:
    """Displays an AI draft only; Planner KPI owns all Office edits and decisions."""

    def __init__(self, parent, service: AssignmentDraftService, tenant_id: str, draft_id: str, on_changed) -> None:
        self.service = service
        self.tenant_id = tenant_id
        self.draft_id = draft_id
        self.on_changed = on_changed
        self.send_button = None
        self.handoff_status_label = None
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
            f"Trang thai gui Planner: {planner_display_status(draft.planner_handoff_status)}\n"
            f"Planner draft: {draft.planner_draft_id or ''}\n\n{draft.task_title}\n\n"
            f"{draft.task_description}\n\nDon vi AI de xuat: {draft.lead_unit_source_key or ''}\n"
            f"Bat dau: {draft.proposed_start_date or ''}\nThoi han: {draft.proposed_due_date or ''}\n"
            f"Uu tien: {draft.priority}\nMuc tin cay: {draft.overall_confidence}\n\nSan pham:\n"
            + "\n".join(draft.deliverables) + "\n\nChecklist:\n" + "\n".join(draft.checklist_items)
            + "\n\nMoc:\n" + "\n".join(draft.milestones) + f"\n\nNhan su AI de xuat:\n{people}\n\nCanh bao:\n{warnings}",
        )
        body.configure(state="disabled")
        controls = ctk.CTkFrame(self.window)
        controls.pack(fill="x", padx=16, pady=(0, 16))
        self.send_button = ctk.CTkButton(
            controls, text="Gui du thao sang Planner KPI", command=self.send_to_planner,
            state="normal" if draft.current_status == PENDING_OFFICE_REVIEW and draft.planner_handoff_status != "SENT" else "disabled",
        )
        self.send_button.pack(side="left", padx=6, pady=8)
        self.handoff_status_label = ctk.CTkLabel(controls, text="")
        self.handoff_status_label.pack(side="left", padx=6, pady=8)
        if draft.planner_handoff_status == "SENT":
            self.handoff_status_label.configure(text="Da gui Planner KPI")
            planner_draft_url = self.service.planner_draft_url(draft.planner_draft_id)
            if planner_draft_url:
                ctk.CTkButton(self.window, text="Mo tren Planner KPI", command=lambda: webbrowser.open(planner_draft_url)).pack(pady=(0, 12))
        elif draft.planner_handoff_error:
            self.handoff_status_label.configure(text=draft.planner_handoff_error)

    def send_to_planner(self) -> None:
        if self.send_button is None:
            return
        self.send_button.configure(state="disabled", text="Dang gui...")
        if self.handoff_status_label is not None:
            self.handoff_status_label.configure(text="Dang gui du thao sang Planner KPI")
        self.window.update_idletasks()
        try:
            result = self.service.send_draft_to_planner(self.tenant_id, self.draft_id)
        except AssignmentDraftServiceError as exc:
            self._show_handoff_error(str(exc))
            return
        if result.outcome is PlannerHandoffOutcome.CREATED:
            self._show_handoff_success("Da tao du thao tren Planner KPI", result.planner_draft_url)
        elif result.outcome is PlannerHandoffOutcome.DUPLICATE:
            self._show_handoff_success("Du thao da ton tai tren Planner KPI", result.planner_draft_url)
        else:
            messages = {
                PlannerHandoffOutcome.VALIDATION_ERROR: "Planner tu choi du lieu du thao.",
                PlannerHandoffOutcome.AUTH_ERROR: "Xac thuc Planner KPI khong thanh cong.",
                PlannerHandoffOutcome.PLANNER_UNAVAILABLE: "Planner KPI chua san sang hoac chua duoc cau hinh.",
                PlannerHandoffOutcome.UNKNOWN_RESULT: "Chua xac dinh ket qua gui. Hay thu lai thu cong.",
                PlannerHandoffOutcome.LOCAL_PERSISTENCE_ERROR: "Planner da phan hoi nhung SmartOffice chua luu duoc ket qua.",
            }
            self._show_handoff_error(messages.get(result.outcome, "Khong the gui du thao."))

    def _show_handoff_success(self, message: str, planner_draft_url: str | None) -> None:
        if self.handoff_status_label is not None:
            self.handoff_status_label.configure(text=message)
        if self.send_button is not None:
            self.send_button.configure(text="Da gui Planner", state="disabled")
        if planner_draft_url:
            ctk.CTkButton(self.window, text="Mo tren Planner KPI", command=lambda: webbrowser.open(planner_draft_url)).pack(pady=(0, 12))
        self.on_changed()

    def _show_handoff_error(self, message: str) -> None:
        if self.handoff_status_label is not None:
            self.handoff_status_label.configure(text=message)
        if self.send_button is not None:
            self.send_button.configure(text="Gui du thao sang Planner KPI", state="normal")
        messagebox.showwarning("Planner KPI", message, parent=self.window)
