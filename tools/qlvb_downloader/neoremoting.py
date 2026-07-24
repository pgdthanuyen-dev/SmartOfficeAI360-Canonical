from __future__ import annotations

import ast
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit

from .models import AttachmentInfo


MAX_RESPONSE_BYTES = 64 * 1024
MAX_ATTACHMENTS = 32
MAX_NESTING_DEPTH = 5
_DOCUMENT_ID_RE = re.compile(r"^[0-9]{3,18}$")
_ALLOWED_FIELDS = {
    "name", "hdd_file", "type", "is_phieu_trinh",
    "file_id", "created_date", "user_name", "ky_so_info", "vanban_chinh_phu",
}
_SAFE_FIELD_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_FORBIDDEN_FIELD_NAMES = {"__proto__", "constructor", "prototype"}
_ALLOWED_QUERY_KEYS = ("5E1XCBS.", "5FpXTEW.", "TFbm5O.")
_ALLOWED_DETAIL_QUERY_KEYS = {"id", "doc_id", "document_id", "vb_id", "6yxl"}
_ONCLICK_PATTERNS = (
    ("legacy_onclick_show_detail", re.compile(r"showDocDetail\s*\(\s*['\"]?([0-9]{3,18})['\"]?", re.I)),
    ("legacy_onclick_attachment_list", re.compile(r"getFileAttachLst\s*\(\s*['\"]?([0-9]{3,18})['\"]?", re.I)),
    ("legacy_onclick_all_file_download", re.compile(r"allFileDownload\s*\(\s*['\"]?([0-9]{3,18})['\"]?", re.I)),
    ("legacy_onclick_incoming", re.compile(r"van_ban_den\s*\(\s*['\"]?([0-9]{3,18})['\"]?", re.I)),
)


@dataclass(frozen=True)
class DocumentIdExtraction:
    document_id: str
    source_method: str
    validation_status: str = "VALID"


class NeoRemotingDiscoveryError(RuntimeError):
    """Structured discovery error; only selected states permit a DOM fallback."""

    fallback_allowed_codes = {
        "NEOREMOTING_NOT_AVAILABLE",
        "NEOREMOTING_METHOD_NOT_AVAILABLE",
        "NEOREMOTING_OBJECT_NOT_AVAILABLE",
        "NEOREMOTING_GETRSET_NOT_FUNCTION",
        "NEOREMOTING_INVALID_RESPONSE",
    }

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)

    @property
    def fallback_allowed(self) -> bool:
        return self.code in self.fallback_allowed_codes


def _valid_document_id(value: object) -> str | None:
    text = str(value or "").strip()
    return text if _DOCUMENT_ID_RE.fullmatch(text) else None


def extract_document_id(
    *,
    attributes: Mapping[str, object] | None = None,
    row_id: object = "",
    onclick: object = "",
    href: object = "",
    detail_metadata: Mapping[str, object] | None = None,
) -> DocumentIdExtraction | None:
    """Extract only a structurally identified QLVB document id, never row text."""
    attributes = {str(key).lower(): value for key, value in (attributes or {}).items()}
    for key in ("data-document-id", "data-doc-id", "data-vb-id"):
        value = _valid_document_id(attributes.get(key))
        if value:
            return DocumentIdExtraction(value, "canonical_data_attribute")

    for value in (attributes.get("data-id"), row_id):
        candidate = str(value or "").strip()
        match = re.fullmatch(r"(?:vb[_-]?)?([0-9]{3,18})", candidate, re.I)
        if match:
            return DocumentIdExtraction(match.group(1), "legacy_row_id")

    script = str(onclick or "")
    for method, pattern in _ONCLICK_PATTERNS:
        match = pattern.search(script)
        if match:
            return DocumentIdExtraction(match.group(1), method)

    try:
        for key, value in parse_qsl(urlsplit(str(href or "")).query, keep_blank_values=True):
            if key.lower() in _ALLOWED_DETAIL_QUERY_KEYS:
                candidate = _valid_document_id(value)
                if candidate:
                    return DocumentIdExtraction(candidate, "allowlisted_href_query")
    except ValueError:
        pass

    for key in ("document_id", "source_document_id", "doc_id", "vb_id"):
        candidate = _valid_document_id((detail_metadata or {}).get(key))
        if candidate:
            return DocumentIdExtraction(candidate, "detail_action_metadata")
    return None


