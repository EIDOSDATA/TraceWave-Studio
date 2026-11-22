/** @file @brief 보고서에서 직접 연 원본의 실제 해석 목록 위치만 찾아 선택을 동기화한다. */
#include "result_workspace.h"
#include "result_source_browser.h"
#include "studio_support.h"
#include <algorithm>
#include <stdexcept>

void ResultWorkspace::LocatePinnedSource(const Json& source, const Json& pin, int offset,
                                         std::uint64_t catalogGeneration, std::uint64_t selectionGeneration)
{
    const auto current = [this, source, pin, catalogGeneration, selectionGeneration]()
    {
        return catalogGeneration == m_catalogGeneration && selectionGeneration == m_selectionGeneration &&
               m_browser->Kind() == "solver" && m_description.is_object() && m_description.at("source") == source &&
               m_description.at("pin") == pin;
    };
    Read(
        "result.sources",
        {{"kind", "solver"},
         {"revision_id", nullptr},
         {"snapshot_id", nullptr},
         {"study_id", nullptr},
         {"offset", offset},
         {"limit", 25},
         {"catalog_hash", offset == 0 ? Json(nullptr) : Json(m_catalogHash)}},
        current,
        [this, source, pin, offset, catalogGeneration, selectionGeneration](const Json& response)
        {
            const auto& items = response.at("items");
            const auto next = response.at("next_offset");
            if (!items.is_array() || items.size() > 25 || response.at("offset") != offset ||
                !response.at("catalog_hash").is_string() ||
                (offset > 0 && response.at("catalog_hash") != m_catalogHash) ||
                (!next.is_null() &&
                 (!next.is_number_integer() || next != offset + static_cast<int>(items.size()) || items.empty())))
            {
                throw std::runtime_error("직접 연 결과 목록의 고정 해시 또는 다음 페이지가 다릅니다.");
            }
            m_catalogHash = response.at("catalog_hash").get<std::string>();
            const bool found = std::any_of(items.begin(), items.end(),
                                           [&source](const Json& item)
                                           {
                                               return item.at("source") == source;
                                           });
            if (found || next.is_null() || offset >= 1575)
            {
                m_catalog = response;
                m_browser->SetCatalog(response, source);
                m_browser->SetStatus(
                    found ? "선택한 기록과 동일한 봉인 해석 원본을 표시합니다."
                          : "선택한 봉인 원본을 표시 중입니다. 조회한 목록 범위에는 없어 선택 행을 두지 않습니다.");
                return;
            }
            /** @brief 한 번의 직접 열기는 최대 64페이지까지만 읽으며 곡선의 원본을 대체하지 않는다. */
            LocatePinnedSource(source, pin, next.get<int>(), catalogGeneration, selectionGeneration);
        },
        [this](const Json& error)
        {
            m_browser->SetStatus("봉인 원본은 유지합니다. 해당 목록 위치 조회 실패: " + DiagnosticMessage(error));
        });
}
