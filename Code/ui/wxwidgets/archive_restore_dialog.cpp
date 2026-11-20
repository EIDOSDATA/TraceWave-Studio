/** @file @brief 받은 파일 바이트가 지정한 복원 결과와 일치할 때만 다음 화면으로 이동한다. */
#include "archive_restore_dialog.h"
#include "display_mesh.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/base64.h>
#include <wx/button.h>
#include <wx/file.h>
#include <wx/filedlg.h>
#include <wx/filename.h>
#include <wx/gauge.h>
#include <wx/listctrl.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <wx/weakref.h>
#include <wx/wrapsizer.h>
#include <algorithm>
#include <stdexcept>

namespace
{
constexpr std::size_t ChunkBytes = 128U * 1024U;
constexpr std::size_t Limit = 8U * 1024U * 1024U;
constexpr auto Receiver = "rfad.archive-receive/0.1";
constexpr auto Archive = "rfad.project-archive/0.1";

wxButton* Button(wxWindow* parent, wxSizer& layout, const char* label)
{
    auto* button = new wxButton(parent, wxID_ANY, Display(label));
    StudioTheme::Button(*button);
    layout.Add(button, 0, wxALL, parent->FromDIP(4));
    return button;
}

std::string Missing(const std::string& reason)
{
    if (reason == "external_reference")
    {
        return "외부 원문";
    }
    if (reason == "source_missing")
    {
        return "원본에서 미확보";
    }
    return "내보내기에서 제외";
}
}

ArchiveRestoreDialog::ArchiveRestoreDialog(wxWindow* parent, wxString workspace, DialogGateway gateway)
    : wxDialog(parent, wxID_ANY, Display("프로젝트 보존 묶음 복원"), wxDefaultPosition, wxDefaultSize,
               wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER),
      m_gateway(std::move(gateway))
{
    StudioTheme::BindSurface(*this);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* title = new wxStaticText(this, wxID_ANY, Display("편집 복원용 프로젝트 묶음"));
    StudioTheme::Title(*title);
    layout->Add(title, 0, wxEXPAND | wxTOP | wxLEFT | wxRIGHT, FromDIP(12));
    auto* destination = new wxStaticText(this, wxID_ANY, Display("받는 작업 영역") + "\n" + workspace);
    destination->Wrap(FromDIP(690));
    destination->SetToolTip(workspace);
    layout->Add(destination, 0, wxEXPAND | wxALL, FromDIP(12));
    auto* files = new wxWrapSizer(wxHORIZONTAL);
    m_browse = Button(this, *files, "복원 ZIP 선택");
    m_check = Button(this, *files, "복원 결과 다시 확인");
    layout->Add(files, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));

    m_values = new wxListCtrl(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(760, 161)),
                              wxLC_REPORT | wxLC_SINGLE_SEL | wxBORDER_SIMPLE);
    m_values->SetName(Display("보존 저장본과 복원 개정 비교"));
    StudioTheme::Table(*m_values);
    m_values->AppendColumn(Display("항목"), wxLIST_FORMAT_LEFT, FromDIP(170));
    m_values->AppendColumn(Display("보존 저장본"), wxLIST_FORMAT_LEFT, FromDIP(283));
    m_values->AppendColumn(Display("가져올 개정"), wxLIST_FORMAT_LEFT, FromDIP(300));
    m_values->Bind(wxEVT_SIZE,
                   [this](wxSizeEvent& event)
                   {
                       const int width = m_values->GetClientSize().x;
                       if (width > FromDIP(600))
                       {
                           m_values->SetColumnWidth(0, width * 22 / 100);
                           m_values->SetColumnWidth(1, width * 38 / 100);
                           m_values->SetColumnWidth(2, width * 39 / 100);
                       }
                       event.Skip();
                   });
    layout->Add(m_values, 1, wxEXPAND | wxLEFT | wxRIGHT | wxTOP, FromDIP(12));
    m_details = new wxTextCtrl(this, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(760, 104)),
                               wxTE_MULTILINE | wxTE_READONLY);
    m_details->SetName(Display("복원 범위와 누락 목록"));
    layout->Add(m_details, 0, wxEXPAND | wxALL, FromDIP(12));
    m_progress = new wxGauge(this, wxID_ANY, 100);
    m_progress->SetName(Display("인계 파일 수신 진행률"));
    layout->Add(m_progress, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    m_status = new wxStaticText(this, wxID_ANY, wxEmptyString);
    layout->Add(m_status, 0, wxEXPAND | wxALL, FromDIP(12));

    auto* actions = new wxWrapSizer(wxHORIZONTAL);
    m_apply = Button(this, *actions, "검토한 프로젝트 복원");
    StudioTheme::Button(*m_apply, true);
    m_open = Button(this, *actions, "복원 프로젝트 열기");
    m_close = Button(this, *actions, "닫기");
    layout->Add(actions, 0, wxALIGN_RIGHT | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    SetSizerAndFit(layout);
    SetMinSize(FromDIP(wxSize(788, 453)));
    CentreOnParent();
    m_browse->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       Browse();
                   });
    m_apply->Bind(wxEVT_BUTTON,
                  [this](wxCommandEvent&)
                  {
                      Apply();
                  });
    m_check->Bind(wxEVT_BUTTON,
                  [this](wxCommandEvent&)
                  {
                      Check();
                  });
    m_open->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     CloseDialog(wxID_OK);
                 });
    m_close->Bind(wxEVT_BUTTON,
                  [this](wxCommandEvent&)
                  {
                      CloseDialog(wxID_CANCEL);
                  });
    Bind(wxEVT_CLOSE_WINDOW,
         [this](wxCloseEvent& event)
         {
             if (event.CanVeto())
             {
                 event.Veto();
             }
             CloseDialog(wxID_CANCEL);
         });
    SetEscapeId(m_close->GetId());
    Status("받은 .rfad.zip을 선택하여 등록 개정과 누락 파일을 검토하세요.");
    Actions();
    m_browse->SetFocus();
}

