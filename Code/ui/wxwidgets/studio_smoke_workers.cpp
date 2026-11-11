/** @file @brief 주 창의 smoke_workers 책임을 구현한다. */
#include "studio_internal.h"
#include "radiation_dialog.h"

/** @brief 실제 GUI 명령과 서비스, CAD 프로세스 및 renderer의 연결을 검증한다. */
void StudioSmokeDriver::CadSmokeTick()
{
    if (!m_frame.m_options.cadSmoke || !m_frame.m_connected || m_frame.m_cadRestoring || m_frame.m_busy ||
        m_frame.m_finishing)
    {
        return;
    }
    if (m_cadSmokeStage == 1 && !m_frame.m_modelView->IsLoading())
    {
        if (!m_frame.m_cadConfigured)
        {
            FinishSmoke(false, "CAD smoke requires a configured native runtime.");
            return;
        }
        m_cadSmokeStage = 2;
        m_frame.m_description->SetValue(Display("GUI CAD 출력 전 적용할 입력"));
        m_frame.StartCad(true);
    }
    else if (m_cadSmokeStage == 2)
    {
        if (m_frame.m_options.cadExpectFailure && m_frame.m_cadState == "failed")
        {
            CanvasAssert(m_frame.m_cadResult.empty() && !m_frame.m_modelView->HasMesh() &&
                             !m_frame.m_tools.at(IdOutputFolder)->IsEnabled(),
                         "Failed CAD output was exposed.");
            m_cadChecks.push_back("invalid_input_not_published");
            m_cadSmokeStage = 7;
            FinishSmoke(true, "");
        }
        else if (!m_frame.m_cadTask.Id().empty())
        {
            CanvasAssert(m_frame.m_cadSnapshot.at("revision_id") == m_frame.m_revision && !m_frame.HasDraft(),
                         "CAD snapshot did not include applied draft.");
            CanvasAssert(m_frame.GetMenuBar()->IsEnabled(IdSave) && m_frame.m_canvas->IsEnabled(),
                         "CAD blocked project editing.");
            m_cadChecks.push_back("draft_applied_before_snapshot");
            m_cadChecks.push_back("editing_enabled_during_cad");
            m_cadSmokeStage = 3;
            m_frame.m_name->SetValue(wxEmptyString);
            m_frame.ApplyCurrent(
                [this]()
                {
                    FinishSmoke(false, "Invalid edit was accepted during CAD.");
                },
                [this](const Json&)
                {
                    CanvasAssert(m_frame.HasDraft() && m_frame.m_revision == m_frame.m_cadSnapshot.at("revision_id"),
                                 "Rejected edit changed the snapshot revision.");
                    m_frame.m_name->SetValue(Display("CAD 출력 중 편집한 이름"));
                    m_frame.ApplyCurrent(
                        [this]()
                        {
                            m_frame.Ready("CAD 실행 중 편집 검증");
                            m_frame.SaveProject();
                        });
                });
            m_frame.Send("capabilities.get", Json::object(), false, Json::object(),
                         [this](const Json&)
                         {
                             m_cadErrorProbeSeen = true;
                         });
        }
    }
    else if (m_cadSmokeStage == 3 && !m_frame.m_cadResult.empty() && m_frame.m_cadTask.Id().empty() &&
             !m_frame.m_modelView->IsLoading() && m_frame.m_modelView->HasMesh() &&
             m_frame.m_modelView->RenderedFrameCount() > 0)
    {
        CanvasAssert(m_frame.m_cadResult.at("snapshot").at("revision_id") != m_frame.m_revision &&
                         m_frame.m_editor.at("saved_revision") == m_frame.m_revision,
                     "Output snapshot changed or concurrent save failed.");
        CanvasAssert(m_frame.m_cadResult.at("artifacts").size() == 6 && m_frame.m_modelView->TriangleCount() > 0 &&
                         m_frame.m_modelView->BodyCount() > 0 && m_frame.m_tools.at(IdOutputFolder)->IsEnabled(),
                     "CAD mesh or package was not connected.");
        CanvasAssert(Utf8(m_frame.m_modelState->GetLabel()).find("이전 설계") != std::string::npos,
                     "Stale CAD view was not labelled.");
        CanvasAssert(m_cadErrorProbeSeen && m_frame.m_tools.at(IdBuild3D)->IsEnabled() &&
                         m_frame.m_tools.at(IdFit3D)->IsEnabled(),
                     "Responses or controls did not recover after CAD loading.");
        m_cadChecks.push_back("edit_error_does_not_drop_responses");
        m_cadChecks.push_back("snapshot_fixed_and_stale_label");
        m_cadChecks.push_back("save_during_cad");
        m_cadChecks.push_back("verified_mesh_rendered");
        m_cadChecks.push_back("step_package_accessible");
        m_cadFirstSnapshot = m_frame.m_modelView->LoadedSnapshotId();
        m_frame.m_modelView->SetView("top");
        m_frame.m_modelView->FitView();
        m_frame.m_modelView->SetView("isometric");
        m_cadChecks.push_back("camera_controls");
        m_cadSmokeStage = 4;
        m_frame.StartCad(false);
    }
    else if (m_cadSmokeStage == 4 && !m_frame.m_cadTask.Id().empty())
    {
        m_cadSmokeStage = 5;
        m_frame.CancelCad();
    }
    else if (m_cadSmokeStage == 5 && m_frame.m_cadTask.Id().empty() && m_frame.m_cadState == "cancelled")
    {
        CanvasAssert(m_frame.m_modelView->LoadedSnapshotId() == m_cadFirstSnapshot && !m_frame.m_cadResult.empty(),
                     "Cancellation removed the previous result.");
        m_cadChecks.push_back("cancel_preserves_previous_result");
        m_cadSmokeStage = 6;
        m_frame.m_connected = false;
        m_frame.m_transportFailed = false;
        m_frame.m_restarting = true;
        m_frame.BeginShutdown();
    }
    else if (m_cadSmokeStage == 6 && !m_frame.m_modelView->IsLoading() && m_frame.m_modelView->HasMesh())
    {
        CanvasAssert(m_serviceSessions == 2 && m_frame.m_modelView->LoadedSnapshotId() == m_cadFirstSnapshot,
                     "Published CAD result did not survive restart.");
        m_cadChecks.push_back("restart_restores_published_mesh");
        m_cadSmokeStage = 7;
        FinishSmoke(true, "");
    }
    if (!m_frame.m_modelView->IsLoading() && !m_frame.m_modelView->Error().empty() &&
        !m_frame.m_options.cadExpectFailure)
    {
        FinishSmoke(false, m_frame.m_modelView->Error());
    }
}

