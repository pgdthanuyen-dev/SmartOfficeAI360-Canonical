from __future__ import annotations

import re
import os
import tempfile
import time
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from .config import QLVBConfig
from .neoremoting import (
    NeoRemotingDiscoveryError,
    build_legacy_download_url,
    extract_document_id,
    parse_attachment_response,
)


CDP_ENDPOINT = "http://127.0.0.1:9223"
QLVB_HOST = "qlvb.laichau.gov.vn"
QLVB_PATH_PREFIX = "/qlvbdh_lcu/"
QLVB_MAIN_PATH = "/qlvbdh_lcu/main"
MAX_ROWS_PER_CATEGORY = 10
POST_CLICK_TIMEOUT_SECONDS = 20.0

MENU_GROUP = "\u0051\u0075\u1ea3\u006e\u0020\u006c\u00fd\u0020\u0076\u0103\u006e\u0020\u0062\u1ea3\u006e\u0020\u0111\u1ebf\u006e"
CATEGORY_INCOMING_REGISTRY = "\u0056\u0103\u006e\u0020\u0062\u1ea3\u006e\u0020\u0076\u00e0\u006f\u0020\u0073\u1ed5"
CATEGORY_FORWARDED_PROCESSED = "\u0110\u00e3\u0020\u0063\u0068\u0075\u0079\u1ec3\u006e\u0020\u0078\u1eed\u0020\u006c\u00fd"
CATEGORY_PROCESSED = "\u0110\u00e3\u0020\u0078\u1eed\u0020\u006c\u00fd"
MOJIBAKE_MARKERS = ("\u00c3", "\u00c4", "\u00c2", "\u00e1\u00ba", "\u00e1\u00bb")


@dataclass(frozen=True)
class CdpCategory:
    index: int
    label: str
    slug: str


@dataclass(frozen=True)
class DownloadResult:
    http_status: int
    content_type: str
    body_length: int
    signature: str
    integrity: str
    session_expired: bool
    persisted: bool
    failure_code: str = ""
    final_path: Path | None = None


CATEGORY_ORDER: tuple[CdpCategory, ...] = (
    CdpCategory(1, CATEGORY_INCOMING_REGISTRY, "01-van-ban-vao-so"),
    CdpCategory(2, CATEGORY_FORWARDED_PROCESSED, "02-da-chuyen-xu-ly"),
    CdpCategory(3, CATEGORY_PROCESSED, "03-da-xu-ly"),
)


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.replace("\u0111", "d").replace("\u0110", "D").casefold().split())


def safe_log(value: object, limit: int = 500) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ")[:limit]


def label_mojibake_detected(value: object) -> bool:
    text = str(value or "")
    return any(marker in text for marker in MOJIBAKE_MARKERS)


def validate_category_labels(labels: list[str] | None = None) -> None:
    checked = labels if labels is not None else [MENU_GROUP, *(item.label for item in CATEGORY_ORDER)]
    if any(label_mojibake_detected(label) for label in checked):
        raise RuntimeError("CATEGORY_LABEL_MOJIBAKE_DETECTED")


def safe_filename(name: object) -> str:
    normalized = unicodedata.normalize("NFC", str(name or "")).strip()
    normalized = normalized.replace("\\", "_").replace("/", "_")
    normalized = re.sub(r'[<>:"|?*\x00-\x1f]+', "_", normalized).strip(" .")
    return (normalized if normalized and normalized not in {".", ".."} else "attachment.bin")[:180]


def _url_parts(page: Any) -> tuple[str, str]:
    parsed = urlsplit(str(getattr(page, "url", "") or ""))
    return parsed.hostname or "", parsed.path or "/"


def collect_pages(browser: Any) -> list[Any]:
    pages: list[Any] = []
    for context in list(getattr(browser, "contexts", []) or []):
        pages.extend(list(getattr(context, "pages", []) or []))
    return pages


def find_qlvb_page(browser: Any) -> Any | None:
    candidates: list[tuple[int, Any]] = []
    for page in collect_pages(browser):
        try:
            if page.is_closed():
                continue
            host, path = _url_parts(page)
            if host != QLVB_HOST or not path.startswith(QLVB_PATH_PREFIX):
                continue
            score = 10 if path == QLVB_MAIN_PATH else 1
            try:
                score += 1 if str(page.title() or "").strip() else 0
            except Exception:
                pass
            candidates.append((score, page))
        except Exception:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def validation_frames(page: Any) -> list[Any]:
    frames = list(getattr(page, "frames", []) or [])
    main = getattr(page, "main_frame", None) or (frames[0] if frames else page)
    ordered = [main]
    for frame in frames:
        if frame not in ordered:
            ordered.append(frame)
    return ordered