const std::string& ArchiveRestoreDialog::OpenPath() const
{
    return m_openPath;
}

void ArchiveRestoreDialog::Status(const std::string& text)
{
    m_status->SetLabel(Display(text));
    m_status->SetToolTip(Display(text));
    m_status->Wrap(std::max(FromDIP(510), GetClientSize().x - FromDIP(24)));
    Layout();
}

void ArchiveRestoreDialog::Actions()
{
    m_browse->Enable(!m_busy && !m_uncertain && !m_completed);
    m_apply->Enable(!m_busy && !m_uncertain && m_review.is_object() && !m_completed);
    m_check->Enable(!m_busy && !m_digest.empty() && m_uncertain);
    m_open->Enable(!m_busy && m_completed);
    m_close->Enable(!m_applying);
}

void ArchiveRestoreDialog::Browse()
{
    wxFileDialog chooser(this, Display("받은 프로젝트 보존 묶음 선택"), wxEmptyString, wxEmptyString,
                         Display("보존 ZIP (*.rfad.zip)|*.rfad.zip"), wxFD_OPEN | wxFD_FILE_MUST_EXIST);
    if (chooser.ShowModal() != wxID_OK)
    {
        return;
    }
    try
    {
        const auto path = chooser.GetPath();
        wxFile file(path, wxFile::read);
        const auto size = file.IsOpened() ? file.Length() : wxInvalidOffset;
        if (size <= 0 || size > static_cast<wxFileOffset>(Limit))
        {
            throw std::runtime_error("읽을 수 있는 8 MiB 이하의 ZIP을 선택하세요.");
        }
        std::string raw(static_cast<std::size_t>(size), '\0');
        if (file.Read(raw.data(), raw.size()) != size || file.Length() != size)
        {
            throw std::runtime_error("읽는 동안 원문의 길이가 변경되었습니다.");
        }
        Drop();
        m_review = nullptr;
        m_values->DeleteAllItems();
        m_received = 0;
        m_progress->SetValue(0);
        m_bytes = std::move(raw);
        m_digest = DisplayMesh::Sha256(m_bytes);
        m_name = Utf8(wxFileName(path).GetFullName());
        m_details->ChangeValue(Display(m_name + "\nSHA256 " + m_digest));
        Receive();
    }
    catch (const std::exception& error)
    {
        Status(error.what());
        Actions();
    }
}

void ArchiveRestoreDialog::Receive()
{
    Status("선택한 ZIP의 바이트를 확인하고 있습니다.");
    Request("archive.receive.begin", {{"bytes", m_bytes.size()}, {"archive_sha256", m_digest}}, false,
            [this](const Json& progress)
            {
                ValidateProgress(progress);
                m_upload = progress.at("upload_id").get<std::string>();
                m_received = progress.at("received").get<std::size_t>();
                ReceiveNext();
            });
}

