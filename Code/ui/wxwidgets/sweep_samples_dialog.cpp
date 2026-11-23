/** @file @brief 공정 시료의 CSV 원문과 표집 조건을 읽기 전용 비교에 전달한다. */
#include "studio_internal.h"
#include "sweep_samples_dialog.h"
#include "studio_theme.h"
#include "file_delivery.h"
#include <wx/file.h>
#include <wx/filedlg.h>

void SelectSweepSamples(wxWindow* parent, const wxString& workspace, const Json& axes,
                        const Json& labels, Json& options)
{
    wxDialog dialog(parent, wxID_ANY, Display("공정 표본 비교"));
    StudioTheme::ApplyTypography(dialog);
    const int gap = dialog.FromDIP(10);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* guide = new wxStaticText(&dialog, wxID_ANY, Display(
        "시료 하나를 한 행에 입력하세요. observed 열에는 실제 검사 결과 pass 또는 fail을 입력하거나 비워 둘 수 있습니다."));
    guide->Wrap(dialog.FromDIP(455));
    layout->Add(guide, 0, wxEXPAND | wxALL, gap);
    std::string header = "sample_id,observed";
    for (const auto& axis : axes)
    {
        const auto id = axis.at("id").get<std::string>();
        const auto key = axis.at("kind").get<std::string>() + ":" + id;
        const auto unit = axis.at("unit").get<std::string>();
        layout->Add(new wxStaticText(&dialog, wxID_ANY,
                    Display(labels.value(key, id) + " (" + unit + ")  " + id)), 0, wxLEFT | wxRIGHT, gap);
        header += "," + id + ":" + unit;
    }
    auto* buttons = new wxBoxSizer(wxHORIZONTAL);
    auto* sample = new wxButton(&dialog, wxID_ANY, Display("CSV 양식 저장"));
    auto* select = new wxButton(&dialog, wxID_ANY, Display("표본 CSV 열기"));
    auto* clear = new wxButton(&dialog, wxID_ANY, Display("선택 해제"));
    buttons->Add(sample);
    buttons->Add(select, 0, wxLEFT, gap);
    buttons->Add(clear, 0, wxLEFT, gap);
    layout->Add(buttons, 0, wxALL, gap);
    const Json initial = options.is_object() ? options : Json::object();
    std::string text = initial.value("text", std::string());
    auto* source = new wxTextCtrl(&dialog, wxID_ANY, Display(initial.value("source", std::string())));
    source->SetHint(Display("자료 출처 또는 로트 이름"));
    source->SetMaxLength(120);
    layout->Add(source, 0, wxEXPAND | wxLEFT | wxRIGHT, gap);
    auto* random = new wxCheckBox(&dialog, wxID_ANY, Display("독립 무작위 표집으로 수집한 시료"));
    random->SetValue(initial.value("independent_random_sample", false));
    layout->Add(random, 0, wxALL, gap);
    auto* status = new wxStaticText(&dialog, wxID_ANY, text.empty() ? Display("선택한 파일 없음") : Display("표본 선택됨"));
    layout->Add(status, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, gap);
    layout->Add(dialog.CreateSeparatedButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, gap);
    sample->Bind(wxEVT_BUTTON, [&](wxCommandEvent&)
    {
        wxFileDialog file(&dialog, Display("공정 표본 양식 저장"), {}, "process-samples.csv",
                          "CSV (*.csv)|*.csv", wxFD_SAVE);
        if (file.ShowModal() == wxID_OK)
        {
            try
            {
                WriteExternalExportFile(file.GetPath(), workspace, header + "\r\n");
                status->SetLabel(Display("현재 연구의 변수와 단위로 양식을 저장했습니다."));
            }
            catch (const std::exception& error)
            {
                status->SetLabel(Display(error.what()));
            }
        }
    });
    select->Bind(wxEVT_BUTTON, [&](wxCommandEvent&)
    {
        wxFileDialog file(&dialog, Display("공정 표본 열기"), {}, {}, "CSV (*.csv)|*.csv", wxFD_OPEN | wxFD_FILE_MUST_EXIST);
        if (file.ShowModal() != wxID_OK)
        {
            return;
        }
        wxFile input(file.GetPath(), wxFile::read);
        const auto length = input.IsOpened() ? input.Length() : -1;
        if (length <= 0 || length > 262144)
        {
            status->SetLabel(Display("1~262144바이트의 UTF-8 CSV를 선택하세요."));
            return;
        }
        std::string bytes(static_cast<std::size_t>(length), '\0');
        if (input.Read(bytes.data(), bytes.size()) != length || bytes.find('\0') != std::string::npos ||
            wxString::FromUTF8(bytes.data(), bytes.size()).empty())
        {
            status->SetLabel(Display("UTF-8 CSV 원문을 읽지 못했습니다."));
            return;
        }
        text = std::move(bytes);
        source->SetValue(wxFileName(file.GetPath()).GetFullName());
        status->SetLabel(Display("표본 CSV를 읽었습니다."));
    });
    clear->Bind(wxEVT_BUTTON, [&](wxCommandEvent&)
    {
        text.clear();
        source->Clear();
        random->SetValue(false);
        status->SetLabel(Display("선택한 파일 없음"));
    });
    dialog.Bind(wxEVT_BUTTON, [&](wxCommandEvent&)
    {
        if (!text.empty() && source->GetValue().Strip(wxString::both).empty())
        {
            status->SetLabel(Display("표본의 출처를 입력하세요."));
            source->SetFocus();
            return;
        }
        options = text.empty() ? Json(nullptr) : Json{{"text", text}, {"source", Utf8(source->GetValue().Strip(wxString::both))},
                                                       {"independent_random_sample", random->GetValue()}};
        dialog.EndModal(wxID_OK);
    }, wxID_OK);
    dialog.SetSizerAndFit(layout);
    dialog.CentreOnParent();
    dialog.ShowModal();
}
