/** @file @brief 현재 결과의 이름/실제 표본과 미정 조건을 같은 선택에 맞춰 표시한다. */
#include "network_panel.h"
#include "network_chart.h"
#include "result_presentation.h"
#include "studio_notebook.h"
#include "studio_theme.h"
#include "frequency_display.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/listctrl.h>
#include <wx/scrolwin.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <wx/wrapsizer.h>
#include <algorithm>
#include <array>

namespace
{
wxString Display(const std::string& text)
{
    return wxString::FromUTF8(text.data(), text.size());
}

std::string Text(const Json& value)
{
    if (value.is_null() || value == "unknown" || value == "")
    {
        return "미정";
    }
    return value.is_string() ? value.get<std::string>() : value.dump();
}

/** @brief 무한대와 정의 불가를 서비스 상태에 따라 미정과 구분한다. */
wxString Value(const Json& sample, const std::string& key)
{
    if (sample.contains(key) && sample.at(key).is_number())
    {
        return wxString::Format("%.8g", sample.at(key).get<double>());
    }
    const auto state = sample.value(key == "phase_deg" ? "phase_state" : key + "_state", "missing");
    if (state == "negative_infinity")
    {
        return Display("-inf (크기 0)");
    }
    if (state == "positive_infinity")
    {
        return "+inf";
    }
    if (state == "undefined_zero_magnitude" || state == "undefined_active")
    {
        return Display("정의 불가");
    }
    if (state == "not_applicable")
    {
        return Display("해당 없음");
    }
    if (state == "nonfinite")
    {
        return Display("유한값 없음");
    }
    return Display("미정");
}

std::string Kind(const std::string& kind)
{
    if (kind == "imported")
    {
        return "가져온 원문";
    }
    if (kind == "solver")
    {
        return "계산 결과";
    }
    return "파생 결과";
}

/** @brief 서비스의 표본 상태/출처 원문을 보존하고 표시 문자열만 번역한다. */
std::string SampleLabel(const Json& value, bool origin)
{
    static const std::map<std::string, std::string> statuses{
        {"valid", "유효"},         {"missing", "미정"},
        {"singular", "특이"},      {"ill_conditioned", "수치 불안정"},
        {"unsupported", "미지원"}, {"outside_validity", "적용 범위 밖"},
        {"nonfinite", "비유한"}};
    static const std::map<std::string, std::string> origins{{"computed", "계산"},        {"measured", "측정"},
                                                            {"imported", "가져온 자료"}, {"derived", "파생"},
                                                            {"interpolated", "보간"},    {"unknown", "미정"}};
    const auto& labels = origin ? origins : statuses;
    const std::string key = value.is_string() ? value.get<std::string>() : "";
    const auto found = labels.find(key);
    return found == labels.end() ? Text(value) : found->second;
}

const std::array<const char*, 6> Metrics{{"magnitude_db", "magnitude", "phase_deg", "real", "imag", "vswr"}};
}

