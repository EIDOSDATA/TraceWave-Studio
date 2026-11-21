"""! @brief 발행 문서와 지역이 명시된 대역 초안만 제공한다."""

from rfad.application.target_editor_fields import blank_target
from rfad.domain.errors import ProjectError
from rfad.domain.units import Quantity, QuantityStatus


LTE = "https://www.etsi.org/deliver/etsi_ts/136100_136199/136101/17.18.00_60/ts_136101v171800p.pdf"


def _entry(identity, name, version, scope, url, band, *, reference=None, samples=()):
    """! @brief 문서가 뒷받침하는 범위와 선택한 표본 의미를 고정한다."""
    return {"id": identity + "/0.1", "name": name, "version": version, "scope": scope, "url": url,
            "band_mhz": band, "reference_mhz": reference, "samples_mhz": samples}


PRESETS = (
    _entry("ble-centers", "Bluetooth LE 40채널 중심", "Bluetooth Core 7.0, LE RFPHY 2절", "LE 공통 PHY",
           "https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Core_v7.0/out/en/low-energy-controller/radiophysical-layer-rfphy--specification.html",
           (2402, 2480), samples=tuple(range(2402, 2481, 2))),
    _entry("wifi-americas-centers", "Wi-Fi 2.4 GHz 채널 1~11 중심", "Cisco Aironet OL-4232-01, 표 2-1", "미주 기기 예시 (-A)",
           "https://www.cisco.com/E-Learning/bulk/guest/celc/fwl/index/pedia/FWL_CommandReference.pdf",
           (2412, 2462), samples=tuple(range(2412, 2463, 5))),
    _entry("lorawan-eu868", "LoRaWAN EU863-870", "LoRa Alliance RP002-1.0.3, 2.4.2절", "EU863-870 채널 계획",
           "https://lora-alliance.org/wp-content/uploads/2021/05/RP002-1.0.3-FINAL-1.pdf",
           (863, 870), samples=(868.1, 868.3, 868.5)),
    _entry("uwb-ch5", "UWB 채널 5 공칭 폭", "Qorvo APR005 Rev. A, p.1", "EU 실내 RTLS 자료의 채널 폭",
           "https://www.qorvo.com/-/media/files/qorvopublic/application-notes/apr005-v12report-on-updated-tx-power-requirements-for-indoor-uwb-rtls-applications-in-the-eu.pdf",
           (6240, 6739.2), reference=6489.6),
    _entry("gnss-gps-l1", "GNSS GPS III L1 공칭 대역", "IS-GPS-200N, 3.3.1.1절", "GPS III 이후 L1 신호 조건",
           "https://www.navcen.uscg.gov/sites/default/files/pdf/gps/IS-GPS-200N.pdf",
           (1560.075, 1590.765), reference=1575.42),
    _entry("lte-b3-ul", "셀룰러 LTE B3 상향", "ETSI TS 136 101 V17.18.0, 표 5.5-1", "E-UTRA Band 3 UE 송신", LTE, (1710, 1785)),
    _entry("lte-b3-dl", "셀룰러 LTE B3 하향", "ETSI TS 136 101 V17.18.0, 표 5.5-1", "E-UTRA Band 3 UE 수신", LTE, (1805, 1880)),
)


def choices():
    """! @brief 선택지에서 발행 판과 적용 범위를 열람할 수 있다."""
    return [{key: row[key] for key in ("id", "name", "version", "scope")} for row in PRESETS]


def draft(identity):
    """! @brief 시작·끝·표본만 제공하고 급전과 성능 한계는 수량 미정으로 둔다."""
    row = next((item for item in PRESETS if item["id"] == identity), None)
    if row is None:
        raise ProjectError("E_UNSUPPORTED", "지원하는 대역 프리셋 판을 선택하십시오.", details={"field_path": "preset_id"})
    refs = [row["id"], row["version"], row["scope"], row["url"]]

    def frequency(value):
        """! @brief 저장 시 해당 판의 원문 근거를 SI 값에 함께 복사한다."""
        return Quantity.from_value(value, "MHz", status=QuantityStatus.SOURCE_DEFAULT, source_refs=tuple(refs)).to_dict()

    target = blank_target()
    target["name"] = row["name"]
    target["source_refs"] = refs
    target["band"].update(start=frequency(row["band_mhz"][0]), end=frequency(row["band_mhz"][1]))
    if row["reference_mhz"] is not None:
        target["band"]["reference"] = frequency(row["reference_mhz"])
    samples = row["samples_mhz"]
    target["band"]["sampling"] = ({"kind": "explicit", "frequencies": [frequency(value) for value in samples]} if samples
                                  else {"kind": "linear", "count": 3})
    return target
