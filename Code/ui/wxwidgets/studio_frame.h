/** @file @brief 주 창은 화면 이벤트와 기능별 작업 객체를 연결한다. */
#pragma once

#include "studio_types.h"
#include "app_options.h"
#include "service_client.h"
#include <wx/frame.h>
#include <wx/timer.h>
#include <functional>
#include <map>
#include <memory>
#include <string>
#include <thread>
#include <vector>
#include "async_state.h"
#include "analysis_workflow.h"

class StudioSmokeDriver;
class PcbSelectionDialog;
class SolverChart;
class DesignCanvas;
class ModelView;
class EditorPanel;
class wxAuiManager;
class wxButton;
class wxCheckBox;
class wxChoice;
class wxStaticText;
class wxTextCtrl;
class wxNotebook;
class wxListBox;
class wxListCtrl;
class wxSpinCtrlDouble;
class wxTreeCtrl;
class wxPanel;
class wxThreadEvent;

/** @brief 표시와 이벤트 연결을 맡고 작업 진행은 독립 상태 객체에 위임하는 주 창이다. */
class StudioFrame final : public wxFrame
{
public:
    explicit StudioFrame(Options options);
    ~StudioFrame() override;

private:
    friend class StudioSmokeDriver;
    std::unique_ptr<StudioSmokeDriver> m_smoke;
    struct NumericField
    {
        std::string key;
        std::string label;
        double initial;
    };

