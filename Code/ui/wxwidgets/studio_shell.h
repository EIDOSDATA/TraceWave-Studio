/** @file @brief 도킹 배치와 키보드 패널 이동만 소유하는 Studio 표시 컨트롤러다. */
#pragma once

#include <wx/event.h>
#include <wx/string.h>
#include <array>

class wxAuiManager;
class wxAuiManagerEvent;
class wxFrame;
class wxMenu;
class wxNotebook;
class wxPanel;
class wxWindow;
class WorkspaceBar;

/** @brief 서비스 원본과 초안을 바꾸지 않고 같은 속성 폼을 작은 창의 탭으로 이동한다. */
class StudioShell final : public wxEvtHandler
{
public:
    StudioShell(wxFrame& frame, wxAuiManager& manager, wxNotebook& navigation, wxWindow& tree, wxPanel& propertiesHost,
                wxPanel& properties, wxWindow& views, wxWindow& bottom, WorkspaceBar& workspaceBar,
                wxMenu& viewMenu, bool usePreferences);
    ~StudioShell() override;
    /** @brief 현재 창 폭에 맞는 기본 배치를 복원하고 숨긴 패널을 다시 보인다. */
    void RestoreLayout();
    /** @brief 현재 창 배치에서 사용자가 선택한 패널의 표시 상태를 반환한다. */
    std::array<bool, 4> PanelVisibility() const;
    /** @brief 보기 메뉴와 같은 사용자 설정에 패널 표시를 기록한다. */
    void SetPanelVisibility(const std::array<bool, 4>& visible);
    /** @brief 명시적인 선택 편집 요청에 따라 속성 패널 또는 속성 탭을 보인다. */
    void ShowProperties(bool focus = false);
    /** @brief 검색과 객체 이름 변경 시 탐색 탭을 명시적으로 보인다. */
    void ShowNavigation(bool focus = false);
    /** @brief 결과 목록/조건 View에서는 설계 레이어를 숨기되 사용자 배치를 보존한다. */
    void SetResultContext(bool active, bool study = false, bool validation = false, bool output = false);
    /** @brief F6와 Shift+F6의 논리적 패널 순서로 키보드 초점을 옮긴다. */
    void FocusNext(bool reverse = false);
    /** @brief 현재 탐색/속성 탭 배치 여부를 반환한다. */
    bool IsCompact() const
    {
        return m_compact;
    }

private:
    void ApplyResponsiveLayout();
    void SetCompact(bool compact);
    void ApplyVisibility();
    /** @brief 좁은 보기의 두 메뉴는 한 패널 상태를 공유한다. */
    std::size_t VisibilityIndex(std::size_t index) const;
    /** @brief 명시적인 메뉴, 닫기 및 기본 배치 선택만 사용자 설정으로 기록한다. */
    void SaveVisibility(std::size_t index);
    void OnSize(wxSizeEvent& event);
    void OnKey(wxKeyEvent& event);
    void OnMenu(wxCommandEvent& event);
    void OnUpdateMenu(wxUpdateUIEvent& event);
    void OnPaneClose(wxAuiManagerEvent& event);
    wxFrame& m_frame;
    wxAuiManager& m_manager;
    wxNotebook& m_navigation;
    wxWindow& m_tree;
    wxPanel& m_propertiesHost;
    wxPanel& m_properties;
    wxWindow& m_views;
    wxWindow& m_bottom;
    WorkspaceBar& m_workspaceBar;
    wxWindow* m_layersHost = nullptr;
    wxWindow* m_layers = nullptr;
    wxString m_defaultLayout;
    std::array<int, 4> m_menuIds{};
    static constexpr std::size_t CompactNavigation = 4;
    std::array<bool, 5> m_visible{{true, true, true, true, true}};
    bool m_usePreferences = false;
    bool m_compact = false;
    bool m_updating = false;
    bool m_resultContext = false;
    bool m_studyContext = false;
    bool m_validationContext = false;
    bool m_outputContext = false;
};
