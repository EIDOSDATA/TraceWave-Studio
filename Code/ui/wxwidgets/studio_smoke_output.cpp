/** @file @brief 실제 출력 화면의 고정 입력, 검토, 생성, 별도 검수와 저장 재열기를 검증한다. */
#include "studio_internal.h"
#include "output_controller.h"
#include "output_workspace.h"
#include "output_pending_store.h"
#include "output_record_dialog.h"
#include "output_conditions_view.h"
#include "drawing_output_view.h"
#include "drawing_sheet_canvas.h"
#include "studio_notebook.h"
#include "setup_smoke_support.h"
#include <wx/spinctrl.h>
#include <wx/stattext.h>
#include <wx/listctrl.h>
#include <fstream>
#include <regex>

namespace
{
/** @brief 출력 검토 대화상자의 취소/확인 분기만 고정하고 실제 제품 경로를 유지한다. */
class OutputReviewHook final : public wxModalDialogHook
{
public:
    explicit OutputReviewHook(int answer, const std::string& expectedLabel = "")
        : m_answer(answer), m_expectedLabel(expectedLabel)
    {
        Register();
    }
    ~OutputReviewHook() override
    {
        Unregister();
    }
    int Enter(wxDialog* dialog) override
    {
        if (dynamic_cast<OutputRecordDialog*>(dialog) != nullptr)
        {
            ++count;
            omissionSeen = FindOmission(dialog);
            return m_answer;
        }
        return wxID_NONE;
    }
    int count = 0;
    bool omissionSeen = false;

private:
    /** @brief 실제 대화상자 표의 이름/제외/원문 사유 열을 확인한다. */
    bool FindOmission(wxWindow* window) const
    {
        if (auto* table = dynamic_cast<wxListCtrl*>(window))
        {
            for (long row = 0; row < table->GetItemCount(); ++row)
            {
                if (table->GetColumnCount() >= 4 && table->GetItemText(row) == Display(m_expectedLabel) &&
                    table->GetItemText(row, 1) == Display("제외 / 의미 보존 범위") &&
                    table->GetItemText(row, 3).Contains("include_in_export=false"))
                {
                    return true;
                }
            }
        }
        for (auto* child : window->GetChildren())
        {
            if (FindOmission(child))
            {
                return true;
            }
        }
        return false;
    }
    int m_answer;
    std::string m_expectedLabel;
};
}

