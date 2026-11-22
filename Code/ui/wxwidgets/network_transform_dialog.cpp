/** @file @brief S/Z/Y 변환과 실수 기준 임피던스 재정규화의 검토 수명을 관리한다. */
#include "network_transform_dialog.h"
#include "frequency_display.h"
#include "network_chart.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/wx.h>
#include <wx/listctrl.h>
#include <wx/scrolwin.h>
#include <array>
#include <stdexcept>
#include <vector>

namespace
{
/** @brief 서버의 값과 미정 상태를 계산 없이 읽기 가능한 문자열로 바꾼다. */
std::string Value(const Json& value)
{
    return value.is_null() ? "미정" : value.is_string() ? value.get<std::string>() : value.dump();
}

/** @brief 모든 입력 필드에 보이는 레이블과 native 툴팁을 제공한다. */
void Field(wxWindow* parent, wxSizer* layout, const std::string& label, wxWindow* input)
{
    layout->Add(new wxStaticText(parent, wxID_ANY, Display(label)), 0, wxBOTTOM, parent->FromDIP(4));
    layout->Add(input, 0, wxEXPAND | wxBOTTOM, parent->FromDIP(12));
    input->SetToolTip(Display(label));
}

/** @brief 서로 다른 복소 종류와 기준면을 한 축의 같은 값으로 오해하지 않도록 표시한다. */
std::string Conditions(const Json& descriptor)
{
    std::string text = "자료: " + Value(descriptor.at("parameter_kind")) + " / 단위 " + Value(descriptor.at("unit"));
    text += "\n포트 " + std::to_string(descriptor.at("port_ids").size()) + "개 / 표본 " +
            Value(descriptor.at("sample_count")) + "개";
    text += "\n주파수: " + StudioFrequency::Range(descriptor.at("frequency_min_hz"), descriptor.at("frequency_max_hz"));
    text += "\n기준면: " + Value(descriptor.at("reference_planes"));
    text += "\n첫 표본 Z0 (실수, 허수): " + Value(descriptor.at("z0_ohm")) + " ohm";
    text += descriptor.value("z0_frequency_dependent", false) ? "\nZ0는 주파수별로 다릅니다."
                                                              : "\nZ0는 주파수별 동일 또는 미정입니다.";
    text += "\n파 정의: " + Value(descriptor.at("wave_definition")) +
            "\n시간 규약: " + Value(descriptor.at("phasor_convention"));
    text += "\n미정/무효 값: " + Value(descriptor.at("invalid_value_count")) + "개";
    text += "\n출처: " + Value(descriptor.at("source_refs"));
    text += "\n제작 / 측정 등 원문 조건: " + Value(descriptor.at("conditions"));
    return text;
}
}

NetworkTransformDialog::NetworkTransformDialog(wxWindow* parent, const Json& context, const Json& selection,
                                               DialogGateway gateway)
    : ProjectSetupDialog(parent, "네트워크 변환 / 별도 결과 저장", context, std::move(gateway)), m_context(context),
      m_selection(selection)
{
    SetName("network.transform.dialog");
    BuildInterface();
    m_loading = true;
    int selected = wxNOT_FOUND;
    for (const auto& item : context.at("datasets"))
    {
        const auto name = Display(item.at("name").get<std::string>());
        const int index = m_datasets->Append(name);
        m_leftFixture->Append(name);
        m_rightFixture->Append(name);
        if (!selection.is_null() && item.at("id") == selection.at("entry").at("id"))
        {
            selected = index;
        }
    }
    m_datasets->SetSelection(selected);
    if (selected == wxNOT_FOUND)
    {
        m_selection = nullptr;
    }
    m_loading = false;
    RenderSource();
    SetStatus("변환 종류와 입력 조건을 확인한 뒤 검토하세요. 원본과 제작/측정 조건은 보존됩니다.");
    UpdateActions();
    if (!m_selection.is_null())
    {
        const auto& page = m_selection.at("page");
        if (page.at("offset") != 0 || page.at("channel").at("row") != 0 || page.at("channel").at("column") != 0)
        {
            SelectDataset();
        }
    }
}