def _norm_js() -> str:
    return r"""
        const normalize = (value) => String(value || '')
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '')
            .replace(/\u0111/g, 'd')
            .replace(/\u0110/g, 'D')
            .toLowerCase()
            .replace(/\s+/g, ' ')
            .trim();
        const stripCount = (value) => normalize(value).replace(/\s*\(\s*\d+\s*\)\s*$/g, '').trim();
    """


CATEGORY_STATE_SCRIPT = "({label}) => {\n" + _norm_js() + r"""
    const expected = stripCount(label);
    const titleOk = stripCount(document.title || '') === expected;
    const breadcrumbText = normalize(Array.from(document.querySelectorAll('.breadcrumb, .page-breadcrumb, [aria-label*="breadcrumb" i]')).map(el => el.innerText || el.textContent || '').join(' / '));
    const activeText = normalize(Array.from(document.querySelectorAll('[aria-current="page"], .active, .selected, .current')).map(el => el.innerText || el.textContent || '').join(' / '));
    const bodyText = normalize(document.body ? (document.body.innerText || document.body.textContent || '') : '');
    const emptyState = bodyText.includes('khong tim thay du lieu') || bodyText.includes('khong co du lieu') || bodyText.includes('khong co ban ghi') || bodyText.includes('no data available');
    return {
        title: titleOk,
        breadcrumb: breadcrumbText.includes('quan ly van ban den') && breadcrumbText.includes(expected),
        activeMenu: activeText.includes(expected) && !activeText.includes('thong tin xu ly van ban'),
        emptyState,
    };
}"""


TABLE_VALIDATOR_SCRIPT = "(() => {\n" + _norm_js() + r"""
    const rectOk = (el) => {
        const rect = el && el.getBoundingClientRect ? el.getBoundingClientRect() : {width: 0, height: 0};
        return rect.width > 0 && rect.height > 0;
    };
    const hiddenByAncestor = (el) => {
        for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
            const tag = String(node.tagName || '').toLowerCase();
            if (tag === 'template') return true;
            if (node.getAttribute('aria-hidden') === 'true' || node.hidden) return true;
            const style = window.getComputedStyle(node);
            if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return true;
        }
        return false;
    };
    const visible = (el) => {
        if (!el || !el.isConnected || hiddenByAncestor(el)) return false;
        const style = window.getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden' && rectOk(el);
    };
    const inModalDialogOrTemplate = (el) => !!el.closest('.modal, .popup, [role="dialog"], [aria-modal="true"], .ui-dialog, template');
    const inMainContent = (el) => !!el.closest('#div_data_list, main, #content, #main-content, .main-content, .content-wrapper, .page-content, body');
    const cellText = (cell) => normalize(cell.innerText || cell.textContent || cell.getAttribute('aria-label') || cell.getAttribute('data-title') || '');
    const visibleHeaders = (table) => Array.from(table.querySelectorAll('thead th, tr:first-child th')).filter(th => visible(th)).map(cellText).filter(Boolean);
    const visibleRows = (table) => {
        let rows = Array.from(table.querySelectorAll('tbody tr'));
        if (rows.length === 0) rows = Array.from(table.querySelectorAll('tr')).slice(1);
        return rows.filter(row => {
            if (!visible(row)) return false;
            const text = normalize(row.innerText || row.textContent || '');
            if (!text || text.includes('khong co du lieu') || text.includes('khong tim thay du lieu') || text.includes('no data available')) return false;
            if (text.includes('truoc') && text.includes('sau') && text.includes('trang')) return false;
            return Array.from(row.querySelectorAll('td, [role="cell"]')).filter(cell => visible(cell)).length > 0;
        });
    };
    const rawTables = Array.from(document.querySelectorAll('table'));
    const scored = [];
    for (const table of rawTables.filter(t => visible(t) && !inModalDialogOrTemplate(t) && inMainContent(t))) {
        const headers = Array.from(new Set(visibleHeaders(table)));
        const hasSoKyHieu = headers.includes('so ky hieu');
        const hasTrichYeu = headers.includes('trich yeu');
        const hasFiles = headers.includes('files');
        const hasDateOrUnit = headers.includes('ngay van ban') || headers.includes('ngay den') || headers.includes('don vi ban hanh');
        const rows = visibleRows(table);
        let score = 0;
        if (table.closest('#div_data_list')) score += 4;
        if (hasSoKyHieu) score += 3;
        if (hasTrichYeu) score += 3;
        if (hasFiles) score += 2;
        if (hasDateOrUnit) score += 1;
        if (rows.length > 0) score += 1;
        const valid = hasSoKyHieu && hasTrichYeu && (hasFiles || hasDateOrUnit);
        scored.push({table, rowCount: rows.length, score, valid});
    }
    scored.sort((a, b) => b.score - a.score);
    const selected = scored[0] || null;
    window.__qlvb_cdp_selected_table = selected && selected.valid ? selected.table : null;
    return {
        validated: !!(selected && selected.valid),
        visibleRowCount: selected ? selected.rowCount : 0,
        rawTableCount: rawTables.length,
        visibleTableCount: rawTables.filter(visible).length,
    };
})()
"""


