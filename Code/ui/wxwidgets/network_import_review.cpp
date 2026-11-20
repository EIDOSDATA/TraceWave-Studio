/** @file @brief 서비스가 검증한 복소 표본과 미정 조건을 보여 주고 원자 적용한다. */
#include "network_import_dialog.h"
#include "network_chart.h"
#include "measurement_record_form.h"
#include "measurement_model.h"
#include "frequency_display.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/grid.h>
#include <wx/listctrl.h>
#include <wx/notebook.h>
#include <wx/panel.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <stdexcept>

namespace
{
/** @brief 서비스 표시 값의 null을 0으로 바꾸지 않고 미정으로 표시한다. */
std::string Value(const Json& value)
{
    if (value.is_null())
    {
        return "미정";
    }
    if (value.is_number())
    {
        return Utf8(wxString::Format("%.12g", value.get<double>()));
    }
    if (value.is_string())
    {
        const std::string text = value.get<std::string>();
        if (text == "unknown")
        {
            return "미정";
        }
        if (text == "valid")
        {
            return "유효";
        }
        if (text == "imported")
        {
            return "가져온 자료";
        }
        return text;
    }
    return value.dump();
}
}

void NetworkImportDialog::BuildReviewPage(wxWindow* page)
{
    const int pad = FromDIP(StudioTheme::PanelPadding);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* heading = new wxStaticText(page, wxID_ANY, Display("검토 요약 / 아직 프로젝트에 적용하지 않음"));
    StudioTheme::Heading(*heading);
    layout->Add(heading, 0, wxEXPAND | wxALL, pad);
    m_summary =
        new wxTextCtrl(page, wxID_ANY, wxEmptyString, wxDefaultPosition, wxDefaultSize, wxTE_MULTILINE | wxTE_READONLY);
    m_summary->SetName("network.import.review");
    m_summary->SetMinSize(wxSize(-1, FromDIP(130)));
    layout->Add(m_summary, 1, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, pad);
    auto* views = new wxNotebook(page, wxID_ANY);
    m_chart = new NetworkChart(views);
    m_chart->SetMinSize(FromDIP(wxSize(320, 180)));
    m_chart->SetName("network.import.chart");
    views->AddPage(m_chart, Display("복소 곡선"));
    auto* tablePage = new wxPanel(views);
    auto* tableLayout = new wxBoxSizer(wxVERTICAL);
    m_samples = new wxListCtrl(tablePage, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_SINGLE_SEL);
    m_samples->SetName("network.import.samples");
    const std::array<const char*, 5> columns = {"주파수", "실수부", "허수부", "표본 상태", "자료 구분"};
    for (const auto* column : columns)
    {
        m_samples->AppendColumn(Display(column), wxLIST_FORMAT_LEFT, FromDIP(170));
    }
    StudioTheme::Table(*m_samples);
    tableLayout->Add(m_samples, 1, wxEXPAND);
    tablePage->SetSizer(tableLayout);
    views->AddPage(tablePage, Display("실제 표본"));
    layout->Add(views, 1, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, pad);
    auto* note = new wxStaticText(page, wxID_ANY,
                                  Display("가져오기는 원문과 정규화 자료를 함께 저장하는 한 명령입니다. 교정 / 기준면 "
                                          "/ 시료의 미정은 실측 검증 완료로 바뀌지 않습니다."));
    note->Wrap(FromDIP(820));
    StudioTheme::BindSecondary(*note);
    layout->Add(note, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, pad);
    page->SetSizer(layout);
}

