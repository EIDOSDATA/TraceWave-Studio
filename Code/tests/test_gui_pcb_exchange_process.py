"""! @brief 실제 Windows PCB/CAM 파일 생성과 청크 가져오기/재열기의 출처를 검증한다."""
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
from rfad.application.exchange_runtime import ExchangeRuntime
from rfad.application.exchange_service import read
from rfad.application.projects import ProjectService
from rfad.application.pcb_import_service import read as import_read
from test_exchange_service import ExchangeFixture
from test_pcb_exchange_service import prepare, request
from test_physical_setup import fixture as physical_fixture

ROOT=Path(__file__).resolve().parents[1]
GUI=os.environ.get("RFAD_GUI_EXE","")
EXCHANGE=os.environ.get("RFAD_EXCHANGE_PYTHON","")


def fixture(workspace):
    """! @brief 별도 실제 writer의 보드 파일을 만들고 GUI가 읽을 정확한 원문을 보존한다."""
    f=ExchangeFixture(ExchangeRuntime(Path(EXCHANGE)))
    try:
        preserved=deepcopy(f.document)
        preserved["extensions"].update(deepcopy(physical_fixture()["extensions"]))
        preserved["extensions"]["gui_preservation_sample"]={"source":"PCB 교환 시험 원문","missing":None,"verified":False}
        preserved["parent_revision_ids"]=[f.revision]
        preserved["revision_id"]=str(uuid4())
        def install(state):
            project=state["projects"][f.project]
            reference=f.service._store_document(project["path"],preserved)
            project.update(current=reference,saved=reference,history={"undo":[],"redo":[],"head_revision":preserved["revision_id"]})
            project["revisions"][preserved["revision_id"]]=reference
        f.service.journal.transaction(install)
        f.document,f.revision=preserved,preserved["revision_id"]
        prepare(f)
        source=request(f)
        review=f.complete("export.preview",source)
        task=f.service.mutate("export.build",f.request({**source,"review_hash":review["review_hash"]}))
        f.service.exchange.run_next()
        record=f.read("export.get",{"job_id":task["job_id"]})
        if record["state"]!="completed":
            raise AssertionError(record)
        artifact=next(row for row in record["result"]["artifacts"] if row["uri"].endswith("/board.kicad_pcb"))
        raw=f.service.journal.read_artifact(artifact)+b" "*(300*1024)
        document=deepcopy(f.document)
        f.complete("project.save",{"expected_revision":f.revision})
        copper=sorted((row for row in document["stackup"] if row["role"]=="conductor"),key=lambda row:row["order"])
        nets={"0":None}
        for index,row in enumerate(document["nets"],1):
            nets[str(index)]=row["id"]
        data={"project_id":f.project,"revision_id":f.revision,"snapshot":f.snapshot,"import_context":f.read("pcb.import.context",{}),"raw_sha256":hashlib.sha256(raw).hexdigest(),
              "layer_mapping":{"F.Cu":copper[-1]["id"],"B.Cu":copper[0]["id"]},"net_mapping":nets,"scope":"actual native file writing/reading; no manufacturing/RF approval"}
        original={path.relative_to(f.workspace).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in (f.workspace/"projects").rglob("*") if path.is_file()}
        state=f.service.journal.read()
        f.service.close()
        shutil.copytree(f.workspace,workspace)
        (workspace/"gui-source.kicad_pcb").write_bytes(raw)
        (workspace/"pcb-exchange-smoke-fixture.json").write_bytes(canonical_bytes(data))
        return document,state,original,raw
    finally:
        f.close()