NetworkPanel::NetworkPanel(wxWindow* centerParent, wxWindow* navigationParent, wxWindow* conditionsParent)
    : wxPanel(centerParent)
{
    StudioTheme::BindSurface(*this);
    BuildNavigation(navigationParent);
    BuildConditions(conditionsParent);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* actions = new wxWrapSizer(wxHORIZONTAL);
    const std::vector<std::pair<NetworkAction, const char*>> commands{
        {NetworkAction::Import, "가져오기"},      {NetworkAction::Solver, "해석 결과 등록"},
        {NetworkAction::Circuit, "RLC 정합"},     {NetworkAction::Assessment, "목표 평가"},
        {NetworkAction::Transform, "변환"},       {NetworkAction::Export, "내보내기"},
        {NetworkAction::Diagnostics, "계산 진단"}};
    for (const auto& command : commands)
    {
        auto* button =
            new wxButton(this, wxID_ANY, Display(command.second), wxDefaultPosition, wxDefaultSize, wxBU_EXACTFIT);
        StudioTheme::Button(*button);
        actions->Add(button, 0, wxALL, FromDIP(4));
        m_actions.emplace(command.first, button);
        button->Bind(wxEVT_BUTTON,
                     [this, action = command.first](wxCommandEvent&)
                     {
                         if (onAction)
                         {
                             onAction(action);
                         }
                     });
    }
    layout->Add(actions, 0, wxEXPAND | wxALL, FromDIP(4));
    m_heading = new wxStaticText(this, wxID_ANY, Display("네트워크 결과"), wxDefaultPosition, wxDefaultSize,
                                 wxST_ELLIPSIZE_END);
    StudioTheme::Title(*m_heading);
    layout->Add(m_heading, 0, wxLEFT | wxRIGHT | wxTOP, FromDIP(12));
    auto* controls = new wxWrapSizer(wxHORIZONTAL);
    controls->Add(new wxStaticText(this, wxID_ANY, Display("채널")), 0, wxALL | wxALIGN_CENTER_VERTICAL, FromDIP(8));
    m_channel = new wxChoice(this, wxID_ANY);
    m_channel->SetMinSize(FromDIP(wxSize(100, 32)));
    m_channel->SetName(Display("결과 행렬 채널"));
    controls->Add(m_channel, 0, wxALL | wxALIGN_CENTER_VERTICAL, FromDIP(4));
    m_metric = new wxChoice(this, wxID_ANY);
    for (const auto* label : {"크기 (dB)", "크기", "위상 (deg)", "실수부", "허수부", "VSWR"})
    {
        m_metric->Append(Display(label));
    }
    m_metric->SetSelection(0);
    m_metric->SetMinSize(FromDIP(wxSize(150, 32)));
    m_metric->SetName(Display("결과 표시 지표"));
    controls->Add(m_metric, 0, wxALL | wxALIGN_CENTER_VERTICAL, FromDIP(4));
    controls->Add(new wxStaticText(this, wxID_ANY, Display("주파수")), 0, wxALL | wxALIGN_CENTER_VERTICAL, FromDIP(4));
    m_frequencyUnit = new wxChoice(this, wxID_ANY);
    for (const auto* unit : {"자동", "Hz", "kHz", "MHz", "GHz"})
    {
        m_frequencyUnit->Append(Display(unit));
    }
    m_frequencyUnit->SetSelection(0);
    m_frequencyUnit->SetMinSize(FromDIP(wxSize(88, 32)));
    m_frequencyUnit->SetName("network.frequency-unit");
    m_frequencyUnit->SetToolTip(Display("표와 곡선의 표시 단위만 바꿉니다. 원본 Hz 값은 유지됩니다."));
    controls->Add(m_frequencyUnit, 0, wxALL | wxALIGN_CENTER_VERTICAL, FromDIP(4));
    m_previous = new wxButton(this, wxID_ANY, Display("이전 표본"));
    m_next = new wxButton(this, wxID_ANY, Display("다음 표본"));
    StudioTheme::Button(*m_previous);
    StudioTheme::Button(*m_next);
    controls->Add(m_previous, 0, wxALL | wxALIGN_CENTER_VERTICAL, FromDIP(4));
    controls->Add(m_next, 0, wxALL | wxALIGN_CENTER_VERTICAL, FromDIP(4));
    m_pageLabel = new wxStaticText(this, wxID_ANY, wxEmptyString);
    controls->Add(m_pageLabel, 0, wxALL | wxALIGN_CENTER_VERTICAL, FromDIP(8));
    layout->Add(controls, 0, wxEXPAND);
    m_status = new wxStaticText(this, wxID_ANY, Display("프로젝트를 열고 결과를 선택하세요."));
    StudioTheme::BindSecondary(*m_status);
    layout->Add(m_status, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(12));
    m_chart = new NetworkChart(this);
    layout->Add(m_chart, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    m_marker = new wxStaticText(this, wxID_ANY, Display("표본을 선택하면 같은 실제 값을 확인합니다."));
    layout->Add(m_marker, 0, wxEXPAND | wxALL, FromDIP(8));
    m_samples = new wxListCtrl(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 120)),
                               wxLC_REPORT | wxLC_SINGLE_SEL | wxLC_HRULES);
    StudioTheme::Table(*m_samples);
    const std::vector<std::pair<const char*, int>> columns{{"표본", 64},    {"주파수 / Hz", 128}, {"실수부", 108},
                                                           {"허수부", 108}, {"크기 / dB", 128},   {"위상 / deg", 108},
                                                           {"VSWR", 110},   {"상태 / 출처", 200}};
    for (const auto& column : columns)
    {
        m_samples->AppendColumn(Display(column.first), wxLIST_FORMAT_LEFT, FromDIP(column.second));
    }
    m_samples->SetName(Display("네트워크 실제 복소 표본"));
    layout->Add(m_samples, 0, wxEXPAND | wxALL, FromDIP(8));
    SetSizer(layout);
    m_channel->Bind(wxEVT_CHOICE,
                    [this](wxCommandEvent&)
                    {
                        RequestSelected();
                    });
    m_metric->Bind(wxEVT_CHOICE,
                   [this](wxCommandEvent&)
                   {
                       UpdateMetric();
                   });
    m_frequencyUnit->Bind(wxEVT_CHOICE,
                          [this](wxCommandEvent&)
                          {
                              UpdateFrequencyDisplay();
                          });
    m_previous->Bind(wxEVT_BUTTON,
                     [this](wxCommandEvent&)
                     {
                         if (m_selection.is_object())
                         {
                             RequestSelected(std::max(0, m_selection.at("page").value("offset", 0) - 201));
                         }
                     });
    m_next->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     if (!m_selection.is_object())
                     {
                         return;
                     }
                     const auto next = m_selection.at("page").value("next_offset", Json(nullptr));
                     if (next.is_number_integer())
                     {
                         RequestSelected(next.get<int>());
                     }
                 });
    m_samples->Bind(wxEVT_LIST_ITEM_SELECTED,
                    [this](wxListEvent& event)
                    {
                        SelectMarker(event.GetIndex());
                    });
    Bind(wxEVT_SIZE,
         [this](wxSizeEvent& event)
         {
             m_status->Wrap(std::max(FromDIP(280), GetClientSize().x - FromDIP(24)));
             event.Skip();
         });
    UpdateActions();
}

