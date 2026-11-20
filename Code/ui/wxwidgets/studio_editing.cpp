/** @file @brief 주 창의 editing 책임을 구현한다. */
#include "studio_internal.h"
#include "editor_sync.h"
#include "studio_shell.h"

/** @brief 전체 원본 대신 목록과 선택 객체의 작은 편집 DTO만 조회한다. */
void StudioFrame::RefreshEditor(const Json& selection, std::function<void()> completed)
{
    m_busy = true;
    UpdateControls();
    const auto project = m_project;
    const auto revision = m_revision;
    Json input{{"expected_revision", revision}, {"selection", selection}};
    if (m_extendedEditView)
    {
        input["display_profile"] = Studio::EditViewTransportProfile;
    }
    Send("editor.get", input, false, Context(),
         [this, project, revision, completed](const Json& result)
         {
             if (m_closing || project != m_project || revision != m_revision)
             {
                 return;
             }
             if (!Studio::MatchesEditor(result, project, revision))
             {
                 throw std::runtime_error("Unexpected editor profile or revision.");
             }
             m_editor = result;
             m_selection = result.at("selection");
             m_selection.erase("fields");
             m_modelView->SetSelection(m_selection.value("id", ""));
             RefreshProject();
             RefreshScene(completed);
         });
}

/** @brief 같은 revision의 표시 DTO는 재사용하고 변경된 표시 데이터만 다시 읽는다. */
void StudioFrame::RefreshScene(std::function<void()> completed)
{
    if (Studio::MatchesCanvas(m_scene, m_project, m_revision))
    {
        m_canvas->SetSelection(m_selection.value("kind", "") == "geometry" ? m_selection.value("id", "") : "");
        RefreshDimensions();
        completed();
        return;
    }
    const auto project = m_project;
    const auto revision = m_revision;
    Json input{{"expected_revision", revision}};
    if (m_extendedEditView)
    {
        input["display_profile"] = Studio::EditViewTransportProfile;
    }
    Send("canvas.get", input, false, Context(),
         [this, project, revision, completed](const Json& result)
         {
             if (m_closing || project != m_project || revision != m_revision)
             {
                 return;
             }
             if (!Studio::MatchesCanvas(result, project, revision))
             {
                 throw std::runtime_error("Unexpected canvas profile, unit or revision.");
             }
             const bool first = m_scene.empty();
             m_canvas->SetScene(result);
             m_scene = result;
             m_layerChoice->Clear();
             m_layerIds.clear();
             for (const auto& layer : result.at("layers"))
             {
                 if (layer.at("role") == "conductor")
                 {
                     m_layerIds.push_back(layer.at("id"));
                     m_layerChoice->Append(Display(layer.at("label").get<std::string>()));
                 }
             }
             auto active = std::find(m_layerIds.begin(), m_layerIds.end(), m_activeLayer);
             if (active == m_layerIds.end())
             {
                 m_activeLayer = m_layerIds.empty() ? "" : m_layerIds.front();
                 active = m_layerIds.begin();
             }
             if (!m_layerIds.empty())
             {
                 m_layerChoice->SetSelection(static_cast<int>(active - m_layerIds.begin()));
             }
             m_canvas->SetDrawingLayer(m_activeLayer);
             RefreshLayerList();
             m_canvas->SetSelection(m_selection.value("kind", "") == "geometry" ? m_selection.value("id", "") : "");
             if (first)
             {
                 m_canvas->FitView();
                 m_canvasHint->SetLabel(
                     Display(m_activeLayer.empty()
                                 ? "도체층을 추가한 뒤 선 또는 원호 도구를 선택하세요."
                                 : "선 또는 원호 도구를 선택하세요. 휠: 확대/축소, 가운데 버튼: 이동, Esc: 취소"));
             }
             for (const auto& omission : result.at("omissions"))
             {
                 Log("표시 생략: " + omission.at("message").get<std::string>());
             }
             ShowProblems();
             RefreshDimensions();
             completed();
         });
}

