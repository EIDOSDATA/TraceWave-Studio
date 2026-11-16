/** @file @brief native 도킹과 작은 창의 탐색/속성 탭을 같은 입력 위젯으로 구성한다. */
#include "studio_shell.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/aui/aui.h>
#include <wx/frame.h>
#include <wx/menu.h>
#include <wx/notebook.h>
#include <wx/panel.h>
#include <wx/sizer.h>
#include <algorithm>

namespace
{
const std::array<const char*, 4> PaneNames{{"navigation", "properties", "layers", "problems"}};

/** @brief 입력 위젯의 현재 초점이 특정 패널 내부에 있는지 확인한다. */
bool Contains(const wxWindow& parent, const wxWindow* child)
{
    return child != nullptr && (&parent == child || parent.IsDescendant(const_cast<wxWindow*>(child)));
}
}

StudioShell::StudioShell(wxFrame& frame, wxAuiManager& manager, wxNotebook& navigation, wxWindow& tree,
                         wxPanel& propertiesHost, wxPanel& properties, wxWindow& views, wxWindow& bottom,
                         wxMenu& viewMenu)
    : m_frame(frame), m_manager(manager), m_navigation(navigation), m_tree(tree), m_propertiesHost(propertiesHost),
      m_properties(properties), m_views(views), m_bottom(bottom), m_layersHost(manager.GetPane("layers").window),
      m_layers(wxWindow::FindWindowByName("workspace.layer-content", &frame)),
      m_defaultLayout(manager.SavePerspective())
{
    viewMenu.AppendSeparator();
    const std::array<const char*, 4> labels{
        {"프로젝트 탐색 패널", "선택 속성 패널", "레이어 표시 패널", "문제 / 작업 / 로그 패널"}};
    for (std::size_t index = 0; index < m_menuIds.size(); ++index)
    {
        m_menuIds[index] = wxWindow::NewControlId();
        viewMenu.AppendCheckItem(m_menuIds[index], Display(labels[index]),
                                 Display(index < 2 ? "작은 창에서는 탐색과 속성이 같은 패널의 탭입니다."
                                                   : "F6 / Shift+F6으로 패널을 이동합니다."));
        m_frame.Bind(wxEVT_MENU, &StudioShell::OnMenu, this, m_menuIds[index]);
        m_frame.Bind(wxEVT_UPDATE_UI, &StudioShell::OnUpdateMenu, this, m_menuIds[index]);
    }
    m_frame.Bind(wxEVT_SIZE, &StudioShell::OnSize, this);
    m_frame.Bind(wxEVT_CHAR_HOOK, &StudioShell::OnKey, this);
    m_frame.Bind(wxEVT_AUI_PANE_CLOSE, &StudioShell::OnPaneClose, this);
    ApplyResponsiveLayout();
}

StudioShell::~StudioShell()
{
    m_frame.Unbind(wxEVT_SIZE, &StudioShell::OnSize, this);
    m_frame.Unbind(wxEVT_CHAR_HOOK, &StudioShell::OnKey, this);
    m_frame.Unbind(wxEVT_AUI_PANE_CLOSE, &StudioShell::OnPaneClose, this);
    for (const int id : m_menuIds)
    {
        m_frame.Unbind(wxEVT_MENU, &StudioShell::OnMenu, this, id);
        m_frame.Unbind(wxEVT_UPDATE_UI, &StudioShell::OnUpdateMenu, this, id);
    }
}

void StudioShell::ApplyResponsiveLayout()
{
    if (m_updating || m_frame.IsIconized())
    {
        return;
    }
    const int width = m_frame.ToDIP(m_frame.GetClientSize()).GetWidth();
    // @brief 경계 부근에서 반복 재배치를 피하고, 1366 창에서는 편집 면적을 확보한다.
    const int boundary = m_compact ? 1490 : 1440;
    SetCompact(width < boundary);
}

