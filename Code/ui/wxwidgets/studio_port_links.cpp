/** @file @brief 편집 급전의 적용된 단자, 표시와 진단을 원본 ID로 연결한다. */
#include "studio_internal.h"
#include "editor_sync.h"
#include "frequency_display.h"
#include "studio_shell.h"
#include "studio_theme.h"

void StudioFrame::BuildPortLinks(wxSizer& form)
{
    m_portLinks = new wxPanel(m_properties);
    StudioTheme::BindSurface(*m_portLinks);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    m_portLinkStatus = new wxStaticText(m_portLinks, wxID_ANY, wxEmptyString);
    StudioTheme::BindSecondary(*m_portLinkStatus);
    layout->Add(m_portLinkStatus, 0, wxEXPAND | wxBOTTOM, FromDIP(StudioTheme::InputGap));

    auto* actions = new wxFlexGridSizer(2, FromDIP(StudioTheme::InputGap), FromDIP(StudioTheme::InputGap));
    actions->AddGrowableCol(0);
    actions->AddGrowableCol(1);
    const auto add = [this, actions](const char* label)
    {
        auto* button = new wxButton(m_portLinks, wxID_ANY, Display(label));
        StudioTheme::Button(*button);
        actions->Add(button, 0, wxEXPAND);
        return button;
    };
    m_portSignal = add("신호 도체");
    m_portReference = add("기준 도체");
    m_portReturn = add("급전으로 이동");
    m_portProblem = add("관련 진단");
    m_portModel = add("3D 단자 보기");
    m_portPick = add("도면에서 단자 선택");
    layout->Add(actions, 0, wxEXPAND);
    m_portLinks->SetSizer(layout);
    form.Add(m_portLinks, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(StudioTheme::PanelPadding));
    m_portLinks->Hide();

    const auto bindTerminal = [this](wxButton& button, std::size_t index)
    {
        button.Bind(wxEVT_BUTTON,
                    [this, source = &button, index](wxCommandEvent&)
                    {
                        if (const auto* port = RelatedPort())
                        {
                            FollowPortLink(*source, {{"kind", "geometry"}, {"id", port->at("terminal_ids").at(index)}});
                        }
                    });
    };
    bindTerminal(*m_portSignal, 0);
    bindTerminal(*m_portReference, 1);
    m_portReturn->Bind(wxEVT_BUTTON,
                      [this](wxCommandEvent&)
                      {
                          if (const auto* port = RelatedPort())
                          {
                              FollowPortLink(*m_portReturn, {{"kind", "port"}, {"id", port->at("id")}});
                          }
                      });
    m_portProblem->Bind(wxEVT_BUTTON,
                       [this](wxCommandEvent&)
                       {
                           const auto* port = RelatedPort();
                           const long index = port == nullptr ? -1 : FindPortProblem(*port);
                           if (m_busy || index < 0)
                           {
                               return;
                           }
                           auto& pane = m_manager->GetPane(m_bottom);
                           if (!pane.IsShown())
                           {
                               pane.Show();
                               m_manager->Update();
                           }
                           m_bottom->SetSelection(0);
                           m_problems->SetItemState(index, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED,
                                                   wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
                           m_problems->EnsureVisible(index);
                           m_problems->SetFocus();
                       });
    m_portPick->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        wxMenu menu;
                        menu.Append(1, Display("신호 단자 선택"));
                        menu.Append(2, Display("기준 단자 선택"));
                        const int selected = GetPopupMenuSelectionFromUser(menu);
                        if (selected != wxID_NONE)
                        {
                            BeginPortPick(selected == 1 ? "positive_geometry_id" : "reference_geometry_id");
                        }
                    });
    m_portModel->Bind(wxEVT_BUTTON,
                     [this](wxCommandEvent&)
                     {
                         if (!m_busy && CurrentDisplayMesh())
                         {
                             m_views->SetSelection(1);
                         }
                     });
}

const Json* StudioFrame::RelatedPort() const
{
    const auto kind = m_selection.value("kind", "");
    if ((kind != "port" && kind != "geometry") || !Studio::EditableProject(m_editor, m_scene, m_project, m_revision))
    {
        return nullptr;
    }
    const auto& id = m_selection.at("id");
    const auto port = m_editor.find("port_links");
    if (port == m_editor.end())
    {
        return nullptr;
    }
    const auto& terminals = port->at("terminal_ids");
    return port->at("id") == id || std::find(terminals.begin(), terminals.end(), id) != terminals.end()
        ? &*port : nullptr;
}

