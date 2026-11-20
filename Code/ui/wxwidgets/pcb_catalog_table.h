/** @file @brief PCB 자료 표가 화면에 필요한 검색 행만 보유한다. */
#pragma once

#include "studio_types.h"
#include <deque>
#include <functional>
#include <map>
#include <wx/listctrl.h>

/** @brief Windows 가상 목록과 제한된 행 캐시를 연결한다. */
class PcbCatalogTable final : public wxListCtrl
{
public:
    static constexpr long PageSize = 25;

    PcbCatalogTable(wxWindow* parent, std::function<void(long)> requestRow);
    void Reset();
    void Begin(const std::string& entity, long count, const Json& firstPage);
    void StorePage(long offset, const Json& rows);
    const Json* Row(long index) const;
    long MissingOffset(long index) const;
    static std::string NativeLabel(const Json& row);
    static std::string NativeDimensions(const Json& row);

protected:
    wxString OnGetItemText(long index, long column) const override;

private:
    static constexpr std::size_t RetainedPages = 8;
    const std::function<void(long)> m_requestRow;
    std::map<long, Json> m_pages;
    std::deque<long> m_pageOrder;
    std::string m_entity;
};