Json NetworkImportDialog::Input() const
{
    if (m_encoded.empty() || m_fileName.empty())
    {
        throw std::runtime_error("가져올 파일을 먼저 선택하세요.");
    }
    if (m_name->GetValue().Strip().empty())
    {
        throw std::runtime_error("자료 이름을 입력하세요.");
    }
    Json input{{"expected_revision", m_revision},
               {"operation", "import"},
               {"parameters",
                {{"name", Utf8(m_name->GetValue())},
                 {"file_name", m_fileName},
                 {"format", Format()},
                 {"source_base64", m_encoded},
                 {"mapping", Mapping()},
                 {"declarations", Declarations()}}}};
    if (MeasurementSelected())
    {
        input["parameters"] = {{"network", input.at("parameters")},
                               {"name", m_measurementForm->Name()},
                               {"changes", m_measurementForm->Changes()},
                               {"reason", m_measurementForm->Reason()}};
        input["operation"] = "import_record";
        input["draft_time_utc"] = m_draftTime;
    }
    return input;
}

void NetworkImportDialog::Preview()
{
    if (!Editable() || m_pending || MeasurementUncertain() || m_measurementForm->Pending())
    {
        return;
    }
    try
    {
        if (m_pairs->IsCellEditControlShown())
        {
            m_pairs->SaveEditControlValue();
            m_pairs->HideCellEditControl();
        }
        const Json input = Input();
        m_review = nullptr;
        m_reviewInput = nullptr;
        m_samples->DeleteAllItems();
        m_chart->Clear();
        m_summary->ChangeValue(Display("원문 형식, 유한 표본과 명시 조건을 서비스에서 검사하고 있습니다."));
        SetStatus("파일 / 조건을 검토하는 중입니다.");
        Request(MeasurementSelected() ? "measurement.preview" : "network.preview", input, false,
                [this, input](const Json& result)
                {
                    if (result.at("project_id") != m_projectId || result.at("revision_id") != m_revision ||
                        (result.value("can_apply", false) && result.value("operation", "") != input.at("operation")))
                    {
                        throw std::runtime_error("다른 프로젝트 또는 개정의 가져오기 응답입니다.");
                    }
                    m_review = result;
                    m_reviewInput = input;
                    if (result.value("can_apply", false) && m_sourceDescriptor.is_null())
                    {
                        m_sourceDescriptor = result.at("descriptor");
                    }
                    RenderReview(result);
                    m_tabs->SetSelection(ReviewPage);
                    SetStatus(
                        result.value("can_apply", false)
                            ? "후보를 확인했습니다. 필요하면 열 / 포트 대응에서 미정 조건을 명시한 뒤 다시 검토하세요."
                            : "가져올 수 없습니다. 검토 안내와 입력 조건을 확인하세요.");
                });
    }
    catch (const std::exception& error)
    {
        m_review = nullptr;
        m_reviewInput = nullptr;
        SetStatus(error.what());
    }
    UpdateActions();
}

