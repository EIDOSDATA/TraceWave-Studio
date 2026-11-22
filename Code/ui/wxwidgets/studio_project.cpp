/** @file @brief 주 창의 project 책임을 구현한다. */
#include "studio_internal.h"
#include "editor_sync.h"
#include "output_controller.h"

void StudioFrame::OpenProject(const std::string& mode, const std::string& path, const std::string& name,
                              std::function<void()> opened)
{
    if ((m_pcbFeatureUncertain || m_pcbImportUncertain || m_measurementUncertain) && path != m_path)
    {
        Log("이전 PCB 편집 결과를 확인한 뒤 다른 프로젝트를 여세요. 설계 메뉴의 PCB 형상에서 같은 영수증을 조회할 수 "
            "있습니다.");
        return;
    }
    if (m_output && m_output->Active() && path != m_path)
    {
        Log("출력 요청의 접수/완료 여부를 확인한 뒤 다른 프로젝트를 여세요. 기존 요청 키와 파일은 보존합니다.");
        return;
    }
    if (m_cadPreparing || !m_cadTask.Id().empty() || m_modelView->IsLoading() || m_cadRestoring ||
        m_solverWorkflow.Active() || m_solverRestoring)
    {
        Log("CAD/해석 작업 또는 결과 읽기가 끝난 뒤 프로젝트를 전환하세요.");
        return;
    }
    m_canvas->CancelGesture();
    if (opened)
    {
        m_projectOpenCompletion = std::move(opened);
        m_projectOpenCompletionPath = path;
    }
    else if (m_projectOpenCompletionPath != path)
    {
        m_projectOpenCompletion = {};
        m_projectOpenCompletionPath.clear();
    }
    m_busy = true;
    UpdateControls();
    Json input{{"open_mode", mode}, {"path", path}};
    if (m_pagedEditView)
    {
        input["result_mode"] = "summary";
    }
    if (mode == "create")
    {
        input["name"] = name;
    }
    Send("project.open", input, true, Json::object(),
         [this, path](const Json& task)
         {
             WaitJob(task,
                     [this, path](const Json& result)
                     {
                         const auto openedProject = result.at("project_id").get<std::string>();
                         if (m_project != openedProject)
                         {
                             m_solverDraft = Json::object();
                             m_solverRepairPending = false;
                         }
                         m_project = openedProject;
                         m_revision = result.at("revision_id").get<std::string>();
                         m_savedRevision = result.at("saved_revision").get<std::string>();
                         ResetNetwork();
                         m_path = path;
                         ReadPcbFeatureRecovery();
                         ReadPcbImportRecovery();
                         ReadMeasurementRecovery();
                         PrepareOutputRecovery();
                         m_scene = Json::object();
                         m_modelView->Clear();
                         m_cadResult = Json::object();
                         m_displayResult = Json::object();
                         m_loadingModel = Json::object();
                         m_solverChart->Clear();
                         m_solverResult = Json::object();
                         m_solverSamples = Json::object();
                         m_solverLastAttempt = Json::object();
                         UpdateSolverView();
                         m_solverViewState->SetLabel(
                             Display("표시할 해석 결과가 없습니다."));
                         SolverStatus("idle", "선택한 프로젝트의 완료 결과를 조회합니다.");
                         m_problemRevision.clear();
                         m_diagnostics = Json::array();
                         m_diagnosticCount = 0;
                         m_diagnosticsTruncated = false;
                         RefreshEditor(Json{{"kind", "project"}, {"id", m_project}},
                                       [this, path]()
                                       {
                                           Ready("프로젝트를 열었습니다.");
                                           RestoreCad();
                                           RestoreSolver();
                                           if (m_projectOpenCompletion && m_projectOpenCompletionPath == path)
                                           {
                                               auto opened = std::move(m_projectOpenCompletion);
                                               m_projectOpenCompletionPath.clear();
                                               opened();
                                           }
                                           m_smoke->OnOpened();
                                       });
                     });
         });
}

