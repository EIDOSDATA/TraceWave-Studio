/** @file @brief 기존 서비스가 계산한 수렴 연구 보고서를 표시한다. */
#include "study_report_dialog.h"

#include <wx/wx.h>
#include <wx/filedlg.h>
#include <wx/listctrl.h>
#include <nlohmann/json.hpp>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <sstream>

namespace
{
/** @brief UTF-8 원문을 위젯에 전달한다. */
wxString Text(const std::string& value)
{
    return wxString::FromUTF8(value);
}

/** @brief 판정기의 상태만 번역하고 새로운 수렴 판정을 계산하지 않는다. */
std::string Status(const std::string& value)
{
    if (value == "established" || value == "passed")
    {
        return "충족";
    }
    if (value == "failed")
    {
        return "미충족";
    }
    return "미확립";
}

/** @brief 비교 축을 사용자가 읽을 수 있는 이름으로 표시한다. */
std::string Axis(const std::string& value)
{
    if (value == "mesh")
    {
        return "격자";
    }
    if (value == "boundary")
    {
        return "경계 거리";
    }
    return "시간 종료";
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
    try
    {
        const std::filesystem::path path(picker.GetPath().ToStdWstring());
        if (std::filesystem::file_size(path) > 2 * 1024 * 1024)
        {
            throw std::runtime_error("보고서의 2 MiB 표시 상한을 초과했습니다.");
        }
        std::ifstream stream(path);
        const auto report = nlohmann::json::parse(stream);
        if (report.at("schema") != "rfad.ifa-convergence-run/0.1" || !report.at("cases").is_array() ||
            report.at("cases").size() > 18 || report.at("status") != "completed")
        {
            throw std::runtime_error("완료된 수렴 연구 보고서가 필요합니다.");
        }
        wxDialog dialog(parent, wxID_ANY, Text("수렴 연구와 결과 비교"), wxDefaultPosition,
                        parent->FromDIP(wxSize(960, 640)), wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
        auto* sizer = new wxBoxSizer(wxVERTICAL);
        auto* notice = new wxStaticText(&dialog, wxID_ANY,
                                        Text("선택한 파일에 기록된 판정입니다. 원본 결과 검증과 재판정은 연구 도구에서 "
                                             "수행합니다. 제조/실측 합격을 뜻하지 않습니다."));
        notice->Wrap(dialog.FromDIP(900));
        sizer->Add(notice, 0, wxEXPAND | wxALL, 10);
        auto* table = new wxListCtrl(&dialog, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT);
        int column = 0;
        for (const auto* label : {"사례", "비교 축", "격자 mm", "공기 여백 mm", "종료 기준", "주파수 GHz"})
        {
            table->InsertColumn(column++, Text(label), wxLIST_FORMAT_LEFT, dialog.FromDIP(145));
        }
        for (const auto& entry : report.at("cases"))
        {
            const auto& settings = entry.at("settings");
            const long row = table->InsertItem(table->GetItemCount(), Text(entry.at("label").get<std::string>()));
            table->SetItem(row, 1, Text(Axis(entry.at("axis").get<std::string>())));
            table->SetItem(row, 2, Text(settings.at("grid_mm").dump()));
            table->SetItem(row, 3, Text(settings.at("air_padding_mm").dump()));
            table->SetItem(row, 4, Text(settings.at("end_criterion").dump()));
            const auto& frequency = settings.at("frequency_hz");
            table->SetItem(row, 5,
                           wxString::Format("%.4f .. %.4f (%d)", frequency.at("start").get<double>() / 1e9,
                                            frequency.at("stop").get<double>() / 1e9,
                                            frequency.at("count").get<int>()));
        }
        table->SetColumnWidth(0, dialog.FromDIP(155));
        table->SetColumnWidth(1, dialog.FromDIP(100));
        table->SetColumnWidth(2, dialog.FromDIP(100));
        table->SetColumnWidth(3, dialog.FromDIP(120));
        table->SetColumnWidth(4, dialog.FromDIP(100));
        table->SetColumnWidth(5, dialog.FromDIP(235));
        sizer->Add(table, 1, wxEXPAND | wxLEFT | wxRIGHT, 10);
        const auto& stability = report.at("assessment").at("numerical_stability");
        std::ostringstream summary;
        summary << "전체 수치 안정성: " << Status(stability.at("status").get<std::string>()) << "\n\n";
        for (const auto* axis : {"mesh", "boundary", "termination"})
        {
            const auto& result = stability.at("axes").at(axis);
            summary << Axis(axis) << ": " << Status(result.at("status").get<std::string>()) << '\n';
            if (result.contains("final_pair") && result.at("final_pair").is_object())
            {
                const auto& pair = result.at("final_pair");
                summary << "  마지막 복소 S11 최대 변화: " << pair.at("metrics").at("max_s11_complex_delta")
                        << " (기준 " << pair.at("acceptance_profile").at("max_s11_complex_delta") << ")\n";
                summary << "  공진 위치 비교: " << Status(pair.at("resonance").at("status").get<std::string>()) << '\n';
            }
            summary << '\n';
        }
        summary << "공진 미확립은 내부 공진 표본/대응 여부를 연구 결과에서 확인해야 합니다.\n"
                   "전체 대역 정합과 제조/실측 정확도는 별도 검증 항목입니다.";
        auto* assessment = new wxTextCtrl(&dialog, wxID_ANY, Text(summary.str()), wxDefaultPosition,
                                          dialog.FromDIP(wxSize(-1, 220)), wxTE_MULTILINE | wxTE_READONLY | wxHSCROLL);
        sizer->Add(assessment, 1, wxEXPAND | wxALL, 10);
        sizer->Add(dialog.CreateButtonSizer(wxOK), 0, wxALIGN_RIGHT | wxALL, 10);
        dialog.SetSizer(sizer);
        dialog.CentreOnParent();
        dialog.ShowModal();
    }
    catch (const std::exception& error)
    {
        wxMessageBox(Text(error.what()), Text("수렴 보고서 읽기 실패"), wxOK | wxICON_ERROR, parent);
    }
}
