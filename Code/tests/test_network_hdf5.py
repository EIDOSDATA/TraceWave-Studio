"""! @brief 고정 HDF5 배열/출처 왕복과 위험 저장 구조의 선행 차단을 검증한다."""

from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.adapters import network_hdf5
from rfad.application.canonical import canonical_bytes
from rfad.domain.errors import ProjectError
from rfad.domain.network_data import make_dataset


def fixture(kind="S", ports=2):
    """! @brief 비상호 행렬, 포트별 복소 Z0와 원문 미정 조건을 만든다."""
    matrices = [[[[.1, -.2], [.3, .4]], [[.5, .6], [.7, -.8]]],
                [[[.2, -.1], [.4, .3]], [[.6, .5], [.8, -.7]]]]
    if ports == 1:
        matrices = [[[[.1, -.2]]], [[[.3, .4]]]]
    return make_dataset(parameter_kind=kind, frequency_hz=[0, 2.45e9],
                        port_ids=[str(uuid4()) for _ in range(ports)], values_ri=matrices,
                        port_names=["급전 " + str(index + 1) for index in range(ports)],
                        z0_ohm=[[[50 + index, index] for index in range(ports)] for _ in range(2)],
                        provenance={"source_file": "원문 측정 아닌 합성 검증 자료", "original_reference_plane": None},
                        conditions={"manufacturing": None, "measurement": None}, source_refs=["독립 합성 배열"])


