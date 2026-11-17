/** @file @brief 실제 후보 채택 창의 원본 보존, 검토 수명과 별도 작업 사본 전환을 검사한다. */
#include "studio_internal.h"
#include "sweep_selection_dialog.h"
#include "sweep_selection_recovery.h"
#include "sweep_panel.h"
#include "studio_notebook.h"
#include "setup_smoke_support.h"
#include "design_canvas.h"
#include <fstream>

void StudioSmokeDriver::SelectionSafetyChecks()
{
    struct Pending
    {
        std::string method;
        Json input;
        std::function<void(const Json&)> success;
        std::function<void(const Json&)> failure;
    };
    std::vector<Pending> calls;
    auto recovery = std::make_shared<SweepSelectionRecovery>();
    const Json context = m_selectionFixture.at("context");
    recovery->context = context;
    DialogGateway gateway = [&calls](const std::string& method, const Json& input, bool,
                                     std::function<void(const Json&)> success, std::function<void(const Json&)> failure)
    {
        calls.push_back({method, input, std::move(success), std::move(failure)});
    };
    auto dialog = std::make_unique<SweepSelectionDialog>(&m_frame, context, gateway, recovery);
    dialog->m_reason->SetValue(Display("화면 수명 계약 시험; 실제 생성 요청 아님"));
    dialog->Preview();
    const auto old = calls.back().success;
    dialog->m_name->SetValue(Display("조회 뒤 바뀐 이름"));
    old(m_selectionFixture.at("preview"));
    CanvasAssert(dialog->m_review.is_null() && !dialog->m_apply->IsEnabled(),
                 "입력이 바뀐 뒤 이전 후보 검토를 적용했습니다.");
    dialog->Preview();
    const auto valid = calls.back().success;
    valid(m_selectionFixture.at("preview"));
    CanvasAssert(dialog->m_apply->IsEnabled(), "현재 후보 검토가 적용 버튼에 연결되지 않았습니다.");
    dialog->Apply();
    const auto count = calls.size();
    dialog->Apply();
    CanvasAssert(calls.size() == count && dialog->m_mutating, "중복 생성 클릭이 두 번째 변경 요청을 전송했습니다.");
    recovery->uncertain = true;
    recovery->input = calls.back().input;
    recovery->requestKey = "selection-safety-stable-key";
    recovery->epoch = m_frame.m_epoch;
    const auto uncertain = calls.back().failure;
    uncertain({{"code", "E_UNCERTAIN"}, {"message", "시험용 전송 결과 불명"}});
    CanvasAssert(dialog->NeedsReload() && !dialog->m_apply->IsEnabled() && !dialog->m_preview->IsEnabled(),
                 "변경 결과 불명 상태에서 새 생성 요청을 허용했습니다.");
    dialog->Recover();
    CanvasAssert(calls.back().method == "sweep.selection.receipt" &&
                     calls.back().input.at("request_key") == recovery->requestKey,
                 "권위 조회가 원래 요청 키 대신 새 변경 명령을 만들었습니다.");
    const auto unresolved = calls.back().success;
    unresolved(
        {{"status", "unresolved"}, {"authoritative", true}, {"response", nullptr}, {"reason", "원 작업 확인 필요"}});
    CanvasAssert(!dialog->m_apply->IsEnabled() && recovery->uncertain && dialog->m_recover->IsEnabled(),
                 "영수증 미발견을 미생성으로 단정하여 중복 요청 잠금을 풀었습니다.");
    dialog->Recover();
    const auto late = calls.back().success;
    dialog->m_closed = true;
    dialog.reset();
    late({{"status", "expired"}, {"authoritative", true}, {"response", nullptr}});
    m_setupChecks.push_back("selection_late_draft_uncertain_receipt_lifetime");

    const std::string workspace = Utf8(m_frame.m_options.workspace);
    SweepSelectionStore::Write(workspace, m_selectionOriginalProject, *recovery);
    const auto stored = SweepSelectionStore::Read(workspace, m_selectionOriginalProject);
    CanvasAssert(stored->uncertain && stored->requestKey == recovery->requestKey && stored->epoch == recovery->epoch &&
                     stored->input == recovery->input && stored->context == context,
                 "재열기할 요청 키/epoch/원문 입력을 보존하지 못했습니다.");
    wxString alternate = m_frame.m_options.workspace.Upper();
    alternate.Replace("\\", "/");
    alternate += "/.";
    const auto sameWorkspace = SweepSelectionStore::Read(Utf8(alternate), m_selectionOriginalProject);
    CanvasAssert(sameWorkspace->uncertain && sameWorkspace->requestKey == recovery->requestKey &&
                     sameWorkspace->input == recovery->input,
                 "같은 작업공간의 경로 구분자/대소문자/점 표기가 복구 잠금을 우회했습니다.");
    CanvasAssert(!SweepSelectionStore::Read(workspace + "-different", m_selectionOriginalProject)->uncertain,
                 "다른 작업 공간의 복구 요청을 현재 원본으로 사용했습니다.");
    const Json editor = m_frame.m_editor;
    const Json scene = m_frame.m_scene;
    const wxString originalName = m_frame.m_name->GetValue();
    m_frame.m_name->ChangeValue(originalName + Display(" / 표시 초안"));
    for (int mismatch = 0; mismatch < 4; ++mismatch)
    {
        m_frame.m_editor = editor;
        m_frame.m_scene = scene;
        Json& stale = mismatch < 2 ? m_frame.m_editor : m_frame.m_scene;
        stale[mismatch % 2 == 0 ? "project_id" : "revision_id"] = "00000000-0000-4000-8000-000000000001";
        m_frame.UpdateControls();
        CanvasAssert(!m_frame.GetMenuBar()->IsEnabled(IdSave) && !m_frame.GetMenuBar()->IsEnabled(IdUndo) &&
                         !m_frame.GetMenuBar()->IsEnabled(IdRedo) && !m_frame.m_apply->IsEnabled() &&
                         !m_frame.m_name->IsEnabled() && !m_frame.m_tools.at(IdLine)->IsEnabled() &&
                         !m_frame.m_tools.at(IdArc)->IsEnabled() && m_frame.GetMenuBar()->IsEnabled(IdRefresh) &&
                         m_frame.GetMenuBar()->IsEnabled(IdOpen),
                     "다른 프로젝트/개정의 editor 또는 canvas DTO로 변경을 허용하거나 권위 재조회를 차단했습니다.");
        CanvasAssert(SweepSelectionStore::Read(workspace, m_selectionOriginalProject)->requestKey ==
                         recovery->requestKey,
                     "표시 조회 실패 상태가 원래 생성 영수증 키를 변경했습니다.");
        const auto pending = m_frame.m_requests.Size();
        m_frame.OpenRename();
        m_frame.OpenPrecision();
        CanvasAssert(m_frame.m_setupDialog == nullptr && m_frame.m_requests.Size() == pending,
                     "오래된 조회 상태에서 이름 또는 정밀 편집 진입이 추가 요청을 전송했습니다.");
    }
    m_frame.m_editor = editor;
    m_frame.m_scene = scene;
    m_frame.m_name->ChangeValue(originalName);
    m_frame.UpdateControls();
    SweepSelectionStore::Clear(workspace, m_selectionOriginalProject);
    CanvasAssert(!SweepSelectionStore::Read(workspace, m_selectionOriginalProject)->uncertain,
                 "시험 복구 기록을 명시적으로 회수하지 못했습니다.");
    m_setupChecks.push_back("selection_recovery_key_epoch_persisted");
}

