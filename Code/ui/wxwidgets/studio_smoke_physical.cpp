/** @file @brief Windows의 물리 설정과 실제 CAD/저장/재열기 경로를 검사한다. */
#include "studio_internal.h"
#include "physical_setup_dialog.h"
#include "result_workspace.h"
#include "result_compare_view.h"
#include "setup_smoke_support.h"
#include "studio_notebook.h"
#include <wx/stattext.h>

/** @brief 실제 PCB 계산 두 건을 저장된 원본에서 다시 선택하여 비교한다. */
void StudioSmokeDriver::InstallationSmokeTick()
{
    auto* setup = dynamic_cast<PhysicalSetupDialog*>(m_frame.m_setupDialog);
    if ((setup == nullptr && m_frame.m_busy) || m_frame.m_solverRestoring)
    {
        return;
    }
    if (m_frame.m_solverState == "failed")
    {
        throw std::runtime_error(Utf8(m_frame.m_solverDetails->GetValue()));
    }
    if (m_setupStage == 1)
    {
        const std::filesystem::path path(m_frame.m_options.solverSettings.ToStdWstring());
        std::ifstream settings(path, std::ios::binary);
        m_frame.m_solverSettings = Json::parse(settings);
        std::ifstream part(path.parent_path() / "installation-part.json", std::ios::binary);
        if (part)
        {
            m_resultsFixture = Json::parse(part);
        }
        m_setupStage = 2;
        m_frame.StartSolver();
    }
    else if (m_setupStage == 2 && m_frame.m_solverState == "completed" && !m_frame.m_solverWorkflow.Active())
    {
        m_solverFirstResult = m_frame.m_solverResult.at("artifact_id");
        m_setupStage = 3;
        m_frame.CallAfter([this]()
        {
            wxCommandEvent event(wxEVT_MENU, IdPhysicalSetup);
            m_frame.GetEventHandler()->ProcessEvent(event);
        });
    }
    else if (auto* dialog = setup)
    {
        if (dialog->m_pending)
        {
            return;
        }
        CanvasAssert(dialog->m_error.is_null(), dialog->m_error.dump());
        auto choose = [dialog](const std::string& key, const std::string& value)
        {
            auto* control = static_cast<wxChoice*>(dialog->m_inputs.at(key));
            for (unsigned index = 0; index < control->GetCount(); ++index)
            {
                const auto* data = static_cast<wxStringClientData*>(control->GetClientObject(index));
                if (Utf8(data->GetData()) == value)
                {
                    SetupSmoke::Choose(control, static_cast<int>(index));
                    return;
                }
            }
            throw std::runtime_error("설치 선택지를 찾지 못했습니다.");
        };
        auto apply = [dialog]()
        {
            dialog->m_reason->SetValue(Display("내부 케이스 검증 출처"));
            SetupSmoke::Click(dialog->m_apply);
        };
        if (m_setupStage == 3)
        {
            m_setupStage = 4;
            SetupSmoke::Choose(dialog->m_section, m_resultsFixture.value("kind", "") == "solder_mask" ? 1 : 4);
        }
        else if (m_setupStage == 4)
        {
            const auto kind = m_resultsFixture.value("kind", std::string("dielectric_case"));
            if (kind == "solder_mask")
            {
                auto field = [dialog](const std::string& key, const std::string& value)
                {
                    static_cast<wxTextCtrl*>(dialog->m_inputs.at(key))->SetValue(Display(value));
                };
                if (m_resultsFixture.contains("fullArtifact"))
                {
                    if (!dialog->m_context.at("exists").get<bool>())
                    {
                        const int index = dialog->m_record->FindString(Display("시험 솔더마스크"));
                        CanvasAssert(index != wxNOT_FOUND, "전체 피복 원본을 찾지 못했습니다.");
                        SetupSmoke::Choose(dialog->m_record, index);
                        return;
                    }
                    field("openings", "6 4 4 4");
                }
                else
                {
                    field("name", "시험 솔더마스크");
                    field("offset", "0");
                    field("thickness", "0.15");
                    auto* material = static_cast<wxChoice*>(dialog->m_inputs.at("material_id"));
                    const int index = material->FindString(Display("검증용 유전체 케이스 재료"));
                    CanvasAssert(index != wxNOT_FOUND, "시험 마스크 재료를 찾지 못했습니다.");
                    SetupSmoke::Choose(material, index);
                    static_cast<wxCheckBox*>(dialog->m_inputs.at("include_in_em"))->SetValue(true);
                }
                m_setupStage = 5;
                apply();
                return;
            }
            if (kind == "grounded_pec_box")
            {
                if (!dialog->m_context.at("exists").get<bool>())
                {
                    const int index = dialog->m_record->FindString(Display("시험용 금속 접지 비교"));
                    CanvasAssert(index != wxNOT_FOUND, "비접촉 금속 원본을 찾지 못했습니다.");
                    SetupSmoke::Choose(dialog->m_record, index);
                    return;
                }
                choose("kind", kind);
                static_cast<wxTextCtrl*>(dialog->m_inputs.at("z"))->SetValue(Display("1.035"));
                m_setupStage = 5;
                apply();
                return;
            }
            const auto& scenario = dialog->m_context.at("records").at("scenario").at(0);
            choose("scenario_id", scenario.at("id"));
            const bool metal = kind == "isolated_pec_box";
            choose("kind", kind);
            auto* material = static_cast<wxChoice*>(dialog->m_inputs.at("material_id"));
            const int index = material->FindString(Display(metal ? "Explicit test conductor" : "검증용 유전체 케이스 재료"));
            CanvasAssert(index != wxNOT_FOUND, "시험 재료를 찾지 못했습니다.");
            SetupSmoke::Choose(material, index);
            const Json fields = metal
                ? Json{{"name", "검증용 금속 상자"}, {"x", "19"}, {"y", "4"}, {"z", "0.5"},
                       {"yaw", "0"}, {"width", "2"}, {"height", "5"}, {"depth", "1"}}
                : Json{{"name", "검증용 케이스"}, {"x", "-2"}, {"y", "-2"}, {"z", "0"},
                       {"yaw", "0"}, {"width", "20"}, {"height", "16"}, {"depth", "3.5"}, {"case_thickness", "1"}};
            for (const auto& field : fields.items())
            {
                static_cast<wxTextCtrl*>(dialog->m_inputs.at(field.key()))->SetValue(Display(field.value()));
            }
            static_cast<wxCheckBox*>(dialog->m_inputs.at("include_in_em"))->SetValue(true);
            m_setupStage = 5;
            apply();
        }
        else if (m_setupStage == 5)
        {
            if (m_resultsFixture.contains("kind"))
            {
                m_setupStage = 8;
                dialog->CloseDialog();
            }
            else
            {
                m_setupStage = 6;
                SetupSmoke::Choose(dialog->m_section, 2);
            }
        }
        else if (m_setupStage == 6)
        {
            choose("active_scenario_id", dialog->m_context.at("records").at("scenario").at(0).at("id"));
            m_setupStage = 7;
            apply();
        }
        else if (m_setupStage == 7)
        {
            m_setupStage = 8;
            dialog->CloseDialog();
        }
    }
    else if (m_setupStage == 8)
    {
        m_setupStage = 9;
        m_frame.SaveProject();
    }
    else if (m_setupStage == 9 && m_frame.m_savedRevision == m_frame.m_revision)
    {
        m_setupExpectedRevision = m_frame.m_revision;
        m_setupStage = 10;
        m_frame.StartSolver();
    }
    else if (m_setupStage == 10 && m_frame.m_solverState == "completed" && !m_frame.m_solverWorkflow.Active())
    {
        const std::string installed = m_frame.m_solverResult.at("artifact_id");
        CanvasAssert(installed != m_solverFirstResult, "케이스 해석이 별도 결과를 생성하지 않았습니다.");
        if (m_resultsFixture.value("kind", "") == "solder_mask" && !m_resultsFixture.contains("fullArtifact"))
        {
            m_resultsFixture["fullArtifact"] = installed;
            m_setupStage = 3;
            m_frame.CallAfter([this]()
            {
                wxCommandEvent event(wxEVT_MENU, IdPhysicalSetup);
                m_frame.GetEventHandler()->ProcessEvent(event);
            });
            return;
        }
        const auto full = m_resultsFixture.value("fullArtifact", "");
        m_resultsFixture = {{"bare", {{"kind", "solver"}, {"artifact_id", m_solverFirstResult}}},
                            {"installed", {{"kind", "solver"}, {"artifact_id", installed}}},
                            {"kind", m_resultsFixture.value("kind", std::string("dielectric_case"))}};
        if (!full.empty())
        {
            m_resultsFixture["full"] = {{"kind", "solver"}, {"artifact_id", full}};
        }
        m_setupStage = 11;
        m_frame.OpenProject("open", m_frame.m_path);
    }
    else if (m_setupStage == 11 && m_frame.m_savedRevision == m_setupExpectedRevision)
    {
        m_frame.PrepareExtendedWorkspaces(2);
        m_frame.m_views->SetSelection(14);
        m_setupStage = 12;
        m_frame.m_results->Select(m_resultsFixture.at("bare"));
    }
    else if (m_setupStage >= 12)
    {
        auto& workspace = *m_frame.m_results;
        auto* view = workspace.m_compare;
        if (m_setupStage == 12 && workspace.m_description.is_object() &&
            workspace.m_description.at("source") == m_resultsFixture.at("bare"))
        {
            CanvasAssert(view->Add(workspace.m_description), "기판 단독 결과를 다시 읽지 못했습니다.");
            m_setupStage = 13;
            workspace.Select(m_resultsFixture.contains("full") ? m_resultsFixture.at("full") : m_resultsFixture.at("installed"));
        }
        else if (m_setupStage == 13 && m_resultsFixture.contains("full") && workspace.m_description.is_object() &&
                 workspace.m_description.at("source") == m_resultsFixture.at("full"))
        {
            CanvasAssert(view->Add(workspace.m_description), "전체 피복 해석 결과를 다시 읽지 못했습니다.");
            workspace.Select(m_resultsFixture.at("installed"));
        }
        else if (m_setupStage == 13 && workspace.m_description.is_object() &&
                 workspace.m_description.at("source") == m_resultsFixture.at("installed"))
        {
            CanvasAssert(view->Add(workspace.m_description), "케이스 결과를 다시 읽지 못했습니다.");
            m_setupStage = 14;
        }
        else if (m_setupStage == 14 && view->m_pages.at(0).is_object() && view->m_pages.at(1).is_object())
        {
            view->m_orders.at(1) = Json::array({0});
            m_setupStage = 15;
            workspace.Compare(view, 1);
        }
        else if (m_setupStage == 15 || m_setupStage == 17)
        {
            const std::size_t index = m_setupStage == 17 ? 2 : 1;
            const auto& comparison = view->m_comparisons.at(index);
            if (!comparison.is_object())
            {
                return;
            }
            CanvasAssert(comparison.at("points").size() == 31, "S11 공통 표본을 표시하지 못했습니다.");
            const auto& installation = comparison.at("installation_comparison");
            CanvasAssert(installation.contains("frequencies"), installation.dump());
            view->OpenInstallation(installation);
            auto* dialog = wxWindow::FindWindowByName("installation-comparison", view);
            CanvasAssert(dialog != nullptr && dialog->IsShown(), "설치 방사 비교 창이 열리지 않았습니다.");
            auto* values = dynamic_cast<wxStaticText*>(wxWindow::FindWindowByName("installation-efficiencies", dialog));
            const auto kind = m_resultsFixture.at("kind");
            const auto firstLabel = kind == "solder_mask" ? "마스크 없음" :
                kind == "grounded_pec_box" ? "(비접촉)" : kind == "isolated_pec_box" ? "기준 결과" : "기판 단독";
            const auto secondLabel = kind == "grounded_pec_box" ? "(접지 연결)" :
                kind == "isolated_pec_box" ? "검증용 금속 상자" :
                kind == "solder_mask" ? (index == 1 ? "(개구 없음)" : "(개구 1개)") : "유전체 케이스 시험";
            CanvasAssert(values != nullptr && values->GetLabel().Contains(Display(firstLabel)) &&
                             values->GetLabel().Contains(Display(secondLabel)),
                         "설치 비교 창에 두 원본과 효율이 표시되지 않았습니다.");
            if (kind == "solder_mask" && index == 1)
            {
                CanvasAssert(view->m_pages.size() == 3 && view->m_pages.at(2).is_object(), "S11 세 곡선을 읽지 못했습니다.");
                m_setupStage = 17;
                dialog->Destroy();
                view->m_orders.at(2) = Json::array({0});
                workspace.Compare(view, 2);
                return;
            }
            m_setupChecks.push_back("native_installation_reopen_s11_efficiency_radiation");
            m_setupStage = 16;
            dialog->Destroy();
            FinishSmoke(true, "");
        }
    }
}

