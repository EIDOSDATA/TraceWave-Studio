"""! @brief 제조사 예제 선택지와 확인한 배포 원문을 연결한다."""

RENESAS_ARCHIVE = "65efabf76029e597ed93f478bb11051c3bd575babfd5820789646b2b0b1c6cc2"
RENESAS_URL = "https://lpccs-docs.renesas.com/DA14531_HW_Design_Examples/index.html"
VENDOR_FORMATS = {
    key: {"format": key, "label": "Renesas " + label + " / 2.4 GHz",
          "member": name, "sha256": digest, "archive_sha256": RENESAS_ARCHIVE,
          "source_url": RENESAS_URL, "revision": "AN-B-027 Rev. 2.5",
          "description": "AN-B-027 DXF ZIP 또는 " + name + "을 선택하세요. " + scope}
    for key, label, name, digest, scope in (
        ("vendor_renesas_ifa", "전폭 IFA", "ant_ifa.dxf",
         "3977b8e4f5f01431753b4ad8c1ae6a8fa93ab7416957f755e6df61041b41e2e8", "그림 3의 상·하부 동박."),
        ("vendor_renesas_ifa_v1", "축소 IFA 1", "ant_ifa-v1.dxf",
         "bc6c31448a88ea977e9501012a3be7e9d4dd0e1e059563854c9675857806369b", "그림 8의 동박."),
        ("vendor_renesas_ifa_v2", "축소 IFA 2", "ant_ifa-v2.dxf",
         "feb6161dda5a9f543f361dac6be983317dbab622bad8045ff905020b7c3a2d2f", "그림 13의 동박."),
        ("vendor_renesas_ifa_ss", "단층 IFA", "ant_ifa_ss.dxf",
         "868d50e3f5c5d3ee1960d3536661b709ec5ea0cccbca742e7f71bdf5c83830f6", "그림 28의 상부 동박."),
        ("vendor_renesas_zor", "ZOR", "ant_zor.dxf",
         "ff4c311ad226c4c38d72a1266355f51208e88e5aba4149378bbb4dfd130bc617", "그림 18·23의 상·하부 DXF 동박."),
    )
}


VENDOR_FORMATS.update({
    "vendor_ti_cc2511": {
        "format": "vendor_ti_cc2511", "label": "TI CC2511 USB IFA / 2.4 GHz",
        "revision": "CC2511 USB Dongle 1.3 / AN043", "member": "IFA_USB.spl",
        "source_url": "https://www.ti.com/lit/an/swra117d/swra117d.pdf",
        "archive_sha256": "554fc9527ba4ad0b35172b1771f4ba9f188725a3e7618560daa51b2f746c2689",
        "sha256": "a3828d60e68a181ae70f20c8b4c442e3280e2da64a94113e227e9d4d35bc04a1",
        "description": "CC2511 USB 참조 설계 ZIP 또는 IFA_USB.spl을 선택하세요. X/Y는 도체 경계 왼쪽 아래 기준입니다.",
    },
    "vendor_ti_cc25xx_dipole": {
        "format": "vendor_ti_cc25xx_dipole", "label": "TI CC25xx 접힌 다이폴 / 2.4 GHz",
        "revision": "CC2500EM FD 1.1 / DN004", "member": "CC25xx_Folded_Dipole.spl",
        "source_url": "https://www.ti.com/lit/an/swra118/swra118.pdf",
        "archive_sha256": "6f96cc25788f2f079e80fb9847c51234c8597367f36acee21f09dad0aec5cf04",
        "sha256": "1736564ac3d74726cf3c86f2abb11161d3ae56a1bf82de8d91c22a6d2d7ef424",
        "description": "CC25xxEM 참조 설계 ZIP 또는 CC25xx_Folded_Dipole.spl을 선택하세요. X/Y는 도체 경계 왼쪽 아래 기준입니다.",
    },
})
