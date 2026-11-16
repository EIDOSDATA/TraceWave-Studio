"""! @brief 파일 접근 없이 bounded Touchstone/CSV 복소 자료의 공개 교환 함수를 제공한다.

@details 서비스는 원본 bytes와 parser_metadata를 함께 보존하고 가져온 순서대로
network.port_ids를 부여한 뒤 공통 도메인 validator를 실행해야 한다.
"""

from rfad.adapters.network_csv import csv_export_mapping, parse_csv, write_csv
from rfad.adapters.network_text import MAX_COLUMNS, MAX_FILE_BYTES, MAX_LINE_CHARS, MAX_LINES
from rfad.adapters.network_touchstone import parse_touchstone, write_touchstone
from rfad.domain.network_data import MAX_PORTS, MAX_SAMPLES


PROFILE = "rfad.network-files/0.1"


def capabilities():
    """! @brief 실제 구현한 파일 profile과 유한 예산만 공개한다."""
    return {"profile": PROFILE, "max_bytes": MAX_FILE_BYTES, "max_samples": MAX_SAMPLES,
            "max_ports": MAX_PORTS, "max_line_chars": MAX_LINE_CHARS, "max_lines": MAX_LINES,
            "max_csv_columns": MAX_COLUMNS,
            "touchstone": {"versions": ["1.0", "2.0", "2.1"], "parameter_kind": "S",
                           "matrix_format": "Full", "complex_formats": ["RI", "MA", "DB"],
                           "utf8_comments_extension": True, "export_version": "2.1", "export_format": "RI"},
            "csv": {"encoding": "utf-8", "explicit_column_mapping": True,
                    "parameter_kinds": ["S", "Z", "Y"], "complex_formats": ["RI", "MA", "DB"],
                    "phase_unit": "deg", "export_format": "RI"}}