LOADING_STATE_SCRIPT = "(() => {\n" + _norm_js() + r"""
    const visible = (el) => {
        if (!el || !el.isConnected) return false;
        const r = el.getBoundingClientRect ? el.getBoundingClientRect() : {width: 0, height: 0};
        const style = window.getComputedStyle(el);
        return r.width > 0 && r.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
    };
    const selectors = ['.loading', '.spinner', '.overlay', '.blockUI', '.ajax-loading', '.modal-backdrop', '[class*="loading" i]', '[id*="loading" i]', '[class*="spinner" i]'];
    const loadingVisible = selectors.some(selector => Array.from(document.querySelectorAll(selector)).some(visible));
    const bodyTextLength = document.body ? (document.body.innerText || document.body.textContent || '').length : 0;
    const rawTables = Array.from(document.querySelectorAll('table'));
    return {loadingVisible, bodyTextLength, tableCount: rawTables.length, visibleTableCount: rawTables.filter(visible).length};
})()
"""


MENU_NAV_SCRIPT = "async ({label, groupLabel}) => {\n" + _norm_js() + r"""
    const expected = stripCount(label);
    const expectedGroup = stripCount(groupLabel);
    const rectOk = (el) => { const r = el && el.getBoundingClientRect ? el.getBoundingClientRect() : {width:0,height:0}; return r.width > 0 && r.height > 0; };
    const hiddenByAncestor = (el) => {
        for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
            const tag = String(node.tagName || '').toLowerCase();
            if (tag === 'template') return true;
            if (node.getAttribute('aria-hidden') === 'true' || node.hidden) return true;
            const s = window.getComputedStyle(node);
            if (s.display === 'none' || s.visibility === 'hidden' || Number(s.opacity) === 0) return true;
        }
        return false;
    };
    const visible = (el) => {
        if (!el || !el.isConnected || !rectOk(el) || hiddenByAncestor(el)) return false;
        const s = window.getComputedStyle(el);
        return s.display !== 'none' && s.visibility !== 'hidden';
    };
    const inExcluded = (el) => !!el.closest('main, #content, #main-content, .main-content, .modal, .popup, [role="dialog"], table, tr, td, th, template');
    const isNav = (el) => {
        const tag = String(el.tagName || '').toLowerCase();
        return tag === 'a' || tag === 'button' || el.getAttribute('role') === 'menuitem' || !!el.getAttribute('href') || !!el.getAttribute('onclick') || !!el.getAttribute('data-url') || !!el.getAttribute('data-href') || !!el.getAttribute('data-link');
    };
    const actionableFrom = (node, boundary) => {
        for (let cur = node; cur && cur !== boundary.parentElement; cur = cur.parentElement) {
            if (cur === boundary) continue;
            if (isNav(cur) && visible(cur) && !inExcluded(cur)) return cur;
        }
        return isNav(node) ? node : null;
    };
    const roots = Array.from(document.querySelectorAll('#full_menu, nav, aside, .sidebar, .main-sidebar, .side-menu, .nav-menu, ul[role="menu"]')).filter(el => visible(el) && !inExcluded(el));
    let group = null;
    let header = null;
    for (const root of roots) {
        const candidates = Array.from(root.querySelectorAll('li, [role="group"]'));
        for (const candidate of candidates) {
            if (inExcluded(candidate)) continue;
            const h = Array.from(candidate.querySelectorAll(':scope > a, :scope > button, :scope > span, :scope > div, :scope > [role="menuitem"], :scope > [onclick]')).find(el => stripCount(el.innerText || el.textContent || '') === expectedGroup && visible(el));
            if (h) { group = candidate; header = actionableFrom(h, candidate) || h; break; }
        }
        if (group) break;
    }
    const submenuCandidates = () => {
        if (!group) return [];
        const matches = [];
        for (const node of Array.from(group.querySelectorAll('a, button, span, div, li, [role="menuitem"], [onclick], [href], [data-url], [data-href], [data-link]'))) {
            if (node === group || inExcluded(node) || stripCount(node.innerText || node.textContent || '') !== expected || !visible(node)) continue;
            const action = actionableFrom(node, group);
            if (action && isNav(action) && visible(action) && group.contains(action)) matches.push(action);
        }
        return Array.from(new Set(matches));
    };
    const groupFound = !!(group && header);
    const expandedBefore = submenuCandidates().length > 0;
    let clickedToExpand = false;
    if (groupFound && !expandedBefore) {
        header.click();
        clickedToExpand = true;
        await new Promise(resolve => setTimeout(resolve, 900));
    }
    const candidatesAfter = submenuCandidates();
    const submenuVisibleAfter = candidatesAfter.length > 0;
    if (!groupFound) return {clicked: false, state: 'MENU_GROUP_NOT_FOUND', menu_group_found: false, menu_group_expanded_before: false, menu_group_clicked_to_expand: false, submenu_visible_after_expand: false, submenu_candidate_count: 0};
    if (candidatesAfter.length !== 1) return {clicked: false, state: 'MENU_TARGET_NOT_UNIQUE', menu_group_found: true, menu_group_expanded_before: expandedBefore, menu_group_clicked_to_expand: clickedToExpand, submenu_visible_after_expand: submenuVisibleAfter, submenu_candidate_count: candidatesAfter.length};
    candidatesAfter[0].click();
    return {clicked: true, state: 'CLICKED', menu_group_found: true, menu_group_expanded_before: expandedBefore, menu_group_clicked_to_expand: clickedToExpand, submenu_visible_after_expand: submenuVisibleAfter, submenu_candidate_count: 1};
}"""