NetworkPanel::~NetworkPanel()
{
    onSelect = {};
    onAction = {};
    onRefresh = {};
}

void NetworkPanel::BuildNavigation(wxWindow* parent)
{
    auto* navigation = new wxPanel(parent);
    m_navigation = navigation;
    StudioTheme::BindSurface(*navigation);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* heading = new wxStaticText(navigation, wxID_ANY, Display("결과 자료"));
    StudioTheme::Heading(*heading);
    layout->Add(heading, 0, wxALL, FromDIP(12));
    m_results = new wxListCtrl(navigation, wxID_ANY, wxDefaultPosition, wxDefaultSize,
                               wxLC_REPORT | wxLC_SINGLE_SEL | wxLC_HRULES);
    StudioTheme::Table(*m_results);
    m_results->AppendColumn(Display("이름"), wxLIST_FORMAT_LEFT, FromDIP(172));
    m_results->AppendColumn(Display("종류"), wxLIST_FORMAT_LEFT, FromDIP(100));
    m_results->SetName(Display("프로젝트 네트워크 자료 목록"));
    layout->Add(m_results, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(4));
    m_refresh = new wxButton(navigation, wxID_ANY, Display("자료 다시 읽기"));
    StudioTheme::Button(*m_refresh);
    layout->Add(m_refresh, 0, wxEXPAND | wxALL, FromDIP(8));
    navigation->SetSizer(layout);
    wxWeakRef<NetworkPanel> owner(this);
    m_results->Bind(wxEVT_LIST_ITEM_SELECTED,
                    [owner](wxListEvent& event)
                    {
                        if (owner && !owner->m_rebuilding && event.GetIndex() >= 0 &&
                            static_cast<std::size_t>(event.GetIndex()) < owner->m_ids.size())
                        {
                            owner->m_dataset = owner->m_ids[static_cast<std::size_t>(event.GetIndex())];
                            owner->m_channel->Clear();
                            owner->m_channels.clear();
                            owner->RequestSelected();
                        }
                    });
    m_refresh->Bind(wxEVT_BUTTON,
                    [owner](wxCommandEvent&)
                    {
                        if (owner && owner->onRefresh)
                        {
                            owner->onRefresh();
                        }
                    });
}

