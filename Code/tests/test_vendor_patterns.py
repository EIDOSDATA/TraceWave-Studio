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
TI_IFA = next(REFERENCE.rglob("*CC2511_USB_CAD*.zip"), None)
TI_DIPOLE = next(REFERENCE.rglob("*CC25XX_DIPOLE_CAD*.zip"), None)
WB003 = next(REFERENCE.rglob("WB003.zip"), None)



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

@unittest.skipUnless(TI_IFA and TI_DIPOLE, "공식 TI 패턴 원본이 필요합니다.")
class VendorTiTests(unittest.TestCase):
    """! @brief TI의 실제 inch SPL 두 종류의 원점과 영역을 비교한다."""

    def test_independent_gerber_and_archive_use_same_copper(self):
        for format_name, path, width, height, area, parts in (
            ("vendor_ti_cc2511", TI_IFA, 14.4272, 5.41528, 22.3035221, 1),
            ("vendor_ti_cc25xx_dipole", TI_DIPOLE, 44.6405, 17.43456, 75.1786606, 29),
        ):
            with self.subTest(format_name=format_name), ZipFile(path) as archive:
                from shapely import Polygon, unary_union
                member = VENDOR_FORMATS[format_name]["member"]
                from_archive = parse_package({path.name: path.read_bytes()}, format_name, {})["records"][0]["data"]
                from_member = parse_package({member: archive.read(member)}, format_name, {})["records"][0]["data"]
                self.assertEqual(from_archive, from_member)
                regions = from_archive["regions"]
                self.assertEqual(len(regions), parts)
                for value in regions:
                    validate_region(value["outer_mm"], value["holes_mm"])
                effective = unary_union([Polygon(row["outer_mm"], row["holes_mm"]) for row in regions])
                x, y, right, top = effective.bounds
                self.assertEqual(from_archive["placement_anchor_mm"], [x, y])
                self.assertAlmostEqual(right - x, width, places=5)
                self.assertAlmostEqual(top - y, height, places=5)
                self.assertAlmostEqual(effective.area, area, places=5)

@unittest.skipIf(WB003 is None, "공식 WB003 원본이 필요합니다.")
class VendorWb003Tests(unittest.TestCase):
    """! @brief WB003의 원문 동박/clear와 겹침, 외곽 자료를 대조한다."""

    def test_layers_hole_and_original_cpw_overlap(self):
        from shapely import Polygon, unary_union
        key = "vendor_qorvo_wb003"
        with ZipFile(WB003) as outer:
            member = VENDOR_FORMATS[key]["member"]
            packet = outer.read(member)
        parsed = parse_package({WB003.name: WB003.read_bytes()}, key, {})
        data = parsed["records"][0]["data"]
        self.assertEqual(data, parse_package({"Mini-Hoe_Antenna_Gerbers.zip": packet}, key, {})["records"][0]["data"])
        sources = import_sources(parsed)
        self.assertEqual({(row["source"], row["side"]) for row in sources["layers"]}, {("Top", "top"), ("Bottom", "bottom")})
        self.assertEqual([row["source_name"] for row in sources["nets"]], [None])
        composed = {}
        for label, area in (("안테나", 68.3923), ("CPW 접지", 312.48), ("하면 접지", 324.0)):
            rows = [row for row in data["regions"] if row["label"] == label]
            for row in rows:
                validate_region(row["outer_mm"], row["holes_mm"])
            composed[label] = unary_union([Polygon(row["outer_mm"], row["holes_mm"]) for row in rows])
            self.assertAlmostEqual(composed[label].area, area, places=6)
        self.assertEqual(len(composed["안테나"].interiors), 1)
        overlap = composed["안테나"].intersection(composed["CPW 접지"])
        self.assertAlmostEqual(overlap.area, 0.8)
        self.assertEqual(overlap.bounds, (6.35, 17, 7.15, 18))
        members = {row["role"]: row for row in data["members"]}
        self.assertEqual(members["기준 외곽"]["bounds_mm"], [-9.0, 0.0, 9.0, 26.0])
        self.assertEqual(members["비아 도면"]["path"], "minihoe_via_hole.gbr")
        self.assertFalse(parsed["physics_verified"])
