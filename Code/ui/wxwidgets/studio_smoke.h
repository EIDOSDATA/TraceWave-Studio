/** @file @brief 실제 GUI 통합 시나리오는 제품 화면 상태와 별도로 보관한다. */
#pragma once
#include "studio_types.h"
#include <wx/event.h>
#include <wx/weakref.h>
#include <string>

class StudioFrame;
class PcbSelectionDialog;
class RadiationDialog;

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
    /** @brief 원형 보드와 기존 패턴 참조를 시험의 시작 상태로 만든다. */
    void PcbSmokePrepare();
    /** @brief 실제 대화상자 컨트롤에 이벤트를 보내고 비동기 결과를 관찰한다. */
    void PcbSmokeDialog(PcbSelectionDialog& dialog);
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
    std::string m_solverFirstResult;
    Json m_solverChecks = Json::array();
    int m_solverSmokeStage = 0;
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
