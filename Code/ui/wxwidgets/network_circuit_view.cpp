/** @file @brief native 입력과 표시 전용 회로 선도로 외부 정합망의 세 탭을 구성한다. */
#include "network_circuit_dialog.h"
#include "frequency_display.h"
#include "result_presentation.h"
#include "network_chart.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/wx.h>
#include <wx/dcbuffer.h>
#include <wx/listctrl.h>
#include <wx/scrolwin.h>
#include <algorithm>
#include <array>

/** @brief 선택/편집 원본을 소유하지 않는 이상 회로의 표시 전용 선도이다. */
class NetworkCircuitDrawing final : public wxScrolledWindow
{
public:
    explicit NetworkCircuitDrawing(wxWindow* parent)
        : wxScrolledWindow(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxHSCROLL)
    {
        SetBackgroundStyle(wxBG_STYLE_PAINT);
        SetScrollRate(FromDIP(16), 0);
        Bind(wxEVT_PAINT, &NetworkCircuitDrawing::Paint, this);
        SetMinSize(FromDIP(wxSize(390, 180)));
    }

    void SetElements(const Json& elements, int selected)
    {
        m_elements = elements;
        m_selected = selected;
        SetVirtualSize(FromDIP(std::max(430, 120 + static_cast<int>(elements.size()) * 145)), FromDIP(195));
        Refresh(false);
    }

private:
    void Paint(wxPaintEvent&)
    {
        wxAutoBufferedPaintDC dc(this);
        PrepareDC(dc);
        const auto colour = StudioTheme::Colours();
        dc.SetBackground(wxBrush(colour.content));
        dc.Clear();
        dc.SetFont(GetFont());
        dc.SetTextForeground(colour.secondary);
        const auto point = [this](int x, int y)
        {
            return wxPoint(FromDIP(x), FromDIP(y));
        };
        const auto line = [&dc, &point](int x1, int y1, int x2, int y2)
        {
            dc.DrawLine(point(x1, y1), point(x2, y2));
        };
        dc.DrawText(Display("입력"), point(18, 24));
        if (m_elements.empty())
        {
            dc.DrawText(Display("직렬 또는 병렬 소자를 추가하세요."), point(50, 80));
            return;
        }
        dc.SetPen(wxPen(colour.text, FromDIP(2)));
        dc.SetBrush(wxBrush(colour.content));
        dc.DrawCircle(point(24, 80), FromDIP(5));
        line(29, 80, 55, 80);
        const int step = std::max(145, (ToDIP(GetClientSize()).x - 120) / static_cast<int>(m_elements.size()));
        for (std::size_t index = 0; index < m_elements.size(); ++index)
        {
            const auto& element = m_elements.at(index);
            const int start = 55 + static_cast<int>(index) * step;
            const int middle = start + step / 2;
            const bool shunt = element.at("connection") == "shunt";
            const std::string kind = element.at("kind");
            const std::string state = element.at("state");
            dc.SetPen(wxPen(static_cast<int>(index) == m_selected ? colour.accent : colour.text, FromDIP(2)));
            dc.SetTextForeground(static_cast<int>(index) == m_selected ? colour.accent : colour.text);
            const std::string label =
                element.value("name", kind) + " / " +
                (state == "connected" ? (element.value("value_text", "").empty()
                                             ? "미정"
                                             : element.value("value_text", "") + " " + element.value("value_unit", ""))
                 : state == "dnp"     ? "미실장"
                 : state == "open"    ? "개방"
                                      : "단락");
            dc.DrawText(wxControl::Ellipsize(Display(label), dc, wxELLIPSIZE_END, FromDIP(step - 8)), point(start, 20));
            if (shunt)
            {
                line(start, 80, start + step, 80);
                line(middle, 80, middle, 105);
                if (state == "open" || state == "dnp")
                {
                    dc.DrawCircle(point(middle, 108), FromDIP(3));
                    dc.DrawCircle(point(middle, 132), FromDIP(3));
                }
                else if (state == "short")
                {
                    line(middle, 105, middle, 135);
                }
                else if (kind == "C")
                {
                    line(middle, 105, middle, 116);
                    line(middle - 14, 116, middle + 14, 116);
                    line(middle - 14, 124, middle + 14, 124);
                    line(middle, 124, middle, 135);
                }
                else if (kind == "R")
                {
                    dc.DrawRectangle(FromDIP(middle - 8), FromDIP(105), FromDIP(16), FromDIP(30));
                }
                else
                {
                    for (int segment = 0; segment < 3; ++segment)
                    {
                        dc.DrawEllipticArc(FromDIP(middle - 6), FromDIP(105 + segment * 10), FromDIP(12), FromDIP(10),
                                           270, 90);
                    }
                }
                line(middle, 135, middle, 151);
                line(middle - 17, 151, middle + 17, 151);
                line(middle - 11, 157, middle + 11, 157);
                line(middle - 5, 163, middle + 5, 163);
            }
            else
            {
                line(start, 80, middle - 22, 80);
                line(middle + 22, 80, start + step, 80);
                if (state == "open" || state == "dnp")
                {
                    dc.DrawCircle(point(middle - 19, 80), FromDIP(3));
                    dc.DrawCircle(point(middle + 19, 80), FromDIP(3));
                }
                else if (state == "short")
                {
                    line(middle - 22, 80, middle + 22, 80);
                }
                else if (kind == "C")
                {
                    line(middle - 22, 80, middle - 4, 80);
                    line(middle + 4, 80, middle + 22, 80);
                    line(middle - 4, 65, middle - 4, 95);
                    line(middle + 4, 65, middle + 4, 95);
                }
                else if (kind == "R")
                {
                    dc.DrawRectangle(FromDIP(middle - 22), FromDIP(72), FromDIP(44), FromDIP(16));
                }
                else
                {
                    for (int segment = 0; segment < 4; ++segment)
                    {
                        dc.DrawEllipticArc(FromDIP(middle - 22 + segment * 11), FromDIP(71), FromDIP(11), FromDIP(18),
                                           0, 180);
                    }
                }
            }
        }
        const int end = 55 + static_cast<int>(m_elements.size()) * step;
        dc.DrawCircle(point(end, 80), FromDIP(5));
        dc.DrawText(Display("부하"), point(end - 20, 108));
    }

