/** @file @brief 실제 검증 화면의 명시 판정 선택과 미실행/미정 원문 보존을 검사한다. */
#include "studio_internal.h"
#include "rf_validation_controller.h"
#include "rf_validation_view.h"
#include "result_workspace.h"
#include "result_source_browser.h"
#include "studio_notebook.h"
#include "setup_smoke_support.h"
#include <wx/stattext.h>
#include <fstream>

void StudioSmokeDriver::ValidationSafetyChecks()
{
    auto host = std::make_unique<wxDialog>(&m_frame, wxID_ANY, Display("검증 기록 수명 시험"));
    auto* views = new StudioNotebook(host.get());
    auto* navigation = new wxPanel(host.get());
    auto* conditions = new wxPanel(host.get());
    navigation->SetSizer(new wxBoxSizer(wxVERTICAL));
    conditions->SetSizer(new wxBoxSizer(wxVERTICAL));
    struct Pending
    {
        std::string method;
        Json input;
        std::function<void(const Json&)> success;
    };
    std::vector<Pending> calls;
    DialogGateway gateway = [&calls, this](const std::string& method, const Json& input, bool mutation,
                                           std::function<void(const Json&)> success, std::function<void(const Json&)>)
    {
        CanvasAssert(!mutation, "검증 기록 화면이 조회 대신 변경 명령을 전송했습니다.");
        calls.push_back({method, input, std::move(success)});
    };
    auto controller = std::make_unique<RfValidationController>(views, navigation, conditions, gateway);
    const auto project = m_validationFixture.at("project_id").get<std::string>();
    controller->Update(project, "validation-smoke-epoch", true, true, true, 0);
    const auto identity = m_validationFixture.at("validation_id").get<std::string>();
    controller->Select(identity, m_validationFixture.at("first").at("report_id"));
    CanvasAssert(calls.size() == 1 && calls.front().method == "rf.validation.reports",
                 "판정 조회 대기열이 직렬 순서를 유지하지 못했습니다.");
    const auto reportsLoaded = calls.front().success;
    reportsLoaded(m_validationFixture.at("reports"));
    CanvasAssert(calls.size() == 2 && calls.back().method == "rf.validation.get",
                 "명시 선택한 판정을 조회하지 않았습니다.");
    const auto old = calls.back().success;
    controller->Select(identity, m_validationFixture.at("second").at("report_id"));
    old(m_validationFixture.at("first"));
    CanvasAssert(controller->m_view->m_record.is_null() && calls.size() == 3,
                 "늦은 이전 판정이 새 선택을 덮어썼습니다.");
    const auto selectedLoaded = calls.back().success;
    selectedLoaded(m_validationFixture.at("second"));
    CanvasAssert(controller->m_view->m_record == m_validationFixture.at("second"),
                 "현재 선택한 불변 보고서가 표시되지 않았습니다.");
    controller->Select(identity, m_validationFixture.at("first").at("report_id"));
    const auto late = calls.back().success;
    controller->Reset();
    late(m_validationFixture.at("first"));
    CanvasAssert(controller->m_view->m_record.is_null(), "초기화 뒤 이전 프로젝트의 판정이 표시됐습니다.");
    controller->Select(identity, m_validationFixture.at("first").at("report_id"));
    const auto disconnected = calls.back().success;
    controller->Update(project, "validation-smoke-epoch", false, true, false, 15);
    CanvasAssert(!controller->m_inflight && controller->m_queue.empty() && controller->m_view->m_record.is_null(),
                 "서비스 연결이 끊어진 뒤 이전 조회나 보고서가 남았습니다.");
    const auto previousCount = calls.size();
    controller->Update(project, "validation-smoke-epoch", true, true, true, 15);
    CanvasAssert(calls.size() == previousCount + 1 && calls.back().method == "rf.validation.list",
                 "같은 프로젝트/epoch 재연결에서 새 검증 목록을 조회하지 못했습니다.");
    disconnected(m_validationFixture.at("reports"));
    CanvasAssert(controller->m_view->m_record.is_null() && controller->m_inflight,
                 "연결 이전 콜백이 새 연결의 조회 수명을 바꿨습니다.");
    const auto catalogLoaded = calls.back().success;
    catalogLoaded(m_validationFixture.at("catalog"));
    CanvasAssert(controller->m_view->m_catalog == m_validationFixture.at("catalog") && !controller->m_inflight,
                 "재연결 뒤 실제 검증 목록 응답을 반영하지 못했습니다.");
    controller.reset();
    late(m_validationFixture.at("first"));
    disconnected(m_validationFixture.at("reports"));
    m_setupChecks.push_back("validation_late_selection_reset_destroy_safe");

    /** @brief 아래 descriptor와 목록은 화면 연결만 시험하는 합성이며 RF 계산값을 만들지 않는다. */
    calls.clear();
    auto results = std::make_unique<ResultWorkspace>(views, navigation, conditions, gateway);
    results->m_available = true;
    const Json source = {{"kind", "solver"}, {"artifact_id", "00000000-0000-0000-0000-000000000001"}};
    const Json pin = {{"identity_hash", std::string(64, 'a')}, {"dataset_sha256", std::string(64, 'b')}};
    const Json description = {
        {"profile", "rfad.result-view/0.1"},
        {"source", source},
        {"pin", pin},
        {"label", "화면 연결 전용 합성 원본 / 실제 RF 결과 아님"},
        {"is_current_design", false},
        {"descriptor",
         {{"parameter_kind", "S"},
          {"port_ids", Json::array()},
          {"conditions", {{"manufacturing", nullptr}, {"measurement", nullptr}}}}},
        {"states",
         {{"computation", "not_evaluated"}, {"numerical", "not_established"}, {"physics", "not_established"}}},
        {"source_refs", Json::array({"화면 목록/고정 해시 연결 시험 전용"})}};
    Json firstItems = Json::array();
    for (int index = 0; index < 25; ++index)
    {
        firstItems.push_back({{"label", "화면 연결 전용 다른 원본 " + std::to_string(index + 1)},
                              {"source",
                               {{"kind", "solver"},
                                {"artifact_id", "00000000-0000-0000-0000-" + std::to_string(100000000000LL + index)}}},
                              {"result_state", "not_evaluated"}});
    }
    const auto catalogHash = std::string(64, 'c');
    const Json firstPage = {
        {"items", firstItems}, {"offset", 0}, {"total", 26}, {"next_offset", 25}, {"catalog_hash", catalogHash}};
    const Json lastPage = {
        {"items",
         Json::array({{{"label", description.at("label")}, {"source", source}, {"result_state", "not_evaluated"}}})},
        {"offset", 25},
        {"total", 26},
        {"next_offset", nullptr},
        {"catalog_hash", catalogHash}};
    results->OpenPinned(source, pin);
    CanvasAssert(results->m_browser->Kind() == "solver" && calls.size() == 1 &&
                     calls.back().method == "result.describe" && calls.back().input.at("source") == source,
                 "보고서의 직접 열기가 해석 종류와 정확한 원본으로 전환되지 않았습니다.");
    const auto described = calls.back().success;
    described(description);
    CanvasAssert(calls.size() == 2 && calls.back().method == "result.sources" &&
                     calls.back().input.at("kind") == "solver" && calls.back().input.at("offset") == 0 &&
                     calls.back().input.at("limit") == 25,
                 "봉인 원본의 실제 해석 목록 첫 페이지를 조회하지 않았습니다.");
    const auto firstListed = calls.back().success;
    firstListed(firstPage);
    CanvasAssert(calls.size() == 3 && calls.back().input.at("offset") == 25 &&
                     calls.back().input.at("catalog_hash") == catalogHash &&
                     results->m_browser->SelectedSource().is_null(),
                 "찾지 못한 원본을 다른 행으로 대신하거나 다음 페이지의 해시를 잃었습니다.");
    const auto lastListed = calls.back().success;
    lastListed(lastPage);
    CanvasAssert(results->m_browser->SelectedSource() == source && results->m_catalog == lastPage &&
                     results->m_description == description &&
                     results->m_browser->m_items->GetSelectedItemCount() == 1 &&
                     results->m_browser->m_items->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_FOCUSED) == 0,
                 "직접 연 원본과 실제 목록의 선택/포커스 또는 고정 해시가 다릅니다.");
    results->OpenPinned(source, pin);
    const auto mismatch = calls.back().success;
    Json changed = description;
    changed["pin"]["dataset_sha256"] = std::string(64, 'd');
    const auto beforeMismatch = calls.size();
    mismatch(changed);
    CanvasAssert(results->m_description.is_null(), "봉인 해시가 다른 결과 상세를 채택했습니다.");
    CanvasAssert(results->m_browser->SelectedSource().is_null(), "봉인 해시가 다른 원본을 선택했습니다.");
    CanvasAssert(calls.size() == beforeMismatch, "봉인 해시가 다른 원본의 목록을 요청했습니다.");
    CanvasAssert(results->m_browser->m_statusText.Contains(Display("봉인 해시")) &&
                     !results->m_browser->m_status->GetLabel().IsEmpty(),
                 "봉인 해시 불일치 안내를 표시하지 않았습니다.");
    results->OpenPinned(source, pin);
    const auto describedAgain = calls.back().success;
    describedAgain(description);
    const auto staleList = calls.back().success;
    SetupSmoke::Choose(results->m_browser->m_kind, 0);
    staleList(firstPage);
    CanvasAssert(results->m_browser->Kind() == "network" && results->m_catalog.is_null() &&
                     results->m_browser->SelectedSource().is_null() && calls.back().method == "result.revisions",
                 "목록 종류가 바뀐 뒤 이전 해석 목록을 표시하거나 자동 선택했습니다.");
    results.reset();
    staleList(firstPage);
    m_setupChecks.push_back("validation_pinned_source_catalog_and_hash");
}