void StudioSmokeDriver::OutputSafetyChecks()
{
    auto host = std::make_unique<wxDialog>(&m_frame, wxID_ANY, Display("출력 조회 수명 시험"));
    auto* conditions = new wxPanel(host.get());
    conditions->SetSizer(new wxBoxSizer(wxVERTICAL));
    struct Pending
    {
        std::string method;
        Json input;
        bool mutation;
        std::function<void(const Json&)> success;
        std::function<void(const Json&)> failure;
        std::string key;
        std::string epoch;
    };
    std::vector<Pending> calls;
    OutputGateway gateway = [&calls](const std::string& method, const Json& input, bool mutation,
                                     std::function<void(const Json&)> success, std::function<void(const Json&)> failure,
                                     const std::string& key, const std::string& epoch)
    {
        calls.push_back({method, input, mutation, std::move(success), std::move(failure), key, epoch});
    };
    const auto workspace = Utf8(m_frame.m_options.workspace) + "/output-controller-safety";
    const auto project = m_outputFixture.at("project_id").get<std::string>();
    const auto revision = m_outputFixture.at("revision_id").get<std::string>();
    const auto epoch = Uuid();
    OutputPendingStore::Clear(workspace, project);
    auto controller = std::make_unique<OutputController>(host.get(), conditions, workspace, gateway);
    controller->Update(project, revision, epoch, true, true, true, false);
    controller->Context(0, true);
    const auto late = calls.back().success;
    controller->Update(project, revision, epoch, false, true, false, false);
    late(m_outputFixture.at("context"));
    CanvasAssert(controller->m_view->m_context.is_null() && controller->m_reads == 0,
                 "끊어진 연결의 출력 입력 응답을 표시했습니다.");
    controller->Update(project, revision, epoch, true, true, true, false);
    controller->Context(0, true);
    const auto loaded = calls.back().success;
    loaded(m_outputFixture.at("context"));
    CanvasAssert(controller->m_view->m_context == m_outputFixture.at("context"),
                 "재연결한 출력 입력을 표시하지 못했습니다.");
    controller->m_view->SelectSnapshot(m_outputFixture.at("snapshot"));
    controller->m_view->m_drawing->m_format->SetSelection(0);
    controller->Preview();
    CanvasAssert(calls.back().mutation && calls.back().method == "export.preview" && !calls.back().key.empty(),
                 "출력 검토의 기존 영수증 키를 고정하지 않았습니다.");
    const auto request = calls.back();
    request.failure({{"code", "E_IO"}, {"message", "시험의 명시적인 전송 결과 불명"}});
    const auto saved = OutputPendingStore::Read(workspace, project);
    CanvasAssert(controller->m_uncertain && saved.at("request_key") == request.key &&
                     saved.at("request_key_epoch") == request.epoch && !controller->m_view->m_capture->IsEnabled(),
                 "결과 불명에서 기존 키를 보존하지 않거나 새 작업이 열렸습니다.");
    const auto count = calls.size();
    controller->Preview();
    controller->Capture();
    CanvasAssert(calls.size() == count, "결과 불명에서 새 키의 변경 요청을 보냈습니다.");
    controller->Recover();
    const auto missing = calls.back().success;
    missing({{"status", "unresolved"},
             {"authoritative", true},
             {"response", nullptr},
             {"reason", "영수증 미발견은 미접수 증거가 아닙니다."}});
    CanvasAssert(controller->m_uncertain && OutputPendingStore::Read(workspace, project) == saved,
                 "영수증 미발견을 미생성으로 간주했습니다.");
    controller.reset();
    request.success({{"job_id", Uuid()}, {"state", "queued"}, {"events_cursor", 1}});
    late(m_outputFixture.at("context"));
    controller = std::make_unique<OutputController>(host.get(), conditions, workspace, gateway);
    controller->Update(project, revision, epoch, true, true, true, false);
    CanvasAssert(controller->m_uncertain && controller->m_pending == saved,
                 "새 화면 수명에서 원래 요청 키와 입력을 복구하지 못했습니다.");
    controller->Recover();
    CanvasAssert(calls.back().input.at("request_key") == request.key &&
                     calls.back().input.at("request_key_epoch") == request.epoch,
                 "복구 조회가 원래 요청과 다른 키를 사용했습니다.");
    const auto found = calls.back().success;
    const auto job = Uuid();
    found({{"status", "found"},
           {"authoritative", true},
           {"response", {{"job_id", job}, {"state", "queued"}, {"events_cursor", 1}}}});
    CanvasAssert(!controller->m_uncertain && controller->m_task.Id() == job,
                 "권위 영수증의 기존 작업으로 복구하지 못했습니다.");
    controller.reset();
    OutputPendingStore::Clear(workspace, project);
    m_setupChecks.push_back("output_late_context_disconnect_destroy_safe");
    m_setupChecks.push_back("output_uncertain_stable_receipt_no_duplicate");
}

