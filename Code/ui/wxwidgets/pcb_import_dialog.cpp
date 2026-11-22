/** @file @brief 원문 전송과 현재 개정의 명시 대응을 네 탭으로 구분한다. */
#include "pcb_import_dialog.h"
#include "design_canvas.h"
#include "output_model.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/checkbox.h>
#include <wx/checklst.h>
#include <wx/choice.h>
#include <wx/listctrl.h>
#include <wx/scrolwin.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <wx/weakref.h>
#include <wx/wrapsizer.h>
#include <array>

PcbImportDialog::PcbImportDialog(wxWindow* parent, const Json& context, DialogGateway gateway,
                                 std::shared_ptr<PcbImportRecovery> recovery)
    : ProjectSetupDialog(parent, "PCB / CAM 원문 가져오기", context, gateway), m_context(context),
      m_gateway(std::move(gateway)), m_recovery(std::move(recovery)), m_poll(this)
{
    SetName("pcb.import.dialog");
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* title = new wxStaticText(this, wxID_ANY, Display("원문 보존과 변환 검토"));
    StudioTheme::Heading(*title);
    layout->Add(title, 0, wxALL, FromDIP(12));
    m_tabs = new StudioNotebook(this);
    for (const auto& label : {"파일 / 전송", "층 / 넷 대응", "후보 / 손실 검토", "출처 / 원문"})
    {
        auto* page = new wxScrolledWindow(m_tabs, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL);
        page->SetScrollRate(0, FromDIP(16));
        StudioTheme::BindSurface(*page);
        m_tabs->AddPage(page, Display(label));
    }
    BuildSource(m_tabs->GetPage(0));
    BuildMapping(m_tabs->GetPage(1));
    BuildReview(m_tabs->GetPage(2));
    BuildOriginal(m_tabs->GetPage(3));
    layout->Add(m_tabs, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    m_status = new wxStaticText(this, wxID_ANY, wxEmptyString);
    layout->Add(m_status, 0, wxEXPAND | wxALL, FromDIP(12));
    auto* actions = new wxWrapSizer(wxHORIZONTAL);
    m_recover = new wxButton(this, wxID_ANY, Display("이전 요청 확인"));
    m_preview = new wxButton(this, wxID_ANY, Display("변환 후보 검토"));
    m_apply = new wxButton(this, wxID_APPLY, Display("검토한 후보 적용"));
    auto* close = new wxButton(this, wxID_CANCEL, Display("닫기"));
    for (auto* button : {m_recover, m_preview, m_apply, close})
    {
        StudioTheme::Button(*button, button == m_apply);
        actions->Add(button, 0, wxRIGHT | wxBOTTOM, FromDIP(8));
    }
    layout->Add(actions, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    SetSizer(layout);
    m_recover->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        Recover();
                    });
    m_preview->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        Preview();
                    });
    m_apply->Bind(wxEVT_BUTTON,
                  [this](wxCommandEvent&)
                  {
                      Apply();
                  });
    Bind(wxEVT_TIMER, &PcbImportDialog::Poll, this);
    if (Uncertain())
    {
        m_disconnected = true;
        SetStatus("이전 요청의 결과를 먼저 확인하세요. 같은 원문을 새 요청으로 중복 적용하지 않습니다.");
    }
    else
    {
        SetStatus("파일을 선택해 원문을 전송하거나 보존된 전송을 여세요. 실제 읽기 완료 후 층과 넷을 명시합니다.");
        if (m_recovery->checkpoint.is_object())
        {
            wxWeakRef<PcbImportDialog> weak(this);
            CallAfter(
                [weak]()
                {
                    if (weak && !weak->m_closed)
                    {
                        weak->Recover();
                    }
                });
        }
    }
    UpdateActions();
}

PcbImportDialog::~PcbImportDialog()
{
    m_poll.Stop();
}

bool PcbImportDialog::Uncertain() const
{
    return m_recovery->checkpoint.is_object() && !m_recovery->checkpoint.value("confirmed", false);
}

bool PcbImportDialog::HasDraft() const
{
    return m_dirty && !m_closed;
}

std::string PcbImportDialog::Format() const
{
    return m_formats.at(static_cast<std::size_t>(std::max(0, m_format->GetSelection())));
}

bool PcbImportDialog::VendorFormat() const
{
    return Format().rfind("vendor_", 0) == 0;
}

