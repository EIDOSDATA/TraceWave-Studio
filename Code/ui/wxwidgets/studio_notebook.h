/** @file @brief 안정된 페이지 번호와 업무별 native 하위 탭을 연결한다. */
#pragma once

#include <wx/panel.h>
#include <functional>
#include <vector>

class wxAuiNotebook;
class wxAuiNotebookEvent;

/** @brief 숨기는 페이지도 파괴하지 않아 폼 초안과 GL 장면을 유지한다. */
class StudioNotebook final : public wxPanel
{
public:
    explicit StudioNotebook(wxWindow* parent);
    ~StudioNotebook() override;
    bool AddPage(wxWindow* page, const wxString& label, bool select = false);
    wxWindow* GetPage(std::size_t index) const;
    std::size_t GetPageCount() const;
    int GetSelection() const;
    int SetSelection(std::size_t index);
    void SetPageText(std::size_t index, const wxString& label);
    /** @brief 같은 업무 번호의 페이지만 탭으로 표시하며 원래 인덱스는 유지한다. */
    void SetGroups(const std::vector<int>& groups);
    /** @brief 서비스 연결 인덱스를 바꾸지 않고 화면의 탭 순서만 지정한다. */
    void SetDisplayOrder(const std::vector<std::size_t>& order);
    std::size_t VisiblePageCount() const;
    std::function<void(int)> onSelectionChanged;

private:
    struct Page
    {
        wxWindow* window;
        wxString label;
        int group = 0;
    };
    void ShowGroup(int group);
    void OnPageChanged(wxAuiNotebookEvent& event);
    wxAuiNotebook* m_book = nullptr;
    std::vector<Page> m_pages;
    std::vector<std::size_t> m_visible;
    std::vector<std::size_t> m_order;
    int m_selection = wxNOT_FOUND;
    int m_group = 0;
    bool m_switching = false;
};
