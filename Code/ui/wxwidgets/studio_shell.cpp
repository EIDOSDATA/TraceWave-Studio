/** @file @brief native 도킹과 작은 창의 탐색/속성 탭을 같은 입력 위젯으로 구성한다. */
#include "studio_shell.h"
#include "studio_support.h"
#include "studio_theme.h"
#include "workspace_bar.h"
#include <wx/aui/aui.h>
#include <wx/config.h>
#include <wx/frame.h>
#include <wx/menu.h>
#include <wx/notebook.h>
#include <wx/panel.h>
#include <wx/sizer.h>
#include <algorithm>

namespace
{
const std::array<const char*, 4> PaneNames{{"navigation", "properties", "layers", "problems"}};
constexpr auto VisibilityGroup = "/workspace_ui/v1/pane_visibility";
const std::array<const char*, 5> VisibilityNames{
    {"wide_navigation", "wide_properties", "layers", "problems", "compact_navigation"}};

/** @brief 모드별 명시 선택을 키로 분리하고 다른 패널의 설정을 건드리지 않는다. */
wxString VisibilityKey(std::size_t index)
{
    return wxString(VisibilityGroup) + "/" + VisibilityNames[index];
}

/** @brief 입력 위젯의 현재 초점이 특정 패널 내부에 있는지 확인한다. */
bool Contains(const wxWindow& parent, const wxWindow* child)
{
    return child != nullptr && (&parent == child || parent.IsDescendant(const_cast<wxWindow*>(child)));
}
}

