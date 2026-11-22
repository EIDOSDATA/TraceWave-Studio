/** @file @brief 프로젝트 탐색, 표시 필터와 이름 변경을 서비스 선택에 연결한다. */
#include "studio_internal.h"
#include "editor_sync.h"
#include "object_rename_dialog.h"
#include "project_activity_dialog.h"
#include "result_workspace.h"
#include "studio_theme.h"
#include "studio_shell.h"
#include "workspace_bar.h"
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

/** @brief 같은 개정과 필터에서 기존 native 행으로 바로 이동한다. */
class NavigationRows final : public wxClientData
{
public:
    std::string project;
    std::string revision;
    wxString query;
    int filter = 0;
    bool pcbFeatures = false;
    bool draft = false;
    std::set<std::string> expanded;
    std::map<std::pair<std::string, std::string>, wxTreeItemId> items;
};

/** @brief 폴더/파일 대신 서비스 객체 종류에 대응하는 표시 아이콘을 선택한다. */
int NavigationIcon(const std::string& kind)
{
    static const std::map<std::string, int> icons{
        {"project", 0}, {"templates", 1}, {"targets", 2}, {"board", 3}, {"layer", 3}, {"geometry", 4},
        {"port", 5}, {"net", 5}, {"material", 6}, {"parameter", 7}, {"environment", 8}, {"rules", 9}};
    const auto found = icons.find(kind);
    if (kind == "hole" || kind == "cutout")
    {
        return 14;
    }
    if (kind == "footprint" || kind == "aperture" || kind == "artwork_layer")
    {
        return 13;
    }
    if (kind == "keepout")
    {
        return 9;
    }
    return found == icons.end() ? 7 : found->second;
}
}

