/** @file @brief 실제 PCB 전용 폼의 미정/수량/검토/원자 이력과 재열기를 검사한다. */
#include "studio_internal.h"
#include "pcb_feature_dialog.h"
#include "pcb_feature_form.h"
#include "reviewed_request_store.h"
#include "setup_smoke_support.h"
#include "studio_notebook.h"
#include <wx/listctrl.h>
#include <wx/textctrl.h>
#include <fstream>
#include <set>

void StudioSmokeDriver::FeaturesSafetyChecks()
{
    struct Call
    {
        std::string method;
        Json input;
        std::function<void(const Json&)> success;
    };
    std::vector<Call> calls;
    DialogGateway gateway = [&calls](const std::string& method, const Json& input, bool,
                                     std::function<void(const Json&)> success, std::function<void(const Json&)>)
    {
        calls.push_back({method, input, std::move(success)});
    };
    auto recovery = std::make_shared<PcbFeatureRecovery>();
    auto dialog = std::make_unique<PcbFeatureDialog>(&m_frame, m_featuresFixture.at("context"), gateway, recovery);
    dialog->Preview();
    const auto late = calls.back().success;
    dialog->m_reason->SetValue(Display("새 입력으로 이전 후보 폐기"));
    late(m_featuresFixture.at("preview"));
    CanvasAssert(dialog->m_review.is_null(), "PCB 폼 변경 뒤 늦은 후보를 표시했습니다.");
    dialog->Preview();
    const auto destroyed = calls.back().success;
    dialog->m_closed = true;
    dialog.reset();
    destroyed(m_featuresFixture.at("preview"));
    m_setupChecks.push_back("features_late_preview_and_destroy_safe");
    const auto workspace = Utf8(m_frame.m_options.workspace) + "/features-safety";
    const auto project = m_featuresFixture.at("project_id").get<std::string>();
    const std::set<std::string> methods{"pcb.features.apply"};
    const Json pending{{"method", "pcb.features.apply"},
                       {"request_key", Uuid()},
                       {"request_key_epoch", Uuid()},
                       {"input", {{"expected_revision", m_featuresFixture.at("revision_id")}}}};
    ReviewedRequestStore::Write("pcb_features", workspace, project, methods, pending);
    recovery->pending = ReviewedRequestStore::Read("pcb_features", workspace + "/.", project, methods);
    CanvasAssert(recovery->pending == pending, "같은 작업공간의 원래 PCB 요청 키를 잃었습니다.");
    dialog = std::make_unique<PcbFeatureDialog>(&m_frame, m_featuresFixture.at("context"), gateway, recovery);
    CanvasAssert(!dialog->m_apply->IsEnabled() && !dialog->m_preview->IsEnabled() && dialog->m_recover->IsEnabled(),
                 "불명 PCB 적용에서 새 편집이 열렸습니다.");
    const auto count = calls.size();
    dialog->Apply();
    CanvasAssert(calls.size() == count, "미확정 변경을 새 키로 다시 보냈습니다.");
    dialog->Recover();
    CanvasAssert(calls.back().method == "pcb.features.receipt" &&
                     calls.back().input.at("request_key") == pending.at("request_key"),
                 "복구 조회가 원래 ledger 키를 사용하지 않습니다.");
    const auto unresolved = calls.back().success;
    unresolved({{"status", "unresolved"}, {"authoritative", true}, {"response", nullptr}});
    CanvasAssert(recovery->pending == pending && !dialog->m_apply->IsEnabled(), "영수증 부재를 미접수로 추정했습니다.");
    dialog->m_closed = true;
    dialog.reset();
    ReviewedRequestStore::Clear("pcb_features", workspace, project);
    m_setupChecks.push_back("features_uncertain_receipt_preserves_key");
}

