"""! @brief 자료 파일과 관측 및 출처 연결을 변경 없이 전수 검증한다."""

import argparse
import json
import sys
from pathlib import Path
from zipfile import BadZipFile

from dataset_io import BASE
from verification_common import Audit
from verify_inventory import verify_guide, verify_manifest
from verify_observations import verify_observations
from verify_sources import verify_archive_members, verify_search_index, verify_sources


def verify(base: Path, include_manifest: bool = True) -> dict:
    """! @brief 각 책임별 검사를 실행하고 검증 범위를 명시한 결과를 반환한다."""
    audit = Audit(base)
    stages = []
    if include_manifest:
        stages.append(("manifest", lambda: verify_manifest(audit)))
    source_ids = set()

    def sources_stage():
        """! @brief 이후 외래키 검사에 필요한 출처 ID를 확보한다."""
        source_ids.update(verify_sources(audit))

    stages.extend([
        ("sources", sources_stage),
        ("observations", lambda: verify_observations(audit, source_ids)),
        ("search_text", lambda: verify_search_index(audit, source_ids)),
        ("archive_members", lambda: verify_archive_members(audit, source_ids)),
        ("guide", lambda: verify_guide(audit)),
    ])
    for label, operation in stages:
        try:
            operation()
        except (OSError, ValueError, KeyError, TypeError, BadZipFile) as error:
            audit.errors.append(f"{label}: {error}")
    return {
        "status": "failed" if audit.errors else "passed",
        "manifest_checked": include_manifest,
        "counts": dict(audit.counts),
        "error_count": len(audit.errors),
        "errors": audit.errors[:100],
        "errors_omitted": max(0, len(audit.errors) - 100),
        "scope": "File integrity, record structure and source links only. Not independent material, cell-transcription or solver accuracy validation.",
    }


def main() -> int:
    """! @brief 표준 출력으로 검사 결과를 제공하고 실패 시 0이 아닌 값을 반환한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, default=BASE)
    parser.add_argument("--skip-manifest", action="store_true", help="Check working content before regenerating the final manifest.")
    arguments = parser.parse_args()
    result = verify(arguments.package_root, not arguments.skip_manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
