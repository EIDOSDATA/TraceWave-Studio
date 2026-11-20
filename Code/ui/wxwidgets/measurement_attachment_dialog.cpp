/** @file @brief 원문 파일을 실행하지 않고 이름, 바이트와 SHA256을 함께 보관한다. */
#include "measurement_attachment_dialog.h"
#include "display_mesh.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/base64.h>
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/file.h>
#include <wx/filedlg.h>
#include <wx/filename.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <wx/weakref.h>
#include <array>

MeasurementAttachmentDialog::MeasurementAttachmentDialog(wxWindow* parent, const Json& context, DialogGateway gateway,
                                                         std::shared_ptr<MeasurementRecovery> recovery)
    : ProjectSetupDialog(parent, "측정 근거 원문 보관", context, gateway), m_gateway(gateway),
      m_recovery(std::move(recovery))
{
    SetSize(FromDIP(wxSize(780, 430)));
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* note =
        new wxStaticText(this, wxID_ANY,
                         Display("파일을 그대로 보관한 뒤 시료 / 교정 기록에 연결합니다. 기록 편집을 취소해도 이미 "
                                 "보관한 원문은 남습니다. 파일당 512 KiB, 프로젝트당 최대 16개 / 8 MiB입니다."));
    note->Wrap(FromDIP(720));
    layout->Add(note, 0, wxEXPAND | wxALL, FromDIP(12));
    m_path = new wxTextCtrl(this, wxID_ANY, wxEmptyString, wxDefaultPosition, wxDefaultSize, wxTE_READONLY);
    m_browse = new wxButton(this, wxID_ANY, Display("원문 파일 선택..."));
    auto* path = new wxBoxSizer(wxHORIZONTAL);
    path->Add(m_path, 1, wxEXPAND | wxRIGHT, FromDIP(8));
    path->Add(m_browse);
    layout->Add(path, 0, wxEXPAND | wxALL, FromDIP(12));
    auto* fields = new wxFlexGridSizer(2, FromDIP(8), FromDIP(12));
    fields->AddGrowableCol(1, 1);
    m_role = new wxChoice(this, wxID_ANY);
    for (const auto* label : {"교정", "시료", "환경", "외부 처리", "기타"})
    {
        m_role->Append(Display(label));
    }
    m_role->SetSelection(4);
    m_media = new wxChoice(this, wxID_ANY);
    for (const auto* label :
         {"application/octet-stream", "application/pdf", "image/png", "image/jpeg", "text/plain", "text/csv"})
    {
        m_media->Append(label);
    }
    m_media->SetSelection(0);
    fields->Add(new wxStaticText(this, wxID_ANY, Display("근거 역할")), 0, wxALIGN_CENTER_VERTICAL);
    fields->Add(m_role, 1, wxEXPAND);
    fields->Add(new wxStaticText(this, wxID_ANY, Display("명시 파일 유형")), 0, wxALIGN_CENTER_VERTICAL);
    fields->Add(m_media, 1, wxEXPAND);
    layout->Add(fields, 0, wxEXPAND | wxALL, FromDIP(12));
    m_status = new wxStaticText(
        this, wxID_ANY, Display("원문 선택 후 보관하세요. 문서를 실행하거나 온라인 참조를 자동 내려받지 않습니다."));
    layout->Add(m_status, 1, wxEXPAND | wxALL, FromDIP(12));
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    m_upload = new wxButton(this, wxID_ANY, Display("원문 보관"));
    m_recover = new wxButton(this, wxID_ANY, Display("이전 보관 결과 확인"));
    for (auto* button : {m_upload, m_recover, new wxButton(this, wxID_CANCEL, Display("닫기"))})
    {
        actions->Add(button, 0, wxALL, FromDIP(4));
    }
    layout->Add(actions, 0, wxALL, FromDIP(8));
    SetSizer(layout);
    m_browse->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       Browse();
                   });
    m_upload->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       Upload();
                   });
    m_recover->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        Recover();
                    });
    UpdateActions();
}

