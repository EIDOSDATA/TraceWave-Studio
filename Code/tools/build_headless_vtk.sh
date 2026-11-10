#!/usr/bin/env bash
# @file
# @brief 고정한 VTK 소스로 네 가지 I/O 모듈과 필수 전이 의존성을 Qt 없이 빌드한다.
# @param 1 Linux 런타임 루트. 기본값은 /home/tracewave/rfad-runtime이다.
# @param 2 빌드 병렬 수. 기본값 4이며 최대 4이다.
# @param 3 이미 받은 소스 archive 경로. 생략하면 공식 고정 URL에서 내려받는다.
# @details root 실행과 기존 경로 덮어쓰기를 거부한다. 제품 렌더링용 VTK가 아니다.
set -euo pipefail

runtime_root="${1:-/home/tracewave/rfad-runtime}"
jobs="${2:-4}"
source_archive="${3:-}"
vtk_version='9.3.1'
vtk_commit='4f02ae83179c6a1542ac3c335c73dea976578c63'
vtk_digest='2d2da63dc660016628fc41c3a201e24d49a7e67b0d5d6fbbe655fb23f5099929'
vtk_url="https://codeload.github.com/Kitware/VTK/tar.gz/${vtk_commit}"

if [[ "${EUID}" == '0' ]]; then
    printf '%s\n' 'Run as the dedicated unprivileged Linux development user.' >&2
    exit 2
fi
if [[ ! "${jobs}" =~ ^[1-4]$ ]]; then
    printf '%s\n' 'Build jobs must be an integer from 1 to 4.' >&2
    exit 2
fi
if [[ "${runtime_root}" != /* || "${runtime_root}" == '/' ]]; then
    printf '%s\n' 'The runtime root must be an explicit non-root absolute directory.' >&2
    exit 2
fi
mkdir -p "${runtime_root}"
runtime_root="$(realpath "${runtime_root}")"
vtk_root="${runtime_root}/vtk/${vtk_version}"
source_dir="${vtk_root}/source"
build_dir="${vtk_root}/build"
install_dir="${vtk_root}/install"
mkdir -p "${vtk_root}"

if [[ -z "${source_archive}" ]]; then
    source_archive="${vtk_root}/vtk-${vtk_version}.tar.gz"
    if [[ ! -f "${source_archive}" ]]; then
        python3 - "${vtk_url}" "${source_archive}" <<'PY'
"""! @brief 검증할 archive를 공식 고정 commit URL에서 받는다."""
from pathlib import Path
import sys
import urllib.request
destination = Path(sys.argv[2])
partial = destination.with_suffix(destination.suffix + '.part')
urllib.request.urlretrieve(sys.argv[1], partial)
partial.replace(destination)
PY
    fi
fi
printf '%s  %s\n' "${vtk_digest}" "${source_archive}" | sha256sum --check --status

if [[ -d "${source_dir}" ]]; then
    if [[ ! -f "${source_dir}/.rfad-source-sha256" ]] || [[ "$(cat "${source_dir}/.rfad-source-sha256")" != "${vtk_digest}" ]]; then
        printf '%s\n' 'Existing source is not marked with the pinned archive identity; inspect it manually.' >&2
        exit 2
    fi
else
    python3 - "${source_archive}" "${source_dir}" "${vtk_commit}" "${vtk_digest}" <<'PY'
"""! @brief 고정 archive를 새 staging 경로에 안전하게 풀고 완성된 소스만 게시한다."""
from pathlib import Path
import sys
import tarfile
archive, destination, commit, digest = sys.argv[1:]
destination = Path(destination)
staging = destination.with_name('extract-staging')
if staging.exists():
    raise RuntimeError('Incomplete extraction remains; inspect the staging directory before retrying.')
staging.mkdir()
with tarfile.open(archive) as source:
    source.extractall(staging, filter='data')
extracted = staging / ('VTK-' + commit)
if not (extracted / 'CMakeLists.txt').is_file():
    raise RuntimeError('Unexpected VTK archive layout.')
(extracted / '.rfad-source-sha256').write_text(digest + '\n', encoding='ascii')
extracted.rename(destination)
staging.rmdir()
PY
fi

cmake -S "${source_dir}" -B "${build_dir}" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CXX_FLAGS_RELEASE='-O2 -DNDEBUG' \
    -DCMAKE_C_FLAGS_RELEASE='-O2 -DNDEBUG' \
    -DCMAKE_INSTALL_PREFIX="${install_dir}" \
    -DCMAKE_INSTALL_LIBDIR=lib \
    -DCMAKE_INSTALL_RPATH="${install_dir}/lib" \
    -DBUILD_SHARED_LIBS=ON \
    -DVTK_BUILD_ALL_MODULES=OFF \
    -DVTK_BUILD_TESTING=OFF \
    -DVTK_BUILD_EXAMPLES=OFF \
    -DVTK_ENABLE_WRAPPING=OFF \
    -DVTK_WRAP_PYTHON=OFF \
    -DVTK_WRAP_JAVA=OFF \
    -DVTK_USE_MPI=OFF \
    -DVTK_SMP_IMPLEMENTATION_TYPE=Sequential \
    -DVTK_GROUP_ENABLE_StandAlone=DONT_WANT \
    -DVTK_GROUP_ENABLE_Rendering=DONT_WANT \
    -DVTK_GROUP_ENABLE_Qt=NO \
    -DVTK_GROUP_ENABLE_Tk=NO \
    -DVTK_GROUP_ENABLE_MPI=NO \
    -DVTK_GROUP_ENABLE_Web=NO \
    -DVTK_MODULE_ENABLE_VTK_IOXML=YES \
    -DVTK_MODULE_ENABLE_VTK_IOGeometry=YES \
    -DVTK_MODULE_ENABLE_VTK_IOLegacy=YES \
    -DVTK_MODULE_ENABLE_VTK_IOPLY=YES
cmake --build "${build_dir}" --parallel "${jobs}"
cmake --install "${build_dir}"

python3 - "${install_dir}" "${vtk_root}" "${vtk_commit}" "${vtk_digest}" <<'PY'
"""! @brief 설치된 모든 VTK 공유 라이브러리의 동적 의존성을 기록하고 Qt를 거부한다."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys
prefix, report_root, commit, digest = sys.argv[1:]
prefix = Path(prefix)
libraries = sorted({item.resolve() for item in (prefix / 'lib').glob('*.so*')})
if not libraries:
    raise RuntimeError('No installed shared libraries found.')
results = []
for library in libraries:
    query = subprocess.run(['ldd', str(library)], text=True, capture_output=True, timeout=15, check=True)
    output = query.stdout + query.stderr
    if 'not found' in output or re.search(r'libQt[456]|libvtk[^\s]*Qt', output, re.IGNORECASE):
        raise RuntimeError('Missing or forbidden dynamic dependency: ' + str(library) + '\n' + output)
    results.append({'name': library.name, 'sha256': hashlib.sha256(library.read_bytes()).hexdigest(), 'ldd': output.splitlines()})
report = {
    'schema': 'rfad.runtime.vtk-build/0.1',
    'status': 'passed',
    'checked_at_utc': datetime.now(timezone.utc).isoformat(),
    'version': '9.3.1',
    'commit': commit,
    'source_archive_sha256': digest,
    'prefix': str(prefix),
    'library_count': len(results),
    'qt_dynamic_dependencies': [],
    'libraries': results,
    'scope': 'headless I/O dependency build; no rendering or solver accuracy claim',
}
destination = Path(report_root) / 'build-report.json'
destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'status': 'passed', 'library_count': len(results), 'report': str(destination)}))
PY
