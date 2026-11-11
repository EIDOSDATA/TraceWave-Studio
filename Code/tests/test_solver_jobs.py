"""! @brief 가짜 WSL 전송과 실제 journal로 해석 작업의 수명 및 봉인을 검증한다.

@details 이 파일의 analytic 샘플은 조정기 시험 데이터일 뿐 native solver 실행
증거가 아니다. 실제 도파관 실행 정확도는 별도 통합 검증으로 확인한다.
"""

from copy import deepcopy
import cmath
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.adapters.solvers.openems.native import RAW_NAMES, descriptor
from rfad.adapters.solvers.openems.reference import C0, LIMITS, analytic_te10, assess_samples, check_termination
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.projects import ProjectService
from rfad.application.solver import PROFILE, RUNTIME_PROFILE
from rfad.application.solver_jobs import SolverRuntime
from rfad.domain.errors import ProjectError


def _json_file(stage, relative, value, role):
    """! @brief 시험 JSON도 실제 바이트와 hash를 가진 파일로 생성한다."""
    path = stage / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))
    return descriptor(stage, path, role)


class FakeTransport:
    """! @brief native 프로세스 없이 worker 파일 계약과 종료 소유권을 모사한다."""

    def __init__(self):
        """! @brief 시험별 전송 호출, 단계와 취소 gate를 독립적으로 보존한다."""
        self.mode = "success"
        self.calls = []
        self.cancels = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.reconcile_confirmed = True

    def identity(self):
        """! @brief 실제 WSL 설치와 혼동하지 않을 고정 시험 식별자를 반환한다."""
        return {"distribution": "fake-test-only", "user": "test-only", "python": "/fake/python"}

    def cancel(self, run_id, nonce):
        """! @brief 이전 실행의 소유 확인 결과만 돌려주며 계산을 재개하지 않는다."""
        self.cancels.append((run_id, nonce))
        return {"state": "cancelled" if self.reconcile_confirmed else "unknown", "termination_confirmed": self.reconcile_confirmed, "outcome_unknown": not self.reconcile_confirmed}

    def inspect(self, run_id, nonce):
        """! @brief 재접속에도 미확인 상태가 남으면 terminal interrupted로 보고한다."""
        return {"state": "cancelled" if self.reconcile_confirmed else "interrupted", "termination_confirmed": self.reconcile_confirmed, "outcome_unknown": not self.reconcile_confirmed}

    def execute(self, stage, *, run_id, nonce, cancel, timeout_seconds, on_state):
        """! @brief 요청과 같은 식별자를 가진 파일 묶음 또는 명시 실패를 생성한다."""
        request = json.loads((stage / "request.json").read_bytes())
        self.calls.append(deepcopy(request))
        self.started.set()
        if self.mode == "not_started":
            raise ProjectError("E_SCHEMA", "WSL 시작 전 시험 실패", details={"not_started": True, "termination_confirmed": True, "outcome_unknown": False})
        if self.mode == "block":
            if not self.release.wait(5.0):
                raise RuntimeError("가짜 전송 gate 대기 실패")
        if self.mode == "unknown":
            return {"state": "unknown", "termination_confirmed": False, "outcome_unknown": True}
        if self.mode == "timeout":
            return {"state": "timeout", "termination_confirmed": True, "outcome_unknown": False}
        if self.mode == "cancelled":
            return {"state": "cancelled", "termination_confirmed": True, "outcome_unknown": False}
        package = {"schema": "rfad.openems-worker-result/0.1", "phase": request["phase"], "run_id": run_id, "nonce": nonce,
                   "analysis_plan_id": request["analysis_plan"]["plan_id"]}
        runtime = {"schema": "rfad.openems-runtime-observation/0.1", "python": "test-only", "manifest_sha256": request["runtime"]["manifest_sha256"],
                   "code_files": request["runtime"]["code_files"], "packages": {}, "native_files": [], "loaded_native_files": [], "qt_found": False,
                   "python_executable": {"path": "/fake/python", "sha256": "0" * 64, "bytes": 1}}
        if request["phase"] == "prepare":
            package["preparation"], package["files"] = self._prepare(stage, request, runtime)
        else:
            on_state({"phase": "postprocessing"})
            package["result"], package["files"] = self._analysis(stage, request, runtime)
        if self.mode == "wrong_nonce":
            package["nonce"] = "0" * 32
        elif self.mode == "wrong_plan":
            package["analysis_plan_id"] = str(uuid4())
        elif self.mode == "bad_hash":
            package["files"][0]["sha256"] = "0" * 64
        elif self.mode == "unsafe_path":
            package["files"][0]["path"] = "output/../outside.xml"
        elif self.mode == "oversize":
            package["files"][0]["bytes"] = 64 * 1024 * 1024 + 1
        elif self.mode == "missing_file":
            (stage / package["files"][0]["path"]).unlink()
        _json_file(stage, "output/result.json", package, "envelope")
        return {"state": "completed", "termination_confirmed": True, "outcome_unknown": False}

    def _prepare(self, stage, request, runtime):
        """! @brief 준비 계약의 native 입력, 실제형식 mesh와 소비 보고를 모사한다."""
        plan = request["analysis_plan"]
        case = plan["case"]
        grid = case["mesh"]["grid_mm"]
        def segment(start, stop):
            """! @brief native 격자 생성 규칙과 같은 분할 개수를 시험에 사용한다."""
            count = math.ceil((stop - start) / grid)
            return [start + (stop - start) * i / count for i in range(count + 1)]
        critical = case["mesh"]["critical_z_mm"]
        lines = {"x": segment(0.0, 20.0), "y": segment(0.0, 10.0),
                 "z": sorted({value for start, stop in zip(critical, critical[1:]) for value in segment(start, stop)})}
        counts = [len(lines[axis]) for axis in ("x", "y", "z")]
        mesh = {"schema": "rfad.openems-mesh/0.1", "grid_mm": grid, "native_length_unit": "mm", "delta_unit_m": 0.001,
                "lines_mm": lines, "line_counts": counts, "interval_counts": [value - 1 for value in counts],
                "native_grid_points": math.prod(counts), "yee_interval_cells": math.prod(value - 1 for value in counts),
                "pml_cells_per_end": 8, "native_preprocessing_executed": False, "fdtd_executed": False}
        consumption = {"schema": "rfad.openems-consumption/0.1", "analysis_plan_id": plan["plan_id"], "source": "explicit_reference_case",
                       "consumed_case": case, "project_geometry_consumed": False, "project_materials_consumed": False,
                       "material": "vacuum", "walls": "PEC boundary", "approximations": ["PEC ideal wall", "vacuum lossless medium", "Cartesian Yee grid", "8-cell PML at both z ends"],
                       "unsupported": ["arbitrary_project_geometry", "IFA", "NF2FF"], "fdtd_executed": False}
        normalization = deepcopy(plan["normalization"])
        if self.mode == "wrong_mesh":
            mesh["line_counts"][0] += 1
        elif self.mode == "wrong_consumption":
            consumption["consumed_case"] = deepcopy(case)
            consumption["consumed_case"]["medium"]["epsilon_r"] = 4.2
        elif self.mode == "wrong_normalization":
            normalization["native_voltage_unit"] = "V"
        xml = stage / "output/prepared/waveguide.xml"
        xml.parent.mkdir(parents=True, exist_ok=True)
        xml.write_bytes(b"<openEMS><!-- fake coordinator test only --></openEMS>\n")
        files = [descriptor(stage, xml, "native_input")]
        for name, role, value in (("mesh.json", "mesh_statistics", mesh), ("consumption.json", "consumption_report", consumption),
                                  ("normalization.json", "normalization", normalization), ("runtime.json", "runtime_provenance", runtime)):
            files.append(_json_file(stage, "output/prepared/" + name, value, role))
        preparation = {"schema": "rfad.preparation-artifact/0.1", "analysis_plan_id": plan["plan_id"], "analysis_plan_hash": canonical_hash(plan),
                       "profile": plan["analysis_profile"], "files": deepcopy(files), "mesh_statistics": mesh, "normalization": normalization,
                       "consumption_report": consumption, "runtime_identity": runtime}
        files.append(_json_file(stage, "output/prepared/preparation.json", preparation, "preparation_artifact"))
        return preparation, files

    def _analysis(self, stage, request, runtime):
        """! @brief 조정기만 시험하는 analytic 샘플과 전체 raw 봉인을 생성한다."""
        plan, prepared, preparation = request["analysis_plan"], request["prepared_plan"], request["preparation"]
        xml_input = next(item for item in request["input_files"] if item["role"] == "native_input")
        log = "Exact-endcriteria: evaluating the end criteria every timestep\nRunFDTD: end-criteria of -70dB reached after 1000 timesteps (-71dB)\n"
        statistics = {"native_cells": preparation["mesh_statistics"]["native_grid_points"], "timestep_seconds": 1e-12, "iterations": 1000,
                      "raw_values": [float(preparation["mesh_statistics"]["native_grid_points"]), 1e-12, 1000.0, 0.1, 1.0, 2.0]}
        files = []
        for name in RAW_NAMES:
            path = stage / "output/raw" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = b"0 0\n1e-12 1\n2e-12 0\n"
            if name == "waveguide.xml":
                raw = (stage / xml_input["path"]).read_bytes()
            elif name == "native.log":
                raw = log.encode("ascii")
            elif name == "openEMS_stats.txt":
                raw = ("\n".join(str(value) for value in statistics["raw_values"]) + "\n").encode("ascii")
            path.write_bytes(raw)
            files.append(descriptor(stage, path, "raw/" + name))
        termination = check_termination(log, 1000)
        manifest = {"schema": "rfad.openems-raw/0.1", "complete": True, "analysis_plan_id": plan["plan_id"], "analysis_plan_hash": canonical_hash(plan),
                    "prepared_plan_id": prepared["prepared_plan_id"], "prepared_plan_hash": canonical_hash(prepared), "files": deepcopy(files),
                    "execution": {"command": ["fake-coordinator-test-only"], "elapsed_seconds": 0.01, "exit_code": 0, "loaded_native_files": [],
                                  "statistics": statistics, "termination": termination, "native_input_sha256": xml_input["sha256"]}}
        if self.mode == "incomplete_raw":
            manifest["complete"] = False
        files.append(_json_file(stage, "output/raw_manifest.json", manifest, "raw_manifest"))
        samples = []
        for index in range(31):
            frequency = 9.5e9 + 1e9 * index / 30
            impedance, _ = analytic_te10(frequency)
            beta = math.sqrt((2 * math.pi * frequency / C0) ** 2 - (math.pi / 0.020) ** 2)
            transmission = cmath.exp(-1j * beta * 0.05)
            samples.append({"frequency_hz": frequency, "s11": [0.0, 0.0], "s21": [transmission.real, transmission.imag], "impedance_ohm": [impedance, 0.0]})
        provenance = {"schema": "rfad.openems-provenance/0.1", "run_id": request["run_id"], "nonce": request["nonce"], "execution_mode": request["phase"],
                      "analysis_plan": plan, "prepared_plan": prepared, "preparation": preparation, "runtime": runtime, "raw_manifest": manifest}
        result = {"schema": "rfad.openems-result/0.1", "analysis_plan_id": plan["plan_id"], "prepared_plan_id": prepared["prepared_plan_id"],
                  "samples": samples, "assessment": assess_samples(samples), "limits": LIMITS, "termination": termination, "native_statistics": statistics,
                  "mesh_statistics": preparation["mesh_statistics"], "normalization": plan["normalization"], "provenance": provenance, "raw_manifest": manifest}
        if self.mode == "wrong_provenance":
            provenance["nonce"] = "f" * 32
        elif self.mode == "wrong_assessment":
            result["assessment"]["metrics"]["max_reflection_amplitude"] = 0.01
        elif self.mode == "wrong_frequency":
            result["samples"][0]["frequency_hz"] = 9.49e9
        files.extend([_json_file(stage, "output/normalized.json", result, "normalized_result"), _json_file(stage, "output/provenance.json", provenance, "provenance")])
        return result, files


