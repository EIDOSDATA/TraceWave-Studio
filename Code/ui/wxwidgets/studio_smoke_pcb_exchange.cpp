/** @file @brief 실제 PCB/CAM 생성과 원문 청크 전송/명시 대응/단일 적용을 연결한다. */
#include "studio_internal.h"
#include "pcb_import_dialog.h"
#include "pcb_cam_output_view.h"
#include "output_controller.h"
#include "output_workspace.h"
#include "output_record_dialog.h"
#include "setup_smoke_support.h"
#include "studio_notebook.h"
#include <wx/checkbox.h>
#include <wx/checklst.h>
#include <wx/listctrl.h>
#include <wx/textctrl.h>
#include <fstream>

namespace
{
/** @brief 실제 출력 검토 확인만 승인하고 writer와 검수 작업은 제품 경로로 수행한다. */
class PcbOutputConfirm final : public wxModalDialogHook
{
public:
    PcbOutputConfirm()
    {
        Register();
    }
    ~PcbOutputConfirm() override
    {
        Unregister();
    }
    int Enter(wxDialog* dialog) override
    {
        return dynamic_cast<OutputRecordDialog*>(dialog) ? wxID_OK : wxID_NONE;
    }
};
}

void StudioSmokeDriver::PcbExchangeSafetyChecks()
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
    auto recovery = std::make_shared<PcbImportRecovery>();
    auto dialog =
        std::make_unique<PcbImportDialog>(&m_frame, m_pcbExchangeFixture.at("import_context"), gateway, recovery);
    dialog->ReadUpload(Uuid());
    const auto late = calls.back().success;
    dialog->m_closed = true;
    dialog.reset();
    late(Json::object());
    recovery->checkpoint = {{"method", "pcb.import.chunk"},
                            {"request_key", Uuid()},
                            {"request_key_epoch", Uuid()},
                            {"input", Json::object()}};
    const auto pending = recovery->checkpoint;
    dialog = std::make_unique<PcbImportDialog>(&m_frame, m_pcbExchangeFixture.at("import_context"), gateway, recovery);
    CanvasAssert(dialog->Uncertain() && !dialog->m_uploadButton->IsEnabled() && !dialog->m_apply->IsEnabled(),
                 "불명 원문 전송에서 새 전송/적용이 열렸습니다.");
    dialog->Recover();
    CanvasAssert(calls.back().method == "pcb.import.receipt" &&
                     calls.back().input.at("request_key") == pending.at("request_key"),
                 "원문 전송 복구가 원래 영수증 키를 잃었습니다.");
    const auto unresolved = calls.back().success;
    unresolved({{"status", "unresolved"}, {"authoritative", true}, {"response", nullptr}});
    CanvasAssert(recovery->checkpoint == pending && dialog->Uncertain(), "영수증 부재를 미전송으로 추정했습니다.");
    dialog->m_closed = true;
    dialog.reset();
    m_setupChecks.push_back("pcb_exchange_late_source_and_uncertain_receipt_safe");
}