void NetworkTransformDialog::BuildInterface()
{
    StudioTheme::ApplyTypography(*this);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* title = new wxStaticText(this, wxID_ANY, Display("네트워크 변환"));
    StudioTheme::Title(*title);
    layout->Add(title, 0, wxALL, FromDIP(16));
    auto* introduction = new wxStaticText(
        this, wxID_ANY,
        Display("복소 종류와 Z0를 변환하고, 기준면을 이동하거나 시간 게이트를 적용합니다. 결과를 별도 자료로 저장합니다."));
    StudioTheme::BindSecondary(*introduction);
    introduction->Wrap(FromDIP(980));
    layout->Add(introduction, 0, wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(16));
    auto* selection = new wxBoxSizer(wxVERTICAL);
    m_datasets = new wxChoice(this, wxID_ANY);
    m_datasets->SetName("network.transform.dataset");
    Field(this, selection, "원본 자료", m_datasets);
    layout->Add(selection, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(16));
    m_tabs = new StudioNotebook(this);
    auto* options = new wxScrolledWindow(m_tabs, wxID_ANY);
    options->SetScrollRate(FromDIP(16), FromDIP(16));
    auto* optionLayout = new wxBoxSizer(wxHORIZONTAL);
    auto* fields = new wxBoxSizer(wxVERTICAL);
    m_name = new wxTextCtrl(options, wxID_ANY, Display("변환 결과 01"));
    m_name->SetName("network.transform.name");
    Field(options, fields, "별도로 저장할 결과 이름", m_name);
    m_mode = new wxChoice(options, wxID_ANY);
    m_mode->SetName("network.transform.mode");
    m_mode->Append(Display("S / Z / Y 종류 변환"));
    m_mode->Append(Display("S 기준 임피던스 재정규화"));
    m_mode->Append(Display("S 기준면 이동 (정합 선로)"));
    m_mode->Append(Display("양쪽 2포트 치구 제거"));
    m_mode->Append(Display("S 시간 게이트"));
    m_mode->SetSelection(0);
    Field(options, fields, "변환 작업", m_mode);
    m_kind = new wxChoice(options, wxID_ANY);
    m_kind->SetName("network.transform.kind");
    for (const auto* kind : {"S", "Z", "Y"})
    {
        m_kind->Append(Display(kind));
    }
    m_kind->SetSelection(1);
    Field(options, fields, "변환할 복소 종류", m_kind);
    m_reference = new wxTextCtrl(options, wxID_ANY);
    m_reference->SetName("network.transform.reference");
    m_reference->SetHint(Display("양의 실수 입력 / 빈칸은 미정"));
    Field(options, fields, "새 Z0 (ohm, 모든 포트 / 주파수에 동일 적용)", m_reference);
    m_lineFields = new wxBoxSizer(wxVERTICAL);
    m_lines = new wxTextCtrl(options, wxID_ANY, wxEmptyString, wxDefaultPosition,
                             FromDIP(wxSize(400, 72)), wxTE_MULTILINE);
    m_lines->SetName("network.transform.reference-lines");
    Field(options, m_lineFields, "포트 | 거리 또는 좌표(mm) | 위상 속도(m/s) | 감쇠(dB/m) | 새 기준면", m_lines);
    auto* lineHelp = new wxStaticText(options, wxID_ANY, Display(
        "포트마다 한 줄을 입력합니다. 양수 길이는 추가, 음수 길이는 제거입니다.\n"
        "거리 예시 1 | -5 | 2e8 | 0 | 기판 패드\n"
        "좌표는 현재 점 > 새 점 > 바깥 방향을 XYZ로 입력합니다.\n"
        "좌표 예시 1 | 0,0,0 > 3,4,0 > 3,4,0 | 2e8 | 0 | 정합 선로 끝"));
    lineHelp->Wrap(FromDIP(400));
    StudioTheme::BindSecondary(*lineHelp);
    m_lineFields->Add(lineHelp, 0, wxEXPAND | wxBOTTOM, FromDIP(10));
    fields->Add(m_lineFields, 0, wxEXPAND);
    m_fixtureFields = new wxBoxSizer(wxVERTICAL);
    m_leftFixture = new wxChoice(options, wxID_ANY);
    m_leftFixture->SetName("network.transform.left-fixture");
    Field(options, m_fixtureFields, "왼쪽 치구 (포트 1 바깥, 포트 2 안쪽)", m_leftFixture);
    m_rightFixture = new wxChoice(options, wxID_ANY);
    m_rightFixture->SetName("network.transform.right-fixture");
    Field(options, m_fixtureFields, "오른쪽 치구 (포트 1 안쪽, 포트 2 바깥)", m_rightFixture);
    auto* fixtureHelp = new wxStaticText(
        options, wxID_ANY, Display("원본에는 왼쪽 치구, DUT, 오른쪽 치구가 차례로 연결되어 있어야 합니다.\n"
                                  "세 자료의 주파수, 양의 실수 Z0, 파 규약 및 바깥 기준면을 확인합니다."));
    fixtureHelp->Wrap(FromDIP(400));
    StudioTheme::BindSecondary(*fixtureHelp);
    m_fixtureFields->Add(fixtureHelp, 0, wxEXPAND | wxBOTTOM, FromDIP(10));
    fields->Add(m_fixtureFields, 0, wxEXPAND);
    m_timeGateFields = new wxBoxSizer(wxVERTICAL);
    m_gateStart = new wxTextCtrl(options, wxID_ANY);
    m_gateStart->SetName("network.transform.gate.start");
    Field(options, m_timeGateFields, "유지할 시간 시작 (ns)", m_gateStart);
    m_gateStop = new wxTextCtrl(options, wxID_ANY);
    m_gateStop->SetName("network.transform.gate.stop");
    Field(options, m_timeGateFields, "유지할 시간 끝 (ns)", m_gateStop);
    auto* gateHelp = new wxStaticText(
        options, wxID_ANY, Display("균일 주파수 표본의 복소 대역에서 입력한 지연 구간을 남깁니다.\n"
                                  "시간 간격과 주기는 원본 주파수 간격과 표본 수로 결정됩니다."));
    gateHelp->Wrap(FromDIP(400));
    StudioTheme::BindSecondary(*gateHelp);
    m_timeGateFields->Add(gateHelp, 0, wxEXPAND | wxBOTTOM, FromDIP(10));
    fields->Add(m_timeGateFields, 0, wxEXPAND);
    auto* scope = new wxStaticText(
        options, wxID_ANY,
        Display("기준면, 파 정의와 포트/전류 규약을 확인해야 합니다.\n복소 Z0는 보존하되 현재 변환에서는 지원하지 "
                "않습니다.\n계산 완료는 수렴 또는 실물 검증 완료를 뜻하지 않습니다."));
    scope->Wrap(FromDIP(410));
    StudioTheme::BindSecondary(*scope);
    fields->Add(scope, 0, wxEXPAND | wxTOP, FromDIP(8));
    optionLayout->Add(fields, 1, wxEXPAND | wxALL, FromDIP(16));
    auto* sourceLayout = new wxBoxSizer(wxVERTICAL);
    auto* sourceTitle = new wxStaticText(options, wxID_ANY, Display("원본 조건과 출처"));
    StudioTheme::Heading(*sourceTitle);
    sourceLayout->Add(sourceTitle, 0, wxBOTTOM, FromDIP(8));
    m_source = new wxTextCtrl(options, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(350, 320)),
                              wxTE_MULTILINE | wxTE_READONLY);
    sourceLayout->Add(m_source, 1, wxEXPAND);
    optionLayout->Add(sourceLayout, 1, wxEXPAND | wxTOP | wxRIGHT | wxBOTTOM, FromDIP(16));
    options->SetSizer(optionLayout);
    m_tabs->AddPage(options, Display("변환 조건"), true);
    auto* result = new wxScrolledWindow(m_tabs, wxID_ANY);
    result->SetScrollRate(FromDIP(16), FromDIP(16));
    auto* resultLayout = new wxBoxSizer(wxVERTICAL);
    m_pageLabel = new wxStaticText(result, wxID_ANY, Display("검토 전 / 표시할 후보가 없습니다."));
    m_pageLabel->Wrap(FromDIP(980));
    resultLayout->Add(m_pageLabel, 0, wxEXPAND | wxBOTTOM, FromDIP(8));
    auto* graphs = new wxBoxSizer(wxHORIZONTAL);
    m_originalGraph = new NetworkChart(result);
    m_resultGraph = new NetworkChart(result);
    graphs->Add(m_originalGraph, 1, wxEXPAND | wxRIGHT, FromDIP(12));
    graphs->Add(m_resultGraph, 1, wxEXPAND);
    resultLayout->Add(graphs, 1, wxEXPAND | wxBOTTOM, FromDIP(12));
    m_samples =
        new wxListCtrl(result, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 180)), wxLC_REPORT | wxLC_SINGLE_SEL);
    m_samples->SetName("network.transform.samples");
    const std::array<std::pair<const char*, int>, 6> columns{{{"주파수 (Hz)", 155},
                                                              {"원본 실수", 145},
                                                              {"원본 허수", 145},
                                                              {"변환 실수", 145},
                                                              {"변환 허수", 145},
                                                              {"표본 상태", 160}}};
    for (std::size_t index = 0; index < columns.size(); ++index)
    {
        m_samples->InsertColumn(static_cast<int>(index), Display(columns[index].first), wxLIST_FORMAT_LEFT,
                                FromDIP(columns[index].second));
    }
    StudioTheme::Table(*m_samples);
    resultLayout->Add(m_samples, 1, wxEXPAND);
    auto* resultOuter = new wxBoxSizer(wxVERTICAL);
    resultOuter->Add(resultLayout, 1, wxEXPAND | wxALL, FromDIP(16));
    result->SetSizer(resultOuter);
    m_tabs->AddPage(result, Display("변환 후보"));
    auto* diagnostics = new wxScrolledWindow(m_tabs, wxID_ANY);
    diagnostics->SetScrollRate(FromDIP(16), FromDIP(16));
    auto* diagnosticLayout = new wxBoxSizer(wxVERTICAL);
    m_resultConditions = new wxTextCtrl(diagnostics, wxID_ANY, wxEmptyString, wxDefaultPosition,
                                        FromDIP(wxSize(-1, 185)), wxTE_MULTILINE | wxTE_READONLY);
    Field(diagnostics, diagnosticLayout, "변환 후 조건과 원문 보존", m_resultConditions);
    m_diagnostics = new wxTextCtrl(diagnostics, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 190)),
                                   wxTE_MULTILINE | wxTE_READONLY);
    diagnosticLayout->Add(new wxStaticText(diagnostics, wxID_ANY, Display("계산 진단 / 미리보기 최대 8개")), 0,
                          wxBOTTOM, FromDIP(4));
    diagnosticLayout->Add(m_diagnostics, 1, wxEXPAND);
    auto* diagnosticOuter = new wxBoxSizer(wxVERTICAL);
    diagnosticOuter->Add(diagnosticLayout, 1, wxEXPAND | wxALL, FromDIP(16));
    diagnostics->SetSizer(diagnosticOuter);
    m_tabs->AddPage(diagnostics, Display("조건과 진단"));
    layout->Add(m_tabs, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    m_status = new wxStaticText(this, wxID_ANY, wxEmptyString);
    layout->Add(m_status, 0, wxEXPAND | wxALL, FromDIP(16));
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    auto* close = new wxButton(this, wxID_CANCEL, Display("닫기"));
    m_preview = new wxButton(this, wxID_ANY, Display("변환 검토"));
    m_preview->SetName("network.transform.preview");
    m_apply = new wxButton(this, wxID_APPLY, Display("검토한 결과 저장"));
    m_apply->SetName("network.transform.apply");
    actions->AddStretchSpacer();
    for (auto* button : {close, m_preview, m_apply})
    {
        StudioTheme::Button(*button, button == m_apply);
        actions->Add(button, 0, wxLEFT, FromDIP(8));
    }
    layout->Add(actions, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(16));
    SetSizer(layout);
    m_datasets->Bind(wxEVT_CHOICE,
                     [this](wxCommandEvent&)
                     {
                         SelectDataset();
                     });
    for (auto* input : {m_name, m_reference, m_lines, m_gateStart, m_gateStop})
    {
        input->Bind(wxEVT_TEXT,
                    [this](wxCommandEvent&)
                    {
                        Changed();
                    });
    }
    for (auto* input : {m_mode, m_kind, m_leftFixture, m_rightFixture})
    {
        input->Bind(wxEVT_CHOICE,
                    [this](wxCommandEvent&)
                    {
                        Changed();
                    });
    }
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
}

