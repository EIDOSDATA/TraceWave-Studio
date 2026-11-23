"""! @brief WSL 단일 포트 PCB의 체크포인트 신뢰 경계, 재시도 및 연속 계산 일치를 검사한다."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


TOOLS = Path(__file__).resolve().parents[1] / "tools"
CLI = TOOLS / "pcb_fdtd_checkpoint.py"


@unittest.skipUnless(sys.platform == "linux", "WSL Linux의 소유권과 파일 잠금이 필요합니다.")
class CheckpointInputTests(unittest.TestCase):
    """! @brief 공개 XML의 제한과 도구가 만든 상태의 봉인 경계를 대조한다."""

    def test_abnormal_exit_cannot_complete(self):
        """! @brief 통계 파일의 존재만으로 중단된 프로세스를 정상 종료에 포함하지 않는다."""
        sys.path.insert(0, str(TOOLS))
        from pcb_fdtd_checkpoint import status
        state = {"status": "running", "pid": None, "runtime": {"boot": ""}}
        with TemporaryDirectory() as temporary:
            job = Path(temporary)
            (job / "run").mkdir()
            (job / "run/openEMS_stats.txt").write_text("2000 % number of iterations")
            for code in (None, b"-9", b"1"):
                if code is not None:
                    (job / "initial-exit").write_bytes(code)
                result = status(job, state)
                self.assertEqual(result["status"], "interrupted")
                self.assertNotIn("result", result)

    def test_rejects_unsupported_xml_and_changed_state(self):
        sys.path.insert(0, str(TOOLS))
        from pcb_checkpoint_store import input_xml, save, load

        with TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / "pcb.xml"
            for content in (b"<!DOCTYPE openEMS><openEMS/>", b"<openEMS/>",
                            b"<openEMS><FDTD/><ContinuousStructure><DumpBox Name='field'/></ContinuousStructure></openEMS>"):
                file.write_bytes(content)
                with self.assertRaises(ValueError):
                    input_xml(file)
            key = os.urandom(32)
            state = {"job": root.name, "directory": str(root), "status": "suspended"}
            save(root, key, state)
            self.assertEqual(load(root, key), state)
            file = root / "state.json"
            envelope = json.loads(file.read_bytes())
            envelope["value"]["status"] = "completed"
            file.write_text(json.dumps(envelope))
            with self.assertRaises(ValueError):
                load(root, key)


@unittest.skipUnless(sys.platform == "linux" and os.getenv("RFAD_CHECKPOINT_ARC") and os.getenv("RFAD_CHECKPOINT_IFA"),
                     "단일 포트 원호 및 IFA XML과 WSL DMTCP 환경이 필요합니다.")
class NativeCheckpointTests(unittest.TestCase):
    """! @brief 실제 고정 openEMS의 연속 실행과 중단 후 재개 실행을 대조한다."""

    def test_arc_and_ifa_match_continuous_engine(self):
        sys.path.insert(0, str(TOOLS))
        from pcb_checkpoint_store import ENGINE, ARGS, TRACES, JOB_ROOT, input_xml

        def command(*args, expected=True):
            """! @brief 일반 사용자가 호출하는 별도 CLI 프로세스의 상태를 확인한다."""
            result = subprocess.run([sys.executable, str(CLI), *map(str, args)], capture_output=True, timeout=600)
            if expected:
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                return json.loads(result.stdout)
            self.assertNotEqual(result.returncode, 0)
            return result.stderr

        for name in ("ARC", "IFA"):
            with self.subTest(case=name), TemporaryDirectory() as tmp:
                baseline = Path(tmp)
                source = Path(os.environ["RFAD_CHECKPOINT_" + name])
                raw, _ = input_xml(source)
                (baseline / "pcb.xml").write_bytes(raw)
                with (baseline / "native.log").open("wb") as log, subprocess.Popen(
                        [str(ENGINE), *ARGS], cwd=baseline, stdout=log, stderr=subprocess.STDOUT) as direct:
                    job = command("start", "--xml", source)["job"]
                    suspended = command("suspend", job)
                    self.assertEqual(suspended["status"], "suspended")
                    path = JOB_ROOT / job
                    probe, = (path / "images").glob("*_files/port_ut_1_*")
                    with probe.open("ab") as stream:
                        stream.write(b"x")
                    try:
                        self.assertIn("해시".encode(), command("resume", job, expected=False))
                        self.assertFalse(any((path / "history").iterdir()))
                    finally:
                        with probe.open("r+b") as stream:
                            stream.truncate(probe.stat().st_size - 1)
                    complete = command("resume", job)
                    self.assertEqual(complete["status"], "completed")
                    self.assertEqual(command("resume", job), complete)
                    self.assertEqual(direct.wait(timeout=600), 0)
                    for trace in TRACES:
                        def samples(folder):
                            """! @brief 시각이 포함된 파일 머리말을 제외한 시간과 값 원문을 읽는다."""
                            return [line for line in (folder / trace).read_bytes().splitlines()
                                    if line and not line.startswith(b"%")]
                        self.assertEqual(samples(baseline), samples(path / "run"))
                        self.assertEqual(len(samples(baseline)), complete["samples"][trace])
                        self.assertTrue((path / "history/1" / trace).is_file())
