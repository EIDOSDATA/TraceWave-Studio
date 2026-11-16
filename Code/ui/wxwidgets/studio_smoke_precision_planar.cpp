/** @file @brief 평면 대상 체크, 집합 후보, 빈 결과 복구와 원자 저장을 실제 화면으로 검사한다. */
#include "studio_internal.h"
#include "precision_dialog.h"
#include "setup_smoke_support.h"
#include <wx/checklst.h>

namespace
{
/** @brief 지원 작업을 실제 선택 변경 이벤트로 선택한다. */
int Operation(const Json& rows, const std::string& name)
{
    for (std::size_t index = 0; index < rows.size(); ++index)
    {
        if (rows.at(index).at("id") == name)
        {
            return static_cast<int>(index);
        }
    }
    throw std::runtime_error("평면 작업이 없습니다: " + name);
}

/** @brief 직사각형의 독립 기대 면적과 비교할 서비스 후보의 전체 면적을 읽는다. */
double Area(const Json& review)
{
    double area = 0;
    for (const auto& row : review.at("dimensions"))
    {
        if (row.at("key") == "region.area")
        {
            area += row.at("value").get<double>();
        }
    }
    return area;
}
}

void StudioSmokeDriver::PrecisionPlanarSmokeTick()
{
    auto* dialog = dynamic_cast<PrecisionDialog*>(m_frame.m_setupDialog);
    if (dialog != nullptr && dialog->m_pending)
    {
        return;
    }
    if (dialog != nullptr)
    {
        if (m_setupStage == 3)
        {
            CanvasAssert(dialog->m_selection->GetCount() == 2 && dialog->m_selection->IsChecked(0),
                         "선택한 첫 피연산자가 목록 맨 앞에 표시되지 않았습니다.");
            dialog->m_selection->Check(1);
            m_setupStage = 4;
            wxCommandEvent event(wxEVT_CHECKLISTBOX, dialog->m_selection->GetId());
            event.SetInt(1);
            event.SetEventObject(dialog->m_selection);
            dialog->m_selection->GetEventHandler()->ProcessEvent(event);
        }
        else if (m_setupStage == 4)
        {
            CanvasAssert(dialog->m_context.at("selection").size() == 2, "두 대상의 작업 가능 상태를 재조회하지 못했습니다.");
            SetupSmoke::Choose(dialog->m_operation, Operation(dialog->m_context.at("operations"), "difference"));
            m_setupStage = 5;
            SetupSmoke::Click(dialog->m_preview);
        }
        else if (m_setupStage == 5 || m_setupStage == 6)
        {
            const double expected = m_setupStage == 5 ? 15.0 : 10.0;
            CanvasAssert(dialog->m_review.value("can_apply", false) && std::abs(Area(dialog->m_review) - expected) < 1e-9 &&
                             m_frame.m_scene.at("shapes") == m_precisionBeforeShapes,
                         "빼기/교차 후보의 면적 또는 원본 보존이 다릅니다.");
            SetupSmoke::Choose(dialog->m_operation, Operation(dialog->m_context.at("operations"), m_setupStage == 5 ? "intersection" : "union"));
            ++m_setupStage;
            SetupSmoke::Click(dialog->m_preview);
        }
        else if (m_setupStage == 7)
        {
            CanvasAssert(dialog->m_review.value("can_apply", false) && std::abs(Area(dialog->m_review) - 40.0) < 1e-9,
                         "합치기 후보가 독립 직사각형 면적 40 mm2와 다릅니다.");
            m_setupChecks.push_back("planar_target_order_difference_intersection_union_preview");
            m_setupStage = 8;
            SetupSmoke::Click(dialog->m_apply);
        }
        else if (m_setupStage == 9)
        {
            SetupSmoke::Choose(dialog->m_operation, Operation(dialog->m_context.at("operations"), "offset"));
            dialog->m_numbers.at("distance_mm")->SetValue("-100");
            m_setupStage = 10;
            SetupSmoke::Click(dialog->m_preview);
        }
        else if (m_setupStage == 10)
        {
            CanvasAssert(!dialog->m_review.value("can_apply", true) && dialog->m_review.at("scene").is_null() &&
                             !dialog->m_disconnected && !dialog->m_apply->IsEnabled() &&
                             m_frame.m_scene.at("shapes") == m_precisionDimensionShapes,
                         "빈 오프셋 결과가 원본을 지우거나 복구 가능한 화면을 잠갔습니다.");
            m_setupChecks.push_back("planar_empty_offset_blocks_without_deleting_source");
            dialog->m_numbers.at("distance_mm")->SetValue("1");
            m_setupStage = 11;
            SetupSmoke::Click(dialog->m_preview);
        }
        else if (m_setupStage == 11)
        {
            CanvasAssert(dialog->m_review.value("can_apply", false) && std::abs(Area(dialog->m_review) - 70.0) < 1e-9,
                         "1 mm 오프셋 후보가 독립 직사각형 면적 70 mm2와 다릅니다.");
            m_setupStage = 12;
            SetupSmoke::Click(dialog->m_apply);
        }
        else if (m_setupStage == 13)
        {
            SetupSmoke::Choose(dialog->m_operation, Operation(dialog->m_context.at("operations"), "mirror"));
            SetupSmoke::Choose(dialog->m_axis, 0);
            dialog->m_numbers.at("offset_mm")->SetValue("6");
            m_setupStage = 14;
            SetupSmoke::Click(dialog->m_preview);
        }
        else if (m_setupStage == 14)
        {
            CanvasAssert(dialog->m_review.value("can_apply", false) && std::abs(Area(dialog->m_review) - 70.0) < 1e-9,
                         "미러 후보가 영역 면적을 보존하지 않았습니다.");
            m_setupStage = 15;
            SetupSmoke::Click(dialog->m_apply);
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
            if (item.at("kind") == "geometry" && item.at("label").get<std::string>().find("연산 영역 A") != std::string::npos)
            {
                m_precisionId = item.at("id");
            }
        }
        CanvasAssert(!m_precisionId.empty(), "평면 연산 시험 대상이 없습니다.");
        m_precisionBeforeShapes = m_frame.m_scene.at("shapes");
        m_precisionUndoBefore = m_frame.m_editor.at("history").at("undo_count");
        m_setupStage = 2;
        m_frame.SelectObject({{"kind", "geometry"}, {"id", m_precisionId}});
    }
    else if (m_setupStage == 2)
    {
        m_setupStage = 3;
        SetupSmoke::Click(m_frame.m_tools.at(IdPrecision));
    }
    else if (m_setupStage == 8)
    {
        CanvasAssert(m_frame.m_scene.at("shapes").size() == 1 && m_frame.m_selection.value("id", "") != m_precisionId &&
                         m_frame.m_editor.at("history").at("undo_count").get<int>() == m_precisionUndoBefore + 1,
                     "합치기가 새 UUID 선택과 하나의 명령으로 적용되지 않았습니다.");
        m_precisionId = m_frame.m_selection.at("id");
        m_precisionDimensionShapes = m_frame.m_scene.at("shapes");
        m_setupChecks.push_back("planar_union_atomic_replacement_selection");
        m_setupStage = 9;
        SetupSmoke::Click(m_frame.m_tools.at(IdPrecision));
    }
    else if (m_setupStage == 12)
    {
        CanvasAssert(m_frame.m_selection.value("id", "") != m_precisionId &&
                         m_frame.m_editor.at("history").at("undo_count").get<int>() == m_precisionUndoBefore + 2,
                     "오프셋이 새 UUID 선택과 하나의 명령으로 적용되지 않았습니다.");
        m_precisionId = m_frame.m_selection.at("id");
        m_precisionDimensionShapes = m_frame.m_scene.at("shapes");
        m_setupStage = 13;
        SetupSmoke::Click(m_frame.m_tools.at(IdPrecision));
    }
    else if (m_setupStage == 15)
    {
        CanvasAssert(m_frame.m_selection.value("id", "") == m_precisionId &&
                         m_frame.m_editor.at("history").at("undo_count").get<int>() == m_precisionUndoBefore + 3,
                     "미러가 원래 객체 ID와 하나의 명령으로 적용되지 않았습니다.");
        m_precisionAppliedShapes = m_frame.m_scene.at("shapes");
        CanvasAssert(m_precisionAppliedShapes != m_precisionDimensionShapes, "미러가 실제 형상을 바꾸지 않았습니다.");
        m_setupStage = 16;
        m_frame.History("project.undo");
    }
    else if (m_setupStage == 16)
    {
        CanvasAssert(m_frame.m_scene.at("shapes") == m_precisionDimensionShapes && m_frame.m_selection.value("id", "") == m_precisionId,
                     "미러 실행 취소가 형상/선택을 복원하지 못했습니다.");
        m_setupStage = 17;
        m_frame.History("project.redo");
    }
    else if (m_setupStage == 17)
    {
        CanvasAssert(m_frame.m_scene.at("shapes") == m_precisionAppliedShapes && m_frame.m_selection.value("id", "") == m_precisionId,
                     "미러 다시 실행이 형상/선택을 복원하지 못했습니다.");
        m_setupChecks.push_back("planar_offset_mirror_apply_undo_redo");
        m_setupStage = 18;
        m_frame.SaveProject();
    }
    else if (m_setupStage == 18 && m_frame.m_savedRevision == m_frame.m_revision)
    {
        m_setupStage = 19;
        m_frame.m_connected = false;
        m_frame.m_transportFailed = false;
        m_frame.m_restarting = true;
        m_frame.BeginShutdown();
    }
    else if (m_setupStage == 19)
    {
        CanvasAssert(m_serviceSessions >= 2 && m_frame.m_savedRevision == m_frame.m_revision &&
                         m_frame.m_scene.at("shapes") == m_precisionAppliedShapes,
                     "평면 형상과 이름을 서비스 재시작 뒤 복원하지 못했습니다.");
        m_setupChecks.push_back("planar_saved_service_restart_preserves_geometry");
        m_setupStage = 20;
        FinishSmoke(true, "");
    }
}
