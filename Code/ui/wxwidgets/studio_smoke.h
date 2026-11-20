/** @file @brief 실제 GUI 통합 시나리오는 제품 화면 상태와 별도로 보관한다. */
#pragma once
#include "studio_types.h"
#include <wx/event.h>
#include <wx/weakref.h>
#include <string>
#include <functional>
#include <memory>

class StudioFrame;
class PcbSelectionDialog;
class StudioCatalogDisplayProbe;
class RadiationDialog;
class TargetEditorDialog;
class TemplateDialog;

/** @brief 명시적 smoke 옵션에서만 실제 화면과 서비스를 구동하는 통합 시험 운전자다. */
class StudioSmokeDriver final
{
public:
    /** @brief 주 창보다 짧은 수명으로 시험 상태를 소유한다. */
    explicit StudioSmokeDriver(StudioFrame& frame) : m_frame(frame) {}

    /** @brief 실제 화면 이벤트와 결과를 검증한다. */
    void CadSmokeTick();
    /** @brief 실제 화면 이벤트와 결과를 검증한다. */
    void SolverSmokeTick();
    /** @brief 같은 취소 요청에 연결한 화면·접수·종료 시각을 통합 시험에 남긴다. */
    void RecordSolverCancellation(const std::string& job, const char* milestone, Json details);
    /** @brief WSL 조정기가 실제 guest worker를 관찰한 작업 ID를 기록한다. */
    void ObserveSolverGuest(const std::string& job);
    /** @brief 일반 프로젝트 연구의 실제 화면/취소/재개/재연결을 확인한다. */
    void StudySmokeTick();
    /** @brief 목표 CRUD와 명시 카드 미리보기/적용을 실제 화면에서 확인한다. */
    void SetupSmokeTick();
    /** @brief 실제 화면 이벤트와 결과를 검증한다. */
    void EditorSmokeNext();
    /** @brief 실제 화면 이벤트와 결과를 검증한다. */
    void CheckEditorValue(double expected) const;
    /** @brief 실제 화면 이벤트와 결과를 검증한다. */
    void CheckUxState(const std::string& expected, bool applyEnabled) const;
    /** @brief 실제 화면 이벤트와 결과를 검증한다. */
    void CanvasMouse(wxEventType type, double x, double y, bool left = false, bool middle = false);
    /** @brief 실제 화면 이벤트와 결과를 검증한다. */
    void CanvasClick(double x, double y);
    /** @brief 실제 화면 이벤트와 결과를 검증한다. */
    Json CanvasShape(const std::string& id) const;
    /** @brief 실제 화면 이벤트와 결과를 검증한다. */
    void CanvasAssert(bool condition, const std::string& message) const;
    /** @brief 실제 화면 이벤트와 결과를 검증한다. */
    void PrimitivesSmokeTick();
    /** @brief 실제 PCB 대화상자와 서비스의 선택, 검토, 적용 및 이력을 검증한다. */
    void PcbSmokeTick();
    /** @brief 부모 종료 요청 뒤 모달 반환과 서비스 회수 완료를 확인하고 보고한다. */
    void OnPcbShutdownComplete();
    /** @brief 실제 화면 이벤트와 결과를 검증한다. */
    void CanvasSmokeNext();
    /** @brief 실제 화면 이벤트와 결과를 검증한다. */
    void FinishSmoke(bool passed, const std::string& error);