void StudioShell::SetCompact(bool compact)
{
    if (compact == m_compact || m_updating)
    {
        return;
    }
    m_updating = true;
    auto* focused = wxWindow::FindFocus();
    const bool propertiesFocused = Contains(m_properties, focused);
    m_frame.Freeze();
    if (compact)
    {
        m_propertiesHost.GetSizer()->Detach(&m_properties);
        m_properties.Reparent(&m_navigation);
        m_navigation.AddPage(&m_properties, Display("속성"), propertiesFocused || (!m_visible[0] && m_visible[1]));
        if (m_layers != nullptr && m_layersHost != nullptr)
        {
            m_layersHost->GetSizer()->Detach(m_layers);
            auto* navigationPage = m_navigation.GetPage(0);
            m_layers->Reparent(navigationPage);
            m_layers->SetMinSize(m_frame.FromDIP(wxSize(-1, 150)));
            navigationPage->GetSizer()->Add(m_layers, 0, wxEXPAND);
        }
        m_manager.GetPane("navigation")
            .MinSize(m_frame.FromDIP(wxSize(320, 240)))
            .BestSize(m_frame.FromDIP(wxSize(340, 600)));
    }
    else
    {
        const int page = m_navigation.FindPage(&m_properties);
        if (page != wxNOT_FOUND)
        {
            m_navigation.RemovePage(static_cast<std::size_t>(page));
        }
        m_properties.Reparent(&m_propertiesHost);
        m_propertiesHost.GetSizer()->Add(&m_properties, 1, wxEXPAND);
        m_properties.Show();
        if (m_layers != nullptr && m_layersHost != nullptr)
        {
            m_navigation.GetPage(0)->GetSizer()->Detach(m_layers);
            m_layers->Reparent(m_layersHost);
            m_layers->SetMinSize(wxDefaultSize);
            m_layersHost->GetSizer()->Add(m_layers, 1, wxEXPAND);
        }
        m_manager.GetPane("navigation")
            .MinSize(m_frame.FromDIP(wxSize(220, 240)))
            .BestSize(m_frame.FromDIP(wxSize(280, 600)));
    }
    m_compact = compact;
    ApplyVisibility();
    m_propertiesHost.Layout();
    if (m_layersHost != nullptr)
    {
        m_layersHost->Layout();
    }
    m_navigation.GetPage(0)->Layout();
    m_navigation.Layout();
    m_manager.Update();
    m_frame.Thaw();
    if (focused != nullptr && focused->IsShownOnScreen() && focused->IsEnabled())
    {
        focused->SetFocus();
    }
    m_updating = false;
}

void StudioShell::ApplyVisibility()
{
    m_manager.GetPane("navigation").Show(m_visible[0] || (m_compact && m_visible[1]));
    m_manager.GetPane("properties").Show(!m_compact && m_visible[1]);
    m_manager.GetPane("layers").Show(!m_compact && m_visible[2]);
    if (m_layers != nullptr)
    {
        m_layers->Show(m_visible[2]);
        m_navigation.GetPage(0)->Layout();
    }
    m_manager.GetPane("problems").Show(m_visible[3]);
}

void StudioShell::RestoreLayout()
{
    SetCompact(false);
    m_updating = true;
    m_visible.fill(true);
    m_manager.LoadPerspective(m_defaultLayout, false);
    ApplyVisibility();
    m_manager.Update();
    m_updating = false;
    ApplyResponsiveLayout();
}

void StudioShell::ShowProperties(bool focus)
{
    auto* previouslyFocused = wxWindow::FindFocus();
    const bool movingFocusedPanel =
        m_compact && Contains(m_navigation, previouslyFocused) && !Contains(m_properties, previouslyFocused);
    m_visible[1] = true;
    ApplyVisibility();
    if (m_compact)
    {
        m_visible[0] = true;
        const int page = m_navigation.FindPage(&m_properties);
        if (page != wxNOT_FOUND)
        {
            m_navigation.SetSelection(static_cast<std::size_t>(page));
        }
    }
    m_manager.Update();
    if (focus || movingFocusedPanel)
    {
        m_properties.SetFocus();
    }
    else if (previouslyFocused != nullptr && previouslyFocused->IsShownOnScreen() && previouslyFocused->IsEnabled())
    {
        previouslyFocused->SetFocus();
    }
}