void PcbImportDialog::DescribeFormat()
{
    std::string detail = Format() == "ipc2581_revc"
        ? "압축에서 꺼낸 IPC-2581 Rev C XML을 선택합니다. 층·넷·홀·부품을 검토하고 지원하는 내부 절삭을 반영합니다."
        : "KiCad, Gerber 또는 Excellon 원본을 선택하세요.";
    if (Format() == "odbpp_zip")
    {
        detail = "ODB++ ZIP 하나를 선택합니다. 보드 정의와 층을 확인하고 지원하는 내부 절삭을 반영합니다.";
    }
    for (const auto& pattern : m_context.value("vendor_patterns", Json::array()))
    {
        if (pattern.at("format") == Format())
        {
            detail = pattern.at("description").get<std::string>() + "\n" +
                     pattern.at("source_url").get<std::string>();
            break;
        }
    }
    m_formatDetail->ChangeValue(Display(detail));
}

void PcbImportDialog::Changed()
{
    if (m_loading || m_mutating || Uncertain())
    {
        return;
    }
    InvalidateRead();
    m_dirty = true;
    m_review = nullptr;
    m_reviewInput = nullptr;
    m_changes->DeleteAllItems();
    m_issues->ChangeValue(Display("입력이 바뀌었습니다. 적용 전에 변환 후보를 다시 검토하세요."));
    ShowScene();
    UpdateActions();
}

void PcbImportDialog::UpdateActions()
{
    if (!m_apply)
    {
        return;
    }
    const bool editable = Editable() && !m_pending && !m_recovering && !Uncertain();
    const bool parsed = m_uploadState.is_object() && m_uploadState.value("parsed", Json(nullptr)).is_object();
    const auto mappingSources = m_uploadState.is_object() ? m_uploadState.value("mapping_sources", Json()) : Json();
    const auto format = Format();
    const bool profileOnly = format == "ipc2581_revc" || format == "odbpp_zip";
    const bool canMap = parsed && (!profileOnly || (mappingSources.is_object() &&
        mappingSources.value("manufacturing_profile_available", mappingSources.value("ipc_profile_available", false))));
    const bool applied = m_uploadState.is_object() && !m_uploadState.value("applied_revision", Json(nullptr)).is_null();
    const bool runtime = m_context.value("runtime_configured", false);
    const Json state = m_uploadState.is_object() ? m_uploadState : Json::object();
    m_browse->Enable(editable && !m_uploading);
    m_format->Enable(editable && m_upload.empty());
    m_uploadChoice->Enable(editable && !m_uploading);
    m_uploadButton->Enable(editable && !m_files.empty() && !parsed && !applied && !m_uploading &&
                           (!m_uploadState.is_object() || m_uploadState.value("status", "") == "uploading"));
    bool complete = m_uploadState.is_object() && !m_uploadState.value("files", Json::array()).empty();
    for (const auto& file : state.value("files", Json::array()))
    {
        complete = complete && file.value("bytes", 0) == file.value("received", -1);
    }
    m_parseButton->Enable(editable && runtime && complete && state.value("parse_job_id", Json(nullptr)).is_null() &&
                          state.value("status", "") == "uploading");
    m_mappingPage->Enable(editable && canMap && !applied);
    m_losses->Enable(editable && canMap && !applied);
    m_reason->Enable(editable && canMap && !applied);
    m_preview->Enable(editable && canMap && !applied && m_boardConfirmed->GetValue());
    m_apply->Enable(editable && m_review.is_object() && m_review.value("can_apply", false) &&
                    !m_review.value("review_hash", Json(nullptr)).is_null());
    m_recover->Enable(!m_mutating && !m_recovering && m_recovery->checkpoint.is_object());
    if (auto* close = FindWindow(wxID_CANCEL))
    {
        close->Enable(!m_mutating);
    }
}

void PcbImportDialog::ShowRequestFailure(const Json& error)
{
    m_uploading = false;
    m_issues->ChangeValue(Display(DiagnosticMessage(error)));
    SetStatus(DiagnosticMessage(error));
}

void PcbImportDialog::ShowScene()
{
    const auto scene =
        m_review.is_object()
            ? m_review.value(m_sceneChoice->GetSelection() == 1 ? "before_scene" : "scene", Json(nullptr))
            : Json(nullptr);
    if (scene.is_object())
    {
        m_canvas->SetScene(scene);
        m_canvas->FitView();
        wxWeakRef<PcbImportDialog> weak(this);
        CallAfter(
            [weak]()
            {
                if (weak && !weak->m_closed)
                {
                    weak->m_canvas->FitView();
                }
            });
    }
    else
    {
        m_canvas->SetScene(
            {{"board", nullptr}, {"layers", Json::array()}, {"shapes", Json::array()}, {"omissions", Json::array()}});
    }
}
