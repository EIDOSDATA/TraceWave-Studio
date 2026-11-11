/** @file @brief 물성 제안의 개정 및 기존 입력 보존을 위젯 없이 검사한다. */
#include "pcb_suggestion_model.h"
#include "pcb_selection_model_data.h"
#include <cmath>
#include <set>

namespace Studio::PcbSuggestions
{
using PcbSelectionData::Require;

std::string StateLabel(const std::string& state)
{
    if (state == "published" || state == "source_value")
    {
        return "공개값";
    }
    if (state == "missing" || state == "unresolved")
    {
        return "미정";
    }
    if (state == "ambiguous")
    {
        return "후보 충돌";
    }
    if (state == "approximation_required")
    {
        return "근사 입력 필요";
    }
    return "자동 제안 미지원";
}

void Validate(const Json& source, const Json& response)
{
    PcbSelectionData::Source(source);
    PcbSelectionData::Bounded(response);
    Require(!source.is_null() && response.at("schema") == "rfad.pcb-stackup-suggestions/0.1" &&
                response.at("source") == source && response.at("readiness") == "not_assessed",
            "선택한 적층과 물성 제안의 출처 개정이 다릅니다.");
    PcbSelectionData::Draft(source, response.at("draft"));
    const auto& suggestions = response.at("layers");
    Require(suggestions.is_array() && suggestions.size() <= 8, "표시할 물성 제안 페이지의 층 수가 올바르지 않습니다.");
    Require(response.at("offset").is_number_integer() && response.at("offset").get<int>() >= 0 &&
                response.at("offset") <= response.at("draft").at("layers").size() &&
                response.at("returned_count") == suggestions.size() &&
                response.at("total_count") == response.at("draft").at("layers").size(),
            "물성 제안 페이지 범위가 올바르지 않습니다.");
    const auto end = response.at("offset").get<std::size_t>() + suggestions.size();
    Require(end <= response.at("total_count").get<std::size_t>(), "물성 제안이 전체 층 범위를 벗어났습니다.");
    for (const char* field : {"next_offset"})
    {
        const auto& offset = response.at(field);
        Require(offset.is_null() || (offset.is_number_integer() && offset.get<int>() >= 0 &&
                                     offset.get<std::size_t>() < response.at("total_count").get<std::size_t>()),
                "물성 제안 페이지 연결이 올바르지 않습니다.");
        Require(offset.is_null() ? end == response.at("total_count").get<std::size_t>()
                                 : !suggestions.empty() && offset == end,
                "물성 제안의 다음 페이지가 현재 범위를 이어가지 않습니다.");
    }
    std::set<std::string> seen;
    const std::set<std::string> states = {"published", "missing", "ambiguous", "approximation_required", "unsupported"};
    for (const auto& suggestion : suggestions)
    {
        const std::string key = suggestion.at("layer_key");
        Require(!key.empty() && seen.insert(key).second, "물성 제안의 층 식별자가 중복되거나 없습니다.");
        const Json* matched = nullptr;
        for (const auto& layer : response.at("draft").at("layers"))
        {
            if (layer.at("key") == key)
            {
                matched = &layer;
            }
        }
        Require(matched != nullptr && matched->at("role") == suggestion.at("role") &&
                    matched->at("thickness_mm") == suggestion.at("thickness_mm"),
                "물성 제안의 층 또는 두께가 선택한 적층과 다릅니다.");
        for (const char* field : {"epsilon_r", "tan_delta"})
        {
            const auto& property = suggestion.at("properties").at(field);
            Require(states.count(property.at("state").get<std::string>()) != 0, "지원하지 않는 물성 제안 상태입니다.");
            const auto& value = property.at("value");
            Require(value.is_null() || (value.is_number() && std::isfinite(value.get<double>())),
                    "물성 제안에는 숫자 또는 미정값이 필요합니다.");
            Require(property.at("reason").is_string(), "물성 제안의 출처 및 상태 설명이 없습니다.");
        }
        const auto& material = suggestion.at("material_spec");
        Require(material.is_null() || (suggestion.at("role") == "dielectric" && material.is_object() &&
                                       material.at("key").is_string() && material.at("name").is_string()),
                "유전체 층에 연결할 제안 재료가 올바르지 않습니다.");
    }
}

Json PrepareUse(const Json& source, const Json& response, std::size_t index, const Json& layers, const Json& materials)
{
    Validate(source, response);
    Require(index < response.at("layers").size(), "먼저 사용할 물성 제안을 선택하세요.");
    const auto& suggestion = response.at("layers").at(index);
    const auto& material = suggestion.at("material_spec");
    Require(!material.is_null(), "이 층은 자동 연결할 재료 제안이 없습니다. 직접 입력을 사용하세요.");
    Require(materials.size() < 16, "한 번에 선택할 재료는 최대 16개입니다.");
    bool found = false;
    for (const auto& layer : layers)
    {
        if (layer.at("key") == suggestion.at("layer_key"))
        {
            Require(layer.at("role") == "dielectric", "제안한 유전체 층의 역할이 변경되었습니다.");
            Require(layer.value("material_id", Json(nullptr)).is_null(),
                    "이 층에는 이미 재료가 연결되어 있습니다. 기존 연결을 직접 해제한 뒤 제안을 사용하세요.");
            found = true;
        }
    }
    Require(found, "제안에 대응하는 층이 현재 편집 목록에 없습니다.");
    for (const auto& current : materials)
    {
        Require(current.at("key") != material.at("key"),
                "이 제안 재료는 이미 추가했습니다. 재료 목록에서 직접 수정하거나 연결하세요.");
    }
    return {{"layer_key", suggestion.at("layer_key")}, {"material", material}};
}
}
