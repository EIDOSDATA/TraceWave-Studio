/** @file @brief 문헌/초기식의 실제 GUI 적용과 표시 전용 작업 공간을 통합 검증한다. */
#include "studio_internal.h"
#include "template_dialog.h"
#include "setup_smoke_support.h"
#include "workspace_bar.h"
#include <wx/tglbtn.h>

void StudioSmokeDriver::PrintedSeedSmokeTick()
{
    if (auto* dialog = dynamic_cast<TemplateDialog*>(m_frame.m_setupDialog))
    {
        if (!dialog->m_pending)
        {
            PrintedSeedDialog(*dialog);
        }
        return;
    }
    if (m_frame.m_busy || m_frame.m_cadRestoring || m_frame.m_solverRestoring)
    {
        return;
    }
    if (m_setupStage == 1)
    {
        const std::string revision = m_frame.m_revision;
        const int pages[] = {0, 3, 2, 4, 5};
        for (int index = 0; index < 5; ++index)
        {
            auto* button = dynamic_cast<wxToggleButton*>(wxWindow::FindWindowByName(
                Display("workspace.area." + std::to_string(index)), &m_frame));
            CanvasAssert(button != nullptr && button->IsEnabled(), "작업 영역 이동 버튼이 없습니다.");
            wxCommandEvent event(wxEVT_TOGGLEBUTTON, button->GetId());
            event.SetEventObject(button);
            button->GetEventHandler()->ProcessEvent(event);
            CanvasAssert(m_frame.m_views->GetSelection() == pages[index] && button->GetValue(),
                         "작업 탭과 실제 화면이 다릅니다.");
        }
        m_frame.NavigateWorkspace(WorkspaceArea::Design);
        CanvasAssert(!m_frame.m_workspaceLayerIds.empty(), "표시 레이어 목록이 없습니다.");
        const std::string layer = m_frame.m_workspaceLayerIds.front();
        for (bool visible : {false, true})
        {
            m_frame.m_workspaceBoard->SetValue(visible);
            wxCommandEvent boardEvent(wxEVT_CHECKBOX, m_frame.m_workspaceBoard->GetId());
            boardEvent.SetEventObject(m_frame.m_workspaceBoard);
            m_frame.m_workspaceBoard->GetEventHandler()->ProcessEvent(boardEvent);
            CanvasAssert(m_frame.m_canvas->IsBoardVisible() == visible, "기판 외곽 표시와 캔버스가 다릅니다.");
            m_frame.m_workspaceLayers->Check(0, visible);
            wxCommandEvent event(wxEVT_CHECKLISTBOX, m_frame.m_workspaceLayers->GetId());
            event.SetInt(0);
            event.SetEventObject(m_frame.m_workspaceLayers);
            m_frame.m_workspaceLayers->GetEventHandler()->ProcessEvent(event);
            CanvasAssert(m_frame.m_canvas->IsLayerVisible(layer) == visible, "표시 층과 캔버스가 다릅니다.");
        }
        CanvasAssert(m_frame.m_revision == revision && m_frame.m_workspaceJobs->GetItemCount() == 2,
                     "표시 조작이 원본 개정을 바꾸거나 실제 작업 행이 없습니다.");
        m_setupChecks.push_back("workspace_navigation_and_layer_visibility_without_mutation");
        m_setupStage = 10;
        m_frame.CallAfter([this]()
        {
            m_frame.OpenDesignSetup(true);
        });
    }
    else if (m_setupStage == 30)
    {
        CanvasAssert(m_frame.m_revision == m_setupExpectedRevision && m_frame.m_scene.at("shapes").size() == 7,
                     "문헌 세 카드의 적용 개정/형상 수가 다릅니다.");
        m_setupShapes = m_frame.m_scene.at("shapes");
        m_setupStage = 31;
        m_frame.History("project.undo");
    }
    else if (m_setupStage == 31)
    {
        CanvasAssert(m_frame.m_scene.at("shapes").size() == 6, "초기식 생성이 원자적으로 취소되지 않았습니다.");
        m_setupStage = 32;
        m_frame.History("project.redo");
    }
    else if (m_setupStage == 32)
    {
        CanvasAssert(m_frame.m_scene.at("shapes") == m_setupShapes, "초기식 재실행의 기하가 다릅니다.");
        m_setupChecks.push_back("printed_seed_atomic_undo_redo");
        m_setupStage = 33;
        m_frame.SaveProject();
    }
    else if (m_setupStage == 33)
    {
        CanvasAssert(m_frame.m_savedRevision == m_frame.m_revision, "초기식 결과가 저장되지 않았습니다.");
        m_setupStage = 34;
        m_frame.OpenProject("open", m_frame.m_path);
    }
    else if (m_setupStage == 34)
    {
        CanvasAssert(m_frame.m_scene.at("shapes") == m_setupShapes, "재열기 뒤 문헌 기하가 다릅니다.");
        m_setupChecks.push_back("printed_seed_saved_reopen");
        m_setupStage = 35;
        FinishSmoke(true, "");
    }
}

