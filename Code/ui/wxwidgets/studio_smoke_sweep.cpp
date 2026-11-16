/** @file @brief 실제 연구 폼과 외부 회로 실행/취소/재개 및 저장 재열기를 검증한다. */
#include "studio_internal.h"
#include "sweep_dialog.h"
#include "sweep_panel.h"
#include "sweep_result_dialog.h"
#include "studio_notebook.h"
#include "setup_smoke_support.h"
#include "workspace_bar.h"
#include <wx/checklst.h>
#include <wx/listbox.h>
#include <wx/spinctrl.h>
#include <wx/collpane.h>
#include <wx/grid.h>
#include <cmath>

namespace
{
/** @brief 입력 방식 확인 창의 실제 거절/승인 분기만 고정해 초안 보존을 검사한다. */
class ValueModeHook final : public wxModalDialogHook
{
public:
    explicit ValueModeHook(int response) : m_response(response)
    {
        Register();
    }
    ~ValueModeHook() override
    {
        Unregister();
    }
    int Enter(wxDialog* dialog) override
    {
        if (dialog->GetTitle() == Display("값 입력 방식"))
        {
            ++count;
            return m_response;
        }
        return wxID_NONE;
    }
    int count = 0;

private:
    int m_response;
};
}

void StudioSmokeDriver::SweepSmokeRequest(const std::string& method, const Json& input, bool mutation,
                                          std::function<void(const Json&)> completed)
{
    m_sweepAwaiting = true;
    m_frame.Send(
        method, input, mutation, m_frame.Context(),
        [this, completed](const Json& result)
        {
            m_sweepAwaiting = false;
            completed(result);
        },
        [this](const Json& error)
        {
            m_sweepAwaiting = false;
            FinishSmoke(false, DiagnosticMessage(error));
        });
}

void StudioSmokeDriver::OpenSweepSmokeDialog()
{
    m_frame.CallAfter(
        [this]()
        {
            m_frame.OpenSweepSetup();
        });
}

