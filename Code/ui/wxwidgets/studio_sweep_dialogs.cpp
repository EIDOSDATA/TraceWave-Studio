/** @file @brief 원본 개정을 바꾸지 않는 연구 설정 창의 수명과 저장 후 권위 조회를 연결한다. */
#include "studio_internal.h"
#include "sweep_dialog.h"
#include "sweep_panel.h"
#include "sweep_result_dialog.h"
#include <wx/msgdlg.h>

void StudioFrame::OpenSweepSetup()
{
    if (!m_connected || !m_sweepSupported || m_closing || m_project.empty() || m_busy || m_sweepPending ||
        m_setupDialog)
    {
        return;
    }
    if (HasDraft())
    {
        ApplyCurrent(
            [this]()
            {
                OpenSweepSetup();
            });
        return;
    }
    const auto project = m_project;
    const auto revision = m_revision;
    m_busy = true;
    UpdateControls();
    Send(
        "sweep.context", Json::object(), false, Context(),
        [this, project, revision](const Json& context)
        {
            CallAfter(
                [this, project, revision, context]()
                {
                    if (!m_closing && m_connected && project == m_project && revision == m_revision &&
                        context.at("revision_id") == revision)
                    {
                        ShowSweepSetup(context);
                    }
                    else if (!m_closing)
                    {
                        m_busy = false;
                        UpdateControls();
                    }
                });
        },
        [this](const Json& error)
        {
            m_busy = false;
            m_sweepPanel->SetStatus(DiagnosticMessage(error));
            UpdateControls();
        });
}

void StudioFrame::ReviewNextSweepCandidate(const Json& proposal)
{
    if (m_closing || m_sweepPending || m_busy)
    {
        return;
    }
    if (m_revision != proposal.at("revision_id") || HasDraft())
    {
        m_sweepPanel->SetStatus("새 후보를 검토하려면 연구 기준 개정을 열고 편집 중인 값을 정리하십시오.");
        return;
    }
    const auto project = m_project;
    const auto revision = m_revision;
    const auto generation = ++m_sweepGeneration;
    const auto matches = [this, project, revision, generation]()
    {
        return !m_closing && m_connected && m_project == project && m_revision == revision &&
               m_sweepGeneration == generation;
    };
    const auto failed = [this, matches](const Json& error)
    {
        if (matches())
        {
            m_sweepPending = false;
            m_sweepPanel->SetStatus(DiagnosticMessage(error));
            UpdateControls();
        }
    };
    Json input{{"expected_revision", revision}, {"specification", proposal.at("specification")}};
    m_sweepPending = true;
    UpdateControls();
    Send("sweep.preview", input, false, Context(),
         [this, matches, failed, input, proposal](const Json& review)
         {
             if (!matches())
             {
                 return;
             }
             if (!review.value("can_create", false) || review.at("counts").value("valid", 0) != 1 ||
                 review.at("budget_estimate").value("native_budget_insufficient", false))
             {
                 m_sweepPending = false;
                 m_sweepPanel->SetStatus("새 후보의 입력 또는 실행 예산이 검토를 통과하지 못했습니다.");
                 UpdateControls();
                 return;
             }
             CallAfter([this, matches, failed, input, proposal, review]() mutable
             {
                 if (!matches())
                 {
                     return;
                 }
                 auto text = wxString::Format(Display("후보 %d와 %d의 목표 평가에서 얻은 중간값입니다.\n\n"),
                     proposal.at("basis_ordinal").get<int>() + 1, proposal.at("neighbor_ordinal").get<int>() + 1);
                 for (const auto& value : review.at("candidates").at(0).at("values"))
                 {
                     text += wxString::Format(Display("%s  %s %s\n"),
                         Display(value.at("name")), Display(value.at("text")), Display(value.at("unit")));
                 }
                 text += Display("\n저장하면 후보 한 개의 연구가 만들어집니다. 실행은 연구 화면에서 시작합니다.");
                 wxMessageDialog dialog(this, text, Display("다음 후보 검토"), wxYES_NO | wxNO_DEFAULT | wxICON_QUESTION);
                 dialog.SetYesNoLabels(Display("새 연구 저장"), Display("취소"));
                 if (dialog.ShowModal() != wxID_YES || !matches() || HasDraft())
                 {
                     if (matches())
                     {
                         m_sweepPending = false;
                         UpdateControls();
                     }
                     return;
                 }
                 input["review_hash"] = review.at("review_hash");
                 Send("sweep.create", input, true, Context(),
                      [this, matches](const Json& result)
                      {
                          if (matches())
                          {
                              m_sweepPending = false;
                              RefreshSweeps(result.at("study_id"));
                              UpdateControls();
                          }
                      }, failed);
             });
         }, failed);
}

void StudioFrame::ShowSweepSetup(const Json& context)
{
    try
    {
        auto dialog = std::make_unique<SweepDialog>(this, context, ObjectToolGateway());
        m_setupDialog = dialog.get();
        m_canvas->CancelGesture();
        UpdateControls();
        dialog->ShowModal();
        const auto result = dialog->GetAppliedResult();
        const bool reload = dialog->NeedsReload();
        m_setupDialog = nullptr;
        m_busy = false;
        if (m_closeAfterSetup)
        {
            const bool force = m_forceCloseAfterSetup;
            m_closeAfterSetup = false;
            m_forceCloseAfterSetup = false;
            CallAfter(
                [this, force]()
                {
                    Close(force);
                });
            return;
        }
        if (reload && m_connected && !m_closing)
        {
            m_scene = Json::object();
            OpenProject("open", m_path);
        }
        else if (m_connected && !m_closing)
        {
            m_views->SetSelection(8);
            RefreshSweeps(result.is_object() ? result.value("study_id", "") : m_sweepPanel->StudyId());
        }
        UpdateControls();
    }
    catch (const std::exception& error)
    {
        m_setupDialog = nullptr;
        Failure(error.what());
    }
}

void StudioFrame::OpenSweepResult(int index)
{
    if (!m_connected || m_closing || m_busy || m_sweepPending || m_setupDialog || m_sweepPanel->StudyId().empty())
    {
        return;
    }
    const auto project = m_project;
    const auto id = m_sweepPanel->StudyId();
    m_busy = true;
    UpdateControls();
    CallAfter(
        [this, project, id, index]()
        {
            if (m_closing || project != m_project || !m_connected)
            {
                m_busy = false;
                UpdateControls();
                return;
            }
            try
            {
                const Json context{{"project_id", project}, {"revision_id", m_revision}};
                auto dialog = std::make_unique<SweepResultDialog>(this, context, id, index, ObjectToolGateway());
                m_setupDialog = dialog.get();
                UpdateControls();
                dialog->ShowModal();
                m_setupDialog = nullptr;
                m_busy = false;
                if (m_closeAfterSetup)
                {
                    const bool force = m_forceCloseAfterSetup;
                    m_closeAfterSetup = false;
                    m_forceCloseAfterSetup = false;
                    CallAfter(
                        [this, force]()
                        {
                            Close(force);
                        });
                    return;
                }
                UpdateControls();
            }
            catch (const std::exception& error)
            {
                m_setupDialog = nullptr;
                Failure(error.what());
            }
        });
}