@unittest.skipUnless(importlib.util.find_spec("h5py"), "고정 h5py 교환 환경이 필요합니다.")
class NetworkHdf5Tests(unittest.TestCase):
    """! @brief 실제 HDF5 엔진에서 유한 profile만 교환하는지 검증한다."""

    def mutate(self, raw, callback):
        """! @brief 실제 파일 접근 없이 변조된 파일 image를 구성한다."""
        import h5py
        with h5py.File.in_memory(raw) as handle:
            callback(handle, h5py)
            handle.flush()
            return handle.id.get_file_image()

    def test_roundtrip_all_kinds_and_exact_array_layout(self):
        """! @brief 복소 축/단위/포트 순서와 미정 출처를 S/Z/Y 각각 왕복한다."""
        import h5py
        for kind in ("S", "Z", "Y"):
            data = fixture(kind)
            before = deepcopy(data)
            raw = network_hdf5.encode_network_hdf5(data)
            self.assertEqual(network_hdf5.decode_network_hdf5(raw), before)
            self.assertEqual(data, before)
            with h5py.File.in_memory(raw) as handle:
                matrix = handle[kind.lower()]
                self.assertEqual(matrix.shape, (2, 2, 2, 2))
                self.assertEqual(matrix.dtype.str, "<f8")
                self.assertIsNone(matrix.chunks)
                self.assertIsNone(matrix.compression)
                self.assertEqual(handle["port_ids"][...].tolist(), [identity.encode() for identity in data["port_ids"]])
                self.assertEqual(handle["metadata_json"][...].tobytes(), canonical_bytes(data))

    def test_repeated_encoding_ignores_clock_and_runtime_names(self):
        """! @brief 시간이 달라진 재검토에서도 전체 HDF5 bytes가 동일해야 한다."""
        data = fixture()
        first = network_hdf5.encode_network_hdf5(data)
        time.sleep(1.05)
        self.assertEqual(network_hdf5.encode_network_hdf5(data), first)
        self.assertEqual(network_hdf5.encode_network_hdf5(network_hdf5.decode_network_hdf5(first)), first)

    def test_null_and_masked_finite_values_remain_distinct(self):
        """! @brief 미정/null과 유효하지 않은 원문 숫자를 같은 0으로 만들지 않는다."""
        import h5py
        import numpy as np
        data = fixture()
        data["z0_ohm"][0][1] = None
        data["values_ri"][0][0][1] = None
        data["valid_mask"][0][0][1] = False
        data["sample_status"][0][0][1] = "missing"
        data["valid_mask"][1][1][0] = False
        data["sample_status"][1][1][0] = "outside_validity"
        raw = network_hdf5.encode_network_hdf5(data)
        self.assertEqual(network_hdf5.decode_network_hdf5(raw), data)
        with h5py.File.in_memory(raw) as handle:
            self.assertTrue(np.isnan(handle["s"][0, 0, 1]).all())
            self.assertEqual(handle["network_value_present"][0, 0, 1], 0)
            self.assertEqual(handle["valid_mask"][1, 1, 0], 0)
            self.assertEqual(handle["network_value_present"][1, 1, 0], 1)
            self.assertTrue(np.isfinite(handle["s"][1, 1, 0]).all())
        data["z0_ohm"] = None
        self.assertIsNone(network_hdf5.decode_network_hdf5(network_hdf5.encode_network_hdf5(data))["z0_ohm"])

    def test_array_metadata_and_nonfinite_tampering_is_rejected(self):
        """! @brief metadata와 독립 배열이 충돌하거나 유효 셀에 NaN이 들어가면 거절한다."""
        raw = network_hdf5.encode_network_hdf5(fixture())
        for name, position, value in (("s", (0, 0, 0, 0), 999), ("s", (0, 0, 0, 0), float("nan")),
                                      ("valid_mask", (0, 0, 0), 0), ("sample_status", (0, 0, 0), 1),
                                      ("frequency_hz", 0, 123), ("z0_ohm", (0, 1, 0), 999)):
            with self.subTest(name=name, value=value):
                changed = self.mutate(raw, lambda handle, _: handle[name].__setitem__(position, value))
                with self.assertRaises(ProjectError) as error:
                    network_hdf5.decode_network_hdf5(changed)
                self.assertEqual(error.exception.code, "E_HASH")

    def test_soft_external_links_and_external_storage_are_rejected_before_read(self):
        """! @brief 존재하지 않는 외부 파일도 열어보지 않고 저장 방식에서 차단한다."""
        raw = network_hdf5.encode_network_hdf5(fixture())
        for mode in ("soft", "external", "storage"):
            def alter(handle, h5py):
                del handle["s"]
                if mode == "soft":
                    handle["s"] = h5py.SoftLink("/does-not-exist")
                elif mode == "external":
                    handle["s"] = h5py.ExternalLink("not-opened-file.h5", "/matrix")
                else:
                    handle.create_dataset("s", shape=(2, 2, 2, 2), dtype="<f8", external=[("not-opened.raw", 0, 128)])
            changed = self.mutate(raw, alter)
            with self.subTest(mode=mode), self.assertRaises(ProjectError) as error:
                network_hdf5.decode_network_hdf5(changed)
            self.assertEqual(error.exception.code, "E_UNSUPPORTED")
        self.assertFalse(Path("not-opened.raw").exists())

    def test_vds_compression_chunk_and_oversized_shapes_are_rejected(self):
        """! @brief 외부 VDS와 필터/희소 거대 배열을 값 읽기 전에 거절한다."""
        raw = network_hdf5.encode_network_hdf5(fixture())
        for mode in ("virtual", "gzip", "chunk", "huge", "endian", "variable"):
            def alter(handle, h5py):
                del handle["s"]
                if mode == "virtual":
                    layout = h5py.VirtualLayout(shape=(2, 2, 2, 2), dtype="<f8")
                    layout[...] = h5py.VirtualSource("not-read-vds.h5", "source", shape=(2, 2, 2, 2))
                    handle.create_virtual_dataset("s", layout)
                elif mode == "gzip":
                    handle.create_dataset("s", shape=(2, 2, 2, 2), dtype="<f8", compression="gzip")
                elif mode == "chunk":
                    handle.create_dataset("s", shape=(2, 2, 2, 2), dtype="<f8", chunks=(1, 2, 2, 2))
                elif mode == "huge":
                    handle.create_dataset("s", shape=(2**30, 2, 2, 2), dtype="<f8")
                elif mode == "endian":
                    handle.create_dataset("s", shape=(2, 2, 2, 2), dtype=">f8")
                else:
                    handle.create_dataset("s", shape=(2, 2, 2, 2), dtype=h5py.string_dtype())
            changed = self.mutate(raw, alter)
            with self.subTest(mode=mode), self.assertRaises(ProjectError):
                network_hdf5.decode_network_hdf5(changed)

    def test_root_unknown_objects_attributes_and_alias_are_rejected(self):
        """! @brief 알 수 없는 metadata와 hard-link 별칭도 조용히 삭제하지 않는다."""
        raw = network_hdf5.encode_network_hdf5(fixture())
        for mode in ("extra", "attribute", "alias", "group"):
            def alter(handle, h5py):
                if mode == "extra":
                    handle.create_group("unknown")
                elif mode == "attribute":
                    handle.attrs["unknown"] = "value"
                elif mode == "alias":
                    del handle["network_value_present"]
                    handle["network_value_present"] = handle["valid_mask"]
                else:
                    del handle["s"]
                    handle.create_group("s")
            with self.subTest(mode=mode), self.assertRaises(ProjectError):
                network_hdf5.decode_network_hdf5(self.mutate(raw, alter))

    def test_invalid_json_schema_profile_signature_and_size_are_rejected(self):
        """! @brief 파서 상한과 canonical metadata의 불일치를 명시적으로 반환한다."""
        raw = network_hdf5.encode_network_hdf5(fixture())
        for payload in (b'{"schema":"x","schema":"y"}', b'{"value":NaN}', b"not json"):
            def alter(handle, _):
                import numpy as np
                del handle["metadata_json"]
                handle.create_dataset("metadata_json", data=np.frombuffer(payload, dtype="u1"))
            with self.assertRaises(ProjectError):
                network_hdf5.decode_network_hdf5(self.mutate(raw, alter))
        for invalid in (b"", b"not hdf5", raw[:100], raw + b"0" * network_hdf5.MAX_FILE_BYTES):
            with self.assertRaises(ProjectError):
                network_hdf5.decode_network_hdf5(invalid)

    def test_max_samples_two_ports_are_bounded_and_roundtrip(self):
        """! @brief 최대 표본/포트 자료가 원문 예산 안에서 정확히 왕복한다."""
        data = make_dataset(parameter_kind="S", frequency_hz=list(range(1001)), port_ids=[str(uuid4()), str(uuid4())],
                            values_ri=[[[[.1, .2], [.3, .4]], [[.5, .6], [.7, .8]]]] * 1001)
        raw = network_hdf5.encode_network_hdf5(data)
        self.assertLess(len(raw), network_hdf5.MAX_FILE_BYTES)
        self.assertEqual(network_hdf5.decode_network_hdf5(raw), data)


class Hdf5OptionalRuntimeTests(unittest.TestCase):
    """! @brief 선택 HDF5 모듈 부재가 일반 서비스 가져오기를 깨뜨리지 않게 한다."""

    def test_missing_runtime_is_explicit_and_does_not_mutate_input(self):
        """! @brief 미설치 환경에서 파일을 성공으로 만들거나 원본을 수정하지 않는다."""
        data = fixture()
        before = deepcopy(data)
        with patch("rfad.adapters.network_hdf5.import_module", side_effect=ImportError):
            with self.assertRaises(ProjectError) as error:
                network_hdf5.encode_network_hdf5(data)
        self.assertEqual(error.exception.code, "E_CAPABILITY")
        self.assertEqual(data, before)

    def test_capabilities_import_does_not_import_native_modules(self):
        """! @brief 별도 Python 프로세스에서 capabilities의 native 비의존성을 검사한다."""
        program = """import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in ('h5py', 'numpy'):
        raise RuntimeError('native import: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from rfad.adapters.network_hdf5 import installation_metadata
print(installation_metadata()['runtime_checked'])
"""
        result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, timeout=20, env=os.environ.copy())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main()