ROW_DISCOVERY_SCRIPT = r"""({maxRows}) => {
    const table = window.__qlvb_cdp_selected_table;
    if (!table) return {rowCount: 0, rows: []};
    const rectOk = (el) => { const r = el && el.getBoundingClientRect ? el.getBoundingClientRect() : {width:0,height:0}; return r.width > 0 && r.height > 0; };
    const visible = (el) => { if (!el || !el.isConnected || !rectOk(el)) return false; const s = window.getComputedStyle(el); return s.display !== 'none' && s.visibility !== 'hidden'; };
    let rows = Array.from(table.querySelectorAll('tbody tr'));
    if (rows.length === 0) rows = Array.from(table.querySelectorAll('tr')).slice(1);
    rows = rows.filter(row => visible(row) && Array.from(row.querySelectorAll('td, [role="cell"]')).filter(cell => visible(cell)).length > 0);
    const attrs = (el) => {
        const out = {};
        for (const name of ['data-document-id','data-doc-id','data-vb-id','data-id','data-url','data-href','data-link']) {
            const value = el.getAttribute && el.getAttribute(name);
            if (value) out[name] = value;
        }
        return out;
    };
    return {rowCount: rows.length, rows: rows.slice(0, maxRows).map(row => ({
        rowId: row.id || '',
        attributes: attrs(row),
        onclick: row.getAttribute('onclick') || '',
        href: row.getAttribute('href') || '',
        actions: Array.from(row.querySelectorAll('a, button, [onclick], [href], [data-document-id], [data-doc-id], [data-vb-id], [data-id], [data-url], [data-href], [data-link]')).slice(0, 64).map(el => ({attributes: attrs(el), onclick: el.getAttribute('onclick') || '', href: el.getAttribute('href') || ''}))
    }))};
}"""


NEOREMOTING_SCRIPT = r"""async ({documentId, timeoutMs}) => {
    const scopes = [window, ...Array.from(window.frames || [])];
    for (let index = 0; index < scopes.length; index += 1) {
        let neo = null;
        try { neo = scopes[index].NEORemoting; } catch (_) { neo = null; }
        const neoType = typeof neo;
        const getRSetType = typeof (neo && neo.getRSet);
        if (!neo || !['object', 'function'].includes(neoType) || getRSetType !== 'function') continue;
        const operation = 'qlvb.van_ban_den.getFileAttachLst("' + documentId + '",0)';
        return await new Promise(resolve => {
            let settled = false;
            const timer = window.setTimeout(() => { if (!settled) { settled = true; resolve({state: 'NEOREMOTING_CALLBACK_TIMEOUT'}); } }, timeoutMs);
            try {
                neo.getRSet.call(neo, operation, function(data) {
                    if (settled) return;
                    settled = true;
                    window.clearTimeout(timer);
                    let raw = '';
                    if (typeof data === 'string') raw = data;
                    else if (Array.isArray(data) || (data && typeof data === 'object')) { try { raw = JSON.stringify(data); } catch (_) { raw = ''; } }
                    const shape = {
                        callbackArgCount: arguments.length,
                        resultType: typeof data,
                        isArray: Array.isArray(data),
                        stringLength: typeof data === 'string' ? data.length : null,
                        arrayLength: Array.isArray(data) ? data.length : null,
                        topLevelKeys: data && typeof data === 'object' && !Array.isArray(data) ? Object.keys(data).slice(0, 32) : [],
                        firstItemKeys: Array.isArray(data) && data[0] && typeof data[0] === 'object' ? Object.keys(data[0]).slice(0, 32) : []
                    };
                    resolve({state: 'SUCCESS', raw, shape});
                });
            } catch (_) {
                if (!settled) { settled = true; window.clearTimeout(timer); resolve({state: 'NEOREMOTING_SYNCHRONOUS_EXCEPTION'}); }
            }
        });
    }
    return {state: 'NEOREMOTING_OBJECT_NOT_AVAILABLE'};
}"""