    Json m_elements = Json::array();
    int m_selected = -1;
};

namespace
{
/** @brief 입력 행을 공통 간격과 접근 가능한 native 레이블로 구성한다. */
void Field(wxWindow* parent, wxSizer* layout, const std::string& title, wxWindow* control)
{
    layout->Add(new wxStaticText(parent, wxID_ANY, Display(title)), 0, wxBOTTOM, parent->FromDIP(4));
    layout->Add(control, 0, wxEXPAND | wxBOTTOM, parent->FromDIP(10));
    control->SetToolTip(Display(title));
}

std::string Number(const Json& value)
{
    if (value.is_number())
    {
        return ResultUi::Number(value);
    }
    return value.is_null() ? "미정" : value.is_string() ? value.get<std::string>() : value.dump();
}
}

void NetworkCircuitDialog::BuildInterface()
{
    StudioTheme::ApplyTypography(*this);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* title = new wxStaticText(this, wxID_ANY, Display("외부 정합망 / 기본 RLC"));
    StudioTheme::Title(*title);
    layout->Add(title, 0, wxALL, FromDIP(16));
    auto* introduction = new wxStaticText(
        this, wxID_ANY,
        Display("기본 회로를 부하 포트 데이터에 연결합니다. 실제 부품 손실과 방사 결과는 별도로 검증합니다."));
    StudioTheme::BindSecondary(*introduction);
    layout->Add(introduction, 0, wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(16));
    auto* selectors = new wxBoxSizer(wxHORIZONTAL);
    m_circuits = new wxChoice(this, wxID_ANY);
    m_circuits->SetName("network.circuit.saved");
    m_datasets = new wxChoice(this, wxID_ANY);
    m_datasets->SetName("network.circuit.dataset");
    for (const auto& pair : std::vector<std::pair<std::string, wxWindow*>>{{"회로 사본", m_circuits},
                                                                           {"안테나 / 부하 입력 자료", m_datasets}})
    {
        auto* column = new wxBoxSizer(wxVERTICAL);
        Field(this, column, pair.first, pair.second);
        selectors->Add(column, 1, wxRIGHT, FromDIP(12));
    }
    layout->Add(selectors, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(16));
    m_step = new wxStaticText(this, wxID_ANY, wxEmptyString);
    m_step->SetName("network.circuit.next_step");
    StudioTheme::BindSecondary(*m_step);
    layout->Add(m_step, 0, wxEXPAND | wxLEFT | wxRIGHT | wxTOP, FromDIP(16));
    m_tabs = new StudioNotebook(this);
    auto* configuration = new wxScrolledWindow(m_tabs, wxID_ANY);
    configuration->SetScrollRate(FromDIP(16), FromDIP(16));
    auto* body = new wxBoxSizer(wxHORIZONTAL);
    auto* left = new wxBoxSizer(wxVERTICAL);
    m_drawing = new NetworkCircuitDrawing(configuration);
    left->Add(m_drawing, 1, wxEXPAND | wxBOTTOM, FromDIP(12));
    m_table = new wxListCtrl(configuration, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(510, 120)),
                             wxLC_REPORT | wxLC_SINGLE_SEL);
    m_table->SetName("network.circuit.elements");
    const std::array<std::pair<const char*, int>, 5> columns{
        {{"소자 이름", 130}, {"연결", 70}, {"값", 100}, {"단위", 70}, {"상태", 100}}};
    for (std::size_t index = 0; index < columns.size(); ++index)
    {
        m_table->InsertColumn(static_cast<int>(index), Display(columns[index].first), wxLIST_FORMAT_LEFT,
                              FromDIP(columns[index].second));
    }
    StudioTheme::Table(*m_table);
    left->Add(m_table, 1, wxEXPAND | wxBOTTOM, FromDIP(12));
    auto* tools = new wxBoxSizer(wxHORIZONTAL);
    const auto tool =
        [this, configuration, tools](const std::string& label, const std::string& name, std::function<void()> action)
    {
        auto* button = new wxButton(configuration, wxID_ANY, Display(label));
        button->SetName(Display(name));
        StudioTheme::Button(*button);
        button->Bind(wxEVT_BUTTON,
                     [action](wxCommandEvent&)
                     {
                         action();
                     });
        tools->Add(button, 0, wxRIGHT, FromDIP(6));
        m_editButtons.push_back(button);
    };
    tool("직렬 추가", "network.circuit.add_series",
         [this]()
         {
             AddElement("series");
         });
    tool("병렬 추가", "network.circuit.add_shunt",
         [this]()
         {
             AddElement("shunt");
         });
    tool("삭제", "network.circuit.remove",
         [this]()
         {
             RemoveElement();
         });
    tool("앞으로", "network.circuit.up",
         [this]()
         {
             MoveElement(-1);
         });
    tool("뒤로", "network.circuit.down",
         [this]()
         {
             MoveElement(1);
         });
    left->Insert(1, tools, 0, wxEXPAND | wxBOTTOM, FromDIP(8));
    auto* order = new wxStaticText(configuration, wxID_ANY,
                                   Display("목록은 입력에서 부하 방향 순서입니다. 이상 소자 / 부품 손실·공차 미정"));
    StudioTheme::BindSecondary(*order);
    left->Add(order, 0, wxTOP, FromDIP(12));
    body->Add(left, 3, wxEXPAND | wxALL, FromDIP(16));
    auto* right = new wxBoxSizer(wxVERTICAL);
    m_name = new wxTextCtrl(configuration, wxID_ANY);
    m_name->SetName("network.circuit.name");
    Field(configuration, right, "정합망 이름", m_name);
    m_elementFields = new wxPanel(configuration);
    auto* fields = new wxBoxSizer(wxVERTICAL);
    m_elementName = new wxTextCtrl(m_elementFields, wxID_ANY);
    m_elementName->SetName("network.circuit.element_name");
    Field(m_elementFields, fields, "선택한 소자 이름", m_elementName);
    auto* kinds = new wxBoxSizer(wxHORIZONTAL);
    m_kind = new wxChoice(m_elementFields, wxID_ANY);
    m_connection = new wxChoice(m_elementFields, wxID_ANY);
    m_state = new wxChoice(m_elementFields, wxID_ANY);
    m_kind->SetName("network.circuit.kind");
    m_connection->SetName("network.circuit.connection");
    m_state->SetName("network.circuit.state");
    for (const auto* label : {"R", "L", "C"})
    {
        m_kind->Append(Display(label));
    }
    for (const auto* label : {"직렬", "병렬"})
    {
        m_connection->Append(Display(label));
    }
    for (const auto* label : {"연결", "개방", "단락", "미실장"})
    {
        m_state->Append(Display(label));
    }
    for (auto* control : {m_kind, m_connection, m_state})
    {
        kinds->Add(control, 1, wxRIGHT, FromDIP(4));
    }
    fields->Add(kinds, 0, wxEXPAND | wxBOTTOM, FromDIP(10));
    m_value = new wxTextCtrl(m_elementFields, wxID_ANY);
    m_value->SetName("network.circuit.value");
    m_value->SetHint(Display("빈칸은 미정"));
    Field(m_elementFields, fields, "값", m_value);
    m_unit = new wxChoice(m_elementFields, wxID_ANY);
    m_unit->SetName("network.circuit.unit");
    Field(m_elementFields, fields, "표시 / 입력 단위", m_unit);
    m_source = new wxTextCtrl(m_elementFields, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 70)),
                              wxTE_MULTILINE | wxTE_READONLY);
    Field(m_elementFields, fields, "입력 출처 (보존)", m_source);
    m_elementFields->SetSizer(fields);
    right->Add(m_elementFields, 1, wxEXPAND);
    body->Add(right, 2, wxEXPAND | wxTOP | wxRIGHT | wxBOTTOM, FromDIP(16));
    configuration->SetSizer(body);
    m_tabs->AddPage(configuration, Display("회로 구성"), true);
    auto* input = new wxScrolledWindow(m_tabs, wxID_ANY);
    input->SetScrollRate(0, FromDIP(16));
    auto* inputLayout = new wxBoxSizer(wxVERTICAL);
    m_inputPlane = new wxTextCtrl(input, wxID_ANY);
    m_inputPlane->SetName("network.circuit.input_plane");
    m_inputPlane->SetHint(Display("회로 입력 기준면을 명시하세요"));
    m_loadPlane = new wxTextCtrl(input, wxID_ANY);
    m_loadPlane->SetName("network.circuit.load_plane");
    m_loadPlane->SetHint(Display("부하 데이터의 기준면과 정확히 같아야 합니다"));
    Field(input, inputLayout, "회로 입력 기준면", m_inputPlane);
    Field(input, inputLayout, "부하 연결 기준면", m_loadPlane);
    m_useLoadPlane = new wxButton(input, wxID_ANY, Display("선택한 부하의 기준면 사용"));
    StudioTheme::Button(*m_useLoadPlane);
    inputLayout->Add(m_useLoadPlane, 0, wxBOTTOM, FromDIP(8));
    m_useLoadPlane->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        if (m_selection.is_object())
        {
            const auto planes = m_selection.at("descriptor").value("reference_planes", Json::array());
            if (planes.size() == 1 && planes.front().is_string())
            {
                m_loadPlane->SetValue(Display(planes.front()));
            }
        }
    });
    m_dataDetails = new wxTextCtrl(input, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 220)),
                                   wxTE_MULTILINE | wxTE_READONLY);
    inputLayout->Add(m_dataDetails, 1, wxEXPAND | wxTOP, FromDIP(12));
    auto* inputOuter = new wxBoxSizer(wxVERTICAL);
    inputOuter->Add(inputLayout, 1, wxEXPAND | wxALL, FromDIP(16));
    input->SetSizer(inputOuter);
    m_tabs->AddPage(input, Display("입력 데이터"));
    auto* result = new wxScrolledWindow(m_tabs, wxID_ANY);
    result->SetScrollRate(FromDIP(16), FromDIP(16));
    auto* resultLayout = new wxBoxSizer(wxVERTICAL);
    m_resultName = new wxTextCtrl(result, wxID_ANY, Display("정합 결과 01"));
    m_resultName->SetName("network.circuit.result_name");
    Field(result, resultLayout, "별도로 저장할 결과 이름", m_resultName);
    m_pageLabel = new wxStaticText(result, wxID_ANY, Display("결합 결과 없음"));
    resultLayout->Add(m_pageLabel, 0, wxBOTTOM, FromDIP(8));
    m_resultGraph = new NetworkChart(result);
    m_resultGraph->SetMinSize(FromDIP(wxSize(400, 220)));
    resultLayout->Add(m_resultGraph, 1, wxEXPAND | wxBOTTOM, FromDIP(12));
    m_results =
        new wxListCtrl(result, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 150)), wxLC_REPORT | wxLC_SINGLE_SEL);
    const std::array<std::pair<const char*, int>, 6> resultColumns{
        {{"주파수 (Hz)", 104}, {"부하 S11 (dB)", 122}, {"결합 S11 (dB)", 125}, {"VSWR", 151},
         {"표본 상태", 100}, {"회로 손실 (%)", 120}}};
    for (std::size_t index = 0; index < resultColumns.size(); ++index)
    {
        m_results->InsertColumn(static_cast<int>(index), Display(resultColumns[index].first),
                                index != 0 && index != 4 ? wxLIST_FORMAT_RIGHT : wxLIST_FORMAT_LEFT,
                                FromDIP(resultColumns[index].second));
    }
    StudioTheme::Table(*m_results);
    resultLayout->Add(m_results, 1, wxEXPAND);
    m_resultDetails = new wxTextCtrl(result, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 90)),
                                     wxTE_MULTILINE | wxTE_READONLY);
    resultLayout->Add(m_resultDetails, 0, wxEXPAND | wxTOP, FromDIP(12));
    auto* resultOuter = new wxBoxSizer(wxVERTICAL);
    resultOuter->Add(resultLayout, 1, wxEXPAND | wxALL, FromDIP(16));
    result->SetSizer(resultOuter);
    m_tabs->AddPage(result, Display("결합 결과"));
    layout->Add(m_tabs, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    m_status = new wxStaticText(this, wxID_ANY, wxEmptyString);
    layout->Add(m_status, 0, wxEXPAND | wxALL, FromDIP(16));
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    auto* close = new wxButton(this, wxID_CANCEL, Display("닫기"));
    m_reviewDefinition = new wxButton(this, wxID_ANY, Display("회로 검토"));
    m_reviewCalculation = new wxButton(this, wxID_ANY, Display("결합 검토"));
    m_apply = new wxButton(this, wxID_APPLY, Display("검토한 회로 저장"));
    m_reviewDefinition->SetName("network.circuit.preview_definition");
    m_reviewCalculation->SetName("network.circuit.preview_calculation");
    m_apply->SetName("network.circuit.apply");
    actions->AddStretchSpacer();
    for (auto* button : {close, m_reviewDefinition, m_reviewCalculation, m_apply})
    {
        StudioTheme::Button(*button, button == m_apply);
        actions->Add(button, 0, wxLEFT, FromDIP(8));
    }
    layout->Add(actions, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(16));
    SetSizer(layout);
    m_circuits->Bind(wxEVT_CHOICE,
                     [this](wxCommandEvent&)
                     {
                         const int selected = m_circuits->GetSelection();
                         if (!ConfirmDiscard())
                         {
                             m_circuits->SetSelection(m_circuitIndex);
                             return;
                         }
                         LoadCircuit(selected);
                     });
    m_datasets->Bind(wxEVT_CHOICE,
                     [this](wxCommandEvent&)
                     {
                         SelectDataset();
                     });
    m_table->Bind(wxEVT_LIST_ITEM_SELECTED,
                  [this](wxListEvent& event)
                  {
                      if (!m_loading)
                      {
                          m_elementIndex = static_cast<int>(event.GetIndex());
                          RenderElement();
                          m_drawing->SetElements(m_elements, m_elementIndex);
                      }
                  });
    for (auto* control : {m_name, m_inputPlane, m_loadPlane})
    {
        control->Bind(wxEVT_TEXT,
                      [this](wxCommandEvent&)
                      {
                          ChangeDefinition();
                      });
    }
    m_resultName->Bind(wxEVT_TEXT,
                       [this](wxCommandEvent&)
                       {
                           if (!m_loading)
                           {
                               InvalidateReview();
                               UpdateActions();
                           }
                       });
    m_elementName->Bind(wxEVT_TEXT,
                        [this](wxCommandEvent&)
                        {
                            EditElement();
                        });
    m_value->Bind(wxEVT_TEXT,
                  [this](wxCommandEvent&)
                  {
                      EditElement(true);
                  });
    m_kind->Bind(wxEVT_CHOICE,
                 [this](wxCommandEvent&)
                 {
                     EditElement(false, true);
                 });
    m_connection->Bind(wxEVT_CHOICE,
                       [this](wxCommandEvent&)
                       {
                           EditElement();
                       });
    m_state->Bind(wxEVT_CHOICE,
                  [this](wxCommandEvent&)
                  {
                      EditElement();
                  });
    m_unit->Bind(wxEVT_CHOICE,
                 [this](wxCommandEvent&)
                 {
                     ChangeUnit();
                 });
    m_reviewDefinition->Bind(wxEVT_BUTTON,
                             [this](wxCommandEvent&)
                             {
                                 Preview(false);
                             });
    m_reviewCalculation->Bind(wxEVT_BUTTON,
                              [this](wxCommandEvent&)
                              {
                                  Preview(true);
                              });
    m_apply->Bind(wxEVT_BUTTON,
                  [this](wxCommandEvent&)
                  {
                      Apply();
                  });
}

