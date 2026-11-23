/** @file @brief 실제 결과 화면의 과거 개정, Smith, 비교와 원문 교환을 검증한다. */
#include "studio_internal.h"
#include "result_workspace.h"
#include "result_source_browser.h"
#include "result_network_view.h"
#include "result_compare_view.h"
#include "result_conditions_view.h"
#include "field_result_view.h"
#include "field_slice_canvas.h"
#include "smith_view.h"
#include "smith_chart.h"
#include "network_chart.h"
#include "network_export.h"
#include "studio_notebook.h"
#include "setup_smoke_support.h"
#include <wx/choicdlg.h>
#include <wx/scrolwin.h>
#include <wx/spinctrl.h>
#include <wx/textctrl.h>
#include <algorithm>
#include <fstream>
#include <cmath>

namespace
{
/** @brief 명시 포트 대응 대화상자에서 실제 첫 포트를 선택해 승인한다. */
class ResultPortHook final : public wxModalDialogHook
{
public:
    ResultPortHook()
    {
        Register();
    }
    ~ResultPortHook() override
    {
        Unregister();
    }
    int Enter(wxDialog* dialog) override
    {
        if (dialog->GetTitle() == Display("명시 포트 대응"))
        {
            auto* choice = dynamic_cast<wxSingleChoiceDialog*>(dialog);
            if (choice != nullptr)
            {
                choice->SetSelection(0);
                ++count;
                return wxID_OK;
            }
        }
        return wxID_NONE;
    }
    int count = 0;
};
}

void StudioSmokeDriver::ResultWorkspaceSafetyChecks()
{
    auto host = std::make_unique<wxDialog>(&m_frame, wxID_ANY, Display("결과 수명 검증"));
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
        CanvasAssert(!mutation, "결과 조회가 변경 명령을 전송했습니다.");
        calls.push_back({method, input, std::move(success)});
    };
    auto controller = std::make_unique<ResultWorkspace>(views, navigation, conditions, gateway);
    controller->m_available = true;
    controller->Select(m_resultsFixture.at("sources").at("first"));
    controller->Select(m_resultsFixture.at("sources").at("second"));
    CanvasAssert(calls.size() == 1, "결과 읽기 대기열이 직렬 요청을 유지하지 못했습니다.");
    const auto old = calls.front().success;
    old(m_resultsFixture.at("descriptions").at("first"));
    CanvasAssert(controller->m_description.is_null() && calls.size() == 2,
                 "늦게 도착한 이전 결과가 현재 선택으로 표시됐습니다.");
    calls.at(1).success(m_resultsFixture.at("descriptions").at("second"));
    CanvasAssert(controller->m_description.at("source") == m_resultsFixture.at("sources").at("second"),
                 "현재 결과 선택의 응답이 보존되지 않았습니다.");
    controller->Select(m_resultsFixture.at("sources").at("first"));
    const auto late = calls.back().success;
    controller->Reset();
    late(m_resultsFixture.at("descriptions").at("first"));
    CanvasAssert(controller->m_description.is_null(), "프로젝트 초기화 뒤 이전 결과가 복원됐습니다.");
    controller.reset();
    late(m_resultsFixture.at("descriptions").at("first"));
    m_setupChecks.push_back("results_late_selection_reset_destroy_safe");
}

