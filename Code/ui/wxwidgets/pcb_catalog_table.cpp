/** @file @brief 작은 페이지 캐시와 PCB 자료의 표기를 구현한다. */
#include "pcb_catalog_table.h"
#include "pcb_selection_view_support.h"
#include <algorithm>
#include <iterator>
#include <utility>

PcbCatalogTable::PcbCatalogTable(wxWindow* parent, std::function<void(long)> requestRow)
    : wxListCtrl(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_SINGLE_SEL | wxLC_VIRTUAL),
      m_requestRow(std::move(requestRow))
{
}

/** @brief 새 검색에서 이전 행 데이터와 선택이 함께 사라지게 한다. */
void PcbCatalogTable::Reset()
{
    SetItemCount(0);
    m_pages.clear();
    m_pageOrder.clear();
    m_entity.clear();
}

void PcbCatalogTable::Begin(const std::string& entity, long count, const Json& firstPage)
{
    m_entity = entity;
    if (count > 0)
    {
        StorePage(0, firstPage);
    }
    SetItemCount(count);
}

void PcbCatalogTable::StorePage(long offset, const Json& rows)
{
    if (rows.empty())
    {
        return;
    }
    if (m_pages.find(offset) == m_pages.end())
    {
        if (m_pageOrder.size() == RetainedPages)
        {
            m_pages.erase(m_pageOrder.front());
            m_pageOrder.pop_front();
        }
        m_pageOrder.push_back(offset);
    }
    m_pages.insert_or_assign(offset, rows);
    const long last = std::min<long>(GetItemCount() - 1, offset + static_cast<long>(rows.size()) - 1);
    if (offset <= last)
    {
        RefreshItems(offset, last);
    }
}

const Json* PcbCatalogTable::Row(long index) const
{
    const auto after = m_pages.upper_bound(index);
    if (after == m_pages.begin())
    {
        return nullptr;
    }
    const auto& [offset, items] = *std::prev(after);
    const auto position = static_cast<std::size_t>(index - offset);
    return position < items.size() ? &items.at(position) : nullptr;
}

/** @brief 응답 바이트 제한으로 짧게 읽은 페이지의 나머지 구간부터 다시 읽는다. */
long PcbCatalogTable::MissingOffset(long index) const
{
    const long base = index - index % PageSize;
    const auto after = m_pages.upper_bound(index);
    if (after != m_pages.begin())
    {
        const auto& [offset, items] = *std::prev(after);
        return std::max(base, offset + static_cast<long>(items.size()));
    }
    return base;
}

/** @brief 내부 템플릿 ID보다 제조사가 공개한 적층 표기를 우선한다. */
std::string PcbCatalogTable::NativeLabel(const Json& row)
{
    if (row.contains("stackup_label") && row.at("stackup_label").is_string() &&
        !row.at("stackup_label").get<std::string>().empty())
    {
        return row.at("stackup_label");
    }
    if (row.value("kind", std::string()) == "jlc_user_defined_template")
    {
        return "사용자 정의 구성 (공개 적층명 없음)";
    }
    return "공개 적층명 미연결 (상세 확인)";
}

std::string PcbCatalogTable::NativeDimensions(const Json& row)
{
    return PcbView::Text(row, "layer_count") + "층 / 공칭 " + PcbView::Text(row, "nominal_thickness_mm") + " mm";
}

/** @brief 그리기 콜백에서는 I/O 없이 이미 수신한 셀 또는 대기 문구를 반환한다. */
wxString PcbCatalogTable::OnGetItemText(long index, long column) const
{
    const Json* row = Row(index);
    if (row == nullptr)
    {
        m_requestRow(index);
        return column == 0 ? Display("읽는 중") : wxString();
    }
    if (m_entity == "native_templates")
    {
        if (column == 1)
        {
            return Display(NativeLabel(*row));
        }
        if (column == 2)
        {
            return Display(NativeDimensions(*row));
        }
    }
    const char* fields[] = {"publisher", "product", "material_form", "dk", "df", "frequency_ghz"};
    return column >= 0 && column < 6 ? Display(PcbView::Text(*row, fields[column])) : wxString();
}
