"""! @brief 폐기한 직접 실행 entry를 거절하고 공통 worker 경로를 안내한다.

@details 과거 보고서와 원시 자료는 보존한다. 동일 다이폴 생성은
rfad.adapters.solvers.openems.reference_benchmark에 있으며 이 파일로 실행하지 않는다.
"""

import sys


if __name__ == "__main__":
    sys.stderr.write("이 구형 직접 worker는 실행하지 않습니다. verify_nf2ff_reference.py의 공개 서비스 경로를 사용하십시오.\n")
    raise SystemExit(19)