void NetworkPanel::BuildConditions(wxWindow* parent)
{
    auto* conditions = new wxPanel(parent);
    m_conditions = conditions;
    StudioTheme::BindSurface(*conditions);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    m_conditionHeading = new wxStaticText(conditions, wxID_ANY, Display("결과 조건"), wxDefaultPosition, wxDefaultSize,
                                          wxST_ELLIPSIZE_END);
    StudioTheme::Title(*m_conditionHeading);
    layout->Add(m_conditionHeading, 0, wxALL, FromDIP(12));
    auto* pages = new StudioNotebook(conditions);
    auto* summary = new wxScrolledWindow(pages, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL);
    summary->SetScrollRate(0, FromDIP(12));
    auto* summaryLayout = new wxBoxSizer(wxVERTICAL);
    m_conditionSummary = new wxStaticText(summary, wxID_ANY, Display("결과를 선택하세요."));
    summaryLayout->Add(m_conditionSummary, 0, wxEXPAND | wxALL, FromDIP(12));
    summary->SetSizer(summaryLayout);
    pages->AddPage(summary, Display("조건"));
    m_source = new wxTextCtrl(pages, wxID_ANY, wxEmptyString, wxDefaultPosition, wxDefaultSize,
                              wxTE_MULTILINE | wxTE_READONLY);
    m_source->SetName(Display("결과 출처와 원문 조건"));
    pages->AddPage(m_source, Display("출처"));
    layout->Add(pages, 1, wxEXPAND);
    auto* notice = new wxStaticText(
        conditions, wxID_ANY,
        Display("계산 / 목표 평가 / 수렴 / 실측 검증은 별도 상태입니다. 미정 조건을 자동 확정하지 않습니다."));
    notice->Wrap(FromDIP(290));
    StudioTheme::BindSecondary(*notice);
    layout->Add(notice, 0, wxEXPAND | wxALL, FromDIP(12));
    conditions->SetSizer(layout);
}

wxWindow* NetworkPanel::NavigationView() const
{
    return m_navigation.get();
}
wxWindow* NetworkPanel::ConditionsView() const
{
    return m_conditions.get();
}
const Json& NetworkPanel::Library() const
{
    return m_library;
}
const Json& NetworkPanel::Selection() const
{
    return m_selection;
}
const std::string& NetworkPanel::DatasetId() const
{
    return m_dataset;
}

void NetworkPanel::SetLibrary(const Json& context, const std::string& preferredId)
{
    m_library = context;
    m_rebuilding = true;
    m_results->DeleteAllItems();
    m_ids.clear();
    const std::string desired = preferredId.empty() ? m_dataset : preferredId;
    long selected = -1;
    for (const auto& entry : context.value("datasets", Json::array()))
    {
        const auto row = m_results->InsertItem(m_results->GetItemCount(), Display(entry.at("name")));
        m_results->SetItem(row, 1, Display(Kind(entry.at("kind"))));
        m_ids.push_back(entry.at("id"));
        if (m_ids.back() == desired)
        {
            selected = row;
        }
    }
    if (selected < 0 && !m_ids.empty())
    {
        selected = 0;
    }
    m_dataset = selected < 0 ? "" : m_ids[static_cast<std::size_t>(selected)];
    if (selected >= 0)
    {
        m_results->SetItemState(selected, wxLIST_STATE_SELECTED, wxLIST_STATE_SELECTED);
        m_results->EnsureVisible(selected);
    }
    m_rebuilding = false;
    ClearSelection(m_ids.empty() ? "등록된 결과가 없습니다. 원문 파일이나 완료된 해석 결과를 명시적으로 가져오세요."
                                 : "선택한 결과를 읽습니다.");
}