bool StudioFrame::CurrentDisplayMesh() const
{
    return m_modelView->HasMesh() && !m_modelView->IsLoading() && !m_displayResult.empty() &&
           m_displayResult.at("snapshot").at("revision_id") == m_revision &&
           m_displayResult.at("snapshot").at("snapshot_id") == m_modelView->LoadedSnapshotId();
}

/** @brief 적용된 참조에만 강조와 이동을 연결하고 비활성 상태의 근거를 화면에 남긴다. */
void StudioFrame::UpdatePortLinks()
{
    const auto* port = RelatedPort();
    const bool visible = port != nullptr;
    const bool selectingPort = visible && m_selection.at("kind") == "port";
    std::vector<std::string> terminals;
    std::vector<std::string> modelSources;
    if (selectingPort)
    {
        terminals = port->at("terminal_ids").get<std::vector<std::string>>();
        if (CurrentDisplayMesh())
        {
            for (const auto& id : terminals)
            {
                if (!m_modelView->SourceRole(id).empty())
                {
                    modelSources.push_back(id);
                }
            }
        }
    }
    m_canvas->SetInspection(terminals, std::nullopt);
    m_modelView->SetRelatedSelection(modelSources, visible && !CurrentDisplayMesh());
    const int page = m_views->GetSelection();
    const bool showLinks = visible && (page == 0 || page == 1);
    const bool visibilityChanged = m_portLinks->Show(showLinks);
    if (!showLinks)
    {
        if (visibilityChanged)
        {
            m_properties->Layout();
        }
        return;
    }

    const bool ready = m_connected && !m_busy && m_setupDialog == nullptr;
    m_portSignal->Show(selectingPort);
    m_portReference->Show(selectingPort);
    m_portModel->Show(selectingPort);
    m_portPick->Show(selectingPort);
    m_portPick->Enable(ready);
    m_portReturn->Show(!selectingPort);
    m_portReturn->SetToolTip(Display(port->at("label").get<std::string>()));
    m_portReturn->Enable(ready);
    const long problem = FindPortProblem(*port);
    const std::string problemReason =
        m_problemRevision.empty() ? "관련 진단을 보려면 해석 입력 검사를 실행하세요."
        : m_problemRevision != m_revision ? "이전 개정의 진단입니다. 다시 검사하세요."
        : problem < 0 ? "표시된 검사 결과에 관련 진단이 없습니다." : "문제 목록에서 관련 진단으로 이동합니다.";
    m_portProblem->SetToolTip(Display(problemReason));
    m_portProblem->Enable(ready && problem >= 0);

    std::string status = problem < 0 ? problemReason : "";
    if (selectingPort)
    {
        auto marker = m_scene.value("port_marker", Json::object());
        for (const auto& candidate : m_scene.value("port_markers", Json::array()))
        {
            if (candidate.at("id") == port->at("id"))
            {
                marker = candidate;
                break;
            }
        }
        std::string markerReason = marker.value("reason", std::string());
        if (markerReason.rfind("치수에 표시할 값이 없습니다", 0) == 0)
        {
            markerReason = "급전 시작/끝 좌표가 미정입니다.";
        }
        if (markerReason.empty() && !m_canvas->PortMarkerVisible(port->at("id").get<std::string>()))
        {
            markerReason = "표시할 수 있는 양쪽 도체가 필요합니다.";
        }
        if (!markerReason.empty())
        {
            status = "2D 표식: " + markerReason + (status.empty() ? "" : "\n" + status);
        }
        const std::string modelReason =
            !m_modelView->HasMesh() ? "3D 형상을 먼저 생성하세요."
            : !CurrentDisplayMesh() ? "현재 개정으로 3D를 갱신하세요."
            : modelSources.empty() ? "현재 3D에 단자 바디가 없습니다."
            : modelSources.size() < terminals.size() ? "현재 3D에서 표시 가능한 단자만 강조합니다."
            : "현재 3D에서 양쪽 단자 바디를 강조합니다.";
        if (modelSources.size() != terminals.size())
        {
            status += (status.empty() ? "" : "\n") + modelReason;
        }
        m_portModel->SetToolTip(Display(modelReason));
        m_portModel->Enable(ready && !modelSources.empty());
        const std::array<wxButton*, 2> buttons{m_portSignal, m_portReference};
        const std::array<std::string, 2> roles{"신호", "기준"};
        std::string connections;
        for (std::size_t i = 0; i < buttons.size(); ++i)
        {
            const auto& id = terminals.at(i);
            const auto& items = m_editor.at("items");
            const auto conductor = std::find_if(items.begin(), items.end(), [&id](const Json& item)
            {
                return item.at("id") == id && item.at("kind") == "geometry";
            });
            const auto reason = m_canvas->ConductorDisplayReason(id);
            buttons[i]->SetToolTip(Display(conductor == items.end() ? "참조 도체가 없습니다."
                : conductor->at("label").get<std::string>() + (reason.empty() ? "" : "\n" + reason)));
            buttons[i]->Enable(ready && conductor != items.end());
            const std::string name = conductor == items.end() ? "미정" : conductor->at("label").get<std::string>();
            connections += roles[i] + " 도체: " + name + "\n";
        }
        const auto impedance = port->value("reference_impedance_ohm", Json(nullptr));
        const auto low = port->value("frequency_min_hz", Json(nullptr));
        const auto high = port->value("frequency_max_hz", Json(nullptr));
        const auto sourceCount = port->value("source_ref_count", std::size_t(0));
        std::string summary = "적용 Z0: " + (impedance.is_number() ? impedance.dump() + " ohm" : "미정") +
            "\n유효 대역: " + (low.is_number() && high.is_number() ? StudioFrequency::Range(low, high) : "미정") +
            "\n저항 / 대역 출처: " + (sourceCount > 0 ? std::to_string(sourceCount) + "개" : "미정");
        status = summary + "\n" + connections + status;
    }
    else
    {
        const auto reason = m_canvas->ConductorDisplayReason(m_selection.at("id").get<std::string>());
        if (!reason.empty())
        {
            status = reason + (status.empty() ? "" : "\n" + status);
        }
    }
    m_portLinkStatus->SetLabel(Display(status));
    m_portLinkStatus->Wrap(std::max(FromDIP(220), m_properties->GetClientSize().x - FromDIP(32)));
    m_portLinkStatus->Show(!status.empty());
    m_portLinks->Layout();
    m_properties->Layout();
}

