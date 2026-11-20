"""! @brief 한 개정의 편집 표시를 보관하고 유한 RPC 페이지로 나눈다."""

from copy import deepcopy
import json
from threading import RLock

from rfad.application.canvas import project_canvas
from rfad.application.editor import editor_items, editor_selection
from rfad.application.project_contract import _fields, _uuid
from rfad.domain.errors import ProjectError
from rfad.domain.resource_limits import MAX_SELECTION_RESULT_BYTES


PROFILE = "rfad.edit-view-pages/0.1"
MAX_ROWS = 512
MAX_PAGE_BYTES = MAX_SELECTION_RESULT_BYTES
CANVAS_ROWS = ("shapes", "omissions", "pcb_features")


def _size(value):
    """! @brief 실제 RPC 응답과 같은 UTF-8 인코딩으로 본문 크기를 잰다."""
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8"))


def _bounded(result):
    """! @brief 한 속성 또는 페이지가 프레임 한도를 넘으면 명시적으로 거절한다."""
    if _size(result) > MAX_PAGE_BYTES:
        raise ProjectError("E_RESOURCE", "편집 표시 페이지가 전송 한도를 초과했습니다.")
    return result


def _page(shell, rows, offset):
    """! @brief 서로 다른 행 목록을 고정 순서로 잘라 다음 위치를 반환한다."""
    total = sum(len(items) for items in rows.values())
    if offset > total or (offset == total and offset != 0):
        raise ProjectError("E_SCHEMA", "편집 표시 페이지의 시작 위치가 유효하지 않습니다.")
    end = min(total, offset + MAX_ROWS)
    while True:
        result = dict(shell)
        base = 0
        for name, items in rows.items():
            result[name] = items[max(0, offset - base):max(0, end - base)]
            base += len(items)
        result["page"] = {"profile": PROFILE, "offset": offset, "next": end if end < total else None, "total": total}
        if _size(result) <= MAX_PAGE_BYTES:
            return deepcopy(result)
        if end <= offset + 1:
            return _bounded(result)
        end = offset + (end - offset) // 2


class EditViewPages:
    """! @brief 검증을 마친 현재 개정 한 개만 표시 조회에서 재사용한다."""

    def __init__(self):
        self._lock = RLock()
        self._reference = None
        self._document = None
        self._items = None
        self._scene = None
        self._selection = None
        self._details = None

    def read(self, service, params, *, canvas):
        """! @brief 원본·개정이 확인된 페이지 또는 선택 속성만 반환한다."""
        _fields(params, {"contract_version", "context", "input"})
        if params["contract_version"] != "rfad.api/2.0":
            raise ProjectError("E_VERSION", "지원하지 않는 API 버전입니다.")
        options = set() if canvas else {"selection", "include_items"}
        data = _fields(params["input"], {"expected_revision", "offset"}, options)
        _uuid(data["expected_revision"])
        offset = data["offset"]
        if type(offset) is not int or offset < 0:
            raise ProjectError("E_SCHEMA", "편집 표시에는 0 이상의 페이지 위치가 필요합니다.")
        include_items = data.get("include_items", True)
        if type(include_items) is not bool:
            raise ProjectError("E_SCHEMA", "목록 포함 여부는 boolean이어야 합니다.")
        # @brief journal의 같은 참조가 등록돼 있는 동안만 봉인된 표시 스냅샷을 재사용한다.
        with self._lock:
            project = service._project(service.journal.read(), params["context"])
            reference = project["current"]
            if reference != self._reference:
                self._document = service._load(project)
                self._reference = reference
                self._items = None
                self._scene = None
                self._details = None
            elif offset == 0:
                service.journal.read_document(reference)
            document = self._document
            if document["revision_id"] != data["expected_revision"]:
                raise ProjectError("E_CONFLICT", "편집 표시의 기준 개정이 현재 개정과 다릅니다.")
            service._check_history_head(project, document["revision_id"])
            if canvas:
                return self._canvas(document, offset)
            return self._editor(service, project, document, data.get("selection"), include_items, offset)

    def _editor(self, service, project, document, selection, include_items, offset):
        """! @brief 목록과 큰 속성 선택지를 같은 개정에서 잘라 보낸다."""
        if self._details is None or self._selection != selection or offset == 0:
            saved = document["revision_id"] if project["current"] == project["saved"] else service._saved_revision(project)
            details = editor_selection(document, saved, service._history_status(project), selection)
            choices = []
            for index, field in enumerate(details["selection"]["fields"]):
                if field.get("choices"):
                    choices.extend([index, item] for item in field["choices"])
                    field["choices"] = []
            if "coordinate_choices" in details:
                choices.extend([-1, item] for item in details["coordinate_choices"])
                details["coordinate_choices"] = []
            self._selection = deepcopy(selection)
            self._details = (details, choices)
        details, choices = self._details
        if include_items and self._items is None:
            self._items = editor_items(document)
        rows = {"items": self._items if include_items else [], "view_choices": choices}
        shell = details if offset == 0 else {key: details[key] for key in ("profile", "project_id", "revision_id")}
        return _page(shell, rows, offset)

    def _canvas(self, document, offset):
        """! @brief 장면을 한 번 투영하고 원래 순서를 유지해서 나눈다."""
        if self._scene is None:
            self._scene = project_canvas(document)
        scene = self._scene
        rows = {name: scene[name] for name in CANVAS_ROWS if name in scene}
        keys = (key for key in scene if key not in CANVAS_ROWS) if offset == 0 else (
            "profile", "project_id", "revision_id", "unit", "angle_unit")
        return _page({key: scene[key] for key in keys}, rows, offset)
