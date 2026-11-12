/** @file @brief 주 창의 project 책임을 구현한다. */
#include "studio_internal.h"

void StudioFrame::OpenProject(const std::string& mode, const std::string& path, const std::string& name)
{
    if (m_cadPreparing || !m_cadTask.Id().empty() || m_modelView->IsLoading() || m_cadRestoring ||
        m_solverWorkflow.Active() || m_solverRestoring)
    {
        Log("CAD/해석 작업 또는 결과 읽기가 끝난 뒤 프로젝트를 전환하세요.");
        return;
    }
    m_canvas->CancelGesture();
    m_busy = true;
    UpdateControls();
    Json input{{"open_mode", mode}, {"path", path}};
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
                         m_project = result.at("project_id").get<std::string>();
                         m_revision = result.at("revision_id").get<std::string>();
                         m_path = path;
                         m_scene = Json::object();
                         m_modelView->Clear();
                         m_cadResult = Json::object();
                         m_displayResult = Json::object();
                         m_solverChart->Clear();
                         m_solverResult = Json::object();
                         m_solverSamples = Json::object();
                         m_solverViewState->SetLabel(
                             Display("결과 없음 / 단일 포트 PCB 계산 / IFA 및 방사 정확도 검증 전"));
                         SolverStatus("idle", "선택한 프로젝트의 완료 결과를 조회합니다.");
                         m_problemRevision.clear();
                         m_diagnostics = Json::array();
                         m_diagnosticCount = 0;
                         m_diagnosticsTruncated = false;
                         RefreshEditor(Json{{"kind", "project"}, {"id", m_project}},
                                       [this]()
                                       {
                                           Ready("프로젝트를 열었습니다.");
                                           RestoreCad();
                                           RestoreSolver();
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
    m_tree->Freeze();
    m_tree->DeleteAllItems();
    const wxTreeItemId root =
        m_tree->AddRoot(m_name->GetValue(), 0, 0, new SelectionData(Json{{"kind", "project"}, {"id", m_project}}));
    std::map<std::string, wxTreeItemId> categories;
    const std::pair<const char*, const char*> names[] = {
        {"parameter", "매개변수"}, {"board", "기판"},    {"material", "재료"}, {"layer", "적층"},
        {"net", "네트"},           {"geometry", "형상"}, {"port", "포트"}};
    for (const auto& name : names)
    {
        categories.emplace(name.first, m_tree->AppendItem(root, Display(name.second), 0, 0));
    }
    wxTreeItemId selected = root;
    std::string selectedLabel = "프로젝트 속성";
    for (const auto& item : m_editor.at("items"))
    {
        const std::string kind = item.at("kind").get<std::string>();
        if (kind == "project")
        {
            continue;
        }
        const Json selection{{"kind", kind}, {"id", item.at("id")}};
        const auto parent = categories.find(kind);
        const wxTreeItemId node =
            m_tree->AppendItem(parent == categories.end() ? root : parent->second,
                               Display(item.at("label").get<std::string>()), -1, -1, new SelectionData(selection));
        if (selection == m_selection)
        {
            selected = node;
            selectedLabel = item.at("label").get<std::string>();
        }
    }
    if (m_selection.at("kind").get<std::string>().rfind("new_", 0) == 0)
    {
        const std::string kind = m_selection.at("kind").get<std::string>().substr(4);
        selectedLabel = kind == "parameter"
                            ? "새 매개변수"
                            : (kind == "material" ? "새 재료" : (kind == "net" ? "새 네트" : "새 급전 포트"));
        selected =
            m_tree->AppendItem(categories.at(kind), Display(selectedLabel), -1, -1, new SelectionData(m_selection));
    }
    m_tree->Expand(root);
    if (m_tree->GetItemParent(selected).IsOk())
    {
        m_tree->Expand(m_tree->GetItemParent(selected));
    }
    m_tree->SelectItem(selected);
    m_tree->Thaw();
    m_selectionLabel->SetLabel(Display(selectedLabel));
    const bool metadata = m_selection.at("kind") == "project";
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
    if (HasDraft())
    {
        ApplyCurrent(
            [this]()
            {
                SaveProject();
            });
        return;
    }
    m_busy = true;
    UpdateControls();
    Send("project.save", Json{{"expected_revision", m_revision}}, true, Context(),
         [this](const Json& task)
         {
             WaitJob(task,
                     [this](const Json& result)
                     {
                         m_savedRevision = result.at("saved_revision").get<std::string>();
                         m_editor["saved_revision"] = m_savedRevision;
                         Ready("현재 설계 버전을 저장했습니다.");
                         m_smoke->OnSaved();
                     });
         });
}

void StudioFrame::Snapshot()
{
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