void StudioSmokeDriver::PrintedSeedDialog(TemplateDialog& dialog)
{
    if (m_setupStage == 10)
    {
        const std::string ids[] = {"literature.g008_an1088_ifa_62mil", "literature.g009_an1088_ifa_08mm",
                                   "literature.g001_nwp008_monopole"};
        int index = 0;
        for (const auto& card : dialog.m_context.at("cards"))
        {
            if (card.at("template_id") == ids[m_printedCase])
            {
                break;
            }
            ++index;
        }
        CanvasAssert(index < static_cast<int>(dialog.m_context.at("cards").size()), "추가 문헌 카드가 없습니다.");
        SetupSmoke::Choose(dialog.m_cards, index);
        SetupSmoke::Choose(dialog.m_binding, 0);
        CanvasAssert(dialog.m_inputs->FieldValue("offset_x") == "", "미정 배치가 자동 확정되었습니다.");
        if (m_printedCase == 2)
        {
            SetupSmoke::Choose(dialog.m_mode, 1);
            SetupSmoke::Choose(dialog.m_seedRecipe, 2);
            {
                SetupSmoke::DiscardHook reject(wxID_NO);
                CanvasAssert(!dialog.Close() && !dialog.m_closed && reject.count == 1,
                             "초기식만 선택한 초안을 확인 없이 닫았습니다.");
            }
            m_setupChecks.push_back("seed_recipe_only_change_requires_discard_confirmation");
            dialog.m_seedInputs->SetFieldValue("frequency.value", "2.4");
            dialog.m_seedInputs->SetFieldValue("assumption", "GUI 시험: 원문 충분한 접지 조건을 가정; 현재 실제 물성 미정");
        }
        else if (m_printedCase == 1)
        {
            CanvasAssert(dialog.CardDescription().find("0.8636") != std::string::npos,
                         "AN1088 원문의 적층 두께 불일치가 표시되지 않았습니다.");
            m_setupChecks.push_back("source_stackup_conflict_visible_without_default");
        }
        dialog.m_inputs->SetFieldValue("offset_x", m_printedCase == 2 ? "30" : "2");
        dialog.m_inputs->SetFieldValue("offset_y", m_printedCase == 0 ? "40" : (m_printedCase == 1 ? "25" : "5"));
        m_setupExpectedRevision = dialog.m_revision;
        m_setupStage = 11;
        SetupSmoke::Click(dialog.m_previewButton);
    }
    else if (m_setupStage == 11 && m_printedCase == 2)
    {
        CanvasAssert(!dialog.m_preview.is_null() && !dialog.m_preview.value("can_apply", true) &&
                         !dialog.m_applyButton->IsEnabled() && dialog.m_revision == m_setupExpectedRevision,
                     "원문 범위 밖 초기식이 차단되지 않았습니다.");
        dialog.m_seedInputs->SetFieldValue("frequency.value", "2.45");
        SetupSmoke::Choose(dialog.m_mode, 0);
        CanvasAssert(dialog.m_inputs->FieldValue("length") == "23", "명시/추정 길이 초안이 혼합되었습니다.");
        SetupSmoke::Choose(dialog.m_mode, 1);
        CanvasAssert(dialog.m_seedInputs->FieldValue("frequency.value") == "2.45" &&
                         dialog.m_inputs->FieldValue("offset_x") == "30" && dialog.m_seedRecipe->GetSelection() == 2,
                     "초기식 방식 전환이 입력 초안을 잃었습니다.");
        m_setupChecks.push_back("seed_scope_block_and_separate_mode_drafts");
        m_setupStage = 12;
        SetupSmoke::Click(dialog.m_previewButton);
    }
    else if (m_setupStage == 11 || m_setupStage == 12 || m_setupStage == 16)
    {
        CanvasAssert(!dialog.m_preview.is_null() && dialog.m_preview.value("can_apply", false),
                     "문헌 후보 생성 실패: " + dialog.m_preview.dump());
        const auto& generation = dialog.m_preview.at("generation");
        CanvasAssert(generation.at("analysis") == "not_performed" && generation.at("measurement") == "not_verified",
                     "기하 생성이 RF 검증으로 승격되었습니다.");
        if (m_printedCase == 2)
        {
            CanvasAssert(dialog.m_preview.at("initial_estimate").at("length").at("status") == "estimated" &&
                             !dialog.m_preview.at("initial_estimate").at("conditions_verified").get<bool>(),
                         "초기 추정/조건 가정이 구분되지 않았습니다.");
            if (m_setupStage == 12)
            {
                SetupSmoke::Choose(dialog.m_seedRecipe, 1);
                CanvasAssert(dialog.m_preview.is_null() && !dialog.m_applyButton->IsEnabled(),
                             "초기식 변경이 이전 검토 후보를 폐기하지 않았습니다.");
                SetupSmoke::Choose(dialog.m_seedRecipe, 2);
                m_setupStage = 16;
                SetupSmoke::Click(dialog.m_previewButton);
                return;
            }
            m_setupChecks.push_back("estimated_seed_and_late_preview_invalidation");
        }
        m_setupStage = 14;
        SetupSmoke::Click(dialog.m_applyButton);
    }
    else if (m_setupStage == 14)
    {
        CanvasAssert(dialog.m_context.at("instances").size() == static_cast<std::size_t>(m_printedCase + 1) &&
                         dialog.m_revision != m_setupExpectedRevision, "문헌 카드가 한 명령으로 적용되지 않았습니다.");
        ++m_printedCase;
        if (m_printedCase < 3)
        {
            m_setupStage = 10;
        }
        else
        {
            m_setupExpectedRevision = dialog.m_revision;
            m_setupChecks.push_back("three_printed_cards_applied_without_physical_defaults");
            m_setupStage = 30;
            SetupSmoke::DiscardHook discard(wxID_YES);
            SetupSmoke::Click(dialog.m_cancel);
        }
    }
}
