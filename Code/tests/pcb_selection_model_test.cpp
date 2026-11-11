/** @file @brief 위젯 없이 PCB 선택의 출처 ID, 미정값, 입력 변경과 권위 미리보기 경계를 검증한다. */
#include "../ui/wxwidgets/pcb_selection_model.h"
#include <cstdlib>
#include <iostream>
#include <limits>

namespace
{
using Json = Studio::Json;
using Model = Studio::PcbSelectionModel;
const std::string Project = "10000000-0000-0000-0000-000000000001";
const std::string Revision = "10000000-0000-0000-0000-000000000002";
const std::string Selection = "10000000-0000-0000-0000-000000000003";
const std::string Command = "10000000-0000-0000-0000-000000000004";
const std::string Layer = "10000000-0000-0000-0000-000000000005";
const std::string Material = "10000000-0000-0000-0000-000000000006";
const std::string Catalog = "catalog:" + std::string(64, 'a');
const std::string Hash = std::string(64, 'b');

/** @brief Release 빌드에서도 계약 위반의 위치를 종료 코드로 알린다. */
void Check(bool condition, const char* message)
{
    if (!condition)
    {
        std::cerr << "PCB selection model: " << message << '\n';
        std::exit(1);
    }
}

/** @brief 잘못된 입력은 예외로 거부되어야 한다. */
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
    Check(false, "invalid operation was accepted");
}

Json Context()
{
    return Json{{"profile", "rfad.pcb-selection/0.1"},
                {"project_id", Project},
                {"revision_id", Revision},
                {"materials", Json::array({Json{{"id", Material}, {"name", "시험 재료"}}})},
                {"ports", Json::array()},
                {"layers", Json::array({Json{{"id", Layer},
                                             {"name", "시험 코어"},
                                             {"role", "dielectric"},
                                             {"order", 0},
                                             {"thickness_mm", 1.25},
                                             {"z_min_mm", 0.0},
                                             {"material_id", Material},
                                             {"parameter_bound", true}}})}};
}

Json Source(const std::string& catalog = Catalog)
{
    return Json{{"catalog_id", catalog}, {"entity", "native_templates"}, {"id", "4200000000000000001"}};
}

Json Draft(const Json& source)
{
    return Json{{"schema", "rfad.pcb-stackup-draft/0.1"},
                {"catalog_id", source.at("catalog_id")},
                {"template_id", source.at("id")},
                {"record_id", nullptr},
                {"layer_order", "bottom_to_top"},
                {"layers", Json::array({Json{{"key", "core"},
                                             {"name", "원문 코어"},
                                             {"role", "dielectric"},
                                             {"thickness_mm", 0.127},
                                             {"status", "source_value"},
                                             {"thickness_basis", "published_mm"}},
                                        Json{{"key", "top"},
                                             {"name", "미정 완성 동박"},
                                             {"role", "conductor"},
                                             {"thickness_mm", nullptr},
                                             {"status", "unresolved"},
                                             {"thickness_basis", "finished_unknown"}}})}};
}

Json Preview(bool canApply = true)
{
    return Json{{"profile", "rfad.pcb-selection/0.1"},
                {"project_id", Project},
                {"expected_revision", Revision},
                {"selection_id", Selection},
                {"preview_hash", Hash},
                {"can_apply", canApply},
                {"candidate_layers", Context().at("layers")}};
}

void Approve(Model& model, bool canApply = true)
{
    const auto token = model.BeginRequest("preview");
    Check(model.AcceptPreview(token, Preview(canApply)), "current preview rejected");
}