const Json& MeasurementAttachmentDialog::Attachment() const
{
    return m_attachment;
}
bool MeasurementAttachmentDialog::HasDraft() const
{
    return false;
}
void MeasurementAttachmentDialog::UpdateActions()
{
    const bool ready = Editable() && !m_pending && !m_recovering && !m_recovery->pending.is_object();
    m_browse->Enable(ready);
    m_role->Enable(ready);
    m_media->Enable(ready);
    m_upload->Enable(ready && !m_encoded.empty());
    m_recover->Show(m_recovery->pending.is_object());
    m_recover->Enable(m_recovery->pending.is_object() && !m_pending && !m_mutating && !m_recovering);
}
void MeasurementAttachmentDialog::Browse()
{
    wxFileDialog chooser(this, Display("보관할 측정 근거"), wxEmptyString, wxEmptyString,
                         Display("모든 파일 (*.*)|*.*"), wxFD_OPEN | wxFD_FILE_MUST_EXIST);
    if (chooser.ShowModal() != wxID_OK)
    {
        return;
    }
    wxFile file(chooser.GetPath(), wxFile::read);
    const auto size = file.IsOpened() ? file.Length() : wxInvalidOffset;
    if (size <= 0 || size > 512 * 1024)
    {
        SetStatus("읽을 수 있는 512 KiB 이하의 비어 있지 않은 파일을 선택하세요.");
        return;
    }
    std::vector<unsigned char> bytes(static_cast<std::size_t>(size));
    if (file.Read(bytes.data(), bytes.size()) != size || file.Length() != size)
    {
        SetStatus("읽는 중 원문이 바뀌었습니다. 다시 선택하세요.");
        return;
    }
    m_name = Utf8(wxFileName(chooser.GetPath()).GetFullName());
    m_encoded = Utf8(wxBase64Encode(bytes.data(), bytes.size()));
    m_sha256 = DisplayMesh::Sha256(std::string(bytes.begin(), bytes.end()));
    m_bytes = bytes.size();
    m_path->ChangeValue(chooser.GetPath());
    SetStatus("원문 " + std::to_string(m_bytes) + " 바이트 / 이름과 해시를 함께 보관합니다.");
    UpdateActions();
}
void MeasurementAttachmentDialog::Upload()
{
    if (!Editable() || m_pending || m_recovery->pending.is_object() || m_encoded.empty())
    {
        return;
    }
    static const std::array<const char*, 5> roles{"calibration", "specimen", "environment", "processing", "other"};
    Request("measurement.attachment.add",
            {{"name", m_name},
             {"role", roles.at(static_cast<std::size_t>(m_role->GetSelection()))},
             {"media_type", Utf8(m_media->GetStringSelection())},
             {"content_base64", m_encoded},
             {"sha256", m_sha256}},
            true,
            [this](const Json& response)
            {
                Accept(response);
            });
}
void MeasurementAttachmentDialog::Accept(const Json& response)
{
    if (response.value("project_id", "") != m_projectId || !response.value("artifact", Json(nullptr)).is_object())
    {
        throw std::runtime_error("보관한 원문의 프로젝트 또는 파일 참조가 다릅니다.");
    }
    const auto request = m_recovery->pending.value("input", Json::object());
    if (response.at("artifact").value("sha256", "") != request.value("sha256", m_sha256))
    {
        throw std::runtime_error("원문 보관 응답의 SHA256이 요청과 다릅니다.");
    }
    m_attachment = {{"id", response.at("attachment_id")},
                    {"name", response.at("name")},
                    {"role", response.at("role")},
                    {"media_type", response.at("media_type")},
                    {"artifact", response.at("artifact")}};
    if (m_recovery->resolved)
    {
        m_recovery->resolved();
    }
    m_recovery->pending = nullptr;
    m_disconnected = false;
    CloseDialog(true);
}
void MeasurementAttachmentDialog::Recover()
{
    if (m_closed || m_mutating || m_recovering || !m_recovery->pending.is_object())
    {
        return;
    }
    m_recovering = true;
    const auto pending = m_recovery->pending;
    wxWeakRef<MeasurementAttachmentDialog> weak(this);
    UpdateActions();
    m_gateway(
        "measurement.receipt",
        {{"request_key", pending.at("request_key")}, {"request_key_epoch", pending.at("request_key_epoch")}}, false,
        [this, weak, pending](const Json& response)
        {
            if (!weak || m_closed || m_recovery->pending != pending)
            {
                return;
            }
            m_recovering = false;
            if (response.value("authoritative", false) && response.value("status", "") == "found" &&
                response.value("response", Json(nullptr)).is_object())
            {
                Accept(response.at("response"));
            }
            else
            {
                SetStatus("원래 보관 요청을 아직 확정할 수 없습니다. 새 요청을 보내지 않습니다.");
                UpdateActions();
            }
        },
        [this, weak](const Json& error)
        {
            if (!weak || m_closed)
            {
                return;
            }
            m_recovering = false;
            SetStatus(DiagnosticMessage(error));
            UpdateActions();
        });
}