void NetworkTransformDialog::ClearReview()
{
    InvalidateRead();
    m_review = nullptr;
    m_reviewInput = nullptr;
    m_resultGraph->Clear();
    m_samples->DeleteAllItems();
    m_pageLabel->SetLabel(Display("검토 전 / 입력이 바뀌면 변환 후보를 다시 확인해야 합니다."));
    m_resultConditions->ChangeValue(wxEmptyString);
    m_diagnostics->ChangeValue(wxEmptyString);
}

void NetworkTransformDialog::Changed()
{
    if (m_loading || !Editable() || m_pending)
    {
        return;
    }
    m_dirty = true;
    ClearReview();
    UpdateActions();
}

void NetworkTransformDialog::SelectDataset()
{
    if (m_loading || !Editable() || m_pending)
    {
        return;
    }
    ClearReview();
    m_selection = nullptr;
    RenderSource();
    const int selected = m_datasets->GetSelection();
    if (selected < 0)
    {
        UpdateActions();
        return;
    }
    const Json id = m_context.at("datasets").at(selected).at("id");
    Request("network.get",
            {{"expected_revision", m_revision},
             {"dataset_id", id},
             {"offset", 0},
             {"limit", 201},
             {"row", 0},
             {"column", 0}},
            false,
            [this, id](const Json& result)
            {
                if (result.at("entry").at("id") != id || result.at("page").at("offset") != 0 ||
                    result.at("page").at("channel").at("row") != 0 || result.at("page").at("channel").at("column") != 0)
                {
                    throw std::runtime_error("선택한 원본 자료와 응답의 채널/표본 범위가 다릅니다.");
                }
                m_selection = result;
                RenderSource();
            });
}