/** @brief 기본값은 기존 적층 유지이며 새 수치나 물성을 만들지 않는다. */
void ExistingContext()
{
    Model model(Context(), Selection);
    Check(!model.Dirty() && !model.CanApply(), "initial state");
    Check(model.Specification() == Json{{"source", nullptr}, {"materials", Json::array()}},
          "existing stackup specification");
    const auto rows = model.LayerRows();
    Check(rows.at(0).at("key") == Layer && rows.at(0).at("existing_layer_id") == Layer, "existing UUID reuse");
    Check(rows.at(0).at("parameter_bound") == true, "parameter binding display");
    Check(rows.at(0).at("z_min_mm") == 0.0 && !rows.at(0).at("z_min_mm").is_null(), "zero is not missing");
    Check(rows.at(0).at("thickness_mm") == 1.25 && model.CandidateLayers().empty(), "server mm is unchanged");
    Reject(
        [&model]()
        {
            model.ApplyInput(Command);
        });
}

/** @brief 순서가 뒤집힌 검색과 초안 응답이 현재 입력을 덮어쓰지 않는다. */
void StaleResponses()
{
    Model model(Context(), Selection);
    const auto first = model.BeginRequest("search");
    const auto latest = model.BeginRequest("search");
    const Json result{{"items", Json::array({Json{{"template_id", "4200000000000000001"}}})}};
    Check(!model.AcceptSearch(first, result), "late search accepted");
    Check(model.AcceptSearch(latest, result), "latest search rejected");
    Check(model.SearchResult().at("items").at(0).at("template_id").is_string(), "large identity lost string type");
    const auto draftToken = model.BeginRequest("draft");
    model.Invalidate();
    Check(!model.SelectSource(draftToken, Source(), Draft(Source())), "late draft accepted");
    Check(!model.Fail(draftToken, Json{{"code", "old_failure"}}) && model.Error().is_null(), "late failure accepted");
    const auto token = model.BeginRequest("preview");
    model.Reset(Context(), Selection);
    const auto next = model.BeginRequest("preview");
    Check(next != token && !model.AcceptPreview(token, Preview()), "reset reused pending token");
    Check(model.AcceptPreview(next, Preview()), "new generation preview rejected");
    model.BeginRequest("search");
    Check(!model.CanApply() && model.Preview().is_null(), "search change retained apply approval");
}

/** @brief 초안은 원문 mm와 미정값을 유지하고 수정과 대응만 사양에 담는다. */
void DraftAndMappings()
{
    Model model(Context(), Selection);
    const auto source = Source();
    auto token = model.BeginRequest("draft");
    auto wrong = Draft(source);
    wrong["template_id"] = "different";
    Reject(
        [&]()
        {
            model.SelectSource(token, source, wrong);
        });
    Check(model.SelectSource(token, source, Draft(source)), "source draft rejected");
    auto rows = model.LayerRows();
    Check(rows.at(0).at("thickness_mm") == 0.127 && rows.at(1).at("thickness_mm").is_null(), "draft thickness altered");
    Check(rows.at(0).at("z_min_mm").is_null(), "UI invented cumulative z");
    auto spec = model.Specification();
    spec["layer_ids"] = Json{{"core", Layer}};
    spec["material_assignments"] = Json{{"core", Material}, {"top", nullptr}};
    spec["thickness_overrides"] =
        Json{{"top", Json{{"value_mm", 0.035}, {"reason", "사용자가 지정한 시험 완성 두께"}}}};
    model.SetSpecification(spec);
    rows = model.LayerRows();
    Check(rows.at(0).at("existing_layer_id") == Layer && rows.at(0).at("material_id") == Material,
          "explicit mappings lost");
    Check(rows.at(1).at("thickness_mm") == 0.035 && rows.at(1).at("source_thickness_mm").is_null(),
          "override lost original missing value");
    const auto request = model.PreviewInput();
    Check(request.at("specification").at("thickness_overrides").at("top").at("value_mm") == 0.035,
          "UI converted mm to SI");
    Check(request.at("expected_revision") == Revision && request.at("selection_id") == Selection,
          "fixed request identities changed");
    Approve(model);
    spec["thickness_overrides"]["top"]["value_mm"] = 0;
    Reject(
        [&]()
        {
            model.SetSpecification(spec);
        });
    Check(!model.CanApply(), "invalid input left old preview applicable");
    spec["thickness_overrides"]["top"]["value_mm"] = nullptr;
    model.SetSpecification(spec);
    Check(model.LayerRows().at(1).at("thickness_mm").is_null(), "explicit missing override became zero");
}