def category_state(page: Any, label: str) -> dict[str, bool]:
    state = {"title": False, "breadcrumb": False, "activeMenu": False, "emptyState": False}
    for frame in validation_frames(page):
        try:
            data = frame.evaluate(CATEGORY_STATE_SCRIPT, {"label": label})
        except Exception:
            continue
        if isinstance(data, dict):
            for key in state:
                state[key] = state[key] or bool(data.get(key))
    return state


def route_match_for_category(page: Any, label: str) -> bool:
    try:
        title = normalize_text(page.title())
    except Exception:
        title = ""
    return normalize_text(label) == title


def loading_snapshot(page: Any) -> dict[str, Any]:
    aggregate = {"loadingVisible": False, "bodyTextLength": 0, "tableCount": 0, "visibleTableCount": 0}
    for frame in validation_frames(page):
        try:
            data = frame.evaluate(LOADING_STATE_SCRIPT)
        except Exception:
            continue
        if isinstance(data, dict):
            aggregate["loadingVisible"] = bool(aggregate["loadingVisible"] or data.get("loadingVisible"))
            aggregate["bodyTextLength"] = max(int(aggregate["bodyTextLength"]), int(data.get("bodyTextLength", 0) or 0))
            aggregate["tableCount"] += int(data.get("tableCount", 0) or 0)
            aggregate["visibleTableCount"] += int(data.get("visibleTableCount", 0) or 0)
    return aggregate


def table_validation(page: Any) -> tuple[Any | None, dict[str, Any]]:
    best_diag: dict[str, Any] = {"validated": False, "visibleRowCount": 0, "frameIndex": -1}
    for idx, frame in enumerate(validation_frames(page)):
        try:
            diag = frame.evaluate(TABLE_VALIDATOR_SCRIPT)
        except Exception:
            continue
        if isinstance(diag, dict) and diag.get("validated"):
            diag["frameIndex"] = idx
            return frame, diag
        if isinstance(diag, dict) and int(diag.get("visibleTableCount", 0) or 0) > int(best_diag.get("visibleTableCount", 0) or 0):
            best_diag = dict(diag)
            best_diag["frameIndex"] = idx
    return None, best_diag


def ensure_category(page: Any, category: CdpCategory) -> tuple[str, dict[str, str]]:
    state = category_state(page, category.label)
    if state["title"] or (state["breadcrumb"] and state["activeMenu"]):
        return "SKIPPED_ALREADY_ON_TARGET", {
            "menu_group_found": "NOT_REQUIRED",
            "menu_group_expanded_before": "NOT_REQUIRED",
            "menu_group_clicked_to_expand": "NO",
            "submenu_visible_after_expand": "NOT_REQUIRED",
            "submenu_candidate_count": "NOT_REQUIRED",
            "category_menu_clicked": "SKIPPED_ALREADY_ON_TARGET",
        }
    result: dict[str, Any] | None = None
    for frame in validation_frames(page):
        result = frame.evaluate(MENU_NAV_SCRIPT, {"label": category.label, "groupLabel": MENU_GROUP})
        if isinstance(result, dict) and result.get("clicked"):
            break
    if not result or not result.get("clicked"):
        raise RuntimeError("CATEGORY_MENU_CLICK_FAILED")
    return "CLICKED", {
        "menu_group_found": "YES" if result.get("menu_group_found") else "NO",
        "menu_group_expanded_before": "YES" if result.get("menu_group_expanded_before") else "NO",
        "menu_group_clicked_to_expand": "YES" if result.get("menu_group_clicked_to_expand") else "NO",
        "submenu_visible_after_expand": "YES" if result.get("submenu_visible_after_expand") else "NO",
        "submenu_candidate_count": str(result.get("submenu_candidate_count", 0)),
        "category_menu_clicked": "YES",
    }


