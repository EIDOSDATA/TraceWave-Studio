"""! @brief 실제 공급사 바이트, 유한 영역 및 원자 검토의 출처를 검사한다."""

from copy import deepcopy
from pathlib import Path
import unittest
from zipfile import ZipFile

from rfad.adapters.exchange.pcb import parse_package
from rfad.application.pcb_import_mapping import import_sources
from rfad.domain.errors import ProjectError
from rfad.domain.planar import validate_region
from rfad.domain.vendor_catalog import VENDOR_FORMATS
from test_pcb_import_mapping import fixture, run


REFERENCE = Path(__file__).resolve().parents[2] / "00_참고자료/PCB RF ANT/01_RF_Antenna_Vendor_Guides_CAD"
RENESAS = next(REFERENCE.rglob("*AN_B027_DXF*.zip"), None)


def placement(x, y):
    """! @brief 실제 GUI가 전송하는 위치와 각도 문자열을 사용한다."""
    def quantity(text, unit):
        """! @brief 원점 및 회전의 입력 단위를 명시한다."""
        return {"text": str(text), "unit": unit, "source_refs": []}
    return {"origin": [quantity(x, "mm"), quantity(y, "mm")], "rotation": quantity(0, "deg")}


@unittest.skipIf(RENESAS is None, "공식 AN-B-027 DXF 원본이 필요합니다.")
class VendorRenesasTests(unittest.TestCase):
    """! @brief 알려진 DXF의 적용 경계와 원문 불변성을 대조한다."""

    def test_five_dxf_members_and_zip_produce_same_regions(self):
        with ZipFile(RENESAS) as archive:
            for key, card in VENDOR_FORMATS.items():
                if not key.startswith("vendor_renesas_"):
                    continue
                with self.subTest(key=key):
                    from_archive = parse_package({RENESAS.name: RENESAS.read_bytes()}, key, {})
                    from_member = parse_package({card["member"]: archive.read(card["member"])}, key, {})
                    data = from_archive["records"][0]["data"]
                    self.assertEqual(data, from_member["records"][0]["data"])
                    self.assertTrue(data["regions"])
                    self.assertFalse(from_archive["physics_verified"])
                    for region in data["regions"]:
                        validate_region(region["outer_mm"], region["holes_mm"])

    def test_mismatch_cannot_be_labeled_as_vendor_original(self):
        with ZipFile(RENESAS) as archive, self.assertRaises(ProjectError) as caught:
            parse_package({"renamed.dxf": archive.read("ant_ifa.dxf")}, "vendor_renesas_ifa_ss", {})
        self.assertEqual(caught.exception.code, "E_HASH")

    def test_preview_requires_scope_confirmation_and_on_board_placement(self):
        document, _, record, mapping = fixture()
        before = deepcopy(document)
        parsed = parse_package({RENESAS.name: RENESAS.read_bytes()}, "vendor_renesas_ifa_ss", {})
        source = import_sources(parsed)
        self.assertEqual(source["layers"][0]["source"], "ET_TOP")
        mapping["layers"][0]["source"] = "ET_TOP"
        mapping["nets"] = [{"source": "", "target": None}]
        mapping["placement"] = placement(25, 25)
        self.assertFalse(run(document, parsed, record, mapping)[0]["can_apply"])
        accepted = [row["id"] for row in source["losses"]]
        review, patch = run(document, parsed, record, mapping, accepted)
        self.assertTrue(review["can_apply"], review.get("issues"))
        imported = [row["replacement"]["value"] for row in patch["changes"] if row["collection"] == "geometry"]
        self.assertEqual(len(imported), 2)
        self.assertTrue(all(not row["include_in_em"] and row["material_ref"] is None and row["net_id"] is None
                            for row in imported))
        mapping["placement"] = placement(0, 0)
        self.assertFalse(run(document, parsed, record, mapping, accepted)[0]["can_apply"])
        self.assertEqual(document, before)
