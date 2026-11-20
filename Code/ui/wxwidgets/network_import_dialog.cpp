/** @file @brief 복소 자료 가져오기 화면의 원문 읽기와 비동기 검토 수명을 관리한다. */
#include "network_import_dialog.h"
#include "network_chart.h"
#include "measurement_record_form.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/base64.h>
#include <wx/button.h>
#include <wx/checkbox.h>
#include <wx/choice.h>
#include <wx/file.h>
#include <wx/filedlg.h>
#include <wx/filename.h>
#include <wx/grid.h>
#include <wx/listctrl.h>
#include <wx/notebook.h>
#include <wx/scrolwin.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <algorithm>
#include <stdexcept>
#include <vector>

NetworkImportDialog::NetworkImportDialog(wxWindow* parent, const Json& context, DialogGateway gateway,
                                         std::shared_ptr<MeasurementRecovery> recovery)
    : ProjectSetupDialog(parent, "복소 자료 가져오기", context, gateway), m_context(context), m_gateway(gateway),
      m_recovery(recovery ? std::move(recovery) : std::make_shared<MeasurementRecovery>())
{
    SetName("network.import.dialog");
    StudioTheme::ApplyTypography(*this);
    const int pad = FromDIP(StudioTheme::PanelPadding);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* heading = new wxStaticText(this, wxID_ANY, Display("원문 파일과 해석 조건을 보존합니다."));
    StudioTheme::Heading(*heading);
    layout->Add(heading, 0, wxEXPAND | wxALL, pad);
    m_tabs = new wxNotebook(this, wxID_ANY);
    m_tabs->SetName("network.import.tabs");
    auto* file = new wxPanel(m_tabs);
    auto* mapping = new wxScrolledWindow(m_tabs, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL);
    mapping->SetScrollRate(0, FromDIP(12));
    auto* review = new wxScrolledWindow(m_tabs, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL);
    review->SetScrollRate(0, FromDIP(12));
    BuildFilePage(file);
    BuildMappingPage(mapping);
    BuildReviewPage(review);
    auto* measurement = new wxPanel(m_tabs);
    BuildMeasurementPage(measurement, gateway);
    m_tabs->AddPage(file, Display("파일과 형식"));
    m_tabs->AddPage(mapping, Display("열 / 포트 대응"));
    m_tabs->AddPage(measurement, Display("시료와 교정"));
    m_tabs->AddPage(review, Display("가져오기 검토"));
    layout->Add(m_tabs, 1, wxEXPAND | wxLEFT | wxRIGHT, pad);
    m_status = new wxStaticText(this, wxID_ANY, wxEmptyString);
    m_status->SetName("network.import.status");
    layout->Add(m_status, 0, wxEXPAND | wxALL, pad);
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    actions->AddStretchSpacer();
    auto* close = new wxButton(this, wxID_CANCEL, Display("취소"));
    m_preview = new wxButton(this, wxID_ANY, Display("파일 / 조건 검토"));
    m_preview->SetName("network.import.preview");
    m_apply = new wxButton(this, wxID_APPLY, Display("가져오기"));
    m_apply->SetName("network.import.apply");
    m_recoverMeasurement = new wxButton(this, wxID_ANY, Display("이전 가져오기 결과 확인"));
    for (auto* button : {close, m_preview, m_apply, m_recoverMeasurement})
    {
        StudioTheme::Button(*button, button == m_apply);
        actions->Add(button, 0, wxLEFT, FromDIP(8));
    }
    layout->Add(actions, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, pad);
    SetSizer(layout);
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
    m_recoverMeasurement->Bind(wxEVT_BUTTON,
                               [this](wxCommandEvent&)
                               {
                                   RecoverMeasurement();
                               });
    m_loading = false;
    SetStatus("Touchstone / 명시 CSV / TraceWave 정규 HDF5를 지원합니다. 원문 상한은 512 KiB입니다.");
    UpdateActions();
    Layout();
}

std::string NetworkImportDialog::Format() const
{
    const std::array<const char*, 3> formats = {"touchstone", "csv", "hdf5"};
    return formats.at(static_cast<std::size_t>(std::max(0, m_format->GetSelection())));
}

void NetworkImportDialog::Browse()
{
    wxFileDialog chooser(
        this, Display("가져올 복소 자료"), wxEmptyString, wxEmptyString,
        Display(
            "지원 자료 (*.s1p;*.s2p;*.ts;*.csv;*.h5;*.hdf5)|*.s1p;*.s2p;*.ts;*.csv;*.h5;*.hdf5|모든 파일 (*.*)|*.*"),
        wxFD_OPEN | wxFD_FILE_MUST_EXIST);
    if (chooser.ShowModal() == wxID_OK)
    {
        LoadFile(chooser.GetPath());
    }
}

