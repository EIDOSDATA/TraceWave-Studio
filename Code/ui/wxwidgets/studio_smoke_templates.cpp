/** @file @brief 원호/IFA 카드의 미리보기와 명시 입력/최신 적용을 검사한다. */
#include "studio_internal.h"
#include "template_dialog.h"
#include "setup_smoke_support.h"

namespace
{
/** @brief 시험 전용 치수이며 제품 기본값이나 검증 안테나 설계가 아니다. */
Json CardInputs(bool ifa)
{
    if (ifa)
    {
        return Json{{"ground_left", "15"},     {"ground_bottom", "15"},    {"ground_width", "30"},
                    {"ground_height", "20"},   {"radiator_start_x", "18"}, {"radiator_y", "45"},
                    {"radiator_length", "24"}, {"trace_width", "1"},       {"short_x", "20"},
                    {"short_start_y", "32"},   {"feed_x", "25"},           {"feed_start_y", "38"},
                    {"pad_width", "2"},        {"pad_height", "2"}};
    }
    return Json{{"center_x", "40"},  {"center_y", "40"},     {"radius", "15"},
                {"width", "1"},      {"feed_start_x", "30"}, {"feed_start_y", "30"},
                {"feed_width", "1"}, {"start_angle", "30"},  {"sweep_angle", "120"}};
}
}

