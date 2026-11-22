/** @file @brief 기존 서비스가 계산한 수렴 연구 보고서를 표시한다. */
#include "study_report_dialog.h"
#include "study_report_model.h"
#include "studio_theme.h"

#include <wx/wx.h>
#include <wx/filedlg.h>
#include <wx/listctrl.h>
#include <nlohmann/json.hpp>
#include <filesystem>
#include <fstream>
#include <stdexcept>

namespace
{
/** @brief UTF-8 원문을 위젯에 전달한다. */
wxString Text(const std::string& value)
{
    return wxString::FromUTF8(value);
}
}

void ShowStudyReport(wxWindow* parent)
{
    wxFileDialog picker(parent, Text("수렴 연구 보고서 열기"), {}, {}, "JSON (*.json)|*.json",
                        wxFD_OPEN | wxFD_FILE_MUST_EXIST);
    if (picker.ShowModal() != wxID_OK)
    {
        return;
    }
    ShowStudyReportFile(parent, picker.GetPath());
}

/** @brief 고른 로컬 보고서를 읽고 기록된 수치와 판정을 같은 화면에서 보여준다. */
void ShowStudyReportFile(wxWindow* parent, const wxString& filename)
{
    try
    {
        const std::filesystem::path path(filename.ToStdWstring());
        if (std::filesystem::file_size(path) > 2 * 1024 * 1024)
        {
            throw std::runtime_error("보고서의 2 MiB 표시 상한을 초과했습니다.");
        }
        std::ifstream stream(path);
        const auto report = nlohmann::json::parse(stream);
        const auto view = Studio::PresentStudyReport(report);
        wxDialog dialog(parent, wxID_ANY, Text("수렴 연구와 결과 비교"), wxDefaultPosition,
                        parent->FromDIP(wxSize(960, 640)), wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
        StudioTheme::ApplyTypography(dialog);
        StudioTheme::BindSurface(dialog);
        auto* sizer = new wxBoxSizer(wxVERTICAL);
        auto* heading = new wxStaticText(&dialog, wxID_ANY, wxString(path.filename().wstring()));
        heading->Wrap(dialog.FromDIP(880));
        StudioTheme::Title(*heading);
        sizer->Add(heading, 0, wxEXPAND | wxALL, dialog.FromDIP(StudioTheme::PanelPadding));
        auto* notice = new wxStaticText(&dialog, wxID_ANY,
                                        Text("선택한 파일에 기록된 판정입니다. 원본 결과 검증과 재판정은 연구 도구에서 "
                                             "수행합니다. 제조/실측 합격을 뜻하지 않습니다."));
        notice->Wrap(dialog.FromDIP(900));
        sizer->Add(notice, 0, wxEXPAND | wxALL, 10);
        StudioTheme::BindSecondary(*notice);
        auto* table = new wxListCtrl(&dialog, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT);
        table->SetName("study.report.rows");
        StudioTheme::Table(*table);
        int column = 0;
        for (const auto& label : view.columns)
        {
            table->InsertColumn(column++, Text(label), wxLIST_FORMAT_LEFT, dialog.FromDIP(145));
        }
        for (const auto& values : view.rows)
        {
            const long row = table->InsertItem(table->GetItemCount(), Text(values.front()));
            for (std::size_t index = 1; index < values.size(); ++index)
            {
                table->SetItem(row, static_cast<int>(index), Text(values[index]));
            }
        }
        table->SetColumnWidth(0, dialog.FromDIP(155));
        table->SetColumnWidth(1, dialog.FromDIP(100));
        table->SetColumnWidth(2, dialog.FromDIP(100));
        table->SetColumnWidth(3, dialog.FromDIP(120));
        table->SetColumnWidth(4, dialog.FromDIP(100));
        table->SetColumnWidth(5, dialog.FromDIP(235));
        sizer->Add(table, 1, wxEXPAND | wxLEFT | wxRIGHT, 10);
        auto* assessment = new wxTextCtrl(&dialog, wxID_ANY, Text(view.summary), wxDefaultPosition,
                                          dialog.FromDIP(wxSize(-1, 220)), wxTE_MULTILINE | wxTE_READONLY | wxHSCROLL);
        assessment->SetName("study.report.assessment");
        sizer->Add(assessment, 1, wxEXPAND | wxALL, dialog.FromDIP(StudioTheme::PanelPadding));
        auto* close = new wxButton(&dialog, wxID_CANCEL, Text("닫기"));
        StudioTheme::Button(*close);
        sizer->Add(close, 0, wxALIGN_RIGHT | wxLEFT | wxRIGHT | wxBOTTOM,
                   dialog.FromDIP(StudioTheme::PanelPadding));
        dialog.SetSizer(sizer);
        dialog.CentreOnParent();
        dialog.ShowModal();
    }
    catch (const std::exception& error)
    {
        wxMessageBox(Text(error.what()), Text("수렴 보고서 읽기 실패"), wxOK | wxICON_ERROR, parent);
    }
}