    /** @brief 제품 이벤트 이후 필요한 시험 단계만 진행한다. */
    void OnConnected();
    /** @brief 제품 이벤트 이후 필요한 시험 단계만 진행한다. */
    void OnOpened();
    /** @brief 제품 이벤트 이후 필요한 시험 단계만 진행한다. */
    void OnSaved();
    /** @brief 제품 이벤트 이후 필요한 시험 단계만 진행한다. */
    void OnSnapshotCreated();
    /** @brief 제품 이벤트 이후 필요한 시험 단계만 진행한다. */
    void OnApplied();
    /** @brief 제품 이벤트 이후 필요한 시험 단계만 진행한다. */
    void OnSelected();

private:
    /** @brief 실제 PCB 특징 입력과 원문/소유/영수증 보존을 검사한다. */
    void FeaturesSmokeTick();
    void PcbExchangeSmokeTick();
    void PcbExchangeSafetyChecks();
    Json m_pcbExchangeFixture = Json::object(), m_pcbExchangeBefore = nullptr, m_pcbExchangeResult = nullptr;
    std::string m_pcbExchangeRevision, m_pcbExchangeUploadId, m_pcbExchangeBuildId;
    void FeaturesSafetyChecks();
    Json m_featuresFixture = Json::object();
    std::string m_featuresHoleId, m_featuresFootprintId, m_featuresOriginalRevision;
    /** @brief 실제 출력 입력, 검토, 생성 및 새 읽기 검수의 원문 보존을 검사한다. */
    void OutputSmokeTick();
    void OutputSafetyChecks();
    Json m_outputFixture = Json::object();
    Json m_outputBuilt = nullptr;
    std::string m_outputRevision, m_outputBuildId, m_outputVerifyId;
    /** @brief 선택한 후보의 검토/새 사본/원본 보존과 영수증 복구를 확인한다. */
    void SelectionSmokeTick();
    void SelectionSafetyChecks();
    Json m_selectionFixture = Json::object();
    Json m_selectionBefore = Json::object();
    Json m_selectionResult = Json::object();
    std::string m_selectionOriginalProject;
    /** @brief 검증 보고서 선택과 미정값의 읽기 전용 보존을 실제 창에서 확인한다. */
    void ValidationSmokeTick();
    void ValidationSafetyChecks();
    Json m_validationFixture = Json::object();
    std::string m_validationRevision;
    /** @brief 과거 원본/Smith/복수 결과의 실제 표시와 읽기 수명을 검증한다. */
    void ResultsSmokeTick();
    void ResultWorkspaceSafetyChecks();
    Json m_resultsFixture = Json::object();
    Json m_resultsFirst = Json::object();
    Json m_resultsSecond = Json::object();
    std::string m_resultsRevision;
    bool m_resultsAwaiting = false;
    /** @brief 유한 연구 생성과 실제 회로 실행/취소/재개/재열기를 검증한다. */
    void SweepSmokeTick();
    void OpenSweepSmokeDialog();
    void SweepSmokeRequest(const std::string& method, const Json& input, bool mutation,
                           std::function<void(const Json&)> completed);
    Json m_sweepContext = Json::object();
    Json m_sweepView = Json::object();
    std::string m_sweepGridId;
    std::string m_sweepCircuitId;
    bool m_sweepAwaiting = false;
    /** @brief 공통 복소 자료의 실제 창/원자 이력/저장 재시작을 검증한다. */
    void NetworkSmokeTick();
    void OpenNetworkSmokeDialog(int kind);
    void NetworkImportSafetyChecks(const Json& context);
    Json m_networkContext = Json::object();
    std::string m_networkImportedId;
    std::string m_networkDerivedId;
    std::string m_networkCircuitId;
    std::string m_networkAssessmentId;
    bool m_networkAwaiting = false;
    /** @brief 추가 문헌/초기식과 표시 전용 작업 영역을 실제 서비스로 확인한다. */
    void PrintedSeedSmokeTick();
    void CanvasPrecisionSmokeNext();
    void CanvasSmokeSave();
    void DesignRulesSmokeTick();
    void PhysicalSetupSmokeTick();
    /** @brief 이름 오류 복구와 검토 무효화, 원자 편집 및 서비스 재시작을 실제 폼으로 검사한다. */
    void PrecisionEditorSmokeTick();
    void PrecisionPlanarSmokeTick();
    std::string m_precisionId;
    Json m_precisionBeforeShapes;
    Json m_precisionDimensionShapes;
    Json m_precisionAppliedShapes;
    int m_precisionUndoBefore = 0;
    void PrintedSeedDialog(TemplateDialog& dialog);
    int m_printedCase = 0;
    /** @brief 실제 목표 입력/선택/적용 이벤트와 출처 보존을 검사한다. */
    void SetupTargetSmoke(TargetEditorDialog& dialog);
    /** @brief 원호/IFA 카드 입력과 미리보기 변경 폐기를 검사한다. */
    void SetupTemplateSmoke(TemplateDialog& dialog);
    /** @brief 응답 역전/종료 이후 응답/결과 불명의 잠금을 검사한다. */
    void SetupSafetyChecks(const Json& context);
    int m_setupStage = 0;
    bool m_setupLargeChecked = false;
    int m_setupPendingTicks = 0;
    Clock::time_point m_setupStarted{};
    Json m_setupChecks = Json::array();
    Json m_setupSamples = Json::array();
    Json m_setupShapes = Json::array();
    std::string m_setupLayer;
    std::string m_setupSeedTarget;
    std::string m_setupAddedTarget;
    std::string m_setupExpectedRevision;
    /** @brief 원형 보드와 기존 패턴 참조를 시험의 시작 상태로 만든다. */
    void PcbSmokePrepare();
    /** @brief 실제 대화상자 컨트롤에 이벤트를 보내고 비동기 결과를 관찰한다. */
    void PcbSmokeDialog(PcbSelectionDialog& dialog);
    void PcbSmokeLargeCatalog(PcbSelectionDialog& dialog);
    /** @brief 실제 재료 폼에서 물성별 출처와 직접 입력 이유를 독립적으로 지정한다. */
    void PcbSmokeMaterial(PcbSelectionDialog& dialog);
    /** @brief 닫힌 대화상자의 적용 결과, 이력과 저장 후 재열기를 검증한다. */
    void PcbSmokeHistory();
    StudioFrame& m_frame;
    int m_pcbStage = 0;
    int m_pcbTicks = 0;
    int m_pcbRequestTicks = 0;
    int m_pcbUndoBefore = 0;
    Clock::time_point m_pcbStarted{};
    std::string m_pcbLayer;
    std::string m_pcbPattern;
    std::string m_pcbExistingLabel;
    std::string m_pcbBeforeRevision;
    Json m_pcbOriginalBoard;
    Json m_pcbOriginalPattern;
    Json m_pcbOriginalLayers;
    Json m_pcbAppliedLayers;
    Json m_pcbExpectedMaterial;
    Json m_pcbChecks = Json::array();
    Json m_pcbCatalogMetrics = Json::object();
    std::shared_ptr<StudioCatalogDisplayProbe> m_pcbCatalogDisplay;
    Clock::time_point m_pcbCatalogAction{};
    std::string m_solverFirstResult;
    Json m_solverChecks = Json::array();
    Clock::time_point m_solverCancelStarted{};
    std::string m_solverGuestJob;
    Json m_solverCancelTrace = Json::object();
    int m_solverSmokeStage = 0;
    int m_studyStage = 0;
    Json m_studyChecks = Json::array();
    Json m_studyView = Json::object();
    wxWeakRef<RadiationDialog> m_radiationDialog;
    bool m_radiationChecked = false;
    bool m_cadErrorProbeSeen = false;
    int m_cadSmokeStage = 0;
    std::string m_cadFirstSnapshot;
    Json m_cadChecks = Json::array();
    int m_primitivesStage = 0;
    std::string m_primitivesLayerA;
    std::string m_primitivesLayerB;
    std::string m_primitivesPolygon;
    std::string m_primitivesRectangle;
    std::string m_primitivesVia;
    std::string m_primitivesMissingVia;
    Json m_primitivesPads = Json::array();
    Json m_primitivesOriginalPolygon;
    Json m_primitivesMovedPolygon;
    Json m_primitivesSavedShapes;
    Json m_primitivesChecks = Json::array();
    int m_canvasStage = 0;
    int m_canvasUndoBefore = 0;
    bool m_canvasAwaitSelection = false;
    std::string m_canvasLine;
    std::string m_canvasArc;
    Json m_canvasOriginalLine;
    Json m_canvasMovedLine;
    Json m_canvasSavedShapes;
    std::string m_canvasSnappedLine;
    Json m_canvasBeforeEndpoint;
    Json m_canvasAfterEndpoint;
    Json m_canvasChecks = Json::array();
    int m_smokeStage = 0;
    int m_editorStage = 0;
    int m_serviceSessions = 0;
    Json m_editorChecks = Json::array();
    Json m_uxChecks = Json::array();
    std::string m_baseParameter;
    std::string m_dependentParameter;
    std::string m_failureRevision;
    std::string m_smokePath;
};