void StudioSmokeDriver::SetupTemplateSmoke(TemplateDialog& dialog)
{
    if (dialog.m_pending)
    {
        return;
    }
    if (m_setupStage == 20 || m_setupStage == 25)
    {
        const bool ifa = m_setupStage == 25;
        const std::string id = ifa ? "builtin.explicit_planar_ifa" : "builtin.explicit_arc";
        int index = 0;
        for (const auto& card : dialog.m_context.at("cards"))
        {
            if (card.at("template_id") == id)
            {
                break;
            }
            ++index;
        }
        if (!ifa && !m_setupLargeChecked)
        {
            using Callback = std::function<void(const Json&)>;
            Callback success;
            Callback failure;
            DialogGateway gateway =
                [&success, &failure](const std::string&, const Json&, bool, Callback accepted, Callback rejected)
            {
                success = std::move(accepted);
                failure = std::move(rejected);
            };
            auto draft = std::make_unique<TemplateDialog>(&m_frame, dialog.m_context, gateway);
            SetupSmoke::Choose(draft->m_cards, index);
            draft->m_inputs->SetFieldValue("radius", "15");
            SetupSmoke::Choose(draft->m_cards, index == 0 ? 1 : 0);
            draft->m_inputs->SetFieldValue("ground_left", "1");
            draft->m_preview = Json{{"can_apply", true}, {"preview_hash", "mock"}};
            draft->m_reviewedInput = Json::object();
            draft->Apply();
            const auto accepted = success;
            accepted(Json{{"new_revision", Uuid()}});
            CanvasAssert(draft->m_reloadingContext && draft->HasDraft(),
                         "현재 카드 적용 후 다른 카드의 초안을 잃었습니다.");
            failure(Json{
                {"code", 1001}, {"message", "시험용 새 문맥 거절"}, {"data", Json{{"domain_code", "E_RESOURCE"}}}});
            {
                SetupSmoke::DiscardHook reject(wxID_NO);
                CanvasAssert(!draft->Close() && !draft->m_closed && draft->NeedsReload() && reject.count == 1,
                             "문맥 재조회 실패 후 다른 카드 초안을 확인 없이 버렸습니다.");
            }
            m_setupChecks.push_back("other_card_draft_survives_post_apply_query_failure");
        }
        SetupSmoke::Choose(dialog.m_cards, index);
        CanvasAssert(dialog.m_inputs->FieldValue(ifa ? "ground_left" : "radius") == "" &&
                         !dialog.m_applyButton->IsEnabled(),
                     "템플릿에 숨은 치수 기본값 또는 검토되지 않은 적용이 있습니다.");
        SetupSmoke::Choose(dialog.m_binding, 0);
        int targetIndex = 1;
        if (!m_setupLargeChecked)
        {
            for (const auto& target : dialog.m_context.at("targets"))
            {
                if (target.at("id") == m_setupSeedTarget)
                {
                    break;
                }
                ++targetIndex;
            }
        }
        SetupSmoke::Choose(dialog.m_target, targetIndex);
        const Json inputs = CardInputs(ifa);
        for (const auto& input : inputs.items())
        {
            dialog.m_inputs->SetFieldValue(input.key(), input.value());
        }
        if (!ifa)
        {
            const int other = index == 0 ? 1 : 0;
            SetupSmoke::Choose(dialog.m_cards, other);
            SetupSmoke::Choose(dialog.m_cards, index);
            CanvasAssert(dialog.m_inputs->FieldValue("radius") == "15", "카드 전환이 입력한 치수를 버렸습니다.");
            {
                SetupSmoke::DiscardHook reject(wxID_NO);
                CanvasAssert(!dialog.Close() && !dialog.m_closed && reject.count == 1,
                             "템플릿 창 닫기가 미적용 입력을 확인 없이 버렸습니다.");
            }
            m_setupChecks.push_back("template_card_drafts_and_close_confirmation");
        }
        m_setupExpectedRevision = dialog.m_revision;
        m_setupStage = ifa ? 26 : 21;
        SetupSmoke::Click(dialog.m_previewButton);
        if (!ifa)
        {
            dialog.m_inputs->SetFieldValue("width", "1.1");
            CanvasAssert(!dialog.m_pending && dialog.m_preview.is_null() && !dialog.m_applyButton->IsEnabled(),
                         "조회 중 입력 변경이 이전 후보를 폐기하지 않았습니다.");
            m_setupChecks.push_back("late_preview_invalidated_by_edit");
            SetupSmoke::Click(dialog.m_previewButton);
        }
    }
    else if (m_setupStage == 21 || m_setupStage == 26)
    {
        if (m_setupStage == 21 && !m_setupLargeChecked)
        {
            CanvasAssert(!dialog.m_preview.is_null() && !dialog.m_preview.value("can_apply", true) &&
                             !dialog.m_applyButton->IsEnabled() && dialog.m_revision == m_setupExpectedRevision &&
                             dialog.m_preview.at("issues").at(0).at("code") == "E_RESOURCE" &&
                             dialog.m_preview.at("issues").at(0).at("details").at("field_path") == "template_origin",
                         "큰 출처 후보의 바이트 상한 차단이 누락되거나 원본을 변경했습니다. " +
                             dialog.m_preview.value("issues", Json::array()).dump());
            m_setupChecks.push_back("oversized_template_origin_blocks_without_mutation");
            m_setupLargeChecked = true;
            m_setupStage = 40;
            dialog.Close(true);
            return;
        }
        CanvasAssert(!dialog.m_preview.is_null() && dialog.m_preview.value("can_apply", false) &&
                         dialog.m_revision == m_setupExpectedRevision && dialog.m_canvas->IsShown() &&
                         dialog.m_reviewedInput.at("port").is_null(),
                     "읽기 전용 형상 미리보기 또는 geometry-only 조건이 다릅니다. " +
                         Json{{"error", dialog.m_error},
                              {"issues", dialog.m_preview.is_null() ? Json(nullptr)
                                                                    : dialog.m_preview.value("issues", Json::array())}}
                             .dump());
        if (m_setupStage == 21)
        {
            CanvasAssert(dialog.m_reviewedInput.at("explicit_inputs").at("width").at("value") == "1.1",
                         "늦은 미리보기가 최신 입력을 덮었습니다.");
        }
        m_setupStage = m_setupStage == 21 ? 22 : 27;
        SetupSmoke::Click(dialog.m_applyButton);
    }
    else if (m_setupStage == 22)
    {
        CanvasAssert(dialog.m_revision != m_setupExpectedRevision && dialog.m_context.at("instances").size() == 1,
                     "원호 템플릿 적용 뒤 새 문맥을 받지 못했습니다.");
        m_setupChecks.push_back("arc_card_preview_apply_without_physics_defaults");
        m_setupStage = 25;
    }
    else if (m_setupStage == 27)
    {
        CanvasAssert(dialog.m_context.at("instances").size() == 2 && dialog.m_revision != m_setupExpectedRevision,
                     "IFA 템플릿을 두 번째 명령으로 적용하지 못했습니다.");
        m_setupExpectedRevision = dialog.m_revision;
        m_setupChecks.push_back("ifa_card_preview_apply_latest_revision");
        m_setupStage = 28;
    }
    else if (m_setupStage == 28)
    {
        int index = 0;
        for (const auto& card : dialog.m_context.at("cards"))
        {
            if (card.at("template_id") == "literature.g031_pca20006_arc")
            {
                break;
            }
            ++index;
        }
        CanvasAssert(index < static_cast<int>(dialog.m_context.at("cards").size()), "G031 문헌 카드가 없습니다.");
        SetupSmoke::Choose(dialog.m_cards, index);
        SetupSmoke::Choose(dialog.m_binding, 0);
        CanvasAssert(dialog.m_inputs->FieldValue("offset_x") == "" &&
                         dialog.m_inputs->FieldValue("width") == "1.27" && !dialog.m_applyButton->IsEnabled() &&
                         dialog.CardDescription().find("전체 외곽") != std::string::npos,
                     "문헌 치수와 미정 배치 또는 부분 기하 안내가 다릅니다.");
        SetupSmoke::Click(dialog.m_previewButton);
        CanvasAssert(dialog.m_preview.is_null() && dialog.m_revision == m_setupExpectedRevision,
                     "미정 배치를 자동으로 채워 후보를 생성했습니다.");
        dialog.m_inputs->SetFieldValue("offset_x", "55");
        dialog.m_inputs->SetFieldValue("offset_y", "55");
        m_setupStage = 29;
        SetupSmoke::Click(dialog.m_previewButton);
    }
    else if (m_setupStage == 29)
    {
        CanvasAssert(!dialog.m_preview.is_null() && dialog.m_preview.value("can_apply", false) &&
                         dialog.m_preview.at("generation").at("geometry").at("source_dimensions") == "reference" &&
                         dialog.m_reviewedInput.at("explicit_inputs").at("radius") == Json{{"source", "card"}} &&
                         dialog.m_preview.at("generation").at("analysis") == "not_performed" &&
                         dialog.m_preview.at("generation").at("measurement") == "not_verified",
                     "G031 원문/분리 상태의 미리보기가 다릅니다.");
        m_setupChecks.push_back("literature_reference_dimensions_and_partial_scope");
        dialog.m_inputs->SetFieldValue("width", "1.1");
        CanvasAssert(dialog.m_preview.is_null() && !dialog.m_applyButton->IsEnabled(),
                     "문헌 치수 수정이 검토 후보를 폐기하지 않았습니다.");
        m_setupStage = 46;
        SetupSmoke::Click(dialog.m_previewButton);
    }
    else if (m_setupStage == 46)
    {
        CanvasAssert(!dialog.m_preview.is_null() && dialog.m_preview.value("can_apply", false) &&
                         dialog.m_preview.at("generation").at("geometry").at("modified_fields") == Json::array({"width"}) &&
                         dialog.m_reviewedInput.at("explicit_inputs").at("width").at("value") == "1.1" &&
                         dialog.m_notes->GetValue().Find(Display("원문 치수 수정")) != wxNOT_FOUND,
                     "수정 문헌 치수와 원문 또는 검증 상태를 구분하지 않았습니다.");
        m_setupChecks.push_back("literature_modified_dimensions_invalidate_and_keep_source");
        m_setupStage = 47;
        SetupSmoke::Click(dialog.m_applyButton);
    }
    else if (m_setupStage == 47)
    {
        CanvasAssert(dialog.m_context.at("instances").size() == 3 && dialog.m_revision != m_setupExpectedRevision,
                     "G031 부분 기하를 세 번째 원자 명령으로 적용하지 못했습니다.");
        m_setupChecks.push_back("literature_atomic_apply_without_physical_defaults");
        m_setupExpectedRevision = dialog.m_revision;
        m_setupStage = 30;
        SetupSmoke::Click(dialog.m_cancel);
    }
}