    /** @brief 프로젝트 메타데이터와 선택 객체의 서비스 기반 입력 폼을 구성한다. */
    void BuildInterface();
    /** @brief 기존 입력을 적용한 뒤 PCB 자료 검색과 적층 검토 화면을 연다. */
    void OpenPcbSelection();
    /** @brief 응답 처리 타이머가 반환한 뒤 별도 이벤트에서 모달 화면을 표시한다. */
    void ShowPcbSelection(const Json& context);
    /** @brief 메뉴와 도구 버튼이 같은 명령 처리기를 사용하도록 연결한다. */
    void AddTool(wxWindow* parent, wxSizer* sizer, int id, const std::string& label);
    /** @brief 키보드만으로 좌표를 지정하며 유한 수치의 판정 후 서비스에 전달한다. */
    bool AskNumbers(const std::string& title, const std::vector<NumericField>& fields, Json& values);
    /** @brief 빈 줄로 구멍을 구분하는 정확한 수치 입력을 단일 생성 명령으로 보낸다. */
    void AddPolygon();
    /** @brief 원형/회전 사각 패드의 실제 치수를 명시하고 물성을 추정하지 않는다. */
    void AddPad(bool circle);
    /** @brief 비아의 층 범위와 제작 치수를 입력하며 비운 치수는 미정으로 보존한다. */
    void AddVia();
    /** @brief 캔버스 입력 이벤트를 서비스 명령과 도구 선택에 연결한다. */
    void BindCanvas();
    /** @brief 화면 초안을 도메인 명령 하나로 적용하고 권위 scene을 다시 읽는다. */
    void CanvasCommand(const std::string& operation, const Json& values, std::function<void()> completed = {});
    /** @brief 거절된 드래그의 강조를 속성 패널의 권위 선택으로 되돌린다. */
    void RestoreCanvas();
    /** @brief 선과 원호의 명시적 좌표 입력을 받는다. */
    void AddCoordinates();
    /** @brief 잘못된 선폭 입력에는 마지막 유효 표시값을 유지한다. */
    void UpdateStrokeWidth();
    /** @brief 명시적 해석 입력 검사를 실행하며 완료와 설계 합격을 구분한다. */
    void ValidateInput(std::function<void()> completed = {});
    /** @brief 입력 진단 목록과 개수를 화면에 표시한다. */
    void ShowProblems();
    /** @brief 진단이 가리키는 현재 개정의 객체와 필드로 이동한다. */
    void OpenProblem(long index);
    /** @brief 제한된 로그 길이를 유지하고 기존 입력 초점을 복원한다. */
    void Log(const std::string& text);
    /** @brief CAD는 별도 작업으로 추적하여 편집/저장 작업의 callback을 보존한다. */
    void BindCad();
    /** @brief 완료 상태와 입력 개정, 출력 위치를 사용자가 확인할 수 있게 유지한다. */
    void CadStatus(const std::string& state, const std::string& message);
    /** @brief 파일에 기록된 입력과 현재 편집 개정을 구분하며 이전 형상을 숨기지 않는다. */
    void UpdateModelState();
    /** @brief 적용 후 불변 스냅샷을 접수하고 native 작업 중에는 편집 잠금을 해제한다. */
    void StartCad(bool step);
    /** @brief 접수 실패를 기존 정상 출력과 분리하여 사용자에게 알린다. */
    void CadRejected(const Json& error);
    /** @brief 취소 요청과 실제 프로세스 종료를 구분하여 완료 상태를 기다린다. */
    void CancelCad();
    /** @brief 재열기 때 게시 완료된 동일 프로젝트의 마지막 결과만 복원한다. */
    void RestoreCad();
    /** @brief 작은 참조만 GUI로 받아 파일 읽기와 hash 검사를 3D loader에 맡긴다. */
    void AcceptCad(const Json& result, bool show);
    /** @brief CAD 상태는 제한된 주기로 읽고 일반 편집 응답과 별도로 처리한다. */
    void PollCad(Clock::time_point now);
    /** @brief 해석 작업 상태와 결과 그래프를 기존 설계 탭과 분리하여 구성한다. */
    void BuildSolverInterface();
    /** @brief 해석 실행과 취소 메뉴를 연결한다. */
    void BindSolver();
    /** @brief 해석 조건은 사용자가 확인한 입력이며 보드 물성을 대신 생성하지 않는다. */
    void ConfigureSolver();
    /** @brief 봉인된 결과의 방사 조회 화면을 독립적으로 연다. */
    void OpenRadiation();
    /** @brief 작업 상태와 로그를 해석 패널에 표시한다. */
    void SolverStatus(const std::string& state, const std::string& message);
    /** @brief 스냅샷부터 해석까지 별도 작업으로 추적하여 편집과 저장을 계속 허용한다. */
    void StartSolver();
    /** @brief 상태 머신이 만든 한 단계의 명령을 접수한다. */
    void SubmitSolverPhase(const Studio::ServiceCommand& command);
    /** @brief 해석 실패를 표시하고 기존 완료 결과는 유지한다. */
    void SolverRejected(const Json& error);
    /** @brief 취소 요청 뒤에는 다음 단계로 자동 진행하지 않는다. */
    void CancelSolver();
    /** @brief 해석 작업 상태를 조회하고 확인된 완료만 다음 단계로 전달한다. */
    void PollSolver(Clock::time_point now);
    /** @brief 완료된 단계의 결과를 상태 머신에 전달한다. */
    void SolverPhaseComplete(const Json& result);
    /** @brief 프로젝트에 결합된 완료 결과와 표본을 읽어 표시한다. */
    void AcceptSolver(const Json& result, bool show);
    /** @brief 저장된 마지막 완료 결과를 다시 읽는다. */
    void RestoreSolver();
    /** @brief 현재 개정과 이전 해석 결과를 구분해 표시한다. */
    void UpdateSolverView();
    /** @brief 현재 표시 상태에서 실행 가능한 명령을 갱신한다. */
    void UpdateControls();
    /** @brief 미적용 입력과 적용 후 저장 필요 상태를 서비스 개정 정보로 구분한다. */
    void UpdateDraftState();
    /** @brief 적용 전 입력이 선택 변경이나 종료로 조용히 사라지지 않도록 한다. */
    bool HasDraft() const;
    /** @brief 적용 전 입력을 버리는 사용자 선택을 받는다. */
    bool ConfirmDiscard();
    /** @brief 일반 오류와 연결 단절의 상태를 구분해 표시한다. */
    void Failure(const std::string& message, bool disconnected = false);
    /** @brief 별도 서비스 프로세스와 공개 capability 계약으로 연결한다. */
    void Connect();
    /** @brief 요청 관리 객체를 통해 명령을 전달한다. */
    void Send(const std::string& method, const Json& input, bool mutation, const Json& context,
              std::function<void(const Json&)> success, std::function<void(const Json&)> failure = {});
    /** @brief 현재 프로젝트의 요청 문맥을 만든다. */
    Json Context() const;
    /** @brief 일반 작업의 완료 콜백과 조회 대상을 등록한다. */
    void WaitJob(const Json& task, std::function<void(const Json&)> completed);
    /** @brief 작업 중 프로젝트 전환을 차단하고 요청한 프로젝트를 연다. */
    void OpenProject(const std::string& mode, const std::string& path, const std::string& name = "");
    /** @brief 전체 원본 대신 목록과 선택 객체의 작은 편집 DTO만 조회한다. */
    void RefreshEditor(const Json& selection, std::function<void()> completed);
    /** @brief 같은 revision의 표시 DTO는 재사용하고 변경된 표시 데이터만 다시 읽는다. */
    void RefreshScene(std::function<void()> completed);
    /** @brief 비동기 조회 중 비활성화한 트리의 키보드 초점을 완료 후 복원한다. */
    void SelectObject(const Json& selection, bool restoreTreeFocus = false);
    /** @brief 작은 편집 DTO로 탐색 트리와 속성 폼을 갱신한다. */
    void RefreshProject();
    /** @brief 폼 변경분을 한 서비스 명령으로 적용하고 권위 DTO로 다시 표시한다. */
    void ApplyCurrent(std::function<void()> completed, std::function<void(const Json&)> rejected = {});
    /** @brief 선택한 객체의 변경된 속성을 적용한다. */
    void ApplyProperties();
    /** @brief undo/redo의 원본과 이력은 서비스가 소유하며 GUI에는 결과 개정만 반영한다. */
    void History(const std::string& method, std::function<void()> completed = {});
    /** @brief 미적용 입력을 적용한 뒤 현재 개정을 저장한다. */
    void SaveProject();
    /** @brief 현재 적용 개정의 불변 스냅샷을 요청한다. */
    void Snapshot();
    /** @brief 일반 작업 완료 후 편집 가능 상태를 복원한다. */
    void Ready(const std::string& message);
    /** @brief 비동기 응답과 작업 진행을 제한된 주기로 처리한다. */
    void OnTimer(wxTimerEvent&);
    /** @brief 취소와 프로세스 회수를 요청한 뒤 창을 닫는다. */
    void OnClose(wxCloseEvent& event);
    /** @brief 화면 수명을 유지한 채 서비스 종료와 pipe join을 UI 밖에서 수행한다. */
    void BeginShutdown();
    /** @brief 종료 thread가 pipe를 모두 회수한 뒤 창을 파괴하거나 smoke 연결을 재개한다. */
    void OnShutdown(wxThreadEvent&);

