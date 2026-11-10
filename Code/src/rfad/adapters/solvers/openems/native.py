"""! @brief 봉인된 XML의 준비, 실행, 원시 포트 후처리를 분리한다.

@details 이 모듈은 격리 worker에서만 사용한다. 임의 안테나 형상을 지원하지 않는다.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.domain.errors import ProjectError
from .reference import END_CRITERION, LIMITS, analytic_te10, assess_samples, check_termination


EXECUTABLE = Path('/home/tracewave/rfad-runtime/openems/0.37.0/bin/openEMS')
RAW_NAMES = ('port_ut_1', 'port_it_1', 'port_ut_2', 'port_it_2',
             'openEMS_stats.txt', 'openEMS_run_stats.txt', 'native.log', 'waveguide.xml')
MAX_FILE_BYTES = 64 * 1024 * 1024


def require(condition: bool, message: str, code: str = 'E_SOLVER') -> None:
    """! @brief 검증 실패를 구조화된 worker 오류로 전달한다."""
    if not condition:
        raise ProjectError(code, message)


def file_identity(path: Path) -> dict:
    """! @brief 파일의 실제 바이트 수와 SHA256을 계산한다."""
    require(path.is_file() and not path.is_symlink(), '필수 일반 파일이 없습니다: ' + str(path), 'E_MISSING_ARTIFACT')
    digest = hashlib.sha256()
    count = 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            count += len(block)
            digest.update(block)
    return {'bytes': count, 'sha256': digest.hexdigest()}


def write_json(path: Path, data: dict) -> None:
    """! @brief 유한 canonical JSON을 같은 디렉터리에서 원자적으로 발행한다."""
    temporary = path.with_name(path.name + '.partial')
    with temporary.open('xb') as stream:
        stream.write(canonical_bytes(data))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def descriptor(stage: Path, path: Path, role: str) -> dict:
    """! @brief 외부 경로를 제외한 봉인 산출물 설명자를 만든다."""
    identity = file_identity(path)
    require(identity['bytes'] <= MAX_FILE_BYTES, '산출물 크기 제한을 초과했습니다.', 'E_RESOURCE')
    media_type = 'application/json' if path.suffix == '.json' else 'application/xml' if path.suffix == '.xml' else 'text/plain'
    return {'path': path.relative_to(stage).as_posix(), 'role': role, 'media_type': media_type, **identity}


def input_index(stage: Path, records: list[dict]) -> dict[str, Path]:
    """! @brief 입력의 상대 경로, 중복 역할, 링크와 해시를 검증한다."""
    require(type(records) is list and len(records) <= 64, '입력 파일 목록이 올바르지 않습니다.', 'E_INVALID_ARGUMENT')
    result = {}
    for record in records:
        relative = PurePosixPath(record['path'])
        require(bool(relative.parts) and not relative.is_absolute() and relative.parts[0] == 'input' and '..' not in relative.parts
                and '\\' not in record['path'], '입력 경로가 stage 밖을 가리킵니다.', 'E_INVALID_ARGUMENT')
        path = stage.joinpath(*relative.parts)
        require(path.resolve().is_relative_to(stage / 'input') and not any(parent.is_symlink() for parent in [path, *path.parents] if parent != stage),
                '입력에 외부 경로나 심볼릭 링크가 있습니다.', 'E_INVALID_ARGUMENT')
        require(record['role'] not in result, '입력 파일 역할이 중복됩니다.', 'E_INVALID_ARGUMENT')
        identity = file_identity(path)
        require(identity['bytes'] <= MAX_FILE_BYTES and all(identity[key] == record[key] for key in identity), '입력 파일 봉인이 일치하지 않습니다.', 'E_HASH')
        result[record['role']] = path
    return result


def _mapped_files(pid: int | str = 'self') -> list[Path]:
    """! @brief Linux가 실제 매핑한 native 파일을 수집한다."""
    try:
        lines = Path(f'/proc/{pid}/maps').read_text(encoding='utf-8').splitlines()
    except FileNotFoundError:
        return []
    paths = set()
    for line in lines:
        fields = line.split(None, 5)
        if len(fields) == 6 and fields[-1].startswith('/') and Path(fields[-1]).is_file():
            paths.add(Path(fields[-1]).resolve())
    return sorted(paths)


def verify_runtime(stage: Path, expected: dict) -> dict:
    """! @brief 고정 Python 패키지, 구현, native 감사 해시와 Qt 부재를 확인한다."""
    require(sys.platform == 'linux' and sys.prefix != sys.base_prefix, '격리 Linux solver venv가 필요합니다.', 'E_VERSION')
    raw = (stage / 'runtime.json').read_bytes()
    require(len(raw) <= 1024 * 1024 and hashlib.sha256(raw).hexdigest() == expected.get('manifest_sha256'), '런타임 명세 봉인이 다릅니다.', 'E_HASH')
    runtime = json.loads(raw)
    require(runtime.get('schema') == 'rfad.openems-worker-runtime/0.1', '런타임 명세 버전을 지원하지 않습니다.', 'E_VERSION')
    code_files = expected.get('code_files', [])
    require(code_files and any(record['path'] == 'tools/openems_worker.py' for record in code_files), 'worker 구현 해시가 없습니다.', 'E_HASH')
    for record in code_files:
        relative = PurePosixPath(record['path'])
        require(not relative.is_absolute() and '..' not in relative.parts and relative.parts[0] in ('src', 'tools'), '구현 경로가 올바르지 않습니다.', 'E_HASH')
        actual = file_identity(stage.joinpath(*relative.parts))
        require(all(actual[key] == record[key] for key in actual), '실행 구현의 해시가 다릅니다.', 'E_HASH')
    manifest, audit = runtime['python_manifest'], runtime['native_audit']
    require(platform.python_version() == manifest['python']['validated_version'] and platform.machine().lower() == manifest['python']['architecture'].lower(), 'Python 또는 CPU 버전이 고정 명세와 다릅니다.', 'E_VERSION')
    installed = {re.sub(r'[-_.]+', '-', item.metadata['Name']).lower(): item.version for item in importlib.metadata.distributions()}
    require(not any(re.match(r'^(pyqt|pyside|shiboken|qt[0-9-])', name) for name in installed), 'Qt 패키지가 감지되었습니다.', 'E_VERSION')
    require(audit.get('status') == 'passed' and audit.get('qt_found') is False, '승인된 native 감사 결과가 필요합니다.', 'E_VERSION')
    require(installed == audit['packages'], '설치 패키지가 캡처한 native 감사와 다릅니다.', 'E_VERSION')
    for package in manifest['packages']:
        require(installed.get(package['name']) == package['version'], '고정 Python 패키지 버전이 다릅니다: ' + package['name'], 'E_VERSION')
    native_files = {}
    for record in audit['native_files']:
        path = Path(record['path']).resolve()
        require(path.is_relative_to('/home/tracewave/rfad-runtime'), 'native 감사 경로가 고정 런타임 밖입니다.', 'E_VERSION')
        identity = file_identity(path)
        require(identity['sha256'] == record['sha256'], 'native 라이브러리 해시가 다릅니다: ' + str(path), 'E_HASH')
        native_files[str(path)] = identity
    require(str(EXECUTABLE) in native_files and installed.get('openems') == '0.37.0' and installed.get('csxcad') == '0.7.0', '필수 openEMS/CSXCAD 런타임이 다릅니다.', 'E_VERSION')
    import CSXCAD
    import openEMS

    require(CSXCAD.__version__ == '0.7.0' and openEMS.__version__ == '0.37.0', '로드된 solver 모듈 버전이 다릅니다.', 'E_VERSION')
    loaded = _validate_mapped(_mapped_files(), native_files)
    require(any('libopenEMS' in record['path'] for record in loaded), '실제 openEMS native 로딩이 확인되지 않았습니다.', 'E_VERSION')
    return {'schema': 'rfad.openems-runtime-observation/0.1', 'python': platform.python_version(),
            'python_executable': {'path': str(Path(sys.executable).resolve()), **file_identity(Path(sys.executable).resolve())},
            'packages': installed, 'manifest_sha256': expected['manifest_sha256'], 'code_files': code_files,
            'native_files': [{'path': path, **identity} for path, identity in native_files.items()],
            'loaded_native_files': loaded, 'qt_found': False}


def _validate_mapped(paths: list[Path], native_files: dict) -> list[dict]:
    """! @brief 실제 로딩한 solver/VTK 파일을 감사한 경로와 해시로 대조한다."""
    require(not any(re.search(r'libQt[0-9]', path.name) for path in paths), 'native Qt 라이브러리가 감지되었습니다.', 'E_VERSION')
    loaded = []
    for path in paths:
        if any(token in path.name.lower() for token in ('openems', 'csxcad', 'fparser', 'nf2ff', 'libvtk')):
            require(str(path) in native_files, '감사하지 않은 native 라이브러리를 로딩했습니다.', 'E_VERSION')
            identity = file_identity(path)
            require(identity == native_files[str(path)], '로드된 native 라이브러리 해시가 다릅니다.', 'E_HASH')
            loaded.append({'path': str(path), **identity})
    return loaded


def prepare(stage: Path, plan: dict, runtime: dict) -> tuple[dict, list[dict]]:
    """! @brief 실제 CSXCAD 격자와 native XML을 만들되 FDTD는 실행하지 않는다."""
    import numpy as np
    import CSXCAD
    import openEMS
    from rfad.application.solver import normalization_contract

    output = stage / 'output' / 'prepared'
    output.mkdir()
    case = plan['case']
    target = case['mesh']['grid_mm']
    structure = CSXCAD.ContinuousStructure()
    solver = openEMS.openEMS(NrTS=20000, EndCriteria=END_CRITERION)
    solver.SetCSX(structure)
    solver.SetGaussExcite(10e9, 2e9)
    solver.SetBoundaryCond(case['boundary_conditions'])
    grid = structure.GetGrid()
    grid.SetDeltaUnit(0.001)
    lines = {'x': np.linspace(0, 20, math.ceil(20 / target) + 1),
             'y': np.linspace(0, 10, math.ceil(10 / target) + 1)}
    critical = case['mesh']['critical_z_mm']
    lines['z'] = sorted({float(value) for start, stop in zip(critical, critical[1:])
                         for value in np.linspace(start, stop, math.ceil((stop - start) / target) + 1)})
    for axis, values in lines.items():
        grid.AddLine(axis, values)
    for port in case['ports']:
        solver.AddRectWaveGuidePort(port['number'], port['start_mm'], port['stop_mm'], 'z', 0.020, 0.010, 'TE10', excite=port['excite'])
    xml_path = output / 'waveguide.xml'
    solver.Write2XML(str(xml_path))
    xml = ET.parse(xml_path)
    require(xml.getroot().tag == 'openEMS', 'native XML 루트가 올바르지 않습니다.')
    native_lines = {axis: [float(value) for value in grid.GetLines(axis)] for axis in ('x', 'y', 'z')}
    counts = [len(native_lines[axis]) for axis in ('x', 'y', 'z')]
    mesh = {'schema': 'rfad.openems-mesh/0.1', 'grid_mm': target, 'native_length_unit': 'mm', 'delta_unit_m': 0.001,
            'lines_mm': native_lines, 'line_counts': counts, 'interval_counts': [count - 1 for count in counts],
            'native_grid_points': math.prod(counts), 'yee_interval_cells': math.prod(count - 1 for count in counts),
            'pml_cells_per_end': 8, 'native_preprocessing_executed': False, 'fdtd_executed': False}
    consumption = {'schema': 'rfad.openems-consumption/0.1', 'analysis_plan_id': plan['plan_id'],
                   'source': 'explicit_reference_case', 'consumed_case': case,
                   'project_geometry_consumed': False, 'project_materials_consumed': False,
                   'material': 'vacuum', 'walls': 'PEC boundary', 'approximations': ['PEC ideal wall', 'vacuum lossless medium', 'Cartesian Yee grid', '8-cell PML at both z ends'],
                   'unsupported': ['arbitrary_project_geometry', 'IFA', 'NF2FF'], 'fdtd_executed': False}
    normalization = normalization_contract()
    values = [('mesh.json', 'mesh_statistics', mesh), ('consumption.json', 'consumption_report', consumption),
              ('normalization.json', 'normalization', normalization), ('runtime.json', 'runtime_provenance', runtime)]
    files = [descriptor(stage, xml_path, 'native_input')]
    for name, role, data in values:
        write_json(output / name, data)
        files.append(descriptor(stage, output / name, role))
    artifact = {'schema': 'rfad.preparation-artifact/0.1', 'analysis_plan_id': plan['plan_id'],
                'analysis_plan_hash': canonical_hash(plan), 'profile': plan['analysis_profile'], 'files': files,
                'mesh_statistics': mesh, 'normalization': normalization, 'consumption_report': consumption,
                'runtime_identity': runtime}
    write_json(output / 'preparation.json', artifact)
    return artifact, files + [descriptor(stage, output / 'preparation.json', 'preparation_artifact')]


def _check_preparation(request: dict, inputs: dict[str, Path]) -> dict:
    """! @brief 후속 실행에 전달된 native 입력과 준비 artifact의 봉인을 대조한다."""
    preparation = request['preparation']
    plan = request['analysis_plan']
    prepared_plan = request['prepared_plan']
    require(prepared_plan.get('schema') == 'rfad.prepared-plan/0.1' and prepared_plan.get('validation_state') == 'prepared', '실행에는 유효한 PreparedPlan이 필요합니다.', 'E_VERSION')
    require(prepared_plan['analysis_plan']['plan_id'] == plan['plan_id'] and prepared_plan['analysis_plan']['content_hash'] == canonical_hash(plan)
            and prepared_plan['snapshot'] == plan['snapshot'], 'PreparedPlan의 계획 또는 스냅샷 참조가 다릅니다.', 'E_HASH')
    preparation_bytes = canonical_bytes(preparation)
    require(prepared_plan['preparation_artifact']['sha256'] == hashlib.sha256(preparation_bytes).hexdigest()
            and prepared_plan['preparation_artifact']['bytes'] == len(preparation_bytes), 'PreparedPlan의 준비 artifact 봉인이 다릅니다.', 'E_HASH')
    require(preparation['analysis_plan_id'] == plan['plan_id'] and preparation['analysis_plan_hash'] == canonical_hash(plan), '준비 산출물이 AnalysisPlan과 다릅니다.', 'E_HASH')
    require(preparation['schema'] == 'rfad.preparation-artifact/0.1', '준비 artifact 버전이 다릅니다.', 'E_VERSION')
    for record in preparation['files']:
        require(record['role'] in inputs, '준비 입력 파일이 누락되었습니다: ' + record['role'], 'E_MISSING_ARTIFACT')
        actual = file_identity(inputs[record['role']])
        require(all(actual[key] == record[key] for key in actual), '준비 산출물 바이트가 다릅니다.', 'E_HASH')
    require('native_input' in inputs, '준비된 native XML이 없습니다.', 'E_MISSING_ARTIFACT')
    for role, value in [('mesh_statistics', preparation['mesh_statistics']), ('consumption_report', preparation['consumption_report']),
                        ('normalization', preparation['normalization']), ('runtime_provenance', preparation['runtime_identity'])]:
        require(role in inputs and json.loads(inputs[role].read_bytes()) == value, '준비 요약과 실제 artifact가 다릅니다.', 'E_HASH')
    return preparation


def solve(stage: Path, request: dict, inputs: dict[str, Path], runtime: dict) -> tuple[dict, list[dict]]:
    """! @brief 준비 때 봉인한 XML을 그대로 native CLI에 전달하고 종료 근거를 보존한다."""
    preparation = _check_preparation(request, inputs)
    raw = stage / 'output' / 'raw'
    raw.mkdir()
    shutil.copyfile(inputs['native_input'], raw / 'waveguide.xml')
    require(file_identity(raw / 'waveguide.xml') == file_identity(inputs['native_input']), '실행 XML 복사본이 다릅니다.', 'E_HASH')
    command = [str(EXECUTABLE), 'waveguide.xml', '--engine=multithreaded', '--numThreads=2', '--dump-statistics', '--exact-endcriteria']
    started = time.monotonic()
    mapped = set()
    with (raw / 'native.log').open('xb') as stream:
        child = subprocess.Popen(command, cwd=raw, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT)
        try:
            while child.poll() is None:
                mapped.update(_mapped_files(child.pid))
                require((raw / 'native.log').stat().st_size <= MAX_FILE_BYTES, 'native 로그 크기 제한을 초과했습니다.', 'E_RESOURCE')
                time.sleep(0.02)
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()
    require(child.returncode == 0, 'native solver가 정상 종료하지 않았습니다.', 'E_SOLVER')
    require(file_identity(raw / 'waveguide.xml') == file_identity(inputs['native_input']), 'native 실행 중 XML이 변경되었습니다.', 'E_HASH')
    native_files = {record['path']: {key: record[key] for key in ('bytes', 'sha256')} for record in runtime['native_files']}
    actual_loaded = _validate_mapped(sorted(mapped), native_files)
    require(any('libopenEMS' in record['path'] for record in actual_loaded), 'CLI의 실제 native 로딩이 확인되지 않았습니다.', 'E_VERSION')
    statistics = read_statistics(raw / 'openEMS_stats.txt')
    termination = check_termination((raw / 'native.log').read_text(encoding='utf-8'), statistics['iterations'])
    require(statistics['native_cells'] == preparation['mesh_statistics']['native_grid_points'], 'native 격자 통계가 준비한 격자와 다릅니다.', 'E_SOLVER')
    files = [descriptor(stage, raw / name, 'raw/' + name) for name in RAW_NAMES]
    execution = {'command': command, 'elapsed_seconds': time.monotonic() - started, 'exit_code': child.returncode,
                 'loaded_native_files': actual_loaded, 'statistics': statistics, 'termination': termination,
                 'native_input_sha256': file_identity(raw / 'waveguide.xml')['sha256']}
    manifest = {'schema': 'rfad.openems-raw/0.1', 'complete': True, 'analysis_plan_id': request['analysis_plan']['plan_id'],
                'analysis_plan_hash': canonical_hash(request['analysis_plan']), 'prepared_plan_id': request['prepared_plan']['prepared_plan_id'],
                'prepared_plan_hash': canonical_hash(request['prepared_plan']), 'files': files, 'execution': execution}
    write_json(stage / 'output' / 'raw_manifest.json', manifest)
    return manifest, files + [descriptor(stage, stage / 'output' / 'raw_manifest.json', 'raw_manifest')]


def read_statistics(path: Path) -> dict:
    """! @brief openEMS 0.37.0 통계의 유한성과 timestep 상한을 검사한다."""
    values = [float(line.split()[0]) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    require(len(values) >= 6 and all(math.isfinite(value) for value in values), 'native 통계가 불완전합니다.', 'E_SOLVER')
    require(values[0] == int(values[0]) and values[2] == int(values[2]) and 0 < values[2] < 20000, 'native timestep 또는 격자 통계가 유효하지 않습니다.', 'E_SOLVER')
    return {'native_cells': int(values[0]), 'timestep_seconds': values[1], 'iterations': int(values[2]), 'raw_values': values}


def normalize_probes(directory: Path) -> list[dict]:
    """! @brief 모델 재생성 없이 보존한 모드 probe의 시간축에서 S11/S21/Z를 계산한다.

    @details openEMS 0.37.0 pulse DFT와 동일한 exp(-j*2*pi*f*t), 2*dt 규약이다.
    수동 포트의 방향은 -z이므로 출력 전달파는 uf_ref이다. 기준면 이동은 없다.
    """
    import numpy as np

    frequencies = np.linspace(9.5e9, 10.5e9, 31)
    spectra = {}
    for name in RAW_NAMES[:4]:
        data = np.loadtxt(directory / name, comments=('#', '%'))
        require(data.ndim == 2 and data.shape[0] >= 3 and data.shape[1] >= 2 and np.all(np.isfinite(data)), 'raw 포트 데이터가 불완전하거나 유한하지 않습니다.', 'E_MISSING_ARTIFACT')
        times, values = data[:, 0], data[:, 1]
        steps = np.diff(times)
        require(np.all(steps > 0) and np.allclose(steps, steps[0], rtol=5e-4, atol=0), 'raw 포트 시간축이 균일하지 않습니다.', 'E_SOLVER')
        spectra[name] = np.array([2 * steps[0] * np.sum(values * np.exp(-1j * 2 * np.pi * frequency * times)) for frequency in frequencies])
    impedance_reference = np.array([analytic_te10(float(frequency))[0] for frequency in frequencies])
    inlet_u, inlet_i = spectra['port_ut_1'], spectra['port_it_1']
    incident = 0.5 * (inlet_u + inlet_i * impedance_reference)
    reflected = inlet_u - incident
    outgoing = 0.5 * (spectra['port_ut_2'] - spectra['port_it_2'] * impedance_reference)
    peak = np.max(np.abs(incident))
    require(peak > 1e-18 and np.all(np.abs(incident) > peak * 1e-4) and np.all(np.abs(inlet_i) > 1e-24), '포트 여기 또는 전류가 정규화하기에 너무 작습니다.', 'E_SOLVER')
    s11, s21, impedance = reflected / incident, outgoing / incident, inlet_u / inlet_i
    require(all(np.all(np.isfinite(array)) for array in (s11, s21, impedance)), '정규화 포트 결과가 유한하지 않습니다.', 'E_SOLVER')
    return [{'frequency_hz': float(frequency), 's11': [float(a.real), float(a.imag)], 's21': [float(b.real), float(b.imag)],
             'impedance_ohm': [float(c.real), float(c.imag)]} for frequency, a, b, c in zip(frequencies, s11, s21, impedance)]


def postprocess(stage: Path, request: dict, inputs: dict[str, Path], runtime: dict, manifest: dict | None = None) -> tuple[dict, list[dict]]:
    """! @brief 완료된 raw 봉인만 검증하고 독립 후처리를 수행한다. solver를 실행하지 않는다."""
    preparation = _check_preparation(request, inputs)
    files = []
    raw = stage / 'output' / 'raw'
    if manifest is None:
        require('raw_manifest' in inputs, '완료된 raw manifest가 없습니다.', 'E_MISSING_ARTIFACT')
        manifest = json.loads(inputs['raw_manifest'].read_bytes())
        require(manifest.get('complete') is True and manifest.get('schema') == 'rfad.openems-raw/0.1', 'raw manifest가 완료 상태가 아닙니다.', 'E_MISSING_ARTIFACT')
        require(manifest['analysis_plan_hash'] == canonical_hash(request['analysis_plan']) and manifest['prepared_plan_hash'] == canonical_hash(request['prepared_plan']), 'raw manifest의 계획 봉인이 다릅니다.', 'E_HASH')
        records = manifest.get('files')
        expected_roles = {'raw/' + name for name in RAW_NAMES}
        require(type(records) is list and len(records) == len(RAW_NAMES)
                and all(type(record) is dict and type(record.get('role')) is str for record in records)
                and {record['role'] for record in records} == expected_roles,
                'raw manifest는 중복 없이 모든 필수 native 파일을 포함해야 합니다.', 'E_MISSING_ARTIFACT')
        raw.mkdir()
        for record in records:
            role = record['role']
            require(record.get('path') == 'output/' + role, 'raw manifest의 파일 경로와 역할이 다릅니다.', 'E_HASH')
            require(role in inputs, 'raw 파일이 누락되었습니다.', 'E_MISSING_ARTIFACT')
            identity = file_identity(inputs[role])
            require(all(identity[key] == record[key] for key in identity), 'raw 파일의 봉인이 다릅니다.', 'E_HASH')
            shutil.copyfile(inputs[role], raw / role.split('/')[1])
        files = [descriptor(stage, raw / name, 'raw/' + name) for name in RAW_NAMES]
        write_json(stage / 'output' / 'raw_manifest.json', manifest)
        files.append(descriptor(stage, stage / 'output' / 'raw_manifest.json', 'raw_manifest'))
    require(file_identity(raw / 'waveguide.xml') == file_identity(inputs['native_input']), 'raw 결과가 준비한 XML과 다릅니다.', 'E_HASH')
    statistics = read_statistics(raw / 'openEMS_stats.txt')
    termination = check_termination((raw / 'native.log').read_text(encoding='utf-8'), statistics['iterations'])
    require(manifest['execution']['statistics'] == statistics and manifest['execution']['termination'] == termination,
            'raw 실행 보고와 실제 통계 또는 종료 로그가 다릅니다.', 'E_HASH')
    samples = normalize_probes(raw)
    assessment = assess_samples(samples)
    require(assessment['passed'], 'TE10 참조 사례의 물리 정확도 허용 범위를 벗어났습니다.', 'E_SOLVER')
    provenance = {'schema': 'rfad.openems-provenance/0.1', 'run_id': request['run_id'], 'nonce': request['nonce'],
                  'execution_mode': request['phase'], 'analysis_plan': request['analysis_plan'], 'prepared_plan': request['prepared_plan'],
                  'preparation': preparation, 'runtime': runtime, 'raw_manifest': manifest}
    result = {'schema': 'rfad.openems-result/0.1', 'analysis_plan_id': request['analysis_plan']['plan_id'],
              'prepared_plan_id': request['prepared_plan']['prepared_plan_id'], 'samples': samples, 'assessment': assessment,
              'limits': LIMITS, 'termination': termination, 'native_statistics': statistics,
              'mesh_statistics': preparation['mesh_statistics'], 'normalization': preparation['normalization'],
              'provenance': provenance, 'raw_manifest': manifest}
    write_json(stage / 'output' / 'normalized.json', result)
    write_json(stage / 'output' / 'provenance.json', provenance)
    files.extend([descriptor(stage, stage / 'output' / 'normalized.json', 'normalized_result'),
                  descriptor(stage, stage / 'output' / 'provenance.json', 'provenance')])
    return result, files


def execute(request: dict, stage: Path) -> dict:
    """! @brief 검증한 계획의 단계 하나만 실행하고 봉인 대상 파일을 반환한다."""
    from rfad.application.solver import validate_reference_plan

    require(request.get('schema') == 'rfad.openems-worker/0.1' and request.get('phase') in ('prepare', 'analysis', 'postprocess_only'), 'worker 요청 버전 또는 단계가 올바르지 않습니다.', 'E_INVALID_ARGUMENT')
    validate_reference_plan(request['analysis_plan'])
    require(request['analysis_plan']['runtime_identity'] == request['runtime'], '요청 runtime이 AnalysisPlan에서 고정한 runtime과 다릅니다.', 'E_HASH')
    inputs = input_index(stage, request.get('input_files', []))
    runtime = verify_runtime(stage, request['runtime'])
    output = stage / 'output'
    output.mkdir(exist_ok=True)
    phase = request['phase']
    result = {'schema': 'rfad.openems-worker-result/0.1', 'phase': phase, 'run_id': request['run_id'], 'nonce': request['nonce'],
              'analysis_plan_id': request['analysis_plan']['plan_id']}
    if phase == 'prepare':
        write_json(stage / 'progress.json', {'phase': 'preparing'})
        result['preparation'], result['files'] = prepare(stage, request['analysis_plan'], runtime)
    else:
        manifest = None
        files = []
        if phase == 'analysis':
            write_json(stage / 'progress.json', {'phase': 'running'})
            manifest, files = solve(stage, request, inputs, runtime)
        write_json(stage / 'progress.json', {'phase': 'postprocessing'})
        result['result'], post_files = postprocess(stage, request, inputs, runtime, manifest)
        result['files'] = files + post_files
    return result