void StudioFrame::BuildNavigation(wxWindow* parent, wxSizer* layout)
{
    m_navigationLabel = new wxStaticText(parent, wxID_ANY, Display("프로젝트 객체 찾기"));
    StudioTheme::Heading(*m_navigationLabel);
    layout->Add(m_navigationLabel, 0, wxEXPAND | wxLEFT | wxRIGHT | wxTOP, FromDIP(StudioTheme::InputGap));
    const auto openActivity = [this](const std::string& object)
    {
        if (m_project.empty() || !m_connected || m_closing || m_busy)
        {
            return;
        }
        const auto project = m_project, epoch = m_epoch;
        DialogGateway gateway = [this, project, epoch](const std::string& method, const Json& input, bool mutation,
                                                       std::function<void(const Json&)> success,
                                                       std::function<void(const Json&)> failure)
        {
            if (mutation || m_closing || !m_connected || project != m_project || epoch != m_epoch)
            {
                failure({{"code", "E_STATE"}, {"message", "프로젝트 연결이 바뀌었습니다. 기록 찾기를 다시 여세요."}});
                return;
            }
            Send(method, input, false, Context(), std::move(success), std::move(failure));
        };
        const auto chosen = ShowProjectActivity(this, m_revision, object, std::move(gateway));
        if (chosen.is_object() && project == m_project && epoch == m_epoch && m_connected && !m_closing)
        {
            m_views->SetSelection(9);
            m_results->OpenPinned(chosen.at("source"), chosen.at("pin"));
        }
    };
    auto* activity = new wxButton(parent, wxID_ANY, Display("프로젝트 기록 찾기"));
    activity->SetName("navigation.activity.open");
    StudioTheme::Button(*activity);
    activity->Bind(wxEVT_BUTTON, [openActivity](wxCommandEvent&)
    {
        openActivity("");
    });
    activity->Bind(wxEVT_UPDATE_UI, [this](wxUpdateUIEvent& event)
    {
        event.Enable(m_connected && !m_project.empty() && !m_closing && !m_busy);
    });
    layout->Add(activity, 0, wxEXPAND | wxLEFT | wxRIGHT | wxTOP, FromDIP(8));
    m_objectSearch = new wxSearchCtrl(parent, wxID_ANY);
    m_objectSearch->SetDescriptiveText(Display("객체 이름 검색"));
    m_objectSearch->SetName("navigation.search");
    m_objectSearch->ShowCancelButton(false);
    m_objectSearch->SetToolTip(Display("이름으로 검색 (Ctrl+F). 객체 종류와 함께 좁힐 수 있습니다."));
    m_objectSearch->SetMinSize(FromDIP(wxSize(-1, 34)));
    layout->Add(m_objectSearch, 0, wxEXPAND | wxALL, FromDIP(8));
    m_objectFilter = new wxChoice(parent, wxID_ANY);
    for (const auto* name :
         {"모든 객체", "패턴", "기판 / 적층", "재료", "급전 / 네트", "매개변수", "기계 형상", "풋프린트 / 제조 이미지"})
    {
        m_objectFilter->Append(Display(name));
    }
    m_objectFilter->SetSelection(0);
    m_objectFilter->SetName("navigation.filter");
    m_objectFilter->SetToolTip(Display("표시할 객체 종류"));
    m_objectFilter->SetMinSize(FromDIP(wxSize(-1, 32)));
    layout->Add(m_objectFilter, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    m_navigationStatus = new wxStaticText(parent, wxID_ANY, Display("프로젝트를 열어 검색하세요."));
    m_navigationStatus->SetName("navigation.status");
    StudioTheme::BindSecondary(*m_navigationStatus);
    layout->Add(m_navigationStatus, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(StudioTheme::InputGap));
    m_tree =
        new wxTreeCtrl(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize,
                       wxTR_HAS_BUTTONS | wxTR_TWIST_BUTTONS | wxTR_NO_LINES | wxTR_FULL_ROW_HIGHLIGHT | wxBORDER_NONE);
    m_tree->SetIndent(FromDIP(18));
    m_tree->SetBackgroundColour(StudioTheme::Colours().content);
    const auto assignIcons = [this]()
    {
        auto* icons = new wxImageList(FromDIP(20), FromDIP(34), true);
        for (const auto* kind : {"project", "templates", "targets", "board", "geometry", "port", "material",
                                 "parameter", "environment", "rules", "line", "arc", "region", "pad", "via"})
        {
            icons->Add(StudioTheme::Icon(*m_tree, kind, 20, 34));
        }
        m_tree->AssignImageList(icons);
    };
    assignIcons();
    m_tree->Bind(wxEVT_SYS_COLOUR_CHANGED,
                 [assignIcons](wxSysColourChangedEvent& event)
                 {
                     assignIcons();
                     event.Skip();
                 });
    m_tree->SetName("navigation.objects");
    m_tree->SetToolTip(Display("객체 선택: 속성 / F2: 이름 변경 / 그룹 Enter: 관련 설정"));
    m_tree->AddRoot(Display("프로젝트 없음"));
    layout->Add(m_tree, 1, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    m_objectSearch->Bind(wxEVT_TEXT,
                         [this](wxCommandEvent&)
                         {
                             m_objectSearch->ShowCancelButton(!m_objectSearch->GetValue().empty());
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
                         if (action->commandId == IdPcbFeatures)
                         {
                             OpenPcbFeatures(action->key);
                             return;
                         }
                         wxCommandEvent command(wxEVT_MENU, action->commandId);
                         GetEventHandler()->ProcessEvent(command);
                     }
                     else if (!action && !m_busy && m_pcbFeaturesSupported)
                     {
                         auto* data = dynamic_cast<SelectionData*>(m_tree->GetItemData(event.GetItem()));
                         if (data)
                         {
                             const auto kind = data->selection.value("kind", "");
                             if (kind == "cutout" || kind == "hole" || kind == "footprint" || kind == "artwork_layer" ||
                                 kind == "aperture" || kind == "keepout")
                             {
                                 OpenPcbFeatures(kind, data->selection.at("id"));
                             }
                         }
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
                 [this, openActivity](wxTreeEvent& event)
                 {
                     if (m_busy || !event.GetItem().IsOk() ||
                         !Studio::EditableProject(m_editor, m_scene, m_project, m_revision))
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
                         const int jump = wxWindow::NewControlId();
                         if (selection.contains("id"))
                         {
                             menu.Append(jump, Display("이 객체의 프로젝트 기록"));
                             menu.Bind(wxEVT_MENU,
                                       [openActivity, selection](wxCommandEvent&)
                                       {
                                           openActivity(selection.at("id").get<std::string>());
                                       },
                                       jump);
                         }
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
    if (!m_tree)
    {
        return;
    }
    if (m_editor.empty())
    {
        m_navigationStatus->SetLabel(Display("프로젝트를 열어 검색하세요."));
        return;
    }
    const bool refreshing = m_refreshing;
    m_refreshing = true;
    const auto selectionKind = m_selection.value("kind", "");
    const bool draft = selectionKind.rfind("new_", 0) == 0;
    wxString query = m_objectSearch->GetValue();
    query.Trim().Trim(false);
    query.MakeLower();
    const int filter = m_objectFilter->GetSelection();
    const auto* previous = dynamic_cast<const NavigationRows*>(m_tree->GetClientObject());
    if (previous && !previous->draft && !draft && previous->project == m_project && previous->revision == m_revision &&
        previous->query == query && previous->filter == filter && previous->pcbFeatures == m_pcbFeaturesSupported)
    {
        const auto selected = previous->items.find({selectionKind, m_selection.value("id", "")});
        if (selected == previous->items.end())
        {
            m_tree->Unselect();
        }
        else if (m_tree->GetSelection() != selected->second)
        {
            m_tree->SelectItem(selected->second);
            m_tree->EnsureVisible(selected->second);
        }
        m_refreshing = refreshing;
        return;
    }
    auto rows = std::make_unique<NavigationRows>();
    rows->project = m_project;
    rows->revision = m_revision;
    rows->query = query;
    rows->filter = filter;
    rows->pcbFeatures = m_pcbFeaturesSupported;
    rows->draft = draft;

    const bool restricted = !query.empty() || filter != 0;
    const auto oldRoot = m_tree->GetRootItem();
    const bool first = m_navigationProject != m_project;
    if (!first && previous && (!previous->query.empty() || previous->filter != 0))
    {
        rows->expanded = previous->expanded;
    }
    else if (!first && oldRoot.IsOk())
    {
        wxTreeItemIdValue cookie;
        for (auto node = m_tree->GetFirstChild(oldRoot, cookie); node.IsOk();
             node = m_tree->GetNextChild(oldRoot, cookie))
        {
            auto* action = dynamic_cast<NavigationAction*>(m_tree->GetItemData(node));
            if (action && m_tree->IsExpanded(node))
            {
                rows->expanded.insert(action->key);
            }
        }
    }
    if (first)
    {
        rows->expanded.insert("geometry");
    }
    m_navigationProject = m_project;
    m_tree->Freeze();
    m_tree->DeleteAllItems();
    const auto root = m_tree->AddRoot(Display(m_editor.at("metadata").at("name").get<std::string>()), 0, 0,
                                      new SelectionData({{"kind", "project"}, {"id", m_project}}));
    m_tree->SetItemBold(root);
    rows->items.emplace(std::make_pair("project", m_project), root);
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
    if (m_pcbFeaturesSupported)
    {
        group("hole", "기계 형상 / 홀과 절삭", IdPcbFeatures);
        groups["cutout"] = groups["hole"];
        group("footprint", "풋프린트", IdPcbFeatures);
        group("artwork_layer", "제조 이미지 / 개구", IdPcbFeatures);
        groups["aperture"] = groups["artwork_layer"];
        group("keepout", "금지 영역", IdPcbFeatures);
    }
    wxTreeItemId selected;
    std::map<void*, wxTreeItemId> groupAnchors;
    // @brief 뒤에서부터 같은 위치에 넣어 표시 순서를 보존하며 native 트리에서 끝 탐색을 줄인다.
    const auto insertObject = [&](wxTreeItemId parent, const wxString& label, int icon, const Json& selection)
    {
        auto position = groupAnchors.find(parent.GetID());
        if (position == groupAnchors.end())
        {
            position = groupAnchors.emplace(parent.GetID(), m_tree->GetLastChild(parent)).first;
        }
        const auto& anchor = position->second;
        auto* data = new SelectionData(selection);
        return anchor.IsOk() ? m_tree->InsertItem(parent, anchor, label, icon, icon, data)
                             : m_tree->PrependItem(parent, label, icon, icon, data);
    };
    std::map<std::string, wxTreeItemId> footprintNodes;
    std::map<std::string, std::string> owners;
    std::map<std::string, int> shapeIconById;
    const std::map<std::string, int> shapeIcons{
        {"line_path", 10}, {"arc_path", 11}, {"planar_region", 12}, {"pad", 13}, {"via", 14}};
    for (const auto* collection : {"shapes", "pcb_features"})
    {
        const auto rows = m_scene.find(collection);
        if (rows == m_scene.end())
        {
            continue;
        }
        for (const auto& shape : *rows)
        {
            const auto icon = shapeIcons.find(shape.value("kind", ""));
            if (icon != shapeIcons.end())
            {
                shapeIconById.emplace(shape.at("id").get<std::string>(), icon->second);
            }
            const auto owner = shape.value("owner_footprint_id", Json(nullptr));
            if (owner.is_string())
            {
                owners[shape.at("id").get<std::string>()] = owner.get<std::string>();
            }
        }
    }
    const auto& items = m_editor.at("items");
    if (m_pcbFeaturesSupported && query.empty() && (filter == 0 || filter == 7))
    {
        for (auto position = items.rbegin(); position != items.rend(); ++position)
        {
            const auto& item = *position;
            if (item.at("kind") == "footprint")
            {
                const Json selection{{"kind", "footprint"}, {"id", item.at("id")}};
                const int icon = NavigationIcon("footprint");
                const auto node = m_tree->PrependItem(groups.at("footprint"), Display(item.at("label").get<std::string>()),
                                                      icon, icon, new SelectionData(selection));
                const auto id = item.at("id").get<std::string>();
                footprintNodes[id] = node;
                rows->items.emplace(std::make_pair("footprint", id), node);
                if (selection == m_selection)
                {
                    selected = node;
                }
            }
        }
    }
    for (auto position = items.rbegin(); position != items.rend(); ++position)
    {
        const auto& item = *position;
        const std::string kind = item.at("kind");
        if (kind == "project")
        {
            continue;
        }
        if (kind == "footprint" && footprintNodes.count(item.at("id").get<std::string>()))
        {
            continue;
        }
        const bool matches =
            filter == 0 || (filter == 1 && kind == "geometry") ||
            (filter == 2 && (kind == "board" || kind == "layer")) || (filter == 3 && kind == "material") ||
            (filter == 4 && (kind == "port" || kind == "net")) || (filter == 5 && kind == "parameter") ||
            (filter == 6 && (kind == "hole" || kind == "cutout")) ||
            (filter == 7 &&
             (kind == "footprint" || kind == "artwork_layer" || kind == "aperture" || kind == "keepout"));
        const wxString label = Display(item.at("label").get<std::string>());
        if (!matches || (!query.empty() && label.Lower().Find(query) == wxNOT_FOUND))
        {
            continue;
        }
        const Json selection{{"kind", kind}, {"id", item.at("id")}};
        int icon = NavigationIcon(kind);
        if (kind == "geometry")
        {
            const auto match = shapeIconById.find(item.at("id").get<std::string>());
            if (match != shapeIconById.end())
            {
                icon = match->second;
            }
        }
        auto parent = groups.count(kind) ? groups.at(kind) : root;
        const auto owner = owners.find(item.at("id").get<std::string>());
        if (owner != owners.end() && footprintNodes.count(owner->second))
        {
            parent = footprintNodes.at(owner->second);
        }
        const auto node = insertObject(parent, label, icon, selection);
        rows->items.emplace(std::make_pair(kind, item.at("id").get<std::string>()), node);
        if (selection == m_selection)
        {
            selected = node;
        }
    }
    if (draft)
    {
        const auto groupKind = selectionKind.substr(4);
        selected = m_tree->AppendItem(groups.count(groupKind) ? groups.at(groupKind) : root, Display("새 객체 / 미적용 입력"), 1,
                                      1, new SelectionData(m_selection));
    }
    m_tree->Expand(root);
    for (const auto& [key, node] : groups)
    {
        if (restricted || rows->expanded.count(key))
        {
            m_tree->Expand(node);
        }
    }
    if (restricted)
    {
        wxTreeItemIdValue cookie;
        for (auto node = m_tree->GetFirstChild(root, cookie); node.IsOk();)
        {
            const auto next = m_tree->GetNextChild(root, cookie);
            if (m_tree->GetChildrenCount(node, false) == 0)
            {
                m_tree->Delete(node);
            }
            node = next;
        }
    }
    const auto count = rows->items.size() - 1;
    m_navigationStatus->SetLabel(count == 0 && restricted ? Display("일치하는 객체 없음")
        : wxString::Format(Display(restricted ? "검색 결과 %zu개" : "프로젝트 객체 %zu개"), count));
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
    m_tree->SetClientObject(rows.release());
    m_refreshing = refreshing;
}

void StudioFrame::FocusObjectSearch()
{
    if (m_objectSearch->IsEnabled())
    {
        if (!m_objectSearch->IsShown())
        {
            NavigateWorkspace(WorkspaceArea::Design);
        }
        m_shell->ShowNavigation();
        m_objectSearch->SetFocus();
        m_objectSearch->SelectAll();
    }
}

void StudioFrame::OpenRename()
{
    if (m_busy || !m_connected || m_project.empty() || m_setupDialog ||
        !Studio::EditableProject(m_editor, m_scene, m_project, m_revision) || !ConfirmDiscard())
    {
        return;
    }
    const auto kind = m_selection.value("kind", "");
    if (kind == "cutout" || kind == "hole" || kind == "footprint" || kind == "artwork_layer" || kind == "aperture" ||
        kind == "keepout")
    {
        OpenPcbFeatures(kind, m_selection.at("id"));
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
            if (m_closing || m_busy || m_setupDialog || !m_connected || context.at("project_id") != m_project ||
                context.at("revision_id") != m_revision ||
                !Studio::EditableProject(m_editor, m_scene, m_project, m_revision))
            {
                return;
            }
            ShowObjectTool(std::make_unique<ObjectRenameDialog>(this, context, ObjectToolGateway()),
                           context.at("selection"));
        });
}