void StudioSmokeDriver::PcbExchangeSmokeTick()
{
    if (auto* dialog = dynamic_cast<PcbImportDialog*>(m_frame.m_setupDialog))
    {
        if (dialog->m_pending || dialog->m_uploading)
        {
            return;
        }
        if (m_setupStage == 7)
        {
            const auto path =
                std::filesystem::path(m_frame.m_options.workspace.ToStdWstring()) / "gui-source.kicad_pcb";
            CanvasAssert(dialog->LoadFiles({wxString(path.native())}), "원래 KiCad 파일 바이트를 읽지 못했습니다.");
            CanvasAssert(dialog->m_files.at(0).bytes.size() > 256U * 1024U, "청크 경계 시험 원문이 작습니다.");
            m_setupStage = 8;
            SetupSmoke::Click(dialog->m_uploadButton);
        }
        else if (m_setupStage == 8 && dialog->m_uploadState.is_object())
        {
            const auto& file = dialog->m_uploadState.at("files").at(0);
            CanvasAssert(file.at("received") == file.at("bytes") &&
                             file.at("sha256") == m_pcbExchangeFixture.at("raw_sha256"),
                         "명시 전송 위치/원문 hash가 다릅니다.");
            m_pcbExchangeUploadId = dialog->m_upload;
            m_setupChecks.push_back("pcb_exchange_native_exact_chunk_upload");
            m_setupStage = 9;
            SetupSmoke::Click(dialog->m_parseButton);
        }
        else if (m_setupStage == 9 && dialog->m_mappingLoaded)
        {
            CanvasAssert(dialog->m_uploadState.at("parse_state") == "completed" &&
                             !dialog->m_uploadState.at("parsed").at("physics_verified").get<bool>(),
                         "별도 parser가 완료되지 않았거나 물리 합격으로 승격됐습니다.");
            dialog->m_boardConfirmed->SetValue(true);
            wxCommandEvent checked(wxEVT_CHECKBOX, dialog->m_boardConfirmed->GetId());
            dialog->m_boardConfirmed->GetEventHandler()->ProcessEvent(checked);
            for (auto& row : dialog->m_layerRows)
            {
                const auto desired = m_pcbExchangeFixture.at("layer_mapping").at(row.source);
                int selected = -1;
                for (std::size_t index = 1; index < row.targets.size(); ++index)
                {
                    if (row.targets.at(index) == desired)
                    {
                        selected = static_cast<int>(index);
                    }
                }
                CanvasAssert(selected > 0, "명시 도체층 대응을 선택할 수 없습니다.");
                SetupSmoke::Choose(row.choice, selected);
            }
            for (auto& row : dialog->m_netRows)
            {
                const auto desired = m_pcbExchangeFixture.at("net_mapping").at(row.source);
                int selected = -1;
                for (std::size_t index = 1; index < row.targets.size(); ++index)
                {
                    if (row.targets.at(index) == desired)
                    {
                        selected = static_cast<int>(index);
                    }
                }
                CanvasAssert(selected > 0, "미연결을 포함한 명시 넷 대응이 없습니다.");
                SetupSmoke::Choose(row.choice, selected);
            }
            for (unsigned int index = 0; index < dialog->m_losses->GetCount(); ++index)
            {
                dialog->m_losses->Check(index);
            }
            dialog->m_reason->SetValue(Display("실제 GUI의 파일 대응 검증 / 제작 합격 아님"));
            m_setupChecks.push_back("pcb_exchange_real_parser_explicit_mapping");
            m_setupStage = 10;
            SetupSmoke::Click(dialog->m_preview);
        }
        else if (m_setupStage == 10 && dialog->m_review.is_object())
        {
            CanvasAssert(dialog->m_review.value("can_apply", false) && dialog->m_canvas->IsShownOnScreen() &&
                             dialog->m_changes->GetItemCount() > 0 &&
                             dialog->m_changes->GetClientSize().y > dialog->FromDIP(80),
                         "수입 후보와 실제 변경표를 검토할 수 없습니다.");
            dialog->m_reason->SetValue(Display("명시 대응을 다시 확인함"));
            CanvasAssert(dialog->m_review.is_null() && !dialog->m_apply->IsEnabled(),
                         "수입 이유 변경 뒤 검토 hash를 무효화하지 않았습니다.");
            m_setupChecks.push_back("pcb_exchange_review_invalidates_and_visible_changes");
            m_setupStage = 11;
            SetupSmoke::Click(dialog->m_preview);
        }
        else if (m_setupStage == 11 && dialog->m_review.is_object())
        {
            CanvasAssert(dialog->m_review.value("can_apply", false), "수입 재검토가 실패했습니다.");
            m_setupStage = 12;
            SetupSmoke::Click(dialog->m_apply);
            dialog->Apply();
        }
        return;
    }
    if (m_frame.m_busy || !m_frame.m_output || m_frame.m_cadRestoring || m_frame.m_solverRestoring)
    {
        return;
    }
    auto& output = *m_frame.m_output;
    auto* view = output.m_view;
    const bool idle = !output.Active() && output.m_reads == 0;
    if (m_setupStage == 1)
    {
        std::ifstream stream(std::filesystem::path(m_frame.m_options.workspace.ToStdWstring()) /
                                 "pcb-exchange-smoke-fixture.json",
                             std::ios::binary);
        stream >> m_pcbExchangeFixture;
        m_pcbExchangeBefore = m_frame.m_editor;
        m_pcbExchangeRevision = m_frame.m_revision;
        PcbExchangeSafetyChecks();
        m_setupStage = 2;
        m_frame.m_views->SetSelection(5);
        output.Context(0, true);
    }
    else if (m_setupStage == 2 && idle && view->m_context.is_object())
    {
        view->SelectKind(2);
        view->SelectSnapshot(m_pcbExchangeFixture.at("snapshot"));
        view->m_pcb->m_tabs->SetSelection(1);
        output.Actions();
        m_setupStage = 3;
        SetupSmoke::Click(view->m_pcb->m_preview);
    }
    else if (m_setupStage == 3 && idle && view->Preview().is_object())
    {
        CanvasAssert(view->Preview().value("can_build", false) && view->Preview().at("format") == "gerber_job" &&
                         view->m_pcb->m_gerber->GetItemCount() >= 2,
                     "CAM 원문 층의 실제 검토가 없습니다.");
        CanvasAssert(view->Preview().at("pcb_preview").at("holes").at(0).at("tool_diameter_mm").is_null(),
                     "CAM 검토가 공구를 추정했습니다.");
        m_setupChecks.push_back("pcb_exchange_native_cam_layers_and_unknown_tool");
        m_setupStage = 4;
        PcbOutputConfirm confirm;
        SetupSmoke::Click(view->m_pcb->m_build);
    }
    else if (m_setupStage == 4 && idle && view->Record().is_object())
    {
        CanvasAssert(view->Record().at("state") == "completed" && view->Record().at("format") == "gerber_job" &&
                         !view->Record().at("report").at("manufacturing_verified").get<bool>(),
                     "실제 CAM 생성과 제조 검증 상태를 혼동했습니다.");
        m_pcbExchangeBuildId = view->Record().at("job_id").get<std::string>();
        m_setupChecks.push_back("pcb_exchange_actual_cam_build_no_manufacturing_claim");
        m_setupStage = 5;
        SetupSmoke::Click(view->m_verify);
    }
    else if (m_setupStage == 5 && idle && view->Record().is_object() &&
             view->Record().at("job_id") != m_pcbExchangeBuildId)
    {
        CanvasAssert(view->Record().at("state") == "completed" &&
                         view->Record().at("result").at("original_job_id") == m_pcbExchangeBuildId,
                     "별도 CAM 검수가 원래 패키지와 결합되지 않았습니다.");
        m_setupChecks.push_back("pcb_exchange_fresh_verify_preserves_package");
        m_setupStage = 7;
        m_frame.CallAfter(
            [this]()
            {
                m_frame.OpenPcbImport();
            });
    }
    else if (m_setupStage == 12)
    {
        CanvasAssert(m_frame.m_revision != m_pcbExchangeRevision &&
                         m_frame.m_editor.at("history").at("undo_count").get<int>() ==
                             m_pcbExchangeBefore.at("history").at("undo_count").get<int>() + 1,
                     "가져오기가 한 명령으로 적용되지 않았습니다.");
        m_setupChecks.push_back("pcb_exchange_atomic_import_keeps_original_records");
        m_setupStage = 13;
        m_frame.History("project.undo",
                        [this]()
                        {
                            m_setupStage = 14;
                        });
    }
    else if (m_setupStage == 14)
    {
        CanvasAssert(m_frame.m_editor.at("history").at("undo_count") ==
                         m_pcbExchangeBefore.at("history").at("undo_count"),
                     "수입 전 단일 이력 기준으로 돌아가지 못했습니다.");
        m_setupStage = 15;
        m_frame.History("project.redo",
                        [this]()
                        {
                            m_setupStage = 16;
                        });
    }
    else if (m_setupStage == 16)
    {
        m_setupChecks.push_back("pcb_exchange_single_undo_redo");
        m_setupStage = 17;
        m_frame.SaveProject();
    }
    else if (m_setupStage == 17 && m_frame.m_savedRevision == m_frame.m_revision)
    {
        m_setupExpectedRevision = m_frame.m_revision;
        m_setupStage = 18;
        m_frame.m_connected = false;
        m_frame.m_transportFailed = false;
        m_frame.m_restarting = true;
        m_frame.BeginShutdown();
    }
    else if (m_setupStage == 18 && m_serviceSessions >= 2)
    {
        CanvasAssert(m_frame.m_revision == m_setupExpectedRevision, "원문 수입 저장/서비스 재시작 개정이 다릅니다.");
        m_setupChecks.push_back("pcb_exchange_saved_restart_preserves_sources");
        FinishSmoke(true, "");
    }
}
