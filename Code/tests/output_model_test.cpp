/** @file @brief 종이 좌표와 검토 정체성의 수용 경계를 실제 원문 보존과 함께 검사한다. */
#include "drawing_sheet_model.h"
#include "output_model.h"
#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>

namespace
{
void Check(bool condition, const char* message)
{
    if (!condition)
    {
        throw std::runtime_error(message);
    }
}

void Rejected(const Json& pages)
{
    bool rejected = false;
    try
    {
        DrawingSheet::ValidatePages(pages);
    }
    catch (const std::exception&)
    {
        rejected = true;
    }
    Check(rejected, "malformed paper geometry was accepted");
}
}

int main()
{
    try
    {
        const Json omission{{"reason", "sidecar_only"}, {"reason_label", "핀 의미는 보존 원문에만 기록"}};
        const auto omissionBefore = omission;
        Check(OutputUi::Issues(Json::array({omission})) == "핀 의미는 보존 원문에만 기록" && omission == omissionBefore,
              "display reason did not preserve the raw omission code");
        Check(OutputUi::Issues(Json::array({{{"reason", "original reason"}}})) == "original reason",
              "historical omission reason was changed");
        const Json camVerification{{"format", "verification"},
                                   {"result", {{"profile", "rfad.exchange.cam/0.1"}}},
                                   {"report",
                                    {{"status", "passed_profile"},
                                     {"reader", {{"reader", "bounded Gerber/XNC/Job parsers"}, {"files", 6}}},
                                     {"kernel_independent", false}}}};
        const auto preservedCam = camVerification;
        const auto displayedCam = OutputUi::RecordForDisplay(camVerification);
        Check(displayedCam.at("format") == "gerber_job" &&
                  OutputUi::Purpose(displayedCam) == "Gerber / 드릴 / Job 패키지" &&
                  OutputUi::Reader(displayedCam.at("report").at("reader")) == "bounded Gerber/XNC/Job parsers" &&
                  displayedCam.at("report").at("kernel_independent") == false && camVerification == preservedCam,
              "CAM verification displayed a drawing or lost the actual reader / source");
        for (const auto& item : Json::array({{"rfad.exchange.kicad-board/0.1", "kicad_pcb"},
                                             {"rfad.exchange.kicad-footprint/0.1", "kicad_mod"},
                                             {"rfad.step.mechanical/0.1", "step"}}))
        {
            auto record = camVerification;
            record["result"]["profile"] = item.at(0);
            Check(OutputUi::RecordForDisplay(record).at("format") == item.at(1),
                  "known verification profile was replaced with operation name");
        }
        auto drawingVerification = camVerification;
        drawingVerification["result"] = {{"profile", "rfad.exchange.drawing/0.1"},
                                         {"format", "svg"},
                                         {"options", {{"mode", "fabrication_geometry"}}}};
        Check(OutputUi::RecordForDisplay(drawingVerification).at("format") == "svg" &&
                  OutputUi::Purpose(OutputUi::RecordForDisplay(drawingVerification)) == "1:1 형상",
              "verification overwrote recorded drawing format or fabrication purpose");
        Check(OutputUi::Purpose({{"profile", "future"}, {"format", "verification"}}) != "기술 도면" &&
                  OutputUi::Reader({{"formats", Json::array({{{"reader", "existing PDF parser"}}})}}) ==
                      "existing PDF parser",
              "unknown profile was inferred as a drawing or historical reader was lost");
        const Json loop =
            Json::array({{{"kind", "arc"}, {"center", {0, 0}}, {"radius", 12}, {"start_deg", 0}, {"sweep_deg", 360}}});
        Json hole = loop;
        hole[0]["radius"] = 2;
        Json pages = Json::array({{{"width_mm", 24},
                                   {"height_mm", 24},
                                   {"view_box_mm", {-12, -12, 24, 24}},
                                   {"primitives", Json::array({{{"kind", "path"},
                                                                {"loops", Json::array({loop, hole})},
                                                                {"fill", {200, 100, 0}},
                                                                {"stroke", nullptr},
                                                                {"stroke_width_mm", 0},
                                                                {"clip_rect_mm", {-10, -10, 20, 20}},
                                                                {"source_id", "preserved"}}})}}});
        const auto original = pages;
        DrawingSheet::ValidatePages(pages);
        Check(pages == original && pages[0]["primitives"][0]["loops"].size() == 2, "origin or analytic hole changed");
        auto bad = pages;
        bad[0]["primitives"][0]["clip_rect_mm"][2] = 0;
        Rejected(bad);
        bad = pages;
        bad[0]["view_box_mm"][2] = 25;
        Rejected(bad);
        bad = pages;
        bad[0]["primitives"][0]["loops"][0][0]["radius"] = std::numeric_limits<double>::infinity();
        Rejected(bad);
        bad = pages;
        bad[0]["primitives"][0]["kind"] = "unknown";
        Rejected(bad);
        const auto landscape = DrawingSheet::Fit(297, 210, 800, 600, 16);
        Check(std::abs(landscape.width / landscape.height - 297.0 / 210.0) < 1e-12 && landscape.x >= 16 - 1e-9 &&
                  landscape.y >= 16 - 1e-9 && landscape.width <= 768 + 1e-9 && landscape.height <= 568 + 1e-9,
              "paper fit changed aspect ratio or clipped page");
        Check(DrawingSheet::Fit(297, 210, 30, 30, 16).scale == 0, "small canvas produced invalid scale");
        Check(DrawingSheet::Fit(std::numeric_limits<double>::denorm_min(), std::numeric_limits<double>::denorm_min(),
                                800, 600, 16)
                      .scale == 0,
              "overflowing fit was accepted");
        Json input{{"profile", "rfad.exchange.drawing/0.1"},
                   {"format", "svg"},
                   {"snapshot", {{"snapshot_id", "snapshot-a"}, {"content_hash", "fixed-hash"}}},
                   {"options", {{"scale", 1}, {"views", Json::array({{{"kind", "outline"}}})}}}};
        Json preview = input;
        preview["can_build"] = true;
        preview["review_hash"] = "reviewed";
        Check(OutputUi::MatchesPreview(preview, input), "matching review rejected");
        for (const auto& key : {"profile", "format"})
        {
            auto changed = input;
            changed[key] = "different";
            Check(!OutputUi::MatchesPreview(preview, changed), "different output contract accepted");
        }
        auto changed = input;
        changed["snapshot"]["content_hash"] = "different";
        Check(!OutputUi::MatchesPreview(preview, changed), "different fixed source accepted");
        changed = input;
        changed["options"]["scale"] = 2;
        Check(!OutputUi::MatchesPreview(preview, changed), "changed scale retained review");
        preview["can_build"] = false;
        Check(!OutputUi::MatchesPreview(preview, input), "unavailable runtime enabled generation");
        const Json conditions{{"manufacturing", nullptr}, {"measurement", nullptr}};
        const Json namedOmissions = Json::array({{{"id", "preserved-geometry-id"},
                                                  {"label", "제외된 원호"},
                                                  {"name", "제외된 원호"},
                                                  {"name_state", "persistent"},
                                                  {"reason", "출력에서 제외한 형상"}},
                                                 {{"id", "preserved-part-id"},
                                                  {"label", "외부 고체 1"},
                                                  {"name", nullptr},
                                                  {"name_state", "temporary"},
                                                  {"reason", "치수 미정"}}});
        const Json savedRecord{{"result",
                                {{"profile", "rfad.exchange.drawing/0.1"},
                                 {"manufacturing", nullptr},
                                 {"measurement", nullptr},
                                 {"omissions", Json::array({{{"reason", "이전 원문"}}})}}},
                               {"format", "pdf"},
                               {"manifest", {{"sha256", "preserved-manifest"}}},
                               {"report", {{"status", "passed_profile"}}},
                               {"omissions", namedOmissions}};
        const auto preservedRecord = savedRecord;
        const auto displayRecord = OutputUi::RecordForDisplay(savedRecord);
        Check(displayRecord.at("omissions") == namedOmissions && displayRecord.at("format") == "pdf" &&
                  displayRecord.at("manifest") == savedRecord.at("manifest") &&
                  displayRecord.at("report") == savedRecord.at("report") &&
                  displayRecord.at("manufacturing").is_null() && displayRecord.at("measurement").is_null() &&
                  savedRecord == preservedRecord,
              "record projection lost omission names, unknowns or changed stored source");
        const auto omissionSummary = OutputUi::Conditions(displayRecord);
        Check(omissionSummary.find("제외된 원호: 출력에서 제외한 형상") != std::string::npos &&
                  omissionSummary.find("외부 고체 1: 치수 미정") != std::string::npos,
              "condition summary lost preserved omission labels or reasons");
        auto legacyRecord = savedRecord;
        legacyRecord.erase("omissions");
        Check(OutputUi::RecordForDisplay(legacyRecord).at("omissions") == savedRecord.at("result").at("omissions"),
              "legacy result omissions were silently discarded");
        legacyRecord["omissions"] = Json::array();
        Check(OutputUi::RecordForDisplay(legacyRecord).at("omissions").empty(),
              "explicit empty omission list was replaced by old source");
        Check(OutputUi::RecordForDisplay(preview) == preview && OutputUi::RecordForDisplay(nullptr).is_null(),
              "preview or absent record was converted into a stored result");
        OutputUi::DeferredDisplay queue;
        const Json first{{"artifact", {{"sha256", "first"}}}, {"snapshot", {{"content_hash", "source-one"}}}};
        const Json latest{{"artifact", {{"sha256", "latest"}}}, {"snapshot", {{"content_hash", "source-two"}}}};
        queue.Replace(first);
        Check(queue.TakeWhenIdle(true).is_null() && !queue.Empty(), "busy display discarded a pending selection");
        queue.Replace(latest);
        Check(queue.TakeWhenIdle(true).is_null() && queue.TakeWhenIdle(false) == latest && queue.Empty(),
              "previous mesh completion replaced the latest pinned selection");
        queue.Replace(first);
        queue.Clear();
        Check(queue.TakeWhenIdle(false).is_null(), "cleared project restarted an old display load");
        const auto text = OutputUi::Conditions(conditions);
        Check(text.find("제작 조건: 미정") != std::string::npos && text.find("측정 조건: 미정") != std::string::npos,
              "unknown conditions were represented as established");
        std::cout << "output model checks passed\n";
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
