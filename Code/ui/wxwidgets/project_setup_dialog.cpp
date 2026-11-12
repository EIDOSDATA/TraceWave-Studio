/** @file @brief 조회 폐기와 모달 수명, 변경 응답 확인을 공통 처리한다. */
#include "project_setup_dialog.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/display.h>
#include <wx/msgdlg.h>
#include <wx/stattext.h>
#include <wx/weakref.h>
#include <algorithm>
#include <set>

namespace
{
/** @brief 서버가 변경 전 확정 거절한 오류와 결과가 불명인 전송 실패를 구분한다. */
std::string DomainCode(const Json& error)
{
    if (error.contains("data") && error.at("data").is_object())
    {
        return error.at("data").value("domain_code", std::string());
    }
    return error.contains("code") && error.at("code").is_string() ? error.at("code").get<std::string>() : "";
}

bool DefinitiveRejection(const Json& error)
{
    static const std::set<std::string> rejected = {"E_SCHEMA",      "E_CONFLICT",  "E_UNIT",    "E_RESOURCE",
                                                   "E_UNSUPPORTED", "E_NOT_FOUND", "E_VERSION", "E_LIMIT"};
    return rejected.count(DomainCode(error)) != 0;
}
}

ProjectSetupDialog::ProjectSetupDialog(wxWindow* parent, const std::string& title, const Json& context,
                                       DialogGateway gateway)
    : wxDialog(parent, wxID_ANY, Display(title), wxDefaultPosition, parent->FromDIP(wxSize(1120, 780)),
               wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER),
      m_projectId(context.at("project_id")),
      m_revision(context.value("revision_id", context.value("expected_revision", std::string()))),
      m_gateway(std::move(gateway))
{
    StudioTheme::BindSurface(*this);
    const int index = wxDisplay::GetFromWindow(parent);
    const auto area = wxDisplay(index == wxNOT_FOUND ? 0U : static_cast<unsigned int>(index)).GetClientArea();
    const wxSize available(std::max(320, area.width - FromDIP(32)), std::max(300, area.height - FromDIP(48)));
    SetSize(wxSize(std::min(GetSize().x, available.x), std::min(GetSize().y, available.y)));
    SetMinSize(wxSize(std::min(FromDIP(860), available.x), std::min(FromDIP(560), available.y)));
    CentreOnParent();
    Bind(wxEVT_CLOSE_WINDOW,
         [this](wxCloseEvent& event)
         {
             if (m_mutating && event.CanVeto())
             {
                 SetStatus("적용 응답을 기다리고 있습니다. 완료 또는 연결 상태 확인 후 닫을 수 있습니다.");
                 event.Veto();
                 return;
             }
             if (m_mutating)
             {
                 ServiceDisconnected("종료 요청으로 적용 결과를 다시 확인해야 합니다.");
             }
             CloseDialog(!event.CanVeto());
             if (!m_closed && event.CanVeto())
             {
                 event.Veto();
             }
         });
    Bind(
        wxEVT_BUTTON,
        [this](wxCommandEvent&)
        {
            CloseDialog();
        },
        wxID_CANCEL);
}

const Json& ProjectSetupDialog::GetAppliedResult() const
{
    return m_applied;
}

bool ProjectSetupDialog::NeedsReload() const
{
    return m_disconnected || m_needsReload;
}

void ProjectSetupDialog::Request(const std::string& method, const Json& input, bool mutation,
                                 std::function<void(const Json&)> completed)
{
    if (!Editable())
    {
        return;
    }
    const std::uint64_t generation = ++m_generation;
    m_pending = true;
    m_mutating = mutation;
    m_error = nullptr;
    UpdateActions();
    wxWeakRef<ProjectSetupDialog> weak(this);
    try
    {
        m_gateway(
            method, input, mutation,
            [weak, generation, completed, mutation](const Json& result)
            {
                if (!weak || weak->m_closed || generation != weak->m_generation)
                {
                    return;
                }
                weak->m_pending = false;
                weak->m_mutating = false;
                try
                {
                    completed(result);
                }
                catch (const std::exception& error)
                {
                    weak->m_mutating = mutation;
                    weak->ServiceDisconnected(std::string("응답을 확인할 수 없습니다: ") + error.what());
                    return;
                }
                if (!weak->m_closed)
                {
                    weak->UpdateActions();
                }
            },
            [weak, generation, mutation](const Json& error)
            {
                if (!weak || weak->m_closed || generation != weak->m_generation)
                {
                    return;
                }
                weak->m_error = error;
                if (mutation && !DefinitiveRejection(error))
                {
                    weak->ServiceDisconnected(DiagnosticMessage(error));
                    return;
                }
                weak->m_pending = false;
                weak->m_mutating = false;
                weak->ShowRequestFailure(error);
                if (DomainCode(error) == "E_CONFLICT")
                {
                    weak->m_needsReload = true;
                    weak->SetStatus(DiagnosticMessage(error) +
                                    "\n개정이 바뀐 경우 이 화면을 닫고 최신 프로젝트를 다시 읽으세요.");
                }
                weak->UpdateActions();
            });
    }
    catch (const std::exception& error)
    {
        ServiceDisconnected(std::string("요청 전송 상태를 확인할 수 없습니다: ") + error.what());
    }
}

void ProjectSetupDialog::ShowRequestFailure(const Json& error)
{
    SetStatus(DiagnosticMessage(error));
}

void ProjectSetupDialog::InvalidateRead()
{
    if (!m_mutating)
    {
        ++m_generation;
        m_pending = false;
    }
}

void ProjectSetupDialog::AcceptMutation(const Json& result)
{
    m_revision = result.at("new_revision").get<std::string>();
    m_applied = result;
    m_needsReload = false;
}

bool ProjectSetupDialog::Editable() const
{
    return !m_mutating && !m_disconnected && !m_closed;
}

void ProjectSetupDialog::SetStatus(const std::string& message)
{
    if (m_status != nullptr)
    {
        m_status->SetLabel(Display(message));
        m_status->Wrap(std::max(200, GetClientSize().x - FromDIP(32)));
        Layout();
    }
}

bool ProjectSetupDialog::ConfirmDiscard()
{
    if (!HasDraft())
    {
        return true;
    }
    wxMessageDialog confirm(this, Display("미적용 입력을 버리고 계속하시겠습니까?"), Display("미적용 입력 확인"),
                            wxYES_NO | wxNO_DEFAULT | wxICON_QUESTION);
    confirm.SetName("setup.discard");
    return confirm.ShowModal() == wxID_YES;
}

void ProjectSetupDialog::CloseDialog(bool force)
{
    if (m_mutating || m_closed)
    {
        return;
    }
    if (!force && !ConfirmDiscard())
    {
        return;
    }
    m_closed = true;
    ++m_generation;
    EndModal(wxID_CANCEL);
}

void ProjectSetupDialog::ServiceDisconnected(const std::string& message)
{
    if (m_closed)
    {
        return;
    }
    const bool uncertain = m_mutating;
    ++m_generation;
    m_mutating = false;
    m_pending = false;
    m_disconnected = true;
    SetStatus((uncertain ? "적용 여부가 미확정입니다. 다시 적용하지 말고 닫은 뒤 프로젝트를 다시 확인하세요.\n"
                         : "서비스 상태가 바뀌었습니다. 닫은 뒤 다시 열어 확인하세요.\n") +
              message);
    UpdateActions();
}
