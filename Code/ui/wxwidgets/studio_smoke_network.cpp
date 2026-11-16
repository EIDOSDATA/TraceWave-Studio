/** @file @brief 실제 가져오기/RLC/평가 창과 저장/서비스 재시작을 연결하여 검사한다. */
#include "studio_internal.h"
#include "network_import_dialog.h"
#include "network_circuit_dialog.h"
#include "network_assessment_dialog.h"
#include "network_transform_dialog.h"
#include "network_export.h"
#include "network_panel.h"
#include "network_assessment_panel.h"
#include "workspace_bar.h"
#include "setup_smoke_support.h"
#include <wx/grid.h>

namespace
{
/** @brief 체크 상자의 값과 제품 변경 이벤트를 함께 전달한다. */
void Check(wxCheckBox* control, bool value)
{
    control->SetValue(value);
    wxCommandEvent event(wxEVT_CHECKBOX, control->GetId());
    event.SetEventObject(control);
    control->GetEventHandler()->ProcessEvent(event);
}
}

void StudioSmokeDriver::OpenNetworkSmokeDialog(int kind)
{
    m_networkAwaiting = true;
    m_frame.m_busy = true;
    m_frame.UpdateControls();
    const auto failed = [this](const Json& error)
    {
        m_networkAwaiting = false;
        FinishSmoke(false, DiagnosticMessage(error));
    };
    m_frame.Send(
        "network.library", {{"expected_revision", m_frame.m_revision}}, false, m_frame.Context(),
        [this, kind, failed](const Json& context)
        {
            m_networkContext = context;
            const auto show = [this, kind, context](const Json& selection)
            {
                m_frame.CallAfter(
                    [this, kind, context, selection]()
                    {
                        try
                        {
                            if (kind == 0 && m_setupStage == 2)
                            {
                                NetworkImportSafetyChecks(context);
                            }
                            std::unique_ptr<ProjectSetupDialog> dialog;
                            if (kind == 0)
                            {
                                dialog = std::make_unique<NetworkImportDialog>(&m_frame, context,
                                                                               m_frame.ObjectToolGateway());
                            }
                            else if (kind == 1)
                            {
                                dialog = std::make_unique<NetworkCircuitDialog>(&m_frame, context, selection,
                                                                                m_frame.ObjectToolGateway());
                            }
                            else if (kind == 2)
                            {
                                dialog = std::make_unique<NetworkAssessmentDialog>(&m_frame, context, selection,
                                                                                   m_frame.ObjectToolGateway());
                            }
                            else
                            {
                                dialog = std::make_unique<NetworkTransformDialog>(&m_frame, context, selection,
                                                                                  m_frame.ObjectToolGateway());
                            }
                            m_networkAwaiting = false;
                            m_frame.ShowObjectTool(std::move(dialog), m_frame.m_selection);
                        }
                        catch (const std::exception& error)
                        {
                            m_networkAwaiting = false;
                            FinishSmoke(false, error.what());
                        }
                    });
            };
            if (kind == 0)
            {
                show(nullptr);
            }
            else
            {
                const auto& identity = kind == 2 ? m_networkDerivedId : m_networkImportedId;
                m_frame.Send("network.get",
                             {{"expected_revision", m_frame.m_revision},
                              {"dataset_id", identity},
                              {"offset", 0},
                              {"limit", 201},
                              {"row", 0},
                              {"column", 0}},
                             false, m_frame.Context(), show, failed);
            }
        },
        failed);
}