def poll_category_target_state(browser: Any, page: Any, label: str, timeout_seconds: float = POST_CLICK_TIMEOUT_SECONDS) -> dict[str, Any]:
    started = time.monotonic()
    final: dict[str, Any] = {"targetReached": False, "page": page, "table_frame": None, "visible_rows": 0}
    page_count_max = 0
    poll_count = 0
    while time.monotonic() - started < timeout_seconds:
        poll_count += 1
        candidates = collect_pages(browser)
        page_count_max = max(page_count_max, len(candidates))
        for candidate in candidates:
            try:
                if candidate.is_closed():
                    continue
                host, path = _url_parts(candidate)
                if host != QLVB_HOST or not path.startswith(QLVB_PATH_PREFIX):
                    continue
                page = candidate
                break
            except Exception:
                continue
        state = category_state(page, label)
        loading = loading_snapshot(page)
        table_frame, table_diag = table_validation(page)
        empty = bool(state.get("emptyState"))
        primary = bool(table_frame) or empty
        secondary = bool(state.get("title") or state.get("breadcrumb") or state.get("activeMenu") or route_match_for_category(page, label))
        loading_visible = bool(loading.get("loadingVisible")) or int(loading.get("bodyTextLength", 0) or 0) == 0
        reached = primary and secondary and not loading_visible
        final.update({
            "page": page,
            "table_frame": table_frame,
            "visible_rows": int(table_diag.get("visibleRowCount", 0) or 0),
            "empty": empty,
            "title": bool(state.get("title")),
            "breadcrumb": bool(state.get("breadcrumb")),
            "activeMenu": bool(state.get("activeMenu")),
            "route": route_match_for_category(page, label),
            "table": bool(table_frame),
            "frameCount": len(validation_frames(page)),
            "durationMs": int((time.monotonic() - started) * 1000),
            "pollCount": poll_count,
            "pageCountMax": page_count_max,
            "targetReached": reached,
        })
        if reached:
            return final
        time.sleep(0.4)
    return final


def extract_id_from_row(row: dict[str, Any]) -> str:
    candidates = [(row.get("attributes") or {}, row.get("rowId", ""), row.get("onclick", ""), row.get("href", ""))]
    for action in row.get("actions", []) or []:
        candidates.append((action.get("attributes") or {}, "", action.get("onclick", ""), action.get("href", "")))
    for attributes, row_id, onclick, href in candidates:
        extracted = extract_document_id(attributes=attributes, row_id=row_id, onclick=onclick, href=href)
        if extracted:
            return extracted.document_id
    return ""


def discover_attachment(page: Any, table_frame: Any, max_rows: int = MAX_ROWS_PER_CATEGORY) -> tuple[int, bool, list[dict[str, str]], dict[str, str]]:
    payload = table_frame.evaluate(ROW_DISCOVERY_SCRIPT, {"maxRows": max_rows})
    rows = list((payload or {}).get("rows") or [])
    for checked, row in enumerate(rows, start=1):
        document_id = extract_id_from_row(row)
        if not document_id:
            continue
        result = page.evaluate(NEOREMOTING_SCRIPT, {"documentId": document_id, "timeoutMs": 15000})
        if not isinstance(result, dict) or result.get("state") != "SUCCESS":
            continue
        try:
            attachments = parse_attachment_response(result.get("raw"))
        except NeoRemotingDiscoveryError:
            continue
        if attachments:
            return checked, True, attachments, attachments[0]
    return min(len(rows), max_rows), False, [], {}


def detect_login_html(body: bytes, content_type: str) -> bool:
    head = body[:4096].decode("utf-8", errors="ignore").lower()
    return (
        "text/html" in content_type.lower()
        and ("<html" in head or "password" in head or "dang nhap" in normalize_text(head))
    ) or ("password" in head and "input" in head)


def body_signature(body: bytes) -> str:
    if body.startswith(b"%PDF"):
        return "PDF"
    if body.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "ZIP"
    if body.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "OLE"
    return "UNKNOWN"


def validate_integrity(path: Path, body: bytes, signature: str) -> str:
    if not path.exists() or path.stat().st_size != len(body) or not body:
        return "FAIL"
    if signature == "PDF":
        return "PASS" if body.startswith(b"%PDF") and b"%%EOF" in body[-4096:] else "FAIL"
    if signature == "ZIP":
        try:
            with zipfile.ZipFile(path, "r") as archive:
                return "PASS" if archive.testzip() is None else "FAIL"
        except zipfile.BadZipFile:
            return "FAIL"
    if signature == "OLE":
        return "PASS" if body.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1") else "FAIL"
    return "FAIL"