void NetworkCircuitDialog::RenderElements()
{
    const bool loading = m_loading;
    m_loading = true;
    m_table->Freeze();
    m_table->DeleteAllItems();
    for (std::size_t index = 0; index < m_elements.size(); ++index)
    {
        const auto& element = m_elements.at(index);
        const long row = m_table->InsertItem(static_cast<long>(index), Display(element.at("name").get<std::string>()));
        m_table->SetItem(row, 1, Display(element.at("connection") == "series" ? "직렬" : "병렬"));
        m_table->SetItem(row, 2,
                         Display(element.value("value_text", "").empty() ? "미정" : element.value("value_text", "")));
        m_table->SetItem(row, 3, Display(element.value("value_unit", "")));
        const std::string state = element.at("state");
        m_table->SetItem(row, 4,
                         Display(state == "connected" ? "연결"
                                 : state == "open"    ? "개방"
                                 : state == "short"   ? "단락"
                                                      : "미실장"));
    }
    if (m_elementIndex >= 0)
    {
        m_table->SetItemState(m_elementIndex, wxLIST_STATE_SELECTED, wxLIST_STATE_SELECTED);
    }
    m_table->Thaw();
    m_loading = loading;
    m_drawing->SetElements(m_elements, m_elementIndex);
}

void NetworkCircuitDialog::RenderElement()
{
    const bool loading = m_loading;
    m_loading = true;
    if (m_elementIndex >= 0 && m_elementIndex < static_cast<int>(m_elements.size()))
    {
        const auto& element = m_elements.at(m_elementIndex);
        m_elementName->ChangeValue(Display(element.at("name").get<std::string>()));
        m_kind->SetStringSelection(Display(element.at("kind").get<std::string>()));
        m_connection->SetSelection(element.at("connection") == "series" ? 0 : 1);
        const std::string state = element.at("state");
        m_state->SetSelection(state == "connected" ? 0 : state == "open" ? 1 : state == "short" ? 2 : 3);
        m_value->ChangeValue(Display(element.value("value_text", "")));
        m_unit->Clear();
        const std::string kind = element.at("kind");
        const std::vector<std::string> units = kind == "R"   ? std::vector<std::string>{"ohm", "kohm"}
                                               : kind == "L" ? std::vector<std::string>{"H", "uH", "nH"}
                                                             : std::vector<std::string>{"F", "uF", "nF", "pF"};
        for (const auto& unit : units)
        {
            m_unit->Append(Display(unit));
        }
        m_unit->SetStringSelection(Display(element.value("value_unit", units.front())));
        std::string source = "이상 소자 / 실물 부품 검증 미확립\n";
        for (const auto& value : element.at("value").at("source_refs"))
        {
            source += value.get<std::string>() + "\n";
        }
        m_source->ChangeValue(Display(source));
    }
    else
    {
        m_elementName->ChangeValue(wxEmptyString);
        m_value->ChangeValue(wxEmptyString);
        m_source->ChangeValue(Display("소자를 추가하거나 목록에서 선택하세요."));
    }
    m_loading = loading;
    UpdateActions();
}

