/** @file @brief 설정 화면의 변경과 주 창 갱신/이력/재열기를 함께 검사한다. */
#include "studio_internal.h"
#include "target_editor_dialog.h"
#include "template_dialog.h"

void StudioSmokeDriver::SetupSmokeTick()
{
    if (!m_frame.m_options.setupSmoke || m_frame.m_finishing || !m_frame.m_connected || m_setupStage == 0)
    {
        return;
    }
    try
    {
        if (Clock::now() - m_setupStarted > std::chrono::seconds(180))
        {
            throw std::runtime_error("설정 화면 시험 제한 시간을 초과했습니다.");
        }
        if (m_frame.m_requests.Size() != 0)
        {
            ++m_setupPendingTicks;
        }
        if (auto* target = dynamic_cast<TargetEditorDialog*>(m_frame.m_setupDialog))
        {
            SetupTargetSmoke(*target);
            return;
        }
        if (auto* templated = dynamic_cast<TemplateDialog*>(m_frame.m_setupDialog))
        {
            SetupTemplateSmoke(*templated);
            return;
        }
        if (m_frame.m_busy || m_frame.m_cadRestoring || m_frame.m_solverRestoring)
        {
            return;
        }
        if (m_setupStage == 1)
        {
            m_setupStage = 101;
            m_frame.CanvasCommand("create_board", {{"id", Uuid()}, {"width_mm", 80.0}, {"height_mm", 80.0}});
        }
        else if (m_setupStage == 101)
        {
            m_setupLayer = Uuid();
            m_setupStage = 102;
            m_frame.CanvasCommand("create_layer", {{"id", m_setupLayer}, {"name", "미정 물성 도체층"}});
        }
        else if (m_setupStage == 102)
        {
            m_setupStage = 2;
            m_frame.CallAfter(
                [this]()
                {
                    m_frame.OpenDesignSetup(false);
                });
        }
        else if (m_setupStage == 12)
        {
            CanvasAssert(m_frame.m_revision == m_setupExpectedRevision,
                         "여러 목표 적용 뒤 최신 개정이 주 창에 반영되지 않았습니다.");
            m_setupChecks.push_back("latest_target_revision_returned_to_frame");
            m_setupStage = 13;
            m_frame.History("project.undo");
        }
        else if (m_setupStage == 13)
        {
            m_setupStage = 14;
            m_frame.History("project.redo");
        }
        else if (m_setupStage == 14)
        {
            m_setupChecks.push_back("target_undo_redo");
            m_setupStage = 20;
            m_frame.CallAfter(
                [this]()
                {
                    m_frame.OpenDesignSetup(true);
                });
        }
        else if (m_setupStage == 40)
        {
            m_setupStage = 41;
            m_frame.SaveProject();
        }
        else if (m_setupStage == 41)
        {
            CanvasAssert(m_frame.m_savedRevision == m_frame.m_revision, "큰 표본 원본을 저장하지 못했습니다.");
            m_setupStage = 42;
            m_frame.OpenProject("open", "projects/GUI 카드 형상 검증");
        }
        else if (m_setupStage == 42)
        {
            m_setupStage = 43;
            m_frame.CanvasCommand("create_board", {{"id", Uuid()}, {"width_mm", 80.0}, {"height_mm", 80.0}});
        }
        else if (m_setupStage == 43)
        {
            m_setupStage = 44;
            m_frame.CanvasCommand("create_layer", {{"id", Uuid()}, {"name", "미정 물성 도체층"}});
        }
        else if (m_setupStage == 44)
        {
            m_setupStage = 20;
            m_frame.CallAfter(
                [this]()
                {
                    m_frame.OpenDesignSetup(true);
                });
        }
        else if (m_setupStage == 30)
        {
            CanvasAssert(m_frame.m_revision == m_setupExpectedRevision, "여러 템플릿 적용 뒤 주 창의 개정이 다릅니다.");
            m_setupShapes = m_frame.m_scene.at("shapes");
            CanvasAssert(m_setupShapes.size() == 9, "원호/IFA/G031의 기하 수가 다릅니다.");
            m_setupStage = 31;
            m_frame.History("project.undo");
        }
        else if (m_setupStage == 31)
        {
            CanvasAssert(m_frame.m_scene.at("shapes").size() == 7,
                         "G031 한 번 실행 취소가 모든 생성 객체를 회수하지 않았습니다.");
            m_setupStage = 32;
            m_frame.History("project.redo");
        }
        else if (m_setupStage == 32)
        {
            CanvasAssert(m_frame.m_scene.at("shapes") == m_setupShapes, "템플릿 재실행의 기하가 달라졌습니다.");
            m_setupChecks.push_back("template_single_command_undo_redo");
            m_setupChecks.push_back("literature_single_command_undo_redo");
            m_setupStage = 33;
            m_frame.SaveProject();
        }
        else if (m_setupStage == 33)
        {
            CanvasAssert(m_frame.m_savedRevision == m_frame.m_revision, "설정 변경의 저장 개정이 다릅니다.");
            m_setupStage = 34;
            m_frame.OpenProject("open", m_frame.m_path);
        }
        else if (m_setupStage == 34)
        {
            CanvasAssert(m_frame.m_scene.at("shapes") == m_setupShapes, "재열기 뒤 템플릿 기하가 달라졌습니다.");
            m_setupChecks.push_back("saved_reopen_preserves_geometry");
            m_setupStage = 35;
            FinishSmoke(true, "");
        }
    }
    catch (const std::exception& error)
    {
        FinishSmoke(false, "설정 화면 단계 " + std::to_string(m_setupStage) + ": " + error.what());
    }
}