void StudioSmokeDriver::OutputSmokeTick()
{
    if (m_frame.m_busy || !m_frame.m_output)
    {
        return;
    }
    auto& controller = *m_frame.m_output;
    auto* view = controller.m_view;
    auto* drawing = view->m_drawing;
    const bool idle = !controller.Active() && controller.m_reads == 0;
    if (m_setupStage == 1)
    {
        std::ifstream stream(std::filesystem::path(m_frame.m_options.workspace.ToStdWstring()) /
                                 "output-smoke-fixture.json",
                             std::ios::binary);
        stream >> m_outputFixture;
        m_outputRevision = m_frame.m_revision;
        CanvasAssert(m_outputRevision == m_outputFixture.at("revision_id"), "출력 시험의 편집 개정이 다릅니다.");
        OutputSafetyChecks();
        m_setupStage = 2;
        m_frame.m_views->SetSelection(5);
        m_frame.UpdateOutputViews();
    }
    else if (m_setupStage == 2 && idle && view->m_context.is_object())
    {
        CanvasAssert(view->m_context.at("runtime_configured") == true && !view->Snapshot().is_object(),
                     "현재 문서를 묵시 스냅샷으로 대신하거나 실제 출력 환경을 놓쳤습니다.");
        CanvasAssert(view->m_status->GetLabel().Contains(Display("선택")) &&
                         !view->m_status->GetLabel().Contains(Display("다시 읽어야")),
                     "입력 조회 성공 뒤 미선택 안내가 초기 연결 안내로 남았습니다.");
        for (const auto& message : {Display(drawing->m_canvas->m_message), drawing->m_summary->GetLabel(),
                                    view->m_conditions->m_input->GetValue()})
        {
            CanvasAssert(message.Contains(Display("선택")) && !message.Contains(Display("다시 읽어야")),
                         "입력 조회 성공 뒤 종이/설명/고정 입력 안내가 초기 상태에 남았습니다.");
        }
        const auto requests = m_frame.m_requests.Size();
        const auto project = m_frame.m_project;
        const auto path = m_frame.m_path;
        controller.m_uncertain = true;
        m_frame.OpenProject("open", "projects/another");
        CanvasAssert(m_frame.m_requests.Size() == requests && m_frame.m_project == project && m_frame.m_path == path &&
                         m_frame.m_revision == m_outputRevision && !m_frame.m_busy,
                     "결과 불명 출력이 있는 동안 직접 다른 프로젝트 열기가 원본 또는 요청을 바꿨습니다.");
        controller.m_uncertain = false;
        controller.Actions();
        SetupSmoke::Choose(drawing->m_format, 0);
        m_setupStage = 3;
        SetupSmoke::Click(view->m_capture);
    }
    else if (m_setupStage == 3 && idle && view->Snapshot().is_object())
    {
        CanvasAssert(view->Snapshot().at("snapshot_id") != m_outputFixture.at("snapshot").at("snapshot_id") &&
                         m_frame.m_revision == m_outputRevision &&
                         view->m_context.at("source_revision_id") == m_outputRevision,
                     "명시 고정 입력이 새로 생성되지 않았거나 원본을 바꿨습니다.");
        CanvasAssert(std::regex_search(Utf8(view->m_snapshots->GetStringSelection()),
                                       std::regex("[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2} UTC")),
                     "고정 입력 시각을 날짜와 UTC 대신 epoch 또는 지수로 표시했습니다.");
        m_setupChecks.push_back("output_snapshot_explicit_native");
        m_setupStage = 4;
        SetupSmoke::Click(drawing->m_preview);
    }
    else if (m_setupStage == 4 && idle && view->m_preview.is_object())
    {
        CanvasAssert(view->m_preview.value("can_build", false) &&
                         drawing->m_canvas->Pages() == view->m_preview.at("pages") &&
                         drawing->m_canvas->PageCount() > 0 && drawing->m_canvas->PageCount() <= 32 &&
                         drawing->m_canvas->GetClientSize().y > drawing->FromDIP(100),
                     "서비스의 실제 용지 배치가 native 캔버스에 보존되지 않았습니다.");
        m_setupChecks.push_back("output_actual_paper_and_bounded_pages");
        SetupSmoke::Choose(drawing->m_sheet, 1);
        CanvasAssert(view->m_preview.is_null() && controller.m_previewInput.is_null() &&
                         !drawing->m_build->IsEnabled() && drawing->m_canvas->PageCount() == 0,
                     "옵션 변경 뒤 이전 검토 hash 또는 종이 배치가 남았습니다.");
        m_setupChecks.push_back("output_options_invalidate_review");
        m_setupStage = 5;
        SetupSmoke::Click(drawing->m_preview);
    }
    else if (m_setupStage == 5 && idle && view->m_preview.is_object())
    {
        CanvasAssert(view->m_preview.value("can_build", false), "변경한 도면 옵션을 재검토하지 못했습니다.");
        {
            OutputReviewHook cancel(wxID_CANCEL, m_outputFixture.at("omitted_name"));
            SetupSmoke::Click(drawing->m_build);
            CanvasAssert(cancel.count == 1 && cancel.omissionSeen && !controller.Active(),
                         "검토표에서 실제 제외 도형 이름이 사라졌거나 취소 뒤 도면 생성을 접수했습니다.");
        }
        m_setupStage = 6;
        {
            OutputReviewHook accept(wxID_OK, m_outputFixture.at("omitted_name"));
            SetupSmoke::Click(drawing->m_build);
            CanvasAssert(accept.count == 1 && accept.omissionSeen && controller.Active(),
                         "검토표의 제외 이름이 없거나 확인 뒤 실제 생성이 접수되지 않았습니다.");
        }
        m_setupChecks.push_back("output_review_confirmation_cancel_and_accept");
    }
    else if (m_setupStage == 6 && idle && view->m_record.is_object())
    {
        const auto& value = view->m_record.at("result");
        CanvasAssert(view->m_record.at("state") == "completed" && value.at("status") == "generated_unverified" &&
                         value.at("manufacturing_verified") == false && value.at("physics_verified") == false &&
                         value.at("verification").at("kernel_independent") == false &&
                         m_frame.m_revision == m_outputRevision,
                     "도면 생성이 제작/물리 검증으로 표시되거나 원본 개정을 변경했습니다.");
        m_outputBuilt = view->m_record;
        m_outputBuildId = view->m_record.at("job_id");
        CanvasAssert(view->m_record.at("omissions").size() == 1 &&
                         view->m_record.at("omissions").at(0).at("label") == m_outputFixture.at("omitted_name") &&
                         view->m_conditions->m_limits->GetValue().Contains(Display(m_outputFixture.at("omitted_name"))),
                     "실제 get의 누락 이름이 기본 조건 요약에 전달되지 않았습니다.");
        CanvasAssert(std::regex_search(Utf8(view->m_records->GetStringSelection()),
                                       std::regex("[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2} UTC")),
                     "출력 기록의 시각을 사람이 읽는 UTC 날짜로 표시하지 않았습니다.");
        m_setupChecks.push_back("output_actual_build_generated_not_manufacturing");
        m_setupStage = 7;
        SetupSmoke::Click(view->m_verify);
    }
    else if (m_setupStage == 7 && idle && view->m_record.is_object() && view->m_record.at("job_id") != m_outputBuildId)
    {
        CanvasAssert(view->m_record.at("result").at("original_job_id") == m_outputBuildId &&
                         view->m_record.at("result").at("source_manifest_sha256") ==
                             m_outputBuilt.at("manifest_sha256") &&
                         view->m_record.at("result").at("verification").at("status") == "passed_profile",
                     "새 검수가 원래 출력의 정확한 manifest와 연결되지 않았습니다.");
        m_outputVerifyId = view->m_record.at("job_id");
        m_setupChecks.push_back("output_fresh_verify_keeps_original");
        m_setupStage = 8;
        controller.Record(m_outputBuildId);
    }
    else if (m_setupStage == 8 && idle && view->m_record.is_object() && view->m_record.at("job_id") == m_outputBuildId)
    {
        CanvasAssert(view->m_record == m_outputBuilt && drawing->m_canvas->PageCount() == 0 &&
                         view->m_preview.is_null() && !drawing->m_build->IsEnabled(),
                     "과거 출력 조회에 다른 미리보기가 남았거나 새 검수가 원래 결과를 바꿨습니다.");
        {
            OutputReviewHook details(wxID_OK, m_outputFixture.at("omitted_name"));
            SetupSmoke::Click(view->m_details);
            CanvasAssert(
                details.count == 1 && details.omissionSeen &&
                    view->m_conditions->m_limits->GetValue().Contains(Display(m_outputFixture.at("omitted_name"))),
                "과거 출력의 누락 이름이 상세 표 또는 기본 조건에 전달되지 않았습니다.");
        }
        m_setupChecks.push_back("output_history_clears_current_paper");
        if (m_outputFixture.value("cancel_operation", "") == "export.build")
        {
            m_setupStage = 15;
            SetupSmoke::Click(drawing->m_preview);
        }
        else
        {
            m_setupStage = 12;
            SetupSmoke::Click(view->m_verify);
        }
    }
    else if (m_setupStage == 15 && idle)
    {
        CanvasAssert(view->m_preview.is_object() && view->m_preview.value("can_build", false),
                     "실행 중 생성 취소를 위한 새 도면 검토를 받지 못했습니다.");
        OutputReviewHook accept(wxID_OK, m_outputFixture.at("omitted_name"));
        m_setupStage = 12;
        SetupSmoke::Click(drawing->m_build);
        CanvasAssert(accept.count == 1 && accept.omissionSeen && controller.Active(),
                     "실행 중 취소할 두 번째 도면 생성이 접수되지 않았습니다.");
    }
    else if (m_setupStage == 12 && !controller.m_task.Empty() && controller.m_task.Id() == m_runningNativeJob)
    {
        CanvasAssert(view->m_cancel->IsEnabled(), "실행 중인 출력 작업을 취소할 수 없습니다.");
        m_setupStage = 13;
        const auto operation = m_outputFixture.value("cancel_operation", "export.verify");
        ArmNativeCancellation(controller.m_task.Id(), operation.c_str());
        SetupSmoke::Click(view->m_cancel);
        CanvasAssert(!view->m_cancel->IsEnabled(), "출력 취소 버튼이 입력 직후 잠기지 않았습니다.");
    }
    else if (m_setupStage == 12 && idle)
    {
        FinishSmoke(false, "실행 중인 출력 worker를 관찰하기 전에 작업이 끝났습니다.");
    }
    else if (m_setupStage == 13 && idle)
    {
        CheckNativeCancellation();
        m_setupStage = 14;
        controller.Record(m_outputBuildId);
    }
    else if (m_setupStage == 14 && idle && view->m_record.is_object())
    {
        CanvasAssert(view->m_record == m_outputBuilt && m_frame.m_revision == m_outputRevision,
                     "출력 취소 뒤 이전 산출물이나 개정이 바뀌었습니다.");
        m_setupChecks.push_back("output_running_cancel_reaps_worker_and_keeps_record");
        m_setupStage = 9;
        m_frame.SaveProject();
    }
    else if (m_setupStage == 9 && m_frame.m_savedRevision == m_outputRevision)
    {
        m_setupStage = 10;
        m_frame.m_connected = false;
        m_frame.m_transportFailed = false;
        m_frame.m_restarting = true;
        m_frame.BeginShutdown();
    }
    else if (m_setupStage == 10 && m_serviceSessions >= 2 && idle && view->m_context.is_object())
    {
        m_setupStage = 11;
        controller.Record(m_outputBuildId);
    }
    else if (m_setupStage == 11 && idle && view->m_record.is_object())
    {
        CanvasAssert(view->m_record == m_outputBuilt && m_frame.m_revision == m_outputRevision,
                     "저장/서비스 재시작 뒤 출력 기록 또는 원본 개정이 달라졌습니다.");
        m_setupChecks.push_back("output_saved_restart_exact_record");
        FinishSmoke(true, "");
    }
}
