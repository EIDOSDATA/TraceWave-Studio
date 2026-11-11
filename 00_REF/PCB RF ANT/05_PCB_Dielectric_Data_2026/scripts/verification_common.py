"""! @brief 검증 오류와 파일 무결성 검사를 공통으로 관리한다."""

from collections import Counter
from pathlib import Path

from dataset_io import package_path, sha256


class Audit:
    """! @brief 읽기 전용 검증에서 발견한 오류와 확인 건수를 기록한다."""

    def __init__(self, base: Path):
        """! @brief 자료 폴더와 파일 해시 캐시를 초기화한다."""
        self.base = base.resolve()
        self.errors = []
        self.counts = Counter()
        self.hashes = {}
        self.file_checks = {}

    def require(self, condition: bool, message: str) -> None:
        """! @brief 조건 불일치를 숨기지 않고 결과에 추가한다."""
        if not condition:
            self.errors.append(message)

    def file(self, relative: str, label: str, expected_hash=None, expected_bytes=None):
        """! @brief 패키지 내부 파일의 존재와 선택적인 크기 및 해시를 검사한다."""
        key = (relative, expected_hash, expected_bytes)
        if key in self.file_checks:
            self.counts["reused_file_checks"] += 1
            return self.file_checks[key]
        try:
            path = package_path(relative, self.base)
            if not path.is_file():
                self.errors.append(f"{label}: missing file {relative}")
                self.file_checks[key] = None
                return None
            if expected_bytes is not None:
                self.require(path.stat().st_size == expected_bytes, f"{label}: byte count mismatch {relative}")
            if expected_hash is not None:
                if path not in self.hashes:
                    self.hashes[path] = sha256(path)
                self.require(self.hashes[path] == expected_hash, f"{label}: SHA-256 mismatch {relative}")
            self.file_checks[key] = path
            return path
        except (OSError, ValueError, TypeError) as error:
            self.errors.append(f"{label}: {error}")
            self.file_checks[key] = None
            return None
