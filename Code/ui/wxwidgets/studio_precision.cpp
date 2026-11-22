/** @file @brief 정밀 편집 메뉴, 선택 필터와 서비스 치수를 주 작업 공간에 연결한다. */
#include "studio_internal.h"
#include "editor_sync.h"
#include "precision_dialog.h"
#include "smart_dimension_dialog.h"
#include "studio_theme.h"

void StudioFrame::BuildPrecisionTools(wxWindow* parent, wxSizer* layout)
{
    GetMenuBar()->GetMenu(1)->AppendSeparator();
    GetMenuBar()->GetMenu(1)->Append(IdPrecision, Display("정밀 2D 편집 / 치수"));
    AddTool(parent, layout, IdPrecision, "정밀 편집");
    const int smartId = wxWindow::NewControlId();
    GetMenuBar()->GetMenu(1)->Append(smartId, Display("스마트 치수"));
    auto* smart = new wxButton(parent, smartId, Display("스마트 치수"));
    smart->SetName("smart.dimension.open");
    StudioTheme::Button(*smart);
    layout->Add(smart, 0, wxALL | wxALIGN_CENTER_VERTICAL, FromDIP(4));
    const auto canOpen = [this]()
    {
        return !m_busy && m_connected && !m_closing && !m_project.empty() && !m_setupDialog &&
               m_precisionSupported && Studio::EditableProject(m_editor, m_scene, m_project, m_revision);
    };
    const auto open = [this, canOpen]()
    {
        if (!canOpen())
        {
            return;
        }
        const auto project = m_project, revision = m_revision;
        const auto selection = m_selection;
        m_busy = true;
        UpdateControls();
        Send("precision.smart.get", {{"expected_revision", revision}}, false, Context(),
            [this, project, revision, selection](const Json& result)
            {
                CallAfter([this, project, revision, selection, result]()
                {
                    m_busy = false;
                    if (m_closing || !m_connected || m_project != project || m_revision != revision)
                    {
                        UpdateControls();
                        return;
                    }
                    ShowObjectTool(std::make_unique<SmartDimensionDialog>(this, result, m_scene, selection,
                                                                         ObjectToolGateway()), selection);
                });
            },
            [this](const Json& error)
            {
                Failure(DiagnosticMessage(error));
            });
    };
    const auto activate = [this, canOpen, open](wxCommandEvent&)
    {
        if (canOpen() && HasDraft())
        {
            ApplyCurrent(open);
            return;
        }
        open();
    };
    smart->Bind(wxEVT_BUTTON, activate);
    Bind(wxEVT_MENU, activate, smartId);
    Bind(wxEVT_UPDATE_UI, [canOpen](wxUpdateUIEvent& event)
    {
        event.Enable(canOpen());
    }, smartId);
    auto* filter = new wxChoice(parent, wxID_ANY);
    const std::vector<std::string> kinds{"", "line_path", "arc_path", "planar_region", "pad", "via"};
    for (const auto* label : {"모두 선택", "선만", "원호만", "면만", "패드만", "비아만"})
    {
        filter->Append(Display(label));
    }
    filter->SetSelection(0);
    filter->SetName("canvas.selection_filter");
    layout->Add(filter, 0, wxALL | wxALIGN_CENTER_VERTICAL, FromDIP(4));
    auto* active = new wxCheckBox(parent, wxID_ANY, Display("활성 층만 선택"));
    active->SetName("canvas.active_layer_only");
    layout->Add(active, 0, wxALL | wxALIGN_CENTER_VERTICAL, FromDIP(4));
    const auto changed = [this, filter, active, kinds](wxCommandEvent&)
    {
        m_canvas->SetSelectionFilter(kinds.at(filter->GetSelection()), active->GetValue());
    };
    filter->Bind(wxEVT_CHOICE, changed);
    active->Bind(wxEVT_CHECKBOX, changed);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            OpenPrecision();
        },
        IdPrecision);
}

void StudioFrame::OpenPrecision()
{
    if (m_busy || !m_connected || !m_precisionSupported || m_project.empty() || m_setupDialog ||
        !Studio::EditableProject(m_editor, m_scene, m_project, m_revision))
    {
        return;
    }
    if (HasDraft())
    {
        ApplyCurrent(
            [this]()
            {
                OpenPrecision();
            });
        return;
    }
    Json ids = Json::array();
    if (m_selection.value("kind", "") == "geometry")
    {
        ids.push_back(m_selection.at("id"));
    }
    const std::string project = m_project;
    const std::string revision = m_revision;
    const Json selection = m_selection;
    m_busy = true;
    UpdateControls();
    Send(
        "precision.get", {{"expected_revision", revision}, {"selection_ids", ids}}, false, Context(),
        [this, project, revision, selection](const Json& result)
        {
            CallAfter(
                [this, project, revision, selection, result]()
                {
                    if (m_closing || !m_connected || m_project != project || m_revision != revision ||
                        !Studio::EditableProject(m_editor, m_scene, m_project, m_revision))
                    {
                        m_busy = false;
                        UpdateControls();
                        return;
                    }
                    Json objects = Json::array();
                    for (const auto& item : m_editor.at("items"))
                    {
                        if (item.at("kind") == "geometry" && item.at("id") == selection.value("id", ""))
                        {
                            objects.push_back(item);
                        }
                    }
                    for (const auto& item : m_editor.at("items"))
                    {
                        if (item.at("kind") == "geometry" && item.at("id") != selection.value("id", ""))
                        {
                            objects.push_back(item);
                        }
                    }
                    m_busy = false;
                    ShowObjectTool(
                        std::make_unique<PrecisionDialog>(this, result, objects, m_scene, ObjectToolGateway()),
                        selection);
                });
        },
        [this](const Json& error)
        {
            Failure(DiagnosticMessage(error));
        });
}

void StudioFrame::RefreshDimensions()
{
    m_canvas->SetDimensions(Json::array());
    if (!m_precisionSupported || m_selection.value("kind", "") != "geometry")
    {
        return;
    }
    const std::string project = m_project;
    const std::string revision = m_revision;
    const Json selection = m_selection;
    Send(
        "precision.get", {{"expected_revision", revision}, {"selection_ids", Json::array({selection.at("id")})}}, false,
        Context(),
        [this, project, revision, selection](const Json& result)
        {
            if (!m_closing && m_project == project && m_revision == revision && m_selection == selection)
            {
                m_canvas->SetDimensions(result.at("dimensions"));
            }
        },
        [this, project, revision](const Json& error)
        {
            if (!m_closing && m_project == project && m_revision == revision)
            {
                Log("연관 치수 조회: " + DiagnosticMessage(error));
            }
        });
}
