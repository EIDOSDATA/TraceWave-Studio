/** @file @brief PCB 선택 입력과 표시 DTO를 검사하며 물리 수치의 계산은 서비스에 맡긴다. */
#include "pcb_selection_model_data.h"
#include "pcb_selection_model.h"
#include <cmath>
#include <regex>
#include <set>
#include <stdexcept>

namespace Studio::PcbSelectionData
{
void Require(bool condition, const std::string& message)
{
    if (!condition)
    {
        throw std::invalid_argument(message);
    }
}

/** @brief 빈 문자열과 숫자로 바뀐 식별자를 허용하지 않는다. */
void Text(const Json& value)
{
    Require(value.is_string() && !value.get_ref<const std::string&>().empty(), "명시적인 문자열이 필요합니다.");
}

/** @brief 작은 JSON DTO의 모든 실수는 유한해야 하며 null로 자동 대체하지 않는다. */
void Finite(const Json& value)
{
    if (value.is_number_float())
    {
        Require(std::isfinite(value.get<double>()), "유한 숫자만 사용할 수 있습니다.");
    }
    else if (value.is_structured())
    {
        for (const auto& child : value)
        {
            Finite(child);
        }
    }
}

void Bounded(const Json& value)
{
    Finite(value);
    Require(value.dump().size() <= 384 * 1024, "PCB 화면 DTO의 384 KiB 상한을 초과했습니다.");
}

void Uuid(const Json& value)
{
    Text(value);
    static const std::regex pattern("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}");
    Require(std::regex_match(value.get_ref<const std::string&>(), pattern), "정규 UUID 문자열이 필요합니다.");
}

/** @brief 숫자 0과 미정 null을 분리하고 두께에는 양수만 허용한다. */
void Number(const Json& value, bool positive = false)
{
    Require(value.is_null() ||
                (value.is_number() && std::isfinite(value.get<double>()) && (!positive || value.get<double>() > 0)),
            "명시적 숫자 또는 미정값을 확인하십시오.");
}

void Source(const Json& value)
{
    if (value.is_null())
    {
        return;
    }
    Require(value.is_object() && value.size() == 3 && value.contains("catalog_id") && value.contains("entity") &&
                value.contains("id"),
            "적층 출처의 필드가 올바르지 않습니다.");
    Text(value.at("catalog_id"));
    Text(value.at("id"));
    Require(value.at("entity") == "native_templates" || value.at("entity") == "observations",
            "적층 출처 종류를 확인하십시오.");
}

/** @brief 서비스가 해결한 mm 표시값만 검사하고 단위 환산을 하지 않는다. */
void DisplayLayers(const Json& values)
{
    Require(values.is_array(), "층 표시는 목록이어야 합니다.");
    std::set<std::string> ids;
    for (const auto& item : values)
    {
        Uuid(item.at("id"));
        Require(ids.insert(item.at("id").get<std::string>()).second, "층 ID가 중복됩니다.");
        Text(item.at("name"));
        Text(item.at("role"));
        Number(item.at("thickness_mm"), true);
        Number(item.at("z_min_mm"));
        Require(item.at("parameter_bound").is_boolean(), "층의 매개변수 상태가 올바르지 않습니다.");
        if (!item.at("material_id").is_null())
        {
            Uuid(item.at("material_id"));
        }
    }
}

void Context(const Json& value)
{
    Bounded(value);
    Uuid(value.at("project_id"));
    Uuid(value.at("revision_id"));
    DisplayLayers(value.at("layers"));
    Require(value.at("materials").is_array() && value.at("ports").is_array(), "재료와 포트 문맥은 목록이어야 합니다.");
    for (const auto& material : value.at("materials"))
    {
        Uuid(material.at("id"));
        Text(material.at("name"));
    }
}

void Specification(const Json& value)
{
    Bounded(value);
    Require(value.is_object() && value.contains("source") && value.contains("materials"),
            "선택 사양의 필수 필드가 없습니다.");
    static const std::set<std::string> allowed = {
        "source",    "materials",    "layers",      "layout_reason", "thickness_overrides", "material_assignments",
        "layer_ids", "material_ids", "z_origin_mm", "notes",         "port_updates",        "catalog_id"};
    for (const auto& item : value.items())
    {
        Require(allowed.count(item.key()) != 0, "선택 사양에 지원하지 않는 필드가 있습니다.");
    }
    Source(value.at("source"));
    Require(value.at("materials").is_array() && value.at("materials").size() <= 16, "재료 선택은 최대 16개입니다.");
    for (const auto* field : {"layer_ids", "material_ids", "material_assignments", "thickness_overrides"})
    {
        if (value.contains(field))
        {
            Require(value.at(field).is_object() && value.at(field).size() <= 32,
                    "층 또는 재료 대응은 최대 32개 객체입니다.");
        }
    }
    for (const auto* field : {"layer_ids", "material_ids"})
    {
        for (const auto& item : value.value(field, Json::object()))
        {
            Uuid(item);
        }
    }
    for (const auto& item : value.value("thickness_overrides", Json::object()))
    {
        Require(item.is_object() && item.size() == 2 && item.contains("value_mm") && item.contains("reason"),
                "두께 수정에는 값과 이유가 필요합니다.");
        Number(item.at("value_mm"), true);
        Text(item.at("reason"));
    }
    if (value.contains("layers"))
    {
        Text(value.at("layout_reason"));
        Require(value.at("layers").is_array() && !value.at("layers").empty() && value.at("layers").size() <= 32,
                "직접 정의한 적층은 1~32개 층이어야 합니다.");
        std::set<std::string> keys;
        for (const auto& layer : value.at("layers"))
        {
            Require(layer.is_object() && layer.size() == 4, "수동 층의 필드를 확인하십시오.");
            Text(layer.at("key"));
            Text(layer.at("name"));
            Text(layer.at("role"));
            Require(keys.insert(layer.at("key").get<std::string>()).second, "수동 층 key가 중복됩니다.");
            Number(layer.at("thickness_mm"), true);
        }
    }
    if (value.contains("z_origin_mm"))
    {
        Require(!value.at("z_origin_mm").is_null(), "원점에는 명시적인 mm 값이 필요합니다.");
        Number(value.at("z_origin_mm"));
    }
    if (value.contains("catalog_id"))
    {
        Text(value.at("catalog_id"));
        Require(value.at("source").is_null() || value.at("source").at("catalog_id") == value.at("catalog_id"),
                "재료와 적층은 동일 카탈로그 개정에서 선택해야 합니다.");
    }
}

void Draft(const Json& source, const Json& value)
{
    Bounded(value);
    Require(value.is_object() && value.at("schema") == "rfad.pcb-stackup-draft/0.1" &&
                value.at("catalog_id") == source.at("catalog_id"),
            "원문 초안의 개정이 선택과 다릅니다.");
    const auto* field = source.at("entity") == "native_templates" ? "template_id" : "record_id";
    Require(value.at(field) == source.at("id"), "원문 초안의 개체 ID가 선택과 다릅니다.");
    Require(value.at("layer_order") == "bottom_to_top" && value.at("layers").is_array(),
            "지원하지 않는 원문 층 순서입니다.");
    std::set<std::string> keys;
    for (const auto& layer : value.at("layers"))
    {
        Text(layer.at("key"));
        Text(layer.at("name"));
        Text(layer.at("role"));
        Require(keys.insert(layer.at("key").get<std::string>()).second, "원문 초안의 층 key가 중복됩니다.");
        Number(layer.at("thickness_mm"), true);
    }
}

void Preview(const Json& value)
{
    Bounded(value);
    Require(value.is_object() && value.at("profile") == "rfad.pcb-selection/0.1" && value.at("can_apply").is_boolean(),
            "PCB 미리보기 응답의 계약이 다릅니다.");
    Uuid(value.at("project_id"));
    Uuid(value.at("expected_revision"));
    Uuid(value.at("selection_id"));
    Text(value.at("preview_hash"));
    static const std::regex hash("[0-9a-f]{64}");
    Require(std::regex_match(value.at("preview_hash").get_ref<const std::string&>(), hash),
            "미리보기 해시가 올바르지 않습니다.");
    DisplayLayers(value.at("candidate_layers"));
}
}

