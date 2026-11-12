/** @file @brief 실제 대화상자의 조회 세대와 종료/미확정 변경 안전성을 검사한다. */
#include "studio_internal.h"
#include "target_editor_dialog.h"
#include "setup_smoke_support.h"

void StudioSmokeDriver::SetupSafetyChecks(const Json& context)
{
    using Callback = std::function<void(const Json&)>;
    std::vector<Callback> successes;
    std::vector<Callback> failures;
    DialogGateway delayed =
        [&successes, &failures](const std::string&, const Json&, bool, Callback success, Callback failure)
    {
        successes.push_back(std::move(success));
        failures.push_back(std::move(failure));
    };
    int accepted = 0;
    auto dialog = std::make_unique<TargetEditorDialog>(&m_frame, context, delayed);
    dialog->Request("target.editor.get", Json::object(), false,
                    [&accepted](const Json&)
                    {
                        ++accepted;
                    });
    dialog->Request("target.editor.get", Json::object(), false,
                    [&accepted](const Json&)
                    {
                        ++accepted;
                    });
    successes.at(0)(context);
    CanvasAssert(accepted == 0 && dialog->m_pending, "이전 조회 응답을 현재 요청으로 잘못 적용했습니다.");
    successes.at(1)(context);
    CanvasAssert(accepted == 1 && !dialog->m_pending, "현재 조회 응답을 회수하지 못했습니다.");
    dialog->Request("target.editor.get", Json::object(), false,
                    [&accepted](const Json&)
                    {
                        ++accepted;
                    });
    dialog->CallAfter(
        [&dialog]()
        {
            dialog->Close();
        });
    dialog->ShowModal();
    successes.at(2)(context);
    CanvasAssert(dialog->m_closed && accepted == 1, "닫힌 모달 화면에 조회 응답을 적용했습니다.");
    dialog.reset();
    successes.at(2)(context);
    CanvasAssert(accepted == 1, "파괴된 화면에 조회 응답을 적용했습니다.");
    m_setupChecks.push_back("late_response_close_and_destroy_are_safe");

    auto rejected = std::make_unique<TargetEditorDialog>(&m_frame, context, delayed);
    rejected->Request("target.editor.apply", Json::object(), true,
                      [](const Json&)
                      {
                      });
    failures.back()(
        Json{{"code", 1001}, {"message", "시험용 확정 입력 거절"}, {"data", Json{{"domain_code", "E_SCHEMA"}}}});
    CanvasAssert(!rejected->m_mutating && !rejected->m_disconnected && rejected->Editable(),
                 "확정 입력 거절을 불명 적용으로 처리했습니다.");
    rejected.reset();
    m_setupChecks.push_back("definitive_rejection_keeps_draft_editable");

    auto uncertain = std::make_unique<TargetEditorDialog>(&m_frame, context, delayed);
    uncertain->Request("target.editor.apply", Json::object(), true,
                       [](const Json&)
                       {
                       });
    failures.back()(Json{{"code", "E_TIMEOUT"}, {"message", "시험용 결과 미확정"}});
    CanvasAssert(uncertain->m_disconnected && !uncertain->m_mutating && !uncertain->Editable() &&
                     !uncertain->m_apply->IsEnabled() && uncertain->m_cancel->IsEnabled(),
                 "결과 미확정 변경을 다시 적용할 수 있습니다.");
    const auto count = successes.size();
    uncertain->Request("target.editor.apply", Json::object(), true,
                       [](const Json&)
                       {
                       });
    CanvasAssert(successes.size() == count, "불명 적용을 자동 재전송했습니다.");
    uncertain.reset();
    m_setupChecks.push_back("uncertain_mutation_requires_reload");
    const Json resourceError{
        {"code", 1001}, {"message", "시험용 조회 용량 초과"}, {"data", Json{{"domain_code", "E_RESOURCE"}}}};
    Json selected = context;
    const std::string firstId = selected.at("items").at(0).at("id");
    selected["selection"]["id"] = firstId;
    selected["items"].push_back(Json{{"id", Uuid()}, {"label", "조회 실패 목표"}, {"summary", ""}});
    auto failedSelection = std::make_unique<TargetEditorDialog>(&m_frame, selected, delayed);
    SetupSmoke::Select(failedSelection->m_targets, 1);
    CanvasAssert(failedSelection->m_pending && !failedSelection->m_remove->IsEnabled(),
                 "조회 중 이전 목표의 삭제를 허용했습니다.");
    failures.back()(resourceError);
    CanvasAssert(failedSelection->m_targets->GetSelection() == 0 && failedSelection->m_targetId == firstId,
                 "조회 실패 뒤 목록과 실제 편집 대상이 달라졌습니다.");
    failedSelection.reset();
    m_setupChecks.push_back("failed_target_selection_restores_authoritative_identity");

    auto reloadFailure = std::make_unique<TargetEditorDialog>(&m_frame, context, delayed);
    reloadFailure->m_fields->SetFieldValue("name", "신규 적용 후 조회 실패");
    reloadFailure->m_reason->SetValue(Display("시험"));
    reloadFailure->Apply(false);
    const std::string createdId = Uuid();
    const Json applied{{"new_revision", Uuid()}, {"target_id", createdId}};
    const auto acceptApplied = successes.back();
    acceptApplied(applied);
    CanvasAssert(reloadFailure->m_targetId == createdId && reloadFailure->m_reloadingContext &&
                     !reloadFailure->m_apply->IsEnabled(),
                 "새 목표 적용 후 조회가 끝나기 전에 중복 생성을 허용했습니다.");
    failures.back()(resourceError);
    const auto beforeRetry = successes.size();
    reloadFailure->Apply(false);
    CanvasAssert(reloadFailure->NeedsReload() && reloadFailure->GetAppliedResult() == applied &&
                     successes.size() == beforeRetry && !reloadFailure->m_apply->IsEnabled(),
                 "적용 후 조회 실패를 재적용 가능한 초안으로 되돌렸습니다.");
    reloadFailure.reset();
    m_setupChecks.push_back("post_apply_query_failure_locks_without_duplicate_create");

    auto draft = std::make_unique<TargetEditorDialog>(&m_frame, context, delayed);
    draft->m_fields->SetFieldValue("name", "보존할 미적용 초안");
    {
        SetupSmoke::DiscardHook reject(wxID_NO);
        CanvasAssert(!draft->Close() && !draft->m_closed, "창 닫기가 초안 거부를 무시했습니다.");
        SetupSmoke::Click(draft->m_cancel);
        CanvasAssert(!draft->m_closed && draft->m_fields->FieldValue("name") == "보존할 미적용 초안" &&
                         reject.count == 2,
                     "닫기 버튼이 초안을 확인 없이 버렸습니다.");
    }
    {
        SetupSmoke::DiscardHook accept(wxID_YES);
        draft->CallAfter(
            [&draft]()
            {
                draft->Close();
            });
        draft->ShowModal();
        CanvasAssert(draft->m_closed && accept.count == 1, "승인한 초안 폐기 후 닫지 못했습니다.");
    }
    draft.reset();
    m_setupChecks.push_back("dirty_close_requires_explicit_discard");
}
