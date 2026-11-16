/** @file @brief 저장/실행/출력과 작업 탭을 공통 테마 및 키보드 입력으로 제공한다. */
#include "workspace_bar.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/artprov.h>
#include <wx/button.h>
#include <wx/sizer.h>
#include <wx/tglbtn.h>
#include <wx/wrapsizer.h>
#include <wx/settings.h>
#include <algorithm>

WorkspaceBar::WorkspaceBar(wxWindow* parent) : wxPanel(parent)
{
    StudioTheme::BindSurface(*this);
    SetName("workspace.actions");
    auto* layout = new wxBoxSizer(wxHORIZONTAL);
    const auto command = [this, layout](const std::string& label, const wxArtID& icon, int action)
    {
        auto* button = new wxButton(this, wxID_ANY, Display(label));
        button->SetBitmap(wxArtProvider::GetBitmap(icon, wxART_BUTTON, FromDIP(wxSize(16, 16))));
        const auto best = button->GetBestSize();
        button->SetMinSize(wxSize(std::max(best.GetWidth() + FromDIP(8), FromDIP(90)),
                                  std::max(best.GetHeight(), FromDIP(StudioTheme::ToolHeight))));
        button->SetName(Display("workspace." + std::to_string(action)));
        layout->Add(button, 0, wxALL, FromDIP(StudioTheme::Space));
        button->Bind(wxEVT_BUTTON, [this, action](wxCommandEvent&)
        {
            if (onCommand)
            {
                onCommand(action);
            }
        });
        return button;
    };
    m_save = command("저장", wxART_FILE_SAVE, 0);
    m_run = command("실행 전 확인", wxART_GO_FORWARD, 1);
    m_run->SetToolTip(Display("해석 조건을 확인한 후 명시적으로 실행합니다."));
    m_step = command("STEP 출력", wxART_NORMAL_FILE, 2);
    layout->AddSpacer(FromDIP(StudioTheme::InputGap));
    const std::array<const char*, 5> names{"설계", "해석", "결과", "비교", "출력"};
    for (std::size_t index = 0; index < names.size(); ++index)
    {
        auto* button = new wxToggleButton(this, wxID_ANY, Display(names[index]));
        button->SetName(Display("workspace.area." + std::to_string(index)));
        const auto best = button->GetBestSize();
        button->SetMinSize(wxSize(std::max(best.GetWidth(), FromDIP(68)),
                                  std::max(best.GetHeight(), FromDIP(StudioTheme::ToolHeight))));
        button->SetFont(button->GetFont().Bold());
        m_tabs[index] = button;
        layout->Add(button, 0, wxALL, FromDIP(StudioTheme::Space));
        button->Bind(wxEVT_TOGGLEBUTTON, [this, index](wxCommandEvent&)
        {
            Select(static_cast<WorkspaceArea>(index));
            if (onNavigate)
            {
                onNavigate(static_cast<WorkspaceArea>(index));
            }
        });
        button->Bind(wxEVT_KEY_DOWN, [this, index](wxKeyEvent& event)
        {
            const int key = event.GetKeyCode();
            if (key != WXK_LEFT && key != WXK_RIGHT && key != WXK_HOME && key != WXK_END)
            {
                event.Skip();
                return;
            }
            const std::size_t next = key == WXK_HOME ? 0 : (key == WXK_END ? m_tabs.size() - 1 :
                (index + m_tabs.size() + (key == WXK_LEFT ? -1 : 1)) % m_tabs.size());
            const auto area = static_cast<WorkspaceArea>(next);
            Select(area);
            m_tabs[next]->SetFocus();
            if (onNavigate)
            {
                onNavigate(area);
            }
        });
    }
    SetSizer(layout);
    Select(WorkspaceArea::Design);
    Bind(wxEVT_SYS_COLOUR_CHANGED, [this](wxSysColourChangedEvent& event)
    {
        Select(m_selected);
        event.Skip();
    });
}

void WorkspaceBar::Select(WorkspaceArea area)
{
    m_selected = area;
    const auto colours = StudioTheme::Colours();
    for (std::size_t index = 0; index < m_tabs.size(); ++index)
    {
        const bool selected = index == static_cast<std::size_t>(area);
        m_tabs[index]->SetValue(selected);
        m_tabs[index]->SetToolTip(m_tabs[index]->GetLabel() + Display(selected ? " 작업 영역 (현재)" : " 작업 영역으로 이동"));
        m_tabs[index]->SetBackgroundColour(selected ? wxSystemSettings::GetColour(wxSYS_COLOUR_HIGHLIGHT) : colours.panel);
        m_tabs[index]->SetForegroundColour(selected ? wxSystemSettings::GetColour(wxSYS_COLOUR_HIGHLIGHTTEXT) : colours.text);
        m_tabs[index]->Refresh();
    }
}

void WorkspaceBar::SetCommandState(bool save, bool run, bool step)
{
    m_save->Enable(save);
    m_run->Enable(run);
    m_step->Enable(step);
}
