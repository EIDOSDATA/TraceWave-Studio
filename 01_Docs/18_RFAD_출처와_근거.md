# 출처, 근거, 검토 수준

개정: 3.4 / 2026-11-07 KST / 상태: 설계 기준선 승인 / 개발: 착수 전

이 문서는 최종 설계가 어떤 자료와 판단을 사용했는지 설명한다. 공식 문서에서 API가 존재함을 확인한 것, 식을 유도, 대조한 것, 프로그램을 실행한 것, 실제 안테나를 측정한 것은 서로 다른 증거이다. 이번 작업에서 RFAD 제품 실행, 전체파 해석, 제작, 실측 검증을 수행하지 않았다.

## 1. 현재 자료와 추적 규칙

- A 원본 JSON `00_baseline_A_consolidated.json`은 현재 저장소에 없다. A의 137개 요구와 출처 연결은 [사용자 요구사항](03_RFAD_사용자_요구사항.md)과 [추적표](17_RFAD_요구사항_추적표.md)에 남은 내용으로 추적하며, 원본 JSON과의 byte 일치나 전체 원본 보존을 주장하지 않는다.
- B 원문은 [추가 요구사항 원본](23_RFAD_원본_추가_요구사항.md)이다. 128개 요구와 48개 출처는 B namespace로 구별하고 원문은 보존한다.
- 현재 추출 자료의 위치와 실제 재계산한 레코드 수는 [자료 통합](20_RFAD_참고_자료_통합.md)에 있다. 과거 ZIP의 통합 출처/수식/시험 registry와 review/evidence 디렉터리는 현재 제공되지 않는다.
- 동일 URL의 다른 source ID와 당시 title/hash/locator는 추적을 위해 유지한다. 변경된 URL, 새 개정, 재확인 결과는 별도 기록으로 추가하며 원래 ID를 덮어쓰지 않는다.
- PDF는 physical page와 printed page, HTML은 section/anchor, CAD는 archive hash/member/object를 구별한다. 출처 파일이 없거나 위치가 바뀌면 `unavailable` 또는 `unresolved`로 표시하고 존재하는 증거로 취급하지 않는다.

## 2. 색인 숫자와 근거 상태

아래 표의 250개 source ID는 이전 문서에 보존된 색인이다. 고유 논문 수, 현재 다운로드 완료 수 또는 독립 검증 횟수가 아니다. A170/B48/수식 근거44/UI 참조34/시스템 추가15라는 이전 분류는 중복되며 단순 합산하지 않는다. 현재 00_REF의 source_coverage 241개 레코드와 이 설계 source ID 색인은 목적과 namespace가 다르다.

표의 `baseline_A_evidence_preserved_not_all_refetched`, `official_documentation_rechecked`, `primary_document_or_artifact_review_in_finalization` 등의 문자열은 이전 문서의 이력 표기다. 해당 과거 검토 로그가 현재 제공되지 않으므로 이번 검토의 실행 증거나 현재 URL 확인 결과로 해석하지 않는다. 이번 직접 확인한 공식 페이지와 사용 범위는 7절에 별도 기록한다. 이전의 B48 검토 집계나 source32/hash 일치 수치로 현재 실재/무결성 검사를 대신하지 않는다.

## 3. 반드시 유지할 해석상의 제한

| 사안 | 채택한 판단과 구현 영향 |
| --- | --- |
| lambda/4, microstrip epsilon_eff | 초기 길이 탐색 또는 전송선 근사. 원호, IFA, 케이스 포함 공진의 정답으로 사용하지 않는다. |
| Nordic PCA20006/G031 | 추출한 원호 좌표, 폭, grid를 검증하는 geometry fixture. 전체 적층, 그라운드, 급전, 환경이 완비된 RF 재현 모델이 아니다. |
| material epsilon_r/Df | 재질명 하나의 상수로 뭉개지 않고 주파수, 두께, 시험법, 방향, 출처, 온습도 조건을 보존한다. |
| copper roughness | Sq, Ra, Rz와 모델 파라미터를 등치하지 않는다. 적용 solver/model의 정의를 확인한다. |
| 자료 간 충돌 | TI DN023 L6, RO4730G3 Df 0.0022/0.0028, PAPER-065 0.018/18 등은 conflict로 남기고 자동 평균, 자동 선택하지 않는다. |
| 문헌 수식의 규약 | RMS/peak, exp(+j*omega*t) 또는 exp(-j*omega*t), Fourier 부호, 전류 방향과 complex Z0 파 정의를 명시한 뒤 변환한다. |
| 원문 오탈자, 단위 의심 | MathWorks FieldCalculation의 거리 factor, TI AN058의 f 단위, 역사적 Yee CFL 등은 독립 차원, 유도 검토를 우선한다. 구체적 판단은 현재 수식 문서의 해당 EQ 항목과 후속 검토 기록에 남긴다. |
| openEMS 재료, 포트 | 문서의 개요 표현을 일반 법칙으로 확대하지 않는다. 상수 물성 유효 범위와 인과성, native normalization은 별도 확인한다. |
| KiCad STEP | 동박 옵션의 존재와 실제 RF 형상, 물리 두께, 허용 오차의 보존은 다르다. display용 추가 pad 높이, merge 공차를 그대로 채택하지 않는다. |
| B-S40 | 원본 AddConductingSheet URL 실패를 보존하고 B-S02의 공식 Materials 문서를 탐색 URL로 사용한다. |
| demo, README, 논문 예제 | 도구의 가능한 흐름을 보여주는 자료이며 RFAD의 실행, 측정 정확도를 증명하지 않는다. |
| 라이선스, 재배포 | 다운로드 가능성과 재배포 허락은 별개다. 원문, 도구, 생성물별 실제 license를 기록한다. |

## 4. 공식 도구 자료에서 채택한 설계 근거