void StudioSmokeDriver::PhysicalSetupSmokeTick()
{
    auto* dialog = dynamic_cast<PhysicalSetupDialog*>(m_frame.m_setupDialog);
    if (dialog == nullptr)
    {
        if (m_frame.m_busy || m_frame.m_cadRestoring || m_frame.m_solverRestoring)
        {
            return;
        }
        switch (m_setupStage)
        {
        case 1:
        case 16:
            ++m_setupStage;
            m_frame.CallAfter([this]()
            {
                wxCommandEvent event(wxEVT_MENU, IdPhysicalSetup);
                m_frame.GetEventHandler()->ProcessEvent(event);
            });
            break;
        case 10:
            m_setupStage = 11;
            m_frame.History("project.undo");
            break;
        case 11:
            m_setupStage = 12;
            m_frame.History("project.redo");
            break;
        case 12:
            m_setupStage = 13;
            m_frame.StartCad(false);
            break;
        case 13:
            if (m_frame.m_cadState == "failed")
            {
                throw std::runtime_error(Utf8(m_frame.m_cadDetails->GetValue()));
            }
            if (m_frame.m_modelView->BodyCount() > 0 && m_frame.m_modelView->RenderedFrameCount() > 0 &&
                !m_frame.m_modelView->IsLoading())
            {
                const auto& report = m_frame.m_cadResult.at("environment_placement");
                CanvasAssert(report.size() == 1 && report.at(0).at("relation") == "separated" &&
                             report.at(0).at("material_id").is_null(), "외부 고체 간극 또는 미정 물성이 다릅니다.");
                CanvasAssert(report.at(0).at("clearance_mm").get<double>() > 0.0, "간극 값이 표시되지 않았습니다.");
                m_setupChecks.push_back("physical_setup_native_opengl_clearance");
                m_setupStage = 14;
                m_frame.StartCad(true);
            }
            break;
        case 14:
            if (m_frame.m_cadState == "failed")
            {
                throw std::runtime_error(Utf8(m_frame.m_cadDetails->GetValue()));
            }
            if (m_frame.m_cadResult.value("projection_purpose", "") == "step" && m_frame.m_cadState == "completed")
            {
                CanvasAssert(m_frame.m_modelView->BodyCount() > static_cast<std::size_t>(m_frame.m_cadResult.at("body_count").get<int>()),
                             "STEP 범위가 별도의 표시 모델을 바꿨습니다.");
                m_setupChecks.push_back("physical_setup_step_visibility_independent");
                m_setupStage = 15;
                m_frame.SaveProject();
            }
            break;
        case 15:
            if (m_frame.m_savedRevision == m_frame.m_revision)
            {
                const wxString selectedFile = wxFileName(m_frame.m_options.smokeReport).GetPathWithSep() + "fixture.step";
                if (wxFileName::FileExists(selectedFile))
                {
                    const auto marker = std::filesystem::path((m_frame.m_options.smokeReport + ".saved").ToStdWstring());
                    if (!std::filesystem::exists(marker))
                    {
                        std::ofstream output(marker);
                        output << "saved\n";
                        output.close();
                        CanvasAssert(output.good(), "저장 완료 시험 신호를 작성하지 못했습니다.");
                    }
                    return;
                }
                m_setupStage = 16;
                m_frame.OpenProject("open", m_frame.m_path);
            }
            break;
        case 19:
            m_setupStage = 20;
            m_frame.StartCad(false);
            break;
        case 20:
            if (m_frame.m_cadState == "failed")
            {
                throw std::runtime_error(Utf8(m_frame.m_cadDetails->GetValue()));
            }
            if (m_frame.m_cadState == "completed" && m_frame.m_cadResult.value("projection_purpose", "") == "geometry" &&
                m_frame.m_modelView->HasMesh() && !m_frame.m_modelView->IsLoading() &&
                m_frame.m_modelView->LoadedSnapshotId() == m_frame.m_cadResult.at("snapshot").at("snapshot_id"))
            {
                m_setupChecks.push_back("physical_setup_rebuild_from_embedded_step");
                FinishSmoke(true, "");
            }
            break;
        default:
            break;
        }
        return;
    }
    if (dialog->m_pending)
    {
        return;
    }
    CanvasAssert(dialog->m_error.is_null(), "물리 설정 오류 " + dialog->m_error.dump());
    auto field = [dialog](const std::string& key, const std::string& value)
    {
        static_cast<wxTextCtrl*>(dialog->m_inputs.at(key))->SetValue(Display(value));
    };
    auto apply = [dialog](const std::string& reason)
    {
        dialog->m_reason->SetValue(Display(reason));
        if (!dialog->m_apply->IsEnabled())
        {
            throw std::runtime_error("물리 설정 폼에 변경을 적용할 수 없습니다.");
        }
        SetupSmoke::Click(dialog->m_apply);
    };
    switch (m_setupStage)
    {
    case 2:
        CanvasAssert(dialog->m_stack->GetItemCount() == 2, "기본 PCB 적층 표가 열리지 않았습니다.");
        field("nominal", "1.08");
        SetupSmoke::Choose(static_cast<wxChoice*>(dialog->m_inputs.at("scope")), 2);
        m_setupStage = 3;
        apply("시험 명목 두께 자료");
        break;
    case 3:
        CanvasAssert(dialog->m_context.at("exists") == true, "명목 두께를 적용하지 못했습니다.");
        m_setupStage = 4;
        SetupSmoke::Choose(dialog->m_section, 1);
        break;
    case 4:
        field("name", "검증용 솔더마스크");
        field("offset", "0");
        field("thickness", "0.02");
        field("openings", "2 3 4 5");
        static_cast<wxCheckBox*>(dialog->m_inputs.at("include_in_export"))->SetValue(true);
        m_setupStage = 5;
        apply("시험 마스크 출처");
        break;
    case 5:
        CanvasAssert(dialog->m_stack->GetItemCount() == 3, "표면층이 단면 표에 반영되지 않았습니다.");
        m_setupStage = 6;
        SetupSmoke::Choose(dialog->m_section, 4);
        break;
    case 6:
        CanvasAssert(dialog->m_context.at("records").at("part").size() == 1, "기존 외부 물체를 표시하지 못했습니다.");
        field("name", "읽어온 외부 금속 시험 고체");
        field("x", "8");
        field("y", "4");
        field("z", "5");
        field("yaw", "90");
        SetupSmoke::Choose(static_cast<wxChoice*>(dialog->m_inputs.at("scenario_id")), 1);
        m_setupStage = 7;
        dialog->ReviewStep(wxFileName(m_frame.m_options.smokeReport).GetPathWithSep() + "fixture.step");
        break;
    case 7:
        CanvasAssert(!dialog->m_stepReview.is_null() && dialog->m_stepReview.at("faces") == 6 &&
                     dialog->m_stepReview.at("material_id").is_null(), "격리 STEP 미리보기 결과가 다릅니다.");
        m_setupStage = 8;
        apply("시험 STEP 배치 출처");
        break;
    case 8:
        CanvasAssert(dialog->m_context.at("exists") == true && !dialog->m_context.at("step").is_null(),
                     "외부 STEP 적용 후 원본 키가 없습니다.");
        m_setupChecks.push_back("physical_setup_surface_and_step_applied");
        m_setupStage = 10;
        dialog->CloseDialog();
        break;
    case 17:
        CanvasAssert(dialog->m_stack->GetItemCount() == 3 && dialog->Value("nominal") == "1.08",
                     "재열기 후 명목 두께/표면층 표가 다릅니다.");
        m_setupStage = 18;
        SetupSmoke::Choose(dialog->m_section, 4);
        break;
    case 18:
        if (!dialog->m_context.at("exists").get<bool>())
        {
            auto* record = dialog->m_record;
            for (unsigned index = 1; index < record->GetCount(); ++index)
            {
                if (record->GetString(index) == Display("읽어온 외부 금속 시험 고체"))
                {
                    SetupSmoke::Choose(record, static_cast<int>(index));
                    return;
                }
            }
            throw std::runtime_error("저장한 STEP 항목을 다시 읽지 못했습니다.");
        }
        CanvasAssert(dialog->Value("material_id").empty() && dialog->Value("yaw") == "90" &&
                     Utf8(dialog->m_review->GetValue()).find("시험 STEP 배치 출처") != std::string::npos &&
                     Utf8(dialog->m_review->GetValue()).find("SHA-256") != std::string::npos,
                     "STEP 원본 해시, 물성 미정 또는 출처가 재열기에서 사라졌습니다.");
        m_setupChecks.push_back("physical_setup_saved_reopen_sources_and_missing");
        m_setupStage = 19;
        dialog->CloseDialog();
        break;
    }
}