void StudioShell::ShowNavigation(bool focus)
{
    auto* previouslyFocused = wxWindow::FindFocus();
    m_visible[0] = true;
    if (m_compact)
    {
        m_visible[1] = true;
    }
    ApplyVisibility();
    m_navigation.SetSelection(0);
    m_manager.Update();
    if (focus)
    {
        m_tree.SetFocus();
    }
    else if (previouslyFocused != nullptr && previouslyFocused->IsShownOnScreen() && previouslyFocused->IsEnabled())
    {
        previouslyFocused->SetFocus();
    }
    else if (m_compact && previouslyFocused != nullptr && Contains(m_properties, previouslyFocused))
    {
        m_tree.SetFocus();
    }
}

void StudioShell::FocusNext(bool reverse)
{
    auto* focused = wxWindow::FindFocus();
    const std::array<wxWindow*, 5> regions{{&m_navigation, &m_views, &m_properties, &m_bottom, m_layers}};
    int current = -1;
    for (std::size_t index = 0; index < regions.size(); ++index)
    {
        if (regions[index] != nullptr && Contains(*regions[index], focused))
        {
            current = static_cast<int>(index);
        }
    }
    if (current < 0 && reverse)
    {
        current = 0;
    }
    for (int offset = 1; offset <= static_cast<int>(regions.size()); ++offset)
    {
        const int next = (current + (reverse ? -offset : offset) + 10) % 5;
        auto* target = regions[next];
        const bool available =
            next == 0 ? m_visible[0] : (next == 2 ? m_visible[1] : (target != nullptr && target->IsShownOnScreen()));
        if (!available || target == nullptr || !target->IsEnabled())
        {
            continue;
        }
        if (next == 0)
        {
            ShowNavigation(true);
        }
        else if (next == 2)
        {
            ShowProperties(true);
        }
        else
        {
            target->SetFocus();
        }
        return;
    }
}

void StudioShell::OnSize(wxSizeEvent& event)
{
    ApplyResponsiveLayout();
    event.Skip();
}

void StudioShell::OnKey(wxKeyEvent& event)
{
    auto* focused = wxWindow::FindFocus();
    if (event.GetKeyCode() == WXK_F6 && !event.ControlDown() && !event.AltDown() && focused != nullptr &&
        wxGetTopLevelParent(focused) == &m_frame)
    {
        FocusNext(event.ShiftDown());
        return;
    }
    event.Skip();
}

void StudioShell::OnMenu(wxCommandEvent& event)
{
    const auto found = std::find(m_menuIds.begin(), m_menuIds.end(), event.GetId());
    if (found == m_menuIds.end())
    {
        event.Skip();
        return;
    }
    const std::size_t index = static_cast<std::size_t>(found - m_menuIds.begin());
    m_visible[index] = event.IsChecked();
    if (m_compact && index < 2)
    {
        // @brief 작은 창의 두 항목은 같은 탭 패널을 보이거나 숨긴다.
        m_visible[0] = event.IsChecked();
        m_visible[1] = event.IsChecked();
        m_navigation.SetSelection(index == 1 ? 1 : 0);
    }
    ApplyVisibility();
    m_manager.Update();
    if (event.IsChecked())
    {
        if (index == 0)
        {
            ShowNavigation(true);
        }
        else if (index == 1)
        {
            ShowProperties(true);
        }
        else if (index == 2 && m_layers != nullptr)
        {
            if (m_compact)
            {
                ShowNavigation();
            }
            m_layers->SetFocus();
        }
        else if (index == 3)
        {
            m_bottom.SetFocus();
        }
    }
}

void StudioShell::OnUpdateMenu(wxUpdateUIEvent& event)
{
    const auto found = std::find(m_menuIds.begin(), m_menuIds.end(), event.GetId());
    if (found != m_menuIds.end())
    {
        const std::size_t index = static_cast<std::size_t>(found - m_menuIds.begin());
        event.Check(m_compact && index < 2 ? m_manager.GetPane("navigation").IsShown() : m_visible[index]);
    }
}

void StudioShell::OnPaneClose(wxAuiManagerEvent& event)
{
    if (event.GetPane() != nullptr)
    {
        for (std::size_t index = 0; index < PaneNames.size(); ++index)
        {
            if (event.GetPane()->name == PaneNames[index])
            {
                m_visible[index] = false;
                if (m_compact && index == 0)
                {
                    m_visible[1] = false;
                }
            }
        }
    }
    event.Skip();
}