    Studio::RequestDispatcher m_requests;
    Studio::JobTracker m_foregroundTask;
    Studio::JobTracker m_cadTask;
    Studio::JobTracker m_solverTask;
    Studio::AnalysisWorkflow m_solverWorkflow;
    Options m_options;
    PcbSelectionDialog* m_pcbDialog = nullptr;
    bool m_closeAfterPcb = false;
    bool m_forceCloseAfterPcb = false;
    bool m_pcbSelectionSupported = false;
    SolverChart* m_solverChart = nullptr;
    wxChoice* m_solverMetric = nullptr;
    wxStaticText* m_solverStatus = nullptr;
    wxStaticText* m_solverViewState = nullptr;
    wxTextCtrl* m_solverDetails = nullptr;
    bool m_solverConfigured = false;
    bool m_solverRestoring = false;
    std::string m_solverState = "idle";
    Json m_solverDraft = Json::object();
    wxCheckBox* m_recordRadiation = nullptr;
    Json m_radiationDraft = Json::object();
    Json m_solverSettings = Json::object();
    Json m_solverResult = Json::object();
    Json m_solverSamples = Json::object();
    wxAuiManager* m_manager = nullptr;
    wxString m_defaultLayout;
    std::map<int, wxButton*> m_tools;
    DesignCanvas* m_canvas = nullptr;
    wxNotebook* m_views = nullptr;
    ModelView* m_modelView = nullptr;
    wxStaticText* m_modelState = nullptr;
    wxStaticText* m_modelHint = nullptr;
    wxStaticText* m_cadStatus = nullptr;
    wxTextCtrl* m_cadDetails = nullptr;
    bool m_cadConfigured = false;
    bool m_cadPreparing = false;
    bool m_cadRestoring = false;
    bool m_cadCancelRequested = false;
    bool m_modelWasLoading = false;
    std::string m_cadState = "idle";
    Json m_cadSnapshot = Json::object();
    Json m_cadResult = Json::object();
    Json m_displayResult = Json::object();
    wxListBox* m_steps = nullptr;
    wxChoice* m_layerChoice = nullptr;
    wxSpinCtrlDouble* m_width = nullptr;
    wxStaticText* m_canvasHint = nullptr;
    wxStaticText* m_problemSummary = nullptr;
    wxNotebook* m_bottom = nullptr;
    wxListCtrl* m_problems = nullptr;
    std::vector<std::string> m_layerIds;
    std::string m_activeLayer;
    std::string m_drawTool = "select";
    std::string m_problemRevision;
    Json m_scene = Json::object();
    Json m_diagnostics = Json::array();
    std::size_t m_diagnosticCount = 0;
    bool m_diagnosticsTruncated = false;
    Json m_lineDraft = Json::object();
    Json m_arcDraft = Json::object();
    std::string m_polygonDraft;
    ServiceClient m_client;
    std::thread m_shutdown;
    wxTimer m_timer;
    wxTreeCtrl* m_tree = nullptr;
    wxPanel* m_properties = nullptr;
    wxPanel* m_metadataPanel = nullptr;
    EditorPanel* m_editorPanel = nullptr;
    wxStaticText* m_selectionLabel = nullptr;
    wxTextCtrl* m_name = nullptr;
    wxTextCtrl* m_description = nullptr;
    wxTextCtrl* m_log = nullptr;
    wxButton* m_apply = nullptr;
    wxStaticText* m_revisionLabel = nullptr;
    bool m_connected = false;
    bool m_busy = true;
    bool m_transportFailed = false;
    bool m_finishing = false;
    bool m_restarting = false;
    bool m_closing = false;
    bool m_waitingClose = false;
    Clock::time_point m_closeDeadline{};
    bool m_refreshing = false;
    bool m_updatingDraft = false;
    Clock::time_point m_started;
    std::function<void(const Json&)> m_jobComplete;
    Json m_editor = Json::object();
    Json m_selection = Json::object();
    std::string m_editState = "empty";
    std::string m_epoch;
    std::string m_project;
    std::string m_revision;
    std::string m_path;
    std::string m_savedRevision;
    std::string m_snapshot;
};
