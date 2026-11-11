"""! @brief 기존 명시 fixture의 카탈로그 출처를 실제 WSL worker까지 전달한다.

@details 제조사 PCB의 미정 물성을 채우는 시험이 아니다. 기존 원형 PCB
fixture의 시험 가정을 합성 카탈로그로 보존하며 실제 제조/안테나 정확도를
검증했다고 보고하지 않는다. RFAD_TEST_WSL=1인 Windows에서만 실행하며
CAD 통합 시험은 RFAD_CAD_PYTHON으로 실행 파일을 명시해야 한다.
"""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from catalog_pcb_verification.common import call, read_json_artifact, wait
from catalog_pcb_verification.runner import run as run_integration
from catalog_pcb_verification.solver import restore_solver, verify_solver
from rfad.application.cad_jobs import CadRuntime
from rfad.application.canonical import canonical_bytes
from rfad.application.projects import ProjectService
from rfad.application.solver_runtime import SolverRuntime
from rfad.catalog.build import build_catalog
from rfad.domain.pcb_selection import EXTENSION_KEY
from test_catalog_build import make_package, manifest, write_json
from verify_pcb_worker import create_fixture


@contextmanager
def native_output(case_name):
    """! @brief 지정 출력 아래 시험별 새 경로를 만들고 기존 보고서는 보존한다."""
    configured = os.environ.get("RFAD_CATALOG_NATIVE_OUTPUT")
    if configured:
        root = Path(configured).resolve()
        root.mkdir(parents=True, exist_ok=True)
        output = root / (case_name + "-" + uuid4().hex)
        output.mkdir(exist_ok=False)
        yield output
    else:
        with TemporaryDirectory() as temporary:
            yield Path(temporary)


def fixture_catalog(package, fixture, fixture_name):
    """! @brief 기존 시험 유전체의 명시 값을 복사하며 제조사 관측으로 위장하지 않는다."""
    document = fixture["document"]
    material_id = next(layer["material_id"] for layer in document["stackup"] if layer["role"] == "dielectric")
    substrate = next(item for item in document["materials"] if item["id"] == material_id)
    record = {"record_id": "EXPLICIT-FIXTURE", "source_id": "S1", "manufacturer": "TraceWave synthetic test fixture",
              "product": "Existing " + fixture_name + " assumptions; not a manufactured PCB",
              "dataset_role": "material_published_parameter", "evidence_scope": "synthetic_fixture_only",
              "dk": substrate["epsilon_r"]["value_si"],
              "df": substrate["tan_delta"]["value_si"], "source_file": "originals/source.txt",
              "value_type": "test_only_explicit_assumption"}
    make_package(package, [record])
    original = package / "originals/source.txt"
    original.write_bytes(canonical_bytes(fixture))
    write_json(package / "catalog/sources.json", [{
        "source_id": "S1", "organization": "TraceWave synthetic test fixture",
        "title": "Existing explicit fixture assumptions; not manufacturer evidence",
        "url": "https://example.invalid/tracewave-test-fixture", "local_path": "originals/source.txt",
        "archived": True, "bytes": original.stat().st_size, "sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
    }])
    manifest(package)
    return substrate


@unittest.skipUnless(sys.platform == "win32" and os.environ.get("RFAD_TEST_WSL") == "1",
                     "실제 TraceWave-Dev WSL과 RFAD_TEST_WSL=1이 필요합니다.")
