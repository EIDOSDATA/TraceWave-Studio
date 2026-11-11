#include "canvas_scene.h"
#include "canvas_viewport.h"
#include "canvas_gesture.h"
#include "editor_presentation.h"

#include <cmath>
#include <iostream>
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

Json Fixture()
{
    return {{"board", {{"kind", "circle"}, {"center", {10.0, 20.0}}, {"radius", 5.0}}},
        {"layers", Json::array({{{"id", "top"}}, {{"id", "bottom"}}})},
        {"shapes", Json::array({
            {{"id", "line"}, {"kind", "line_path"}, {"layer_id", "top"}, {"width", 1.0},
                {"start", {7.0, 20.0}}, {"end", {13.0, 20.0}}, {"movable", true}},
            {{"id", "ground"}, {"kind", "planar_region"}, {"layer_id", "bottom"},
                {"outer", {{0.0, 0.0}, {4.0, 0.0}, {4.0, 4.0}, {0.0, 4.0}}},
                {"holes", Json::array({{{1.0, 1.0}, {3.0, 1.0}, {3.0, 3.0}, {1.0, 3.0}}})}},
            {{"id", "via"}, {"kind", "via"}, {"layer_id", "top"}, {"center", {10.0, 20.0}},
                {"span_layer_ids", {"top", "bottom"}}, {"finished_hole_diameter", nullptr},
                {"plating_thickness", nullptr}, {"tool_hole_diameter", nullptr}}
        })}, {"omissions", Json::array({{{"id", "unfinished"}}})}};
}

/** @brief 선택 순서/인덱스/구멍/비아/화면 범위를 같은 장면 모델로 확인한다. */
void SceneChecks()
{
    const auto scene = CanvasScene::Model::Parse(Fixture());
    Check(scene.shapes.front().id == "ground" && scene.shapes.back().id == "via", "scene drawing order");
    Check(scene.Find("line") != nullptr && scene.Find("line")->start.x == 7.0 && scene.Find("absent") == nullptr, "identity index");
    Check(scene.Find("via")->incomplete && scene.omissionCount == 1, "missing dimensions stay missing");
    Check(CanvasScene::DistanceTo(*scene.Find("ground"), {2.0, 2.0}) == 1.0, "polygon hole hit distance");
    Check(CanvasScene::DistanceTo(*scene.Find("ground"), {0.5, 0.5}) == 0.0, "polygon interior hit distance");
    Check(CanvasScene::Visible(*scene.Find("via"), {"top"}), "via visible on any span layer");
    Check(!CanvasScene::Visible(*scene.Find("via"), {"top", "bottom"}), "via hidden on all span layers");
    const auto bounds = scene.VisibleBounds({"bottom"});
    Check(bounds.left == 5.0 && bounds.right == 15.0 && bounds.bottom == 15.0 && bounds.top == 25.0, "circular board bounds");
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
        EditorPresentation::RequiresCurrentValue("center.0.mode") && EditorPresentation::RequiresCurrentValue("width.value"),
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
    Check(!available.enabled && available.visible && EditorPresentation::ValueLabel("value", fields) == "마지막 적용값 / 단위", "expression preserves readonly last value");
    fields.at("mode").value = "missing";
    Check(!EditorPresentation::Evaluate("value", fields, false).visible, "missing hides value");
    Check(!EditorPresentation::Evaluate("center.0.unit", fields, false).enabled && EditorPresentation::Evaluate("center.0.parameter_id", fields, false).visible, "reference mode locks unit");
    Check(!EditorPresentation::Evaluate("id", fields, false).visible && EditorPresentation::Evaluate("id", fields, true).visible, "advanced details visibility");
    const Json selection{{"kind", "geometry"}, {"id", "shape"}};
    Check(EditorPresentation::ResolveDiagnosticField("geometry.shape.outer[2][1]", selection, fields) == "outer", "coordinate diagnostic prefix");
    fields.at("center.0.value").enabled = false;
    Check(EditorPresentation::ResolveDiagnosticField("values.center[0]", selection, fields) == "center.0.parameter_id", "diagnostic selects enabled reference control");
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
        std::cout << "scene, viewport, gesture and editor presentation checks passed\n";
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