void ArchiveRestoreDialog::ValidateProgress(const Json& result) const
{
    const auto received = result.at("received").get<std::size_t>();
    if (result.value("profile", "") != Receiver || result.at("archive_sha256") != m_digest ||
        result.at("bytes") != m_bytes.size() || result.at("chunk_bytes") != ChunkBytes ||
        !result.at("upload_id").is_string() || received > m_bytes.size() ||
        (received < m_bytes.size() && received % ChunkBytes != 0))
    {
        throw std::runtime_error("복원 원문의 해시 또는 전송 위치가 다릅니다.");
    }
}

void ArchiveRestoreDialog::ReceiveNext()
{
    m_progress->SetValue(static_cast<int>(100 * m_received / m_bytes.size()));
    if (m_received == m_bytes.size())
    {
        Review();
        return;
    }
    const auto count = std::min(m_bytes.size() - m_received, ChunkBytes);
    const auto encoded = wxBase64Encode(m_bytes.data() + m_received, count);
    Request("archive.receive.chunk",
            {{"upload_id", m_upload}, {"offset", m_received}, {"content_base64", Utf8(encoded)}}, false,
            [this, count](const Json& progress)
            {
                ValidateProgress(progress);
                if (progress.at("upload_id") != m_upload || progress.at("received") != m_received + count)
                {
                    throw std::runtime_error("받았다고 확인한 복원 청크 범위가 다릅니다.");
                }
                m_received += count;
                ReceiveNext();
            });
}

void ArchiveRestoreDialog::Review()
{
    Status("개정, 스냅샷, 파일과 누락 목록을 검토하고 있습니다.");
    Request("archive.receive.review", {{"upload_id", m_upload}}, false,
            [this](const Json& result)
            {
                if (result.value("profile", "") != Archive || result.at("upload_id") != m_upload ||
                    result.at("archive_sha256") != m_digest || !result.at("review_hash").is_string() ||
                    result.at("scope").at("execution_on_restore") != false)
                {
                    throw std::runtime_error("복원 검토가 받은 ZIP과 일치하지 않습니다.");
                }
                ShowReview(result);
                m_review = result;
                Status("보존 개정과 누락 목록을 확인한 뒤 복원하세요.");
            });
}

void ArchiveRestoreDialog::ShowReview(const Json& result)
{
    const auto field = [&result](const char* key)
    {
        return result.at(key).get<std::string>();
    };
    const auto row = [this](const char* label, const std::string& saved, const std::string& restore)
    {
        const auto index = m_values->InsertItem(m_values->GetItemCount(), Display(label));
        m_values->SetItem(index, 1, Display(saved));
        m_values->SetItem(index, 2, Display(restore));
    };
    m_values->DeleteAllItems();
    row("설계 개정", field("saved_revision"), field("revision_id"));
    row("프로젝트 경로", field("path"), field("path"));
    row("실행 작업", "작업과 실행 환경 제외", "자동 재실행 없음");
    row("제작 / 실측 검증", "미확립", "미확립");
    std::string summary = m_name + "\n보존 파일 " + std::to_string(result.at("files").get<int>()) + "개 / 명령 " +
                          std::to_string(result.at("commands").get<int>()) + "개 / 스냅샷 " +
                          std::to_string(result.at("snapshots").get<int>()) + "개\n미확보/제외 " +
                          std::to_string(result.at("missing_count").get<int>()) + "개 / 보존되지 않은 상위 개정 " +
                          std::to_string(result.at("unavailable_parent_count").get<int>()) + "개\nSHA256 " + m_digest;
    for (const auto& entry : result.at("omitted_preview"))
    {
        summary += "\n" + Missing(entry.at("reason")) + " / " + entry.at("reference").at("uri").get<std::string>();
    }
    if (result.at("missing_count").get<std::size_t>() > result.at("omitted_preview").size())
    {
        summary += "\n전체 누락 원문은 ZIP의 restore-index.json에서 확인하세요.";
    }
    m_details->ChangeValue(Display(summary));
}

Json ArchiveRestoreDialog::Application() const
{
    return {{"upload_id", m_upload}, {"archive_sha256", m_digest}, {"review_hash", m_review.at("review_hash")}};
}