void NetworkTransformDialog::RenderSource()
{
    if (m_selection.is_null())
    {
        m_source->ChangeValue(Display("변환할 원본 자료를 선택하세요. 원본 조건이 없으면 임의로 채우지 않습니다."));
        m_originalGraph->Clear();
        return;
    }
    m_source->ChangeValue(Display(Conditions(m_selection.at("descriptor"))));
    m_originalGraph->SetFrequencyUnit(StudioFrequency::ForDescriptor(m_selection.at("descriptor")).unit);
    m_originalGraph->SetPage(m_selection.at("page"),
                             Display("원본 " + Value(m_selection.at("descriptor").at("parameter_kind")) + "11"));
}

Json NetworkTransformDialog::Input() const
{
    Json options;
    if (m_mode->GetSelection() == 0)
    {
        options = {{"operation", "convert"}, {"parameter_kind", Utf8(m_kind->GetStringSelection())}};
    }
    else if (m_mode->GetSelection() == 1)
    {
        options = {
            {"operation", "renormalize"},
            {"reference", {{"text", Utf8(m_reference->GetValue())}, {"unit", "ohm"}, {"source_refs", Json::array()}}}};
    }
    else if (m_mode->GetSelection() == 2)
    {
        options = {{"operation", "shift_plane"}, {"line_table", Utf8(m_lines->GetValue())}};
    }
    else if (m_mode->GetSelection() == 3)
    {
        options = {{"operation", "deembed_fixtures"},
                   {"left_id", m_context.at("datasets").at(m_leftFixture->GetSelection()).at("id")},
                   {"right_id", m_context.at("datasets").at(m_rightFixture->GetSelection()).at("id")}};
    }
    else
    {
        options = {{"operation", "time_gate"}, {"start_ns", Utf8(m_gateStart->GetValue())},
                   {"stop_ns", Utf8(m_gateStop->GetValue())}};
    }
    return {
        {"expected_revision", m_revision},
        {"operation", "transform"},
        {"parameters",
         {{"name", Utf8(m_name->GetValue())}, {"dataset_id", m_selection.at("entry").at("id")}, {"options", options}}}};
}