| Source ID | 문서 | 최종 설계에서의 사용 범위 |
| --- | --- | --- |
| F-SYS01 | [Qt for Python 공식 문서](https://doc.qt.io/qtforpython-6/) | 이전 기술 검토의 역사 자료. 현재 GUI는 C++ wxWidgets로 확정되었으며 Qt/PySide6는 제외한다. |
| F-SYS02 | [CadQuery Introduction](https://cadquery.readthedocs.io/en/latest/intro.html) | Python CAD 모델링 및 STEP 경로 후보. RFAD의 얇은 동박, via 재열기 시험은 별도. |
| F-SYS03 | [JSON-RPC 2.0 Specification](https://www.jsonrpc.org/specification) | 요청, 응답, notification envelope. TaskPlan과 artifact 계약은 RFAD 자체 명세. |
| F-SYS04 | [openEMS Python solver API](https://docs.openems.de/en/latest/python/openEMS/openEMS.html) | solver 생성, 시간 종료, 실행 API. 실제 binary profile과 정상 동작은 후속 계약시험. |
| F-SYS05 | [openEMS Ports API](https://docs.openems.de/en/latest/python/openEMS/ports.html) | port 및 결과 채널 API. RMS/peak와 FFT 정규화는 채널별 검증 필요. |
| F-SYS06 | [openEMS Near-Field to Far-Field](https://docs.openems.de/en/latest/concepts/nf2ff.html) | NF2FF 데이터, 사용 조건. 위상 기준과 전력 경계는 RFAD 계약과 함께 검증. |
| F-SYS07 | [KiCad 10 CLI](https://docs.kicad.org/10.0/en/cli/cli.html) | STEP copper 관련 옵션 및 CLI. pad extra thickness와 merge 거리 기본값을 물리 두께, RF 공차로 오인하지 않음. |
| F-SYS08 | [KiCad PCB S-expression File Format](https://dev-docs.kicad.org/en/file-formats/sexpr-pcb/) | PCB track/arc/polygon/layer/net 구조의 공식 형식. 실제 버전별 roundtrip 필요. |
| F-SYS09 | [Ucamco Gerber official portal](https://www.ucamco.com/en/gerber) | Gerber 제조 데이터와 사양 원문. RF 물성과 solver port 전체의 교환 형식으로 취급하지 않음. |
| F-SYS10 | [Open CASCADE STEP documentation](https://occt3d.com/dev/doc/overview/html/occt_user_guides__step.html) | 현재 STEP translator 안내. 기존 GitHub wiki는 deprecated 안내를 표시한다. 설치 버전의 schema/속성/수신 CAD 호환성은 후속 시험에서 확정한다. |
| F-SYS11 | [scikit-rf Network.renormalize](https://scikit-rf.readthedocs.io/en/latest/api/generated/skrf.network.Network.renormalize.html) | 참조 임피던스 및 s_def 재정규화 API. physical port 변경과 후처리 renormalization을 분리. |
| F-SYS12 | [SciPy differential_evolution](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.differential_evolution.html) | 제약, bounds, seed, 평가 예산을 갖는 최적화 adapter 후보. 전역 최적성 보장으로 사용하지 않음. |
| F-SYS13 | [pymoo NSGA-II](https://pymoo.org/algorithms/moo/nsga2.html) | R2 Pareto 후보 알고리즘. RF feasibility, 실패 후보, 후속 고정밀 검증은 도메인 계층 책임. |
| F-SYS14 | [IBIS Touchstone 2.1 Specification](https://ibis.org/touchstone_ver2.1/touchstone_ver2_1.pdf) | Touchstone 2.1 원문 및 네트워크 교환 규약. 결과의 형상, mesh, 전체 물성은 sidecar manifest에 유지. |
| F-SYS15 | [RFC 8785 JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785) | JSON 결정적 직렬화 후보. RFC의 지위와 binary artifact hash 규약은 별도이며 모든 JSON parser가 자동 준수하는 것은 아님. |

구체적인 선택과 대안은 [설계 결정](01_RFAD_설계_결정과_범위.md), 실제 지원 판단은 [solver 계약](11_RFAD_해석기_어댑터_계약.md) 및 [검증](14_RFAD_검증과_수용_기준.md)을 따른다. 원문의 최신 페이지를 사용했더라도 제품 의존성 버전은 R0에서 실제 설치, 실행 후 고정한다.

## 5. 전체 source ID 색인

아래 표는 탐색과 이전 출처 ID의 보존을 위한 색인이다. 현재 없는 JSON의 records/review_observations에 근거가 있다고 간주하지 않는다. 실제 주장에 사용할 때는 현존 원문과 locator를 다시 확인하고 7절의 검토 범위 또는 새 검토 기록에 연결한다.

| Source ID | 자료, 링크 | 기록 기원 | 이전 근거 표기(현재 재검증 아님) |
| --- | --- | --- | --- |
| C001 | [Ansys Electronics \| Electronic Design & Electromagnetics Simulation Software](https://ansys.synopsys.com/products/electronics) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C002 | [AEDT Antenna Toolkit - official repository](https://github.com/ansys/pyaedt-toolkits-antenna) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C003 | [Antenna wizard](https://aedt.antenna.toolkit.docs.pyansys.com/version/stable/toolkit/ui.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C004 | [Modeler3D.create_polyline](https://aedt.docs.pyansys.com/version/stable/API/_autosummary/ansys.aedt.core.modeler.modeler_3d.Modeler3D.create_polyline.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C005 | [Assigning and Creating Materials](https://ansyshelp.ansys.com/public/Views/Secured/Electronics/v242/en/Subsystems/HFSS/Subsystems/An%20Introduction%20to%20HFSS/Content/AssigningandCreatingMaterials.htm) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C006 | [Hfss.export_3d_model](https://aedt.docs.pyansys.com/version/stable/API/_autosummary/ansys.aedt.core.hfss.Hfss.export_3d_model.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C007 | [Gerber Export - HFSS 3D Layout](https://ansyshelp.ansys.com/public/Views/Secured/Electronics/v242/en/Subsystems/HFSS3DLayout/Content/3DLayout/GerberExport.htm) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C008 | [Getting Started with Ansys HFSS Software](https://learninghub.ansys.com/learn/courses/271/ansys-hfss-getting-started) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C009 | [CST Studio Suite](https://www.3ds.com/products/simulia/cst-studio-suite) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C010 | [Antenna Magus](https://www.3ds.com/products/simulia/antenna-magus) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C011 | [CST Electromagnetic Design Environment](https://www.3ds.com/products/simulia/cst-studio-suite/electromagnetic-design-environment) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C012 | [CST Electromagnetic Simulation Solvers](https://www.3ds.com/products/simulia/cst-studio-suite/electromagnetic-simulation-solvers) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C013 | [CST Workflow Integration](https://www.3ds.com/products/simulia/cst-studio-suite/workflow-integration) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C014 | [CAD (Geometry) Formats for Export - Feko](https://help.altair.com/feko/topics/feko/user_guide/chapter_heads/export_geometry_feko_c-cadfeko.htm) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C015 | [Geometry (CAD) Formats for Import - Feko](https://2025.help.altair.com/2025/feko/topics/feko/user_guide/cadfeko/import_geometry_formats_versions_feko_r-cadfeko.htm) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C016 | [Media and Supported Solution Methods - Feko](https://help.altair.com/feko/topics/feko/user_guide/cadfeko/medium_limitations_feko_r-cadfeko.htm) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C017 | [Feko Overview](https://help.altair.com/feko/topics/feko/user_guide/introduction/overview_feko_c.htm) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C018 | [Optimisation in Feko](https://help.altair.com/2024/feko/topics/feko/user_guide/optimisation/optimisation_intro_feko_c.htm) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C019 | [Introduction to Scripting and the API - Feko](https://help.altair.com/feko/topics/feko/user_guide/scripting/intro_script_api_feko_c.htm) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C020 | [DI Card - Feko](https://2021.help.altair.com/2021.2/feko/topics/feko/user_guide/appendix/editfeko_cards/control/card_di_feko_r.htm) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C021 | [Modeling Software for RF, Microwave, and Millimeter-Wave Designs - COMSOL](https://www.comsol.com/rf-module?lan=en) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C022 | [CAD Import Module - COMSOL](https://www.comsol.com/cad-import-module) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C023 | [COMSOL 6.3 - Export, ExportFinal](https://doc.comsol.com/6.3/doc/com.comsol.help.design/design_ug_ref.6.36.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C024 | [COMSOL 6.4 - Optimization Module Overview](https://doc.comsol.com/6.4/doc/com.comsol.help.opt/opt_ug_intro.4.2.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C025 | [COMSOL 6.3 - Exporting Geometry to File](https://doc.comsol.com/6.3/doc/com.comsol.help.comsol/comsol_api_geom.48.050.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C026 | [RF EM Professional (RFPro) - Keysight](https://www.keysight.com/us/en/products/design-engineering-software/electronic-design-automation/rf-suite/rf-em-professional-rfpro.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C027 | [Electromagnetics Professional (EMPro) - Keysight](https://www.keysight.com/us/en/products/design-engineering-software/electronic-design-automation/rf-suite/electromagnetics-professional-empro.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C028 | [W2110L EMPro Translator Bundle Software License [Obsolete]](https://www.keysight.com/gb/en/product/W2110L/empro-translator-bundle-software-license.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C029 | [EMPro Quick Start - 2009](https://edadownload.software.keysight.com/eedl/empro/2009/pdf/quickstart.pdf) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C030 | [EM Design (EMPro) 2026 Product Release](https://www.keysight.com.cn/cn/zh/lib/resources/software-releases/em-design-empro-2026-product-release.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C031 | [ADS 2025 Product Release](https://www.keysight.com/us/content/lib/resources/software-releases/advanced-design-system-ads-2025.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C032 | [ADS 2024 Update 1.0 Release Notes](https://docs.keysight.com/spaces/flyingpdf/pdfpageexport.action?pageId=831229529) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C033 | [AWR Design Environment Platform - Cadence](https://www.cadence.com/en_US/home/tools/system-analysis/rf-microwave-design/awr-design-environment-platform.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C034 | [AWR Analyst Datasheet - Cadence](https://www.cadence.com/en_US/home/resources/datasheets/awr-analyst-ds.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C035 | [AWR Software Datasheet - Cadence](https://www.cadence.com/ko_KR/home/resources/datasheets/awr-software-ds.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C036 | [Get Started with Cadence AntSyn](https://www.cadence.com/en_US/home/resources/videos/tools/system-analysis/get-started-with-cadence-antsyn.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C037 | [LTCC Transmit/Receive X-Band Module with a Phased Array Antenna - Cadence](https://www.cadence.com/en_US/home/resources/application-notes/ltcc-transmit-receive-x-band-module-with-a-phased-array-antenna-an.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C038 | [PCB Antenna Designer - MathWorks](https://www.mathworks.com/help/antenna/ref/pcbantennadesigner-app.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C039 | [CAD File Import and Export - Antenna Toolbox](https://www.mathworks.com/help/antenna/cad-io.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C040 | [Custom Geometry and PCB Fabrication - RF PCB Toolbox](https://www.mathworks.com/help/rfpcb/custom-geometry.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C041 | [Overview of Solvers - RF PCB Toolbox](https://www.mathworks.com/help/rfpcb/ug/overview-of-solvers.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C042 | [FEM-based Solver for RF Structures - MathWorks](https://www.mathworks.com/help/rfpcb/ug/FEM-based-solver-for-RF-structures.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C043 | [solver - Antenna Toolbox](https://www.mathworks.com/help/antenna/ref/solver.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C044 | [dielectric - MathWorks](https://www.mathworks.com/help/antenna/ref/dielectric.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C045 | [metal - MathWorks](https://www.mathworks.com/help/antenna/ref/metal.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C046 | [Antenna and Array Optimization - MathWorks](https://www.mathworks.com/help/antenna/antenna-and-array-optimization.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C047 | [Antenna Designer - MathWorks](https://www.mathworks.com/help/antenna/ref/antennadesigner-app.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C048 | [Sonnet Suites](https://www.sonnetsoftware.com/products/sonnet-suites/) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C049 | [Export Wizard - Sonnet 19.54](https://www.sonnetsoftware.com/support/doc_19.54/Topics/Interfaces_Translators/Export_Wizard.htm) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C050 | [Uniaxial Anisotropy Modeling - Sonnet](https://www.sonnetsoftware.com/products/sonnet-suites/uniaxial-anisotropy-v12.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C051 | [What's New - Sonnet 19.52](https://www.sonnetsoftware.com/support/doc_19.52/Topics/Welcome/What_s_New.htm) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C052 | [Sonnet Suites Detailed Features](https://www.sonnetsoftware.com/products/sonnet-suites/detailed-features.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C053 | [Options - Keysight ADS Interface, Sonnet 19.54](https://www.sonnetsoftware.com/support/doc_19.54/Topics/Interfaces_Translators/ADS_int/Options.htm) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C054 | [3D Electromagnetic Simulation Software \| XFdtd - Remcom](https://www.remcom.com/xfdtd-3d-em-simulation-software) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C055 | [Features - Optenni Lab](https://optenni.com/overview-of-optenni-lab/features/) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C056 | [Matching Circuit Synthesis - Optenni Lab](https://optenni.com/overview-of-optenni-lab/features/matching-circuit-synthesis-and-optimization/matching-circuit-synthesis/) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| C057 | [Importing 3D Model Files - HFSS 2026 R1](https://ansyshelp.ansys.com/public/views/secured/electronics/v261/en/subsystems/hfss/content/variables/Importing3DModelFiles.htm) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S01 | [openEMS 0.37.0 Introduction](https://docs.openems.de/en/stable/intro.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S02 | [openEMS README](https://github.com/thliebig/openEMS/blob/master/README.md) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S03 | [Near-Field to Far-Field Transformation](https://docs.openems.de/en/latest/concepts/nf2ff.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S04 | [openEMS COPYING](https://github.com/thliebig/openEMS/blob/master/COPYING) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S05 | [CSXCAD.pyx license header](https://github.com/thliebig/CSXCAD/blob/master/python/CSXCAD/CSXCAD.pyx) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S06 | [FreeCAD-OpenEMS-Export README](https://github.com/LubomirJagos/FreeCAD-OpenEMS-Export) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S07 | [FreeCAD exporter LICENSE](https://github.com/LubomirJagos/FreeCAD-OpenEMS-Export/blob/main/LICENSE) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S08 | [gerber2ems README](https://github.com/antmicro/gerber2ems) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S09 | [gerber2ems stackup and settings](https://github.com/antmicro/gerber2ems) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S10 | [gerber2ems LICENSE](https://github.com/antmicro/gerber2ems/blob/main/LICENSE) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S11 | [pyems README](https://github.com/matthuszagh/pyems) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S12 | [pyems COPYING](https://github.com/matthuszagh/pyems/blob/master/COPYING) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S13 | [AntennaCAT README](https://github.com/LC-Linkous/AntennaCalculationAutotuningTool) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S14 | [AntennaCAT release notes and integration scope](https://github.com/LC-Linkous/AntennaCalculationAutotuningTool/blob/main/README.md?plain=1) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S15 | [AntennaCAT LICENSE](https://github.com/LC-Linkous/AntennaCalculationAutotuningTool/blob/main/LICENSE) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S16 | [AntennaCAT DXF import caveat](https://github.com/LC-Linkous/AntennaCalculationAutotuningTool/blob/main/README.md?plain=1) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S17 | [KiCad 9.0 Command-Line Interface](https://docs.kicad.org/9.0/en/cli/cli.html) | baseline_A; final_UI_FN_reference | baseline_A_evidence_preserved_not_all_refetched |
| OS-S18 | [KiCad licenses](https://www.kicad.org/about/licenses/) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S19 | [KiCad source LICENSE.README](https://github.com/KiCad/kicad-source-mirror/blob/master/LICENSE.README) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S20 | [FreeCAD features](https://www.freecad.org/features) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S21 | [FreeCAD LICENSE](https://github.com/FreeCAD/FreeCAD/blob/main/LICENSE) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S22 | [CadQuery Importing and Exporting Files](https://cadquery.readthedocs.io/en/latest/importexport.html) | baseline_A; final_UI_FN_reference | baseline_A_evidence_preserved_not_all_refetched |
| OS-S23 | [CadQuery LICENSE](https://github.com/CadQuery/cadquery/blob/master/LICENSE) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S24 | [build123d 0.12.0 Import/Export](https://build123d.readthedocs.io/en/stable/import_export.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S25 | [build123d LICENSE (dev branch)](https://github.com/gumyr/build123d/blob/dev/LICENSE) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S26 | [OCCT STEP Translator](https://www.occt3d.com/dev/doc/overview/html/occt_user_guides__step.html) | baseline_A; final_UI_FN_reference | baseline_A_evidence_preserved_not_all_refetched |
| OS-S27 | [OCCT LGPL license text](https://github.com/Open-Cascade-SAS/OCCT/blob/master/LICENSE_LGPL_21.txt) | baseline_A; final_UI_FN_reference | baseline_A_evidence_preserved_not_all_refetched |
| OS-S28 | [OCCT LGPL Exception](https://github.com/Open-Cascade-SAS/OCCT/blob/master/OCCT_LGPL_EXCEPTION.txt) | baseline_A; final_UI_FN_reference | baseline_A_evidence_preserved_not_all_refetched |
| OS-S29 | [Meep README](https://github.com/NanoComp/meep) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S30 | [Meep Python User Interface](https://meep.readthedocs.io/en/stable/Python_User_Interface/) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S31 | [Meep Adjoint Solver](https://meep.readthedocs.io/en/latest/Python_Tutorials/Adjoint_Solver/) | baseline_A; final_UI_FN_reference | baseline_A_evidence_preserved_not_all_refetched |
| OS-S32 | [Meep LICENSE](https://github.com/NanoComp/meep/blob/master/LICENSE) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S33 | [Meep License and Copyright](https://meep.readthedocs.io/en/latest/License_and_Copyright/) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S34 | [Palace README](https://github.com/awslabs/palace) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S35 | [Palace Extracting Fields in the Radiation Zone](https://awslabs.github.io/palace/v0.16.0/features/farfield/) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S36 | [Palace Boundary Conditions](https://awslabs.github.io/palace/v0.16.0/guide/boundaries/) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S37 | [Palace config Domains](https://awslabs.github.io/palace/v0.16.0/config/domains/) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S38 | [Palace LICENSE](https://github.com/awslabs/palace/blob/main/LICENSE) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S39 | [Palace dipole antenna example](https://github.com/awslabs/palace/blob/main/docs/src/examples/antenna.md) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S40 | [SCUFF-RF documentation](https://homerreid.github.io/scuff-em-documentation/applications/scuff-rf/scuff-rf/) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S41 | [SCUFF-EM Microstrip RF Devices](https://homerreid.github.io/scuff-em-documentation/examples/MicrostripDevices/MicrostripDevices/) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S42 | [SCUFF-EM Geometry descriptions](https://homerreid.github.io/scuff-em-documentation/reference/Geometries/) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S43 | [SCUFF-EM LICENSE](https://github.com/HomerReid/scuff-em/blob/master/LICENSE) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S44 | [Gmsh 4.15.2 Reference Manual](https://gmsh.info/doc/texinfo/gmsh.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S45 | [Gmsh manual Appendix F License](https://gmsh.info/doc/texinfo/gmsh.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S46 | [GetDP 3.5.0 manual](https://getdp.info/doc/texinfo/getdp.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S47 | [GetDP project homepage](https://getdp.info/) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S48 | [scikit-rf documentation](https://scikit-rf.readthedocs.io/en/latest/) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S49 | [scikit-rf workshop](https://github.com/scikit-rf/scikit-rf_workshop) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S50 | [scikit-rf LICENSE.txt](https://github.com/scikit-rf/scikit-rf/blob/master/LICENSE.txt) | baseline_A; final_UI_FN_reference | baseline_A_evidence_preserved_not_all_refetched |
| OS-S51 | [openEMS Learn More: interfacing tools](https://docs.openems.de/en/v0.37.0/more.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S52 | [CSXCAD README](https://github.com/thliebig/CSXCAD) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S53 | [Fairbeam official homepage](https://fairbeam.org/) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S54 | [Fairbeam upstream README](https://github.com/ismailakdag/fairbeam) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S55 | [Fairbeam drawings, figures and fabrication](https://fairbeam.org/docs/exports.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S56 | [Fairbeam optimizer](https://fairbeam.org/docs/optimize.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S57 | [Fairbeam validation](https://fairbeam.org/docs/validation.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S58 | [Fairbeam LICENSE](https://github.com/ismailakdag/fairbeam/blob/main/LICENSE) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S59 | [Fairbeam project bundle format](https://fairbeam.org/docs/bundle.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S60 | [openEMS Dispersive Materials](https://docs.openems.de/en/latest/concepts/dispersive.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S61 | [openEMS AddConductingSheet](https://docs.openems.de/en/latest/octave/autogenerated/CSXCAD/AddConductingSheet.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| OS-S62 | [openEMS FAQ](https://docs.openems.de/en/latest/faq.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| BOOK_MIT_STAELIN | [Electromagnetics and Applications](https://www.ocw.mit.edu/courses/6-013-electromagnetics-and-applications-spring-2009/mit6_013_s09_coursetextbook.pdf) | baseline_A; final_physics_review | primary_document_or_artifact_review_in_finalization |
| DUPONT_PYRALUX_AP | [Pyralux AP All-Polyimide Double-Sided Copper-Clad Laminate Data Sheet](https://www.qnityelectronics.com/pyralux-ap.html) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| ISOLA_ASTRA_DKDF | [Astra MT77 Dk/Df Construction Tables](https://www.isola-group.com/pcb-laminates-prepreg/astra-mt77-laminate-and-prepreg/) | baseline_A; final_UI_FN_reference | baseline_A_evidence_preserved_not_all_refetched |
| ISOLA_FR408HR_DKDF | [FR408HR Dk/Df Construction Tables](https://www.isola-group.com/pcb-laminates-prepreg/fr408hr-laminate-and-prepreg/) | baseline_A; final_UI_FN_reference | baseline_A_evidence_preserved_not_all_refetched |
| KEYSIGHT_IMPEDANCE_HANDBOOK | [Impedance Measurement Handbook: A Guide to Measurement Technology and Techniques - 5950-3000](https://www.keysight.com/us/en/assets/7018-06840/application-notes/5950-3000.pdf) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| LORA_ALLIANCE_RP002_1_0_5 | [RP002-1.0.5 - LoRaWAN Regional Parameters](https://resources.lora-alliance.org/technical-specifications/rp002-1-0-5-lorawan-regional-parameters) | baseline_A; final_UI_FN_reference | baseline_A_evidence_preserved_not_all_refetched |
| MEEP_DISPERSION | [Meep - Material Dispersion](https://meep.readthedocs.io/en/latest/Python_Tutorials/Material_Dispersion/) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| MEEP_NF2FF | [Meep - Near-to-Far Field Spectra](https://meep.readthedocs.io/en/latest/Python_Tutorials/Near_to_Far_Field_Spectra/) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| NIST_TN1507 | [Uncertainty Assessment for Standard Antenna Measurements on the Open Area Test Site](https://www.nist.gov/publications/uncertainty-assessment-standard-antenna-measurements-open-area-test-site) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| NORDIC_NWP008 | [nWP008 - lambda/4 printed monopole antenna for 2.45 GHz](https://nrfconnectdocs.nordicsemi.com/pdf/nwp_008/nwp_008.pdf) | baseline_A; final_physics_review; final_UI_FN_reference | primary_document_or_artifact_review_in_finalization |
| NORDIC_NWP013 | [nWP013 - Tuning the nRF24xx matching network](https://nrfconnectdocs.nordicsemi.com/pdf/nwp_013/nwp_013.pdf) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| NORDIC_NWP017 | [nWP017 - Antenna tuning](https://nrfconnectdocs.nordicsemi.com/pdf/nwp_017/nwp_017.pdf) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| NORDIC_PCA20006_CAD | [nRF51822 Bluetooth Smart Beacon Kit - PCA20006 / PCB400059 hardware files](https://devzone.nordicsemi.com/cfs-file/__key/support-attachments/beef5d1b77644c448dabff31668f3a47-1f949ef4dfa645c8b62851b8ead3970f/nRF51822-Bluetooth-Smart-Beacon-kit-hardware-files.zip) | baseline_A; final_physics_review | primary_document_or_artifact_review_in_finalization |
| NPL_GUIDE73 | [Calibration and Use of Antennas, Focusing on EMC Applications - Good Practice Guide 73](https://eprintspublications.npl.co.uk/3520/) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| NXP_AN12549 | [AN12549 - PN5190 antenna design guide](https://www.nxp.com/docs/en/application-note/AN12549.pdf) | baseline_A; final_physics_review; final_UI_FN_reference | primary_document_or_artifact_review_in_finalization |
| NXP_AN1629 | [AN1629 - UHF RFID Label Antenna Design (file AN162910)](https://www.nxp.com/docs/en/application-note/AN162910.pdf) | baseline_A; final_UI_FN_reference | baseline_A_evidence_preserved_not_all_refetched |
| NXP_AN1715 | [AN1715 - UHF RFID PCB antenna design (file AN171530)](https://www.nxp.com/docs/en/application-note/AN171530.pdf) | baseline_A; final_physics_review; final_UI_FN_reference | primary_document_or_artifact_review_in_finalization |
| OPENEMS_MATERIALS | [openEMS - Properties and Materials](https://docs.openems.de/en/latest/concepts/properties.html) | baseline_A; final_physics_review; final_UI_FN_reference | primary_document_or_artifact_review_in_finalization |
| OPENEMS_MESH | [openEMS - Mesh](https://docs.openems.de/en/latest/concepts/mesh.html) | baseline_A; final_physics_review; final_UI_FN_reference | primary_document_or_artifact_review_in_finalization |
| OPENEMS_NF2FF | [openEMS - Near-Field to Far-Field API](https://docs.openems.de/en/latest/python/openEMS/nf2ff.html) | baseline_A; final_physics_review; final_UI_FN_reference | primary_document_or_artifact_review_in_finalization |
| OPENEMS_PATCH | [openEMS - Simple Patch Antenna](https://docs.openems.de/en/latest/python/openEMS/Tutorials/Simple_Patch_Antenna.html) | baseline_A; final_physics_review | primary_document_or_artifact_review_in_finalization |
| OPENEMS_PORTS | [openEMS - Ports](https://docs.openems.de/en/latest/python/openEMS/ports.html) | baseline_A; final_physics_review; final_UI_FN_reference | primary_document_or_artifact_review_in_finalization |
| PAPER-031 | [Compact Asymmetric T-Feed Closed-Slot Antennas for 2.4/5/6 GHz WiFi-7 MIMO Laptops](https://www.mdpi.com/2079-9292/13/13/2430/pdf) | baseline_A; final_physics_review | primary_document_or_artifact_review_in_finalization |
| PAPER-043 | [The art of UHF RFID antenna design: Impedance-matching and size-reduction techniques](https://art.torvergata.it/bitstream/2108/31667/44089/AP-Magaz_tag_Tutorial_2008.pdf) | baseline_A; final_physics_review | primary_document_or_artifact_review_in_finalization |
| PAPER-065 | [Printed Newton's egg curved monopole antenna for ultrawideband applications](https://ietresearch.onlinelibrary.wiley.com/doi/full/10.1049/iet-map.2013.0144) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| PAPER-066 | [Antenna Study and Design for Ultra Wideband Communication Applications](http://ael.chungbuk.ac.kr/lectures/undergraduate/%EC%A2%85%ED%95%A9%EC%84%A4%EA%B3%84-1/2018-2/%EC%9D%B4%EC%88%98%ED%98%B8/liang(06-thesis).pdf) | baseline_A; final_physics_review | primary_document_or_artifact_review_in_finalization |
| PAPER-067 | [Pulse Preserving Capabilities of Printed Circular Disk Monopole Antennas with Different Substrates](https://www.jpier.org/ac_api/download.php?id=07092004) | baseline_A; final_physics_review | primary_document_or_artifact_review_in_finalization |
| PAPER-068 | [Numerical solution of initial boundary value problems involving maxwell's equations in isotropic media](https://doi.org/10.1109/TAP.1966.1138693) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| PAPER-069 | [Electromagnetic scattering by surfaces of arbitrary shape](https://doi.org/10.1109/TAP.1982.1142818) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| PAPER-070 | [A perfectly matched layer for the absorption of electromagnetic waves](https://doi.org/10.1006/jcph.1994.1159) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| PAPER-071 | [Accurate Models for Microstrip Computer-Aided Design](https://doi.org/10.1109/MWSYM.1980.1124303) | baseline_A; final_physics_review | primary_document_or_artifact_review_in_finalization |
| QORVO_APH007 | [APH007 - Antenna Selection / Design Guide for DW1000](https://www.qorvo.com/products/p/DW1000) | baseline_A; final_physics_review; final_UI_FN_reference | primary_document_or_artifact_review_in_finalization |
| QORVO_APS014 | [APS014 - Antenna Delay Calibration of DW1000-Based Products and Systems](https://www.qorvo.com/products/r/ra007040) | baseline_A; final_physics_review | primary_document_or_artifact_review_in_finalization |
| ROGERS_COPPER_FOIL | [Copper Foils for High Frequency Circuit Materials](https://www.rogerscorp.com/advanced-electronics-solutions/rt-duroid-laminates/rt-duroid-5880-laminates) | baseline_A; final_physics_review; final_UI_FN_reference | primary_document_or_artifact_review_in_finalization |
| ROGERS_ISOTROPY | [The Advantage of Nearly Isotropic Dielectric Constant of RT/duroid 5870-5880 Glass Microfiber PTFE](https://www.rogerscorp.com/advanced-electronics-solutions/rt-duroid-laminates/rt-duroid-5880-laminates) | baseline_A; final_physics_review; final_UI_FN_reference | primary_document_or_artifact_review_in_finalization |
| ROGERS_RO3000_BONDPLY | [RO3000 Series Bondply Data Sheet Processing Guidelines](https://www.rogerscorp.com/advanced-electronics-solutions/ro3000-series-laminates/ro3003-laminates) | baseline_A; final_UI_FN_reference | baseline_A_evidence_preserved_not_all_refetched |
| ROGERS_RO3000_DS | [RO3000 Laminate Data Sheet RO3003 - RO3006 - RO3010 - RO3035](https://www.rogerscorp.com/advanced-electronics-solutions/ro3000-series-laminates/ro3003-laminates) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| ROGERS_RO4000_DS | [RO4003C and RO4350B High Frequency Circuit Materials Data Sheet](https://rogerscorp.com/-/media/project/rogerscorp/documents/advanced-electronics-solutions/english/data-sheets/ro4000-laminates-ro4003c-and-ro4350b---data-sheet.pdf) | baseline_A; final_physics_review; final_UI_FN_reference | primary_document_or_artifact_review_in_finalization |
| ROGERS_RO47_DS | [RO4725JXR and RO4730G3 Antenna Grade Laminates Data Sheet](https://www.rogerscorp.com/advanced-electronics-solutions/ro4000-series-laminates/ro4700-antenna-grade-laminates) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| RS_8GE01_ANTENNA_BASICS | [8GE01 - Antenna Basics](https://scdn.rohde-schwarz.com/ur/pws/dl_downloads/premiumdownloads/premium_dl_brochures_and_datasheets/premium_dl_whitepaper/Antenna_Basics_8GE01_1e.pdf) | baseline_A; final_physics_review | primary_document_or_artifact_review_in_finalization |
| SILABS_AN1088 | [AN1088 - Designing with an Inverted-F 2.4 GHz PCB Antenna](https://www.silabs.com/documents/public/application-notes/an1088-designing-with-pcb-antenna.pdf) | baseline_A; final_physics_review | primary_document_or_artifact_review_in_finalization |
| SILABS_AN1195 | [AN1195 - Antenna Array Design Guidelines for Direction Finding](https://www.silabs.com/documents/public/application-notes/an1195-antenna-array-direction-finding.pdf) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| SILABS_AN1275 | [AN1275 - Impedance Matching Network Architectures](https://www.silabs.com/documents/public/application-notes/an1275-imp-match-for-network-arch.pdf) | baseline_A; final_physics_review | primary_document_or_artifact_review_in_finalization |
| SKRF_CALIBRATION | [scikit-rf - Calibration](https://scikit-rf.readthedocs.io/en/latest/tutorials/Calibration.html) | baseline_A; final_UI_FN_reference | baseline_A_evidence_preserved_not_all_refetched |
| SKRF_MANUAL_PDF | [scikit-rf Documentation - downloadable manual](https://scikit-rf.readthedocs.io/_/downloads/en/latest/pdf/) | baseline_A; final_physics_review | primary_document_or_artifact_review_in_finalization |
| SKRF_MATCHING | [scikit-rf - Impedance Matching](https://scikit-rf.readthedocs.io/en/latest/examples/matching/Impedance%20Matching.html) | baseline_A; final_UI_FN_reference | baseline_A_evidence_preserved_not_all_refetched |
| SKRF_NETWORKS | [scikit-rf - Networks](https://scikit-rf.readthedocs.io/en/latest/tutorials/Networks.html) | baseline_A; final_physics_review; final_UI_FN_reference | primary_document_or_artifact_review_in_finalization |
| ST_AN5457 | [AN5457 - RF matching network design guide for STM32WL Series](https://www.st.com/resource/en/application_note/an5457-rf-matching-network-design-guide-for-stm32wl-series-stmicroelectronics.pdf) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| TI_AN058_SWRA161 | [AN058 - Antenna Selection Guide](https://www.ti.com/lit/pdf/swra161) | baseline_A; final_physics_review; final_UI_FN_reference | primary_document_or_artifact_review_in_finalization |
| TI_DN023_SWRA228 | [DN023 - 868 MHz, 915 MHz and 955 MHz Inverted-F Antenna](https://www.ti.com/lit/pdf/swra228) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| CORPUS-DATASET-1 | [RF 안테나 구조화 추출 데이터 v1](https://chatgpt.com/library?file_id=libfile_5a1616914ae08191a420f975e9fd254b&account_id=personal) | baseline_A | baseline_A_evidence_preserved_not_all_refetched |
| B-S01 | [openEMS Dispersive Materials](https://docs.openems.de/en/latest/concepts/dispersive.html) | baseline_B_review; final_physics_review | primary_document_or_artifact_review_in_finalization |
| B-S02 | [openEMS Materials and Conducting Sheet](https://docs.openems.de/en/latest/octave/autogenerated/CSXCAD/materials.html) | baseline_B_review; final_physics_review | primary_document_or_artifact_review_in_finalization |
| B-S03 | [MathWorks Field Calculation in Antennas](https://www.mathworks.com/help/antenna/ug/field-calculation-in-antennas.html) | baseline_B_review; final_physics_review | primary_document_or_artifact_review_in_finalization |
| B-S04 | [MathWorks pcbStack](https://www.mathworks.com/help/antenna/ref/pcbstack.html) | baseline_B_review | not_rechecked_current_review |
| B-S05 | [KiCad Command Line Interface STEP Export](https://docs.kicad.org/9.0/en/cli/cli.html) | baseline_B_review | baseline_A_documentation_evidence |
| B-S06 | [FreeCAD Import and Export File Types](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Manual_Import_and_export_to_other_filetypes.md) | baseline_B_review | not_rechecked_current_review |
| B-S07 | [Sonnet Antennas and Radiation](https://www.sonnetsoftware.com/support/doc_19.54/Topics/Antennas_and_Radiation/Antennas_and_Radiation.htm) | baseline_B_review | not_rechecked_current_review |
| B-S08 | [Qucs RFlayout 공식 저장소](https://github.com/thomaslepoix/Qucs-RFlayout) | baseline_B_review | official_documentation_rechecked |
| B-S09 | [Antmicro KiCad SI Simulation Wrapper](https://github.com/antmicro/kicad-si-simulation-wrapper) | baseline_B_review | official_documentation_rechecked |
| B-S10 | [Palace 공식 문서](https://awslabs.github.io/palace/stable/) | baseline_B_review | not_rechecked_current_review |
| B-S11 | [Meep 공식 문서](https://meep.readthedocs.io/en/master/) | baseline_B_review | not_rechecked_current_review |
| B-S12 | [CADFEKO Geometry Formats for Export](https://help.altair.com/feko/topics/feko/user_guide/chapter_heads/export_geometry_feko_c-cadfeko.htm) | baseline_B_review | baseline_A_documentation_evidence |
| B-S13 | [HFSS Exporting 3D Model Files](https://ansyshelp.ansys.com/public/views/secured/electronics/v261/en/Subsystems/HFSS/Content/Variables/Exporting3DModelFiles.htm) | baseline_B_review | not_rechecked_current_review |
| B-S14 | [webantenna 공식 저장소](https://github.com/vkopitsa/webantenna) | baseline_B_review | official_documentation_rechecked |
| B-S15 | [Fairbeam 기능과 공개 한계](https://fairbeam.org/features.html) | baseline_B_review | not_rechecked_current_review |
| B-S16 | [antenna cad 공식 저장소](https://github.com/jman4162/antenna-cad) | baseline_B_review | official_documentation_rechecked |
| B-S17 | [EMStudioFree 공식 저장소](https://github.com/king-aj3/EMStudioFree) | baseline_B_review | official_documentation_rechecked |
| B-S18 | [FreeCAD OpenEMS Export 공식 저장소](https://github.com/LubomirJagos/FreeCAD-OpenEMS-Export) | baseline_B_review | baseline_A_documentation_evidence |
| B-S19 | [pyems 공식 저장소](https://github.com/matthuszagh/pyems) | baseline_B_review | baseline_A_documentation_evidence |
| B-S20 | [Antmicro gerber2ems 공식 저장소](https://github.com/antmicro/gerber2ems) | baseline_B_review | baseline_A_documentation_evidence |
| B-S21 | [AntennaCAT 공식 저장소](https://github.com/LC-Linkous/AntennaCalculationAutotuningTool) | baseline_B_review | baseline_A_documentation_evidence |
| B-S22 | [AntennaCalculator 공식 저장소](https://github.com/Dollarhyde/AntennaCalculator) | baseline_B_review | official_documentation_rechecked |
| B-S23 | [Antenna Insyght 공식 저장소](https://github.com/insyght-io/Antenna-Insyght) | baseline_B_review | official_documentation_rechecked |
| B-S24 | [MATLAB PCB Antenna Designer](https://www.mathworks.com/help/antenna/ref/pcbantennadesigner-app.html) | baseline_B_review | baseline_A_documentation_evidence |
| B-S25 | [Antenna Magus 공식 제품 설명](https://www.3ds.com/products/simulia/antenna-magus) | baseline_B_review | baseline_A_documentation_evidence |
| B-S26 | [Cadence AntSyn 공식 소개](https://www.cadence.com/en_US/home/resources/videos/tools/system-analysis/get-started-with-cadence-antsyn.html) | baseline_B_review | baseline_A_documentation_evidence |
| B-S27 | [Ansys AEDT Antenna Wizard](https://aedt.antenna.toolkit.docs.pyansys.com/version/stable/toolkit/ui.html) | baseline_B_review | baseline_A_documentation_evidence |
| B-S28 | [Feko CADFEKO Component Library](https://help.altair.com/feko/topics/feko/user_guide/cadfeko/component_database_feko_c-cadfeko.htm) | baseline_B_review | not_rechecked_current_review |
| B-S29 | [CENOS RF 공식 문서와 FAQ](https://cenos-platform.com/documentation/radio-frequency/) | baseline_B_review | official_documentation_rechecked |
| B-S30 | [Keysight RFPro 공식 제품 설명](https://www.keysight.com/us/en/products/design-engineering-software/electronic-design-automation/rf-suite/rf-em-professional-rfpro.html) | baseline_B_review | baseline_A_documentation_evidence |
| B-S31 | [Taoglas Antenna Integrator](https://www.taoglas.com/taoglas-antenna-integrator./) | baseline_B_review | official_documentation_rechecked |
| B-S32 | [COMSOL RF Module](https://www.comsol.com/rf-module) | baseline_B_review | not_rechecked_current_review |
| B-S33 | [Remcom XFdtd Antenna Simulation Workflow](https://www.support.remcom.com/xfdtd/users-guide/antenna-design/antenna-simulation-workflow.html) | baseline_B_review | not_rechecked_current_review |
| B-S34 | [KiCad 10.0 PCB Editor - 3D export conductor options and coordinates](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html) | baseline_B_review | not_rechecked_current_review |
| B-S35 | [Ucamco - Gerber Layer Format Specification, Revision 2026.05](https://www.ucamco.com/files/downloads/file_en/554/gerber-layer-format-specification-revision-2026-05_en.pdf) | baseline_B_review; final_UI_FN_reference; final_UI_FN_recheck | primary_document_or_artifact_review_in_finalization |
| B-S36 | [Ucamco - Gerber Job Format Specification, Revision 2020.08](https://www.ucamco.com/files/downloads/file_en/435/gerber-job-format-specification-revision-2020-08_en.pdf) | baseline_B_review; final_UI_FN_reference; final_UI_FN_recheck | primary_document_or_artifact_review_in_finalization |
| B-S37 | [Open Cascade - STEP translator, official OCCT documentation](https://github.com/Open-Cascade-SAS/OCCT/wiki/step) | baseline_B_review | not_rechecked_current_review |
| B-S38 | [Rogers Digging Deeper into Dielectric Constant for PCB Materials](https://www.rogerscorp.com/blog/2020/digging-deeper-into-dielectric-constant-for-pcb-materials) | baseline_B_review | not_rechecked_current_review |
| B-S39 | [Rogers RO4000 Laminates Data Sheet](https://rogerscorp.com/-/media/project/rogerscorp/documents/advanced-electronics-solutions/english/data-sheets/ro4000-laminates-ro4003c-and-ro4350b---data-sheet.pdf) | baseline_B_review | official_documentation_rechecked_by_team |
| B-S40 | [openEMS AddConductingSheet](https://docs.openems.de/en/latest/octave/autogenerated/CSXCAD/materials.html) | baseline_B_review | original_url_unavailable_replacement_verified |
| B-S41 | [openEMS Mesh](https://docs.openems.de/en/stable/concepts/mesh.html) | baseline_B_review | not_rechecked_current_review |
| B-S42 | [openEMS Ports](https://docs.openems.de/en/latest/concepts/ports.html) | baseline_B_review | official_documentation_rechecked_by_team |
| B-S43 | [openEMS Near Field to Far Field Transformation](https://docs.openems.de/en/stable/concepts/nf2ff.html) | baseline_B_review | not_rechecked_current_review |
| B-S44 | [Remcom Antenna Group Delay](https://www.support.remcom.com/xfdtd/users-guide/antenna-design/antenna-group-delay.html) | baseline_B_review | not_rechecked_current_review |
| B-S45 | [NXP NFC Antenna Design Tool User Manual UM11232](https://www.nxp.com/docs/en/user-manual/UM11232.pdf) | baseline_B_review; final_UI_FN_reference; final_UI_FN_recheck | primary_document_or_artifact_review_in_finalization |
| B-S46 | [Ansys Assigning Finite Conductivity Boundaries](https://ansyshelp.ansys.com/public/Views/Secured/Electronics/v261/en/Subsystems/HFSS/Content/HFSS/AssigningFiniteConductivityBoundaries.htm) | baseline_B_review | not_rechecked_current_review |
| B-S47 | [openEMS Boundary Conditions](https://docs.openems.de/en/latest/concepts/bc.html) | baseline_B_review | not_rechecked_current_review |
| B-S48 | [Dama et al Envelope Correlation Including Power Losses](https://onlinelibrary.wiley.com/doi/10.1155/2011/421691) | baseline_B_review; final_physics_review | primary_document_or_artifact_review_in_finalization |
| SCIKIT_RF_WAVES | [SCIKIT_RF_WAVES](https://scikit-rf.readthedocs.io/en/latest/examples/networktheory/Working%20with%20Complex%20Characteristic%20Impedances.html) | final_physics_review | primary_document_or_artifact_review_in_finalization |
| SCIKIT_RF_S2Z | [SCIKIT_RF_S2Z](https://scikit-rf.readthedocs.io/en/latest/api/generated/skrf.network.s2z.html) | final_physics_review | primary_document_or_artifact_review_in_finalization |
| SCIKIT_RF_Z2S | [SCIKIT_RF_Z2S](https://scikit-rf.readthedocs.io/en/latest/api/generated/skrf.network.z2s.html) | final_physics_review | primary_document_or_artifact_review_in_finalization |
| SCIKIT_RF_RENORM | [SCIKIT_RF_RENORM](https://scikit-rf.readthedocs.io/en/latest/api/generated/skrf.network.renormalize_s.html) | final_physics_review | primary_document_or_artifact_review_in_finalization |
| SCIKIT_RF_CIRCUIT | [SCIKIT_RF_CIRCUIT](https://scikit-rf.readthedocs.io/en/latest/tutorials/Circuit.html) | final_physics_review | primary_document_or_artifact_review_in_finalization |
| SCIKIT_RF_VI | [SCIKIT_RF_VI](https://scikit-rf.readthedocs.io/en/latest/examples/circuit/Voltages%20and%20Currents%20in%20Circuits.html) | final_physics_review | primary_document_or_artifact_review_in_finalization |
| NIST_MARKS_1992 | [NIST_MARKS_1992](https://www.nist.gov/publications/general-waveguide-circuit-theory) | final_physics_review | primary_document_or_artifact_review_in_finalization |
| JCGM100_2008 | [JCGM100_2008](https://www.bipm.org/documents/20126/2071204/JCGM_100_2008_E.pdf) | final_physics_review | primary_document_or_artifact_review_in_finalization |
| NIST_BINOMIAL_CI | [NIST_BINOMIAL_CI](https://www.itl.nist.gov/div898/software/dataplot/refman1/auxillar/propconf.htm) | final_physics_review | primary_document_or_artifact_review_in_finalization |
| SCIPY_BINOMIAL_CI | [SCIPY_BINOMIAL_CI](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.binomtest.html) | final_physics_review | primary_document_or_artifact_review_in_finalization |
| ANSYS_SLOT_SEED | [ANSYS_SLOT_SEED](https://innovationspace.ansys.com/courses/wp-content/uploads/sites/5/2022/07/antenna_types_slot.pdf) | final_physics_review | primary_document_or_artifact_review_in_finalization |
| MATHWORKS_PATCH_SEED | [MATHWORKS_PATCH_SEED](https://www.mathworks.com/help/antenna/ug/impedance-analysis-of-2-by-2-patch-array.html) | final_physics_review; final_UI_FN_reference | primary_document_or_artifact_review_in_finalization |
| DEB_NSGA2_2002 | [DEB_NSGA2_2002](https://doi.org/10.1109/4235.996017) | final_physics_review | primary_document_or_artifact_review_in_finalization |
| NUMPY_FFT_NORMALIZATION | [NUMPY_FFT_NORMALIZATION](https://numpy.org/doc/stable/reference/routines.fft.html) | final_physics_review | primary_document_or_artifact_review_in_finalization |
| QT_QGRAPHICSSCENE | [Qt for Python - QGraphicsScene](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QGraphicsScene.html) | final_UI_FN_reference; final_UI_FN_recheck | primary_document_or_artifact_review_in_finalization |
| QT_UNDOSTACK | [Qt for Python - QUndoStack](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QUndoStack.html) | final_UI_FN_reference; final_UI_FN_recheck | primary_document_or_artifact_review_in_finalization |
| VTK_PYTHON | [VTK - Python API](https://docs.vtk.org/en/latest/api/python.html) | final_UI_FN_reference; final_UI_FN_recheck | primary_document_or_artifact_review_in_finalization |
| F-SYS01 | [Qt for Python 공식 문서](https://doc.qt.io/qtforpython-6/) | final_system_review | primary_document_or_artifact_review_in_finalization |
| F-SYS02 | [CadQuery Introduction](https://cadquery.readthedocs.io/en/latest/intro.html) | final_system_review | primary_document_or_artifact_review_in_finalization |
| F-SYS03 | [JSON-RPC 2.0 Specification](https://www.jsonrpc.org/specification) | final_system_review | primary_document_or_artifact_review_in_finalization |
| F-SYS04 | [openEMS Python solver API](https://docs.openems.de/en/latest/python/openEMS/openEMS.html) | final_system_review | primary_document_or_artifact_review_in_finalization |
| F-SYS05 | [openEMS Ports API](https://docs.openems.de/en/latest/python/openEMS/ports.html) | final_system_review | primary_document_or_artifact_review_in_finalization |
| F-SYS06 | [openEMS Near-Field to Far-Field](https://docs.openems.de/en/latest/concepts/nf2ff.html) | final_system_review | primary_document_or_artifact_review_in_finalization |
| F-SYS07 | [KiCad 10 CLI](https://docs.kicad.org/10.0/en/cli/cli.html) | final_system_review | primary_document_or_artifact_review_in_finalization |
| F-SYS08 | [KiCad PCB S-expression File Format](https://dev-docs.kicad.org/en/file-formats/sexpr-pcb/) | final_system_review | primary_document_or_artifact_review_in_finalization |
| F-SYS09 | [Ucamco Gerber official portal](https://www.ucamco.com/en/gerber) | final_system_review | primary_document_or_artifact_review_in_finalization |
| F-SYS10 | [Open CASCADE STEP documentation](https://github.com/Open-Cascade-SAS/OCCT/wiki/step) | final_system_review | primary_document_or_artifact_review_in_finalization |
| F-SYS11 | [scikit-rf Network.renormalize](https://scikit-rf.readthedocs.io/en/latest/api/generated/skrf.network.Network.renormalize.html) | final_system_review | primary_document_or_artifact_review_in_finalization |
| F-SYS12 | [SciPy differential_evolution](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.differential_evolution.html) | final_system_review | primary_document_or_artifact_review_in_finalization |
| F-SYS13 | [pymoo NSGA-II](https://pymoo.org/algorithms/moo/nsga2.html) | final_system_review | primary_document_or_artifact_review_in_finalization |
| F-SYS14 | [IBIS Touchstone 2.1 Specification](https://ibis.org/touchstone_ver2.1/touchstone_ver2_1.pdf) | final_system_review | primary_document_or_artifact_review_in_finalization |
| F-SYS15 | [RFC 8785 JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785) | final_system_review | primary_document_or_artifact_review_in_finalization |

## 6. 다음 검토자가 남겨야 할 증거

공식 문서 확인은 URL, 버전, 확인일, 페이지, 적용 범위로 기록한다. 설치는 실제 package/binary 버전과 hash, 실행은 input/native/output artifact와 solver log, 수렴은 mesh/boundary/time 비교 데이터, 실측은 fixture, 교정, 환경, 불확도, raw 파일로 기록한다. source ID를 하나 더 붙이는 것만으로 verification state를 올리지 않는다.

문서 재검토 중 잘못된 식이나 오래된 API가 발견되면 원래 기록을 지우지 않고 [Codex 검토 지침](16_RFAD_구현_인계와_독립_검토.md)의 issue, decision change를 생성한다. 해당 요구, EQ, FN, VT의 영향 범위를 추적한 뒤 수정한다.

## GUI 재검토의 추가 근거

C++ wxWidgets의 채택 및 통합/성능 검증 계약은 [GUI 선정과 성능 설계](24_RFAD_GUI_선정과_성능_설계.md)에 기록한다. Avalonia/.NET와 기존 Qt source ID는 과거 기술 비교의 역사 자료로 보존하며 현재 채택 기술로 해석하지 않는다. Qt와 PySide6는 제외한다. GUI 기술, 일반 편집 60 fps/대형 장면 30 fps를 포함한 PERF-001~010/기준 host/fixture의 초기 목표 채택, 유료 GUI 부품 비필수 방침의 근거는 사용자 후속 지시다. 공식 자료의 기능 설명이나 과거 비교가 최소사양 보장이나 실측 합격을 증명하지는 않는다.

R1 Windows 11 x64 wxMSW/local WSL2 우선, Linux wxGTK GUI 후속 출시, 원호/IFA 단일포트 범위 및 내부 검증용 배포 우선도 사용자 결정으로 기록한다. Linux native/headless worker 기본 검증은 R0에서 유지하며 후속 Linux GUI의 출시 버전은 미정이다. 완전한 참조 계산 사례 이후 물성 완비 단일포트 IFA를 첫 제품 사례로 검증하고 R1 원호 검증도 수행한다. 최초 IFA 대역/보드 외형/적층 목표/급전은 3.3에서 [21번 IFA 초기 검증 기준](21_RFAD_사례와_계약.md#ifa-initial-baseline)로 채택했다. 실제 재료 물성과 상세 제작/측정 조건, 정확한 CPU/GPU 실행 manifest 및 외부 공개/상용/소스 공개 방침은 후속 확정한다. 이 선택의 근거를 외부 자료의 제품 성능 보증으로 바꾸지 않는다.

## 7. 3.0 문서 검토에서 직접 확인한 공식 근거

확인일은 2026-11-07 KST이다. 아래는 공개 문서의 내용을 읽은 결과이며 설치, 실행, 라이선스 적합 판정 또는 제품 수용시험 결과가 아니다. 버전 없는 latest 페이지는 움직일 수 있으므로 구현 착수 시 선택 버전 문서와 실제 binary를 고정한다.

| 문서 | 이번 확인 내용 | 문서 반영 및 남은 검증 |
| --- | --- | --- |
| [CadQuery Importing and Exporting Files](https://cadquery.readthedocs.io/en/latest/importexport.html) | STEP/DXF 교환과 fused assembly의 face 변경 및 비용 설명 | RFAD 12: 모든 body fusion을 기본으로 강제하지 않으며 원래 face index를 안정 ID로 쓰지 않음. 실제 writer profile은 미검증 |
| [OCCT STEP Translator](https://occt3d.com/dev/doc/overview/html/occt_user_guides__step.html) | AP203/AP214 및 AP242 일부 지원, write.step.schema 선택과 XDE 속성 범위 | RFAD 12/14: FILE_SCHEMA와 필수 속성 재입력 검수. AP242 전체 지원을 이름만으로 주장하지 않음 |
| [KiCad 10 CLI](https://docs.kicad.org/10.0/en/cli/cli.html) | copper 포함, 추가 pad 두께 제거, 비아 구멍 처리, mask/silkscreen flat face 옵션 | RFAD 12/14: flat face를 실제 두께 solid로 판정하지 않음. 실제 설치 버전과 출력 검수 필요 |
| [KiCad Board File Format](https://dev-docs.kicad.org/en/file-formats/sexpr-pcb/) | board version/generator, layer, track/via/arc, net 및 zone 구조 | RFAD 12: 지원 subset과 객체 의미 보존. 형식 페이지 존재만으로 무손실 왕복을 주장하지 않음 |
| [Gmsh OCC API](https://gmsh.info/doc/texinfo/gmsh.html#Namespace-gmsh_002fmodel_002focc) | OCC 경로가 OpenCASCADE 표현과 연산을 사용 | RFAD 12/14: 다른 프로그램과 다른 kernel의 독립성 구분 |
| [Ucamco Gerber 공식 포털](https://www.ucamco.com/en/gerber) | 공식 Layer/Job 형식 자료의 배포 위치 | 제조 profile은 채택한 개정 원문과 독립 reader로 별도 검수 |

## 8. 출처 상태를 승격할 때 필요한 기록

`catalogued`, `local_file_present`, `hash_checked`, `text_reviewed`, `applied_to_fixture`를 구분한다. URL이 열렸다는 사실, 로컬 파일 존재, 현재 bytes의 hash가 원래 hash와 같은지 여부는 서로 다른 검사다. HTML의 EOL 또는 공백 정규화 일치는 raw byte hash 일치와 별도로 보존하고 원문 hash를 바꾸지 않는다. 구현 결과의 검증 단계는 RFAD 14/20의 별도 상태를 따른다.

기록에는 source ID, 실제 URL/로컬 상대 경로, 확인 시각, 원문 개정, locator, 확인한 문장 또는 항목, 사용한 주장, 미확인 범위가 필요하다. 권리 상태가 미정인 원문은 기본 배포 대상에서 제외하며 사용자의 로컬 참조와 citation은 유지한다. 레코드 수나 hash 일치로 수식, 물성 또는 안테나 성능의 타당성을 대신 증명하지 않는다.

## 9. GUI 채택 및 과거 비교 검토의 추가 출처

아래 ID는 3.0 GUI 문서 검토에서 추가한 별도 색인이다. 5절의 이전 250개 ID 수에 섞지 않는다. 확인일은 2026-11-07 KST이며 3.1에서 C++ wxWidgets가 확정되었다. 현재 채택 근거와 한계는 [RFAD 24](24_RFAD_GUI_선정과_성능_설계.md)를 따른다. GUI-AVA-*와 GUI-DOTNET-AOT는 과거 비교 검토 자료이며 현재 제품의 채택이나 구현 의존성을 뜻하지 않는다. 공식 문서 확인은 prototype 실행이나 메모리/지연/frame 합격을 뜻하지 않는다. 기술 상태는 `selected_pending_validation`이다. 3.2의 성능 초기 목표 채택, 3.4 전체 문서 기준선 승인 완료, 실제 검증 미실행 및 개발 착수 전 상태를 구분한다.

| Source ID | 공식 자료 | 사용할 근거와 제한 |
| --- | --- | --- |
| GUI-WX-OVERVIEW | [wxWidgets 소개](https://wxwidgets.org/about/) | native control과 플랫폼 구성. 명칭만으로 낮은 메모리나 빠른 응답을 판정하지 않음 |
| GUI-WX-LICENSE | [wxWidgets 라이선스](https://wxwidgets.org/about/licence/) | 채택 버전과 배포 구성의 조건 검토. 실제 배포 승인은 별도 |
| GUI-AVA-ARCH | [Avalonia 플랫폼 아키텍처](https://docs.avaloniaui.net/docs/fundamentals/cross-platform-architecture) | 과거 비교 검토: 렌더링/플랫폼 계층. 현재 채택 기술 아님 |
| GUI-AVA-PERF | [Avalonia 성능 문제](https://docs.avaloniaui.net/troubleshooting/app-performance-issues) | 과거 비교 검토: virtualization, TreeDataGrid의 Avalonia Pro 조건. 현재 제품 의존성 아님 |
| GUI-AVA-AOT | [Avalonia Native AOT](https://docs.avaloniaui.net/docs/deployment/native-aot) | 과거 비교 검토: AOT 적용 제약과 빌드 경로. 실제 RFAD 성능 미측정, 현재 채택 기술 아님 |
| GUI-AVA-LICENSE | [Avalonia FAQ](https://avaloniaui.net/faq/) | 과거 비교 검토: MIT core와 상용 control/서비스 구분. 현재 배포 구성 아님 |
| GUI-DOTNET-AOT | [.NET Native AOT](https://learn.microsoft.com/en-us/dotnet/core/deploying/native-aot/) | 과거 비교 검토: runtime 배포와 JIT/AOT 제약. 현재 GUI runtime 의존성 아님 |
| GUI-WIN-MEMORY | [PROCESS_MEMORY_COUNTERS_EX](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters_ex) | working set과 private commit 측정 의미. GUI 단독 수치로 전체 프로세스 비용을 대신하지 않음 |

## 10. 최초 IFA 초기 검증 기준의 근거

확인일은 2026-11-07 KST이다. 아래는 사용자에게 추천하기 전 공식 자료의 해당 내용을 확인한 기록이며 제작/solver/실측 결과가 아니다. 별도 색인의 4개 ID는 과거 250개 출처 수에 합산하지 않는다.

| Source ID | 공식 자료와 확인 위치 | 사용할 근거와 제한 |
| --- | --- | --- |
| IFA-TI-DN007 | [TI SWRU120D, 2.4-GHz Inverted F Antenna](https://www.ti.com/lit/an/swru120d/swru120d.pdf), 1~2쪽 | 25.7 x 7.5 mm는 접지를 제외한 안테나 영역이고 측정 조건은 1 mm FR-4. 접지/재료/두께/주변 구조의 영향과 정합망 권고. 이번 40 x 60 mm 보드의 성능 보증이나 동일 재현본 근거가 아님 |
| IFA-TI-AN043 | [TI SWRA117D, Small Size 2.4 GHz PCB Antenna](https://www.ti.com/lit/an/swra117d/swra117d.pdf), 3쪽 및 5~6쪽 | 50 ohm/2.4 GHz 대역 정합 목표의 사례, 작은 보드에서 coax 배치 및 ground 영향. 원문의 MIFA와 이번 단순 IFA를 동일 형상으로 간주하지 않으며 원문 변동 수치를 허용오차로 복사하지 않음 |
| IFA-SILABS-AN1088 | [Silicon Labs AN1088](https://www.silabs.com/documents/public/application-notes/an1088-designing-with-pcb-antenna.pdf), 2~6쪽 | 원자료 4층 보드, feed/short/keepout/mask와 ground 조건. 14 mil 선폭은 0.008 inch 상부 유전체 조건이므로 이번 2층 보드에 자동 적용하지 않음 |
| IFA-KEYSIGHT-PLANE | [Keysight Removing Unwanted Effects from the Measurement](https://helpfiles.keysight.com/csg/N1930xB/ToolsAndUtilities/Removing_Unwanted_Effects_from_the_Measurement.html), Port Rotation/Extension 및 De-embedding | 기준면 이동과 fixture의 손실/위상/불일치 제거를 구분. 검증된 모델 또는 S-parameter가 필요하며 케이블 외부의 방사 결합까지 제거한 증거는 아님 |

2.400~2.4835 GHz, 폭 40 x 길이 60 mm, 안테나 영역 40 x 10 mm, 접지 외곽 40 x 50 mm, 2층 FR-4 완성 1.0 mm/각 동박 35 um, 50 ohm SMA와 초기 측정 계획은 사용자가 채택한 독자 검증 보드의 초기 기준이다. 공개 설계의 실측 결과를 승계하지 않는다. 물성은 사용자 입력/자료 선택 변수이며 실제 재료, 제조사와 상세 측정 조건은 미정이다. 상세 단일 기준은 [21번](21_RFAD_사례와_계약.md#ifa-initial-baseline), 결정 기록은 [25번](25_RFAD_문서_검토와_승인.md)을 따른다.