def _safe_final_path(category_dir: Path, attachment_name: object) -> Path:
    directory = category_dir.resolve()
    candidate = (directory / safe_filename(attachment_name)).resolve()
    if candidate.parent != directory:
        raise RuntimeError("DOWNLOAD_PATH_OUTSIDE_OUTPUT_DIRECTORY")
    if not candidate.exists():
        return candidate
    suffix = candidate.suffix
    stem = candidate.stem or "attachment"
    for index in range(1, 10000):
        alternative = (directory / f"{stem}-{index}{suffix}").resolve()
        if alternative.parent == directory and not alternative.exists():
            return alternative
    raise RuntimeError("DOWNLOAD_OUTPUT_NAME_EXHAUSTED")


def download_one(page: Any, category_dir: Path, attachment: dict[str, str]) -> DownloadResult:
    url = build_legacy_download_url(str(page.url), attachment["name"], attachment["hdd_file"], attachment.get("type", "vb"))
    response = page.context.request.get(url, timeout=30000)
    body = response.body()
    content_type = str(response.headers.get("content-type", ""))
    status = int(response.status)
    login_html = detect_login_html(body, content_type) or "login" in str(response.url).lower()
    session_expired = status in {401, 403} or login_html
    if status in {401, 403}:
        return DownloadResult(status, content_type, len(body), "UNKNOWN", "FAIL", True, False, "SESSION_EXPIRED")
    if status != 200:
        return DownloadResult(status, content_type, len(body), "UNKNOWN", "FAIL", False, False, "HTTP_DOWNLOAD_FAILED")
    if not body:
        return DownloadResult(status, content_type, 0, "UNKNOWN", "FAIL", session_expired, False, "EMPTY_RESPONSE_BODY")
    if login_html:
        return DownloadResult(status, content_type, len(body), "UNKNOWN", "FAIL", True, False, "LOGIN_HTML_DETECTED")
    signature = body_signature(body)
    if signature == "UNKNOWN":
        return DownloadResult(status, content_type, len(body), signature, "FAIL", False, False, "UNSUPPORTED_OR_UNKNOWN_FILE_SIGNATURE")

    category_dir.mkdir(parents=True, exist_ok=True)
    final_path = _safe_final_path(category_dir, attachment["name"])
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=f".{final_path.name}.part-", dir=category_dir, delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        integrity = validate_integrity(temp_path, body, signature)
        if integrity != "PASS":
            return DownloadResult(status, content_type, len(body), signature, integrity, False, False, "INTEGRITY_CHECK_FAILED")
        os.replace(temp_path, final_path)
        temp_path = None
        return DownloadResult(status, content_type, len(body), signature, integrity, False, True, "", final_path)
    except OSError:
        return DownloadResult(status, content_type, len(body), signature, "FAIL", False, False, "ATOMIC_PERSISTENCE_FAILED")
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def default_output_dir(config: QLVBConfig) -> Path:
    return config.root_path / "qlvb_cdp_three_category_smoke" / datetime.now().strftime("%Y%m%d-%H%M%S")