/** @brief 권위 preview만 적용하며 변경 및 실패 뒤에는 재승인이 필요하다. */
void PreviewAndApply()
{
    Model model(Context(), Selection);
    Approve(model, false);
    Check(!model.CanApply(), "blocked preview was applicable");
    auto token = model.BeginRequest("preview");
    auto wrong = Preview();
    wrong["expected_revision"] = Command;
    Reject(
        [&]()
        {
            model.AcceptPreview(token, wrong);
        });
    Check(!model.CanApply(), "wrong revision got authority");
    Check(model.AcceptPreview(token, Preview()), "matching preview rejected");
    auto unchanged = model.Specification();
    model.SetSpecification(unchanged);
    Check(model.CanApply(), "unchanged valid specification lost approval");
    unchanged["notes"] = Json::array({"추가 검토"});
    model.SetSpecification(unchanged);
    Check(!model.CanApply() && model.CandidateLayers().empty(), "edit retained old cross section authority");
    Approve(model);
    const auto input = model.ApplyInput(Command);
    Check(input.at("preview_hash") == Hash && input.at("specification") == unchanged,
          "apply input differs from approved input");
    token = model.BeginRequest("apply");
    Check(!model.CanApply(), "duplicate apply possible");
    Reject(
        [&]()
        {
            model.Invalidate();
        });
    Reject(
        [&]()
        {
            model.BeginRequest("apply");
        });
    Check(
        model.AcceptApply(token, Json{{"selection_id", Selection}, {"preview_hash", Hash}, {"new_revision", Command}}),
        "apply receipt rejected");
    Check(model.CurrentStage() == Model::Stage::Applied && !model.Dirty(), "apply completion state");
    Check(model.AppliedResult().at("new_revision") == Command, "apply receipt lost");
    model.Reset(Context(), Selection);
    Approve(model);
    token = model.BeginRequest("apply");
    Check(model.Fail(token, Json{{"code", "E_TIMEOUT"}}), "apply failure ignored");
    Check(model.CurrentStage() == Model::Stage::Stale && !model.CanApply(),
          "uncertain apply result silently retryable");
    Reject(
        [&]()
        {
            model.BeginRequest("preview");
        });
}

/** @brief 직접 층 입력도 사용자 이유와 명시 값을 보존하고 비유한값을 거부한다. */
void ManualAndDefensiveInputs()
{
    Model model(Context(), Selection);
    auto spec = model.Specification();
    spec["layers"] = Json::array(
        {Json{{"key", "manual"}, {"name", "직접 정의"}, {"role", "dielectric"}, {"thickness_mm", nullptr}}});
    spec["layout_reason"] = "제작사 층 구성이 아닌 사용자 정의 시험 모델";
    model.SetSpecification(spec);
    Check(model.LayerRows().at(0).at("thickness_mm").is_null(), "manual missing thickness changed");
    spec["layers"][0]["thickness_mm"] = std::numeric_limits<double>::infinity();
    Reject(
        [&]()
        {
            model.SetSpecification(spec);
        });
    auto source = Source();
    source["id"] = 4200000000000000001ULL;
    const auto token = model.BeginRequest("draft");
    Reject(
        [&]()
        {
            model.SelectSource(token, source, Draft(Source()));
        });
    Reject(
        [&]()
        {
            model.BeginRequest("arbitrary_rpc");
        });
    model.MarkStale();
    Check(!model.CanApply() && !model.IsCurrent(token), "stale context retained token");
}
}

int main()
{
    ExistingContext();
    StaleResponses();
    DraftAndMappings();
    PreviewAndApply();
    ManualAndDefensiveInputs();
    std::cout << "PCB selection model tests passed.\n";
    return 0;
}