def _custom_base64(value: str) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/~"
    raw = value.encode("utf-8")
    output: list[str] = []
    for offset in range(0, len(raw), 3):
        group = raw[offset:offset + 3]
        first = group[0]
        second = group[1] if len(group) > 1 else None
        third = group[2] if len(group) > 2 else None
        output.append(alphabet[first >> 2])
        output.append(alphabet[((first & 3) << 4) | ((second >> 4) if second is not None else 0)])
        output.append(alphabet[(((second & 15) << 2) if second is not None else 0) | ((third >> 6) if third is not None else 0)] if second is not None else "~")
        output.append(alphabet[third & 63] if third is not None else "~")
    return "".join(output)


def _safe_filename(name: str) -> str:
    normalized = unicodedata.normalize("NFC", name or "").strip()
    normalized = normalized.replace("\\", "_").replace("/", "_")
    normalized = re.sub(r'[<>:"|?*\x00-\x1f]+', "_", normalized).strip(" .")
    if not normalized or normalized in {".", ".."}:
        raise NeoRemotingDiscoveryError("NEOREMOTING_INVALID_RESPONSE")
    return normalized[:512]


def build_legacy_download_url(base_url: str, file_name: str, hdd_file: str, file_type: str) -> str:
    """Reproduce the verified legacy URL contract through parsed URL components."""
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise NeoRemotingDiscoveryError("NEOREMOTING_INVALID_RESPONSE")
    base_path = parsed.path.split("/main", 1)[0].rstrip("/")
    endpoint = f"{base_path}/smartoffice/jbm/download.jsp"
    if ".." in endpoint.split("/"):
        raise NeoRemotingDiscoveryError("NEOREMOTING_INVALID_RESPONSE")
    encoded_name = _custom_base64(file_name)
    # Keep the verified V18 contract byte-for-byte: an upload/ path is already
    # the server-side path parameter; other values are encoded as opaque ids.
    encoded_path = hdd_file if "upload/" in hdd_file else _custom_base64(hdd_file)
    encoded_type = _custom_base64(file_type or "vb")
    query = "&".join((
        "5E1XCBS.=" + quote(encoded_name, safe=""),
        "5FpXTEW.=" + encoded_path,
        "TFbm5O.=" + quote(encoded_type, safe=""),
    ))
    url = urlunsplit((parsed.scheme, parsed.netloc, endpoint, query, ""))
    validate_neoremoting_download_url(url, allowed_hosts={parsed.hostname.lower()}, allowed_scheme=parsed.scheme)
    return url


def classify_hdd_file(value: object) -> dict[str, object]:
    """Return only non-sensitive shape information for a runtime hdd_file value."""
    text = value if isinstance(value, str) else ""
    parsed = urlsplit(text)
    absolute = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    javascript = parsed.scheme.lower() == "javascript"
    relative = not absolute and not javascript and (
        text.startswith(("/", "./", "../")) or "/" in text
    )
    return {
        "value_type": type(value).__name__,
        "is_absolute_http_url": absolute,
        "is_relative_path": relative,
        "is_server_file_id": bool(text) and not absolute and not relative and not javascript,
        "is_javascript_action": javascript,
        "has_query": bool(parsed.query),
        "length": len(text),
    }


def validate_neoremoting_download_url(url: str, *, allowed_hosts: set[str], allowed_scheme: str = "https") -> None:
    parsed = urlsplit(url)
    if parsed.scheme != allowed_scheme or not parsed.hostname or parsed.hostname.lower() not in allowed_hosts:
        raise NeoRemotingDiscoveryError("NEOREMOTING_INVALID_RESPONSE")
    if parsed.path != "/qlvbdh_lcu/smartoffice/jbm/download.jsp" and not parsed.path.endswith("/smartoffice/jbm/download.jsp"):
        raise NeoRemotingDiscoveryError("NEOREMOTING_INVALID_RESPONSE")
    if any(segment in {"", ".", ".."} for segment in parsed.path.split("/")[1:]):
        raise NeoRemotingDiscoveryError("NEOREMOTING_INVALID_RESPONSE")
    keys = tuple(key for key, _ in parse_qsl(parsed.query, keep_blank_values=True))
    if keys != _ALLOWED_QUERY_KEYS:
        raise NeoRemotingDiscoveryError("NEOREMOTING_INVALID_RESPONSE")