void StudioSmokeDriver::FeaturesSmokeTick()
{
    if (auto* dialog = dynamic_cast<PcbFeatureDialog*>(m_frame.m_setupDialog))
    {
        if (dialog->m_pending || dialog->m_form->Pending())
        {
            return;
        }
        auto field = [dialog](const Json& path)
        {
            for (const auto& value : dialog->m_form->m_fields)
            {
                if (value->descriptor.at("path") == path)
                {
                    return value;
                }
            }
            throw std::runtime_error("PCB 시험 입력 필드를 찾지 못했습니다.");
        };
        auto literal = [&field](const Json& path, const std::string& text)
        {
            const auto value = field(path);
            SetupSmoke::Choose(value->mode, 0);
            value->text->SetValue(Display(text));
        };
        if (m_setupStage == 2)
        {
            const auto original = dialog->m_form->Record();
            m_featuresHoleId = original.at("id").get<std::string>();
            CanvasAssert(original.at("shape").at("diameter").at("value_si").is_null() &&
                             original.at("tool_diameter").at("value_si").is_null() &&
                             original.at("plating").at("state") == "unknown",
                         "신규 홀의 미정 치수/도금을 기본값으로 채웠습니다.");
            m_setupChecks.push_back("features_native_missing_values_preserved");
            field(Json::array({"name"}))->text->SetValue(Display("GUI 비도금 홀 / 출처 보존"));
            literal(Json::array({"shape", "center", 0}), "5");
            literal(Json::array({"shape", "center", 1}), "1");
            literal(Json::array({"shape", "diameter"}), "0");
            const auto plating = field(Json::array({"plating", "state"}));
            int choice = -1;
            for (std::size_t index = 0; index < plating->choices.size(); ++index)
            {
                if (plating->choices.at(index).at("value") == "unplated")
                {
                    choice = static_cast<int>(index);
                }
            }
            CanvasAssert(choice >= 0, "비도금 명시 선택이 없습니다.");
            SetupSmoke::Choose(plating->choice, choice);
            dialog->m_reason->SetValue(Display("실제 GUI의 입력 / RF 합격 아님"));
            m_setupStage = 3;
            SetupSmoke::Click(dialog->m_preview);
        }
        else if (m_setupStage == 3 && dialog->m_review.is_object())
        {
            CanvasAssert(!dialog->m_review.value("can_apply", true) && !dialog->m_apply->IsEnabled() &&
                             !dialog->m_issues->GetValue().empty(),
                         "0 지름의 확정 거절이나 한국어 진단이 없습니다.");
            literal(Json::array({"shape", "diameter"}), "1");
            m_setupStage = 4;
            SetupSmoke::Click(dialog->m_preview);
        }
        else if (m_setupStage == 4 && dialog->m_review.is_object())
        {
            CanvasAssert(dialog->m_review.value("can_apply", false) && dialog->m_changes->GetItemCount() == 1,
                         "잘못된 입력 수정 뒤 실제 PCB 후보로 회복하지 못했습니다.");
            CanvasAssert(dialog->m_canvas->IsShownOnScreen() &&
                             dialog->m_canvas->GetClientSize().y > dialog->FromDIP(100) &&
                             dialog->m_changes->GetClientSize().y > dialog->FromDIP(80),
                         "PCB 검토 형상/변경표가 접혀 보이지 않습니다.");
            m_setupChecks.push_back("features_invalid_input_recovery_and_visible_review");
            dialog->m_reason->SetValue(Display("변경 사유를 다시 검토함"));
            CanvasAssert(dialog->m_review.is_null() && !dialog->m_apply->IsEnabled(),
                         "변경 사유 수정 뒤 검토 hash가 살아 있습니다.");
            m_setupChecks.push_back("features_changed_input_invalidates_review");
            m_setupStage = 5;
            SetupSmoke::Click(dialog->m_preview);
        }
        else if (m_setupStage == 5 && dialog->m_review.is_object())
        {
            CanvasAssert(dialog->m_review.value("can_apply", false), "재검토가 실패했습니다.");
            m_setupStage = 6;
            SetupSmoke::Click(dialog->m_apply);
            CanvasAssert(!dialog->m_apply->IsEnabled(), "PCB 적용 중 버튼이 활성입니다.");
            dialog->Apply();
        }
        else if (m_setupStage == 7)
        {
            CanvasAssert(dialog->m_form->Record().at("tool_diameter").at("value_si").is_null(),
                         "저장한 공구 미정이 바뀌었습니다.");
            field(Json::array({"name"}))->text->SetValue(Display("단위 표시 검토용 임시 이름"));
            dialog->m_reason->SetValue(Display("저장하지 않는 이름 초안에서 표시 단위만 전환"));
            m_setupStage = 8;
            SetupSmoke::Click(dialog->m_preview);
        }
        else if (m_setupStage == 8 && dialog->m_review.is_object())
        {
            CanvasAssert(dialog->m_review.value("can_apply", false),
                         "기존 홀의 이름 초안 검토가 실패했습니다: " + dialog->m_review.dump());
            m_featuresFixture["unit_input"] = dialog->Input();
            m_featuresFixture["unit_review"] = dialog->m_review;
            const auto diameter = field(Json::array({"shape", "diameter"}));
            const int unit = diameter->unit->FindString("um");
            CanvasAssert(unit >= 0, "표시 단위 um이 없습니다.");
            m_setupStage = 9;
            SetupSmoke::Choose(diameter->unit, unit);
        }
        else if (m_setupStage == 9)
        {
            const auto diameter = field(Json::array({"shape", "diameter"}));
            CanvasAssert(diameter->text->GetValue() == "1000.0" || diameter->text->GetValue() == "1000",
                         "1 mm가 1000 um으로 표시되지 않습니다.");
            CanvasAssert(dialog->Input() == m_featuresFixture.at("unit_input") &&
                             dialog->m_review == m_featuresFixture.at("unit_review") &&
                             dialog->m_form->Record().at("shape").at("diameter").at("value_si") == 0.001,
                         "표시 단위만 바꾸며 원문 SI/검토를 변경했습니다.");
            m_setupChecks.push_back("features_unit_only_keeps_si_and_review");
            m_setupStage = 10;
            dialog->CloseDialog(true);
        }
        return;
    }
    if (m_frame.m_busy || m_frame.m_cadRestoring || m_frame.m_solverRestoring)
    {
        return;
    }
    if (m_setupStage == 1)
    {
        std::ifstream stream(std::filesystem::path(m_frame.m_options.workspace.ToStdWstring()) /
                                 "features-smoke-fixture.json",
                             std::ios::binary);
        stream >> m_featuresFixture;
        m_featuresOriginalRevision = m_frame.m_revision;
        CanvasAssert(m_frame.m_project == m_featuresFixture.at("project_id") &&
                         m_frame.m_revision == m_featuresFixture.at("revision_id"),
                     "PCB 시험 원본이 다릅니다.");
        FeaturesSafetyChecks();
        m_setupStage = 2;
        m_frame.CallAfter(
            [this]()
            {
                m_frame.OpenPcbFeatures("hole", nullptr);
            });
    }
    else if (m_setupStage == 6)
    {
        CanvasAssert(m_frame.m_revision != m_featuresOriginalRevision &&
                         m_frame.m_editor.at("history").at("undo_count") == 1 &&
                         m_frame.m_selection.at("kind") == "hole" && m_frame.m_selection.at("id") == m_featuresHoleId,
                     "한 명령의 PCB 적용/typed 선택이 유지되지 않습니다.");
        m_setupChecks.push_back("features_atomic_apply_and_typed_selection");
        m_setupStage = 7;
        m_frame.CallAfter(
            [this]()
            {
                m_frame.OpenPcbFeatures("hole", m_featuresHoleId);
            });
    }
    else if (m_setupStage == 10)
    {
        m_setupStage = 11;
        m_frame.History("project.undo",
                        [this]()
                        {
                            m_setupStage = 12;
                        });
    }
    else if (m_setupStage == 12)
    {
        CanvasAssert(m_frame.m_editor.at("history").at("undo_count") == 0 &&
                         m_frame.m_scene.value("pcb_features", Json::array()).empty(),
                     "처음 없던 PCB 필드를 실행 취소로 복원하지 못했습니다.");
        m_setupStage = 13;
        m_frame.History("project.redo",
                        [this]()
                        {
                            m_setupStage = 14;
                        });
    }
    else if (m_setupStage == 14)
    {
        CanvasAssert(m_frame.m_scene.at("pcb_features").size() == 1 &&
                         m_frame.m_editor.at("history").at("undo_count") == 1,
                     "다시 실행이 원래 홀/단일 이력을 복원하지 못했습니다.");
        m_setupChecks.push_back("features_first_undo_absence_and_exact_redo");
        m_setupStage = 15;
        m_frame.SaveProject();
    }
    else if (m_setupStage == 15 && m_frame.m_savedRevision == m_frame.m_revision)
    {
        m_setupExpectedRevision = m_frame.m_revision;
        m_setupStage = 16;
        m_frame.m_connected = false;
        m_frame.m_transportFailed = false;
        m_frame.m_restarting = true;
        m_frame.BeginShutdown();
    }
    else if (m_setupStage == 16 && m_serviceSessions >= 2)
    {
        CanvasAssert(m_frame.m_revision == m_setupExpectedRevision &&
                         m_frame.m_scene.at("pcb_features").at(0).at("id") == m_featuresHoleId,
                     "저장과 서비스 재시작 뒤 같은 PCB 홀을 재열지 못했습니다.");
        m_setupChecks.push_back("features_save_service_restart_same_source");
        FinishSmoke(true, "");
    }
}
