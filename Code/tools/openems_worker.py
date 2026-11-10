"""! @brief supervisor 소유권 gate 이후에만 openEMS를 로딩하는 격리 진입점이다."""

import argparse
import json
from pathlib import Path
import sys


def main() -> int:
    """! @brief 고정 파일 요청과 시작 gate를 대조하고 단계별 결과를 원자적으로 기록한다."""
    gate_raw = sys.stdin.buffer.readline(65537)
    if not gate_raw.endswith(b'\n') or len(gate_raw) > 65536:
        return 2
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', required=True)
    args = parser.parse_args()
    stage = Path.cwd().resolve()
    path = Path(args.request)
    if path.is_absolute() or path.as_posix() != 'request.json':
        return 2
    raw = path.read_bytes()
    if len(raw) > 4 * 1024 * 1024:
        return 2
    gate, request = json.loads(gate_raw), json.loads(raw)
    if gate.get('schema') != 'rfad.wsl-start/0.1' or any(gate.get(key) != request.get(key) for key in ('run_id', 'nonce')):
        return 2
    sys.path.insert(0, str(stage / 'src'))
    from rfad.adapters.solvers.openems.native import execute, write_json
    from rfad.domain.errors import ProjectError

    status = 0
    try:
        result = execute(request, stage)
    except Exception as error:
        status = 1
        result = {'schema': 'rfad.openems-worker-result/0.1', 'phase': request.get('phase'),
                  'run_id': request.get('run_id'), 'nonce': request.get('nonce'),
                  'analysis_plan_id': request.get('analysis_plan', {}).get('plan_id'), 'files': [],
                  'error': error.diagnostic() if isinstance(error, ProjectError) else {'code': 'E_SOLVER', 'message_ko': str(error)[:2048]}}
    (stage / 'output').mkdir(exist_ok=True)
    write_json(stage / 'output' / 'result.json', result)
    return status


if __name__ == '__main__':
    raise SystemExit(main())
