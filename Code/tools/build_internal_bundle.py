"""! @brief 소스와 Windows GUI의 내부 검증 묶음을 해시 목록과 함께 생성한다."""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def build(root, output):
    """! @brief 원문 자료/사용자 프로젝트/가상환경을 제외한 명시적 입력만 새 묶음에 넣는다."""
    root, output = Path(root), Path(output)
    if output.exists():
        raise ValueError("새 출력 경로가 필요합니다.")
    files = {path for directory in ('src', 'tools', 'ui', 'docs', 'fixtures', 'runtime_profiles', 'tests')
             for path in (root / directory).rglob('*')
             if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc'}
    files.update(root / name for name in ('README.md', 'CMakeLists.txt', 'CMakePresets.json', '.clang-format', '.editorconfig'))
    files.add(root / 'build/windows-release/bin/tracewave_gui.exe')
    entries = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            data = path.read_bytes()
            relative = path.relative_to(root).as_posix()
            entries.append({'path': relative, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
            archive.writestr(relative, data)
        manifest = {'schema': 'rfad.internal-bundle/0.1', 'distribution': 'internal_validation_only',
                    'design_baseline': 'RFAD-D0-3.4', 'files': entries,
                    'setup_required': ['Python service environment', 'approved CAD environment', 'WSL openEMS runtime',
                                       'external PCB catalog source package', 'third-party license review before external release'],
                    'turnkey_installation': False, 'physics_validated': False}
        archive.writestr('bundle-manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(output) as archive:
        for entry in entries:
            if hashlib.sha256(archive.read(entry['path'])).hexdigest() != entry['sha256']:
                raise ValueError('묶음의 파일 해시가 다릅니다: ' + entry['path'])
    return {'path': str(output), 'files': len(entries), 'bytes': output.stat().st_size,
            'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'status': 'contents_verified'}


def main():
    """! @brief 배포나 업로드 없이 로컬 새 ZIP만 만든다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(Path(__file__).resolve().parents[1], args.output), ensure_ascii=False))


if __name__ == '__main__':
    main()