void StudioSmokeDriver::ResultsSmokeTick()
{
    if (m_resultsAwaiting || m_frame.m_busy || !m_frame.m_results)
    {
        return;
    }
    auto& workspace = *m_frame.m_results;
    const auto idle = [&workspace]()
    {
        return !workspace.m_inflight && workspace.m_queue.empty();
    };
    if (m_setupStage == 1)
    {
        std::ifstream stream(std::filesystem::path(m_frame.m_options.workspace.ToStdWstring()) /
                                 "results-smoke-fixture.json",
                             std::ios::binary);
        stream >> m_resultsFixture;
        m_resultsRevision = m_frame.m_revision;
        m_setupShapes = m_frame.m_selection;
        CanvasAssert(m_resultsRevision == m_resultsFixture.at("revision_id"), "결과 시험의 저장 개정이 다릅니다.");
        if (m_resultsFixture.contains("field_source"))
        {
            m_setupStage = 100;
            m_frame.m_views->SetSelection(13);
            m_frame.UpdateResultViews();
            workspace.Select(m_resultsFixture.at("field_source"));
            return;
        }
        ResultWorkspaceSafetyChecks();
        m_frame.m_views->SetSelection(9);
        m_frame.UpdateResultViews();
        m_setupStage = 2;
    }
    else if (m_setupStage >= 100)
    {
        if (!idle())
        {
            return;
        }
        auto& field = *workspace.m_field;
        if (m_resultsFixture.contains("flux_surfaces"))
        {
            const bool first = m_setupStage == 100;
            if (first || m_setupStage == 102)
            {
                const auto& item = m_resultsFixture.at("flux_surfaces").at(first ? 0 : 1);
                CanvasAssert(field.m_fluxPanel->IsShown() && field.m_flux->IsEnabled(), "E/H 체적의 면 적분 입력이 없습니다.");
                SetupSmoke::Choose(field.m_fluxFace, first ? 4 : 6);
                for (int i = 0; i < 3; ++i)
                {
                    for (int end = 0; end < 2; ++end)
                    {
                        if (field.m_fluxBounds[i][end]->IsEnabled())
                        {
                            field.m_fluxBounds[i][end]->SetValue(Display(item.at("bounds_mm").at(i).at(end).dump()));
                        }
                    }
                }
                ++m_setupStage;
                SetupSmoke::Click(field.m_flux);
            }
            else
            {
                const bool rectangle = m_setupStage == 101;
                const auto& item = m_resultsFixture.at("flux_surfaces").at(rectangle ? 0 : 1);
                const auto text = field.m_fluxReport->GetValue();
                double actual = 0;
                const auto expected = item.at("total").get<double>();
                CanvasAssert(text.Contains(Display("W*s^2")) && text.AfterFirst(' ').BeforeFirst(' ').ToCDouble(&actual) &&
                             std::abs(actual - expected) <= std::max(1e-44, std::abs(expected) * 1e-12) &&
                             workspace.Pinned().at("pin") == m_resultsFixture.at("pin") && m_frame.m_revision == m_resultsRevision,
                             "통과량 합계, Fourier 단위 또는 원본 pin이 다릅니다.");
                m_setupChecks.push_back(rectangle ? "field_flux_rectangle" : "field_flux_box_six_faces");
                if (!rectangle)
                {
                    CanvasAssert(text.Contains(Display("-x")) && text.Contains(Display("+z")), "바깥쪽 여섯 면의 표시가 없습니다.");
                    FinishSmoke(true, "");
                    return;
                }
                ++m_setupStage;
            }
            return;
        }
        if (m_setupStage == 100 || m_setupStage == 104)
        {
            CanvasAssert(field.m_description.value("status", "") == "available" &&
                             field.m_monitor->GetCount() == 3 && field.m_frequency->GetCount() >= 2 &&
                             field.m_canvas->IsShownOnScreen() &&
                             workspace.Pinned().at("pin") == m_resultsFixture.at("pin"),
                         "실제 기록 필드나 고정 원본을 열지 못했습니다.");
            const int step = m_setupStage == 104 ? 0 : static_cast<int>(m_setupChecks.size());
            const int frequency = step % static_cast<int>(field.m_frequency->GetCount());
            SetupSmoke::Choose(field.m_frequency, frequency);
            field.m_uCount->SetValue(std::min(24, field.m_uCount->GetMax()));
            field.m_vCount->SetValue(std::min(24, field.m_vCount->GetMax()));
            field.m_uStart->SetValue(std::min(step, field.m_uCount->GetMax() - field.m_uCount->GetValue()));
            field.m_vStart->SetValue(std::min(step, field.m_vCount->GetMax() - field.m_vCount->GetValue()));
            ++m_setupStage;
            SetupSmoke::Click(field.m_load);
        }
        else if (m_setupStage == 101 || m_setupStage == 105)
        {
            const auto& slice = field.m_slice;
            CanvasAssert(slice.is_object() && slice.at("pin") == m_resultsFixture.at("pin") &&
                             !slice.at("physics_validated").get<bool>() &&
                             slice.at("selection").at("frequency_index").get<int>() == field.m_frequency->GetSelection() &&
                             slice.at("selection").at("roi").at("u_start").get<int>() == field.m_uStart->GetValue() &&
                             slice.at("selection").at("roi").at("v_start").get<int>() == field.m_vStart->GetValue(),
                         "필드 화면이 선택과 다른 기록 주파수 또는 ROI를 표시했습니다.");
            const auto rows = slice.at("v_coordinates_mm").size();
            const auto columns = slice.at("u_coordinates_mm").size();
            CanvasAssert(rows > 1 && columns > 1 && field.m_canvas->m_colors.size() == rows * columns &&
                             field.m_point->IsEnabled() && field.m_marker->GetValue().Contains(Display("복소값")),
                         "필드 화면에 색 셀 또는 실제 표본 마커가 없습니다.");
            CanvasAssert(field.m_position->GetLabel().Contains(Display("실제 격자")),
                         "단면 좌표가 실제 격자 위치임을 표시하지 않았습니다.");
            field.m_canvas->Update();
            CanvasAssert(field.m_canvas->m_plot.width > 0 && field.m_canvas->m_plot.height > 0,
                         "필드 화면의 실제 그리기를 확인하지 못했습니다.");
            if (m_setupStage == 105)
            {
                CanvasAssert(slice == m_resultsFirst && m_frame.m_revision == m_resultsRevision,
                             "저장과 서비스 재시작 뒤 필드 원문이나 설계 개정이 바뀌었습니다.");
                m_setupChecks.push_back("field_raw_roi_and_pin_survive_reopen");
                FinishSmoke(true, "");
                return;
            }
            if (m_setupChecks.empty())
            {
                m_resultsFirst = slice;
            }
            m_setupChecks.push_back("field_roi_" + std::to_string(m_setupChecks.size() + 1));
            m_setupStage = 100;
            if (m_setupChecks.size() == 10)
            {
                CanvasAssert(m_frame.m_revision == m_resultsRevision, "읽기 전용 필드가 프로젝트를 변경했습니다.");
                m_setupStage = 102;
                m_frame.SaveProject();
            }
        }
        else if (m_setupStage == 102 && m_frame.m_savedRevision == m_frame.m_revision)
        {
            m_setupStage = 103;
            m_frame.m_connected = false;
            m_frame.m_transportFailed = false;
            m_frame.m_restarting = true;
            m_frame.BeginShutdown();
        }
        else if (m_setupStage == 103 && m_serviceSessions >= 2)
        {
            m_setupStage = 104;
            m_frame.m_views->SetSelection(13);
            m_frame.UpdateResultViews();
            workspace.Select(m_resultsFixture.at("field_source"));
        }
    }
    else if (m_setupStage == 2 && idle() && workspace.m_catalog.is_object())
    {
        auto* browser = workspace.m_browser;
        if (browser->Kind() == "all")
        {
            CanvasAssert(workspace.m_catalog.at("resolved_revision_id") == m_resultsRevision &&
                             workspace.m_catalog.at("current_totals").is_object(),
                         "첫 결과 목록이 현재 개정의 해석과 등록 자료를 읽지 못했습니다.");
            SetupSmoke::Choose(browser->m_kind, 0);
            return;
        }
        int selected = -1;
        for (std::size_t index = 0; index < browser->m_anchors.size(); ++index)
        {
            const auto& anchor = browser->m_anchors.at(index);
            if (anchor.at("revision_id") == m_resultsFixture.at("sources").at("first").at("revision_id") &&
                anchor.at("snapshot_id").is_null())
            {
                CanvasAssert(anchor.at("revision_label").get<std::string>().find("보존 개정") != std::string::npos,
                             "개정 목록에 사용자 표시 이름이 없습니다.");
                selected = static_cast<int>(index + 1);
            }
        }
        CanvasAssert(selected >= 0, "보존된 과거 결과 개정을 목록에서 찾지 못했습니다.");
        m_setupStage = 3;
        SetupSmoke::Choose(browser->m_anchor, selected);
    }
    else if (m_setupStage == 3 && idle() && workspace.m_catalog.is_object())
    {
        CanvasAssert(workspace.m_catalog.at("items").size() == 1 &&
                         workspace.m_catalog.at("items").at(0).at("source") ==
                             m_resultsFixture.at("sources").at("first"),
                     "과거 개정의 결과가 현재 목록으로 대체됐습니다.");
        m_setupStage = 4;
        workspace.m_browser->m_items->SetItemState(0, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED,
                                                   wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
    }
    else if (m_setupStage == 4 && idle() && workspace.m_network->m_response.is_object())
    {
        m_resultsFirst = workspace.m_description;
        CanvasAssert(m_resultsFirst.at("pin") == m_resultsFixture.at("descriptions").at("first").at("pin") &&
                         !m_resultsFirst.at("is_current_design").get<bool>(),
                     "과거 개정의 원본 pin이 바뀌었습니다.");
        CanvasAssert(workspace.m_network->m_samples->GetItemCount() == 4 &&
                         workspace.m_network->m_samples->GetClientSize().y > workspace.m_network->FromDIP(80),
                     "실제 네트워크 표본을 읽거나 표를 표시하지 못했습니다.");
        m_setupChecks.push_back("results_past_revision_named_catalog");
        m_setupStage = 5;
        workspace.Select(m_resultsFixture.at("sources").at("unknown"));
    }
    else if (m_setupStage == 5 && idle() && workspace.m_network->m_response.is_object())
    {
        CanvasAssert(workspace.m_description.at("descriptor").at("phasor_convention") == "unknown" &&
                         workspace.m_description.at("descriptor").at("reference_planes").at(0).is_null(),
                     "미정 원문에 파/기준면 조건을 채웠습니다.");
        CanvasAssert(m_frame.m_revision == m_resultsRevision, "결과 선택이 원본 개정을 변경했습니다.");
        m_setupChecks.push_back("results_unknown_source_preserved");
        auto* conditions = workspace.m_conditions;
        CanvasAssert(!conditions->m_originalGroup->IsCollapsed() && !conditions->m_basisGroup->IsCollapsed() &&
                         !conditions->m_validationGroup->IsCollapsed() && conditions->m_advanced->IsCollapsed(),
                     "결과 조건의 세 그룹 또는 접힌 고급 원문이 시안 구조와 다릅니다.");
        CanvasAssert(conditions->m_basis->GetValue().Contains(Display("기준면: 미정")) &&
                         conditions->m_validation->GetValue().Contains(Display("제작 조건: 미정")) &&
                         conditions->m_validation->GetValue().Contains(Display("측정 조건: 미정")) &&
                         conditions->m_copyText.find("계산 종료 기록") != std::string::npos &&
                         !conditions->m_summary->IsEditable() && !conditions->m_basis->IsEditable(),
                     "그룹 표시에서 미정 조건, 종료 기록 또는 복사 가능한 원문이 사라졌습니다.");
        conditions->m_scroll->Scroll(0, 1000);
        CanvasAssert(conditions->m_scroll->GetVirtualSize().y >= conditions->m_scroll->GetClientSize().y &&
                         conditions->m_validation->GetClientSize().y > conditions->FromDIP(50),
                     "작은 속성 영역에서 검증 상태에 스크롤로 접근할 수 없습니다.");
        conditions->m_scroll->Scroll(0, 0);
        m_setupChecks.push_back("results_grouped_conditions_preserve_unknowns");
        m_setupStage = 6;
        workspace.Select(m_resultsFixture.at("sources").at("first"));
        workspace.Select(m_resultsFixture.at("sources").at("second"));
    }
    else if (m_setupStage == 6 && idle() && workspace.m_network->m_response.is_object())
    {
        CanvasAssert(workspace.m_description.at("source") == m_resultsFixture.at("sources").at("second"),
                     "빠른 원본 전환 뒤 이전 응답이 표시됐습니다.");
        m_resultsSecond = workspace.m_description;
        m_setupStage = 7;
        m_frame.m_views->SetSelection(10);
        workspace.Select(m_resultsFixture.at("sources").at("first"));
    }
    else if (m_setupStage == 7 && idle() && workspace.m_smith->m_response.is_object())
    {
        auto* smith = workspace.m_smith;
        const auto& points = smith->m_response.at("points");
        CanvasAssert(
            points.size() == 4 && points.at(0).at("input_impedance_ohm_ri").at(0) == 50 &&
                points.at(1).at("impedance_state") == "infinite" && points.at(2).at("admittance_state") == "infinite" &&
                points.at(3).at("passivity_region") == "active_region" && points.at(3).at("gamma_ri").at(0) == 2,
            "Smith 정합/개방/단락/능동영역이 실제 표본과 다릅니다.");
        SetupSmoke::Click(smith->m_markerNext);
        CanvasAssert(smith->m_markerIndex == 1 && smith->m_markerValues->GetItemText(1, 1) == Display("1.25 GHz"),
                     "Smith 마커 주파수 또는 표시 단위가 다릅니다.");
        CanvasAssert(smith->m_chart->GetClientSize().y > smith->FromDIP(120), "Smith 표시 높이가 부족합니다.");
        m_setupChecks.push_back("results_smith_poles_active_and_units");
        m_setupStage = 8;
        m_frame.m_views->SetSelection(14);
        CanvasAssert(workspace.m_compare->Add(m_resultsFirst), "첫 비교 원본을 추가하지 못했습니다.");
        workspace.Select(m_resultsFixture.at("sources").at("second"));
    }
    else if (m_setupStage == 8 && idle() && workspace.m_description.is_object())
    {
        CanvasAssert(workspace.m_compare->Add(m_resultsSecond), "두 번째 비교 원본을 추가하지 못했습니다.");
        m_setupStage = 9;
    }
    else if (m_setupStage == 9 && idle() && workspace.m_compare->m_pages.size() == 2 &&
             workspace.m_compare->m_pages.at(1).is_object())
    {
        CanvasAssert(workspace.m_compare->m_requirements->GetLabel().Contains(Display("버튼에서 지정")) &&
                         !workspace.m_compare->m_compare->IsEnabled(),
                     "포트 미대응 상태에서 차이 버튼의 조건과 위치를 안내하지 않았습니다.");
        ResultPortHook mapping;
        SetupSmoke::Click(workspace.m_compare->m_map);
        CanvasAssert(mapping.count == 1 && workspace.m_compare->PortOrder(1) == Json::array({0}),
                     "실제 포트 대응 선택을 기록하지 못했습니다.");
        m_setupStage = 10;
    }
    else if (m_setupStage == 10 && idle() && workspace.m_compare->m_comparisons.at(1).is_object())
    {
        CanvasAssert(workspace.m_compare->m_requirements->GetLabel().Contains(Display("3/4개 일치")),
                     "같은 실제 주파수 개수를 표시하지 않았습니다.");
        const auto& comparison = workspace.m_compare->m_comparisons.at(1);
        CanvasAssert(comparison.at("difference_definition") == "right_minus_left" &&
                         comparison.at("points").at(0).at("difference_ri").at(0) == .2 &&
                         comparison.at("points").at(2).at("difference_ri").is_null(),
                     "복소 차이의 방향 또는 없는 실제 주파수 처리가 다릅니다.");
        CanvasAssert(comparison.at("physical_comparability").at("status") == "not_established",
                     "단순 차이를 물리 합격으로 표시했습니다.");
        bool conditions = false;
        for (const auto& row : comparison.at("condition_differences"))
        {
            if (row.at("field") == "conditions.manufacturing")
            {
                conditions = !row.at("affects_math").get<bool>() && row.at("difference") == "one_unknown";
            }
        }
        CanvasAssert(conditions && workspace.m_compare->m_differences->GetItemCount() == 4 &&
                         workspace.m_compare->m_differences->GetClientSize().y > workspace.m_compare->FromDIP(80),
                     "조건 차이 또는 실제 차이 표를 표시하지 못했습니다.");
        m_setupChecks.push_back("results_explicit_port_comparison_and_conditions");
        CanvasAssert(workspace.m_conditions->ConditionTotal() > 32 && workspace.m_conditions->m_next->IsEnabled(),
                     "32개를 넘는 보존 조건의 다음 페이지가 없습니다.");
        m_setupStage = 16;
        SetupSmoke::Click(workspace.m_conditions->m_next);
    }
    else if (m_setupStage == 16 && idle() && workspace.m_conditions->m_conditionPage.is_object() &&
             workspace.m_conditions->m_conditionPage.at("offset") == 32)
    {
        auto* conditions = workspace.m_conditions;
        CanvasAssert(conditions->m_conditionPage.at("items").size() <= 32 &&
                         conditions->m_pageLabel->GetLabel().Contains("33~") &&
                         conditions->m_validation->GetValue().Contains(Display("보존 조건 39")) &&
                         conditions->m_conditionPage.at("next_offset").is_null(),
                     "조건의 마지막 페이지를 읽지 못했거나 이전 페이지를 합쳐 표시했습니다.");
        m_setupStage = 17;
        SetupSmoke::Click(conditions->m_previous);
    }
    else if (m_setupStage == 17 && idle() && workspace.m_conditions->m_conditionPage.is_object() &&
             workspace.m_conditions->m_conditionPage.at("offset") == 0)
    {
        SetupSmoke::Click(workspace.m_conditions->m_next);
        CanvasAssert(workspace.m_conditions->m_conditionsPending, "다음 조건 페이지 요청이 접수되지 않았습니다.");
        workspace.m_compare->m_sources->SetItemState(1, 0, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
        workspace.m_compare->m_sources->SetItemState(0, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED,
                                                     wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
        m_setupStage = 18;
    }
    else if (m_setupStage == 18 && idle())
    {
        CanvasAssert(workspace.m_conditions->m_conditionPage.is_null() && !workspace.m_conditions->m_pager->IsShown() &&
                         workspace.m_conditions->m_summary->GetValue().Contains(
                             Display(m_resultsFirst.at("label").get<std::string>())) &&
                         m_frame.m_revision == m_resultsRevision,
                     "다른 원본을 선택한 뒤 늦은 조건 페이지가 덮어쓰거나 원본을 바꿨습니다.");
        m_setupChecks.push_back("results_conditions_pages_and_stale_selection");
        workspace.m_compare->m_sources->SetItemState(0, 0, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
        workspace.m_compare->m_sources->SetItemState(1, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED,
                                                     wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
        m_setupStage = 11;
        workspace.m_compare->m_chart->onMarker(0, 2, 1.5e9);
    }
    else if (m_setupStage == 11 && idle())
    {
        CanvasAssert(workspace.m_compare->m_markerIndices == std::vector<int>({2, -1}),
                     "다른 곡선에 없는 주파수를 근처 값으로 대신했습니다.");
        m_setupChecks.push_back("results_exact_shared_frequency_marker");
        CanvasAssert(workspace.m_conditions->m_heading->GetLabel() == Display("비교 조건"),
                     "비교 조회 후 해당 비교 조건을 표시하지 않았습니다.");
        workspace.m_compare->m_sources->SetItemState(1, 0, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
        workspace.m_compare->m_sources->SetItemState(0, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED,
                                                     wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
        CanvasAssert(workspace.m_conditions->m_heading->GetLabel() == Display("결과 조건 / 원본 보존") &&
                         workspace.m_conditions->m_summary->GetValue().Contains(
                             Display(m_resultsFirst.at("label").get<std::string>())),
                     "기준 원본을 선택한 뒤 이전 비교 조건이 남았습니다.");
        m_setupChecks.push_back("results_comparison_selection_restores_source_conditions");
        m_setupStage = 12;
        m_resultsAwaiting = true;
        m_frame.Send(
            "result.export",
            {{"source", m_resultsFirst.at("source")}, {"pin", m_resultsFirst.at("pin")}, {"format", "csv"}}, false,
            m_frame.Context(),
            [this](const Json& result)
            {
                CanvasAssert(result.at("source") == m_resultsFirst.at("source") &&
                                 result.at("pin") == m_resultsFirst.at("pin"),
                             "내보낼 과거 원본의 고정 식별자가 다릅니다.");
                const auto path = std::filesystem::path(m_frame.m_options.workspace.ToStdWstring()).parent_path() /
                                  L"GUI 과거 결과.csv";
                WriteNetworkExportFiles(result, wxString(path.wstring()), m_frame.m_options.workspace);
                m_setupChecks.push_back("results_pinned_historical_export");
                m_resultsAwaiting = false;
            },
            [this](const Json& error)
            {
                m_resultsAwaiting = false;
                FinishSmoke(false, DiagnosticMessage(error));
            });
    }
    else if (m_setupStage == 12)
    {
        CanvasAssert(m_frame.m_revision == m_resultsRevision, "읽기 전용 결과 작업이 설계 개정을 변경했습니다.");
        m_setupStage = 13;
        m_frame.SaveProject();
    }
    else if (m_setupStage == 13 && m_frame.m_savedRevision == m_frame.m_revision)
    {
        m_setupStage = 14;
        m_frame.m_connected = false;
        m_frame.m_transportFailed = false;
        m_frame.m_restarting = true;
        m_frame.BeginShutdown();
    }
    else if (m_setupStage == 14 && m_serviceSessions >= 2)
    {
        m_setupStage = 15;
        m_frame.m_views->SetSelection(9);
        m_frame.UpdateResultViews();
        workspace.Select(m_resultsFixture.at("sources").at("first"));
    }
    else if (m_setupStage == 15 && idle() && workspace.m_network->m_response.is_object())
    {
        CanvasAssert(m_frame.m_revision == m_resultsRevision &&
                         workspace.m_description.at("pin") == m_resultsFirst.at("pin"),
                     "서비스 재시작 뒤 과거 원본 또는 현재 개정이 바뀌었습니다.");
        m_setupChecks.push_back("results_saved_restart_preserves_source");
        m_frame.m_views->SetSelection(0);
        CanvasAssert(m_frame.m_selection == m_setupShapes, "설계 화면으로 복귀할 때 객체 선택이 바뀌었습니다.");
        m_setupChecks.push_back("results_return_design_preserves_selection");
        FinishSmoke(true, "");
    }
}