def _depth(value: Any, current: int = 0) -> int:
    if current > MAX_NESTING_DEPTH:
        return current
    if isinstance(value, dict):
        return max([current, *(_depth(item, current + 1) for item in value.values())])
    if isinstance(value, list):
        return max([current, *(_depth(item, current + 1) for item in value)])
    return current


def parse_attachment_response(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, str) or not raw:
        raise NeoRemotingDiscoveryError("NEOREMOTING_EMPTY_RESULT")
    if len(raw.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise NeoRemotingDiscoveryError("NEOREMOTING_INVALID_RESPONSE")
    lowered = raw.lstrip().lower()
    if lowered.startswith("<") or any(token in lowered for token in ("<script", "function", "=>", "constructor", "__proto__", ";")):
        raise NeoRemotingDiscoveryError("NEOREMOTING_INVALID_RESPONSE")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        candidate = raw.strip()
        if not (candidate.startswith("[") and candidate.endswith("]")):
            raise NeoRemotingDiscoveryError("NEOREMOTING_INVALID_RESPONSE")
        candidate = re.sub(r"([,{]\s*)([A-Za-z_][A-Za-z0-9_]{0,63})\s*:", r'\1"\2":', candidate)
        candidate = re.sub(r"\btrue\b", "True", candidate, flags=re.I)
        candidate = re.sub(r"\bfalse\b", "False", candidate, flags=re.I)
        candidate = re.sub(r"\bnull\b", "None", candidate, flags=re.I)
        try:
            value = ast.literal_eval(candidate)
        except (SyntaxError, ValueError) as exc:
            raise NeoRemotingDiscoveryError("NEOREMOTING_INVALID_RESPONSE") from exc
    if not isinstance(value, list) or len(value) > MAX_ATTACHMENTS or _depth(value) > MAX_NESTING_DEPTH:
        raise NeoRemotingDiscoveryError("NEOREMOTING_INVALID_RESPONSE")
    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise NeoRemotingDiscoveryError("NEOREMOTING_INVALID_RESPONSE")
        for key, field_value in item.items():
            if (
                not isinstance(key, str)
                or not _SAFE_FIELD_NAME_RE.fullmatch(key)
                or key.lower() in _FORBIDDEN_FIELD_NAMES
                or isinstance(field_value, (dict, list, tuple, set))
                or not isinstance(field_value, (str, int, float, bool, type(None)))
                or (isinstance(field_value, str) and len(field_value) > 4096)
            ):
                raise NeoRemotingDiscoveryError("NEOREMOTING_INVALID_RESPONSE")
        name = item.get("name")
        hdd_file = item.get("hdd_file")
        file_type = item.get("type", "vb")
        is_phieu_trinh = item.get("is_phieu_trinh", "0")
        if not isinstance(name, str) or not isinstance(hdd_file, str) or not isinstance(file_type, str):
            raise NeoRemotingDiscoveryError("NEOREMOTING_INVALID_RESPONSE")
        if not name or not hdd_file or len(name) > 512 or len(hdd_file) > 4096 or len(file_type) > 32:
            raise NeoRemotingDiscoveryError("NEOREMOTING_INVALID_RESPONSE")
        if str(is_phieu_trinh) != "1":
            normalized.append({"name": name, "hdd_file": hdd_file, "type": file_type})
    if not normalized:
        raise NeoRemotingDiscoveryError("NO_ATTACHMENTS")
    return normalized


class NeoRemotingAttachmentDiscoveryAdapter:
    source_method = "NEOREMOTING"

    def __init__(self, base_url: str, *, timeout_ms: int = 8000):
        self.base_url = base_url
        self.timeout_ms = max(1000, min(int(timeout_ms), 30000))
        self.last_probe: dict[str, object] = {}

    @staticmethod
    def _select_runtime_scope(page):
        frames = getattr(page, "frames", None)
        scopes = list(frames) if isinstance(frames, (list, tuple)) and frames else [page]
        inspected: list[dict[str, object]] = []
        for index, scope in enumerate(scopes):
            scope_url = str(getattr(scope, "url", "") or "")
            if scope_url.startswith("about:blank"):
                inspected.append({
                    "frame_index": index,
                    "neo_type": "skipped_about_blank",
                    "getrset_type": "skipped_about_blank",
                })
                continue
            try:
                state = scope.evaluate(
                    """() => ({
                        neoType: typeof window.NEORemoting,
                        getRSetType: typeof (window.NEORemoting && window.NEORemoting.getRSet)
                    })"""
                )
            except Exception:
                state = {}
            inspected.append({
                "frame_index": index,
                "neo_type": str(state.get("neoType", "unavailable")) if isinstance(state, dict) else "unavailable",
                "getrset_type": str(state.get("getRSetType", "unavailable")) if isinstance(state, dict) else "unavailable",
            })
            if (
                isinstance(state, dict)
                and state.get("neoType") in {"object", "function"}
                and state.get("getRSetType") == "function"
            ):
                return scope, inspected
        code = "NEOREMOTING_OBJECT_NOT_AVAILABLE"
        if any(item["neo_type"] in {"object", "function"} for item in inspected):
            code = "NEOREMOTING_GETRSET_NOT_FUNCTION"
        raise NeoRemotingDiscoveryError(code)

    def discover(self, page, *, document_id: str, category: str, correlation_id: str) -> list[AttachmentInfo]:
        if not _valid_document_id(document_id):
            raise NeoRemotingDiscoveryError("NEOREMOTING_INVALID_RESPONSE")
        if not str(category or "").startswith("incoming"):
            raise NeoRemotingDiscoveryError("NEOREMOTING_METHOD_NOT_AVAILABLE")
        frames = getattr(page, "frames", None)
        if isinstance(frames, (list, tuple)):
            scope, inspected = self._select_runtime_scope(page)
        else:
            scope, inspected = page, [{"frame_index": 0, "neo_type": "unknown", "getrset_type": "unknown"}]
        result = scope.evaluate(
            """async ({documentId, timeoutMs}) => {
                const neo = window.NEORemoting;
                const neoType = typeof neo;
                if (neo === null || !['object', 'function'].includes(neoType)) {
                    return {state: 'NEOREMOTING_OBJECT_NOT_AVAILABLE', neoType};
                }
                if (typeof neo.getRSet !== 'function') {
                    return {state: 'NEOREMOTING_GETRSET_NOT_FUNCTION', neoType, getRSetType: typeof neo.getRSet};
                }
                const operation = 'qlvb.van_ban_den.getFileAttachLst("' + documentId + '",0)';
                return await new Promise((resolve) => {
                    let settled = false;
                    const timer = window.setTimeout(() => {
                        if (settled) return;
                        settled = true;
                        resolve({state: 'NEOREMOTING_CALLBACK_TIMEOUT'});
                    }, timeoutMs);
                    try {
                        neo.getRSet.call(neo, operation, function(data) {
                            if (settled) return;
                            settled = true;
                            window.clearTimeout(timer);
                            let raw = '';
                            if (typeof data === 'string') raw = data;
                            else if (Array.isArray(data) || (data && typeof data === 'object')) {
                                try { raw = JSON.stringify(data); } catch (_) { raw = ''; }
                            }
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
                    } catch (error) {
                        if (settled) return;
                        settled = true;
                        window.clearTimeout(timer);
                        resolve({state: 'NEOREMOTING_SYNCHRONOUS_EXCEPTION'});
                    }
                });
            }""",
            {"documentId": document_id, "timeoutMs": self.timeout_ms},
        )
        if not isinstance(result, dict):
            raise NeoRemotingDiscoveryError("NEOREMOTING_INVALID_RESPONSE")
        state = str(result.get("state") or "NEOREMOTING_INVALID_RESPONSE")
        self.last_probe = {"frames": inspected, "state": state, "shape": result.get("shape", {})}
        if state != "SUCCESS":
            raise NeoRemotingDiscoveryError(state)
        rows = parse_attachment_response(result.get("raw"))
        candidates: list[AttachmentInfo] = []
        for row in rows:
            filename = _safe_filename(row["name"])
            url = build_legacy_download_url(self.base_url, row["name"], row["hdd_file"], row["type"])
            candidates.append(AttachmentInfo(
                text=filename,
                href=url,
                original_filename=filename,
                attachment_id=row["hdd_file"],
                source_method=self.source_method,
            ))
        return candidates
