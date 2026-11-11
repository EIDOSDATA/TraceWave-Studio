/** @file @brief 일반 연구 화면의 실제 서비스/취소/재개/재열기 시나리오를 검증한다. */
#include "studio_internal.h"
#include "project_study_dialog.h"
#include <filesystem>
#include <fstream>

void StudioSmokeDriver::StudySmokeTick()
{
    if (!m_frame.m_options.studySmoke || m_frame.m_finishing || m_frame.m_busy || !m_frame.m_connected)
    {
        return;
    }
    if (m_studyStage == 1 || m_studyStage == 8)
    {
        m_frame.OpenProjectStudy();
        ++m_studyStage;
        return;
    }
    auto* dialog = m_frame.m_studyDialog;
    if (dialog == nullptr || dialog->Pending())
    {
        return;
    }
    const Json view = dialog->CurrentView();
    if (m_studyStage == 2)
    {
        if (!m_frame.m_options.studySpecification.empty())
        {
            std::ifstream input(std::filesystem::path(m_frame.m_options.studySpecification.ToStdWstring()), std::ios::binary);
            const Json specification = Json::parse(input);
            dialog->SetSpecification(specification);
        }
        m_studyChecks.push_back("original_project_study_form_opened");
        m_studyStage = 3;
        dialog->CreateStudy();
    }
    else if (m_studyStage == 3 && m_frame.m_options.studyExpectFailure && !dialog->LastError().empty())
    {
        CanvasAssert(view.empty(), "Missing material unexpectedly created a study.");
        m_studyChecks.push_back("missing_physics_not_filled_or_executed");
        m_studyStage = 10;
        FinishSmoke(true, "");
        return;
    }
    else if (m_studyStage == 3 && !view.empty() && view.at("state") == "ready")
    {
        CanvasAssert(view.at("snapshot").at("revision_id") == m_frame.m_revision, "Study snapshot changed source revision.");
        m_studyChecks.push_back("snapshot_and_settings_frozen");
        m_studyStage = 4;
        dialog->Command("start");
    }
    else if (m_studyStage == 4 && !view.empty() && view.at("state") == "running" &&
             !view.at("current_job").is_null() && view.at("current_job").at("state") == "running" &&
             view.at("cases").at(0).at("phase") == "solve")
    {
        m_studyChecks.push_back("cancel_during_solver_execution");
        m_studyStage = 5;
        dialog->Command("cancel");
    }
    else if (m_studyStage == 5 && !view.empty() && view.at("state") == "cancelled")
    {
        CanvasAssert(view.at("cases").at(0).at("attempt_count").get<int>() >= 2, "Cancellation attempts missing.");
        m_studyChecks.push_back("actual_termination_before_resume");
        m_studyStage = 6;
        dialog->Command("resume");
    }
    else if (m_studyStage == 6 && !view.empty() && view.at("state") == "running")
    {
        m_studyStage = 7;
        m_frame.m_description->SetValue(Display("고정 연구 실행 중 현재 설계의 메타데이터를 편집했습니다."));
        m_frame.ApplyCurrent([this]() { m_frame.SaveProject(); });
    }
    else if (m_studyStage == 7 && !view.empty() && view.at("state") == "completed")
    {
        CanvasAssert(!view.at("source_revision_matches_current").get<bool>(), "Old snapshot was not labelled stale.");
        CanvasAssert(view.at("power_unit") == "W*s^2" && view.at("absolute_power_w").is_null(), "Power normalization changed.");
        for (const auto& row : view.at("cases"))
        {
            CanvasAssert(row.at("phase") == "done" && !row.at("power_balance").is_null(), "Independent power rows missing.");
        }
        m_studyView = view;
        m_studyChecks.push_back("independent_power_rows_and_stale_revision_displayed");
        dialog->Close();
        m_studyStage = 8;
        m_frame.m_connected = false;
        m_frame.m_transportFailed = false;
        m_frame.m_restarting = true;
        m_frame.BeginShutdown();
        return;
    }
    else if (m_studyStage == 9 && !view.empty())
    {
        CanvasAssert(m_serviceSessions == 2 && view.at("study_id") == m_studyView.at("study_id"), "Study did not restore after restart.");
        CanvasAssert(view.at("state") == "completed" && view.at("cases") == m_studyView.at("cases"), "Study result changed after restart.");
        m_studyChecks.push_back("restart_restores_frozen_study_without_new_solver");
        m_studyStage = 10;
        FinishSmoke(true, "");
        return;
    }
    if (!m_frame.m_options.studyExpectFailure && !dialog->LastError().empty())
    {
        FinishSmoke(false, dialog->LastError());
    }
    else if (!view.empty() && (view.at("state") == "failed" || view.at("state") == "blocked" || view.at("state") == "interrupted"))
    {
        FinishSmoke(false, view.value("message", std::string("Study blocked")));
    }
}