class SolverJobTests(unittest.TestCase):
    """! @brief 실제 서비스 접수와 불변 저장소를 거쳐 결과 게시 경계를 확인한다."""

    def setUp(self):
        """! @brief 로컬 native 설치에 의존하지 않는 명시적 시험 runtime을 만든다."""
        self.temporary = tempfile.TemporaryDirectory(prefix="rfad 해석 작업 ")
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "프로젝트 저장소"
        audit, manifest = self.root / "audit.json", self.root / "manifest.json"
        audit.write_bytes(canonical_bytes({"status": "passed", "qt_found": False, "packages": {}, "native_files": []}))
        manifest.write_bytes(canonical_bytes({"qt_allowed": False, "packages": [], "python": {"validated_version": "test-only", "architecture": "test-only"}}))
        self.transport = FakeTransport()
        self.runtime = SolverRuntime(self.transport, audit=audit, manifest=manifest)
        self.service = ProjectService(self.workspace, auto_run=False, solver_runtime=self.runtime)
        self.runners = []
        task = self.service.mutate("project.open", self.request({"path": "projects/도파관 참조", "open_mode": "create", "name": "명시적 참조 시험"}, {}))
        self.service.run_next()
        created = self.status(task)["events"][-1]["operation_result"]
        self.project, self.revision = created["project_id"], created["revision_id"]
        self.snapshot = self.complete("snapshot.create", {"expected_revision": self.revision}, solver=False)

    def tearDown(self):
        """! @brief 시험 스레드를 회수한 뒤 journal 소유권을 반환한다."""
        self.transport.release.set()
        for runner in self.runners:
            runner.join(8.0)
        self.service.close()
        self.temporary.cleanup()

    def request(self, data, context=None):
        """! @brief 공개 명령의 영속 request key와 epoch를 사용한다."""
        return {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project} if context is None else context,
                "input": data, "request_key": str(uuid4()), "request_key_epoch": self.service.policy()["request_key_epoch"]}

    def status(self, task):
        """! @brief 공개 상태 조회로 terminal과 결과 참조를 읽는다."""
        return self.service.status({"contract_version": "rfad.api/2.0", "context": {}, "input": {"job_id": task["job_id"]}})

    def job(self, task):
        """! @brief 시험에서만 영속 slot 예약과 캡처된 입력을 확인한다."""
        return self.service.journal.read()["jobs"][task["job_id"]]

    def complete(self, method, data, *, solver=True):
        """! @brief 작업 하나를 접수하고 해당 조정기의 명시 실행으로 완료한다."""
        task = self.service.mutate(method, self.request(data))
        (self.service.solver if solver else self.service).run_next()
        status = self.status(task)
        self.assertEqual(status["state"], "completed", status)
        return status["events"][-1]["operation_result"]

    def plan_input(self):
        """! @brief 선택된 봉인 스냅샷과 격자를 명시한다."""
        return {"snapshot": {key: self.snapshot[key] for key in ("snapshot_id", "content_hash")}, "analysis_profile": PROFILE,
                "runtime_profile": RUNTIME_PROFILE, "grid_mm": 1.0}

    def prepared(self):
        """! @brief 실제 계획 및 준비 봉인 경계를 순서대로 통과한다."""
        planned = self.complete("solver.plan", self.plan_input())["analysis_plan"]
        return self.complete("solver.prepare", {"analysis_plan": {key: planned[key] for key in ("plan_id", "content_hash")}, "budget": {"timeout_seconds": 120.0}})["prepared_plan"]

    def analysis_input(self, prepared, *, raw_result_id=None):
        """! @brief 준비 계획만 받는 해석과 raw가 필요한 후처리 입력을 구분한다."""
        task = {"kind": "em_analysis", "prepared_plan": {key: prepared[key] for key in ("prepared_plan_id", "content_hash")},
                "execution_mode": "solve_and_postprocess" if raw_result_id is None else "postprocess_only"}
        if raw_result_id is not None:
            task["raw_result_id"] = raw_result_id
        return {"task_plan": task, "budget": {"timeout_seconds": 120.0}}

    def assert_error(self, callback, code):
        """! @brief 공개 접수 실패의 구조화된 코드가 유지되는지 확인한다."""
        with self.assertRaises(ProjectError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def test_plan_prepare_analysis_result_and_explicit_postprocess(self):
        """! @brief 준비는 FDTD 없이 끝나고 조회는 새 계산 없이 봉인 참조만 반환한다."""
        prepared = self.prepared()
        self.assertEqual([call["phase"] for call in self.transport.calls], ["prepare"])
        result = self.complete("job.submit", self.analysis_input(prepared))
        query = {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project}, "input": {"artifact_id": result["artifact_id"]}}
        before = self.service.journal.read()
        opened = self.service.solver.result_open(query)
        self.assertEqual(opened["metadata"]["sample_count"], 31)
        self.assertEqual(self.service.journal.read(), before)
        self.assertEqual([call["phase"] for call in self.transport.calls], ["prepare", "analysis"])
        self.assertTrue(any(file["role"] == "raw_manifest" for file in opened["files"]))
        for file in opened["files"]:
            self.assertEqual(hashlib.sha256(self.service.journal.read_artifact(file)).hexdigest(), file["sha256"])
        post = self.complete("job.submit", self.analysis_input(prepared, raw_result_id=result["artifact_id"]))
        self.assertNotEqual(result["artifact_id"], post["artifact_id"])
        self.assertEqual([call["phase"] for call in self.transport.calls], ["prepare", "analysis", "postprocess_only"])

    def test_plan_remains_bound_after_edit(self):
        """! @brief 접수 후 편집이 봉인 계획의 원본과 hash를 바꾸지 않는다."""
        task = self.service.mutate("solver.plan", self.request(self.plan_input()))
        changed = self.service.mutate("project.apply_command", self.request({"expected_revision": self.revision, "command_id": str(uuid4()),
            "type": "metadata.describe", "payload": {"description": "접수 후 편집"}}))
        self.service.solver.run_next()
        reference = self.status(task)["events"][-1]["operation_result"]["analysis_plan"]
        plan = json.loads(self.service.journal.read_artifact(reference["artifact"]))
        self.assertEqual(plan["snapshot"], self.snapshot)
        self.assertEqual(plan["source_semantics"]["metadata"]["description"], "")
        self.assertNotEqual(plan["snapshot"]["revision_id"], changed["new_revision"])
        self.assertEqual(canonical_hash(plan), reference["content_hash"])
        self.assertEqual(self.transport.calls, [])

    def test_receipt_replay_and_restart_do_not_repeat_work(self):
        """! @brief 완료 요청 재전송은 같은 job을 반환하고 다시 계획을 만들지 않는다."""
        request = self.request(self.plan_input())
        task = self.service.mutate("solver.plan", request)
        self.assertEqual(self.service.mutate("solver.plan", request), task)
        self.service.solver.run_next()
        before = self.service.journal.read()
        self.assertEqual(self.service.mutate("solver.plan", request), task)
        self.assertEqual(self.service.journal.read(), before)
        self.service.close()
        self.service = ProjectService(self.workspace, auto_run=False, solver_runtime=self.runtime)
        self.assertEqual(self.service.mutate("solver.plan", request), task)
        self.assertEqual(self.status(task)["state"], "completed")
        self.assertFalse(self.service.solver.run_next())

    def test_bad_input_hash_and_unprepared_plan_are_rejected(self):
        """! @brief 미등록 스냅샷/계획 hash를 통해 worker 실행을 우회할 수 없다."""
        data = self.plan_input()
        data["snapshot"]["content_hash"] = "0" * 64
        self.assert_error(lambda: self.service.mutate("solver.plan", self.request(data)), "E_HASH")
        unknown = {"prepared_plan_id": str(uuid4()), "content_hash": "1" * 64}
        self.assert_error(lambda: self.service.mutate("job.submit", self.request(self.analysis_input(unknown))), "E_HASH")
        self.assertEqual(self.transport.calls, [])

    def test_queued_cancel_releases_slot_without_worker(self):
        """! @brief 미시작 작업은 즉시 취소되며 native 실행을 시작하지 않는다."""
        task = self.service.mutate("solver.plan", self.request(self.plan_input()))
        self.service.mutate("job.cancel", self.request({"job_id": task["job_id"], "reason": "시험 취소"}, {}))
        self.assertEqual(self.status(task)["state"], "cancelled")
        self.assertFalse(self.job(task)["solver"]["resource_reserved"])
        self.assertFalse(self.service.solver.run_next())
        self.complete("solver.plan", self.plan_input())
        self.assertEqual(self.transport.calls, [])

    def test_running_cancel_wins_publish_race(self):
        """! @brief 실행 종료 직전 취소 요청이 성공 결과 게시로 덮이지 않는다."""
        prepared = self.prepared()
        self.transport.mode = "block"
        self.transport.started.clear()
        task = self.service.mutate("job.submit", self.request(self.analysis_input(prepared)))
        runner = threading.Thread(target=self.service.solver.run_next)
        self.runners.append(runner)
        runner.start()
        self.assertTrue(self.transport.started.wait(5.0))
        self.service.mutate("job.cancel", self.request({"job_id": task["job_id"], "reason": "게시 경쟁 시험"}, {}))
        self.assertEqual(self.status(task)["state"], "cancel_requested")
        self.assertTrue(self.job(task)["solver"]["resource_reserved"])
        self.transport.release.set()
        runner.join(8.0)
        self.assertFalse(runner.is_alive())
        self.assertEqual(self.status(task)["state"], "cancelled")
        self.assertEqual(self.status(task)["artifacts"], [])
        self.assertFalse(self.job(task)["solver"]["resource_reserved"])
        self.assertEqual(self.service.journal.read()["solver_results"], {})

    def test_unknown_exit_keeps_reservation_through_restart_until_reconcile(self):
        """! @brief guest 종료 미확인은 재시작 후에도 슬롯을 점유하며 확인 후만 해제한다."""
        prepared = self.prepared()
        self.transport.mode = "unknown"
        task = self.service.mutate("job.submit", self.request(self.analysis_input(prepared)))
        self.service.solver.run_next()
        self.assertEqual(self.status(task)["state"], "interrupted")
        self.assertTrue(self.job(task)["solver"]["resource_reserved"])
        self.service.close()
        self.service = ProjectService(self.workspace, auto_run=False, solver_runtime=self.runtime)
        self.assert_error(lambda: self.service.mutate("solver.plan", self.request(self.plan_input())), "E_RESOURCE")
        self.transport.reconcile_confirmed = False
        self.service.solver.reconcile(task["job_id"])
        self.assertTrue(self.job(task)["solver"]["resource_reserved"])
        self.transport.reconcile_confirmed = True
        reconciled = self.service.solver.reconcile(task["job_id"])
        self.assertTrue(reconciled["termination_confirmed"])
        self.assertFalse(self.job(task)["solver"]["resource_reserved"])
        self.assertEqual(self.status(task)["state"], "interrupted")
        self.assertEqual(self.transport.cancels[-1], (self.job(task)["run_id"], self.job(task)["solver"]["nonce"]))
        self.complete("solver.plan", self.plan_input())

    def test_restart_marks_unfinished_native_interrupted_without_reexecution(self):
        """! @brief 시작 상태가 영속된 작업은 서비스 재시작에서 자동 재실행되지 않는다."""
        prepared = self.prepared()
        task = self.service.mutate("job.submit", self.request(self.analysis_input(prepared)))
        def started(state):
            """! @brief 프로세스 손실 직전의 영속 상태를 시험한다."""
            self.service._event(state["jobs"][task["job_id"]], "running")
        self.service.journal.transaction(started)
        calls = len(self.transport.calls)
        self.service.close()
        self.service = ProjectService(self.workspace, auto_run=False, solver_runtime=self.runtime)
        self.assertEqual(self.status(task)["state"], "interrupted")
        self.assertTrue(self.job(task)["solver"]["resource_reserved"])
        self.assertFalse(self.service.solver.run_next())
        self.assertEqual(len(self.transport.calls), calls)

    def test_bad_worker_outputs_never_publish_and_release_confirmed_slot(self):
        """! @brief 현재 작업과 다른 nonce/hash 또는 불안전 경로를 게시하지 않는다."""
        planned = self.complete("solver.plan", self.plan_input())["analysis_plan"]
        data = {"analysis_plan": {key: planned[key] for key in ("plan_id", "content_hash")}, "budget": {"timeout_seconds": 120.0}}
        for mode in ("wrong_nonce", "wrong_plan", "bad_hash", "unsafe_path", "oversize", "missing_file", "timeout", "not_started"):
            with self.subTest(mode=mode):
                self.transport.mode = mode
                task = self.service.mutate("solver.prepare", self.request(data))
                self.service.solver.run_next()
                status = self.status(task)
                self.assertEqual(status["state"], "failed", status)
                self.assertEqual(status["artifacts"], [])
                self.assertFalse(self.job(task)["solver"]["resource_reserved"])
        self.assertEqual(self.service.journal.read()["prepared_plans"], {})

    def test_transport_cancel_without_user_request_is_interrupted(self):
        """! @brief 외부에서 확인된 종료를 사용자 취소로 가장하거나 활성 상태로 남기지 않는다."""
        prepared = self.prepared()
        prior = self.complete("job.submit", self.analysis_input(prepared))
        self.transport.mode = "cancelled"
        for data in (self.analysis_input(prepared), self.analysis_input(prepared, raw_result_id=prior["artifact_id"])):
            task = self.service.mutate("job.submit", self.request(data))
            self.assertTrue(self.service.solver.run_next())
            job = self.job(task)
            self.assertEqual(job["state"], "interrupted", job)
            self.assertFalse(job["solver"]["resource_reserved"])
            self.assertTrue(job["events"][-1]["termination_confirmed"])
            self.assertFalse(job["events"][-1]["outcome_unknown"])
            self.assertEqual(len(self.service.journal.read()["solver_results"]), 1)

    def test_service_close_reaps_preparation_and_preserves_confirmed_interruption(self):
        """! @brief 실제 조정기 스레드 종료는 취소 요청이 없는 preparing을 확정 중단으로 보존한다."""
        planned = self.complete("solver.plan", self.plan_input())["analysis_plan"]
        self.transport.mode = "block"
        task = self.service.mutate("solver.prepare", self.request({
            "analysis_plan": {key: planned[key] for key in ("plan_id", "content_hash")},
            "budget": {"timeout_seconds": 120.0},
        }))
        self.service.solver.start()
        self.assertTrue(self.transport.started.wait(3.0))
        errors = []
        def close_service():
            """! @brief 닫기 스레드의 예외를 시험 본문에서 확인한다."""
            try:
                self.service.close()
            except Exception as error:
                errors.append(error)
        closer = threading.Thread(target=close_service)
        self.runners.append(closer)
        closer.start()
        self.assertTrue(self.service.solver.stop.wait(3.0))
        self.transport.mode = "cancelled"
        self.transport.release.set()
        closer.join(8.0)
        self.assertFalse(closer.is_alive())
        self.assertEqual(errors, [])
        self.service = ProjectService(self.workspace, auto_run=False, solver_runtime=self.runtime)
        job = self.job(task)
        self.assertEqual(job["state"], "interrupted", job)
        self.assertFalse(job["solver"]["resource_reserved"])
        self.assertTrue(job["events"][-1]["termination_confirmed"])
        self.assertFalse(job["events"][-1]["outcome_unknown"])
        self.assertEqual(self.service.journal.read()["prepared_plans"], {})

    def test_stop_after_sealing_preserves_prior_result_without_publication(self):
        """! @brief 파일 봉인 뒤 종료/취소 Event가 도착해도 완료 결과를 새로 게시하지 않는다."""
        prepared = self.prepared()
        prior = self.complete("job.submit", self.analysis_input(prepared))
        original_seal = self.service.solver._seal
        for signal in (self.service.solver.stop, self.service.solver.cancel):
            self.service.solver.stop.clear()
            self.service.solver.cancel.clear()
            task = self.service.mutate("job.submit", self.request(self.analysis_input(prepared)))
            def seal_then_stop(*args):
                """! @brief 봉인 완료와 원자 게시 사이의 종료 경쟁을 재현한다."""
                result = original_seal(*args)
                signal.set()
                return result
            with patch.object(self.service.solver, "_seal", side_effect=seal_then_stop):
                self.assertTrue(self.service.solver.run_next())
            job = self.job(task)
            self.assertEqual(job["state"], "interrupted", job)
            self.assertFalse(job["solver"]["resource_reserved"])
            self.assertTrue(job["events"][-1]["termination_confirmed"])
            self.assertFalse(job["events"][-1]["outcome_unknown"])
            self.assertNotIn("operation_result", job["events"][-1])
            self.assertEqual(set(self.service.journal.read()["solver_results"]), {prior["artifact_id"]})

    def test_budget_is_explicit_finite_and_within_plan_limit(self):
        """! @brief wall-clock 예산은 300초 이내의 명시적인 유한 양수만 허용한다."""
        planned = self.complete("solver.plan", self.plan_input())["analysis_plan"]
        for timeout in (True, 0.0, -1.0, 301.0, math.inf, math.nan):
            with self.subTest(timeout=timeout):
                data = {"analysis_plan": {key: planned[key] for key in ("plan_id", "content_hash")}, "budget": {"timeout_seconds": timeout}}
                self.assert_error(lambda: self.service.mutate("solver.prepare", self.request(data)), "E_RESOURCE" if math.isfinite(timeout) else "E_SCHEMA")
        self.assertEqual(self.transport.calls, [])

    def test_postprocess_requires_registered_raw_result_and_never_falls_back(self):
        """! @brief raw가 없을 때 해석을 자동으로 시작하는 fallback을 차단한다."""
        prepared = self.prepared()
        calls = len(self.transport.calls)
        data = self.analysis_input(prepared, raw_result_id=str(uuid4()))
        self.assert_error(lambda: self.service.mutate("job.submit", self.request(data)), "E_MISSING_ARTIFACT")
        self.assertEqual(len(self.transport.calls), calls)

    def test_preparation_semantics_must_match_plan_before_sealing(self):
        """! @brief 파일 해시가 맞더라도 소비 조건/정규화/mesh가 다르면 준비를 봉인하지 않는다."""
        planned = self.complete("solver.plan", self.plan_input())["analysis_plan"]
        data = {"analysis_plan": {key: planned[key] for key in ("plan_id", "content_hash")}, "budget": {"timeout_seconds": 120.0}}
        for mode in ("wrong_mesh", "wrong_consumption", "wrong_normalization"):
            with self.subTest(mode=mode):
                self.transport.mode = mode
                task = self.service.mutate("solver.prepare", self.request(data))
                self.service.solver.run_next()
                self.assertEqual(self.status(task)["state"], "failed", self.status(task))
                self.assertFalse(self.job(task)["solver"]["resource_reserved"])
        self.assertEqual(self.service.journal.read()["prepared_plans"], {})

    def test_result_semantics_must_match_raw_and_physics_assessment(self):
        """! @brief 파일 봉인만으로 불완전 raw나 변조된 출처/평가를 성공 처리하지 않는다."""
        prepared = self.prepared()
        for mode in ("incomplete_raw", "wrong_provenance", "wrong_assessment", "wrong_frequency"):
            with self.subTest(mode=mode):
                self.transport.mode = mode
                task = self.service.mutate("job.submit", self.request(self.analysis_input(prepared)))
                self.service.solver.run_next()
                self.assertEqual(self.status(task)["state"], "failed", self.status(task))
                self.assertFalse(self.job(task)["solver"]["resource_reserved"])
        self.assertEqual(self.service.journal.read()["solver_results"], {})

    def test_runtime_drift_after_planning_requires_replan(self):
        """! @brief 계획을 만든 runtime과 다른 환경에 준비를 접수하지 않는다."""
        planned = self.complete("solver.plan", self.plan_input())["analysis_plan"]
        self.runtime.identity["manifest_sha256"] = "f" * 64
        data = {"analysis_plan": {key: planned[key] for key in ("plan_id", "content_hash")}, "budget": {"timeout_seconds": 120.0}}
        self.assert_error(lambda: self.service.mutate("solver.prepare", self.request(data)), "E_VERSION")
        self.assertEqual(self.transport.calls, [])

    def test_stdio_openems_option_routes_capabilities_without_native_host_import(self):
        """! @brief 실제 CLI 옵션과 NDJSON을 통과하되 WSL 실행/native host import는 하지 않는다."""
        script = '''from pathlib import Path
import sys
from types import SimpleNamespace
from rfad.application import solver_jobs
from rfad.application.projects import ProjectService

original = solver_jobs.SolverRuntime

def runtime_factory():
    """! @brief CLI의 runtime 파일 관측만 시험용 경로와 전송 식별자로 바꾼다."""
    return original(SimpleNamespace(identity=lambda: {"distribution": "fake-cli-test-only"}), audit=Path(sys.argv[2]), manifest=Path(sys.argv[3]))

solver_jobs.SolverRuntime = runtime_factory
from rfad.__main__ import main
status = main(["serve", "--workspace", sys.argv[1], "--openems-wsl"])
for module in ("openEMS", "CSXCAD", "OCP", "numpy", "PySide6", "PyQt6"):
    if any(name == module or name.startswith(module + ".") for name in sys.modules):
        raise RuntimeError("native host import: " + module)
raise SystemExit(status)
'''
        request = {"jsonrpc": "2.0", "id": "solver CLI 시험", "method": "capabilities.get", "params": {"contract_version": "rfad.api/2.0", "context": {}, "input": {}}}
        process = subprocess.run([sys.executable, "-c", script, str(self.root / "CLI 저장소"), str(self.root / "audit.json"), str(self.root / "manifest.json")],
                                 input=canonical_bytes(request) + b"\n", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20.0)
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", errors="replace"))
        lines = process.stdout.splitlines()
        self.assertEqual(len(lines), 1)
        response = json.loads(lines[0])
        self.assertEqual(response["id"], "solver CLI 시험")
        profile = response["result"]["solver_profile"]
        self.assertTrue(profile["runtime_configured"])
        self.assertTrue(profile["antenna_supported"])
        self.assertFalse(profile["antenna_physics_validated"])
        self.assertEqual(profile["board_outlines"], ["rectangle", "circle"])
        self.assertIn("rfad.openems.pcb-single-port/0.1", profile["profiles"])
        self.assertTrue(profile["nf2ff_supported"])
        self.assertTrue(profile["nf2ff"]["opt_in"])
        self.assertFalse(profile["nf2ff"]["physics_validated"])
        self.assertFalse(profile["nf2ff"]["absolute_power_supported"])
        self.assertEqual(profile["source"], "immutable_snapshot")
        self.assertEqual(profile["profile_scopes"]["rfad.openems.rect-waveguide/0.1"], "empty_reference_project_only")
        self.assertEqual(profile["execution_modes"], ["solve_and_postprocess", "postprocess_only"])
        for method in ("solver.plan", "solver.prepare", "job.submit", "result.open"):
            self.assertEqual(response["result"]["methods"][method]["status"], "implemented")


if __name__ == "__main__":
    unittest.main()
