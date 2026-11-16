/** @file @brief 가져오기 창의 늦은 응답, 초안 보존과 불명 변경 잠금을 검사한다. */
#include "studio_internal.h"
#include "network_import_dialog.h"
#include "setup_smoke_support.h"

void StudioSmokeDriver::NetworkImportSafetyChecks(const Json& context)
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
    auto dialog = std::make_unique<NetworkImportDialog>(&m_frame, context, delayed);
    dialog->Request("network.library", Json::object(), false,
                    [&accepted](const Json&)
                    {
                        ++accepted;
                    });
    dialog->Request("network.library", Json::object(), false,
                    [&accepted](const Json&)
                    {
                        ++accepted;
                    });
    successes.at(0)(context);
    CanvasAssert(accepted == 0 && dialog->m_pending, "가져오기 창이 이전 응답을 현재 응답으로 적용했습니다.");
    successes.at(1)(context);
    CanvasAssert(accepted == 1 && !dialog->m_pending, "가져오기 창이 최신 응답을 회수하지 못했습니다.");
    dialog->Request("network.library", Json::object(), false,
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
    CanvasAssert(dialog->m_closed && accepted == 1, "닫힌 가져오기 창이 응답을 적용했습니다.");
    dialog.reset();
    successes.at(2)(context);
    CanvasAssert(accepted == 1, "파괴된 가져오기 창에서 콜백이 실행되었습니다.");
    m_setupChecks.push_back("network_late_response_close_destroy_safe");

    auto rejected = std::make_unique<NetworkImportDialog>(&m_frame, context, delayed);
    rejected->m_name->SetValue(Display("유지할 파일 초안"));
    rejected->Request("network.apply", Json::object(), true,
                      [](const Json&)
                      {
                      });
    failures.back()({{"code", 1001}, {"message", "시험용 확정 입력 거절"}, {"data", {{"domain_code", "E_SCHEMA"}}}});
    CanvasAssert(rejected->m_name->GetValue() == Display("유지할 파일 초안") && rejected->m_dirty &&
                     rejected->Editable() && !rejected->m_disconnected && !rejected->m_mutating,
                 "확정 거절이 초안을 잃거나 불명 상태로 바뀌었습니다.");
    rejected.reset();
    m_setupChecks.push_back("network_definitive_rejection_preserves_draft");

    auto uncertain = std::make_unique<NetworkImportDialog>(&m_frame, context, delayed);
    uncertain->Request("network.apply", Json::object(), true,
                       [](const Json&)
                       {
                       });
    failures.back()({{"code", "E_TIMEOUT"}, {"message", "시험용 결과 미확정"}});
    CanvasAssert(uncertain->NeedsReload() && !uncertain->Editable() && !uncertain->m_apply->IsEnabled(),
                 "불명 가져오기 결과를 재적용할 수 있습니다.");
    const auto before = successes.size();
    uncertain->Request("network.apply", Json::object(), true,
                       [](const Json&)
                       {
                       });
    CanvasAssert(successes.size() == before, "불명 변경을 자동 재전송했습니다.");
    uncertain.reset();
    m_setupChecks.push_back("network_uncertain_mutation_locks_replay");

    auto draft = std::make_unique<NetworkImportDialog>(&m_frame, context, delayed);
    draft->m_name->SetValue(Display("미적용 원문 초안"));
    {
        SetupSmoke::DiscardHook reject(wxID_NO);
        CanvasAssert(!draft->Close() && !draft->m_closed && draft->m_name->GetValue() == Display("미적용 원문 초안") &&
                         reject.count == 1,
                     "가져오기 창이 초안 폐기 거절을 무시했습니다.");
    }
    {
        SetupSmoke::DiscardHook accept(wxID_YES);
        draft->CallAfter(
            [&draft]()
            {
                draft->Close();
            });
        draft->ShowModal();
        CanvasAssert(draft->m_closed && accept.count == 1, "승인한 가져오기 초안 폐기를 완료하지 못했습니다.");
    }
    m_setupChecks.push_back("network_dirty_close_requires_discard");
}