void StudioSmokeDriver::SweepSmokeTick()
{
    if (m_sweepAwaiting)
    {
        return;
    }
    auto* resultDialog = dynamic_cast<SweepResultDialog*>(m_frame.m_setupDialog);
    if (resultDialog)
    {
        if (resultDialog->m_pending || resultDialog->m_result.is_null())
        {
            return;
        }
        if (m_setupStage == 20)
        {
            CanvasAssert(resultDialog->m_studyId == m_sweepCircuitId && resultDialog->m_index == 0,
                         "선택한 연구 후보와 실제 결과 창의 원본이 다릅니다.");
            m_setupStage = 21;
            resultDialog->m_tabs->SetSelection(1);
        }
        else if (m_setupStage == 21)
        {
            wxListItem heading;
            heading.SetMask(wxLIST_MASK_TEXT);
            resultDialog->m_samples->GetColumn(0, heading);
            double displayed = 0;
            const auto realText = resultDialog->m_samples->GetItemText(0, 1);
            CanvasAssert(resultDialog->m_samples->GetItemCount() == 201 && resultDialog->m_samples->IsShownOnScreen() &&
                             resultDialog->m_samples->GetClientSize().y > resultDialog->FromDIP(100) &&
                             heading.GetText().Find("GHz") != wxNOT_FOUND &&
                             resultDialog->m_samples->GetItemText(0, 0) == "1" && realText.length() <= 12 &&
                             realText.ToDouble(&displayed) && std::abs(displayed - 613.0 / 1513.0) < 1e-8 &&
                             resultDialog->m_samples->GetItemText(0, 6) == Display("유효 / 파생"),
                         "후보 결과 표의 주파수/간결한 수치/유효 상태/출처 또는 실제 표시 높이가 잘못되었습니다.");
            m_setupStage = 22;
            resultDialog->m_tabs->SetSelection(2);
        }
        else if (m_setupStage == 22)
        {
            const auto conditions = resultDialog->m_conditions->GetValue();
            CanvasAssert(resultDialog->m_conditions->IsShownOnScreen() &&
                             conditions.Find(Display("기준면")) != wxNOT_FOUND &&
                             conditions.Find(Display("제작")) != wxNOT_FOUND &&
                             conditions.Find(Display("측정")) != wxNOT_FOUND &&
                             conditions.Find(Display("미정")) != wxNOT_FOUND &&
                             conditions.Find("\"frequency_min_hz\"") == wxNOT_FOUND &&
                             conditions.Find("\"reference_planes\"") == wxNOT_FOUND &&
                             resultDialog->m_advanced->IsCollapsed() && !resultDialog->m_source->IsShownOnScreen(),
                         "기본 조건 화면에 원문 JSON이 노출되거나 제작/측정 미정 상태가 사라졌습니다.");
            CanvasAssert(m_frame.m_revision == m_setupExpectedRevision,
                         "읽기 전용 후보 결과를 여는 동안 설계 개정이 바뀌었습니다.");
            m_setupChecks.push_back("sweep_candidate_result_native_conditions");
            m_setupStage = 23;
            SetupSmoke::Click(dynamic_cast<wxButton*>(resultDialog->FindWindow(wxID_CANCEL)));
        }
        return;
    }
    auto* dialog = dynamic_cast<SweepDialog*>(m_frame.m_setupDialog);
    if (dialog && dialog->m_pending)
    {
        return;
    }
    if (dialog)
    {
        const auto addValues = [this, dialog](int index, const std::vector<std::pair<std::string, std::string>>& values)
        {
            SetupSmoke::Choose(dialog->m_availableVariables, index);
            SetupSmoke::Click(dialog->m_addVariable);
            for (const auto& item : values)
            {
                const int unit = dialog->m_valueUnit->FindString(Display(item.second));
                CanvasAssert(unit != wxNOT_FOUND, "시험 변수의 명시 단위를 찾지 못했습니다.");
                SetupSmoke::Choose(dialog->m_valueUnit, unit);
                dialog->m_valueText->SetValue(Display(item.first));
                SetupSmoke::Click(dialog->m_addValue);
            }
        };
        if (m_setupStage == 2)
        {
            m_sweepContext = dialog->m_context;
            CanvasAssert(dialog->m_catalog.size() >= 2, "두 설계 변수의 원본을 읽지 못했습니다.");
            dialog->m_name->SetValue(Display("GUI 2x2 설계 후보"));
            dialog->m_sources->SetValue(Display("GUI 명시 스윕 입력; 실측 아님"));
            addValues(0, {{"1", "mm"}, {"1.2", "mm"}});
            addValues(1, {{"1", "mm"}, {"1.2", "mm"}});
            const auto& frequency = dialog->m_settings.at("frequency_hz.start");
            CanvasAssert(frequency.unit->GetStringSelection() == "GHz" && frequency.text->GetValue() == "2.4",
                         "초기 주파수가 2.4 GHz로 표시되지 않았습니다.");
            m_setupStage = 3;
            SetupSmoke::Click(dialog->m_preview);
        }
        else if (m_setupStage == 3)
        {
            CanvasAssert(dialog->m_review.is_object() && dialog->m_review.value("can_create", false) &&
                             dialog->m_review.at("candidate_count") == 4 && dialog->m_previewRows->GetItemCount() == 4,
                         "실제 2변수 2x2 후보 검토 결과가 다릅니다.");
            CanvasAssert(dialog->m_previewRows->IsShownOnScreen() &&
                             dialog->m_previewRows->GetClientSize().y > dialog->FromDIP(100),
                         "후보 검토 표의 실제 표시 높이가 사라졌습니다.");
            const auto& candidates = dialog->m_review.at("candidates");
            CanvasAssert(candidates.at(0).at("indices") == Json::array({0, 0}) &&
                             candidates.at(3).at("indices") == Json::array({1, 1}),
                         "Cartesian 후보 순서가 바뀌었습니다.");
            m_setupChecks.push_back("sweep_cartesian_preview_2_by_2");
            m_setupChecks.push_back("sweep_native_fields_and_viewport");
            m_sweepView = dialog->m_review;
            m_sweepContext = dialog->Specification();
            m_setupStage = 301;
            auto* units = dialog->m_settings.at("frequency_hz.start").unit;
            SetupSmoke::Choose(units, units->FindString("MHz"));
        }
        else if (m_setupStage == 301)
        {
            const auto& frequency = dialog->m_settings.at("frequency_hz.start");
            CanvasAssert(frequency.unit->GetStringSelection() == "MHz" && frequency.text->GetValue() == "2400" &&
                             dialog->Specification() == m_sweepContext && dialog->m_review == m_sweepView &&
                             m_frame.m_revision == m_setupExpectedRevision,
                         "MHz 표시 전환이 수치 설정/입력 원문/검토 상태를 바꿨습니다.");
            m_setupStage = 302;
            SetupSmoke::Choose(frequency.unit, frequency.unit->FindString("GHz"));
        }
        else if (m_setupStage == 302)
        {
            const auto& frequency = dialog->m_settings.at("frequency_hz.start");
            CanvasAssert(frequency.unit->GetStringSelection() == "GHz" && frequency.text->GetValue() == "2.4" &&
                             dialog->Specification() == m_sweepContext && dialog->m_review == m_sweepView,
                         "GHz 표시 복귀가 기존 SI 수치나 검토 hash를 바꿨습니다.");
            m_setupChecks.push_back("sweep_frequency_display_preserves_review_and_si");
            dialog->m_name->SetValue(Display("GUI 2x2 저장 연구"));
            CanvasAssert(dialog->m_review.is_null() && !dialog->m_create->IsEnabled(),
                         "입력 변경 뒤 이전 검토로 연구를 저장할 수 있습니다.");
            m_setupChecks.push_back("sweep_changed_input_invalidates_review");
            m_setupStage = 4;
            SetupSmoke::Click(dialog->m_preview);
        }
        else if (m_setupStage == 4)
        {
            CanvasAssert(dialog->m_review.is_object() && dialog->m_review.value("can_create", false) &&
                             dialog->m_review.at("review_hash") != m_sweepView.at("review_hash"),
                         "변경한 원문으로 새 검토 hash가 생성되지 않았습니다.");
            SetupSmoke::Choose(dialog->m_combination, 2);
            SetupSmoke::Click(dialog->m_addRow);
            dialog->m_rows->SetCellValue(0, 0, "1: 1 mm");
            dialog->m_rows->SetCellValue(0, 1, "2: 1.2 mm");
            m_setupStage = 401;
            SetupSmoke::Click(dialog->m_preview);
        }
        else if (m_setupStage == 401)
        {
            CanvasAssert(dialog->m_review.is_object() && dialog->m_review.value("can_create", false) &&
                             dialog->m_review.at("candidate_count") == 1 &&
                             dialog->Specification().at("rows") == Json::array({Json::array({0, 1})}),
                         "명시 후보 행의 선택 값으로 검토하지 못했습니다.");
            const auto before = dialog->Specification();
            const auto reviewed = dialog->m_review;
            {
                ValueModeHook answer(wxID_NO);
                SetupSmoke::Choose(dialog->m_valueMode, 1);
                CanvasAssert(answer.count == 1 && dialog->m_valueMode->GetSelection() == 0 &&
                                 dialog->Specification() == before && dialog->m_review == reviewed &&
                                 dialog->m_rows->GetNumberRows() == 1 && dialog->m_create->IsEnabled() &&
                                 m_frame.m_revision == m_setupExpectedRevision,
                             "입력 방식 변경 거절이 값/명시 행/검토 또는 원본 개정을 바꿨습니다.");
            }
            {
                ValueModeHook answer(wxID_YES);
                SetupSmoke::Choose(dialog->m_valueMode, 1);
                CanvasAssert(answer.count == 1 && dialog->m_valueMode->GetSelection() == 1 &&
                                 dialog->m_rows->GetNumberRows() == 0 && dialog->m_review.is_null() &&
                                 !dialog->m_create->IsEnabled() && m_frame.m_revision == m_setupExpectedRevision,
                             "승인한 범위 전환이 이전 명시 행이나 검토를 그대로 재사용합니다.");
            }
            dialog->m_rangeStart->SetValue("1.1");
            dialog->m_rangeStop->SetValue("1.3");
            {
                ValueModeHook answer(wxID_YES);
                SetupSmoke::Choose(dialog->m_valueMode, 0);
                CanvasAssert(answer.count == 1 && dialog->m_rows->GetNumberRows() == 0 &&
                                 dialog->m_variables.at(dialog->m_variableIndex).at("values").empty() &&
                                 dialog->m_review.is_null(),
                             "범위에서 새 목록으로 돌아올 때 과거 후보 인덱스가 남았습니다.");
            }
            for (const auto* value : {"1", "1.2"})
            {
                dialog->m_valueText->SetValue(value);
                SetupSmoke::Click(dialog->m_addValue);
            }
            SetupSmoke::Choose(dialog->m_combination, 0);
            CanvasAssert(dialog->Specification().at("rows").empty() && m_frame.m_revision == m_setupExpectedRevision,
                         "새 값 목록 입력이 기존 명시 행 또는 설계 원본을 암묵 변경했습니다.");
            m_setupChecks.push_back("sweep_value_mode_explicit_rows_safe_reset");
            m_setupStage = 402;
            SetupSmoke::Click(dialog->m_preview);
        }
        else if (m_setupStage == 402)
        {
            CanvasAssert(dialog->m_review.is_object() && dialog->m_review.value("can_create", false) &&
                             dialog->m_review.at("candidate_count") == 4,
                         "새 명시 값 목록을 다시 검토한 2x2 후보가 잘못되었습니다.");
            m_setupStage = 5;
            SetupSmoke::Click(dialog->m_create);
        }
        else if (m_setupStage == 7)
        {
            dialog->m_name->SetValue(Display("GUI 외부 회로 3후보"));
            dialog->m_sources->SetValue(Display("GUI 명시 스윕 입력; 실측 아님"));
            SetupSmoke::Choose(dialog->m_type, 2);
            CanvasAssert(!dialog->m_context.at("datasets").empty() && !dialog->m_context.at("circuits").empty(),
                         "저장한 원본 자료와 외부 회로가 목록에 없습니다.");
            SetupSmoke::Choose(dialog->m_datasets, 0);
            SetupSmoke::Choose(dialog->m_circuits, 0);
            addValues(0, {{"50", "ohm"}, {"100", "ohm"}, {"0.05", "kohm"}});
            dialog->m_nativeBudget->SetValue(0);
            CanvasAssert(dialog->m_targets->GetCount() == 1, "미정 목표 대응 시험의 목표 개수가 다릅니다.");
            dialog->m_targets->Check(0);
            wxCommandEvent event(wxEVT_CHECKLISTBOX, dialog->m_targets->GetId());
            event.SetEventObject(dialog->m_targets);
            event.SetInt(0);
            dialog->m_targets->GetEventHandler()->ProcessEvent(event);
            m_setupStage = 8;
            SetupSmoke::Click(dialog->m_preview);
        }
        else if (m_setupStage == 8)
        {
            CanvasAssert(dialog->m_review.is_object() && dialog->m_review.value("can_create", false) &&
                             dialog->m_review.at("candidate_count") == 3 &&
                             dialog->m_review.at("counts").at("duplicates") == 1 &&
                             dialog->m_review.at("candidates").at(2).at("duplicate_of") == 0,
                         "회로 값의 단위 동치와 중복 후보가 유지되지 않았습니다.");
            const auto specification = dialog->Specification();
            CanvasAssert(specification.at("settings").is_null() && specification.at("target_contexts").empty() &&
                             specification.at("variables").at(0).at("values").at(2).at("unit") == "kohm",
                         "회로 원문 단위/미정 대응 또는 EM 외부 경계가 바뀌었습니다.");
            m_setupChecks.push_back("sweep_circuit_units_and_duplicate_preserved");
            m_setupStage = 9;
            SetupSmoke::Click(dialog->m_create);
        }
        return;
    }
    if (m_frame.m_busy || m_frame.m_sweepPending || m_frame.m_sweepRefreshQueued || m_frame.m_cadRestoring ||
        m_frame.m_solverRestoring)
    {
        return;
    }
    if (m_setupStage == 1)
    {
        m_setupExpectedRevision = m_frame.m_revision;
        m_precisionUndoBefore = m_frame.m_editor.at("history").at("undo_count");
        m_setupShapes = m_frame.m_selection;
        m_setupStage = 2;
        OpenSweepSmokeDialog();
    }
    else if (m_setupStage == 5)
    {
        SweepSmokeRequest("sweep.list", Json::object(), false,
                          [this](const Json& result)
                          {
                              CanvasAssert(result.at("studies").size() == 1 &&
                                               result.at("studies").at(0).at("state") == "ready",
                                           "연구 저장이 실행을 자동 시작했습니다.");
                              m_sweepGridId = result.at("studies").at(0).at("study_id");
                              CanvasAssert(m_frame.m_revision == m_setupExpectedRevision &&
                                               m_frame.m_editor.at("history").at("undo_count") == m_precisionUndoBefore,
                                           "연구 저장이 직접 설계 개정 또는 명령 이력을 바꿨습니다.");
                              m_setupChecks.push_back("sweep_create_does_not_start_or_change_design");
                              m_setupStage = 7;
                              OpenSweepSmokeDialog();
                          });
    }
    else if (m_setupStage == 9)
    {
        SweepSmokeRequest(
            "sweep.list", Json::object(), false,
            [this](const Json& result)
            {
                CanvasAssert(result.at("studies").size() == 2, "설계/회로 연구가 별도로 저장되지 않았습니다.");
                for (const auto& study : result.at("studies"))
                {
                    if (study.at("type") == "circuit_sweep")
                    {
                        m_sweepCircuitId = study.at("study_id");
                        CanvasAssert(study.at("state") == "ready", "회로 연구 저장이 자동 실행을 시작했습니다.");
                    }
                }
                CanvasAssert(!m_sweepCircuitId.empty(), "새 회로 연구 ID를 찾지 못했습니다.");
                m_setupStage = 10;
                m_frame.m_views->SetSelection(8);
                m_frame.RefreshSweeps(m_sweepCircuitId);
            });
    }
    else if (m_setupStage == 10)
    {
        auto* panel = m_frame.m_sweepPanel;
        CanvasAssert(panel->StudyId() == m_sweepCircuitId && panel->Selection().at("state") == "ready" &&
                         panel->m_actions.at("start")->IsEnabled(),
                     "저장한 회로 연구를 별도로 실행할 수 없습니다.");
        m_setupStage = 11;
        SetupSmoke::Click(panel->m_actions.at("start"));
    }
    else if (m_setupStage == 11)
    {
        auto* panel = m_frame.m_sweepPanel;
        CanvasAssert(panel->Selection().at("state") == "running" && panel->m_actions.at("cancel")->IsEnabled(),
                     "실제 회로 실행 중 취소 상태를 확인하지 못했습니다.");
        m_setupStage = 12;
        SetupSmoke::Click(panel->m_actions.at("cancel"));
    }
    else if (m_setupStage == 12)
    {
        auto* panel = m_frame.m_sweepPanel;
        const auto state = panel->Selection().value("state", "");
        if (state == "cancel_requested" || state == "running")
        {
            return;
        }
        CanvasAssert(state == "cancelled" && panel->m_actions.at("resume")->IsEnabled(),
                     "취소가 완료 후보를 보존한 명시적 재개 상태로 이어지지 않았습니다.");
        m_sweepView = panel->Selection();
        m_setupChecks.push_back("sweep_cancel_preserves_explicit_resume");
        m_setupStage = 13;
        SetupSmoke::Click(panel->m_actions.at("resume"));
    }
    else if (m_setupStage == 13)
    {
        auto* panel = m_frame.m_sweepPanel;
        const auto state = panel->Selection().value("state", "");
        if (state == "running" || state == "resuming")
        {
            return;
        }
        CanvasAssert(state == "completed" && panel->Selection().at("counts").at("completed") == 3 &&
                         panel->Selection().at("budget_usage").at("native_solves") == 0 &&
                         panel->Selection().at("budget_usage").at("wall_seconds").get<double>() >=
                             m_sweepView.at("budget_usage").at("wall_seconds").get<double>(),
                     "회로 재개가 누적 예산/3후보 완료/EM 미실행 상태를 보존하지 못했습니다.");
        m_sweepView = panel->Selection();
        m_setupStage = 14;
        SweepSmokeRequest("sweep.page", {{"study_id", m_sweepCircuitId}, {"offset", 0}, {"limit", 25}}, false,
                          [this](const Json& page)
                          {
                              CanvasAssert(page.at("candidates").size() == 3 &&
                                               page.at("candidates").at(2).at("cached_from_ordinal") == 0 &&
                                               !page.at("candidates").at(0).at("physics_validated").get<bool>(),
                                           "중복 계산 재사용 또는 물리 검증 경계가 기록과 다릅니다.");
                              m_setupStage = 15;
                          });
    }
    else if (m_setupStage == 15)
    {
        m_setupStage = 16;
        SweepSmokeRequest(
            "sweep.result",
            {{"study_id", m_sweepCircuitId}, {"index", 0}, {"offset", 0}, {"limit", 201}, {"row", 0}, {"column", 0}},
            false,
            [this](const Json& result)
            {
                const auto& first = result.at("page").at("samples").at(0);
                CanvasAssert(std::abs(first.at("real").get<double>() - 613.0 / 1513.0) < 1e-12 &&
                                 first.at("frequency_hz") == 1e9 && result.at("descriptor").at("sample_count") == 201,
                             "실제 외부 저항망 계산이 독립 기대 수식과 다릅니다.");
                m_setupChecks.push_back("sweep_real_circuit_completion_and_reuse");
                m_setupStage = 17;
                m_frame.SaveProject();
            });
    }
    else if (m_setupStage == 17 && m_frame.m_savedRevision == m_frame.m_revision)
    {
        CanvasAssert(m_frame.m_revision == m_setupExpectedRevision, "연구 실행이 원본 설계 개정을 바꿨습니다.");
        m_setupStage = 18;
        m_frame.m_connected = false;
        m_frame.m_transportFailed = false;
        m_frame.m_restarting = true;
        m_frame.BeginShutdown();
    }
    else if (m_setupStage == 18)
    {
        CanvasAssert(m_serviceSessions >= 2 && m_frame.m_revision == m_setupExpectedRevision,
                     "연구 저장 후 서비스 재시작이 원본 개정을 유지하지 못했습니다.");
        SweepSmokeRequest(
            "sweep.get", {{"study_id", m_sweepCircuitId}}, false,
            [this](const Json& result)
            {
                CanvasAssert(result.at("state") == "completed" && result.at("counts") == m_sweepView.at("counts") &&
                                 result.at("original_specification") == m_sweepView.at("original_specification"),
                             "재시작한 연구의 완료 이력 또는 원문 정의가 달라졌습니다.");
                m_sweepView = result;
                m_setupChecks.push_back("sweep_saved_service_restart_preserves_history");
                m_setupStage = 19;
                m_frame.m_views->SetSelection(8);
                m_frame.RefreshSweeps(m_sweepCircuitId);
            });
    }
    else if (m_setupStage == 19)
    {
        auto* panel = m_frame.m_sweepPanel;
        CanvasAssert(panel->StudyId() == m_sweepCircuitId && panel->m_candidates->GetItemCount() == 3 &&
                         panel->m_candidates->IsShownOnScreen() &&
                         panel->m_candidates->GetClientSize().y > panel->FromDIP(100),
                     "재열기한 연구 후보 표의 실제 행 또는 표시 높이가 사라졌습니다.");
        CanvasAssert(panel->m_candidates->GetItemText(0, 1).Find("ohm") != wxNOT_FOUND &&
                         panel->Selection().at("physical_validation") == "not_established" &&
                         panel->NavigationView()->IsShown() && panel->ConditionsView()->IsShown(),
                     "연구 원본 단위/검증 상태/탐색 표시가 잘못되었습니다.");
        auto* navigation = dynamic_cast<wxNotebook*>(wxWindow::FindWindowByName("workspace.navigation-tabs", &m_frame));
        const auto buttonPosition = panel->ScreenToClient(panel->m_result->GetScreenPosition());
        const auto buttonSize = panel->m_result->GetSize();
        CanvasAssert(navigation && navigation->GetPageText(0) == Display("연구 목록") &&
                         m_frame.m_manager->GetPane("navigation").caption == Display("연구 목록") &&
                         m_frame.m_manager->GetPane("properties").caption == Display("연구 조건과 출처") &&
                         panel->m_result->IsShownOnScreen() && buttonPosition.x >= 0 &&
                         buttonPosition.x + buttonSize.x <= panel->GetClientSize().x &&
                         buttonSize.x >= panel->m_result->GetBestSize().x,
                     "연구 도킹/탭 제목이 결과 화면으로 남거나 후보 결과 버튼이 가로로 잘렸습니다.");
        m_setupChecks.push_back("sweep_studio_titles_and_result_button");
        panel->m_candidates->SetItemState(0, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED,
                                          wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
        m_setupStage = 20;
        SetupSmoke::Click(panel->m_result);
    }
    else if (m_setupStage == 23)
    {
        auto* panel = m_frame.m_sweepPanel;
        m_frame.NavigateWorkspace(WorkspaceArea::Design);
        CanvasAssert(m_frame.m_views->GetSelection() == 0 && m_frame.m_selection == m_setupShapes &&
                         !panel->NavigationView()->IsShown() && !panel->ConditionsView()->IsShown(),
                     "연구에서 2D 복귀가 원본 선택 또는 탐색 상태를 바꿨습니다.");
        m_setupChecks.push_back("sweep_studio_candidates_and_design_return");
        FinishSmoke(true, "");
    }
}