/** @brief 실제 GUI 작업 사슬과 결과 유지/재열기를 정해진 입력으로 검증한다. */
void StudioSmokeDriver::SolverSmokeTick()
{
    if (!m_frame.m_options.solverSmoke || m_frame.m_busy || m_frame.m_solverRestoring || m_frame.m_cadRestoring ||
        !m_frame.m_connected || m_frame.m_finishing)
    {
        return;
    }
    if (m_solverSmokeStage == 1)
    {
        if (m_frame.m_scene.at("board").is_null())
        {
            m_solverSmokeStage = 8;
            m_frame.CanvasCommand(
                "create_circular_board",
                Json{{"id", Uuid()}, {"center_x_mm", -5.0}, {"center_y_mm", 7.0}, {"radius_mm", 20.0}},
                [this]()
                {
                    CanvasAssert(m_frame.m_scene.at("board").at("kind") == "circle" &&
                                     m_frame.m_scene.at("board").at("center") == Json::array({-5.0, 7.0}) &&
                                     m_frame.m_scene.at("board").at("radius") == 20.0,
                                 "Circular board DTO differs from the submitted geometry.");
                    m_solverChecks.push_back("circular_board_created");
                    m_solverSmokeStage = 1;
                });
            return;
        }
        if (!m_frame.m_options.solverSettings.empty())
        {
            std::ifstream stream(std::filesystem::path(m_frame.m_options.solverSettings.ToStdWstring()),
                                 std::ios::binary);
            m_frame.m_solverSettings = Json::parse(stream);
        }
        else
        {
            m_frame.m_solverSettings = Json{{"frequency_hz", Json{{"start", 2.4e9}, {"stop", 2.4835e9}, {"count", 31}}},
                                            {"grid_mm", 1.0},
                                            {"air_padding_mm", 30.0},
                                            {"curve_tolerance_mm", 0.05},
                                            {"max_timesteps", 30000},
                                            {"end_criterion", 1e-5}};
        }
        if (m_frame.m_scene.at("board").value("kind", "rectangle") == "circle")
        {
            m_frame.m_canvas->FitView();
            m_solverChecks.push_back("circular_board_display");
        }
        m_solverSmokeStage = 2;
        m_frame.StartSolver();
    }
    else if (m_solverSmokeStage == 2 && m_frame.m_options.solverExpectFailure && !m_frame.m_solverWorkflow.Active() &&
             m_frame.m_solverState == "failed")
    {
        CanvasAssert(m_frame.m_solverResult.empty() && m_frame.m_solverChart->SampleCount() == 0,
                     "Invalid physics input produced a result.");
        m_solverChecks.push_back("invalid_physics_not_published");
        m_solverSmokeStage = 7;
        FinishSmoke(true, "");
    }
    else if (m_solverSmokeStage == 2 && !m_frame.m_options.solverExpectFailure && m_frame.m_solverWorkflow.Active() &&
             m_frame.m_solverWorkflow.PhaseName() == "analysis")
    {
        CanvasAssert(m_frame.m_tools.at(IdSave)->IsEnabled() && m_frame.m_tools.at(IdCancelSolver)->IsEnabled(),
                     "Solver blocked save or cancel.");
        m_solverChecks.push_back("editing_enabled_during_solver");
        m_solverSmokeStage = 3;
        m_frame.m_description->SetValue(Display("해석 실행 중 편집/저장 검증"));
        m_frame.ApplyCurrent(
            [this]()
            {
                m_frame.SaveProject();
            });
    }
    else if (m_solverSmokeStage == 3 && !m_frame.m_solverWorkflow.Active() && m_frame.m_solverState == "completed" &&
             m_frame.m_solverChart->RenderedFrames() > 0)
    {
        if (m_frame.m_solverSettings.contains("radiation") && !m_radiationChecked)
        {
            if (!m_radiationDialog)
            {
                CanvasAssert(m_frame.m_tools.at(IdRadiation)->IsEnabled(), "Radiation viewer unavailable.");
                m_frame.OpenRadiation();
                for (auto* child : m_frame.GetChildren())
                {
                    auto* dialog = dynamic_cast<RadiationDialog*>(child);
                    if (dialog != nullptr)
                    {
                        m_radiationDialog = dialog;
                    }
                }
                CanvasAssert(m_radiationDialog.get() != nullptr, "Radiation viewer did not open.");
                return;
            }
            CanvasAssert(m_radiationDialog->m_details->IsEmpty() || m_radiationDialog->m_pattern.Complete(),
                         "Radiation viewer showed partial data.");
            CanvasAssert(!m_radiationDialog->m_status->GetLabel().Contains(Display("실패")), "Radiation query failed.");
            if (!m_radiationDialog->m_pattern.Complete() || m_radiationDialog->m_renderedFrames == 0)
            {
                return;
            }
            m_radiationDialog->m_phi->SetSelection(1);
            m_radiationDialog->m_metric->SetSelection(3);
            m_radiationDialog->m_chart->Refresh(false);
            const auto frames = m_radiationDialog->m_renderedFrames;
            m_radiationDialog->m_chart->Update();
            CanvasAssert(m_radiationDialog->m_renderedFrames > frames, "Radiation phi/metric view did not repaint.");
            m_solverChecks.push_back("radiation_paged_view_and_phi_metric_selection");
            m_radiationChecked = true;
            m_radiationDialog->Destroy();
        }
        CanvasAssert(m_frame.m_solverSamples.at("snapshot").at("revision_id") != m_frame.m_revision &&
                         m_frame.m_editor.at("saved_revision") == m_frame.m_revision,
                     "Solver snapshot changed or concurrent save failed.");
        CanvasAssert(m_frame.m_solverChart->SampleCount() >= 3, "No solver samples displayed.");
        m_solverChecks.push_back("snapshot_fixed_and_stale_label");
        m_solverChecks.push_back("bounded_results_rendered");
        m_solverChecks.push_back("save_during_solver");
        m_solverFirstResult = m_frame.m_solverResult.at("artifact_id");
        m_frame.m_solverMetric->SetSelection(2);
        m_frame.m_solverChart->SetMetric(2);
        m_solverSmokeStage = 4;
        m_frame.StartSolver();
    }
    else if (m_solverSmokeStage == 4 && !m_frame.m_solverTask.Id().empty())
    {
        m_solverSmokeStage = 5;
        m_frame.CancelSolver();
    }
    else if (m_solverSmokeStage == 5 && !m_frame.m_solverWorkflow.Active() && m_frame.m_solverState == "cancelled")
    {
        CanvasAssert(m_frame.m_solverResult.at("artifact_id") == m_solverFirstResult,
                     "Cancel removed prior solver result.");
        m_solverChecks.push_back("cancel_preserves_previous_result");
        m_solverSmokeStage = 6;
        m_frame.m_connected = false;
        m_frame.m_transportFailed = false;
        m_frame.m_restarting = true;
        m_frame.BeginShutdown();
    }
    else if (m_solverSmokeStage == 6 && !m_frame.m_solverSamples.empty())
    {
        CanvasAssert(m_serviceSessions == 2 && m_frame.m_solverResult.at("artifact_id") == m_solverFirstResult,
                     "Solver result was not restored.");
        m_solverChecks.push_back("restart_restores_result");
        m_solverSmokeStage = 7;
        FinishSmoke(true, "");
    }
    if (!m_frame.m_options.solverExpectFailure && !m_frame.m_solverWorkflow.Active() &&
        m_frame.m_solverState == "failed")
    {
        FinishSmoke(false, Utf8(m_frame.m_solverStatus->GetLabel()));
    }
}
