/** @file @brief 주 창의 smoke_report 책임을 구현한다. */
#include "studio_internal.h"
#include "pcb_selection_dialog.h"
#include "project_study_dialog.h"

void StudioSmokeDriver::FinishSmoke(bool passed, const std::string& error)
{
    if (m_frame.m_finishing)
    {
        return;
    }
    if (m_frame.m_pcbDialog != nullptr)
    {
        m_frame.m_pcbDialog->ServiceDisconnected(error.empty() ? "GUI 시험을 종료합니다." : error);
        m_frame.m_pcbDialog->Close();
    }
    m_frame.m_finishing = true;
    if (m_frame.m_studyDialog != nullptr)
    {
        m_frame.m_studyDialog->Close();
    }
    ExitCode = passed ? 0 : 2;
    Json report{{"schema_version", "rfad.gui-smoke/0.1"},
                {"passed", passed},
                {"stage", m_smokeStage},
                {"project_id", m_frame.m_project},
                {"revision_id", m_frame.m_revision},
                {"saved_revision", m_frame.m_savedRevision},
                {"snapshot_id", m_frame.m_snapshot},
                {"service_sessions", m_serviceSessions},
                {"editor_stage", m_editorStage},
                {"editor_checks", m_editorChecks},
                {"canvas_stage", m_canvasStage},
                {"canvas_checks", m_canvasChecks},
                {"primitives_stage", m_primitivesStage},
                {"primitives_checks", m_primitivesChecks},
                {"pcb_stage", m_pcbStage},
                {"pcb_checks", m_pcbChecks},
                {"pcb_ticks", m_pcbTicks},
                {"pcb_request_ticks", m_pcbRequestTicks},
                {"pcb_project_path", m_frame.m_options.pcbSmoke ? m_smokePath : ""},
                {"cad_stage", m_cadSmokeStage},
                {"cad_checks", m_cadChecks},
                {"cad_result", m_frame.m_cadResult},
                {"solver_stage", m_solverSmokeStage},
                {"study_stage", m_studyStage},
                {"study_checks", m_studyChecks},
                {"study_view", m_studyView},
                {"solver_checks", m_solverChecks},
                {"solver_result", m_frame.m_solverResult},
                {"solver_sample_count", m_frame.m_solverChart->SampleCount()},
                {"solver_frames", m_frame.m_solverChart->RenderedFrames()},
                {"mesh_triangles", m_frame.m_modelView->TriangleCount()},
                {"mesh_bodies", m_frame.m_modelView->BodyCount()},
                {"rendered_frames", m_frame.m_modelView->RenderedFrameCount()},
                {"renderer", m_frame.m_modelView->RendererDescription()},
                {"ux_checks", m_uxChecks},
                {"editor_ui_state", m_frame.m_editState},
                {"apply_enabled", m_frame.m_apply->IsEnabled()},
                {"error", error},
                {"physics_tested", false},
                {"frame_budget_tested", false}};
    if (!m_frame.m_options.smokeReport.empty())
    {
        const std::filesystem::path path(m_frame.m_options.smokeReport.ToStdWstring());
        std::error_code filesystemError;
        if (!path.parent_path().empty())
        {
            std::filesystem::create_directories(path.parent_path(), filesystemError);
        }
        std::ofstream output(path, std::ios::binary);
        output << report.dump(2) << '\n';
        if (!output)
        {
            ExitCode = 3;
        }
    }
    if (!m_frame.m_closing)
    {
        m_frame.CallAfter(
            [this]()
            {
                m_frame.Close();
            });
    }
}