class CatalogPcbSolverNativeTests(unittest.TestCase):
    """! @brief 공개 선택/실제 계산/후처리/카탈로그 없는 재열기를 양성 대조한다."""

    def select_fixture(self, service, fixture, fixture_name, catalog, substrate):
        """! @brief 원본 시험 값을 보정하지 않고 공개 명령으로 출처를 추가한다."""
        context, project_path, before_snapshot = create_fixture(service, fixture)
        before = read_json_artifact(service, before_snapshot["artifact"])
        reason = "기존 " + fixture_name + " 시험 가정을 그대로 복사함. 제조사 물성 또는 측정 증거가 아님."
        material = {
            "key": "existing-fixture-substrate", "name": substrate["name"],
            "properties": {field: {"mode": "catalog", "record_id": "EXPLICIT-FIXTURE", "reason": reason}
                           for field in ("epsilon_r", "tan_delta")},
            "validity_hz": {boundary: substrate["validity_hz"][boundary]["value_si"] for boundary in ("min", "max")},
        }
        material["properties"]["conductivity"] = {
            "mode": "user", "value": substrate["conductivity"]["value_si"], "reason": reason}
        material["validity_hz"]["reason"] = reason
        selection = {"expected_revision": before_snapshot["revision_id"], "selection_id": str(uuid4()),
                     "specification": {"source": None, "catalog_id": catalog["catalog_id"],
                                       "materials": [material], "material_ids": {material["key"]: substrate["id"]},
                                       "notes": [reason]}}
        preview = call(service, "pcb.selection.preview", selection, context)
        self.assertTrue(preview["can_apply"], preview["issues"])
        changed = call(service, "pcb.selection.apply", {
            **selection, "preview_hash": preview["preview_hash"], "command_id": str(uuid4()),
        }, context, mutation=True)
        wait(service, call(service, "project.save", {"expected_revision": changed["new_revision"]}, context, mutation=True))
        snapshot, _ = wait(service, call(service, "snapshot.create", {
            "expected_revision": changed["new_revision"], "description": "Synthetic catalog provenance; existing explicit fixture values",
        }, context, mutation=True))
        after = read_json_artifact(service, snapshot["artifact"])
        for field in ("board", "stackup", "geometry", "ports", "nets"):
            self.assertEqual(after[field], before[field])
        for old, selected in zip(before["materials"], after["materials"]):
            self.assertEqual(old["id"], selected["id"])
            for field in ("epsilon_r", "tan_delta", "conductivity"):
                self.assertEqual(old[field]["value_si"], selected[field]["value_si"])
            self.assertEqual([old["validity_hz"][key]["value_si"] for key in ("min", "max")],
                             [selected["validity_hz"][key]["value_si"] for key in ("min", "max")])
        self.assertTrue(after["extensions"][EXTENSION_KEY]["evidence"])
        return context, project_path, snapshot, after

    def test_explicit_fixture_selection_reaches_native_and_reopens_without_catalog(self):
        """! @brief 값과 기하는 기존 fixture대로 유지하고 선택 출처만 native에 연결한다."""
        fixture_path = Path(__file__).resolve().parents[1] / "fixtures/pcb_worker_smoke.json"
        fixture = json.loads(fixture_path.read_bytes())
        original_fixture_bytes = fixture_path.read_bytes()
        with native_output("solver") as output:
            database = output / "synthetic-catalog.sqlite"
            substrate = fixture_catalog(output / "synthetic-source", fixture, fixture_path.stem)
            catalog = build_catalog(output / "synthetic-source", database)
            workspace = output / "workspace"
            with ProjectService(workspace, solver_runtime=SolverRuntime(), catalog_database=database) as service:
                context, project_path, snapshot, after = self.select_fixture(service, fixture, fixture_path.stem, catalog, substrate)
                report = verify_solver(service, context, snapshot, fixture["settings"])
                self.assertFalse(report["assessment"]["physics_validated"])
                self.assertFalse(report["qt_found"])
            with ProjectService(workspace, auto_run=False) as reopened:
                restore_solver(reopened, context, snapshot, report)
                selected = call(reopened, "pcb.selection.get", {}, context)
                self.assertEqual(selected["selection"], after["extensions"][EXTENSION_KEY])
            self.assertEqual(fixture_path.read_bytes(), original_fixture_bytes)
            report.update(schema="rfad.catalog-pcb-native-positive-control/0.1", status="passed",
                          evidence_scope="synthetic_catalog_existing_explicit_fixture_only",
                          actual_manufacturer_pcb_tested=False, result_restored_without_solver_or_catalog=True,
                          workspace=str(workspace.resolve()), project_path=project_path)
            (output / "verification.json").write_bytes(canonical_bytes(report))

    @unittest.skipUnless(os.environ.get("RFAD_CAD_PYTHON"),
                         "CAD 통합 시험은 RFAD_CAD_PYTHON으로 고정 Windows CAD 환경을 지정해야 합니다.")
    def test_two_copper_ifa_fixture_full_cad_solver_chain(self):
        """! @brief 기존 양면 동박 IFA 가정의 같은 스냅샷으로 STEP과 실제 계산을 완료한다."""
        code = Path(__file__).resolve().parents[1]
        fixture_path = code / "fixtures/ifa_feed_smoke.json"
        original_fixture_bytes = fixture_path.read_bytes()
        fixture = json.loads(original_fixture_bytes)
        self.assertEqual(sum(layer["role"] == "conductor" for layer in fixture["document"]["stackup"]), 2)
        with native_output("full") as output:
            database = output / "synthetic-catalog.sqlite"
            substrate = fixture_catalog(output / "synthetic-source", fixture, fixture_path.stem)
            catalog = build_catalog(output / "synthetic-source", database)
            workspace = output / "workspace"
            with ProjectService(workspace, catalog_database=database) as service:
                _, project_path, selected_snapshot, _ = self.select_fixture(service, fixture, fixture_path.stem, catalog, substrate)
            report = run_integration(workspace, project_path, output / "report.json", mode="full",
                                     expected_revision=selected_snapshot["revision_id"], settings=fixture["settings"],
                                     cad_runtime=CadRuntime(Path(os.environ["RFAD_CAD_PYTHON"])), solver_runtime=SolverRuntime())
            report.update(evidence_scope="synthetic_catalog_existing_explicit_ifa_fixture_only",
                          actual_manufacturer_pcb_tested=False, fixture_source="fixtures/ifa_feed_smoke.json",
                          original_fixture_sha256=hashlib.sha256(original_fixture_bytes).hexdigest())
            (output / "report.json").write_bytes(canonical_bytes(report))
            self.assertEqual(report["status"], "passed", report)
            self.assertTrue(report["restored_without_catalog_or_workers"])
            self.assertTrue(report["project_unchanged"])
            self.assertEqual(report["snapshot"], report["solver"]["snapshot"])
            self.assertFalse(report["solver"]["assessment"]["physics_validated"])
            self.assertEqual(fixture_path.read_bytes(), original_fixture_bytes)


if __name__ == "__main__":
    unittest.main()
