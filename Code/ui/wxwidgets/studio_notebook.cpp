/** @file @brief 밑줄 탭의 그림만 사용자 정의하고 입력/초점은 wxAUI가 처리한다. */
#include "studio_notebook.h"
#include "studio_theme.h"
#include <wx/aui/auibook.h>
#include <wx/aui/tabart.h>
#include <wx/dc.h>
#include <wx/sizer.h>
#include <algorithm>
#include <stdexcept>
#include <numeric>

void StudioNotebook::SetTabRowVisible(bool visible)
{
    if (visible == m_tabRowVisible)
    {
        return;
    }
    m_tabRowVisible = visible;
    m_book->SetTabCtrlHeight(visible ? -1 : 0);
    Layout();
}

namespace
{
/** @brief 시안의 평면 탭과 선택 밑줄을 DPI 및 시스템 글꼴에 맞춰 표시한다. */
class StudioTabArt final : public wxAuiGenericTabArt
{
public:
    wxAuiTabArt* Clone() override
    {
        return new StudioTabArt(*this);
    }

    void DrawBackground(wxDC& dc, wxWindow*, const wxRect& rect) override
    {
        const auto colours = StudioTheme::Colours();
        dc.SetPen(wxPen(colours.border));
        dc.SetBrush(wxBrush(colours.panel));
        dc.DrawRectangle(rect);
    }

    void DrawBorder(wxDC&, wxWindow*, const wxRect&) override {}

    int GetBorderWidth(wxWindow*) override
    {
        return 0;
    }

    int GetAdditionalBorderSpace(wxWindow*) override
    {
        return 0;
    }

    int GetIndentSize() override
    {
        return 8;
    }

    int GetBestTabCtrlSize(wxWindow* window, const wxAuiNotebookPageArray&, const wxSize&) override
    {
        return std::max(window->FromDIP(StudioTheme::TabHeight), window->GetCharHeight() + window->FromDIP(16));
    }

    wxSize GetTabSize(wxDC& dc, wxWindow* window, const wxString& caption, const wxBitmapBundle&, bool, int,
                      int* extent) override
    {
        dc.SetFont(window->GetFont().Bold());
        const int width = std::max(window->FromDIP(88), dc.GetTextExtent(caption).x + window->FromDIP(40));
        *extent = width;
        return wxSize(width,
                      std::max(window->FromDIP(StudioTheme::TabHeight), dc.GetCharHeight() + window->FromDIP(16)));
    }

    void DrawTab(wxDC& dc, wxWindow* window, const wxAuiNotebookPage& page, const wxRect& rect, int, wxRect* tabRect,
                 wxRect* buttonRect, int* extent) override
    {
        const auto colours = StudioTheme::Colours();
        const auto size = GetTabSize(dc, window, page.caption, page.bitmap, page.active, 0, extent);
        *tabRect = wxRect(rect.GetPosition(), wxSize(size.x, rect.height));
        *buttonRect = wxRect();
        dc.SetPen(*wxTRANSPARENT_PEN);
        dc.SetBrush(wxBrush(page.active ? colours.content : colours.panel));
        dc.DrawRectangle(*tabRect);
        dc.SetFont(page.active ? window->GetFont().Bold() : window->GetFont());
        dc.SetTextForeground(page.active ? colours.accent : colours.secondary);
        const auto text = dc.GetTextExtent(page.caption);
        dc.DrawText(page.caption, rect.x + (size.x - text.x) / 2, rect.y + (rect.height - text.y) / 2);
        if (page.active)
        {
            dc.SetBrush(wxBrush(colours.accent));
            dc.DrawRectangle(rect.x + window->FromDIP(8), rect.GetBottom() - window->FromDIP(2),
                             size.x - window->FromDIP(16), window->FromDIP(3));
        }
        if (page.active && wxWindow::FindFocus() == window)
        {
            dc.SetPen(wxPen(colours.accent, 1, wxPENSTYLE_DOT));
            dc.SetBrush(*wxTRANSPARENT_BRUSH);
            wxRect focusRect = *tabRect;
            dc.DrawRectangle(focusRect.Deflate(window->FromDIP(4)));
        }
    }
};
}

StudioNotebook::StudioNotebook(wxWindow* parent) : wxPanel(parent)
{
    StudioTheme::BindSurface(*this);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    m_book =
        new wxAuiNotebook(this, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxAUI_NB_TOP | wxAUI_NB_SCROLL_BUTTONS);
    m_book->SetArtProvider(new StudioTabArt);
    m_book->SetFont(GetFont());
    m_book->SetTabCtrlHeight(std::max(FromDIP(StudioTheme::TabHeight), GetCharHeight() + FromDIP(16)));
    layout->Add(m_book, 1, wxEXPAND);
    SetSizer(layout);
    m_book->Bind(wxEVT_AUINOTEBOOK_PAGE_CHANGED, &StudioNotebook::OnPageChanged, this);
    Bind(wxEVT_SET_FOCUS,
         [this](wxFocusEvent& event)
         {
             m_book->SetFocus();
             event.Skip();
         });
}