void NetworkTransformDialog::Preview()
{
    if (!m_preview->IsEnabled())
    {
        return;
    }
    const Json input = Input();
    ClearReview();
    Request("network.preview", input, false,
            [this, input](const Json& result)
            {
                if (result.at("project_id") != m_projectId || result.at("revision_id") != m_revision ||
                    (result.value("can_apply", false) && result.at("operation") != "transform"))
                {
                    throw std::runtime_error("변환 후보의 프로젝트, 개정 또는 작업이 다릅니다.");
                }
                m_review = result;
                m_reviewInput = input;
                if (result.value("can_apply", false))
                {
                    RenderResult(result);
                    m_tabs->SetSelection(1);
                    SetStatus("변환 후보를 검토했습니다. 저장하면 원본과 구분되는 새 자료가 추가됩니다.");
                }
                else
                {
                    std::string message = "변환할 수 없습니다. 원본과 입력을 유지합니다.";
                    for (const auto& issue : result.at("issues"))
                    {
                        message += "\n" + issue.value("message", "입력 확인 필요");
                    }
                    SetStatus(message);
                }
            });
}

void NetworkTransformDialog::RenderResult(const Json& result)
{
    const auto& page = result.at("page");
    const std::string sourceKind = Value(m_selection.at("descriptor").at("parameter_kind"));
    const std::string targetKind = Value(result.at("descriptor").at("parameter_kind"));
    const auto frequencyScale = StudioFrequency::ForDescriptor(result.at("descriptor"));
    m_resultGraph->SetFrequencyUnit(frequencyScale.unit);
    m_resultGraph->SetPage(page, Display("변환 " + targetKind + "11"));
    m_samples->DeleteAllItems();
    wxListItem frequencyColumn;
    frequencyColumn.SetText(Display("주파수 (" + frequencyScale.unit + ")"));
    m_samples->SetColumn(0, frequencyColumn);
    const std::string sourceUnit = Value(m_selection.at("descriptor").at("unit"));
    const std::string targetUnit = Value(result.at("descriptor").at("unit"));
    const std::array<std::string, 4> labels{
        sourceKind + "11 실수 (" + sourceUnit + ")", sourceKind + "11 허수 (" + sourceUnit + ")",
        targetKind + "11 실수 (" + targetUnit + ")", targetKind + "11 허수 (" + targetUnit + ")"};
    for (std::size_t index = 0; index < labels.size(); ++index)
    {
        wxListItem column;
        column.SetText(Display(labels[index]));
        m_samples->SetColumn(static_cast<int>(index + 1), column);
    }
    for (const auto& sample : page.at("samples"))
    {
        const long row = m_samples->InsertItem(
            m_samples->GetItemCount(), Display(StudioFrequency::Value(sample.at("frequency_hz"), frequencyScale)));
        m_samples->SetItem(row, 1, Display("범위 밖"));
        m_samples->SetItem(row, 2, Display("범위 밖"));
        for (const auto& original : m_selection.at("page").at("samples"))
        {
            if (sample.at("frequency_hz") == original.at("frequency_hz"))
            {
                m_samples->SetItem(row, 1, Display(Value(original.at("real"))));
                m_samples->SetItem(row, 2, Display(Value(original.at("imag"))));
                break;
            }
        }
        m_samples->SetItem(row, 3, Display(Value(sample.at("real"))));
        m_samples->SetItem(row, 4, Display(Value(sample.at("imag"))));
        m_samples->SetItem(row, 5, Display(Value(sample.at("status"))));
    }
    m_pageLabel->SetLabel(Display("읽기 전용 후보 / 11 채널의 앞 " + std::to_string(page.at("samples").size()) + " / " +
                                  Value(page.at("total")) + "개 표본. 두 그래프는 각 자료의 단위/축으로 표시합니다."));
    m_pageLabel->Wrap(FromDIP(980));
    m_resultConditions->ChangeValue(Display(Conditions(result.at("descriptor"))));
    std::string diagnostics = "표시 " + std::to_string(result.at("diagnostics").size()) + " / 전체 " +
                              Value(result.at("diagnostic_count")) + "개. 저장하면 전체 계산 진단을 함께 보존합니다.\n";
    const auto& rows = result.at("diagnostics");
    if (!rows.empty() && rows.front().contains("retained_bins"))
    {
        const auto& gate = rows.front();
        const auto& interval = gate.at("selected_bin_range_ns");
        diagnostics += "\n시간 게이트 " + Value(gate.at("retained_bins")) + " / " + Value(gate.at("total_bins")) +
            "개 지연 표본 | 지연 간격 " + Value(gate.at("time_step_ns")) + " ns | 주기 " +
            Value(gate.at("period_ns")) + " ns\n남긴 지연 " + Value(interval.at(0)) +
            "~" + Value(interval.at(1)) + " ns\n";
    }
    for (const auto& item : result.at("diagnostics"))
    {
        diagnostics += "\n" + StudioFrequency::Value(item.at("frequency_hz"), frequencyScale) + " " +
                       frequencyScale.unit + ": " + Value(item.at("status"));
        if (item.contains("valid_channels"))
        {
            diagnostics += " / 유효 복소 채널 " + Value(item.at("valid_channels")) + "개";
        }
        else if (item.contains("fixture_condition_numbers"))
        {
            const auto& fixtures = item.at("fixture_condition_numbers");
            diagnostics += " / 치구 조건수 왼쪽 " + Value(fixtures.at(0)) + " / 오른쪽 " + Value(fixtures.at(1)) +
                " / 재결합 상대 잔차 " + Value(item.at("relative_residual"));
        }
        else if (!item.contains("retained_bins"))
        {
            diagnostics += " / 조건수 " + Value(item.value("condition_number", Json(nullptr))) + " / 상대 잔차 " +
                           Value(item.value("relative_residual", Json(nullptr)));
        }
        if (item.contains("first_conversion"))
        {
            const auto& first = item.at("first_conversion");
            diagnostics += "\n  첫 변환: " + Value(first.at("status")) + " / 조건수 " +
                           Value(first.value("condition_number", Json(nullptr))) + " / 상대 잔차 " +
                           Value(first.value("relative_residual", Json(nullptr)));
        }
    }
    diagnostics += "\n\n전체 표본/진단은 저장 후 결과 화면에서 조회합니다. 계산 진단은 실물 정확도 검증이 아닙니다.";
    m_diagnostics->ChangeValue(Display(diagnostics));
}