/** @brief 적용 전 포트 초안을 유지하면서 2D 원본 도체를 한 번 선택한다. */
void StudioFrame::BeginPortPick(const std::string& field)
{
    if (m_busy || !m_portPick->IsEnabled() || m_selection.value("kind", "") != "port")
    {
        return;
    }
    m_views->SetSelection(0);
    m_canvas->CancelGesture();
    m_portPickField = field;
    m_canvas->onPickConductor = [this](const std::string& id)
    {
        const auto field = m_portPickField;
        const auto other = field == "positive_geometry_id" ? "reference_geometry_id" : "positive_geometry_id";
        if (m_editorPanel->FieldValue(other) == id)
        {
            m_canvasHint->SetLabel(Display("양쪽 단자는 서로 다른 도체여야 합니다. 다른 도체를 선택하거나 Esc로 돌아가세요."));
            return;
        }
        m_editorPanel->SetFieldValue(field, id);
        EndPortPick(true);
    };
    m_canvasHint->SetLabel(Display(field == "positive_geometry_id"
        ? "신호 도체를 선택하세요. Esc로 포트 입력에 돌아갑니다."
        : "기준 도체를 선택하세요. Esc로 포트 입력에 돌아갑니다."));
    m_canvas->SetFocus();
}

void StudioFrame::EndPortPick(bool restoreFocus)
{
    if (m_portPickField.empty())
    {
        return;
    }
    m_canvas->onPickConductor = {};
    m_portPickField.clear();
    m_canvasHint->SetLabel(Display("선택: 객체 속성 / 휠: 확대/축소 / 가운데 버튼: 이동 / Esc: 취소"));
    if (restoreFocus)
    {
        m_shell->ShowProperties(false);
        m_portPick->SetFocus();
    }
}

void StudioFrame::FollowPortLink(wxButton& source, const Json& selection)
{
    if (m_busy || !source.IsEnabled())
    {
        return;
    }
    if (!ConfirmDiscard())
    {
        source.SetFocus();
        return;
    }
    const bool toPort = selection.at("kind") == "port";
    const auto* port = RelatedPort();
    const bool reference = toPort && port && port->at("terminal_ids").at(1) == m_selection.at("id");
    RefreshEditor(selection,
                  [this, toPort, reference]()
                  {
                      Ready("급전과 단자의 원본 선택을 이동했습니다.");
                      m_shell->ShowProperties(false);
                      auto* next = toPort ? (reference ? m_portReference : m_portSignal) : m_portReturn;
                      if (next->IsEnabled())
                      {
                          next->SetFocus();
                      }
                  });
}