void StudioSmokeDriver::NetworkSmokeTick()
{
    if (m_networkAwaiting)
    {
        return;
    }
    auto* importing = dynamic_cast<NetworkImportDialog*>(m_frame.m_setupDialog);
    auto* circuit = dynamic_cast<NetworkCircuitDialog*>(m_frame.m_setupDialog);
    auto* assessment = dynamic_cast<NetworkAssessmentDialog*>(m_frame.m_setupDialog);
    auto* transform = dynamic_cast<NetworkTransformDialog*>(m_frame.m_setupDialog);
    if (m_frame.m_setupDialog && m_frame.m_setupDialog->m_pending)
    {
        return;
    }
    const auto file = [this](const char* name)
    {
        return wxFileName(m_frame.m_options.workspace, Display(name)).GetFullPath();
    };
    if (importing)
    {
        if (m_setupStage == 2)
        {
            CanvasAssert(importing->LoadFile(file("GUI 거절.s1p")), "거절용 원문을 읽지 못했습니다.");
            m_setupStage = 3;
            SetupSmoke::Click(importing->m_preview);
        }
        else if (m_setupStage == 3)
        {
            CanvasAssert(!importing->m_review.is_null() && !importing->m_review.value("can_apply", true) &&
                             !importing->m_disconnected && importing->m_preview->IsEnabled() &&
                             !importing->m_apply->IsEnabled(),
                         "잘못된 원문 후보를 복구 가능한 입력 오류로 처리하지 못했습니다.");
            m_setupChecks.push_back("network_invalid_source_keeps_draft_editable");
            CanvasAssert(importing->LoadFile(file("GUI 원문.s1p")), "복소 원문을 읽지 못했습니다.");
            importing->m_name->SetValue(Display("GUI 초안 자료"));
            m_setupStage = 4;
            SetupSmoke::Click(importing->m_preview);
        }
        else if (m_setupStage == 4)
        {
            CanvasAssert(importing->m_review.value("can_apply", false) && importing->m_samples->GetItemCount() == 3 &&
                             importing->m_sourceDescriptor.at("reference_planes").at(0).is_null() &&
                             importing->m_sourceDescriptor.at("phasor_convention") == "unknown",
                         "원문의 미정 조건을 추정했습니다.");
            wxListItem frequencyColumn;
            frequencyColumn.SetMask(wxLIST_MASK_TEXT);
            importing->m_samples->GetColumn(0, frequencyColumn);
            CanvasAssert(importing->m_samples->GetItemText(0) == "1" &&
                             frequencyColumn.GetText().Find("GHz") != wxNOT_FOUND &&
                             importing->m_summary->GetValue().Find("GHz") != wxNOT_FOUND &&
                             importing->m_review.at("page").at("samples").at(0).at("frequency_hz") == 1e9,
                         "가져오기 검토에서 원본 1e9 Hz와 화면 1 GHz 표시가 일치하지 않습니다.");
            importing->m_name->SetValue(Display("GUI 신규 복소 자료"));
            CanvasAssert(importing->m_review.is_null() && !importing->m_apply->IsEnabled(),
                         "입력 변경이 검토를 무효화하지 않았습니다.");
            SetupSmoke::Choose(importing->m_wave, 4);
            SetupSmoke::Choose(importing->m_phasor, 2);
            SetupSmoke::Choose(importing->m_ports[0].project, 1);
            SetupSmoke::Choose(importing->m_ports[0].orientation, 2);
            Check(importing->m_ports[0].planeChanged, true);
            importing->m_ports[0].plane->SetValue(Display("시험 기준면"));
            m_setupChecks.push_back("network_unknown_preview_and_input_invalidation");
            m_setupStage = 5;
            SetupSmoke::Click(importing->m_preview);
        }
        else if (m_setupStage == 5)
        {
            CanvasAssert(importing->m_review.value("can_apply", false), "명시 조건 후보를 만들지 못했습니다.");
            m_networkImportedId = importing->m_review.at("record_id");
            m_setupStage = 6;
            SetupSmoke::Click(importing->m_apply);
            CanvasAssert(!importing->m_apply->IsEnabled(), "가져오기 적용 중 중복 요청이 가능합니다.");
        }
        else if (m_setupStage == 18)
        {
            CanvasAssert(importing->LoadFile(file("GUI 열 대응.csv")), "CSV 원문을 읽지 못했습니다.");
            importing->m_name->SetValue(Display("GUI 미정 CSV"));
            importing->Preview();
            CanvasAssert(importing->m_review.is_null() && !importing->m_pending &&
                             !importing->m_mappingConfirmed->GetValue(),
                         "확인하지 않은 CSV 기본 열 대응을 전송했습니다.");
            SetupSmoke::Choose(importing->m_frequencyUnit, 3);
            importing->m_ignored->SetValue("3");
            Check(importing->m_mappingConfirmed, true);
            m_setupStage = 19;
            SetupSmoke::Click(importing->m_preview);
        }
        else if (m_setupStage == 19)
        {
            CanvasAssert(importing->m_review.value("can_apply", false) &&
                             importing->m_review.at("descriptor").at("z0_ohm").is_null() &&
                             importing->m_review.at("descriptor").at("reference_planes").at(0).is_null() &&
                             importing->m_review.at("page").at("samples").at(0).at("frequency_hz") == 1e9,
                         "명시 CSV 단위 해석 또는 미정 조건 보존이 다릅니다.");
            m_setupChecks.push_back("network_csv_explicit_mapping_preserves_unknown");
            m_setupStage = 20;
            SetupSmoke::Click(importing->m_apply);
        }
        return;
    }
    if (circuit)
    {
        if (m_setupStage == 9)
        {
            circuit->AddElement("series");
            circuit->m_name->SetValue(Display("GUI 외부 RLC"));
            circuit->m_inputPlane->SetValue(Display("입력 기준면"));
            circuit->m_loadPlane->SetValue(Display("시험 기준면"));
            m_setupStage = 10;
            SetupSmoke::Click(circuit->m_reviewDefinition);
        }
        else if (m_setupStage == 10)
        {
            CanvasAssert(circuit->m_review.value("can_apply", false) &&
                             circuit->m_elements.at(0).at("value").at("value_si").is_null(),
                         "빈 RLC 수치를 미정 정의로 검토하지 못했습니다.");
            circuit->m_value->SetValue("50");
            CanvasAssert(circuit->m_review.is_null(), "RLC 수치 변경 후 이전 후보가 남았습니다.");
            m_setupChecks.push_back("network_rlc_missing_value_and_review_invalidation");
            m_setupStage = 11;
            SetupSmoke::Click(circuit->m_reviewDefinition);
        }
        else if (m_setupStage == 11)
        {
            CanvasAssert(circuit->m_review.value("can_apply", false), "명시 RLC 저장 후보가 없습니다.");
            m_setupStage = 12;
            SetupSmoke::Click(circuit->m_apply);
        }
        else if (m_setupStage == 12)
        {
            CanvasAssert(!circuit->m_savedCircuitId.empty() && !circuit->m_dirty &&
                             circuit->m_reviewCalculation->IsEnabled(),
                         "RLC 저장 후 동일 회로의 결합 검토로 진행하지 못했습니다.");
            m_networkCircuitId = circuit->m_savedCircuitId;
            circuit->m_resultName->SetValue(Display("GUI RLC 결합"));
            m_setupStage = 13;
            SetupSmoke::Click(circuit->m_reviewCalculation);
        }
        else if (m_setupStage == 13)
        {
            CanvasAssert(circuit->m_review.value("can_apply", false) &&
                             std::abs(circuit->m_review.at("page").at("samples").at(0).at("real").get<double>() -
                                      11.0 / 29.0) < 1e-10 &&
                             circuit->m_review.at("descriptor").at("reference_planes").at(0) == "입력 기준면",
                         "직렬 50 ohm 결합의 독립 기대값과 다릅니다.");
            m_networkDerivedId = circuit->m_review.at("record_id");
            m_setupChecks.push_back("network_rlc_saved_definition_and_derived_candidate");
            m_setupStage = 14;
            SetupSmoke::Click(circuit->m_apply);
        }
        return;
    }
    if (assessment)
    {
        if (m_setupStage == 15)
        {
            assessment->m_name->SetValue(Display("GUI 목표 평가"));
            assessment->m_plane->SetValue(Display("입력 기준면"));
            m_setupStage = 16;
            SetupSmoke::Click(assessment->m_preview);
        }
        else if (m_setupStage == 16)
        {
            CanvasAssert(assessment->m_review.value("can_apply", false) &&
                             !assessment->m_review.at("assessment").at("physics_validated").get<bool>() &&
                             !assessment->m_review.at("assessment").at("continuous_band_verified").get<bool>(),
                         "표본 평가를 연속 대역/실물 검증으로 확대했습니다.");
            m_networkAssessmentId = assessment->m_review.at("record_id");
            m_setupChecks.push_back("network_target_assessment_preserves_validation_boundary");
            m_setupStage = 17;
            SetupSmoke::Click(assessment->m_apply);
        }
        return;
    }
    if (transform)
    {
        if (m_setupStage == 24)
        {
            transform->m_name->SetValue(Display("GUI Z 변환"));
            SetupSmoke::Choose(transform->m_kind, 1);
            m_setupStage = 25;
            SetupSmoke::Click(transform->m_preview);
        }
        else if (m_setupStage == 25)
        {
            CanvasAssert(transform->m_review.value("can_apply", false) &&
                             transform->m_review.at("descriptor").at("parameter_kind") == "Z" &&
                             std::abs(transform->m_review.at("page").at("samples").at(0).at("real").get<double>() -
                                      550.0 / 9.0) < 1e-10,
                         "명시 S->Z 변환의 독립 기대값과 다릅니다.");
            m_setupChecks.push_back("network_explicit_s_to_z_preserves_source");
            m_setupStage = 26;
            SetupSmoke::Click(transform->m_apply);
        }
        return;
    }
    if (m_frame.m_busy || m_frame.m_cadRestoring || m_frame.m_solverRestoring)
    {
        return;
    }
    if (m_setupStage == 1)
    {
        m_precisionUndoBefore = m_frame.m_editor.at("history").at("undo_count");
        m_setupStage = 2;
        OpenNetworkSmokeDialog(0);
    }
    else if (m_setupStage == 6)
    {
        CanvasAssert(m_frame.m_editor.at("history").at("undo_count").get<int>() == m_precisionUndoBefore + 1,
                     "가져오기가 단일 이력이 아닙니다.");
        m_setupStage = 7;
        m_frame.History("project.undo");
    }
    else if (m_setupStage == 7)
    {
        m_networkAwaiting = true;
        m_frame.Send(
            "network.library", {{"expected_revision", m_frame.m_revision}}, false, m_frame.Context(),
            [this](const Json& result)
            {
                CanvasAssert(result.at("datasets").size() == 1, "실행 취소가 신규 자료만 회수하지 못했습니다.");
                m_networkAwaiting = false;
                m_setupStage = 8;
                m_frame.History("project.redo");
            },
            [this](const Json& error)
            {
                FinishSmoke(false, DiagnosticMessage(error));
            });
    }
    else if (m_setupStage == 8)
    {
        m_setupChecks.push_back("network_import_single_command_undo_redo");
        m_setupStage = 9;
        OpenNetworkSmokeDialog(1);
    }
    else if (m_setupStage == 14)
    {
        CanvasAssert(m_frame.m_editor.at("history").at("undo_count").get<int>() == m_precisionUndoBefore + 3,
                     "회로 정의와 파생 자료의 독립 이력이 다릅니다.");
        m_setupStage = 15;
        OpenNetworkSmokeDialog(2);
    }
    else if (m_setupStage == 17)
    {
        m_setupStage = 24;
        OpenNetworkSmokeDialog(3);
    }
    else if (m_setupStage == 26)
    {
        m_setupStage = 18;
        OpenNetworkSmokeDialog(0);
    }
    else if (m_setupStage == 20)
    {
        CanvasAssert(m_frame.m_editor.at("history").at("undo_count").get<int>() == m_precisionUndoBefore + 6,
                     "가져오기/회로/평가/CSV의 원자 이력 수가 다릅니다.");
        m_setupStage = 21;
        m_frame.SaveProject();
    }
    else if (m_setupStage == 21 && m_frame.m_savedRevision == m_frame.m_revision)
    {
        m_setupStage = 22;
        m_frame.m_connected = false;
        m_frame.m_transportFailed = false;
        m_frame.m_restarting = true;
        m_frame.BeginShutdown();
    }
    else if (m_setupStage == 22)
    {
        CanvasAssert(m_serviceSessions >= 2 && m_frame.m_savedRevision == m_frame.m_revision,
                     "저장 개정으로 서비스를 재시작하지 못했습니다.");
        m_networkAwaiting = true;
        m_frame.Send(
            "network.library", {{"expected_revision", m_frame.m_revision}}, false, m_frame.Context(),
            [this](const Json& result)
            {
                CanvasAssert(result.at("datasets").size() == 5 && result.at("circuits").size() == 1 &&
                                 result.at("assessments").size() == 1,
                             "재시작한 자료/회로/평가 목록이 다릅니다.");
                m_setupChecks.push_back("network_saved_service_restart_preserves_library");
                m_setupShapes = m_frame.m_selection;
                m_networkAwaiting = false;
                m_setupStage = 27;
                m_frame.m_networkPreferredId = m_networkImportedId;
                m_frame.m_views->SetSelection(6);
                m_frame.RefreshNetwork(m_networkImportedId);
            },
            [this](const Json& error)
            {
                FinishSmoke(false, DiagnosticMessage(error));
            });
    }
    else if (m_setupStage == 27)
    {
        if (m_frame.m_networkPending || m_frame.m_networkRefreshQueued)
        {
            return;
        }
        auto* panel = m_frame.m_networkPanel;
        CanvasAssert(m_frame.m_views->GetSelection() == 6 && panel->DatasetId() == m_networkImportedId &&
                         panel->Selection().is_object() && panel->m_samples->GetItemCount() == 3 &&
                         panel->NavigationView()->IsShown() && panel->ConditionsView()->IsShown() &&
                         !m_frame.m_tree->IsShown(),
                     "주 결과 화면의 목록/실제 표본/조건 전환이 일치하지 않습니다.");
        const Json originalSelection = panel->Selection();
        const auto originalRevision = m_frame.m_revision;
        const Json originalHistory = m_frame.m_editor.at("history");
        wxListItem frequencyColumn;
        frequencyColumn.SetMask(wxLIST_MASK_TEXT);
        panel->m_samples->GetColumn(1, frequencyColumn);
        CanvasAssert(panel->m_samples->GetItemText(0, 1) == "1" && frequencyColumn.GetText().Find("GHz") != wxNOT_FOUND,
                     "주 결과의 자동 주파수 표시가 1 GHz가 아닙니다.");
        SetupSmoke::Choose(panel->m_frequencyUnit, 3);
        panel->m_samples->GetColumn(1, frequencyColumn);
        CanvasAssert(panel->m_samples->GetItemText(0, 1) == "1000" &&
                         frequencyColumn.GetText().Find("MHz") != wxNOT_FOUND,
                     "MHz 표시 선택이 원본 1 GHz를 1000 MHz로 표시하지 않았습니다.");
        SetupSmoke::Choose(panel->m_frequencyUnit, 4);
        panel->m_samples->GetColumn(1, frequencyColumn);
        CanvasAssert(panel->m_samples->GetItemText(0, 1) == "1" &&
                         frequencyColumn.GetText().Find("GHz") != wxNOT_FOUND &&
                         panel->Selection() == originalSelection && m_frame.m_revision == originalRevision &&
                         m_frame.m_editor.at("history") == originalHistory && !m_frame.m_networkPending,
                     "주파수 표시 단위 변경이 원본 SI 자료 또는 프로젝트 개정/이력을 바꿨습니다.");
        m_setupChecks.push_back("network_frequency_units_preserve_si_and_revision");
        wxListEvent selected(wxEVT_LIST_ITEM_SELECTED, panel->m_samples->GetId());
        selected.SetIndex(0);
        selected.SetEventObject(panel->m_samples);
        panel->m_samples->GetEventHandler()->ProcessEvent(selected);
        CanvasAssert(panel->m_marker->GetLabel().Find("M1") != wxNOT_FOUND && panel->DatasetId() == m_networkImportedId,
                     "실제 표본 마커가 표시되지 않거나 자료 선택을 변경했습니다.");
        m_frame.NavigateWorkspace(WorkspaceArea::Design);
        CanvasAssert(m_frame.m_views->GetSelection() == 0 && m_frame.m_selection == m_setupShapes &&
                         !panel->NavigationView()->IsShown() && m_frame.m_tree->IsShown(),
                     "2D 복귀가 원본 선택 또는 탐색 상태를 바꿨습니다.");
        m_setupChecks.push_back("network_studio_results_marker_and_design_return");
        m_setupStage = 28;
        m_frame.m_views->SetSelection(6);
        m_frame.m_views->SetSelection(7);
        m_frame.UpdateNetworkViews();
    }
    else if (m_setupStage == 28)
    {
        if (m_frame.m_networkPending || m_frame.m_networkRefreshQueued)
        {
            return;
        }
        auto* panel = m_frame.m_networkAssessmentPanel;
        CanvasAssert(panel->Selection().is_object() && panel->AssessmentId() == m_networkAssessmentId &&
                         panel->Selection().at("entry").at("id") == m_networkAssessmentId &&
                         panel->Selection().at("entry").at("dataset_id") == m_networkDerivedId &&
                         panel->m_dataset.at("entry").at("id") == m_networkDerivedId &&
                         m_frame.m_networkPanel->DatasetId() == m_networkDerivedId &&
                         panel->m_criteria->GetItemCount() > 0 && panel->m_pointsPreview &&
                         panel->NavigationView()->IsShown() && panel->ConditionsView()->IsShown() &&
                         !m_frame.m_networkPanel->NavigationView()->IsShown() &&
                         !panel->Selection().at("assessment").at("physics_validated").get<bool>() &&
                         !panel->Selection().at("assessment").at("continuous_band_verified").get<bool>(),
                     "주 목표 평가의 원본 연결/판정/미확립 상태가 일치하지 않습니다.");
        m_setupStage = 29;
        SetupSmoke::Click(panel->m_allPoints);
    }
    else if (m_setupStage == 29)
    {
        if (m_frame.m_networkPending || m_frame.m_networkRefreshQueued)
        {
            return;
        }
        auto* panel = m_frame.m_networkAssessmentPanel;
        CanvasAssert(!panel->m_pointsPreview && panel->m_points->GetItemCount() == 3 && panel->CriterionIndex() == 0 &&
                         panel->AssessmentId() == m_networkAssessmentId,
                     "선택한 목표 평가의 실제 표본을 읽지 못했습니다.");
        wxListItem frequencyColumn;
        frequencyColumn.SetMask(wxLIST_MASK_TEXT);
        panel->m_points->GetColumn(0, frequencyColumn);
        CanvasAssert(panel->m_points->GetItemText(0) == "1" && frequencyColumn.GetText().Find("GHz") != wxNOT_FOUND,
                     "저장된 목표 평가의 표본이 1 GHz 표시와 일치하지 않습니다.");
        CanvasAssert(panel->m_points->IsShownOnScreen() && panel->m_points->GetClientSize().y > panel->FromDIP(80),
                     "목표 평가 표본 표의 표시 높이가 사라졌습니다.");
        if (panel->GetVirtualSize().y > panel->GetClientSize().y)
        {
            int horizontalUnit = 0;
            int verticalUnit = 0;
            panel->GetScrollPixelsPerUnit(&horizontalUnit, &verticalUnit);
            CanvasAssert(verticalUnit > 0, "부족한 목표 평가 화면을 세로로 스크롤할 수 없습니다.");
            const auto position = panel->CalcUnscrolledPosition(panel->m_points->GetPosition());
            panel->Scroll(0, position.y / verticalUnit);
            const auto visible = panel->m_points->GetScreenRect().Intersect(panel->GetScreenRect());
            CanvasAssert(panel->GetViewStart().y > 0 && visible.GetHeight() > panel->FromDIP(80),
                         "스크롤한 목표 평가의 실제 표본에 접근할 수 없습니다.");
        }
        CanvasAssert(m_networkImportedId != m_networkDerivedId, "평가 화면 복귀 시험의 두 자료가 구분되지 않습니다.");
        m_frame.m_views->SetSelection(6);
        m_frame.UpdateNetworkViews();
        auto* results = m_frame.m_networkPanel;
        const long selected = results->m_results->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
        const long focused = results->m_results->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_FOCUSED);
        CanvasAssert(selected >= 0 && selected == focused && results->m_results->GetSelectedItemCount() == 1 &&
                         results->m_ids.at(static_cast<std::size_t>(selected)) == m_networkDerivedId &&
                         results->DatasetId() == m_networkDerivedId && results->NavigationView()->IsShown(),
                     "평가 원본으로 전환한 뒤 결과 목록의 선택/초점과 실제 자료가 다릅니다.");
        m_frame.NavigateWorkspace(WorkspaceArea::Design);
        CanvasAssert(m_frame.m_views->GetSelection() == 0 && m_frame.m_selection == m_setupShapes &&
                         !panel->NavigationView()->IsShown() && !panel->ConditionsView()->IsShown() &&
                         m_frame.m_tree->IsShown(),
                     "목표 평가에서 2D로 복귀하며 설계 선택이 변경되었습니다.");
        m_setupChecks.push_back("network_studio_assessment_source_points_and_design_return");
        m_networkAwaiting = true;
        m_frame.Send(
            "network.export",
            {{"expected_revision", m_frame.m_revision}, {"dataset_id", m_networkImportedId}, {"format", "hdf5"}}, false,
            m_frame.Context(),
            [this](const Json& exported)
            {
                const std::filesystem::path workspace(m_frame.m_options.workspace.ToStdWstring());
                const auto path = workspace.parent_path() / std::filesystem::u8path("GUI 교환.h5");
                WriteNetworkExportFiles(exported, wxString(path.native()), m_frame.m_options.workspace);
                int rejected = 0;
                for (const auto& target : {path, workspace / "source.h5"})
                {
                    try
                    {
                        WriteNetworkExportFiles(exported, wxString(target.native()), m_frame.m_options.workspace);
                    }
                    catch (const std::exception&)
                    {
                        ++rejected;
                    }
                }
                CanvasAssert(
                    rejected == 2 && std::filesystem::file_size(path) == exported.at("bytes").get<std::size_t>() &&
                        std::filesystem::is_regular_file(std::filesystem::path(path.native() + L".conditions.json")),
                    "교환 파일 쌍의 저장 또는 원본/기존 파일 보호가 다릅니다.");
                m_setupChecks.push_back("network_export_pair_and_existing_workspace_protection");
                m_networkAwaiting = false;
                m_setupStage = 23;
                FinishSmoke(true, "");
            },
            [this](const Json& error)
            {
                FinishSmoke(false, DiagnosticMessage(error));
            });
    }
}
