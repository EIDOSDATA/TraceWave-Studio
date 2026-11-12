/** @file @brief Studio 작업 영역과 자주 사용하는 명령을 native 위젯으로 표시한다. */
#pragma once
#include <wx/panel.h>
#include <array>
#include <functional>

class wxButton;
class wxToggleButton;

enum class WorkspaceArea
{
    Design,
    Analysis,
    Results,
    Comparison,
    Output
};

/** @brief 원본 명령/물리 상태 없이 작업 선택과 버튼 상태만 소유한다. */
class WorkspaceBar final : public wxPanel
{
public:
    explicit WorkspaceBar(wxWindow* parent);
    void Select(WorkspaceArea area);
    void SetCommandState(bool save, bool run, bool step);
    std::function<void(WorkspaceArea)> onNavigate;
    std::function<void(int)> onCommand;

private:
    WorkspaceArea m_selected = WorkspaceArea::Design;
    std::array<wxToggleButton*, 5> m_tabs{};
    wxButton* m_save = nullptr;
    wxButton* m_run = nullptr;
    wxButton* m_step = nullptr;
};