@unittest.skipUnless(sys.platform=="win32" and GUI and EXCHANGE,"실제 Windows GUI와 별도 PCB 교환 환경을 지정합니다.")
class GuiPcbExchangeTests(unittest.TestCase):
    """! @brief native UI의 검토와 실제 파일/읽기 원본의 저장 수명을 대조한다."""
    def test_real_cam_and_chunk_import_apply_undo_save_restart(self):
        with TemporaryDirectory(prefix="TraceWave PCB 교환 ") as directory:
            workspace=Path(directory)/"작업 영역"
            before,state,files,raw=fixture(workspace)
            report_path=Path(directory)/"PCB 교환 화면.json"
            startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
            process=subprocess.run([str(Path(GUI).resolve()),"--python",sys.executable,"--source",str(ROOT/"src"),"--workspace",str(workspace),"--exchange-python",str(Path(EXCHANGE).resolve()),"--open-project","projects/원본 도면","--pcb-exchange-smoke-test","--smoke-report",str(report_path)],stdin=subprocess.DEVNULL,capture_output=True,startupinfo=startup,timeout=300,check=False)
            self.assertTrue(report_path.is_file(),(process.returncode,process.stderr))
            report=json.loads(report_path.read_bytes())
            if output:=os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR"):
                target=Path(output)/"pcb_exchange.json";target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(report_path.read_bytes())
            self.assertEqual(process.returncode,0,report)
            self.assertTrue(report["passed"],report)
            self.assertGreaterEqual(report["service_sessions"],2)
            self.assertEqual(set(report["setup_checks"]),{"pcb_exchange_late_source_and_uncertain_receipt_safe","pcb_exchange_native_exact_chunk_upload","pcb_exchange_real_parser_explicit_mapping","pcb_exchange_review_invalidates_and_visible_changes","pcb_exchange_native_cam_layers_and_unknown_tool","pcb_exchange_actual_cam_build_no_manufacturing_claim","pcb_exchange_fresh_verify_preserves_package","pcb_exchange_atomic_import_keeps_original_records","pcb_exchange_single_undo_redo","pcb_exchange_saved_restart_preserves_sources"})
            with ProjectService(workspace,auto_run=False) as service:
                after_state=service.journal.read();project=after_state["projects"][before["project_id"]];after=service._load(project)
                self.assertEqual(project["current"],project["saved"])
                self.assertEqual(after["materials"],before["materials"])
                self.assertEqual(after["stackup"],before["stackup"])
                self.assertEqual(after["extensions"],before["extensions"])
                self.assertEqual(after_state["solver_results"],state["solver_results"])
                original_geometry={row["id"]:row for row in after["geometry"]}
                for item in before["geometry"]:
                    self.assertEqual(original_geometry[item["id"]],item)
                self.assertEqual(len(after["pcb"]["imports"]),1)
                imported=after["pcb"]["imports"][0]
                self.assertEqual(service.journal.read_artifact(imported["source_files"][0]),raw)
                session=after_state["pcb_imports"][imported["id"]]
                self.assertEqual(len(session["files"][0]["chunks"]),2)
                self.assertIsNotNone(session["applied_revision"])
                for hole in after["pcb"]["holes"]:
                    self.assertIsNone(hole["tool_diameter"]["value_si"])
                newjobs=[job for identity,job in after_state["jobs"].items() if identity not in state["jobs"] and "exchange" in job]
                self.assertEqual(sorted(job["operation_method"] for job in newjobs),["export.build","export.verify","pcb.import.parse"])
                for job in newjobs:
                    self.assertEqual(job["state"],"completed")
                    if job["operation_method"]!="pcb.import.parse":
                        record=read(service,"export.get",{"contract_version":"rfad.api/2.0","context":{"project_id":before["project_id"]},"input":{"job_id":job["job_id"]}})
                        self.assertFalse(record["report"]["manufacturing_verified"])
                        self.assertFalse(record["report"]["physics_verified"])
                self.assertEqual((workspace/"gui-source.kicad_pcb").read_bytes(),raw)
                for uri,digest in files.items():
                    self.assertEqual(hashlib.sha256((workspace/uri).read_bytes()).hexdigest(),digest,uri)


if __name__=="__main__":
    unittest.main()
