/** @file @brief PCB 표시 선택과 필드 교체가 원본/미정/검토 정체성을 보존하는지 검사한다. */
#include "pcb_feature_model.h"
#include "pcb_import_model.h"
#include "canvas_scene.h"
#include <cmath>
#include <iostream>
#include <stdexcept>

namespace
{
void Check(bool value, const char* message)
{
    if (!value)
    {
        throw std::runtime_error(message);
    }
}
}

int main()
{
    try
    {
        const Json originalRequest{{"method", "pcb.import.apply"},
                                   {"input", {{"upload_id", "upload-a"}, {"review_hash", "review-a"}}}};
        const Json receipt{{"upload_id", "upload-a"},
                           {"project_id", "project-a"},
                           {"new_revision", "revision-b"},
                           {"review_hash", "review-a"}};
        Check(PcbImportUi::MatchesResponse(originalRequest, receipt, "project-a"), "matching import receipt rejected");
        for (const auto* field : {"upload_id", "project_id", "review_hash"})
        {
            auto wrong = receipt;
            wrong[field] = "different";
            Check(!PcbImportUi::MatchesResponse(originalRequest, wrong, "project-a"),
                  "foreign import receipt released recovery gate");
        }
        const Json chunk{{"method", "pcb.import.chunk"},
                         {"input", {{"upload_id", "upload-a"}, {"path", "원문.gbr"}, {"offset", 4}}}};
        Check(PcbImportUi::MatchesResponse(chunk, {{"upload_id", "upload-a"}, {"path", "원문.gbr"}, {"received", 8}},
                                           "project-a"),
              "matching source progress rejected");
        Check(!PcbImportUi::MatchesResponse(chunk, {{"upload_id", "upload-a"}, {"path", "다른.gbr"}, {"received", 8}},
                                            "project-a"),
              "different source progress accepted");
        Check(!PcbImportUi::MatchesResponse(chunk, {{"upload_id", "upload-a"}, {"path", "원문.gbr"}, {"received", 4}},
                                            "project-a"),
              "non-progress receipt accepted");
        const Json quantity{{"value_si", 0.003},
                            {"dimension", "length"},
                            {"display_unit", "mm"},
                            {"status", "user_entered"},
                            {"source_refs", {"original-reference"}}};
        const Json source{{"id", "preserved"}, {"shape", {{"diameter", quantity}}}, {"origin", nullptr}};
        auto edited = source;
        PcbFeatureUi::ReplaceField(edited, Json::array({"shape", "diameter"}),
                                   {{"text", "4"}, {"unit", "mm"}, {"source_refs", {"original-reference"}}});
        Check(source.at("shape").at("diameter") == quantity && edited.at("origin").is_null() &&
                  edited.at("id") == "preserved",
              "field replacement changed source identity or unknown origin");
        bool rejected = false;
        const auto beforeInvalid = edited;
        try
        {
            PcbFeatureUi::ReplaceField(edited, Json::array({"shape", "absent"}), 1);
        }
        catch (const std::exception&)
        {
            rejected = true;
        }
        Check(rejected && edited == beforeInvalid, "unknown field silently materialized");
        const Json input{{"expected_revision", "rev-a"}};
        Json review{
            {"project_id", "project-a"}, {"source_revision_id", "rev-a"}, {"can_apply", true}, {"review_hash", "hash"}};
        Check(PcbFeatureUi::MatchesReview(review, input, "project-a"), "matching PCB review rejected");
        review["source_revision_id"] = "rev-b";
        Check(!PcbFeatureUi::MatchesReview(review, input, "project-a"), "stale PCB review accepted");
        Json scene{{"board", {{"kind", "polygon"}, {"outer", {{-5, -2}, {8, -2}, {8, 7}, {-5, 7}}}}},
                   {"layers", Json::array()},
                   {"shapes", Json::array()},
                   {"omissions", Json::array()},
                   {"pcb_features", Json::array({{{"id", "slot-id"},
                                                  {"kind", "hole"},
                                                  {"owner_footprint_id", "owner-id"},
                                                  {"source_label", "명시 슬롯"},
                                                  {"missing", false},
                                                  {"shape_mm",
                                                   {{"kind", "capsule"},
                                                    {"center_mm", {1, 2}},
                                                    {"finished_length_mm", 6},
                                                    {"finished_width_mm", 2},
                                                    {"rotation_deg", 90}}}}})}};
        const auto original = scene;
        const auto parsed = CanvasScene::Model::Parse(scene);
        const auto* slot = parsed.Find("slot-id");
        Check(slot && slot->selectionKind == "hole" && slot->ownerFootprint == "owner-id" && slot->layer.empty() &&
                  !slot->movable && slot->endpointMask == 0 && !slot->incomplete && scene == original,
              "mechanical display acquired conductor editing identity or mutated source");
        Check(std::abs(slot->start.x - 1) < 1e-12 && std::abs(slot->start.y) < 1e-12 &&
                  std::abs(slot->end.y - 4) < 1e-12 && slot->width == 2,
              "capsule display confused full finished length with centerline length");
        const auto bounds = parsed.VisibleBounds({});
        Check(bounds.left == -5 && bounds.right == 8 && bounds.bottom == -2 && bounds.top == 7,
              "polygon board fit ignored source outline");
        scene["pcb_features"][0]["shape_mm"]["finished_length_mm"] = 1;
        rejected = false;
        try
        {
            CanvasScene::Model::Parse(scene);
        }
        catch (const std::exception&)
        {
            rejected = true;
        }
        Check(rejected, "invalid mechanical slot was silently reinterpreted");
        scene = original;
        scene["pcb_features"][0]["missing"] = true;
        scene["pcb_features"][0]["shape_mm"]["center_mm"][0] = nullptr;
        const auto missingSource = scene;
        const auto missing = CanvasScene::Model::Parse(scene);
        Check(missing.shapes.empty() && missing.omissionCount == 1 && scene == missingSource,
              "unknown feature acquired invented coordinates or failed the whole scene");
        scene["board"]["outer"][0][0] = nullptr;
        Check(!CanvasScene::Model::Parse(scene).hasBoard, "unknown board vertex was invented");
        std::cout << "PCB feature presentation checks passed\n";
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