StudioShell::StudioShell(wxFrame& frame, wxAuiManager& manager, wxNotebook& navigation, wxWindow& tree,
                         wxPanel& propertiesHost, wxPanel& properties, wxWindow& views, wxWindow& bottom,
                         WorkspaceBar& workspaceBar, wxMenu& viewMenu, bool usePreferences)
    : m_frame(frame), m_manager(manager), m_navigation(navigation), m_tree(tree), m_propertiesHost(propertiesHost),
      m_properties(properties), m_views(views), m_bottom(bottom), m_workspaceBar(workspaceBar),
      m_layersHost(manager.GetPane("layers").window),
      m_layers(wxWindow::FindWindowByName("workspace.layer-content", &frame)),
      m_defaultLayout(manager.SavePerspective()), m_usePreferences(usePreferences)
{
    if (m_usePreferences)
    {
        wxConfig configuration("TraceWaveStudio", "TraceWave");
        for (std::size_t index = 0; index < m_visible.size(); ++index)
        {
            long value = 1;
            m_visible[index] = !configuration.Read(VisibilityKey(index), &value) || value != 0;
        }
    }
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
    ApplyVisibility();
    m_manager.Update();
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

std::array<bool, 4> StudioShell::PanelVisibility() const
{
    return {m_visible[VisibilityIndex(0)], m_visible[VisibilityIndex(1)], m_visible[2], m_visible[3]};
}

void StudioShell::SetPanelVisibility(const std::array<bool, 4>& visible)
{
    for (std::size_t index = 0; index < visible.size(); ++index)
    {
        const auto preference = VisibilityIndex(index);
        if ((m_compact && index == 1) || m_visible[preference] == visible[index])
        {
            continue;
        }
        m_visible[preference] = visible[index];
        SaveVisibility(preference);
    }
    ApplyVisibility();
    m_manager.Update();
}

void StudioShell::ApplyVisibility()
{
    m_navigation.SetPageText(0, Display(m_validationContext ? "검증 기록"
                                        : m_studyContext    ? "연구 목록"
                                        : m_resultContext   ? "결과 목록"
                                                            : "탐색"));
    m_manager.GetPane("navigation")
        .Caption(Display(m_validationContext ? "검증 기록"
                         : m_studyContext    ? "연구 목록"
                         : m_resultContext   ? "결과"
                                             : "프로젝트"));
    m_manager.GetPane("properties")
        .Caption(Display(m_outputContext       ? "출력 기준과 출처"
                         : m_validationContext ? "판정 근거와 출처"
                         : m_studyContext      ? "연구 조건과 출처"
                         : m_resultContext     ? "조건과 출처"
                                               : "속성"));
    const int propertiesPage = m_navigation.FindPage(&m_properties);
    if (propertiesPage != wxNOT_FOUND)
    {
        m_navigation.SetPageText(static_cast<std::size_t>(propertiesPage), Display(m_outputContext       ? "출력 기준"
                                                                                   : m_validationContext ? "판정 근거"
                                                                                   : m_studyContext      ? "연구 조건"
                                                                                   : m_resultContext     ? "결과 조건"
                                                                                                         : "속성"));
    }
    m_manager.GetPane("navigation").Show(m_visible[VisibilityIndex(0)]);
    m_manager.GetPane("properties").Show(!m_compact && m_visible[1]);
    m_manager.GetPane("layers").Show(!m_compact && m_visible[2] && !m_resultContext);
    if (m_layers != nullptr)
    {
        m_layers->Show(m_visible[2] && !m_resultContext);
        m_navigation.GetPage(0)->Layout();
    }
    m_manager.GetPane("problems").Show(m_visible[3]);
}

void StudioShell::SetResultContext(bool active, bool study, bool validation, bool output)
{
    if (active == m_resultContext && (active && study) == m_studyContext &&
        (active && validation) == m_validationContext && output == m_outputContext)
    {
        return;
    }
    m_resultContext = active;
    m_studyContext = active && study;
    m_validationContext = active && validation;
    m_outputContext = output;
    ApplyVisibility();
    m_manager.Update();
}

void StudioShell::RestoreLayout()
{
    SetCompact(false);
    m_updating = true;
    m_visible.fill(true);
    if (m_usePreferences)
    {
        wxConfig configuration("TraceWaveStudio", "TraceWave");
        if (configuration.HasGroup(VisibilityGroup) &&
            (!configuration.DeleteGroup(VisibilityGroup) || !configuration.Flush()))
        {
            m_frame.SetStatusText(Display("기본 패널 표시 설정을 저장하지 못했습니다."));
        }
    }
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
    m_visible[VisibilityIndex(1)] = true;
    ApplyVisibility();
    if (m_compact)
    {
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
    m_visible[VisibilityIndex(0)] = true;
    ApplyVisibility();
    m_navigation.SetSelection(0);
    m_manager.Update();
    if (focus)
    {
        if (m_tree.IsShownOnScreen())
        {
            m_tree.SetFocus();
        }
        else
        {
            m_navigation.GetPage(0)->SetFocus();
        }
    }
    else if (previouslyFocused != nullptr && previouslyFocused->IsShownOnScreen() && previouslyFocused->IsEnabled())
    {
        previouslyFocused->SetFocus();
    }
    else if (m_compact && previouslyFocused != nullptr && Contains(m_properties, previouslyFocused))
    {
        m_navigation.GetPage(0)->SetFocus();
    }
}

void StudioShell::FocusNext(bool reverse)
{
    auto* focused = wxWindow::FindFocus();
    const std::array<wxWindow*, 6> regions{{&m_navigation, &m_views, &m_properties, &m_bottom, m_layers,
                                           &m_workspaceBar}};
    const int count = static_cast<int>(regions.size());
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
    for (int offset = 1; offset <= count; ++offset)
    {
        const int next = (current + (reverse ? -offset : offset) + 2 * count) % count;
        auto* target = regions[next];
        const bool available = next == 0 || next == 2 ? m_visible[VisibilityIndex(next == 0 ? 0 : 1)]
                                                      : (target != nullptr && target->IsShownOnScreen());
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
        else if (target == &m_workspaceBar)
        {
            m_workspaceBar.FocusSelected();
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
    const auto preference = VisibilityIndex(index);
    m_visible[preference] = event.IsChecked();
    SaveVisibility(preference);
    if (m_compact && index < 2)
    {
        // @brief 작은 창의 두 항목은 같은 탭 패널을 보이거나 숨긴다.
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
        event.Check(m_visible[VisibilityIndex(index)]);
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
                const auto preference = VisibilityIndex(index);
                m_visible[preference] = false;
                SaveVisibility(preference);
                break;
            }
        }
    }
    event.Skip();
}

std::size_t StudioShell::VisibilityIndex(std::size_t index) const
{
    return m_compact && index < 2 ? CompactNavigation : index;
}

void StudioShell::SaveVisibility(std::size_t index)
{
    if (m_usePreferences)
    {
        wxConfig configuration("TraceWaveStudio", "TraceWave");
        if (!configuration.Write(VisibilityKey(index), m_visible[index] ? 1L : 0L) || !configuration.Flush())
        {
            m_frame.SetStatusText(Display("패널 표시 설정을 저장하지 못했습니다."));
        }
    }
}