/** @brief 비동기 조회 중 비활성화한 트리의 키보드 초점을 완료 후 복원한다. */
void StudioFrame::SelectObject(const Json& selection, bool restoreTreeFocus)
{
    RefreshEditor(selection,
                  [this, restoreTreeFocus]()
                  {
                      Ready("선택한 객체의 속성을 읽었습니다.");
                      if (restoreTreeFocus)
                      {
                          m_tree->SetFocus();
                      }
                      else if (m_shell)
                      {
                          m_shell->ShowProperties(false);
                      }
                      m_smoke->OnSelected();
                  });
}

/** @brief 폼 변경분을 한 서비스 명령으로 적용하고 권위 DTO로 다시 표시한다. */
void StudioFrame::ApplyCurrent(std::function<void()> completed, std::function<void(const Json&)> rejected)
{
    if (!Studio::EditableProject(m_editor, m_scene, m_project, m_revision))
    {
        const Json error{
            {"code", "E_CONFLICT"},
            {"message", "현재 프로젝트의 속성/2D 조회가 완료되지 않아 적용하지 않았습니다. F5로 다시 읽으세요."}};
        if (rejected)
        {
            rejected(error);
        }
        Log(error.at("message").get<std::string>());
        UpdateControls();
        return;
    }
    Json values = Json::object();
    try
    {
        if (m_selection.at("kind") == "project")
        {
            const std::string name = Utf8(m_name->GetValue());
            const std::string description = Utf8(m_description->GetValue());
            if (m_editor.at("metadata").at("name") != name)
            {
                values["name"] = name;
            }
            if (m_editor.at("metadata").at("description") != description)
            {
                values["description"] = description;
            }
        }
        else
        {
            values = m_editorPanel->Changes();
        }
    }
    catch (const std::exception& error)
    {
        m_editorPanel->ShowDiagnostic("", error.what());
        Failure(error.what());
        return;
    }
    if (values.empty() && m_selection.at("kind").get<std::string>().rfind("new_", 0) != 0)
    {
        completed();
        return;
    }
    m_busy = true;
    UpdateControls();
    Json target = m_selection;
    if (target.at("kind").get<std::string>().rfind("new_", 0) == 0)
    {
        target["kind"] = target.at("kind").get<std::string>().substr(4);
    }
    Send(
        "editor.apply",
        Json{{"expected_revision", m_revision}, {"command_id", Uuid()}, {"selection", m_selection}, {"values", values}},
        true, Context(),
        [this, completed, target](const Json& result)
        {
            m_revision = result.at("new_revision").get<std::string>();
            RefreshEditor(target,
                          [this, completed]()
                          {
                              Ready("변경을 적용했습니다.");
                              completed();
                          });
        },
        std::move(rejected));
}

void StudioFrame::ApplyProperties()
{
    if (m_project.empty())
    {
        return;
    }
    ApplyCurrent(
        [this]()
        {
            m_smoke->OnApplied();
        });
}

/** @brief undo/redo의 원본과 이력은 서비스가 소유하며 GUI에는 결과 개정만 반영한다. */
void StudioFrame::History(const std::string& method, std::function<void()> completed)
{
    if (!Studio::EditableProject(m_editor, m_scene, m_project, m_revision))
    {
        Log("현재 프로젝트의 속성/2D 조회가 완료된 뒤 이력을 변경할 수 있습니다.");
        UpdateControls();
        return;
    }
    if (!ConfirmDiscard())
    {
        return;
    }
    m_busy = true;
    UpdateControls();
    const Json previousSelection = m_selection;
    Send(method, Json{{"expected_revision", m_revision}, {"command_id", Uuid()}}, true, Context(),
         [this, completed, previousSelection](const Json& result)
         {
             m_revision = result.at("new_revision").get<std::string>();
             RefreshEditor(Json{{"kind", "project"}, {"id", m_project}},
                           [this, completed, previousSelection]()
                           {
                               const auto finish = [this, completed]()
                               {
                                   Ready("편집 이력을 적용했습니다.");
                                   if (completed)
                                   {
                                       completed();
                                   }
                               };
                               for (const auto& item : m_editor.at("items"))
                               {
                                   if (item.at("kind") == previousSelection.value("kind", "") &&
                                       item.at("id") == previousSelection.value("id", ""))
                                   {
                                       RefreshEditor(previousSelection, finish);
                                       return;
                                   }
                               }
                               finish();
                           });
         });
}
