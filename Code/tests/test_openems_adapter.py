"""! @brief 준비 XML 봉인, 원시 결과 재처리와 실제 TE10 adapter를 검사한다."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.adapters.solvers.openems import native
from rfad.adapters.solvers.openems.reference import compare_grids
from rfad.application.canonical import CANONICAL_VERSION, canonical_bytes, canonical_hash
from rfad.application.solver import build_analysis_plan, make_prepared_plan
from rfad.domain.errors import ProjectError
from rfad.domain.project import new_project


ROOT = Path(__file__).resolve().parents[1]
NATIVE_AVAILABLE = sys.platform == 'linux' and os.environ.get('RFAD_OPENEMS_NATIVE') == '1'


def reference_plan(runtime: dict, grid_mm: float = 1.0) -> dict:
    """! @brief 빈 프로젝트 전체 SnapshotRef에 고정 참조 계획을 연결한다."""
    document = new_project('도파관 adapter 시험')
    raw = canonical_bytes(document)
    snapshot = {'snapshot_id': str(uuid4()), 'project_id': document['project_id'], 'revision_id': document['revision_id'],
                'schema_version': document['schema_version'], 'canonical_version': CANONICAL_VERSION, 'content_hash': canonical_hash(document),
                'sealed_at': 1794270000.0, 'description': 'TE10 native 시험', 'validation_state': 'valid',
                'artifact': {'uri': 'test/snapshot.json', 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}}
    return build_analysis_plan(document, snapshot, runtime, grid_mm)


class OpenemsArtifactTests(unittest.TestCase):
    """! @brief native 설치 없이도 경로와 봉인, gate의 거부 동작을 검사한다."""

    def test_input_hash_role_and_traversal_rejection(self):
        """! @brief 원시 입력의 경로 탈출, 변조, 중복 역할을 차단한다."""
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory).resolve()
            (stage / 'input').mkdir()
            path = stage / 'input' / 'a'
            path.write_bytes(b'abc')
            record = {'path': 'input/a', 'role': 'native_input', **native.file_identity(path)}
            self.assertEqual(native.input_index(stage, [record]), {'native_input': path})
            for value in [dict(record, path='input/../a'), dict(record, path='/input/a'), dict(record, sha256='0' * 64)]:
                with self.assertRaises(ProjectError):
                    native.input_index(stage, [value])
            with self.assertRaises(ProjectError):
                native.input_index(stage, [record, record])

    def test_statistics_reject_nonfinite_and_exhaustion(self):
        """! @brief timestep 상한과 불완전 통계를 성공으로 수용하지 않는다."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'stats'
            for data in ['18711\n1e-12\n20000\n0\n0\n0', '18711\nNaN\n4305\n0\n0\n0', '1\n2']:
                path.write_text(data, encoding='utf-8')
                with self.assertRaises(ProjectError):
                    native.read_statistics(path)

    def test_worker_gate_blocks_before_source_import(self):
        """! @brief 소유권 gate가 없으면 source와 native를 읽기 전에 종료한다."""
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            worker = stage / 'worker.py'
            shutil.copyfile(ROOT / 'tools' / 'openems_worker.py', worker)
            request = {'run_id': str(uuid4()), 'nonce': str(uuid4())}
            (stage / 'request.json').write_bytes(canonical_bytes(request))
            for gate in [b'', b'{}\n', canonical_bytes({'schema': 'rfad.wsl-start/0.1', 'run_id': str(uuid4()), 'nonce': request['nonce']}) + b'\n']:
                run = subprocess.run([sys.executable, '-I', '-B', str(worker), '--request', 'request.json'], cwd=stage, input=gate, capture_output=True, timeout=10)
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertFalse((stage / 'output').exists())

    def test_postprocess_missing_raw_never_runs_solver(self):
        """! @brief raw 누락을 후처리 단계에서 검출하며 FDTD를 자동 실행하지 않는다."""
        with tempfile.TemporaryDirectory() as directory, patch.object(native, '_check_preparation', return_value={}):
            with patch.object(native.subprocess, 'Popen') as popen:
                with self.assertRaises(ProjectError) as failure:
                    native.postprocess(Path(directory), {}, {}, {})
                self.assertEqual(failure.exception.code, 'E_MISSING_ARTIFACT')
                popen.assert_not_called()

    def test_postprocess_rejects_incomplete_duplicate_and_unexpected_manifest_roles(self):
        """! @brief manifest가 중복 또는 누락 파일을 완료 raw로 가장할 수 없다."""
        request = {'analysis_plan': {'example': 1}, 'prepared_plan': {'example': 2}}
        original = [{'role': 'raw/' + name, 'path': 'output/raw/' + name} for name in native.RAW_NAMES]
        for mode in ('missing', 'duplicate', 'extra', 'unexpected', 'wrong_path'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                stage = Path(directory)
                (stage / 'output').mkdir()
                records = deepcopy(original)
                if mode == 'missing':
                    records.pop()
                elif mode == 'duplicate':
                    records[-1] = records[0]
                elif mode == 'extra':
                    records.append(records[0])
                elif mode == 'unexpected':
                    records[-1]['role'] = 'raw/unknown'
                else:
                    records[0]['path'] = 'output/raw/other'
                manifest = {'schema': 'rfad.openems-raw/0.1', 'complete': True,
                            'analysis_plan_hash': canonical_hash(request['analysis_plan']),
                            'prepared_plan_hash': canonical_hash(request['prepared_plan']), 'files': records}
                path = stage / 'raw_manifest.json'
                native.write_json(path, manifest)
                with patch.object(native, '_check_preparation', return_value={}), patch.object(native.subprocess, 'Popen') as popen:
                    with self.assertRaises(ProjectError) as failure:
                        native.postprocess(stage, request, {'raw_manifest': path}, {})
                    self.assertEqual(failure.exception.code, 'E_HASH' if mode == 'wrong_path' else 'E_MISSING_ARTIFACT')
                    popen.assert_not_called()


@unittest.skipUnless(NATIVE_AVAILABLE, 'RFAD_OPENEMS_NATIVE=1인 고정 Linux solver venv가 필요합니다.')
class OpenemsNativeTests(unittest.TestCase):
    """! @brief 실제 Linux openEMS로 두 격자의 XML 준비, 해석과 재후처리를 검증한다."""

    def setUp(self):
        """! @brief native 실행을 ext4의 전용 임시 공간과 고정 감사 명세로 격리한다."""
        self.temporary = tempfile.TemporaryDirectory(prefix='adapter-test-', dir='/home/tracewave/rfad-runtime')
        self.base = Path(self.temporary.name)
        self.audit = json.loads((ROOT / '.local' / 'wsl' / 'native-audit.json').read_bytes())
        self.manifest = json.loads((ROOT / 'runtime_profiles' / 'python-openems-linux-x64.json').read_bytes())
        self.source_dir = self.base / 'frozen-source'
        shutil.copytree(ROOT / 'src', self.source_dir / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        (self.source_dir / 'tools').mkdir()
        shutil.copyfile(ROOT / 'tools' / 'openems_worker.py', self.source_dir / 'tools' / 'openems_worker.py')

    def tearDown(self):
        """! @brief 이 시험이 생성한 정확한 임시 디렉터리만 정리한다."""
        self.temporary.cleanup()

    def stage(self, label: str) -> tuple[Path, dict]:
        """! @brief 실행에 필요한 source만 복사하여 자체 해시를 고정한다."""
        stage = self.base / label
        stage.mkdir()
        shutil.copytree(self.source_dir / 'src', stage / 'src')
        (stage / 'tools').mkdir()
        shutil.copyfile(self.source_dir / 'tools' / 'openems_worker.py', stage / 'tools' / 'openems_worker.py')
        runtime = {'schema': 'rfad.openems-worker-runtime/0.1', 'python_manifest': self.manifest, 'native_audit': self.audit}
        native.write_json(stage / 'runtime.json', runtime)
        code = [{'path': path.relative_to(stage).as_posix(), **native.file_identity(path)} for path in sorted((stage / 'src').rglob('*.py'))]
        code.append({'path': 'tools/openems_worker.py', **native.file_identity(stage / 'tools' / 'openems_worker.py')})
        return stage, {'runtime_profile': 'openems-wsl-reference/0.1', 'manifest_sha256': native.file_identity(stage / 'runtime.json')['sha256'], 'code_files': code, 'transport': {'native_test': True}}

    def run_worker(self, stage: Path, request: dict, expected_code: int = 0) -> dict:
        """! @brief 실제 시작 gate와 worker 프로세스 경계를 통과시킨다."""
        native.write_json(stage / 'request.json', request)
        gate = canonical_bytes({'schema': 'rfad.wsl-start/0.1', 'run_id': request['run_id'], 'nonce': request['nonce']}) + b'\n'
        run = subprocess.run([sys.executable, '-I', '-B', 'tools/openems_worker.py', '--request', 'request.json'], cwd=stage, input=gate, capture_output=True, timeout=60)
        result_path = stage / 'output' / 'result.json'
        result = json.loads(result_path.read_bytes()) if result_path.exists() else {}
        self.assertEqual(run.returncode, expected_code, str(result)[:3000] + run.stderr.decode(errors='replace'))
        return result

    def request(self, phase: str, plan: dict, runtime: dict) -> dict:
        """! @brief 각 단계에 독립 실행 UUID와 nonce를 부여한다."""
        return {'schema': 'rfad.openems-worker/0.1', 'phase': phase, 'run_id': str(uuid4()), 'nonce': str(uuid4()),
                'analysis_plan': plan, 'runtime': runtime, 'input_files': []}

    def copy_inputs(self, source: Path, stage: Path, records: list[dict]) -> list[dict]:
        """! @brief 봉인된 산출물을 원래 역할과 해시로 후속 단계에 전달한다."""
        (stage / 'input').mkdir(exist_ok=True)
        results = []
        for record in records:
            relative = 'input/' + record['role'].replace('/', '_')
            shutil.copyfile(source / record['path'], stage / relative)
            results.append({**record, 'path': relative})
        return results

    def assert_official_ports(self, directory: Path, samples: list[dict]) -> None:
        """! @brief solver 실행 없이 공식 CalcPort와 독립 raw 정규화의 동등성을 대조한다."""
        import numpy as np
        import CSXCAD
        import openEMS

        structure = CSXCAD.ContinuousStructure()
        solver = openEMS.openEMS()
        solver.SetCSX(structure)
        inlet = solver.AddRectWaveGuidePort(1, [0, 0, 10], [20, 10, 15], 'z', 0.02, 0.01, 'TE10', excite=1)
        outlet = solver.AddRectWaveGuidePort(2, [0, 0, 70], [20, 10, 65], 'z', 0.02, 0.01, 'TE10', excite=0)
        frequency = np.array([sample['frequency_hz'] for sample in samples])
        for port in (inlet, outlet):
            port.CalcPort(str(directory), frequency)
        expected = {'s11': inlet.uf_ref / inlet.uf_inc, 's21': outlet.uf_ref / inlet.uf_inc, 'impedance_ohm': inlet.uf_tot / inlet.if_tot}
        for name, values in expected.items():
            # @brief 독립 해석식과 native의 진공 임피던스 상수 차이 약 0.55 ppb를 허용한다.
            np.testing.assert_allclose([complex(*sample[name]) for sample in samples], values, rtol=1e-9, atol=1e-9)

    def test_two_grids_frozen_xml_and_postprocess_without_solver(self):
        """! @brief 두 격자의 물리 오차, 봉인된 XML 소비, raw 재처리 일치를 검사한다."""
        results = []
        for index, grid in enumerate((1.0, 0.75)):
            prepare_stage, runtime = self.stage(f'prepare-{index}')
            plan = reference_plan(runtime, grid)
            prepared = self.run_worker(prepare_stage, self.request('prepare', plan, runtime))
            self.assertFalse((prepare_stage / 'output' / 'raw').exists())
            preparation = prepared['preparation']
            self.assertFalse(preparation['mesh_statistics']['fdtd_executed'])
            preparation_file = next(item for item in prepared['files'] if item['role'] == 'preparation_artifact')
            plan_raw = canonical_bytes(plan)
            prepared_plan = make_prepared_plan({'plan_id': plan['plan_id'], 'content_hash': canonical_hash(plan),
                                               'artifact': {'uri': 'test/plan.json', 'sha256': hashlib.sha256(plan_raw).hexdigest(), 'bytes': len(plan_raw)}},
                                              plan['snapshot'], {'uri': 'test/preparation.json', 'sha256': preparation_file['sha256'], 'bytes': preparation_file['bytes']}, runtime)
            solve_stage, solve_runtime = self.stage(f'analysis-{index}')
            request = self.request('analysis', plan, solve_runtime)
            request.update(prepared_plan=prepared_plan, preparation=preparation)
            request['input_files'] = self.copy_inputs(prepare_stage, solve_stage, preparation['files'])
            solved = self.run_worker(solve_stage, request)
            result = solved['result']
            self.assertEqual(len(result['samples']), 31)
            self.assertTrue(result['assessment']['passed'])
            self.assert_official_ports(solve_stage / 'output' / 'raw', result['samples'])
            self.assertEqual(result['termination']['status'], 'end_criterion_reached')
            self.assertEqual(result['raw_manifest']['execution']['native_input_sha256'], preparation['files'][0]['sha256'])
            results.append(result['samples'])
            post_stage, post_runtime = self.stage(f'post-{index}')
            post_request = self.request('postprocess_only', plan, post_runtime)
            post_request.update(prepared_plan=prepared_plan, preparation=preparation)
            post_request['input_files'] = self.copy_inputs(prepare_stage, post_stage, preparation['files'])
            raw_files = [item for item in solved['files'] if item['role'].startswith('raw/') or item['role'] == 'raw_manifest']
            post_request['input_files'] += self.copy_inputs(solve_stage, post_stage, raw_files)
            post = self.run_worker(post_stage, post_request)
            self.assertEqual(post['result']['samples'], result['samples'])
            self.assertEqual(post['result']['raw_manifest'], result['raw_manifest'])
            self.assertEqual(json.loads((post_stage / 'progress.json').read_bytes()), {'phase': 'postprocessing'})
            if index == 0:
                bad_stage, bad_runtime = self.stage('tampered-xml')
                bad_request = self.request('analysis', plan, bad_runtime)
                bad_request.update(prepared_plan=prepared_plan, preparation=preparation)
                bad_request['input_files'] = self.copy_inputs(prepare_stage, bad_stage, preparation['files'])
                xml = next(item for item in bad_request['input_files'] if item['role'] == 'native_input')
                with (bad_stage / xml['path']).open('ab') as stream:
                    stream.write(b'<!--tampered-->')
                xml.update(native.file_identity(bad_stage / xml['path']))
                failed = self.run_worker(bad_stage, bad_request, 1)
                self.assertEqual(failed['error']['code'], 'E_HASH')
                self.assertFalse((bad_stage / 'output' / 'raw').exists())
        self.assertTrue(compare_grids(*results)['passed'])


if __name__ == '__main__':
    unittest.main()