void StudioSmokeDriver::ValidationSmokeTick()
{
    if (m_frame.m_busy || !m_frame.m_validation)
    {
        return;
    }
    auto& controller = *m_frame.m_validation;
    auto* view = controller.m_view;
    const auto idle = [&controller]()
    {
        return !controller.m_inflight && controller.m_queue.empty();
    };
    const auto chooseReport = [this, view](const Json& report)
    {
        for (std::size_t index = 0; index < view->m_reportIds.size(); ++index)
        {
            if (view->m_reportIds.at(index) == report)
            {
                SetupSmoke::Choose(view->m_reportChoice, static_cast<int>(index));
                return;
            }
        }
        CanvasAssert(false, "보존 판정 선택지에서 요청한 보고서 ID를 찾지 못했습니다.");
    };
    if (m_setupStage == 1)
    {
        std::ifstream stream(std::filesystem::path(m_frame.m_options.workspace.ToStdWstring()) /
                                 "validation-smoke-fixture.json",
                             std::ios::binary);
        stream >> m_validationFixture;
        m_validationRevision = m_frame.m_revision;
        m_setupShapes = m_frame.m_selection;
        CanvasAssert(m_validationRevision == m_validationFixture.at("revision_id"),
                     "검증 화면 시험의 저장 개정이 다릅니다.");
        ValidationSafetyChecks();
        m_setupStage = 2;
        m_frame.OpenValidationRecords();
        m_frame.UpdateValidationViews();
    }
    else if (m_setupStage == 2 && idle() && view->m_catalog.is_object())
    {
        CanvasAssert(view->m_records->GetItemCount() == 1 &&
                         view->m_records->GetItemText(0).Contains(Display("명시 판정 선택")) &&
                         view->m_catalog.at("items").at(0).at("validation_id") ==
                             m_validationFixture.at("validation_id"),
                     "검증 목록이 현재 프로젝트의 사람이 읽는 이름과 연결되지 않았습니다.");
        m_setupStage = 3;
        view->m_records->SetItemState(0, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED,
                                      wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
    }
    else if (m_setupStage == 3 && idle() && view->m_record.is_object())
    {
        CanvasAssert(view->m_record == m_validationFixture.at("second") && view->m_reportIds.size() == 3 &&
                         view->m_reportIds.at(0).is_null() && view->m_reportIds.at(1) != view->m_reportIds.at(2),
                     "계획 선택과 두 개의 불변 보고서를 별도로 표시하지 못했습니다.");
        m_setupChecks.push_back("validation_named_catalog_and_explicit_report");
        m_setupStage = 4;
        chooseReport(nullptr);
    }
    else if (m_setupStage == 4 && idle() && view->m_record.is_object())
    {
        CanvasAssert(view->m_record.at("report_id").is_null() && view->m_record.at("assessment_hash").is_null() &&
                         view->m_record.at("rows").empty() && view->m_metrics->GetItemCount() == 0 &&
                         view->m_identity->GetLabel().Contains(Display("계획과 현재 작업")),
                     "계획 조회가 최신 판정이나 계산 결과로 암묵 대체됐습니다.");
        m_setupChecks.push_back("validation_plan_never_substitutes_report");
        m_setupStage = 5;
        chooseReport(m_validationFixture.at("first").at("report_id"));
    }
    else if (m_setupStage == 5 && idle() && view->m_record.is_object())
    {
        CanvasAssert(view->m_record == m_validationFixture.at("first"),
                     "명시 선택한 과거 보고서의 원문 또는 해시가 달라졌습니다.");
        m_setupChecks.push_back("validation_original_report_hash");
        m_setupStage = 6;
        chooseReport(m_validationFixture.at("second").at("report_id"));
        chooseReport(m_validationFixture.at("first").at("report_id"));
    }
    else if (m_setupStage == 6 && idle() && view->m_record.is_object())
    {
        CanvasAssert(view->m_record == m_validationFixture.at("first") && view->m_cases->GetItemCount() == 9 &&
                         view->m_states->GetItemCount() == 6 && view->m_metrics->GetItemCount() == 9,
                     "빠른 보고서 전환 뒤 이전 결과가 남거나 미평가 행이 사라졌습니다.");
        int blocked = 0;
        for (const auto& item : view->m_record.at("cases"))
        {
            blocked += item.at("blocked_reason").is_null() ? 0 : 1;
            CanvasAssert(item.at("source").is_null() && item.at("pin").is_null(),
                         "실행하지 않은 사례에 해석 결과를 채웠습니다.");
        }
        view->m_cases->SetItemState(3, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED,
                                    wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
        CanvasAssert(blocked == 6 && !view->m_openResult->IsEnabled() &&
                         view->m_record.at("physics_validated") == false,
                     "차단된 사례나 미실행 상태를 결과 조회 또는 물리 검증 완료로 표시했습니다.");
        m_setupChecks.push_back("validation_unexecuted_blocked_and_no_source");
        CanvasAssert(
            view->m_record.at("manufacturing").is_null() && view->m_record.at("measurement").is_null() &&
                view->m_limits->GetValue().Contains(Display("제작 조건: 미정")) &&
                view->m_limits->GetValue().Contains(Display("측정 조건: 미정")) &&
                view->m_basis->GetValue().Contains("2.788446%") && view->m_basis->GetValue().Contains("RFAD-D0-3.4") &&
                view->m_advanced->IsCollapsed() && !view->m_raw->IsEditable() && !view->m_basis->IsEditable() &&
                view->m_raw->GetValue().Contains(Display(view->m_record.at("assessment_hash").get<std::string>())),
            "미정값, 기존 미확립 근거 또는 접힌 불변 원문을 잃었습니다.");
        m_setupChecks.push_back("validation_unknowns_sources_and_collapsed_raw");
        view->Scroll(0, 10000);
        int x = 0, y = 0;
        view->GetViewStart(&x, &y);
        CanvasAssert(view->m_metrics->GetClientSize().y > view->FromDIP(80) && y > 0 &&
                         view->GetVirtualSize().y > view->GetClientSize().y &&
                         view->m_metrics->GetItemText(0, 2) == "2.4 GHz",
                     "좁은 화면에서 실제 지표 표에 스크롤로 접근하지 못하거나 주파수 단위가 다릅니다.");
        view->Scroll(0, 0);
        m_setupChecks.push_back("validation_visible_tables_and_scroll");
        CanvasAssert(m_frame.m_revision == m_validationRevision, "읽기 전용 검증 화면이 프로젝트를 변경했습니다.");
        m_setupStage = 7;
        m_frame.SaveProject();
    }
    else if (m_setupStage == 7 && m_frame.m_savedRevision == m_frame.m_revision)
    {
        m_setupStage = 8;
        m_frame.m_connected = false;
        m_frame.m_transportFailed = false;
        m_frame.m_restarting = true;
        m_frame.BeginShutdown();
    }
    else if (m_setupStage == 8 && m_serviceSessions >= 2)
    {
        m_setupStage = 9;
        m_frame.OpenValidationRecords();
        m_frame.UpdateValidationViews();
        controller.Select(m_validationFixture.at("validation_id").get<std::string>(),
                          m_validationFixture.at("first").at("report_id"));
    }
    else if (m_setupStage == 9 && idle() && view->m_record.is_object())
    {
        CanvasAssert(m_frame.m_revision == m_validationRevision && view->m_record == m_validationFixture.at("first"),
                     "저장과 서비스 재시작 뒤 과거 보고서 또는 원본 개정이 바뀌었습니다.");
        m_setupChecks.push_back("validation_saved_restart_report_preserved");
        m_frame.m_views->SetSelection(0);
        CanvasAssert(m_frame.m_selection == m_setupShapes, "설계 화면 복귀에서 원본 객체 선택이 바뀌었습니다.");
        m_setupChecks.push_back("validation_return_design_preserves_selection");
        FinishSmoke(true, "");
    }
}