void NetworkCircuitDialog::RenderData()
{
    if (m_selection.is_null())
    {
        m_dataDetails->ChangeValue(Display("아직 부하 자료를 선택하지 않았습니다.\n기준면과 시간 규약이 미정인 입력은 "
                                           "명시 조건을 채택한 뒤 결합할 수 있습니다."));
        return;
    }
    const auto& descriptor = m_selection.at("descriptor");
    std::string details = "입력 자료: " + m_selection.at("entry").at("name").get<std::string>() + "\n";
    details += "종류: " + descriptor.at("parameter_kind").get<std::string>() + " / " +
               std::to_string(descriptor.at("port_ids").size()) + "포트\n";
    details += "표본: " + Number(descriptor.at("sample_count")) + "개 / " +
               StudioFrequency::Range(descriptor.at("frequency_min_hz"), descriptor.at("frequency_max_hz")) + "\n";
    details += "\n부하 기준면: " + ResultUi::Text(descriptor.at("reference_planes").at(0)) + "\n";
    const auto& impedance = descriptor.at("z0_ohm");
    details += "부하 포트 1 기준 임피던스 (ohm): " +
               ResultUi::Complex(impedance.is_array() && !impedance.empty() ? impedance.front() : Json(nullptr));
    if (descriptor.value("z0_frequency_dependent", false))
    {
        details += " (첫 표본, 주파수별 적용)";
    }
    details += "\n파 정의: " + ResultUi::State(descriptor.at("wave_definition")) +
               "\n시간 규약: " + ResultUi::Text(descriptor.at("phasor_convention")) + "\n\n";
    details += "전자기장 해석 결과와 별도로 외부 이상 RLC 회로를 계산합니다.";
    m_dataDetails->ChangeValue(Display(details));
}