bool NetworkImportDialog::LoadFile(const wxString& path)
{
    if (!Editable() || m_pending)
    {
        return false;
    }
    constexpr std::size_t Maximum = 512U * 1024U;
    const auto limit = std::min(Maximum, m_context.value("limits", Json::object()).value("source_bytes", Maximum));
    wxFile file(path, wxFile::read);
    const auto size = file.IsOpened() ? file.Length() : wxInvalidOffset;
    if (size <= 0 || size > static_cast<wxFileOffset>(limit))
    {
        if (!m_encoded.empty())
        {
            ChangeInputs();
        }
        SetStatus("읽을 수 있는 512 KiB 이하의 파일을 선택하세요. 빈 파일은 가져올 수 없습니다.");
        return false;
    }
    std::vector<unsigned char> bytes(static_cast<std::size_t>(size));
    if (file.Read(bytes.data(), bytes.size()) != size || file.Length() != size)
    {
        if (!m_encoded.empty())
        {
            ChangeInputs();
        }
        SetStatus("읽는 도중 파일이 바뀌었습니다. 다시 선택하세요.");
        return false;
    }
    const wxFileName name(path);
    const wxString extension = name.GetExt().Lower();
    m_loading = true;
    m_fileName = Utf8(name.GetFullName());
    m_encoded = Utf8(wxBase64Encode(bytes.data(), bytes.size()));
    m_path->ChangeValue(path);
    if (m_name->IsEmpty())
    {
        m_name->ChangeValue(name.GetName());
    }
    m_format->SetSelection(extension == "csv" ? 1 : ((extension == "h5" || extension == "hdf5") ? 2 : 0));
    if (Format() == "hdf5")
    {
        m_raw->ChangeValue(
            Display("이진 HDF5 파일입니다. 서비스 검토에서 정규 프로필과 배열/메타데이터의 일치를 확인합니다."));
    }
    else
    {
        const std::size_t length = std::min<std::size_t>(bytes.size(), 16384);
        std::string preview(reinterpret_cast<const char*>(bytes.data()), length);
        if (length < bytes.size())
        {
            const auto line = preview.find_last_of("\r\n");
            preview.resize(line == std::string::npos ? 0 : line);
        }
        const wxString display = wxString::FromUTF8(preview.data(), preview.size());
        m_raw->ChangeValue(display.empty() && !preview.empty()
                               ? Display("UTF-8 표시가 불가능합니다. 서비스가 원문 인코딩을 검사합니다.")
                               : display);
        m_raw->AppendText(Display("\n\n[읽기 전용 표시: 최대 16 KiB. 전체 원문은 그대로 보존됩니다.]"));
    }
    m_loading = false;
    ChangeInputs(true);
    m_tabs->SetSelection(FilePage);
    SetStatus("파일을 읽었습니다. CSV는 열 대응을 확인하고, 파일 / 조건 검토를 실행하세요.");
    return true;
}

void NetworkImportDialog::ResetConditions()
{
    m_sourceDescriptor = nullptr;
    m_wave->SetSelection(0);
    m_phasor->SetSelection(0);
    for (auto& port : m_ports)
    {
        port.project->SetSelection(0);
        port.mode->SetSelection(0);
        port.orientation->SetSelection(0);
        port.planeChanged->SetValue(false);
        port.plane->ChangeValue(wxEmptyString);
    }
}

void NetworkImportDialog::ChangeInputs(bool sourceChanged)
{
    if (m_loading)
    {
        return;
    }
    InvalidateRead();
    m_review = nullptr;
    m_reviewInput = nullptr;
    m_dirty = true;
    if (sourceChanged)
    {
        ResetConditions();
    }
    m_samples->DeleteAllItems();
    m_chart->Clear();
    m_summary->ChangeValue(Display("입력이 바뀌었습니다. 서비스에서 파일과 조건을 다시 검토하세요."));
    SetStatus("미적용 입력이 있습니다. 다시 검토한 후보만 가져올 수 있습니다.");
    UpdateActions();
}

bool NetworkImportDialog::HasDraft() const
{
    return m_dirty;
}

void NetworkImportDialog::UpdateActions()
{
    if (!m_preview)
    {
        return;
    }
    const bool available = Editable() && !m_pending && !MeasurementUncertain() && !m_measurementForm->Pending();
    m_tabs->Enable(available);
    m_browse->Enable(available);
    m_csv->Enable(available && Format() == "csv");
    const std::size_t count = m_sourceDescriptor.is_null() ? 0 : m_sourceDescriptor.at("port_ids").size();
    m_conditions->Enable(available && count > 0);
    for (std::size_t index = 0; index < m_ports.size(); ++index)
    {
        m_ports[index].panel->Enable(available && index < count);
        m_ports[index].plane->Enable(available && index < count && m_ports[index].planeChanged->GetValue());
        m_z0[index]->Enable(available && Format() == "csv" && m_z0Known->GetValue() &&
                            index < static_cast<std::size_t>(m_portCount->GetSelection() + 1));
    }
    m_preview->Enable(available && !m_encoded.empty());
    m_apply->Enable(available && !m_review.is_null() && m_review.value("can_apply", false));
    m_measurementEnabled->Enable(available && m_context.value("measurement", Json(nullptr)).is_object());
    m_measurementForm->Enable(available && MeasurementSelected());
    m_recoverMeasurement->Show(MeasurementUncertain());
    m_recoverMeasurement->Enable(MeasurementUncertain() && !m_pending && !m_recovering && !m_mutating);
}

void NetworkImportDialog::ShowRequestFailure(const Json& error)
{
    m_review = nullptr;
    m_reviewInput = nullptr;
    m_samples->DeleteAllItems();
    m_chart->Clear();
    m_summary->ChangeValue(Display("검토 또는 적용 요청이 거절되었습니다. 입력과 원문은 이 창에 유지됩니다."));
    ProjectSetupDialog::ShowRequestFailure(error);
}