void StudioFrame::RefreshProject()
{
    m_refreshing = true;
    m_name->ChangeValue(Display(m_editor.at("metadata").at("name").get<std::string>()));
    m_description->ChangeValue(Display(m_editor.at("metadata").at("description").get<std::string>()));
    RebuildNavigation();
    std::string selectedLabel = "프로젝트 속성";
    const bool metadata = m_selection.at("kind") == "project";
    if (!metadata)
    {
        for (const auto& item : m_editor.at("items"))
        {
            if (item.at("kind") == m_selection.at("kind") && item.at("id") == m_selection.at("id"))
            {
                selectedLabel = item.at("label").get<std::string>();
                break;
            }
        }
    }
    if (m_selection.at("kind").get<std::string>().rfind("new_", 0) == 0)
    {
        selectedLabel = "새 객체 / 미적용 입력";
    }
    m_selectionLabel->SetLabel(Display(selectedLabel));
    m_selectionLabel->SetToolTip(Display(selectedLabel));
    m_metadataDiagnostic->Hide();
    m_metadataPanel->Show(metadata);
    m_editorPanel->Show(!metadata);
    m_editorPanel->SetFields(m_editor.at("selection").at("fields"), m_editor.at("selection"),
                             m_editor.value("coordinate_choices", Json::array()));
    m_properties->Layout();
    m_refreshing = false;
    UpdateDraftState();
}

void StudioFrame::SaveProject()
{
    if (!Studio::EditableProject(m_editor, m_scene, m_project, m_revision))
    {
        Log("현재 프로젝트의 속성/2D 조회가 완료된 뒤 저장할 수 있습니다.");
        UpdateControls();
        return;
    }
    if (HasDraft())
    {
        ApplyCurrent(
            [this]()
            {
                SaveProject();
            });
        return;
    }
    /** @brief 미게시 저장 실패에서 마지막 저장 기준과 수동 재시도를 유지한다. */
    const auto unpublished = [this](const Json& diagnostic)
    {
        const auto code = diagnostic.value("code", "");
        const auto details = diagnostic.value("details", Json::object());
        const bool needsFreeSpace = code == "E_RESOURCE" && details.contains("required_free_bytes") &&
                                    details.contains("free_bytes");
        if (!needsFreeSpace && !(code == "E_DISK" && details.value("committed", Json()) == false))
        {
            return false;
        }
        m_busy = false;
        UpdateControls();
        SetStatusText(Display("저장 실패"), 0);
        Log(needsFreeSpace
                ? "마지막 저장본과 현재 편집을 보존했습니다. 디스크 공간을 확보한 뒤 다시 저장하세요."
                : "마지막 저장본과 현재 편집을 보존했습니다. 디스크 여유 공간과 쓰기 권한을 확인한 뒤 다시 저장하세요.");
        m_smoke->OnSaveNotPublished();
        return true;
    };
    m_busy = true;
    UpdateControls();
    Send("project.save", Json{{"expected_revision", m_revision}}, true, Context(),
         [this, unpublished](const Json& task)
         {
             WaitJob(task,
                     [this](const Json& result)
                     {
                         m_savedRevision = result.at("saved_revision").get<std::string>();
                         m_editor["saved_revision"] = m_savedRevision;
                         Ready("현재 설계 버전을 저장했습니다.");
                         m_smoke->OnSaved();
                     },
                     unpublished);
         },
         [this, unpublished](const Json& error)
         {
             for (const auto& diagnostic : error.value("data", Json::object()).value("diagnostics", Json::array()))
             {
                 if (unpublished(diagnostic))
                 {
                     return;
                 }
             }
             Failure(error.value("message", std::string("저장 요청에 실패했습니다.")));
         });
}

void StudioFrame::Snapshot()
{
    if (!Studio::EditableProject(m_editor, m_scene, m_project, m_revision))
    {
        Log("현재 프로젝트의 속성/2D 조회가 완료된 뒤 스냅샷을 만들 수 있습니다.");
        UpdateControls();
        return;
    }
    if (HasDraft())
    {
        ApplyCurrent(
            [this]()
            {
                Snapshot();
            });
        return;
    }
    m_busy = true;
    UpdateControls();
    Send("snapshot.create", Json{{"expected_revision", m_revision}, {"description", "GUI에서 생성한 스냅샷"}}, true,
         Context(),
         [this](const Json& task)
         {
             WaitJob(task,
                     [this](const Json& result)
                     {
                         m_snapshot = result.at("snapshot_id").get<std::string>();
                         Ready("스냅샷을 만들었습니다: " + m_snapshot);
                         m_smoke->OnSnapshotCreated();
                     });
         });
}
