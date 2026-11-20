/** @file @brief 저장된 보고서의 당시 표본, 조건과 보간 계보를 페이지 단위로 보여준다. */
#include "measurement_history_dialog.h"
#include "measurement_model.h"
#include "frequency_display.h"
#include "network_chart.h"
#include "result_presentation.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/collpane.h>
#include <wx/listctrl.h>
#include <wx/scrolwin.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>

MeasurementHistoryDialog::MeasurementHistoryDialog(wxWindow* parent, const Json& context, const Json& entry,
                                                   DialogGateway gateway)
    : ProjectSetupDialog(parent, "보존 측정 보고서", context, gateway), m_entry(entry),
      m_collection(entry.at("collection").get<std::string>())
{
    SetName("measurement.history.dialog");
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* heading = new wxStaticText(this, wxID_ANY, Display(entry.value("name", std::string("보존 보고서"))));
    StudioTheme::Title(*heading);
    layout->Add(heading, 0, wxALL, FromDIP(12));
    m_tabs = new StudioNotebook(this);
    auto* page = new wxScrolledWindow(m_tabs, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL);
    page->SetScrollRate(0, FromDIP(16));
    auto* body = new wxBoxSizer(wxVERTICAL);
    m_summary = new wxTextCtrl(page, wxID_ANY, Display("당시 보고서를 읽고 있습니다."), wxDefaultPosition,
                               FromDIP(wxSize(-1, 130)), wxTE_MULTILINE | wxTE_READONLY);
    body->Add(m_summary, 0, wxEXPAND | wxALL, FromDIP(8));
    m_chart = new NetworkChart(page);
    m_chart->SetMinSize(FromDIP(wxSize(360, 220)));
    body->Add(m_chart, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    m_section = new wxChoice(page, wxID_ANY);
    if (m_collection == "alignments")
    {
        m_section->Append(Display("보간 / 원문 계보"));
    }
    else
    {
        m_section->Append(Display("당시 표본 차이"));
        m_section->Append(Display("당시 시료 / 교정 조건 차이"));
    }
    m_section->SetSelection(0);
    body->Add(m_section, 0, wxALL, FromDIP(8));
    m_items =
        new wxListCtrl(page, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 180)), wxLC_REPORT | wxLC_SINGLE_SEL);
    m_items->SetMinSize(FromDIP(wxSize(-1, 180)));
    StudioTheme::Table(*m_items);
    body->Add(m_items, 0, wxEXPAND | wxALL, FromDIP(8));
    auto* paging = new wxBoxSizer(wxHORIZONTAL);
    m_previous = new wxButton(page, wxID_ANY, Display("이전"));
    m_nextButton = new wxButton(page, wxID_ANY, Display("다음"));
    paging->Add(m_previous, 0, wxALL, FromDIP(4));
    paging->Add(m_nextButton, 0, wxALL, FromDIP(4));
    body->Add(paging, 0);
    page->SetSizer(body);
    page->Bind(wxEVT_SIZE,
               [page](wxSizeEvent& event)
               {
                   page->Layout();
                   page->FitInside();
                   event.Skip();
               });
    m_tabs->AddPage(page, Display("고정 보고서"));
    auto* original = new wxPanel(m_tabs);
    auto* originalLayout = new wxBoxSizer(wxVERTICAL);
    originalLayout->Add(new wxStaticText(original, wxID_ANY,
                                         Display("과거 보고서는 현재 엔진으로 다시 계산하지 않습니다. 기록된 정확도와 "
                                                 "불확도를 독립 검증 합격으로 바꾸지 않습니다.")),
                        0, wxEXPAND | wxALL, FromDIP(12));
    auto* advanced = new wxCollapsiblePane(original, wxID_ANY, Display("고급 / 봉인 원문"), wxDefaultPosition,
                                           wxDefaultSize, wxCP_DEFAULT_STYLE | wxCP_NO_TLW_RESIZE);
    advanced->GetPane()->SetSizer(new wxBoxSizer(wxVERTICAL));
    m_source = new wxTextCtrl(advanced->GetPane(), wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 300)),
                              wxTE_MULTILINE | wxTE_READONLY | wxHSCROLL);
    advanced->GetPane()->GetSizer()->Add(m_source, 1, wxEXPAND);
    advanced->Collapse();
    originalLayout->Add(advanced, 1, wxEXPAND | wxALL, FromDIP(12));
    original->SetSizer(originalLayout);
    advanced->Bind(wxEVT_COLLAPSIBLEPANE_CHANGED,
                   [original](wxCollapsiblePaneEvent&)
                   {
                       original->Layout();
                   });
    m_tabs->AddPage(original, Display("원문과 적용 범위"));
    layout->Add(m_tabs, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    m_status = new wxStaticText(this, wxID_ANY, wxEmptyString);
    layout->Add(m_status, 0, wxEXPAND | wxALL, FromDIP(12));
    layout->Add(CreateButtonSizer(wxCANCEL), 0, wxEXPAND | wxALL, FromDIP(12));
    SetSizer(layout);
    m_section->Bind(wxEVT_CHOICE,
                    [this](wxCommandEvent&)
                    {
                        InvalidateRead();
                        LoadSection(0);
                    });
    m_previous->Bind(wxEVT_BUTTON,
                     [this](wxCommandEvent&)
                     {
                         LoadSection(std::max(0, m_offset - (m_section->GetSelection() == 1 ? 32 : 201)));
                     });
    m_nextButton->Bind(wxEVT_BUTTON,
                       [this](wxCommandEvent&)
                       {
                           if (m_next >= 0)
                           {
                               LoadSection(m_next);
                           }
                       });
    CallAfter(
        [this]()
        {
            if (!m_closed)
            {
                LoadSummary();
            }
        });
}
void MeasurementHistoryDialog::UpdateActions()
{
    if (!m_section)
    {
        return;
    }
    const bool ready = Editable() && !m_pending;
    m_section->Enable(ready && m_summaryData.is_object());
    m_previous->Enable(ready && m_offset > 0);
    m_nextButton->Enable(ready && m_next >= 0);
}
void MeasurementHistoryDialog::LoadSummary()
{
    Request("measurement.history",
            {{"collection", m_collection},
             {"record", m_entry.at("record_ref")},
             {"section", "summary"},
             {"offset", 0},
             {"limit", 201}},
            false,
            [this](const Json& result)
            {
                if (result.value("record_ref", Json(nullptr)) != m_entry.at("record_ref") ||
                    result.value("collection", "") != m_collection || result.value("physics_validated", true))
                {
                    throw std::runtime_error("보고서의 고정 개정 또는 검증 상태가 요청과 다릅니다.");
                }
                m_summaryData = result;
                m_source->ChangeValue(Display(result.dump(2)));
                std::string summary = "이름: " + result.value("name", std::string()) +
                                      "\n초안 기록 시각: " + result.value("draft_time_utc", std::string("미기록"));
                const auto input = result.value("input", Json::object());
                summary +=
                    "\n사유: " +
                    input.value("reason",
                                input.value("specification", Json::object()).value("reason", std::string("미기록")));
                summary += "\n실측 일치: 미확립 / 불확도 전파: 수행하지 않음\n당시 원본, 표본 상태와 조건을 보존한 "
                           "읽기 전용 보고서입니다.";
                m_summary->ChangeValue(Display(summary));
                if (m_collection == "alignments")
                {
                    LoadAlignment(result);
                }
                else
                {
                    LoadSection(0);
                }
            });
}
void MeasurementHistoryDialog::LoadAlignment(const Json& summary)
{
    const auto source = summary.at("source");
    Request("result.describe", {{"source", source}}, false,
            [this, source](const Json& result)
            {
                if (result.value("source", Json(nullptr)) != source || !result.value("pin", Json(nullptr)).is_object())
                {
                    throw std::runtime_error("정렬 자료의 고정 원본이 다릅니다.");
                }
                m_sourcePin = {{"source", source}, {"pin", result.at("pin")}};
                auto input = m_sourcePin;
                input["row"] = 0;
                input["column"] = 0;
                input["offset"] = 0;
                input["limit"] = 201;
                Request("result.page", input, false,
                        [this](const Json& response)
                        {
                            if (response.value("source", Json(nullptr)) != m_sourcePin.at("source") ||
                                response.value("pin", Json(nullptr)) != m_sourcePin.at("pin"))
                            {
                                throw std::runtime_error("정렬 곡선의 원본 해시가 달라졌습니다.");
                            }
                            m_chart->SetFrequencyUnit(StudioFrequency::ForPage(response.at("page")).unit);
                            m_chart->SetPage(response.at("page"), Display("보존 정렬 자료 / 첫 201표본"));
                            LoadSection(0);
                        });
            });
}
void MeasurementHistoryDialog::LoadSection(int offset)
{
    const std::string section = m_collection == "alignments"     ? "lineage"
                                : m_section->GetSelection() == 1 ? "conditions"
                                                                 : "points";
    Request("measurement.history",
            {{"collection", m_collection},
             {"record", m_entry.at("record_ref")},
             {"section", section},
             {"offset", offset},
             {"limit", section == "conditions" ? 32 : 201}},
            false,
            [this, section, offset](const Json& response)
            {
                if (response.value("record_ref", Json(nullptr)) != m_entry.at("record_ref") ||
                    response.value("section", "") != section || response.value("offset", -1) != offset)
                {
                    throw std::runtime_error("보고서 페이지의 원본 또는 범위가 다릅니다.");
                }
                RenderSection(response);
            });
}
void MeasurementHistoryDialog::RenderSection(const Json& response)
{
    m_offset = response.at("offset").get<int>();
    m_next = response.at("next_offset").is_number_integer() ? response.at("next_offset").get<int>() : -1;
    m_items->ClearAll();
    const auto section = response.at("section").get<std::string>();
    std::vector<std::string> columns =
        section == "conditions" ? std::vector<std::string>{"조건", "기준", "비교", "상태 / 사유"}
        : section == "points"   ? std::vector<std::string>{"주파수", "비교 - 기준", "표본 출처", "사유"}
                                : std::vector<std::string>{"표본 / 주파수", "원문 표본", "계보 종류", "근거"};
    for (const auto& title : columns)
    {
        m_items->AppendColumn(Display(title), wxLIST_FORMAT_LEFT, FromDIP(title == columns.back() ? 380 : 210));
    }
    const auto values = response.at("items");
    const auto scale = StudioFrequency::ForSamples(values);
    Json samples = Json::array();
    for (const auto& value : values)
    {
        std::vector<std::string> fields;
        if (section == "conditions")
        {
            fields = {MeasurementUi::Text(value.value("label", Json(nullptr))),
                      MeasurementUi::Text(value.value("left_display", Json(nullptr))),
                      MeasurementUi::Text(value.value("right_display", Json(nullptr))),
                      MeasurementUi::Text(value.value("reason", value.value("state", Json(nullptr))))};
        }
        else if (section == "points")
        {
            const auto difference = value.value("difference_ri", Json(nullptr));
            const auto origins = value.value("sample_origins", Json::object());
            fields = {StudioFrequency::Value(value.value("frequency_hz", Json(nullptr)), scale) + " " + scale.unit,
                      ResultUi::Complex(difference),
                      ResultUi::State(origins.value("left", Json(nullptr))) + " / " +
                          ResultUi::State(origins.value("right", Json(nullptr))),
                      MeasurementUi::Text(value.value("reason", Json(nullptr)))};
            samples.push_back({{"frequency_hz", value.value("frequency_hz", Json(nullptr))},
                               {"real", difference.is_array() ? difference.at(0) : Json(nullptr)},
                               {"imag", difference.is_array() ? difference.at(1) : Json(nullptr)},
                               {"status", difference.is_array() ? "valid" : "missing"}});
        }
        else
        {
            const auto frequency = value.value("frequency_hz", Json(nullptr));
            const auto weight = value.value("weight", Json(nullptr));
            auto evidence = MeasurementUi::Text(value.value("reason", Json(nullptr)));
            if (weight.is_number())
            {
                evidence = "가중치 " + weight.dump() + " / " + evidence;
            }
            const auto indices = value.value("source_indices", Json(nullptr));
            fields = {frequency.is_null() ? "단계 " + std::to_string(value.at("operation").get<int>())
                                          : StudioFrequency::Value(frequency, scale) + " " + scale.unit,
                      indices.is_array() ? indices.dump() : "미정", MeasurementUi::Text(value.at("kind")), evidence};
        }
        const long row = m_items->InsertItem(m_items->GetItemCount(), Display(fields.front()));
        for (std::size_t column = 1; column < fields.size(); ++column)
        {
            m_items->SetItem(row, static_cast<int>(column), Display(fields[column]));
        }
    }
    if (section == "points")
    {
        m_chart->SetMetric("real", Display("비교 - 기준 / 실수부"));
        m_chart->SetFrequencyUnit(scale.unit);
        m_chart->SetPage({{"samples", samples}}, Display("보존 차이 표본"));
    }
    SetStatus("당시 보고서 " + std::to_string(m_offset + 1) + " ~ " + std::to_string(m_offset + values.size()) + " / " +
              std::to_string(response.at("total").get<int>()) + " 항목. 재계산하지 않은 보존 기록입니다.");
}
