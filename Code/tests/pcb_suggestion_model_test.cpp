/** @file @brief 적층 제안의 출처와 기존 직접 입력 보존을 실제 presentation helper로 검사한다. */
#include "pcb_suggestion_model.h"
#include <cstdlib>
#include <iostream>
#include <limits>

namespace
{
using Json = Studio::PcbSuggestions::Json;

/** @brief Release 구성에서도 실패를 숨기지 않는다. */
void Check(bool condition, const char* message)
{
    if (!condition)
    {
        std::cerr << "PCB suggestion: " << message << '\n';
        std::exit(1);
    }
}

/** @brief 계약 위반이 명시적으로 거부되는지 확인한다. */
template <class Action> void Reject(Action action)
{
    try
    {
        action();
    }
    catch (const std::exception&)
    {
        return;
    }
    Check(false, "invalid use accepted");
}

Json Source()
{
    return {{"catalog_id", "catalog:fixture"}, {"entity", "native_templates"}, {"id", "template:fixture"}};
}

Json Response()
{
    const Json dk{{"state", "published"},
                  {"value", 4.2},
                  {"reason", "시험 관측"},
                  {"record_id", "record:1"},
                  {"conditions", Json::object()}};
    const Json df{{"state", "missing"},
                  {"value", nullptr},
                  {"reason", "Df 미제공"},
                  {"record_id", nullptr},
                  {"conditions", Json::object()}};
    const Json material{{"key", "suggested:core"},
                        {"name", "제안 코어"},
                        {"model", "isotropic_constant_total_tan_delta"},
                        {"model_reason", "총 Df 모델 제안"},
                        {"properties",
                         {{"epsilon_r", {{"mode", "catalog"}, {"record_id", "record:1"}, {"reason", "공개값"}}},
                          {"tan_delta", {{"mode", "missing"}, {"reason", "미제공"}}},
                          {"conductivity", {{"mode", "missing"}, {"reason", "비소비"}}}}},
                        {"validity_hz", {{"min", nullptr}, {"max", nullptr}, {"reason", "대역 미정"}}}};
    return {{"offset", 0},
            {"returned_count", 1},
            {"total_count", 1},
            {"next_offset", nullptr},
            {"schema", "rfad.pcb-stackup-suggestions/0.1"},
            {"source", Source()},
            {"readiness", "not_assessed"},
            {"draft",
             {{"schema", "rfad.pcb-stackup-draft/0.1"},
              {"catalog_id", "catalog:fixture"},
              {"template_id", "template:fixture"},
              {"record_id", nullptr},
              {"layer_order", "bottom_to_top"},
              {"layers",
               Json::array({Json{{"key", "core"}, {"name", "코어"}, {"role", "dielectric"}, {"thickness_mm", 1.2}}})}}},
            {"layers", Json::array({Json{{"layer_key", "core"},
                                         {"name", "코어"},
                                         {"role", "dielectric"},
                                         {"thickness_mm", 1.2},
                                         {"thickness_state", "source_value"},
                                         {"properties", {{"epsilon_r", dk}, {"tan_delta", df}}},
                                         {"material_spec", material},
                                         {"notes", Json::array()}}})}};
}

Json Layers()
{
    return Json::array({Json{{"key", "core"},
                             {"role", "dielectric"},
                             {"material_id", nullptr},
                             {"thickness_mm", 1.15},
                             {"edit_reason", "사용자가 수정한 두께"}}});
}
}

int main()
{
    const auto source = Source();
    const auto response = Response();
    auto layers = Layers();
    const auto before = layers;
    const auto usage = Studio::PcbSuggestions::PrepareUse(source, response, 0, layers, Json::array());
    Check(usage.at("material") == response.at("layers").at(0).at("material_spec"), "server material changed");
    Check(layers == before, "manual thickness changed");
    Check(usage.at("material").at("properties").at("tan_delta").at("mode") == "missing", "missing Df filled");
    Check(usage.at("material").at("validity_hz").at("min").is_null(), "model band invented");
    Check(Studio::PcbSuggestions::StateLabel("published") !=
                  Studio::PcbSuggestions::StateLabel("approximation_required") &&
              Studio::PcbSuggestions::StateLabel("missing") != Studio::PcbSuggestions::StateLabel("ambiguous"),
          "states not distinguished");
    layers[0]["material_id"] = "existing-material";
    Reject(
        [&]()
        {
            Studio::PcbSuggestions::PrepareUse(source, response, 0, layers, Json::array());
        });
    Reject(
        [&]()
        {
            Studio::PcbSuggestions::PrepareUse(source, response, 0, before, Json::array({usage.at("material")}));
        });
    Reject(
        [&]()
        {
            Studio::PcbSuggestions::PrepareUse(source, response, 1, before, Json::array());
        });
    auto differentSource = source;
    differentSource["catalog_id"] = "catalog:changed";
    Reject(
        [&]()
        {
            Studio::PcbSuggestions::Validate(differentSource, response);
        });
    auto changed = response;
    changed["layers"][0]["thickness_mm"] = 1.6;
    Reject(
        [&]()
        {
            Studio::PcbSuggestions::Validate(source, changed);
        });
    changed = response;
    changed["layers"][0]["properties"]["epsilon_r"]["value"] = true;
    Reject(
        [&]()
        {
            Studio::PcbSuggestions::Validate(source, changed);
        });
    changed["layers"][0]["properties"]["epsilon_r"]["value"] = std::numeric_limits<double>::infinity();
    Reject(
        [&]()
        {
            Studio::PcbSuggestions::Validate(source, changed);
        });
    changed = response;
    changed["layers"][0]["properties"]["epsilon_r"]["state"] = "assumed_confirmed";
    Reject(
        [&]()
        {
            Studio::PcbSuggestions::Validate(source, changed);
        });
    changed = response;
    changed["offset"] = 2;
    Reject(
        [&]()
        {
            Studio::PcbSuggestions::Validate(source, changed);
        });
    changed = response;
    changed["next_offset"] = 0;
    Reject(
        [&]()
        {
            Studio::PcbSuggestions::Validate(source, changed);
        });
    changed = response;
    changed["layers"].push_back(changed["layers"][0]);
    Reject(
        [&]()
        {
            Studio::PcbSuggestions::Validate(source, changed);
        });
    std::cout << "PCB suggestion state and input preservation checks passed\n";
    return 0;
}