void NetworkImportDialog::RenderReview(const Json& result)
{
    m_samples->DeleteAllItems();
    m_chart->Clear();
    std::string text = "자료: " + Utf8(m_name->GetValue()) + "\n원문: " + m_fileName + "\n";
    if (MeasurementSelected())
    {
        text += MeasurementUi::Summary(result.value("record", Json(nullptr))) + "\n";
    }
    if (!result.value("can_apply", false))
    {
        for (const auto& issue : result.value("issues", Json::array()))
        {
            text += issue.value("code", "오류") + ": " + issue.value("message", "검토 실패") + "\n";
            const auto details = issue.value("details", Json::object());
            if (details.is_object() && details.contains("field"))
            {
                text += "입력 위치: " + Value(details.at("field")) + "\n";
            }
        }
        m_summary->ChangeValue(Display(text));
        return;
    }
    const auto& descriptor = result.at("descriptor");
    m_measurementForm->SetDescriptor(descriptor);
    text += "자료 종류: " + descriptor.at("parameter_kind").get<std::string>() +
            " / 단위: " + descriptor.at("unit").get<std::string>() +
            " / 표본 수: " + std::to_string(descriptor.at("sample_count").get<std::size_t>()) + "\n";
    text += "주파수: " + StudioFrequency::Range(descriptor.at("frequency_min_hz"), descriptor.at("frequency_max_hz")) +
            "\n";
    text += "파 정의: " + Value(descriptor.at("wave_definition")) +
            " / 시간 위상: " + Value(descriptor.at("phasor_convention")) + "\n";
    for (std::size_t index = 0; index < descriptor.at("port_ids").size(); ++index)
    {
        text += "포트 " + std::to_string(index + 1) + ": " + Value(descriptor.at("port_names").at(index)) +
                " / 기준면: " + Value(descriptor.at("reference_planes").at(index)) +
                " / 모드: " + Value(descriptor.at("port_modes").at(index)) +
                " / 전류: " + Value(descriptor.at("current_orientation").at(index));
        if (descriptor.at("z0_ohm").is_null() || descriptor.at("z0_ohm").at(index).is_null())
        {
            text += " / Z0: 미정\n";
        }
        else
        {
            const auto& z0 = descriptor.at("z0_ohm").at(index);
            text += " / Z0: " + Value(z0.at(0)) + " + j(" + Value(z0.at(1)) + ") ohm\n";
        }
    }
    if (descriptor.value("z0_frequency_dependent", false))
    {
        text += "Z0는 주파수에 따라 다릅니다. 위 수치는 첫 표본이며 전체 배열을 보존합니다.\n";
    }
    text += "원문 바이트 / 출처 / 기존 조건을 보존합니다. 사용자 명시 조건은 원본 조건과 별도로 기록합니다.\n";
    text += "미정 조건이 남아도 가져올 수 있으나, 조건이 필요한 후속 계산은 차단될 수 있습니다.\n";
    const auto& page = result.at("page");
    const auto frequencyScale = StudioFrequency::ForDescriptor(descriptor);
    wxListItem frequencyColumn;
    frequencyColumn.SetText(Display("주파수 (" + frequencyScale.unit + ")"));
    m_samples->SetColumn(0, frequencyColumn);
    m_chart->SetFrequencyUnit(frequencyScale.unit);
    m_chart->SetPage(page, m_name->GetValue());
    text += "아래 표: 채널 (" + std::to_string(page.at("channel").at("row").get<int>() + 1) + ", " +
            std::to_string(page.at("channel").at("column").get<int>() + 1) + "), 첫 " +
            std::to_string(page.at("samples").size()) + "개 표본. 전체 자료는 결과 화면에서 조회합니다.";
    m_summary->ChangeValue(Display(text));
    for (const auto& sample : page.at("samples"))
    {
        const long row = m_samples->InsertItem(
            m_samples->GetItemCount(), Display(StudioFrequency::Value(sample.at("frequency_hz"), frequencyScale)));
        m_samples->SetItem(row, 1, Display(Value(sample.at("real"))));
        m_samples->SetItem(row, 2, Display(Value(sample.at("imag"))));
        m_samples->SetItem(row, 3, Display(Value(sample.at("status"))));
        m_samples->SetItem(row, 4, Display(Value(sample.at("origin"))));
    }
}

void NetworkImportDialog::Apply()
{
    if (m_pairs->IsCellEditControlShown())
    {
        m_pairs->SaveEditControlValue();
        m_pairs->HideCellEditControl();
    }
    if (!Editable() || m_pending || MeasurementUncertain() || m_measurementForm->Pending() || m_review.is_null() ||
        !m_review.value("can_apply", false))
    {
        return;
    }
    try
    {
        if (Input() != m_reviewInput)
        {
            ChangeInputs();
            SetStatus("현재 입력이 검토한 후보와 다릅니다. 다시 검토하세요.");
            return;
        }
        Json input = m_reviewInput;
        input["command_id"] = Uuid();
        input["review_hash"] = m_review.at("review_hash");
        Request(MeasurementSelected() ? "measurement.apply" : "network.apply", input, true,
                [this](const Json& result)
                {
                    AcceptImport(result);
                });
    }
    catch (const std::exception& error)
    {
        SetStatus(error.what());
    }
}
