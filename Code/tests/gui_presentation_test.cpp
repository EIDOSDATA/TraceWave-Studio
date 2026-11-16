#include "canvas_scene.h"
#include "canvas_viewport.h"
#include "canvas_gesture.h"
#include "editor_presentation.h"
#include "frequency_display.h"
#include "sweep_model.h"

#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>

namespace
{
using Json = nlohmann::json;

/** @brief Release 빌드에서도 검증을 생략하지 않고 실패를 호출자에게 전한다. */
void Check(bool condition, const char* message)
{
    if (!condition)
    {
        throw std::runtime_error(message);
    }
}

/** @brief 결과 요약은 미정/미평가 이유를 보존하며 원문 객체와 긴 숫자를 숨긴다. */
void SweepResultChecks()
{
    const Json sample{
        {"real", 0.37931034482758624}, {"vswr", 2.2222222222222228}, {"imag", nullptr},
        {"status", "missing"},         {"magnitude_db", nullptr},    {"magnitude_db_state", "negative_infinity"}};
    const auto originalSample = sample;
    Check(SweepUi::SampleValue(sample, "real") == "0.37931034" && SweepUi::SampleValue(sample, "vswr") == "2.2222222" &&
              SweepUi::SampleValue(sample, "imag") == "미정" &&
              SweepUi::SampleValue(sample, "magnitude_db") == "-inf (크기 0)",
          "readable numeric values retain missing and infinite states");
    Check(SweepUi::SampleValue({{"real", nullptr}, {"status", "nonfinite"}}, "real") == "유한값 없음",
          "nonfinite samples differ from missing originals");
    Json result{{"descriptor",
                 {{"frequency_min_hz", 1e9},
                  {"frequency_max_hz", 2e9},
                  {"parameter_kind", "S"},
                  {"unit", "1"},
                  {"sample_count", 201},
                  {"port_ids", {"internal-port-identity"}},
                  {"port_names", {nullptr}},
                  {"reference_planes", {nullptr}},
                  {"z0_ohm", {{50.0, 0.0}}},
                  {"wave_definition", "unknown"},
                  {"port_modes", {"single_ended"}},
                  {"current_orientation", {"into_dut"}},
                  {"conditions", {{"manufacturing", nullptr}, {"measurement", nullptr}}},
                  {"source_refs", {"원본 조건 미정의 수식 시험"}}}},
                {"assessments",
                 {{{"status", "not_evaluated"},
                   {"criteria", Json::array()},
                   {"reason", "목표와 자료의 명시 포트/기준면 대응이 없습니다."},
                   {"evidence", {{"target_original", {{"name", "보존한 목표 이름"}}}}}}}}};
    const auto original = result;
    const auto text = SweepUi::ResultConditions(result);
    Check(text.find("1 ~ 2 GHz") != std::string::npos && text.find("제작 조건: 미정") != std::string::npos &&
              text.find("측정 조건: 미정") != std::string::npos && text.find("기준면: 미정") != std::string::npos &&
              text.find("자료 포트 1: 미정") != std::string::npos && text.find("기준 Z0: 50 ohm") != std::string::npos,
          "summary preserves independently unknown conditions and readable impedance");
    Check(text.find("보존한 목표 이름 / 미평가") != std::string::npos &&
              text.find("명시 포트/기준면 대응이 없습니다") != std::string::npos &&
              text.find("internal-port-identity") == std::string::npos && text.find("source_refs") == std::string::npos,
          "summary exposes the actual reason and name without internal JSON or IDs");
    Check(result == original && sample == originalSample, "formatting leaves source DTOs unchanged");
    result["assessments"][0]["evidence"] = {{"target_original_summary", {{"name", "큰 목표 원문"}}}};
    result["assessments"][0]["reason"] = nullptr;
    result["assessments"][0]["diagnostic"] = {{"message_ko", "원문 조건을 확인해야 합니다."}};
    Check(SweepUi::ResultConditions(result).find("큰 목표 원문 / 미평가") != std::string::npos &&
              SweepUi::ResultConditions(result).find("원문 조건을 확인해야 합니다.") != std::string::npos,
          "large original summaries and diagnostic reasons remain accessible");
}

/** @brief 같은 SI 표본의 표시 단위만 바꾸며 미정과 원문을 유지한다. */
void FrequencyChecks()
{
    using namespace StudioFrequency;
    Check(ForRange(0.0, 0.0).unit == "Hz" && ForRange(0.0, 999.0).unit == "Hz", "frequency zero and Hz range");
    Check(ForRange(0.0, 1e3).unit == "kHz" && ForRange(0.0, 1e6).unit == "MHz" && ForRange(0.0, 1e9).unit == "GHz",
          "frequency engineering unit boundaries");
    Check(ForRange(-2e9, -1e9).unit == "GHz", "frequency scale uses absolute extent");
    const Json page{
        {"samples", Json::array({{{"frequency_hz", 1e9}}, {{"frequency_hz", 1.5e9}}, {{"frequency_hz", 2e9}}})}};
    const Json original = page;
    const auto automatic = ForPage(page);
    const auto explicitMHz = ForPage(page, "MHz");
    Check(automatic.unit == "GHz" && automatic.divisor == 1e9 &&
              Value(page.at("samples").at(0).at("frequency_hz"), automatic) == "1",
          "one billion Hz is displayed as one GHz");
    Check(explicitMHz.unit == "MHz" && Value(1e9, explicitMHz) == "1000" && Value(1.5e9, automatic) == "1.5",
          "frequency unit changes only displayed magnitude");
    const Json partial{{"samples", Json::array({{{"frequency_hz", 0.5e9}}})}};
    const Json descriptor{{"frequency_min_hz", 0.5e9}, {"frequency_max_hz", 2e9}};
    Check(ForPage(partial).unit == "MHz" && ForDescriptor(descriptor).unit == "GHz" &&
              Value(partial.at("samples").at(0).at("frequency_hz"), ForDescriptor(descriptor)) == "0.5",
          "descriptor fixes frequency units across sample pages");
    Check(WithUnit(1e9) == "1 GHz" && Range(1e9, 2e9).find("GHz") != std::string::npos,
          "frequency summary includes engineering unit");
    Check(Value(1e9, automatic) != Value(1e9 + 1.0, automatic),
          "nearby representable samples remain distinct in frequency tables");
    Check(Value(std::numeric_limits<double>::denorm_min(), automatic) == "표시 범위 미만" &&
              Value(std::numeric_limits<double>::denorm_min(), ForRange(0.0, 0.0, "Hz")) != "0",
          "display scaling underflow is not reported as a zero frequency");
    Check(Value(nullptr, automatic) == "미정" &&
              Value(Json(std::numeric_limits<double>::infinity()), automatic) == "유한값 없음",
          "missing and nonfinite frequencies are not displayed as zero");
    Check(page == original, "frequency presentation leaves original SI samples unchanged");
    const Json assessed{
        {"frequency_min_hz", 0.5e9},
        {"frequency_max_hz", 2e9},
        {"evidence",
         {{"target_original", {{"band", {{"start", {{"value_si", 500.0}}}, {"end", {{"value_si", 1000.0}}}}}}}}}};
    const Json assessedOriginal = assessed;
    Check(ForAssessment(assessed, {{"frequency_min_hz", 1e6}, {"frequency_max_hz", 2e6}}).unit == "GHz",
          "whole assessed sample range precedes original and descriptor frequency units");
    const Json expressions{
        {"evidence",
         {{"target_original", {{"band", {{"start", {{"expression", "f0"}}}, {"end", {{"expression", "f1"}}}}}}}}}};
    const Json expressionOriginal = expressions;
    Check(ForAssessment(expressions, descriptor).unit == "GHz" && ForAssessment(Json(nullptr)).unit == "Hz",
          "unknown target expressions use descriptor range or a fixed Hz fallback without evaluation");
    Check(assessed == assessedOriginal && expressions == expressionOriginal,
          "assessment frequency presentation preserves original source and unknown expressions");
    const std::string artifactHash(64, 'a');
    const Json selection{{"entry", {{"dataset", {{"sha256", artifactHash}}}}}, {"descriptor", descriptor}};
    Json evidence = expressions;
    evidence["dataset_hash"] = "sha256:" + artifactHash;
    evidence["evidence"]["dataset"] = {{"sha256", artifactHash}};
    const Json evidenceOriginal = evidence;
    Check(AssessmentMatchesDataset(evidence, selection) &&
              ForAssessment(evidence, selection.at("descriptor")).unit == "GHz",
          "fallback matches sealed artifact hashes rather than canonical dataset hashes");
    evidence["evidence"]["dataset"]["sha256"] = std::string(64, 'b');
    evidence["dataset_hash"] = artifactHash;
    Check(!AssessmentMatchesDataset(evidence, selection),
          "a canonical hash cannot permit fallback to a different artifact");
    evidence["evidence"]["dataset"] = nullptr;
    Check(!AssessmentMatchesDataset(evidence, selection) && !AssessmentMatchesDataset(Json::object(), Json::object()) &&
              !AssessmentMatchesDataset(evidenceOriginal, Json{{"entry", {{"dataset", {{"sha256", 1}}}}}}),
          "missing malformed or empty artifact evidence never matches a selected dataset");
    Check(evidenceOriginal.at("evidence").at("target_original") ==
              expressionOriginal.at("evidence").at("target_original"),
          "dataset identity checking preserves unknown target expressions");
}

Json Fixture()
{
    return {{"board", {{"kind", "circle"}, {"center", {10.0, 20.0}}, {"radius", 5.0}}},
            {"layers", Json::array({{{"id", "top"}}, {{"id", "bottom"}}})},
            {"shapes", Json::array({{{"id", "line"},
                                     {"kind", "line_path"},
                                     {"layer_id", "top"},
                                     {"width", 1.0},
                                     {"start", {7.0, 20.0}},
                                     {"end", {13.0, 20.0}},
                                     {"movable", true}},
                                    {{"id", "ground"},
                                     {"kind", "planar_region"},
                                     {"layer_id", "bottom"},
                                     {"outer", {{0.0, 0.0}, {4.0, 0.0}, {4.0, 4.0}, {0.0, 4.0}}},
                                     {"holes", Json::array({{{1.0, 1.0}, {3.0, 1.0}, {3.0, 3.0}, {1.0, 3.0}}})}},
                                    {{"id", "via"},
                                     {"kind", "via"},
                                     {"layer_id", "top"},
                                     {"center", {10.0, 20.0}},
                                     {"span_layer_ids", {"top", "bottom"}},
                                     {"finished_hole_diameter", nullptr},
                                     {"plating_thickness", nullptr},
                                     {"tool_hole_diameter", nullptr}}})},
            {"omissions", Json::array({{{"id", "unfinished"}}})}};
}

/** @brief 선택 순서/인덱스/구멍/비아/화면 범위를 같은 장면 모델로 확인한다. */
void SceneChecks()
{
    const auto scene = CanvasScene::Model::Parse(Fixture());
    Check(scene.shapes.front().id == "ground" && scene.shapes.back().id == "via", "scene drawing order");
    Check(scene.Find("line") != nullptr && scene.Find("line")->start.x == 7.0 && scene.Find("absent") == nullptr,
          "identity index");
    Check(scene.Find("via")->incomplete && scene.omissionCount == 1, "missing dimensions stay missing");
    Check(CanvasScene::DistanceTo(*scene.Find("ground"), {2.0, 2.0}) == 1.0, "polygon hole hit distance");
    Check(CanvasScene::DistanceTo(*scene.Find("ground"), {0.5, 0.5}) == 0.0, "polygon interior hit distance");
    Check(CanvasScene::Visible(*scene.Find("via"), {"top"}), "via visible on any span layer");
    Check(!CanvasScene::Visible(*scene.Find("via"), {"top", "bottom"}), "via hidden on all span layers");
    const auto bounds = scene.VisibleBounds({"bottom"});
    Check(bounds.left == 5.0 && bounds.right == 15.0 && bounds.bottom == 15.0 && bounds.top == 25.0,
          "circular board bounds");
    auto invalid = Fixture();
    invalid["shapes"][1]["id"] = "line";
    bool rejected = false;
    try
    {
        CanvasScene::Model::Parse(invalid);
    }
    catch (const std::runtime_error&)
    {
        rejected = true;
    }
    Check(rejected && scene.Find("ground") != nullptr, "invalid scene cannot replace previous model");
    auto extreme = Fixture();
    extreme["shapes"][0]["start"][0] = 1e10;
    const auto omitted = CanvasScene::Model::Parse(extreme);
    Check(omitted.rangeOmissionCount == 1 && omitted.Find("line") == nullptr, "display range omission");
    const CanvasViewport viewport{800, 600, {10.0, 20.0}, 8.0};
    const auto pixel = viewport.Project({11.0, 22.0});
    const auto world = viewport.Unproject(pixel);
    Check(pixel.x == 408.0 && pixel.y == 284.0 && world.x == 11.0 && world.y == 22.0, "viewport roundtrip Y-up");
    Check(viewport.Renderable(*scene.Find("line")), "normal shape renderable");
    CanvasViewport extremeView{800, 600, {0.0, 0.0}, 1e6};
    Check(!extremeView.Renderable(*scene.Find("ground")), "polygon native limit shared with selection");
}

/** @brief 동시에 둘 이상의 capture 제스처가 활성화되지 않는 전이를 확인한다. */
void GestureChecks()
{
    CanvasGestureState state;
    Check(!state.Active() && !state.BeginDrag(), "idle cannot drag");
    state.BeginSelection();
    Check(state.Selecting() && state.BeginDrag() && state.Dragging(), "selection promotes to drag");
    state.BeginPan();
    Check(state.Panning() && !state.Selecting() && !state.BeginDrag(), "pan excludes selection/drag");
    state.Reset();
    state.BeginDrawing();
    Check(state.DrawingClick() && !state.Panning() && !state.BeginDrag(), "drawing excludes pan/drag");
    state.Reset();
    Check(!state.Active(), "capture loss/cancel clears state");
}

/** @brief 화면 위젯 없이 입력 모드와 진단/단위 안내의 기존 의미를 검증한다. */
void EditorChecks()
{
    Check(!EditorPresentation::RequiresCurrentValue("bindings") && !EditorPresentation::RequiresCurrentValue("outer") &&
              EditorPresentation::RequiresCurrentValue("center.0.mode") &&
              EditorPresentation::RequiresCurrentValue("width.value"),
          "presentation does not commit unrelated grid drafts");
    std::map<std::string, Json> descriptors;
    EditorPresentation::Fields fields;
    auto add = [&](const std::string& key, Json value, const std::string& label = "필드")
    {
        descriptors[key] = {{"value", value}, {"label", label}, {"editor", "text"}};
        fields.emplace(key, EditorPresentation::Field{&descriptors.at(key), value, true});
    };
    add("mode", "value");
    add("value", "2", "길이");
    add("unit", "mm", "단위");
    add("expression", "");
    add("bindings", Json::object());
    add("outer", Json::array());
    descriptors["outer"]["editor"] = "coordinate_table";
    add("center.0.mode", "parameter");
    add("center.0.value", "4");
    add("center.0.unit", "mm");
    add("center.0.parameter_id", "uuid");
    add("id", "identity");
    descriptors["id"]["advanced"] = true;
    auto available = EditorPresentation::Evaluate("expression", fields, false);
    Check(!available.enabled && !available.visible, "value mode hides expression");
    fields.at("mode").value = "expression";
    available = EditorPresentation::Evaluate("value", fields, false);
    Check(!available.enabled && available.visible &&
              EditorPresentation::ValueLabel("value", fields) == "마지막 적용값 / 단위",
          "expression preserves readonly last value");
    fields.at("mode").value = "missing";
    Check(!EditorPresentation::Evaluate("value", fields, false).visible, "missing hides value");
    Check(!EditorPresentation::Evaluate("center.0.unit", fields, false).enabled &&
              EditorPresentation::Evaluate("center.0.parameter_id", fields, false).visible,
          "reference mode locks unit");
    Check(!EditorPresentation::Evaluate("id", fields, false).visible &&
              EditorPresentation::Evaluate("id", fields, true).visible,
          "advanced details visibility");
    const Json selection{{"kind", "geometry"}, {"id", "shape"}};
    Check(EditorPresentation::ResolveDiagnosticField("geometry.shape.outer[2][1]", selection, fields) == "outer",
          "coordinate diagnostic prefix");
    fields.at("center.0.value").enabled = false;
    Check(EditorPresentation::ResolveDiagnosticField("values.center[0]", selection, fields) == "center.0.parameter_id",
          "diagnostic selects enabled reference control");
    fields.at("mode").value = "value";
    fields.at("unit").value = "m";
    Check(!EditorPresentation::InputNotice(fields).empty(), "unit-only change notice");
    fields.at("value").value = "5";
    Check(EditorPresentation::InputNotice(fields).empty(), "value and unit changed suppress conversion notice");
}
}

int main()
{
    try
    {
        SceneChecks();
        GestureChecks();
        EditorChecks();
        FrequencyChecks();
        SweepResultChecks();
        std::cout << "scene, viewport, gesture, editor and frequency presentation checks passed\n";
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
