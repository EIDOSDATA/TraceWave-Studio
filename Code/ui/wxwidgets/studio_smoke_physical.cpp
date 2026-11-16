/** @file @brief Windows의 물리 설정과 실제 CAD/저장/재열기 경로를 검사한다. */
#include "studio_internal.h"
#include "physical_setup_dialog.h"
#include "setup_smoke_support.h"

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
