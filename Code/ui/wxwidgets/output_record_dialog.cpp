/** @file @brief 실제 응답에 없는 측정이나 통과 상태를 생성하지 않는다. */
#include "output_record_dialog.h"
#include "output_model.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/listctrl.h>
#include <wx/scrolwin.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <array>

namespace
{
wxListCtrl* Table(wxWindow* parent, wxSizer* layout, const std::vector<std::pair<std::string, int>>& columns)
{
    auto* table = new wxListCtrl(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_SINGLE_SEL);
    StudioTheme::Table(*table);
    for (const auto& column : columns)
    {
        table->AppendColumn(Display(column.first), wxLIST_FORMAT_LEFT, parent->FromDIP(column.second));
    }
    layout->Add(table, 1, wxEXPAND | wxALL, parent->FromDIP(8));
    return table;
}

void Row(wxListCtrl& table, const std::vector<std::string>& values)
{
    const long row = table.InsertItem(table.GetItemCount(), Display(values.front()));
    for (std::size_t index = 1; index < values.size(); ++index)
    {
        table.SetItem(row, static_cast<int>(index), Display(values[index]));
    }
}
}

OutputRecordDialog::OutputRecordDialog(wxWindow* parent, const Json& record, bool review)
    : wxDialog(parent, wxID_ANY, Display(review ? "출력 내용 검토" : "출력 파일과 검수 기록"), wxDefaultPosition,
               parent->FromDIP(wxSize(950, 670)), wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER)
{
    StudioTheme::ApplyTypography(*this);
    SetMinSize(FromDIP(wxSize(650, 450)));
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* notice = new wxStaticText(
        this, wxID_ANY,
        Display(
            "고정 입력의 포함/누락과 실제 검수 범위를 확인하세요. 파일 생성은 제조 또는 RF 합격을 뜻하지 않습니다."));
    notice->Wrap(FromDIP(880));
    layout->Add(notice, 0, wxEXPAND | wxALL, FromDIP(12));
    auto* tabs = new StudioNotebook(this);
    const auto page = [tabs](const char* title)
    {
        auto* result = new wxPanel(tabs);
        StudioTheme::BindSurface(*result);
        result->SetSizer(new wxBoxSizer(wxVERTICAL));
        tabs->AddPage(result, Display(title));
        return result;
    };
    auto* scope = page("포함과 누락");
    auto* scopeTable =
        Table(scope, scope->GetSizer(), {{"원본 / 역할", 230}, {"출력", 160}, {"상태", 160}, {"사유", 430}});
    for (const auto& item : record.value("inclusions", Json::array()))
    {
        Row(*scopeTable, {OutputUi::Text(item.value("label", item.value("name", Json(nullptr)))),
                          OutputUi::Text(item.value("target", item.value("role", Json(nullptr)))),
                          OutputUi::State(item.value("status", "included")),
                          OutputUi::Text(item.value("reason", Json(nullptr)), "")});
    }
    for (const auto& item : record.value("omissions", Json::array()))
    {
        Row(*scopeTable,
            {item.is_object() ? OutputUi::Text(item.value("label", item.value("name", Json(nullptr))), "원본 항목")
                              : "원본 항목",
             "제외 / 의미 보존 범위", "범위 확인", OutputUi::Issues(Json::array({item}))});
    }
    const auto pcb = record.value("pcb_preview", Json::object());
    for (const auto& layer : pcb.value("layers", Json::array()))
    {
        Row(*scopeTable, {OutputUi::Text(layer.value("name", Json(nullptr)), "층 이름 미정"),
                          OutputUi::Text(layer.value("target_label", Json(nullptr))),
                          layer.value("selected", false) ? "포함" : "사용 여부 / 제외 확인",
                          "고정 원본의 층 대응. 일부 층만 누락한 Job은 만들지 않습니다."});
    }
    const auto names = pcb.value("names", Json::object());
    for (const auto* collection : {"holes", "cutouts"})
    {
        for (const auto& item : pcb.value(collection, Json::array()))
        {
            Row(*scopeTable, {OutputUi::Text(names.value(item.at("id").get<std::string>(), Json(nullptr)), "기계 형상"),
                              std::string(collection) == "holes" ? "드릴 / 슬롯" : "내부 절삭", "실제 원문 형상",
                              "완성 치수와 공구 지름 / 도금 미정값은 구분합니다."});
        }
    }
    const auto summary = record.value("summary", Json::object());
    for (const auto& item : std::vector<std::pair<std::string, std::string>>{
             {"page_count", "종이 페이지"}, {"shape_count", "투영 도형"}, {"layer_count", "투영 층"}})
    {
        if (summary.contains(item.first))
        {
            Row(*scopeTable,
                {item.second, OutputUi::Text(summary.at(item.first)), "검토한 수량", "서비스의 실제 투영 요약"});
        }
    }
    for (const auto& item : std::vector<std::pair<std::string, std::string>>{{"shape_count", "도체 형상"},
                                                                             {"layer_count", "층"},
                                                                             {"surface_count", "표면 처리"},
                                                                             {"environment_count", "외부 고체"}})
    {
        if (record.contains(item.first))
        {
            Row(*scopeTable,
                {item.second, OutputUi::Text(record.at(item.first)), "검토한 수량", "서비스의 실제 투영 요약"});
        }
    }
    if (scopeTable->GetItemCount() == 0)
    {
        Row(*scopeTable,
            {"상세 포함 목록", "", "미제공", "이 응답에 포함 목록이 없어 임의로 완전함을 판정하지 않습니다."});
    }
    auto* issues = new wxTextCtrl(scope, wxID_ANY, Display(OutputUi::Issues(record.value("issues", Json::array()))),
                                  wxDefaultPosition, FromDIP(wxSize(-1, 110)), wxTE_MULTILINE | wxTE_READONLY);
    scope->GetSizer()->Add(issues, 0, wxEXPAND | wxALL, FromDIP(8));
    auto* filesPage = page("파일 목록");
    auto* files =
        Table(filesPage, filesPage->GetSizer(), {{"파일", 240}, {"역할", 160}, {"바이트", 110}, {"SHA256", 520}});
    auto artifacts = record.value("artifacts", Json::array());
    if (artifacts.empty() && record.value("manifest", Json(nullptr)).is_object())
    {
        artifacts = record.at("manifest").value("artifacts", record.at("manifest").value("files", Json::array()));
    }
    if (artifacts.empty())
    {
        artifacts = record.value("planned_files", Json::array());
    }
    for (const auto& artifact : artifacts)
    {
        auto filename =
            OutputUi::Text(artifact.value("name", artifact.value("file_name", artifact.value("uri", Json(nullptr)))));
        const auto slash = filename.find_last_of("/\\");
        if (slash != std::string::npos)
        {
            filename = filename.substr(slash + 1);
        }
        Row(*files, {filename, OutputUi::Text(artifact.value("role", Json(nullptr))),
                     OutputUi::Text(artifact.value("bytes", Json(nullptr)), "생성 전"),
                     OutputUi::Text(artifact.value("sha256", Json(nullptr)), "생성 전")});
    }
    auto* verifyPage = page("검수 항목");
    const auto rawReport = record.value("report", record.value("verification", Json::object()));
    const auto report = rawReport.is_object() ? rawReport.value("verification", rawReport) : rawReport;
    auto* reader = new wxStaticText(
        verifyPage, wxID_ANY,
        Display(report.is_object() ? "검수 상태: " + OutputUi::State(report.value("status", "not_assessed")) +
                                         " / 읽기 도구: " + OutputUi::Reader(report.value("reader", Json(nullptr)))
                                   : "보존된 검수 보고서가 없습니다."));
    verifyPage->GetSizer()->Add(reader, 0, wxEXPAND | wxALL, FromDIP(8));
    auto* checks = Table(verifyPage, verifyPage->GetSizer(),
                         {{"항목", 230},
                          {"기대값", 135},
                          {"재입력값", 135},
                          {"오차", 110},
                          {"허용값", 110},
                          {"단위", 90},
                          {"판정 / 사유", 360}});
    if (report.is_object())
    {
        for (const auto& row : report.value("rows", Json::array()))
        {
            Row(*checks,
                {OutputUi::Text(row.value("label", row.value("name", Json(nullptr)))),
                 OutputUi::Text(row.value("expected", Json(nullptr))),
                 OutputUi::Text(row.value("actual", Json(nullptr))), OutputUi::Text(row.value("error", Json(nullptr))),
                 OutputUi::Text(row.value("tolerance", Json(nullptr))),
                 OutputUi::Text(row.value("unit", Json(nullptr)), ""),
                 OutputUi::State(row.value("state", row.value("status", "not_assessed"))) + " / " +
                     OutputUi::Text(row.value("reason", Json(nullptr)), "")});
        }
        for (const auto& check : report.value("checks", Json::array()))
        {
            Row(*checks, {OutputUi::Text(check), "고정 원본", "parser 재입력 대조", "개별 수치 미제공", "reader별 계약",
                          "", OutputUi::State(report.value("status", "not_assessed"))});
        }
        for (const auto& body : report.value("bodies", Json::array()))
        {
            const auto name = OutputUi::Text(body.value("label", Json(nullptr)), "고체 / 이름 미제공");
            for (const auto& key : std::vector<std::pair<std::string, std::string>>{
                     {"bbox_error_mm", "경계"}, {"center_error_mm", "중심"}, {"thickness_error_mm", "두께"}})
            {
                if (body.contains(key.first))
                {
                    Row(*checks,
                        {name + " / " + key.second, "원본 sidecar", "새 reader", OutputUi::Text(body.at(key.first)),
                         OutputUi::Text(report.value("linear_tolerance_mm", Json(nullptr))), "mm",
                         OutputUi::State(report.value("status", "not_assessed"))});
                }
            }
            for (const auto& metric : std::vector<std::array<std::string, 4>>{
                     {{"volume_error_mm3", "volume_tolerance_mm3", "체적", "mm^3"}},
                     {{"section_area_error_mm2", "section_area_tolerance_mm2", "단면적", "mm^2"}}})
            {
                if (body.contains(metric[0]))
                {
                    Row(*checks,
                        {name + " / " + metric[2], "원본 sidecar", "새 reader", OutputUi::Text(body.at(metric[0])),
                         OutputUi::Text(body.value(metric[1], Json(nullptr))), metric[3],
                         OutputUi::State(report.value("status", "not_assessed"))});
                }
            }
            for (const auto& count :
                 std::vector<std::pair<std::string, std::string>>{{"solid_count", "고체 수"},
                                                                  {"section_loop_count", "단면 경계 수"},
                                                                  {"through_hole_count", "관통 구멍 수"}})
            {
                if (body.contains(count.first))
                {
                    Row(*checks,
                        {name + " / " + count.second, "원본 sidecar와 대조", OutputUi::Text(body.at(count.first)), "",
                         "동일 수량", "개", OutputUi::State(report.value("status", "not_assessed"))});
                }
            }
        }
        if (checks->GetItemCount() == 0)
        {
            Row(*checks, {"보존 검수 요약", "", "", "세부 수치 미제공", "", "",
                          OutputUi::State(report.value("status", "not_assessed"))});
        }
    }
    auto* sourcePage = page("고급 원문");
    auto* raw = new wxTextCtrl(sourcePage, wxID_ANY, Display(record.dump(2)), wxDefaultPosition, wxDefaultSize,
                               wxTE_MULTILINE | wxTE_READONLY | wxHSCROLL);
    sourcePage->GetSizer()->Add(raw, 1, wxEXPAND | wxALL, FromDIP(8));
    layout->Add(tabs, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    auto* close = new wxButton(this, wxID_OK, Display(review ? "검토한 내용으로 생성" : "닫기"));
    StudioTheme::Button(*close, true);
    layout->Add(close, 0, wxALIGN_RIGHT | wxALL, FromDIP(12));
    SetSizer(layout);
    CentreOnParent();
}
