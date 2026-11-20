/** @file @brief 같은 커널 재입력, 독립 검수와 제조 승인을 별개 상태로 표시한다. */
#include "output_conditions_view.h"
#include "output_model.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/collpane.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>

OutputConditionsView::OutputConditionsView(wxWindow* parent)
    : wxScrolledWindow(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL)
{
    StudioTheme::BindSurface(*this);
    SetScrollRate(0, FromDIP(16));
    SetSizer(new wxBoxSizer(wxVERTICAL));
    auto* heading = new wxStaticText(this, wxID_ANY, Display("출력 기준"));
    StudioTheme::Title(*heading);
    GetSizer()->Add(heading, 0, wxALL, FromDIP(12));
    m_input = Group("고정 입력과 파일");
    m_limits = Group("범위 / 제작과 측정");
    m_verification = Group("생성과 검수");
    m_source = Group("고급 / 보존 원문", true);
    Bind(wxEVT_SIZE,
         [this](wxSizeEvent& event)
         {
             Layout();
             FitInside();
             event.Skip();
         });
    Clear("프로젝트와 출력할 고정 입력을 선택하세요.");
}

wxTextCtrl* OutputConditionsView::Group(const std::string& title, bool collapsed)
{
    auto* pane = new wxCollapsiblePane(this, wxID_ANY, Display(title), wxDefaultPosition, wxDefaultSize,
                                       wxCP_DEFAULT_STYLE | wxCP_NO_TLW_RESIZE);
    pane->Collapse(collapsed);
    auto* content = pane->GetPane();
    content->SetSizer(new wxBoxSizer(wxVERTICAL));
    auto* text = new wxTextCtrl(content, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 142)),
                                wxTE_MULTILINE | wxTE_READONLY | wxBORDER_NONE);
    text->SetMinSize(FromDIP(wxSize(180, 142)));
    content->GetSizer()->Add(text, 1, wxEXPAND | wxALL, FromDIP(4));
    GetSizer()->Add(pane, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    pane->Bind(wxEVT_COLLAPSIBLEPANE_CHANGED,
               [this](wxCollapsiblePaneEvent&)
               {
                   Layout();
                   FitInside();
               });
    if (collapsed)
    {
        m_advanced = pane;
    }
    return text;
}

void OutputConditionsView::SetRecord(const Json& record, const std::string& sourceName)
{
    std::string input = sourceName.empty() ? "고정 입력 이름 미기록" : sourceName;
    input += "\n출력 형식: " + (record.value("format", "") == "verification"
                                    ? std::string("재검수 / 원래 형식은 상세 확인")
                                    : OutputUi::Text(record.value("format", Json(nullptr))));
    const auto options = record.value("options", Json::object());
    input += "\n용도: " + OutputUi::Purpose(record);
    input += "\n좌표 / 단위: 프로젝트 원점 / mm";
    if (options.contains("scale"))
    {
        input += "\n명시 출력 축척: " + OutputUi::Text(options.at("scale"));
    }
    m_input->ChangeValue(Display(input));
    m_limits->ChangeValue(Display(OutputUi::Conditions(record)));
    const auto rawReport = record.value("report", record.value("verification", Json::object()));
    const auto report = rawReport.is_object() ? rawReport.value("verification", rawReport) : rawReport;
    std::string verification = "생성 상태: " + OutputUi::State(record.value("status", "not_assessed"));
    if (report.is_object())
    {
        verification += "\n검수: " + OutputUi::State(report.value("status", "not_assessed"));
        verification += "\n읽기 도구: " + OutputUi::Reader(report.value("reader", Json(nullptr)));
        verification += "\n독립 커널: " + OutputUi::Text(report.value("kernel_independent", Json(nullptr)), "미확립");
    }
    verification += "\n형식 검수 통과는 제조/RF/실측 합격이 아닙니다.";
    m_verification->ChangeValue(Display(verification));
    m_source->ChangeValue(Display(record.dump(2)));
    Layout();
    FitInside();
}

void OutputConditionsView::SetHandoff(const Json& snapshot, const Json& review)
{
    std::string input = "고정 설계와 선택 근거";
    if (review.is_object())
    {
        input += "\n개정: " + review.at("revision_id").get<std::string>();
    }
    if (snapshot.is_object())
    {
        input += "\n고정 입력: " + snapshot.at("snapshot_id").get<std::string>();
    }
    m_input->ChangeValue(Display(input));
    m_limits->ChangeValue(Display(
        "포함: 설계 사본, 보고서, 권한을 확인한 선택 파일\n제작/측정·물리 합격 미확립\n복원 및 작업 재개 범위 제외"));
    m_verification->ChangeValue(
        Display(review.is_object() ? "검토한 파일 " + std::to_string(review.at("files").size() + 1) + "개 / 기록 SHA256 표시"
                                   : "인계 범위를 검토하면 파일과 해시를 확인할 수 있습니다."));
    m_source->ChangeValue(Display(review.is_object() ? review.dump(2) : ""));
    Layout();
    FitInside();
}

void OutputConditionsView::Clear(const std::string& message)
{
    m_input->ChangeValue(Display(message));
    m_limits->ChangeValue(
        Display("제작/측정 조건: 이 출력에서 확인하지 않음 / 출처 확인\n화면 표시와 출력 포함은 별개입니다."));
    m_verification->ChangeValue(Display("생성 / 독립 검수: 미실행"));
    m_source->Clear();
    Layout();
    FitInside();
}
