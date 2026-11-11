"""! @brief 고정 NF2FF 참조 worker를 기존 WSL 소유권 감독으로 실행한다."""

import argparse
import json
from pathlib import Path
import shutil
import sys
import threading
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from rfad.application.wsl_process import WslRuntime
from catalog_pcb_verification.common import publish_report, require


def main():
    """! @brief 새 staging과 보고서만 사용하고 원시 파일을 보존한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--reuse-raw-stage', type=Path)
    options = parser.parse_args()
    require(not options.stage.exists() and not options.report.exists(), '새 경로가 필요합니다.')
    stage = options.stage.resolve()
    (stage / 'tools').mkdir(parents=True)
    shutil.copytree(ROOT / 'src/rfad', stage / 'src/rfad', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copyfile(ROOT / 'tools/nf2ff_dipole_worker.py', stage / 'tools/openems_worker.py')
    if options.reuse_raw_stage is not None:
        shutil.copytree(options.reuse_raw_stage / 'output/native', stage / 'input/native')
    run_id, nonce = str(uuid4()), uuid4().hex
    (stage / 'request.json').write_text(json.dumps({'run_id': run_id, 'nonce': nonce}), encoding='utf-8')
    (stage / 'runtime.json').write_text('{}', encoding='utf-8')
    runtime = WslRuntime()
    process = runtime.execute(stage, run_id=run_id, nonce=nonce, cancel=threading.Event(), timeout_seconds=300,
                              max_directory_bytes=128 * 1024 * 1024, max_files=128)
    result = {'status': 'failed', 'process': process, 'physics_validated': False}
    if process['state'] == 'completed' and process.get('termination_confirmed'):
        result.update(json.loads((stage / 'output/radiation.json').read_text(encoding='utf-8')))
    options.report.parent.mkdir(parents=True, exist_ok=True)
    publish_report(options.report, result)
    print(json.dumps({'status': result['status'], 'report': str(options.report)}, ensure_ascii=False))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
