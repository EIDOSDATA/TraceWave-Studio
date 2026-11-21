"""! @brief Windows 실제 PCB 폼과 서비스 재시작에서 출처/미정/단일 역명령을 검사한다."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.application.canonical import canonical_bytes
from rfad.application import pcb_exchange_service as api
from rfad.application.projects import ProjectService
from test_pcb_features import pcb_document
from test_physical_setup import fixture as physical_fixture

ROOT = Path(__file__).resolve().parents[1]
GUI = os.environ.get("RFAD_GUI_EXE", "")


def fixture(workspace):
    """! @brief FDTD/제작 합격을 만들지 않는 기존 원문과 미정 재료만 설치한다."""
    service=ProjectService(workspace,auto_run=False)
    request={"contract_version":"rfad.api/2.0","context":{},"input":{"path":"projects/PCB 원문","open_mode":"create","name":"PCB GUI 검증"},"request_key":str(uuid4()),"request_key_epoch":service.policy()["request_key_epoch"]}
    task=service.mutate("project.open",request)
    service.run_next()
    result=service.status({"contract_version":"rfad.api/2.0","context":{},"input":{"job_id":task["job_id"]}})["events"][-1]["operation_result"]
    document=pcb_document()
    document["extensions"].update(deepcopy(physical_fixture()["extensions"]))
    document["extensions"]["gui_preservation_sample"] = {"source": "GUI 시험 원문", "missing": None, "verified": False}
    document["schema_version"]="rfad.project/0.5"
    document["project_id"]=result["project_id"]
    def install(state):
        project=state["projects"][document["project_id"]]
        reference=service._store_document(project["path"],document)
        project.update(current=reference,saved=reference,revisions={document["revision_id"]:reference},history={"undo":[],"redo":[],"head_revision":document["revision_id"]})
    service.journal.transaction(install)
    context=api.get(document,{"section":"hole","record_id":None})
    preview,_=api.preview(document,{"expected_revision":document["revision_id"],"operation":"hole.set","values":{"record":context["form"]["record"]},"reason":""})
    data={"project_id":document["project_id"],"revision_id":document["revision_id"],"context":context,"preview":preview,"scope":"real Windows controls and preservation; no native solver or manufacturing validation"}
    data["keepout_context"] = api.get(document, {"section": "keepout", "record_id": None})
    state=service.journal.read()
    original={path.relative_to(workspace).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in (workspace/"projects").rglob("*") if path.is_file()}
    service.close()
    (workspace/"features-smoke-fixture.json").write_bytes(canonical_bytes(data))
    return document,state,original


@unittest.skipUnless(sys.platform=="win32" and GUI,"RFAD_GUI_EXE로 실제 Windows GUI를 지정합니다.")
class GuiPcbFeatureTests(unittest.TestCase):
    """! @brief 실제 native 폼 입력/단위 표시/검토/저장과 영속 이력을 함께 확인한다."""

    def test_native_feature_edit_units_undo_save_restart_preserves_original(self):
        with TemporaryDirectory(prefix="TraceWave PCB GUI ") as directory:
            workspace=Path(directory)/"작업 영역"
            before,state,files=fixture(workspace)
            report_path=Path(directory)/"PCB 화면 검증.json"
            startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
            process=subprocess.run([str(Path(GUI).resolve()),"--python",sys.executable,"--source",str(ROOT/"src"),"--workspace",str(workspace),"--open-project","projects/PCB 원문","--features-smoke-test","--smoke-report",str(report_path)],stdin=subprocess.DEVNULL,capture_output=True,startupinfo=startup,timeout=180,check=False)
            self.assertTrue(report_path.is_file(),(process.returncode,process.stderr))
            report=json.loads(report_path.read_bytes())
            if output:=os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR"):
                target=Path(output)/"features.json";target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(report_path.read_bytes())
            self.assertEqual(process.returncode,0,report)
            self.assertTrue(report["passed"],report)
            self.assertGreaterEqual(report["service_sessions"],2)
            self.assertEqual(set(report["setup_checks"]),{"features_late_preview_and_destroy_safe","features_uncertain_receipt_preserves_key","features_all_conductor_layers_native_field","features_native_missing_values_preserved","features_invalid_input_recovery_and_visible_review","features_changed_input_invalidates_review","features_unit_only_keeps_si_and_review","features_atomic_apply_and_typed_selection","features_first_undo_absence_and_exact_redo","features_save_service_restart_same_source"})
            with ProjectService(workspace,auto_run=False) as service:
                after_state=service.journal.read();project=after_state["projects"][before["project_id"]];after=service._load(project)
                self.assertEqual(project["current"],project["saved"])
                self.assertEqual(after["schema_version"],"rfad.project/0.6")
                self.assertEqual(len(project["history"]["undo"]),1)
                self.assertEqual(after["geometry"],before["geometry"])
                self.assertEqual(after["materials"],before["materials"])
                self.assertEqual(after["extensions"],before["extensions"])
                self.assertEqual(after_state["solver_results"],state["solver_results"])
                hole=after["pcb"]["holes"][0]
                self.assertEqual(hole["name"],"GUI 비도금 홀 / 출처 보존")
                self.assertEqual(hole["shape"]["diameter"]["value_si"],.001)
                self.assertEqual(hole["shape"]["center"][0]["value_si"],.005)
                self.assertEqual(hole["plating"]["state"],"unplated")
                self.assertIsNone(hole["plating"]["thickness"]["value_si"])
                self.assertIsNone(hole["tool_diameter"]["value_si"])
                self.assertEqual(after["geometry"][0]["source_ref"],"explicit-test-source")
                for uri,digest in files.items():
                    self.assertEqual(hashlib.sha256((workspace/uri).read_bytes()).hexdigest(),digest,uri)
                original=deepcopy(after["pcb"])
                def mutate(method):
                    return service.mutate(method,{"contract_version":"rfad.api/2.0","context":{"project_id":before["project_id"]},"input":{"expected_revision":service._load(service.journal.read()["projects"][before["project_id"]])["revision_id"],"command_id":str(uuid4())},"request_key":str(uuid4()),"request_key_epoch":service.policy()["request_key_epoch"]})
                mutate("project.undo")
                self.assertNotIn("pcb",service._load(service.journal.read()["projects"][before["project_id"]]))
                mutate("project.redo")
                self.assertEqual(service._load(service.journal.read()["projects"][before["project_id"]])["pcb"],original)


if __name__=="__main__":
    unittest.main()
