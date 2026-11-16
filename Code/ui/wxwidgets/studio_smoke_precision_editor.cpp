/** @file @brief 실제 이름/정밀 편집 대화상자와 서비스의 실패 복구 및 저장 경계를 검사한다. */
#include "studio_internal.h"
#include "object_rename_dialog.h"
#include "precision_dialog.h"
#include "setup_smoke_support.h"
#include "studio_shell.h"
#include <wx/srchctrl.h>

namespace
{
/** @brief 서비스가 반환한 작업 식별자로 native 선택 이벤트를 발생시킨다. */
int FindRow(const Json& rows, const std::string& field, const std::string& value)
{
    for (std::size_t index = 0; index < rows.size(); ++index)
    {
        if (rows.at(index).value(field, "") == value)
        {
            return static_cast<int>(index);
        }
    }
    throw std::runtime_error("정밀 편집 시험 항목이 없습니다: " + value);
}
}

void StudioSmokeDriver::PrecisionEditorSmokeTick()
{
    if (m_frame.m_options.precisionPlanarSmoke)
    {
        PrecisionPlanarSmokeTick();
        return;
    }
    auto* rename = dynamic_cast<ObjectRenameDialog*>(m_frame.m_setupDialog);
    auto* precision = dynamic_cast<PrecisionDialog*>(m_frame.m_setupDialog);
    if ((rename != nullptr && rename->m_pending) || (precision != nullptr && precision->m_pending))
    {
        return;
    }
    if (rename != nullptr)
    {
        if (m_setupStage == 3)
        {
            rename->m_name->SetValue(Display("중복 이름"));
            m_setupStage = 4;
            SetupSmoke::Click(rename->m_apply);
        }
        else if (m_setupStage == 4)
        {
            CanvasAssert(!rename->m_error.is_null() && rename->m_name->GetValue() == Display("중복 이름") &&
                             rename->m_apply->IsEnabled() && !rename->m_disconnected &&
                             m_frame.m_revision == m_setupExpectedRevision,
                         "이름 중복 거절 뒤 초안/개정/재입력 가능 상태가 보존되지 않았습니다.");
            m_setupChecks.push_back("rename_duplicate_rejection_keeps_draft");
            rename->m_name->SetValue(Display("급전 선 검증"));
            m_setupStage = 5;
            SetupSmoke::Click(rename->m_apply);
            CanvasAssert(!rename->m_apply->IsEnabled(), "이름 적용 중 중복 요청이 허용됩니다.");
        }
        return;
    }
    if (precision != nullptr)
    {
        if (m_setupStage == 6)
        {
            const double width = precision->m_originalScene.at("board").at("width");
            const int pixels = precision->m_canvas->WorldToScreen({width, 0}).x - precision->m_canvas->WorldToScreen({0, 0}).x;
            CanvasAssert(pixels >= precision->m_canvas->GetClientSize().x / 4,
                         "정밀 편집 첫 장면이 최종 캔버스 크기에 맞춰지지 않았습니다.");
            SetupSmoke::Choose(precision->m_operation, FindRow(precision->m_context.at("operations"), "id", "dimension_set"));
            SetupSmoke::Choose(precision->m_dimension, FindRow(precision->m_context.at("dimensions"), "key", "line.length"));
            precision->m_numbers.at("value")->SetValue("0");
            m_setupStage = 7;
            SetupSmoke::Click(precision->m_preview);
        }
        else if (m_setupStage == 7)
        {
            CanvasAssert(!precision->m_review.is_null() && !precision->m_review.at("can_apply").get<bool>() &&
                             precision->m_review.at("scene").is_null() && precision->m_preview->IsEnabled() &&
                             !precision->m_apply->IsEnabled() && !precision->m_disconnected &&
                             m_frame.m_scene.at("shapes") == m_precisionBeforeShapes,
                         "적용 불가/null 장면 후보에서 편집을 복구하지 못했습니다.");
            m_setupChecks.push_back("precision_null_scene_keeps_original_and_recovers");
            precision->m_numbers.at("value")->SetValue("7.5");
            m_setupStage = 8;
            SetupSmoke::Click(precision->m_preview);
        }
        else if (m_setupStage == 8)
        {
            CanvasAssert(precision->m_apply->IsEnabled() && precision->m_review.at("review_hash").get<std::string>().size() == 64 &&
                             m_frame.m_scene.at("shapes") == m_precisionBeforeShapes,
                         "읽기 전용 후보가 원본을 바꾸었거나 검토 해시가 없습니다.");
            precision->m_numbers.at("value")->SetValue("8");
            CanvasAssert(precision->m_review.is_null() && !precision->m_apply->IsEnabled(),
                         "입력 변경 후 오래된 후보를 적용할 수 있습니다.");
            m_setupChecks.push_back("precision_input_change_invalidates_review");
            m_setupStage = 9;
            SetupSmoke::Click(precision->m_preview);
        }
        else if (m_setupStage == 9)
        {
            CanvasAssert(precision->m_review.at("can_apply").get<bool>(), "수정한 치수 후보가 거절되었습니다.");
            const int index = FindRow(precision->m_review.at("dimensions"), "key", "line.length");
            CanvasAssert(std::abs(precision->m_review.at("dimensions").at(index).at("value").get<double>() - 8.0) < 1e-9,
                         "서비스 치수 후보가 명시한 8 mm와 다릅니다.");
            m_setupStage = 10;
            SetupSmoke::Click(precision->m_apply);
            CanvasAssert(!precision->m_apply->IsEnabled(), "정밀 적용 중 중복 요청이 허용됩니다.");
        }
        else if (m_setupStage == 11)
        {
            SetupSmoke::Choose(precision->m_operation, FindRow(precision->m_context.at("operations"), "id", "rotate"));
            precision->m_numbers.at("pivot_x_mm")->SetValue("8");
            precision->m_numbers.at("pivot_y_mm")->SetValue("6");
            precision->m_numbers.at("angle_deg")->SetValue("180");
            m_setupStage = 12;
            SetupSmoke::Click(precision->m_preview);
        }
        else if (m_setupStage == 12)
        {
            CanvasAssert(precision->m_review.at("can_apply").get<bool>() &&
                             m_frame.m_scene.at("shapes") == m_precisionDimensionShapes,
                         "회전 후보가 원본을 변경하거나 계산되지 않았습니다.");
            m_setupStage = 13;
            SetupSmoke::Click(precision->m_apply);
        }
        else if (m_setupStage == 21)
        {
            SetupSmoke::Choose(precision->m_operation, FindRow(precision->m_context.at("operations"), "id", "bind_dimension"));
            SetupSmoke::Choose(precision->m_dimension, FindRow(precision->m_context.at("dimensions"), "key", "line.width"));
            CanvasAssert(precision->m_parameter != nullptr && precision->m_parameter->GetCount() == 1,
                         "선폭과 호환되는 명시 길이 매개변수가 표시되지 않았습니다.");
            SetupSmoke::Choose(precision->m_parameter, 0);
            m_setupStage = 22;
            SetupSmoke::Click(precision->m_preview);
        }
        else if (m_setupStage == 22)
        {
            CanvasAssert(precision->m_review.at("can_apply").get<bool>(), "매개변수 결합 후보가 거절되었습니다.");
            m_setupStage = 23;
            SetupSmoke::Click(precision->m_apply);
        }
        else if (m_setupStage == 24)
        {
            const int index = FindRow(precision->m_context.at("dimensions"), "key", "line.width");
            const auto& width = precision->m_context.at("dimensions").at(index);
            CanvasAssert(!width.at("parameter_id").is_null() && !width.at("editable").get<bool>() &&
                             std::abs(width.at("value").get<double>() - 2.0) < 1e-9,
                         "결합된 선폭의 참조/읽기 전용/서비스 계산값이 재조회에 보존되지 않았습니다.");
            m_setupChecks.push_back("precision_parameter_binding_and_readonly_reopen");
            m_setupStage = 25;
            precision->CloseDialog();
        }
        return;
    }
    if (m_frame.m_busy || m_frame.m_cadRestoring || m_frame.m_solverRestoring)
    {
        return;
    }
    if (m_setupStage == 1)
    {
        for (const auto& item : m_frame.m_editor.at("items"))
        {
            if (item.at("kind") == "geometry" && item.at("label").get<std::string>().find("검증 대상 선") != std::string::npos)
            {
                m_precisionId = item.at("id");
            }
        }
        CanvasAssert(!m_precisionId.empty(), "이름 검증 대상이 없는 시험 프로젝트입니다.");
        m_setupExpectedRevision = m_frame.m_revision;
        m_setupStage = 2;
        m_frame.SelectObject({{"kind", "geometry"}, {"id", m_precisionId}});
    }
    else if (m_setupStage == 2)
    {
        m_frame.m_shell->ShowProperties();
        const auto unit = m_frame.m_editorPanel->m_fields.find("width.unit");
        CanvasAssert(unit != m_frame.m_editorPanel->m_fields.end(), "선폭 단위 입력이 없습니다.");
        auto* control = unit->second.control;
        CanvasAssert(control->GetRect().GetRight() <= unit->second.row->GetClientSize().x &&
                         control->GetSize().x >= control->GetBestSize().x,
                     "작은 속성 창에서 선폭 단위가 잘립니다.");
        m_setupStage = 3;
        wxKeyEvent event(wxEVT_KEY_DOWN);
        event.m_keyCode = WXK_F2;
        event.SetEventObject(m_frame.m_canvas);
        m_frame.m_canvas->GetEventHandler()->ProcessEvent(event);
    }
    else if (m_setupStage == 5)
    {
        CanvasAssert(m_frame.m_selection.value("id", "") == m_precisionId && m_frame.m_revision != m_setupExpectedRevision,
                     "이름 적용 후 선택 ID/개정이 맞지 않습니다.");
        const Json selected = m_frame.m_selection;
        m_frame.m_objectSearch->SetValue(Display("일치하지 않는 검색어"));
        SetupSmoke::Choose(m_frame.m_objectFilter, 3);
        CanvasAssert(m_frame.m_selection == selected, "검색과 목록 필터가 원본 객체 선택을 변경했습니다.");
        m_frame.m_objectSearch->SetValue(Display("급전 선"));
        SetupSmoke::Choose(m_frame.m_objectFilter, 1);
        const auto node = m_frame.m_tree->GetSelection();
        CanvasAssert(node.IsOk() && Utf8(m_frame.m_tree->GetItemText(node)).find("급전 선 검증") != std::string::npos,
                     "변경 이름이 탐색에 표시되지 않거나 선택이 복원되지 않았습니다.");
        m_frame.m_objectSearch->SetValue(wxEmptyString);
        SetupSmoke::Choose(m_frame.m_objectFilter, 0);
        m_setupChecks.push_back("rename_and_search_keep_stable_selection");
        m_precisionBeforeShapes = m_frame.m_scene.at("shapes");
        m_precisionUndoBefore = m_frame.m_editor.at("history").at("undo_count");
        m_setupStage = 6;
        wxKeyEvent event(wxEVT_KEY_DOWN);
        event.m_keyCode = 'D';
        event.SetEventObject(m_frame.m_canvas);
        m_frame.m_canvas->GetEventHandler()->ProcessEvent(event);
    }
    else if (m_setupStage == 10)
    {
        CanvasAssert(m_frame.m_editor.at("history").at("undo_count").get<int>() == m_precisionUndoBefore + 1 &&
                         m_frame.m_selection.value("id", "") == m_precisionId,
                     "치수 적용이 단일 명령이 아니거나 선택이 바뀌었습니다.");
        m_precisionDimensionShapes = m_frame.m_scene.at("shapes");
        m_setupChecks.push_back("precision_dimension_atomic_apply");
        m_setupStage = 11;
        SetupSmoke::Click(m_frame.m_tools.at(IdPrecision));
    }
    else if (m_setupStage == 13)
    {
        CanvasAssert(m_frame.m_editor.at("history").at("undo_count").get<int>() == m_precisionUndoBefore + 2 &&
                         m_frame.m_selection.value("id", "") == m_precisionId,
                     "회전 적용이 단일 명령이 아니거나 선택이 바뀌었습니다.");
        m_precisionAppliedShapes = m_frame.m_scene.at("shapes");
        CanvasAssert(m_precisionAppliedShapes != m_precisionDimensionShapes, "회전이 적용되지 않았습니다.");
        m_setupStage = 14;
        m_frame.History("project.undo");
    }
    else if (m_setupStage == 14)
    {
        CanvasAssert(m_frame.m_scene.at("shapes") == m_precisionDimensionShapes &&
                         m_frame.m_selection.value("id", "") == m_precisionId,
                     "한 번의 실행 취소가 회전 전 형상과 선택을 복원하지 못했습니다.");
        m_setupStage = 15;
        m_frame.History("project.redo");
    }
    else if (m_setupStage == 15)
    {
        CanvasAssert(m_frame.m_scene.at("shapes") == m_precisionAppliedShapes &&
                         m_frame.m_selection.value("id", "") == m_precisionId,
                     "다시 실행이 회전 형상과 선택을 복원하지 못했습니다.");
        m_setupChecks.push_back("precision_rotate_one_command_undo_redo_selection");
        m_setupStage = 21;
        SetupSmoke::Click(m_frame.m_tools.at(IdPrecision));
    }
    else if (m_setupStage == 23)
    {
        CanvasAssert(m_frame.m_editor.at("history").at("undo_count").get<int>() == m_precisionUndoBefore + 3,
                     "매개변수 결합이 한 이력으로 적용되지 않았습니다.");
        m_precisionAppliedShapes = m_frame.m_scene.at("shapes");
        m_setupStage = 24;
        SetupSmoke::Click(m_frame.m_tools.at(IdPrecision));
    }
    else if (m_setupStage == 25)
    {
        m_setupStage = 16;
        m_frame.SaveProject();
    }
    else if (m_setupStage == 16 && m_frame.m_savedRevision == m_frame.m_revision)
    {
        m_setupStage = 17;
        m_frame.m_connected = false;
        m_frame.m_transportFailed = false;
        m_frame.m_restarting = true;
        m_frame.BeginShutdown();
    }
    else if (m_setupStage == 17)
    {
        CanvasAssert(m_serviceSessions >= 2 && m_frame.m_savedRevision == m_frame.m_revision &&
                         m_frame.m_scene.at("shapes") == m_precisionAppliedShapes,
                     "서비스 재시작/저장 재열기가 정밀 편집 형상을 보존하지 못했습니다.");
        m_setupChecks.push_back("precision_saved_service_restart_preserves_geometry");
        m_setupStage = 18;
        FinishSmoke(true, "");
    }
}
