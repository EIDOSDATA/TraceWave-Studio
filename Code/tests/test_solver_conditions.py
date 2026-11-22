"""! @brief 이름 있는 해석 조건의 보존과 결과 출처 검사를 확인한다."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.application import solver_conditions_service, solver_evidence
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.pcb_solver import PROFILE, build_pcb_plan
from rfad.application.projects import ProjectService
from rfad.domain.errors import ProjectError
from rfad.domain.pcb_selection import EXTENSION_KEY, state_hash
from rfad.domain.project import apply_command
from rfad.domain.units import Quantity
from test_cad_worker_process import register_fixture, request, status
from test_pcb_selection_domain import selection
from test_pcb_solver import SETTINGS, fixture_document, runtime_identity


def query(service, document, **args):
    """! @brief GUI가 보내는 조건 조회의 개정과 소유 범위를 사용한다."""
    return solver_conditions_service.read(service, {
        "contract_version": "rfad.api/2.0", "context": {"project_id": document["project_id"]},
        "input": {"expected_revision": document["revision_id"], **args},
    })


def evidence(service, document, artifact_id, **args):
    """! @brief 결과 ID를 기준으로 읽기 전용 출처를 요청한다."""
    return solver_evidence.read(service, {
        "contract_version": "rfad.api/2.0", "context": {"project_id": document["project_id"]},
        "input": {"artifact_id": artifact_id, **args},
    })


class SolverConditionsTests(unittest.TestCase):
    def test_named_condition_reopens_and_survives_history_with_same_source(self):
        """! @brief 이름, 고급 옵션, 작성 기준과 실행 취소 이력을 다시 읽는다."""
        with TemporaryDirectory() as folder:
            root = Path(folder)
            settings = {**SETTINGS, "feature_subdivisions": 2,
                        "radiation": {"frequency_hz": [2.1e9, 2.2e9], "theta_step_deg": 15, "phi_step_deg": 10,
                                      "box_clearance_mm": 1},
                        "compute_profile": {"kind": "tuning_refinement/0.1", "num_threads": 4}}
            with ProjectService(root, auto_run=False) as service:
                source, _ = register_fixture(service, fixture_document())
                settings["radiation"]["frequency_hz"] = [SETTINGS["frequency_hz"]["start"],
                                                          SETTINGS["frequency_hz"]["stop"]]
                identity = source["project_id"]
                self.assertEqual(query(service, source)["saved"], [])
                data = {"expected_revision": source["revision_id"], "command_id": str(uuid4()),
                        "name": "설치 조건", "settings": settings}
                envelope = request(service, identity, data)
                saved = service.mutate("solver.conditions.save", envelope)
                self.assertEqual(service.mutate("solver.conditions.save", envelope), saved)
                state = service.journal.read()
                current = service._load(state["projects"][identity])
                record = query(service, current)["saved"][0]
                self.assertEqual(record["revision_id"], source["revision_id"])
                self.assertEqual(record["settings"], settings)
                self.assertEqual(service.journal.read(), state)
                with self.assertRaises(ProjectError) as error:
                    service.mutate("solver.conditions.save", request(service, identity, {
                        **data, "expected_revision": current["revision_id"], "command_id": str(uuid4()),
                    }))
                self.assertEqual(error.exception.code, "E_CONFLICT")
                for command in ("project.undo", "project.redo"):
                    service.mutate(command, request(service, identity, {
                        "expected_revision": current["revision_id"], "command_id": str(uuid4()),
                    }))
                    current = service._load(service.journal.read()["projects"][identity])
                    self.assertEqual(query(service, current)["saved"], [] if command == "project.undo" else [record])
                save_job = service.mutate("project.save", request(service, identity, {
                    "expected_revision": current["revision_id"],
                }))
                service.run_next()
                self.assertEqual(status(service, save_job["job_id"])["state"], "completed")
            with ProjectService(root, auto_run=False) as reopened:
                same = reopened._load(reopened.journal.read()["projects"][identity])
                self.assertEqual(query(reopened, same)["saved"], [record])

    def test_result_reuses_only_the_owned_immutable_pcb_plan(self):
        """! @brief 결과가 보존한 계획을 사용하고 다른 프로젝트와 참조 해석은 차단한다."""
        with TemporaryDirectory() as folder, ProjectService(Path(folder), auto_run=False) as service:
            fixture = fixture_document(arc=True)
            substrate = next(item for item in fixture["materials"] if item["id"] == fixture["stackup"][0]["material_id"])
            adopted = selection({**fixture, "materials": [substrate]}, published=True)
            adopted["applied_state_sha256"] = state_hash(fixture)
            fixture["extensions"][EXTENSION_KEY] = adopted
            resistance_id, formula_id = str(uuid4()), str(uuid4())
            for command, payload in (
                ("parameter.set", {"id": resistance_id, "name": "저항 원본",
                                   "quantity": Quantity.from_value(25, "ohm", source_refs=["급전 시험 기록"]).to_dict()}),
                ("parameter.set_expression", {"id": formula_id, "name": "급전 저항",
                    "expression": "base * 2", "bindings": {"base": resistance_id},
                    "dimension": "impedance", "display_unit": "ohm"}),
            ):
                fixture = apply_command(fixture, {"command_id": str(uuid4()), "type": command, "payload": payload},
                                        fixture["revision_id"])[0]
            fixture["ports"][0]["resistance"] = {"parameter_id": formula_id}
            document, snapshot = register_fixture(service, fixture)
            identity = document["project_id"]
            plan = build_pcb_plan(document, snapshot, runtime_identity(), SETTINGS)
            artifact = service.journal.put_immutable("solver-artifacts/test/plan.json", canonical_bytes(plan))
            result_id, foreign_id, reference_id = (str(uuid4()) for _ in range(3))

            def register(state):
                """! @brief 파일 해시를 가진 계획과 서로 다른 결과 소유 범위를 등록한다."""
                state["analysis_plans"][plan["plan_id"]] = {
                    "project_id": identity, "reference": {"plan_id": plan["plan_id"],
                        "content_hash": canonical_hash(plan), "artifact": artifact},
                }
                result = {"project_id": identity, "artifact_id": result_id, "metadata": {"profile": PROFILE},
                          "snapshot": snapshot, "analysis_plan_id": plan["plan_id"]}
                state["solver_results"].update({
                    result_id: result, foreign_id: {**result, "artifact_id": foreign_id, "project_id": str(uuid4())},
                    reference_id: {**result, "artifact_id": reference_id, "metadata": {"profile": "reference"}},
                })

            service.journal.transaction(register)
            state = service.journal.read()
            self.assertEqual([row["id"] for row in query(service, document)["results"]], [result_id])
            old = query(service, document, artifact_id=result_id)
            self.assertEqual(old["settings"], SETTINGS)
            self.assertEqual(old["revision_id"], document["revision_id"])
            for invalid in (foreign_id, reference_id):
                with self.assertRaises(ProjectError) as error:
                    query(service, document, artifact_id=invalid)
                self.assertEqual(error.exception.code, "E_MISSING_ARTIFACT")
                with self.assertRaises(ProjectError) as error:
                    evidence(service, document, invalid)
                self.assertEqual(error.exception.code, "E_MISSING_ARTIFACT")
            self.assertEqual(service.journal.read(), state)

            summary = evidence(service, document, result_id)
            self.assertEqual(summary["snapshot"], snapshot)
            self.assertEqual(summary["settings"], SETTINGS)
            self.assertEqual(evidence(service, document, result_id, page="revision")["document_json"].encode(),
                             canonical_bytes(document))
            feed = {"kind": "port", "id": document["ports"][0]["id"]}
            material = {"kind": "material", "id": substrate["id"]}
            port_before = evidence(service, document, result_id, page="object", **feed)
            self.assertEqual(port_before["original"]["resistance"], {"parameter_id": formula_id})
            self.assertEqual(port_before["used"]["resistance_ohm"], 50)
            self.assertEqual(port_before["parameters"][resistance_id]["original"]["quantity"]["value_si"], 25)
            self.assertIn("급전 시험 기록", [entry["reference"] for entry in port_before["sources"]])
            material_before = evidence(service, document, result_id, page="object", **material)
            entry = adopted["evidence"][0]
            index = next(i for i, row in enumerate(material_before["sources"]) if row["reference"] == entry["id"])
            source = evidence(service, document, result_id, page="source", source_index=index, **material)
            self.assertEqual(source["record"], entry)
            self.assertEqual(source["citations"][0]["pointer"], "/dk")
            self.assertIn("epsilon_r", source["fields"])
            with self.assertRaises(ProjectError) as error:
                evidence(service, document, result_id, page="source", source_index=999, **material)
            self.assertEqual(error.exception.code, "E_SCHEMA")
            with self.assertRaises(ProjectError) as error:
                evidence(service, document, result_id, page="object", kind="port", id=material["id"])
            self.assertEqual(error.exception.code, "E_MISSING_ARTIFACT")

            changed = service.mutate("project.apply_command", request(service, identity, {
                "expected_revision": document["revision_id"], "command_id": str(uuid4()), "type": "parameter.set",
                "payload": {"id": resistance_id, "name": "저항 원본",
                            "quantity": Quantity.from_value(40, "ohm", source_refs=["변경한 출처"]).to_dict()},
            }))
            state = service.journal.read()
            after = evidence(service, document, result_id)
            self.assertEqual(after["current_revision_id"], changed["new_revision"])
            self.assertNotEqual(after["current_revision_id"], after["revision_id"])
            self.assertEqual(evidence(service, document, result_id, page="object", **feed), port_before)
            self.assertEqual(evidence(service, document, result_id, page="source", source_index=index, **material), source)
            self.assertEqual(service.journal.read(), state)