void NetworkPanel::ClearSelection(const std::string& message)
{
    m_selection = nullptr;
    m_markerRow = -1;
    m_chart->Clear();
    m_chart->Hide();
    m_samples->DeleteAllItems();
    m_samples->Hide();
    m_marker->Hide();
    m_pageLabel->SetLabel(wxEmptyString);
    m_marker->SetLabel(Display("표본을 선택하면 같은 실제 값을 확인합니다."));
    m_heading->SetLabel(Display("네트워크 결과"));
    m_conditionHeading->SetLabel(Display("결과 조건"));
    m_conditionSummary->SetLabel(Display("표시할 결과를 조회해야 합니다."));
    m_source->Clear();
    SetStatus(message);
    UpdateActions();
}

void NetworkPanel::Clear(const std::string& message)
{
    m_library = Json::object();
    m_dataset.clear();
    m_ids.clear();
    m_results->DeleteAllItems();
    m_channel->Clear();
    m_channels.clear();
    ClearSelection(message);
}

void NetworkPanel::SetResult(const Json& result)
{
    m_selection = result;
    m_markerRow = -1;
    m_dataset = result.at("entry").at("id");
    m_rebuilding = true;
    m_results->SetItemState(-1, 0, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
    for (std::size_t index = 0; index < m_ids.size(); ++index)
    {
        if (m_ids[index] == m_dataset)
        {
            const auto row = static_cast<long>(index);
            m_results->SetItemState(row, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED,
                                    wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
            m_results->EnsureVisible(row);
            break;
        }
    }
    m_rebuilding = false;
    m_results->Refresh();
    m_heading->SetLabel(Display(result.at("entry").at("name")));
    const auto& descriptor = result.at("descriptor");
    const auto& page = result.at("page");
    const int count = static_cast<int>(descriptor.at("port_ids").size());
    m_channel->Clear();
    m_channels.clear();
    for (int row = 0; row < count; ++row)
    {
        for (int column = 0; column < count; ++column)
        {
            m_channels.emplace_back(row, column);
            m_channel->Append(Display(descriptor.at("parameter_kind")) + wxString::Format("%d%d", row + 1, column + 1));
            if (page.at("channel").at("row") == row && page.at("channel").at("column") == column)
            {
                m_channel->SetSelection(static_cast<int>(m_channels.size() - 1));
            }
        }
    }
    if (descriptor.at("parameter_kind") != "S" && (m_metric->GetSelection() == 0 || m_metric->GetSelection() == 5))
    {
        m_metric->SetSelection(1);
    }
    m_chart->Show();
    m_samples->Show();
    m_marker->Show();
    m_chart->SetPage(page, Display(result.at("entry").at("name")));
    UpdateFrequencyDisplay();
    UpdateMetric();
    SetStatus("실제 표본 페이지입니다. 제작/측정 조건과 출처는 오른쪽에서 확인하세요.");
    UpdateActions();
}

void NetworkPanel::RequestSelected(int offset)
{
    if (m_busy || !m_available || m_dataset.empty() || !onSelect)
    {
        return;
    }
    const auto index = m_channel->GetSelection();
    const auto channel = index >= 0 && static_cast<std::size_t>(index) < m_channels.size()
                             ? m_channels[static_cast<std::size_t>(index)]
                             : std::make_pair(0, 0);
    onSelect(m_dataset, channel.first, channel.second, offset);
}

void NetworkPanel::SetEnabledState(bool available, bool busy)
{
    m_available = available;
    m_busy = busy;
    UpdateActions();
}

void NetworkPanel::SetStatus(const std::string& message)
{
    m_status->SetLabel(Display(message));
    m_status->Wrap(std::max(FromDIP(280), GetClientSize().x - FromDIP(24)));
    Layout();
}

void NetworkPanel::UpdateActions()
{
    const bool ready = m_available && !m_busy;
    const bool selected = ready && m_selection.is_object();
    m_results->Enable(ready);
    m_refresh->Enable(ready);
    m_channel->Enable(selected);
    m_metric->Enable(selected);
    m_frequencyUnit->Enable(selected);
    m_previous->Enable(selected && m_selection.at("page").value("offset", 0) > 0);
    m_next->Enable(selected && !m_selection.at("page").value("next_offset", Json(nullptr)).is_null());
    for (const auto& action : m_actions)
    {
        bool enabled = selected;
        if (action.first == NetworkAction::Import || action.first == NetworkAction::Circuit)
        {
            enabled = ready && m_library.contains("revision_id");
        }
        else if (action.first == NetworkAction::Solver)
        {
            enabled = ready && !m_library.value("solver_results", Json::array()).empty();
        }
        else if (action.first == NetworkAction::Assessment)
        {
            enabled = selected && !m_library.value("targets", Json::array()).empty();
        }
        else if (action.first == NetworkAction::Diagnostics)
        {
            enabled = selected && !m_selection.at("entry").value("diagnostics", Json(nullptr)).is_null();
        }
        action.second->Enable(enabled);
    }
}

void NetworkPanel::ShowSamples()
{
    m_samples->DeleteAllItems();
    const auto& page = m_selection.at("page");
    const auto scale = StudioFrequency::ForDescriptor(m_selection.at("descriptor"), FrequencyUnit());
    wxListItem frequencyColumn;
    frequencyColumn.SetText(Display("주파수 / " + scale.unit));
    m_samples->SetColumn(1, frequencyColumn);
    for (const auto& sample : page.at("samples"))
    {
        const auto row =
            m_samples->InsertItem(m_samples->GetItemCount(), wxString::Format("%d", sample.at("index").get<int>() + 1));
        const std::array<const char*, 6> keys{{"frequency_hz", "real", "imag", "magnitude_db", "phase_deg", "vswr"}};
        for (std::size_t index = 0; index < keys.size(); ++index)
        {
            m_samples->SetItem(row, static_cast<int>(index + 1),
                               index == 0 ? Display(StudioFrequency::Value(sample.at("frequency_hz"), scale, 9))
                                          : Value(sample, keys[index]));
        }
        m_samples->SetItem(
            row, 7, Display(SampleLabel(sample.at("status"), false) + " / " + SampleLabel(sample.at("origin"), true)));
    }
    const int offset = page.at("offset");
    m_pageLabel->SetLabel(Display("표본 ") + wxString::Format("%d-%d / %d", offset + 1,
                                                              offset + static_cast<int>(page.at("samples").size()),
                                                              page.at("total").get<int>()));
}

void NetworkPanel::UpdateMetric()
{
    const int selected = m_metric->GetSelection();
    if (selected < 0 || static_cast<std::size_t>(selected) >= Metrics.size())
    {
        return;
    }
    std::string unit = m_selection.is_object() ? m_selection.at("descriptor").value("unit", "") : "";
    const std::array<std::string, 6> labels{
        {"크기 / dB", "크기 / " + unit, "위상 / deg", "실수부 / " + unit, "허수부 / " + unit, "VSWR"}};
    m_chart->SetMetric(Metrics[static_cast<std::size_t>(selected)],
                       Display(labels[static_cast<std::size_t>(selected)]));
}

std::string NetworkPanel::FrequencyUnit() const
{
    static const std::array<std::string, 5> units{{"auto", "Hz", "kHz", "MHz", "GHz"}};
    const int index = m_frequencyUnit->GetSelection();
    return index >= 0 && static_cast<std::size_t>(index) < units.size() ? units[static_cast<std::size_t>(index)]
                                                                        : "auto";
}

void NetworkPanel::UpdateFrequencyDisplay()
{
    if (!m_selection.is_object())
    {
        return;
    }
    const auto scale = StudioFrequency::ForDescriptor(m_selection.at("descriptor"), FrequencyUnit());
    const long marker = m_markerRow;
    m_chart->SetFrequencyUnit(scale.unit);
    ShowSamples();
    ShowConditions();
    if (marker >= 0 && marker < m_samples->GetItemCount())
    {
        m_samples->SetItemState(marker, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED,
                                wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
        m_samples->EnsureVisible(marker);
        SelectMarker(marker);
    }
    Layout();
}

void NetworkPanel::SelectMarker(long row)
{
    if (!m_selection.is_object() || row < 0 ||
        static_cast<std::size_t>(row) >= m_selection.at("page").at("samples").size())
    {
        return;
    }
    const auto& sample = m_selection.at("page").at("samples").at(static_cast<std::size_t>(row));
    m_markerRow = row;
    m_chart->SetMarker(sample.at("index").get<int>());
    const auto scale = StudioFrequency::ForDescriptor(m_selection.at("descriptor"), FrequencyUnit());
    const wxString label = Display("M1 / " + StudioFrequency::WithUnit(sample.at("frequency_hz"), scale.unit)) +
                           " / Re " + Value(sample, "real") + " / Im " + Value(sample, "imag") + " / dB " +
                           Value(sample, "magnitude_db");
    m_marker->SetLabel(label);
    m_marker->Wrap(std::max(FromDIP(280), GetClientSize().x - FromDIP(16)));
    Layout();
}

void NetworkPanel::ShowConditions()
{
    const auto& descriptor = m_selection.at("descriptor");
    const auto& entry = m_selection.at("entry");
    m_conditionHeading->SetLabel(Display(entry.at("name")));
    m_conditionHeading->SetToolTip(Display(entry.at("name")));
    std::string summary =
        "자료: " + Kind(entry.at("kind")) + "\n행렬 / 단위: " + Text(descriptor.at("parameter_kind")) + " / " +
        Text(descriptor.at("unit")) + "\n표본: " + Text(descriptor.at("sample_count")) + "개\n주파수: " +
        StudioFrequency::Range(descriptor.at("frequency_min_hz"), descriptor.at("frequency_max_hz"), FrequencyUnit()) +
        "\n\n파 정의: " + ResultUi::State(descriptor.at("wave_definition")) +
        "\n시간 규약: " + Text(descriptor.at("phasor_convention"));
    const auto& names = descriptor.at("port_names");
    const auto& impedance = descriptor.at("z0_ohm");
    for (std::size_t index = 0; index < names.size(); ++index)
    {
        summary += "\n\n포트 " + std::to_string(index + 1) + ": " + Text(names[index]) +
                   "\n기준면: " + Text(descriptor.at("reference_planes")[index]) +
                   "\n모드: " + ResultUi::State(descriptor.at("port_modes")[index]) +
                   "\n전류 방향: " + ResultUi::State(descriptor.at("current_orientation")[index]);
        summary += "\n기준 임피던스 (ohm): " +
                   ResultUi::Complex(impedance.is_array() && index < impedance.size() ? impedance[index] : Json(nullptr));
    }
    if (descriptor.value("z0_frequency_dependent", false))
    {
        summary += "\nZ0는 주파수별입니다. 위 값은 첫 표본이며 전체 조건은 원본에 보존합니다.";
    }
    const auto& conditions = descriptor.at("conditions");
    const auto conditionState = [&conditions](const std::string& key)
    {
        if (conditions.is_null() ||
            (conditions.is_object() && conditions.contains(key) && conditions.at(key).is_null()))
        {
            return std::string("미정");
        }
        if (conditions.is_object() && conditions.contains(key))
        {
            return std::string("원문 기록 있음. 출처 탭에서 확인");
        }
        return std::string("상세 확인 필요. 확정 여부 자동 판정 안 함");
    };
    summary += "\n\n제작 조건: " + conditionState("manufacturing") + "\n측정 조건: " + conditionState("measurement") +
               "\n유효하지 않은 복소 값: " + Text(descriptor.at("invalid_value_count"));
    m_conditionSummary->SetLabel(Display(summary));
    m_conditionSummary->Wrap(FromDIP(278));
    auto* scrolled = static_cast<wxScrolledWindow*>(m_conditionSummary->GetParent());
    scrolled->Layout();
    scrolled->FitInside();
    Json evidence{{"조건 원문", descriptor.at("conditions")},
                  {"출처 기록", descriptor.at("source_refs")},
                  {"표본 출처", descriptor.at("sample_origins")},
                  {"생성 당시 snapshot", descriptor.at("source_snapshot")},
                  {"자료 원본과 파생 관계", entry}};
    m_source->ChangeValue(Display(evidence.dump(2, ' ', false, Json::error_handler_t::replace)));
    if (m_conditions)
    {
        m_conditions->Layout();
    }
}