def run_cdp_three_category_smoke(
    config: QLVBConfig,
    *,
    output_dir: Path | None = None,
    endpoint: str = CDP_ENDPOINT,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    validate_category_labels()
    target_dir = output_dir or default_output_dir(config)
    target_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "PRECHECK": "PASS",
        "CDP_CONNECTION": "FAIL",
        "CATEGORY_TOTAL": 3,
        "CATEGORY_VALIDATED_COUNT": 0,
        "CATEGORY_EMPTY_COUNT": 0,
        "CATEGORY_DOWNLOAD_COUNT": 0,
        "DOWNLOAD_HTTP_200_COUNT": 0,
        "FILE_INTEGRITY_PASS_COUNT": 0,
        "SESSION_EXPIRED": "NO",
        "OUTPUT_DIRECTORY": str(target_dir),
        "LIVE_ACCEPTANCE": "FAIL",
        "BLOCKED_WITH_EXACT_ERROR": "NONE",
    }
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.connect_over_cdp(endpoint)
            except Exception as exc:
                raise RuntimeError("QLVB_CDP_CONNECTION_FAILED") from exc
            summary["CDP_CONNECTION"] = "PASS"
            page = find_qlvb_page(browser)
            if page is None:
                raise RuntimeError("QLVB_CDP_SOURCE_PAGE_NOT_FOUND")
            for category in CATEGORY_ORDER:
                category_dir = target_dir / category.slug
                category_dir.mkdir(parents=True, exist_ok=True)
                navigation, menu_diag = ensure_category(page, category)
                post_click = poll_category_target_state(browser, page, category.label)
                page = post_click["page"]
                category_ok = bool(post_click.get("targetReached"))
                if not category_ok:
                    raise RuntimeError(f"CATEGORY_{category.index}_POST_CLICK_TARGET_STATE_TIMEOUT")
                summary["CATEGORY_VALIDATED_COUNT"] += 1
                if post_click.get("empty"):
                    summary["CATEGORY_EMPTY_COUNT"] += 1
                    log(f"CATEGORY_{category.index}_NAVIGATION: {navigation}")
                    log(f"CATEGORY_{category.index}_MENU_GROUP_FOUND: {menu_diag.get('menu_group_found')}")
                    log(f"CATEGORY_{category.index}_RESULT: PASS_EMPTY")
                    continue
                table_frame = post_click.get("table_frame")
                checked, found_doc, attachments, selected = discover_attachment(page, table_frame)
                log(f"CATEGORY_{category.index}_NAVIGATION: {navigation}")
                log(f"CATEGORY_{category.index}_MENU_GROUP_FOUND: {menu_diag.get('menu_group_found')}")
                log(f"CATEGORY_{category.index}_VISIBLE_ROW_COUNT: {post_click.get('visible_rows', 0)}")
                log(f"CATEGORY_{category.index}_ROWS_CHECKED: {checked}")
                log(f"CATEGORY_{category.index}_VALID_DOCUMENT_ID_FOUND: {'YES' if found_doc else 'NO'}")
                log(f"CATEGORY_{category.index}_ATTACHMENT_COUNT: {len(attachments)}")
                if not selected:
                    log(f"CATEGORY_{category.index}_RESULT: PASS_NO_ATTACHMENT_IN_BOUNDS")
                    continue
                result = download_one(page, category_dir, selected)
                if result.persisted:
                    summary["CATEGORY_DOWNLOAD_COUNT"] += 1
                if result.persisted and result.http_status == 200:
                    summary["DOWNLOAD_HTTP_200_COUNT"] += 1
                if result.persisted and result.integrity == "PASS":
                    summary["FILE_INTEGRITY_PASS_COUNT"] += 1
                if result.session_expired:
                    summary["SESSION_EXPIRED"] = "YES"
                log(f"CATEGORY_{category.index}_HTTP_STATUS: {result.http_status}")
                log(f"CATEGORY_{category.index}_FILE_SIZE: {result.body_length}")
                log(f"CATEGORY_{category.index}_FILE_INTEGRITY: {result.integrity}")
                if not result.persisted:
                    raise RuntimeError(f"CATEGORY_{category.index}_{result.failure_code or 'DOWNLOAD_INTEGRITY_FAILED'}")
        live_ok = (
            summary["CATEGORY_VALIDATED_COUNT"] == 3
            and summary["SESSION_EXPIRED"] == "NO"
            and summary["DOWNLOAD_HTTP_200_COUNT"] == summary["CATEGORY_DOWNLOAD_COUNT"]
            and summary["FILE_INTEGRITY_PASS_COUNT"] == summary["CATEGORY_DOWNLOAD_COUNT"]
        )
        summary["LIVE_ACCEPTANCE"] = "PASS" if live_ok else "FAIL"
    except Exception as exc:
        summary["BLOCKED_WITH_EXACT_ERROR"] = safe_log(f"{type(exc).__name__}: {exc}")
        summary["LIVE_ACCEPTANCE"] = "FAIL"
    for key in (
        "PRECHECK",
        "CDP_CONNECTION",
        "CATEGORY_TOTAL",
        "CATEGORY_VALIDATED_COUNT",
        "CATEGORY_EMPTY_COUNT",
        "CATEGORY_DOWNLOAD_COUNT",
        "DOWNLOAD_HTTP_200_COUNT",
        "FILE_INTEGRITY_PASS_COUNT",
        "SESSION_EXPIRED",
        "OUTPUT_DIRECTORY",
        "LIVE_ACCEPTANCE",
        "BLOCKED_WITH_EXACT_ERROR",
    ):
        log(f"{key}: {summary[key]}")
    log("OCR_CALLED: NO")
    log("AI_CALLED: NO")
    log("PLANNER_API_CALLED: NO")
    log("BROWSER_CLOSE_CALLED: NO")
    log("CONTEXT_CLOSE_CALLED: NO")
    log("PAGE_CLOSE_CALLED: NO")
    return summary
