/** @file @brief 실제 GUI 통합 시나리오는 제품 화면 상태와 별도로 보관한다. */
#pragma once
#include "studio_types.h"
#include <wx/event.h>
#include <string>

class StudioFrame;

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
    StudioFrame& m_frame;
    std::string m_solverFirstResult;
    Json m_solverChecks = Json::array();
    int m_solverSmokeStage = 0;
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