StudioNotebook::~StudioNotebook()
{
    // @brief 자식 native notebook 파괴 전에 표시 상태에 접근하는 이벤트를 해제한다.
    m_book->Unbind(wxEVT_AUINOTEBOOK_PAGE_CHANGED, &StudioNotebook::OnPageChanged, this);
    onSelectionChanged = {};
}

void StudioNotebook::OnPageChanged(wxAuiNotebookEvent& event)
{
    if (!m_switching && event.GetSelection() >= 0 && static_cast<std::size_t>(event.GetSelection()) < m_visible.size())
    {
        m_selection = static_cast<int>(m_visible[static_cast<std::size_t>(event.GetSelection())]);
        if (onSelectionChanged)
        {
            onSelectionChanged(m_selection);
        }
    }
}

bool StudioNotebook::AddPage(wxWindow* page, const wxString& label, bool select)
{
    page->Reparent(m_book);
    m_pages.push_back({page, label, 0});
    m_order.push_back(m_pages.size() - 1);
    m_switching = true;
    m_visible.push_back(m_pages.size() - 1);
    const bool result = m_book->AddPage(page, label, select || m_selection == wxNOT_FOUND);
    if (m_selection == wxNOT_FOUND || select)
    {
        m_selection = static_cast<int>(m_pages.size() - 1);
    }
    m_switching = false;
    return result;
}

wxWindow* StudioNotebook::GetPage(std::size_t index) const
{
    return m_pages.at(index).window;
}

std::size_t StudioNotebook::GetPageCount() const
{
    return m_pages.size();
}

int StudioNotebook::GetSelection() const
{
    return m_selection;
}

std::size_t StudioNotebook::VisiblePageCount() const
{
    return m_visible.size();
}

void StudioNotebook::SetGroups(const std::vector<int>& groups)
{
    if (groups.size() != m_pages.size())
    {
        throw std::invalid_argument("Studio page group count does not match pages.");
    }
    for (std::size_t index = 0; index < groups.size(); ++index)
    {
        m_pages[index].group = groups[index];
    }
    ShowGroup(m_pages.at(static_cast<std::size_t>(std::max(0, m_selection))).group);
}

void StudioNotebook::ShowGroup(int group)
{
    m_switching = true;
    Freeze();
    while (m_book->GetPageCount() != 0)
    {
        wxWindow* page = m_book->GetPage(0);
        m_book->RemovePage(0);
        page->Hide();
    }
    m_visible.clear();
    m_group = group;
    for (const auto index : m_order)
    {
        if (m_pages[index].group == group)
        {
            m_visible.push_back(index);
            m_book->AddPage(m_pages[index].window, m_pages[index].label, static_cast<int>(index) == m_selection);
        }
    }
    Layout();
    Thaw();
    m_switching = false;
}

void StudioNotebook::SetDisplayOrder(const std::vector<std::size_t>& order)
{
    std::vector<std::size_t> sorted = order;
    std::sort(sorted.begin(), sorted.end());
    std::vector<std::size_t> expected(m_pages.size());
    std::iota(expected.begin(), expected.end(), 0);
    if (sorted != expected)
    {
        throw std::invalid_argument("Studio tab order does not cover each page exactly once.");
    }
    m_order = order;
    ShowGroup(m_group);
}

int StudioNotebook::SetSelection(std::size_t index)
{
    if (index >= m_pages.size())
    {
        return wxNOT_FOUND;
    }
    const int previous = m_selection;
    m_selection = static_cast<int>(index);
    if (m_pages[index].group != m_group)
    {
        ShowGroup(m_pages[index].group);
    }
    m_switching = true;
    const auto found = std::find(m_visible.begin(), m_visible.end(), index);
    m_book->SetSelection(static_cast<std::size_t>(found - m_visible.begin()));
    m_switching = false;
    if (onSelectionChanged && previous != m_selection)
    {
        onSelectionChanged(m_selection);
    }
    return previous;
}

void StudioNotebook::SetPageText(std::size_t index, const wxString& label)
{
    m_pages.at(index).label = label;
    const auto found = std::find(m_visible.begin(), m_visible.end(), index);
    if (found != m_visible.end())
    {
        m_book->SetPageText(static_cast<std::size_t>(found - m_visible.begin()), label);
    }
}