void NetworkTransformDialog::Apply()
{
    if (!Editable() || m_pending || m_review.is_null() || !m_review.value("can_apply", false) || m_selection.is_null())
    {
        return;
    }
    if (Input() != m_reviewInput)
    {
        ClearReview();
        SetStatus("입력이 검토한 후보와 다릅니다. 다시 검토하세요.");
        UpdateActions();
        return;
    }
    Json input = m_reviewInput;
    input["command_id"] = Uuid();
    input["review_hash"] = m_review.at("review_hash");
    Request("network.apply", input, true,
            [this](const Json& result)
            {
                if (result.at("operation") != "transform")
                {
                    throw std::runtime_error("변환 적용 응답의 작업이 다릅니다.");
                }
                AcceptMutation(result);
                m_dirty = false;
                m_review = nullptr;
                m_reviewInput = nullptr;
                CloseDialog();
            });
}

bool NetworkTransformDialog::HasDraft() const
{
    return m_dirty || (!m_review.is_null() && m_review.value("can_apply", false));
}

void NetworkTransformDialog::UpdateActions()
{
    if (!m_apply)
    {
        return;
    }
    const bool enabled = Editable() && !m_pending;
    for (auto* input : std::vector<wxWindow*>{m_datasets, m_mode, m_name})
    {
        input->Enable(enabled);
    }
    m_kind->Enable(enabled && m_mode->GetSelection() == 0);
    m_reference->Enable(enabled && m_mode->GetSelection() == 1);
    const bool shift = m_mode->GetSelection() == 2;
    const bool fixtures = m_mode->GetSelection() == 3;
    const bool gate = m_mode->GetSelection() == 4;
    if (m_lines->IsShown() != shift || m_leftFixture->IsShown() != fixtures || m_gateStart->IsShown() != gate)
    {
        m_lineFields->ShowItems(shift);
        m_fixtureFields->ShowItems(fixtures);
        m_timeGateFields->ShowItems(gate);
        auto* options = static_cast<wxScrolledWindow*>(m_lines->GetParent());
        options->Layout();
        options->FitInside();
    }
    m_lines->Enable(enabled && shift);
    m_leftFixture->Enable(enabled && fixtures);
    m_rightFixture->Enable(enabled && fixtures);
    const bool chosen = m_leftFixture->GetSelection() != wxNOT_FOUND && m_rightFixture->GetSelection() != wxNOT_FOUND;
    m_gateStart->Enable(enabled && gate);
    m_gateStop->Enable(enabled && gate);
    const bool interval = !m_gateStart->GetValue().Trim().Trim(false).empty() &&
                          !m_gateStop->GetValue().Trim().Trim(false).empty();
    m_preview->Enable(enabled && !m_selection.is_null() && (!fixtures || chosen) && (!gate || interval));
    m_apply->Enable(enabled && !m_review.is_null() && m_review.value("can_apply", false));
}

void NetworkTransformDialog::ShowRequestFailure(const Json& error)
{
    ClearReview();
    ProjectSetupDialog::ShowRequestFailure(error);
}
