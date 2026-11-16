/** @file @brief 프로젝트 탐색, 표시 필터와 이름 변경을 서비스 선택에 연결한다. */
#include "studio_internal.h"
#include "object_rename_dialog.h"
#include "studio_theme.h"
#include <wx/srchctrl.h>
#include <wx/imaglist.h>

namespace
{
/** @brief 탐색 그룹은 객체 선택과 구분된 작업 진입점이다. */
class NavigationAction final : public wxTreeItemData
{
public:
    NavigationAction(std::string value, int command) : key(std::move(value)), commandId(command) {}
    std::string key;
    int commandId;
};

/** @brief 폴더/파일 대신 서비스 객체 종류에 대응하는 표시 아이콘을 선택한다. */
int NavigationIcon(const std::string& kind)
{
    const std::map<std::string, int> icons{{"project", 0},  {"templates", 1}, {"targets", 2},     {"board", 3},
                                           {"layer", 3},    {"geometry", 4},  {"port", 5},        {"net", 5},
                                           {"material", 6}, {"parameter", 7}, {"environment", 8}, {"rules", 9}};
    const auto found = icons.find(kind);
    return found == icons.end() ? 7 : found->second;
}
}

void StudioFrame::BuildNavigation(wxWindow* parent, wxSizer* layout)
{
    m_objectSearch = new wxSearchCtrl(parent, wxID_ANY);
    m_objectSearch->SetDescriptiveText(Display("객체 이름 검색"));
    m_objectSearch->SetName("navigation.search");
    m_objectSearch->ShowCancelButton(true);
    m_objectSearch->SetMinSize(FromDIP(wxSize(-1, 34)));
    layout->Add(m_objectSearch, 0, wxEXPAND | wxALL, FromDIP(8));
    m_objectFilter = new wxChoice(parent, wxID_ANY);
    for (const auto* name : {"모든 객체", "패턴", "기판 / 적층", "재료", "급전 / 네트", "매개변수"})
    {
        m_objectFilter->Append(Display(name));
    }
    m_objectFilter->SetSelection(0);
    m_objectFilter->SetName("navigation.filter");
    m_objectFilter->SetMinSize(FromDIP(wxSize(-1, 32)));
    layout->Add(m_objectFilter, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    m_tree =
        new wxTreeCtrl(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize,
                       wxTR_HAS_BUTTONS | wxTR_TWIST_BUTTONS | wxTR_NO_LINES | wxTR_FULL_ROW_HIGHLIGHT | wxBORDER_NONE);
    m_tree->SetIndent(FromDIP(18));
    m_tree->SetBackgroundColour(StudioTheme::Colours().content);
    auto* icons = new wxImageList(FromDIP(20), FromDIP(34), true);
    for (const auto* kind : {"project", "templates", "targets", "board", "geometry", "port", "material", "parameter",
                             "environment", "rules", "line", "arc", "region", "pad", "via"})
    {
        icons->Add(StudioTheme::Icon(*m_tree, kind, 20, 34));
    }
    m_tree->AssignImageList(icons);
    m_tree->SetName("navigation.objects");
    m_tree->SetToolTip(Display("객체 선택: 속성 / F2: 이름 변경 / 그룹 Enter: 관련 설정"));
    m_tree->AddRoot(Display("프로젝트 없음"));
    layout->Add(m_tree, 1, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    m_objectSearch->Bind(wxEVT_TEXT,
                         [this](wxCommandEvent&)
                         {
                             RebuildNavigation();
                         });
    m_objectSearch->Bind(wxEVT_SEARCH_CANCEL,
                         [this](wxCommandEvent&)
                         {
                             m_objectSearch->SetValue(wxEmptyString);
                         });
    m_objectFilter->Bind(wxEVT_CHOICE,
                         [this](wxCommandEvent&)
                         {
                             RebuildNavigation();
                         });
    m_tree->Bind(wxEVT_TREE_ITEM_ACTIVATED,
                 [this](wxTreeEvent& event)
                 {
                     auto* action = dynamic_cast<NavigationAction*>(m_tree->GetItemData(event.GetItem()));
                     if (action && action->commandId != wxID_NONE && !m_busy && !m_project.empty() &&
                         GetMenuBar()->IsEnabled(action->commandId))
                     {
                         wxCommandEvent command(wxEVT_MENU, action->commandId);
                         GetEventHandler()->ProcessEvent(command);
                     }
                 });
    m_tree->Bind(wxEVT_KEY_DOWN,
                 [this](wxKeyEvent& event)
                 {
                     if (event.GetKeyCode() == WXK_F2)
                     {
                         const auto item = m_tree->GetSelection();
                         if (item.IsOk() && dynamic_cast<SelectionData*>(m_tree->GetItemData(item)))
                         {
                             OpenRename();
                         }
                         return;
                     }
                     event.Skip();
                 });
    m_tree->Bind(wxEVT_TREE_ITEM_MENU,
                 [this](wxTreeEvent& event)
                 {
                     if (m_busy || !event.GetItem().IsOk())
                     {
                         return;
                     }
                     auto* data = dynamic_cast<SelectionData*>(m_tree->GetItemData(event.GetItem()));
                     if (data)
                     {
                         const Json selection = data->selection;
                         wxMenu menu;
                         const int rename = wxWindow::NewControlId();
                         menu.Append(rename, Display("이름 바꾸기\tF2"));
                         menu.Bind(
                             wxEVT_MENU,
                             [this, selection](wxCommandEvent&)
                             {
                                 if (selection == m_selection)
                                 {
                                     OpenRename();
                                 }
                                 else if (ConfirmDiscard())
                                 {
                                     RefreshEditor(selection,
                                                   [this]()
                                                   {
                                                       Ready("이름을 변경할 객체를 선택했습니다.");
                                                       OpenRename();
                                                   });
                                 }
                             },
                             rename);
                         PopupMenu(&menu);
                     }
                 });
    m_tree->Bind(wxEVT_TREE_ITEM_GETTOOLTIP,
                 [this](wxTreeEvent& event)
                 {
                     event.SetToolTip(m_tree->GetItemText(event.GetItem()));
                 });
}

void StudioFrame::RebuildNavigation()
{
    if (m_editor.empty() || !m_tree)
    {
        return;
    }
    const bool refreshing = m_refreshing;
    m_refreshing = true;
    std::set<std::string> expanded;
    const auto oldRoot = m_tree->GetRootItem();
    if (m_navigationProject == m_project && oldRoot.IsOk())
    {
        wxTreeItemIdValue cookie;
        for (auto node = m_tree->GetFirstChild(oldRoot, cookie); node.IsOk();
             node = m_tree->GetNextChild(oldRoot, cookie))
        {
            auto* action = dynamic_cast<NavigationAction*>(m_tree->GetItemData(node));
            if (action && m_tree->IsExpanded(node))
            {
                expanded.insert(action->key);
            }
        }
    }
    const bool first = m_navigationProject != m_project;
    m_navigationProject = m_project;
    m_tree->Freeze();
    m_tree->DeleteAllItems();
    const auto root = m_tree->AddRoot(Display(m_editor.at("metadata").at("name").get<std::string>()), 0, 0,
                                      new SelectionData({{"kind", "project"}, {"id", m_project}}));
    m_tree->SetItemBold(root);
    std::map<std::string, wxTreeItemId> groups;
    const auto group = [&](const std::string& key, const std::string& label, int command)
    {
        const int icon = NavigationIcon(key);
        const auto node = m_tree->AppendItem(root, Display(label), icon, icon, new NavigationAction(key, command));
        groups[key] = node;
        return node;
    };
    group("targets", "설계 목표", IdTargets);
    group("templates", "문헌 / 초기 후보", IdTemplates);
    group("board", "PCB / 적층", IdPhysicalSetup);
    groups["layer"] = groups["board"];
    group("geometry", "패턴", IdTemplates);
    group("port", "급전 / 네트", IdNewPort);
    groups["net"] = groups["port"];
    group("material", "재료 / 제조업체 자료", IdPcbSelection);
    group("parameter", "매개변수", IdNewParameter);
    group("environment", "외부 환경", IdPhysicalSetup);
    group("rules", "제약 / 연결 / DRC", IdDesignRules);
    const wxString query = m_objectSearch->GetValue().Lower();
    const int filter = m_objectFilter->GetSelection();
    wxTreeItemId selected;
    for (const auto& item : m_editor.at("items"))
    {
        const std::string kind = item.at("kind");
        if (kind == "project")
        {
            continue;
        }
        const bool matches = filter == 0 || (filter == 1 && kind == "geometry") ||
                             (filter == 2 && (kind == "board" || kind == "layer")) ||
                             (filter == 3 && kind == "material") ||
                             (filter == 4 && (kind == "port" || kind == "net")) || (filter == 5 && kind == "parameter");
        const wxString label = Display(item.at("label").get<std::string>());
        if (!matches || (!query.empty() && label.Lower().Find(query) == wxNOT_FOUND))
        {
            continue;
        }
        const Json selection{{"kind", kind}, {"id", item.at("id")}};
        int icon = NavigationIcon(kind);
        if (kind == "geometry")
        {
            const std::map<std::string, int> shapeIcons{
                {"line_path", 10}, {"arc_path", 11}, {"planar_region", 12}, {"pad", 13}, {"via", 14}};
            for (const auto& shape : m_scene.value("shapes", Json::array()))
            {
                const auto match = shapeIcons.find(shape.value("kind", ""));
                if (shape.at("id") == item.at("id") && match != shapeIcons.end())
                {
                    icon = match->second;
                    break;
                }
            }
        }
        const auto node = m_tree->AppendItem(groups.count(kind) ? groups.at(kind) : root, label, icon, icon,
                                             new SelectionData(selection));
        if (selection == m_selection)
        {
            selected = node;
        }
    }
    const std::string selectionKind = m_selection.value("kind", "");
    if (selectionKind.rfind("new_", 0) == 0)
    {
        const std::string kind = selectionKind.substr(4);
        selected = m_tree->AppendItem(groups.count(kind) ? groups.at(kind) : root, Display("새 객체 / 미적용 입력"), 1,
                                      1, new SelectionData(m_selection));
    }
    m_tree->Expand(root);
    for (const auto& [key, node] : groups)
    {
        if ((first && key == "geometry") || expanded.count(key) || !query.empty())
        {
            m_tree->Expand(node);
        }
    }
    if (m_selection.value("kind", "") == "project")
    {
        selected = root;
    }
    if (selected.IsOk())
    {
        m_tree->SelectItem(selected);
        m_tree->EnsureVisible(selected);
    }
    m_tree->Thaw();
    m_refreshing = refreshing;
}

void StudioFrame::OpenRename()
{
    if (m_busy || !m_connected || m_project.empty() || m_setupDialog || !ConfirmDiscard())
    {
        return;
    }
    std::string name;
    bool available = m_selection.value("kind", "") == "project";
    if (available)
    {
        name = m_editor.at("metadata").at("name");
    }
    for (const auto& field : m_editor.at("selection").at("fields"))
    {
        if (field.at("key") == "name" && !field.value("readonly", false))
        {
            name = field.at("value").get<std::string>();
            available = true;
        }
    }
    if (!available)
    {
        Log("선택한 항목은 이름 변경을 지원하지 않습니다.");
        return;
    }
    const Json context{{"project_id", m_project},
                       {"revision_id", m_revision},
                       {"selection", m_selection},
                       {"name", name},
                       {"label", Utf8(m_selectionLabel->GetLabel())}};
    CallAfter(
        [this, context]()
        {
            if (m_closing || m_busy || m_setupDialog || !m_connected || context.at("revision_id") != m_revision)
            {
                return;
            }
            ShowObjectTool(std::make_unique<ObjectRenameDialog>(this, context, ObjectToolGateway()),
                           context.at("selection"));
        });
}