void ArchiveRestoreDialog::Apply()
{
    const auto input = Application();
    Status("검토한 목적지에 프로젝트 복원을 접수하고 있습니다.");
    Request("archive.receive.reserve", input, true,
            [this, input](const Json& value)
            {
                if (value.at("archive_sha256") != m_digest || value.at("review_hash") != input.at("review_hash"))
                {
                    throw std::runtime_error("복원 접수 결과가 검토와 일치하지 않습니다.");
                }
                if (value.at("status") == "restored")
                {
                    Complete(value);
                    return;
                }
                if (value.at("status") != "reserved")
                {
                    throw std::runtime_error("복원할 대상의 접수 상태를 확인할 수 없습니다.");
                }
                Status("원문을 저장하고 프로젝트를 등록하고 있습니다.");
                Request("archive.receive.apply", input, true,
                        [this](const Json& restored)
                        {
                            Complete(restored);
                        });
            });
}

void ArchiveRestoreDialog::Complete(const Json& result)
{
    if (result.value("profile", "") != Archive || result.at("archive_sha256") != m_digest ||
        result.at("status") != "restored" || result.at("project_id") != m_review.at("project_id") ||
        result.at("revision_id") != m_review.at("revision_id") || result.at("path") != m_review.at("path"))
    {
        throw std::runtime_error("복원한 프로젝트의 신원 또는 개정이 검토와 다릅니다.");
    }
    m_completed = true;
    m_uncertain = false;
    m_openPath = result.at("path").get<std::string>();
    Drop();
    m_bytes.clear();
    Status("프로젝트를 등록했습니다. 복원 프로젝트 열기에서 작업을 이어갈 수 있습니다.");
}

void ArchiveRestoreDialog::Check()
{
    Request("archive.receive.status", {{"archive_sha256", m_digest}}, false,
            [this](const Json& result)
            {
                if (result.value("profile", "") != Receiver || result.at("archive_sha256") != m_digest ||
                    !result.value("authoritative", false))
                {
                    throw std::runtime_error("받은 복원 상태가 현재 파일과 다릅니다.");
                }
                const auto state = result.at("status").get<std::string>();
                if (state == "restored")
                {
                    Complete(result.at("result"));
                }
                else if (state == "reserved" || state == "not_registered")
                {
                    m_uncertain = false;
                    Status(state == "reserved"
                               ? "같은 ZIP의 준비 기록이 있습니다. 검토한 원문으로 복원을 이어가세요."
                               : "이 ZIP을 등록한 결과가 없습니다. 검토를 확인한 뒤 복원할 수 있습니다.");
                }
                else
                {
                    throw std::runtime_error("복원 상태를 확인할 수 없습니다.");
                }
            });
}

void ArchiveRestoreDialog::Request(const std::string& method, const Json& input, bool mutation,
                                   std::function<void(const Json&)> complete)
{
    m_busy = true;
    m_applying = mutation;
    Actions();
    const wxWeakRef<ArchiveRestoreDialog> weak(this);
    const auto finish = [weak, mutation, complete = std::move(complete)](const Json& value, bool success)
    {
        auto* self = weak.get();
        if (!self || !self->m_live)
        {
            return;
        }
        self->m_busy = false;
        self->m_applying = false;
        if (self->m_leaveAfterResponse)
        {
            if (success && value.value("profile", "") == Receiver &&
                value.value("upload_id", Json(nullptr)).is_string())
            {
                self->m_upload = value.at("upload_id").get<std::string>();
            }
            self->CloseDialog(wxID_CANCEL);
            return;
        }
        try
        {
            if (success)
            {
                complete(value);
            }
            else
            {
                throw std::runtime_error(DiagnosticMessage(value));
            }
        }
        catch (const std::exception& error)
        {
            self->m_uncertain = self->m_uncertain || mutation;
            self->Status(error.what());
        }
        self->Actions();
    };
    m_gateway(
        method, input, mutation,
        [finish](const Json& value)
        {
            finish(value, true);
        },
        [finish](const Json& value)
        {
            finish(value, false);
        });
}

void ArchiveRestoreDialog::Drop()
{
    if (!m_upload.empty())
    {
        m_gateway(
            "archive.receive.drop", {{"upload_id", m_upload}}, false,
            [](const Json&)
            {
            },
            [](const Json&)
            {
            });
        m_upload.clear();
    }
}

void ArchiveRestoreDialog::CloseDialog(int result)
{
    if (m_applying)
    {
        return;
    }
    if (m_busy)
    {
        m_leaveAfterResponse = true;
        Status("현재 바이트 확인이 끝나면 닫습니다.");
        return;
    }
    m_live = false;
    Drop();
    EndModal(result);
}