namespace Studio
{
Json PcbSelectionModel::LayerRows() const
{
    const bool manual = m_specification.contains("layers");
    const bool existing = !manual && m_draft.is_null();
    const auto& values =
        manual ? m_specification.at("layers") : (existing ? m_context.at("layers") : m_draft.at("layers"));
    const auto overrides = m_specification.value("thickness_overrides", Json::object());
    const auto mapping = m_specification.value("layer_ids", Json::object());
    const auto assignments = m_specification.value("material_assignments", Json::object());
    Json result = Json::array();
    for (const auto& layer : values)
    {
        const auto key = layer.at(existing ? "id" : "key").get<std::string>();
        Json mapped = existing ? layer.at("id") : Json(nullptr);
        if (mapping.contains(key))
        {
            mapped = mapping.at(key);
        }
        Json material = existing ? layer.at("material_id") : Json(nullptr);
        for (const auto& old : m_context.at("layers"))
        {
            if (old.at("id") == mapped)
            {
                material = old.at("material_id");
            }
        }
        if (assignments.contains(key))
        {
            material = assignments.at(key);
        }
        const bool overridden = overrides.contains(key);
        result.push_back(Json{
            {"key", key},
            {"name", layer.at("name")},
            {"role", layer.at("role")},
            {"thickness_mm", overridden ? overrides.at(key).at("value_mm") : layer.at("thickness_mm")},
            {"source_thickness_mm", layer.at("thickness_mm")},
            {"z_min_mm", existing ? layer.at("z_min_mm") : Json(nullptr)},
            {"existing_layer_id", mapped},
            {"material_id", material},
            {"parameter_bound", existing && layer.value("parameter_bound", false)},
            {"status", overridden ? "user_override" : (existing ? "existing" : layer.value("status", "user_entered"))},
            {"reason", overridden ? overrides.at(key).at("reason") : layer.value("thickness_basis", Json(""))},
            {"overridden", overridden}});
    }
    return result;
}

Json PcbSelectionModel::CandidateLayers() const
{
    return m_preview.is_object() ? m_preview.at("candidate_layers") : Json::array();
}
}
