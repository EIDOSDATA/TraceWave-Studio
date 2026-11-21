/** @file @brief 실제 규칙 폼, DRC 위치 표시, 이력과 저장 재열기를 검사한다. */
#include "studio_internal.h"
#include "design_rules_dialog.h"
#include "setup_smoke_support.h"

void StudioSmokeDriver::DesignRulesSmokeTick()
{
    auto* dialog = dynamic_cast<DesignRulesDialog*>(m_frame.m_setupDialog);
    if (dialog != nullptr && dialog->m_pending)
    {
        return;
    }
    if (dialog == nullptr)
    {
        if (m_frame.m_busy)
        {
            return;
        }
        if (m_setupStage == 1 || m_setupStage == 13)
        {
            m_setupStage = m_setupStage == 1 ? 2 : 14;
            m_frame.CallAfter([this]()
            {
                wxCommandEvent event(wxEVT_MENU, IdDesignRules);
                m_frame.GetEventHandler()->ProcessEvent(event);
            });
        }
        else if (m_setupStage == 9)
        {
            m_setupStage = 10;
            m_frame.History("project.undo");
        }
        else if (m_setupStage == 10)
        {
            m_setupStage = 11;
            m_frame.History("project.redo");
        }
        else if (m_setupStage == 11)
        {
            m_setupStage = 12;
            m_frame.SaveProject();
        }
        else if (m_setupStage == 12 && m_frame.m_savedRevision == m_frame.m_revision)
        {
            m_setupStage = 13;
            m_frame.OpenProject("open", m_frame.m_path);
        }
        else if (m_setupStage == 16)
        {
            FinishSmoke(true, "");
        }
        return;
    }
    if (m_setupStage == 2)
    {
        const auto& board = dialog->m_context.at("scene").at("board");
        const auto width = board.at("width").get<double>();
        const int pixels = dialog->m_canvas->WorldToScreen({width, 0}).x - dialog->m_canvas->WorldToScreen({0, 0}).x;
        CanvasAssert(pixels >= dialog->m_canvas->GetClientSize().x / 4,
                     "첫 표시의 기판이 검사 캔버스에 맞춰지지 않았습니다.");
        m_setupStage = 3;
        SetupSmoke::Choose(dialog->m_subject, 1);
    }
    else if (m_setupStage == 3)
    {
        CanvasAssert(dialog->m_fields->FieldValue("board_width_max.status") == "estimated", "기존 근사 한계가 표시되지 않았습니다.");
        dialog->m_fields->SetFieldValue("board_width_max.unit", "um");
        dialog->m_reason->SetValue(Display("GUI 단위 표시 변경 시험"));
        m_setupStage = 4;
        SetupSmoke::Click(dialog->m_set);
    }
    else if (m_setupStage == 4)
    {
        CanvasAssert(dialog->m_fields->FieldValue("board_width_max.unit") == "um", "단위 변경이 저장되지 않았습니다.");
        m_setupStage = 5;
        SetupSmoke::Choose(dialog->m_section, 2);
    }
    else if (m_setupStage == 5)
    {
        m_setupStage = 6;
        SetupSmoke::Choose(dialog->m_subject, 1);
    }
    else if (m_setupStage == 6)
    {
        dialog->m_fields->SetFieldValue("kind", "connected");
        dialog->m_reason->SetValue(Display("GUI 기대 연결 변경 시험"));
        m_setupStage = 7;
        SetupSmoke::Click(dialog->m_set);
    }
    else if (m_setupStage == 7)
    {
        CanvasAssert(dialog->m_fields->FieldValue("kind") == "connected", "연결 의도가 반영되지 않았습니다.");
        m_setupStage = 8;
        SetupSmoke::Click(dialog->m_check);
    }
    else if (m_setupStage == 8 || m_setupStage == 15)
    {
        CanvasAssert(!dialog->m_report.is_null(), "현재 개정의 검사 보고서를 받지 못했습니다. " + dialog->m_error.dump());
        const auto& issues = dialog->m_report.at("issues");
        for (const auto* rule : {"board_width_max", "expected_connected", "minimum_clearance", "minimum_tool_hole"})
        {
            const auto found = std::find_if(issues.begin(), issues.end(), [rule](const Json& row)
            {
                return row.at("rule") == rule;
            });
            CanvasAssert(found != issues.end(), std::string("필요한 검사 행이 없습니다: ") + rule);
            if (std::string(rule) == "minimum_clearance")
            {
                const auto index = static_cast<long>(found - issues.begin());
                dialog->m_issues->SetItemState(index, wxLIST_STATE_SELECTED, wxLIST_STATE_SELECTED);
                dialog->ShowIssue(index);
                CanvasAssert(!found->at("location_mm").is_null() && found->at("status") == "failed" &&
                             Utf8(dialog->m_detail->GetValue()).find("시험 카탈로그 규칙") != std::string::npos,
                             "실제 간격 위반 위치/출처가 표시되지 않았습니다.");
            }
        }
        CanvasAssert(dialog->m_issues->GetItemCount() == static_cast<long>(issues.size()), "검사 행이 화면과 일치하지 않습니다.");
        int measuredWidths = 0;
        for (const auto& check : dialog->m_report.at("checks"))
        {
            if (check.at("rule") == "minimum_width" && check.at("status") == "passed" && check.at("measured") == 1.0)
            {
                ++measuredWidths;
            }
        }
        CanvasAssert(measuredWidths == 2, "도체에서 떨어진 홀 때문에 두 선폭 판정이 사라졌습니다.");
        if (m_setupStage == 15)
        {
            m_setupChecks.push_back("mechanical_clearance_preserves_unaffected_trace_width");
        }
        m_setupChecks.push_back(m_setupStage == 8 ? "design_rules_apply_and_overlay" : "design_rules_saved_reopen_and_recheck");
        m_setupStage = m_setupStage == 8 ? 9 : 16;
        dialog->CloseDialog();
    }
    else if (m_setupStage == 14)
    {
        m_setupStage = 15;
        SetupSmoke::Click(dialog->m_check);
    }
}