void StudioSmokeDriver::SelectionSmokeTick()
{
    auto* dialog = dynamic_cast<SweepSelectionDialog*>(m_frame.m_setupDialog);
    if (dialog)
    {
        if (dialog->m_pending || dialog->m_recovering)
        {
            return;
        }
        if (m_setupStage == 3)
        {
            CanvasAssert(dialog->m_context.at("source_pin") == m_selectionFixture.at("context").at("source_pin") &&
                             dialog->m_context.at("index") == 1 && dialog->m_context.at("calculated_ordinal") == 0,
                         "선택한 중복 후보의 순서와 실제 계산 행을 구분하지 못했습니다.");
            m_setupStage = 4;
            SetupSmoke::Click(dialog->m_preview);
        }
        else if (m_setupStage == 4 && dialog->m_review.is_object())
        {
            CanvasAssert(!dialog->m_review.at("can_apply").get<bool>() && !dialog->m_apply->IsEnabled() &&
                             dialog->m_reason->IsEnabled(),
                         "사유가 없는 생성 검토를 허용하거나 수정할 입력을 잠갔습니다.");
            m_setupChecks.push_back("selection_required_reason_rejection_recovers");
            dialog->m_reason->SetValue(Display("선택한 행의 출처를 유지하여 편집; 실물 성능 미확립"));
            dialog->m_name->SetValue(Display("채택 화면 검증 사본"));
            dialog->m_path->SetValue(Display("projects/채택 화면 검증 사본"));
            m_setupStage = 5;
            SetupSmoke::Click(dialog->m_preview);
        }
        else if (m_setupStage == 5 && dialog->m_review.is_object())
        {
            CanvasAssert(dialog->m_review.value("can_apply", false) && dialog->m_changes->GetItemCount() == 1 &&
                             dialog->m_changes->GetItemText(0, 2) == "1000" &&
                             dialog->m_changes->GetItemText(0, 3) == "um" &&
                             dialog->m_review.at("changes").at(0).at("after").at("source_refs") ==
                                 Json::array({"test:선택한 중복 행 원문"}),
                         "선택 후보의 실제 단위/출처를 계산 재사용 행으로 바꿨습니다.");
            CanvasAssert(dialog->m_canvas->IsShownOnScreen() &&
                             dialog->m_canvas->GetClientSize().y > dialog->FromDIP(100) &&
                             dialog->m_changes->GetClientSize().y > dialog->FromDIP(80),
                         "후보 캔버스나 치수 표가 실제 창에서 보이지 않습니다.");
            m_setupChecks.push_back("selection_native_candidate_units_sources_and_layout");
            m_setupStage = 6;
            dialog->m_tabs->SetSelection(1);
        }
        else if (m_setupStage == 6)
        {
            const auto text = dialog->m_conditions->GetValue();
            CanvasAssert(text.Contains(Display("실제 계산 후보 1")) && text.Contains(Display("연구 후보 2")) &&
                             text.Contains(Display("미정")) && text.Contains(Display("승계하지 않습니다")) &&
                             !dialog->m_conditions->IsEditable() && dialog->m_advanced->IsCollapsed(),
                         "원본 조건의 미정/당시 상태/계산 재사용 관계 또는 접힌 원문을 잃었습니다.");
            m_setupChecks.push_back("selection_conditions_do_not_inherit_validation");
            dialog->m_tabs->SetSelection(2);
            dialog->m_reason->SetValue(Display("검토 후 수정한 채택 사유; 출처 유지"));
            CanvasAssert(dialog->m_review.is_null() && !dialog->m_apply->IsEnabled(),
                         "사유 수정 뒤 이전 검토 해시를 그대로 적용할 수 있습니다.");
            m_setupChecks.push_back("selection_review_invalidates_on_input_change");
            m_setupStage = 7;
            SetupSmoke::Click(dialog->m_preview);
        }
        else if (m_setupStage == 7 && dialog->m_review.is_object())
        {
            CanvasAssert(dialog->m_review.value("can_apply", false), "수정한 사유의 검토가 실패했습니다.");
            m_setupStage = 8;
            SetupSmoke::Click(dialog->m_apply);
            CanvasAssert(!dialog->m_apply->IsEnabled(), "생성 요청 대기 중 적용 버튼이 다시 활성화됐습니다.");
            dialog->Apply();
        }
        else if (m_setupStage == 8 && dialog->GetAppliedResult().is_object())
        {
            m_selectionResult = dialog->GetAppliedResult();
            CanvasAssert(m_frame.m_project == m_selectionOriginalProject &&
                             m_frame.m_revision == m_selectionFixture.at("revision_id") &&
                             m_selectionResult.at("new_project_id") != m_selectionOriginalProject &&
                             dialog->m_open->IsEnabled() && !dialog->m_apply->IsEnabled(),
                         "새 사본 생성이 원본 개정을 덮거나 자동으로 새 프로젝트를 열었습니다.");
            CanvasAssert(
                SweepSelectionStore::Read(Utf8(m_frame.m_options.workspace), m_selectionOriginalProject)->uncertain,
                "생성 응답 직후 사용자가 결과를 확인하기 전에 복구 영수증 키를 지웠습니다.");
            m_setupChecks.push_back("selection_single_copy_keeps_original_open");
            m_setupStage = 9;
            // @brief 시험 전용 서비스의 두 표시 조회 오류를 실제 복구 경로에서 관찰한다.
            m_frame.m_options.smoke = false;
            SetupSmoke::Click(dialog->m_open);
        }
        return;
    }
    if (m_frame.m_busy || m_frame.m_sweepPending || m_frame.m_cadRestoring || m_frame.m_solverRestoring)
    {
        return;
    }
    if (m_setupStage == 1)
    {
        std::ifstream stream(std::filesystem::path(m_frame.m_options.workspace.ToStdWstring()) /
                                 "selection-smoke-fixture.json",
                             std::ios::binary);
        stream >> m_selectionFixture;
        m_selectionOriginalProject = m_frame.m_project;
        m_selectionBefore = m_frame.m_editor;
        CanvasAssert(m_selectionOriginalProject == m_selectionFixture.at("project_id") &&
                         m_frame.m_revision == m_selectionFixture.at("revision_id"),
                     "후보 채택 시험의 원본 개정이 다릅니다.");
        SelectionSafetyChecks();
        m_setupStage = 16;
        m_frame.m_busy = true;
        m_frame.UpdateControls();
        m_frame.RefreshEditor(m_frame.m_selection,
                              [this]()
                              {
                                  CanvasAssert(
                                      m_frame.m_editor.at("project_id") == m_selectionOriginalProject &&
                                          m_frame.m_editor.at("revision_id") == m_selectionFixture.at("revision_id") &&
                                          m_frame.m_scene.at("project_id") == m_selectionOriginalProject &&
                                          m_frame.m_scene.at("revision_id") == m_selectionFixture.at("revision_id"),
                                      "권위 재조회 성공 뒤에도 현재 프로젝트의 편집/캔버스 원본이 일치하지 않습니다.");
                                  m_frame.m_busy = false;
                                  m_frame.UpdateControls();
                                  CanvasAssert(m_frame.GetMenuBar()->IsEnabled(IdSave) && m_frame.m_name->IsEnabled(),
                                               "현재 원본의 실제 재조회 후 편집 잠금을 회복하지 못했습니다.");
                                  m_setupChecks.push_back("selection_editor_canvas_owner_gate_and_refresh");
                                  m_setupStage = 2;
                                  m_frame.m_views->SetSelection(8);
                                  m_frame.RefreshSweeps(m_selectionFixture.at("study_id").get<std::string>());
                              });
    }
    else if (m_setupStage == 2 && m_frame.m_sweepPanel->StudyId() == m_selectionFixture.at("study_id"))
    {
        m_setupStage = 3;
        m_frame.CallAfter(
            [this]()
            {
                m_frame.OpenSweepSelection(1);
            });
    }
    else if ((m_setupStage == 9 || m_setupStage == 17) && m_frame.m_project == m_selectionResult.at("new_project_id"))
    {
        const bool editorMatches = m_frame.m_editor.value("project_id", "") == m_frame.m_project;
        CanvasAssert(
            editorMatches == (m_setupStage == 17) && m_frame.m_scene.value("project_id", "") != m_frame.m_project &&
                !m_frame.GetMenuBar()->IsEnabled(IdSave) && !m_frame.GetMenuBar()->IsEnabled(IdUndo) &&
                !m_frame.GetMenuBar()->IsEnabled(IdRedo) && !m_frame.m_apply->IsEnabled() &&
                !m_frame.m_name->IsEnabled() && !m_frame.m_tools.at(IdLine)->IsEnabled() &&
                m_frame.GetMenuBar()->IsEnabled(IdRefresh) &&
                SweepSelectionStore::Read(Utf8(m_frame.m_options.workspace), m_selectionOriginalProject)->uncertain,
            "실제 editor/canvas 조회 오류 뒤 편집 잠금 또는 원래 생성 영수증을 잃었습니다.");
        m_setupStage = m_setupStage == 9 ? 17 : 18;
        wxCommandEvent refresh(wxEVT_MENU, IdRefresh);
        m_frame.GetEventHandler()->ProcessEvent(refresh);
    }
    else if (m_setupStage == 18 && m_frame.m_project == m_selectionResult.at("new_project_id"))
    {
        m_frame.m_options.smoke = true;
        CanvasAssert(m_frame.m_revision == m_selectionResult.at("revision_id") &&
                         m_frame.m_editor.at("history").at("undo_count") == 1 &&
                         m_frame.m_editor.at("project_id") == m_frame.m_project &&
                         m_frame.m_scene.at("project_id") == m_frame.m_project &&
                         m_frame.GetMenuBar()->IsEnabled(IdSave),
                     "명시적으로 연 새 사본의 단일 명령 이력이 다릅니다.");
        CanvasAssert(
            !SweepSelectionStore::Read(Utf8(m_frame.m_options.workspace), m_selectionOriginalProject)->uncertain,
            "새 사본을 실제로 연 뒤에도 확인된 복구 키를 회수하지 못했습니다.");
        m_setupChecks.push_back("selection_explicit_open_and_single_undo");
        m_setupChecks.push_back("selection_actual_editor_canvas_failure_recovery");
        m_setupStage = 10;
        m_frame.History("project.undo",
                        [this]()
                        {
                            m_setupStage = 11;
                        });
    }
    else if (m_setupStage == 11)
    {
        CanvasAssert(m_frame.m_editor.at("history").at("undo_count") == 0 &&
                         m_frame.m_editor.at("history").at("redo_count") == 1,
                     "새 사본에서 한 번의 실행 취소로 기준 사본을 복원하지 못했습니다.");
        m_setupStage = 12;
        m_frame.History("project.redo",
                        [this]()
                        {
                            m_setupStage = 13;
                        });
    }
    else if (m_setupStage == 13)
    {
        CanvasAssert(m_frame.m_editor.at("history").at("undo_count") == 1 &&
                         m_frame.m_editor.at("history").at("redo_count") == 0,
                     "새 사본의 다시 실행이 단일 명령을 복원하지 못했습니다.");
        m_setupChecks.push_back("selection_copy_undo_redo_native");
        m_setupStage = 14;
        m_frame.SaveProject();
    }
    else if (m_setupStage == 14 && m_frame.m_savedRevision == m_frame.m_revision)
    {
        m_setupExpectedRevision = m_frame.m_revision;
        m_setupStage = 15;
        m_frame.m_connected = false;
        m_frame.m_transportFailed = false;
        m_frame.m_restarting = true;
        m_frame.BeginShutdown();
    }
    else if (m_setupStage == 15 && m_serviceSessions >= 2)
    {
        CanvasAssert(m_frame.m_project == m_selectionResult.at("new_project_id") &&
                         m_frame.m_revision == m_setupExpectedRevision,
                     "저장/서비스 재시작 후 새 사본 대신 원래 프로젝트나 다른 개정을 열었습니다.");
        m_setupChecks.push_back("selection_saved_copy_service_restart");
        FinishSmoke(true, "");
    }
}