void NetworkCircuitDialog::RenderResult(const Json& result)
{
    m_results->DeleteAllItems();
    if (result.at("page").is_null())
    {
        return;
    }
    const auto& page = result.at("page");
    const auto frequencyScale = StudioFrequency::ForDescriptor(result.at("descriptor"));
    m_resultGraph->SetFrequencyUnit(frequencyScale.unit);
    wxListItem frequencyColumn;
    frequencyColumn.SetText(Display("주파수 (" + frequencyScale.unit + ")"));
    m_results->SetColumn(0, frequencyColumn);
    const Json& converted = result.at("load_page");
    const Json* load = !converted.is_null() ? &converted : m_selection.is_null() ? nullptr : &m_selection.at("page");
    if (load != nullptr)
    {
        m_resultGraph->SetComparison(*load, page, Display(converted.is_null() ? "원본 부하" : "Z 부하의 S11"),
                                     Display("외부 정합 후"));
    }
    else
    {
        m_resultGraph->SetPage(page, Display("외부 정합 후"));
    }
    for (const auto& sample : page.at("samples"))
    {
        const long row = m_results->InsertItem(
            m_results->GetItemCount(), Display(StudioFrequency::Value(sample.at("frequency_hz"), frequencyScale)));
        std::string original = "범위 밖";
        if (load != nullptr)
        {
            for (const auto& source : load->at("samples"))
            {
                if (source.at("frequency_hz") == sample.at("frequency_hz"))
                {
                    original =
                        source.value("zero_magnitude", false) ? "-inf (완전 정합)" : Number(source.at("magnitude_db"));
                    break;
                }
            }
        }
        m_results->SetItem(row, 1, Display(original));
        m_results->SetItem(
            row, 2,
            Display(sample.value("zero_magnitude", false) ? "-inf (완전 정합)" : Number(sample.at("magnitude_db"))));
        const std::string vswrState = sample.value("vswr_state", "");
        m_results->SetItem(row, 3,
                           Display(vswrState == "positive_infinity"  ? "무한대"
                                   : vswrState == "undefined_active" ? "정의 불가 (능동)"
                                                                     : Number(sample.at("vswr"))));
        m_results->SetItem(row, 4, Display(ResultUi::State(sample.at("status"))));
        const auto& power = result.at("power_budget_preview").at(row);
        const auto loss = power.is_null() ? Json(nullptr) : power.at("ideal_circuit_loss_fraction");
        m_results->SetItem(row, 5, loss.is_null() ? Display("미평가") : wxString::Format("%.5g", 100 * loss.get<double>()));
    }
    m_pageLabel->SetLabel(Display("읽기 전용 후보 / 앞 " + std::to_string(page.at("samples").size()) + " / " +
                                  Number(page.at("total")) + "개 표본. 저장 후 결과 화면에서 전체 표본을 조회합니다."));
    const auto& conditions = result.at("matching_conditions");
    const auto& descriptor = result.at("descriptor");
    const auto& impedance = descriptor.at("z0_ohm");
    m_resultDetails->ChangeValue(Display(
        "부하 기준면: " + ResultUi::Text(conditions.at("load_reference_plane")) +
        "\n정합 후 입력 기준면: " + ResultUi::Text(conditions.at("input_reference_plane")) +
        "\n정합 후 기준 임피던스 (ohm): " +
        ResultUi::Complex(impedance.is_array() && !impedance.empty() ? impedance.front() : Json(nullptr)) +
        (descriptor.value("z0_frequency_dependent", false) ? " (첫 표본, 주파수별 적용)" : "") +
        "\n같은 주파수 표본을 각 기준면에서 표시합니다. 회로 손실은 입사전력 대비 이상 RLC 소산입니다. "
        "부품 Q/ESR/ESL/SRF 및 방사 성능은 미평가입니다."));
}
