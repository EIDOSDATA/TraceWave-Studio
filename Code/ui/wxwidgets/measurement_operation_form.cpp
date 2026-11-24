/** @file @brief 포트 순열, 재정규화와 RI 보간의 순서를 명시하는 native 입력이다. */
#include "measurement_operation_dialog.h"
#include "measurement_model.h"
#include "measurement_quantity_group.h"
#include "result_presentation.h"
#include "studio_support.h"
#include <wx/button.h>
#include <wx/checklst.h>
#include <wx/choice.h>
#include <wx/sizer.h>
#include <wx/spinctrl.h>
#include <wx/statbox.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <wx/wrapsizer.h>
#include <map>

void MeasurementOperationDialog::BuildAlignment(wxWindow* parent, wxSizer* layout)
{
    auto* operations = new wxStaticBoxSizer(wxVERTICAL, parent, Display("정렬 순서 (체크한 단계만 적용)"));
    m_operations = new wxCheckListBox(operations->GetStaticBox(), wxID_ANY);
    m_order = {"permute_ports", "renormalize", "linear_ri"};
    for (const auto* label : {"포트 순열 (양쪽 행렬 축에 적용)", "명시 실수 Z0 재정규화", "같은 복소 RI 선형 보간"})
    {
        m_operations->Append(Display(label));
    }
    operations->Add(m_operations, 0, wxEXPAND | wxALL, FromDIP(6));
    auto* orderButtons = new wxBoxSizer(wxHORIZONTAL);
    auto* up = new wxButton(operations->GetStaticBox(), wxID_UP, Display("위로"));
    auto* down = new wxButton(operations->GetStaticBox(), wxID_DOWN, Display("아래로"));
    orderButtons->Add(up, 0, wxALL, FromDIP(4));
    orderButtons->Add(down, 0, wxALL, FromDIP(4));
    operations->Add(orderButtons, 0);
    layout->Add(operations, 0, wxEXPAND | wxALL, FromDIP(8));
    up->Bind(wxEVT_BUTTON,
             [this](wxCommandEvent&)
             {
                 MoveOperation(-1);
             });
    down->Bind(wxEVT_BUTTON,
               [this](wxCommandEvent&)
               {
                   MoveOperation(1);
               });
    m_operations->Bind(wxEVT_CHECKLISTBOX,
                       [this](wxCommandEvent&)
                       {
                           Changed();
                       });
    const auto descriptor = m_selection.value("descriptor", Json::object());
    const auto ports = descriptor.value("port_ids", Json::array());
    auto* mapping = new wxFlexGridSizer(3, FromDIP(8), FromDIP(12));
    mapping->AddGrowableCol(1, 1);
    mapping->AddGrowableCol(2, 1);
    for (const auto* label : {"출력 포트", "원래 포트 대응", "새 Z0 (ohm, 직접 입력)"})
    {
        mapping->Add(new wxStaticText(parent, wxID_ANY, Display(label)));
    }
    for (std::size_t index = 0; index < ports.size(); ++index)
    {
        mapping->Add(new wxStaticText(parent, wxID_ANY, Display("포트 " + std::to_string(index + 1))), 0,
                     wxALIGN_CENTER_VERTICAL);
        auto* port = new wxChoice(parent, wxID_ANY);
        for (std::size_t original = 0; original < ports.size(); ++original)
        {
            port->Append(Display(ResultUi::PortName(descriptor, original)));
        }
        port->SetSelection(static_cast<int>(index));
        mapping->Add(port, 1, wxEXPAND);
        auto* reference = new wxTextCtrl(parent, wxID_ANY);
        reference->SetHint(Display("명시할 때만 입력"));
        mapping->Add(reference, 1, wxEXPAND);
        m_ports.push_back(port);
        m_references.push_back(reference);
        port->Bind(wxEVT_CHOICE,
                   [this](wxCommandEvent&)
                   {
                       Changed();
                   });
        reference->Bind(wxEVT_TEXT,
                        [this](wxCommandEvent&)
                        {
                            Changed();
                        });
    }
    layout->Add(mapping, 0, wxEXPAND | wxALL, FromDIP(12));
    auto* frequencies = new wxStaticBoxSizer(wxVERTICAL, parent, Display("보간 주파수 (외삽 및 결측 건너뛰기 없음)"));
    auto* frequencyParent = frequencies->GetStaticBox();
    auto* grid = new wxFlexGridSizer(4, FromDIP(8), FromDIP(12));
    grid->AddGrowableCol(1, 1);
    grid->AddGrowableCol(3, 1);
    m_frequencyMode = new wxChoice(frequencyParent, wxID_ANY);
    m_frequencyMode->Append(Display("시작, 끝, 개수"));
    m_frequencyMode->Append(Display("명시 목록"));
    m_frequencyMode->SetSelection(0);
    m_frequencyUnit = new wxChoice(frequencyParent, wxID_ANY);
    m_gapUnit = new wxChoice(frequencyParent, wxID_ANY);
    for (auto* control : {m_frequencyUnit, m_gapUnit})
    {
        for (const auto* unit : {"Hz", "kHz", "MHz", "GHz"})
        {
            control->Append(unit);
        }
        control->SetSelection(3);
    }
    m_start = new wxTextCtrl(frequencyParent, wxID_ANY);
    m_stop = new wxTextCtrl(frequencyParent, wxID_ANY);
    m_gap = new wxTextCtrl(frequencyParent, wxID_ANY);
    m_count = new wxSpinCtrl(frequencyParent, wxID_ANY);
    m_count->SetRange(1, 1001);
    m_count->SetValue(2);
    for (const auto& item : std::vector<std::pair<std::string, wxWindow*>>{{"입력 방식", m_frequencyMode},
                                                                           {"입력 단위", m_frequencyUnit},
                                                                           {"시작", m_start},
                                                                           {"끝", m_stop},
                                                                           {"표본 개수", m_count},
                                                                           {"최대 원문 간격", m_gap},
                                                                           {"간격 입력 단위", m_gapUnit}})
    {
        grid->Add(new wxStaticText(frequencyParent, wxID_ANY, Display(item.first)), 0, wxALIGN_CENTER_VERTICAL);
        grid->Add(item.second, 1, wxEXPAND);
    }
    frequencies->Add(grid, 0, wxEXPAND | wxALL, FromDIP(8));
    m_explicit = new wxTextCtrl(frequencyParent, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 80)),
                                wxTE_MULTILINE);
    m_explicit->SetHint(
        Display("명시 목록 (GHz 고정): 한 줄에 하나, 최대 1001개. 원문 범위와 최대 간격은 서비스가 검사합니다."));
    frequencies->Add(m_explicit, 0, wxEXPAND | wxALL, FromDIP(8));
    layout->Add(frequencies, 0, wxEXPAND | wxALL, FromDIP(8));
    m_sources = new wxTextCtrl(parent, wxID_ANY);
    m_sources->SetHint(Display("정렬 근거와 출처 (한 줄에 하나)"));
    layout->Add(m_sources, 0, wxEXPAND | wxALL, FromDIP(12));
    m_frequencyInputs =
        MeasurementQuantityGroup::Create(this, m_frequencyUnit,
                                         {{"calibration.frequency_range_hz.start", m_start, nullptr, nullptr},
                                          {"calibration.frequency_range_hz.stop", m_stop, nullptr, nullptr}},
                                         m_gateway);
    m_gapInputs = MeasurementQuantityGroup::Create(
        this, m_gapUnit, {{"calibration.frequency_range_hz.start", m_gap, nullptr, nullptr}}, m_gateway);
    for (auto group : {m_frequencyInputs, m_gapInputs})
    {
        group->onEdited = [this]()
        {
            Changed();
        };
        group->onState = [this]()
        {
            UpdateActions();
        };
        group->onStatus = [this](const std::string& message)
        {
            SetStatus(message);
        };
    }
    for (auto* input : {m_explicit, m_sources})
    {
        input->Bind(wxEVT_TEXT,
                    [this](wxCommandEvent&)
                    {
                        Changed();
                    });
    }
    for (auto* input : {m_frequencyMode})
    {
        input->Bind(wxEVT_CHOICE,
                    [this](wxCommandEvent&)
                    {
                        Changed();
                    });
    }
    m_count->Bind(wxEVT_SPINCTRL,
                  [this](wxSpinEvent&)
                  {
                      Changed();
                  });
    m_count->Bind(wxEVT_TEXT,
                  [this](wxCommandEvent&)
                  {
                      Changed();
                  });
}

void MeasurementOperationDialog::MoveOperation(int delta)
{
    const int selected = m_operations->GetSelection(), next = selected + delta;
    if (selected < 0 || next < 0 || next >= static_cast<int>(m_order.size()))
    {
        return;
    }
    const bool checked = m_operations->IsChecked(selected), other = m_operations->IsChecked(next);
    const auto text = m_operations->GetString(selected);
    m_operations->SetString(selected, m_operations->GetString(next));
    m_operations->SetString(next, text);
    m_operations->Check(selected, other);
    m_operations->Check(next, checked);
    std::swap(m_order.at(static_cast<std::size_t>(selected)), m_order.at(static_cast<std::size_t>(next)));
    m_operations->SetSelection(next);
    Changed();
}

Json MeasurementOperationDialog::Input() const
{
    Json parameters;
    if (m_operation == "compare_record")
    {
        parameters = {{"name", Utf8(m_name->GetValue())},
                      {"reason", Utf8(m_reason->GetValue())},
                      {"comparison", m_selection.at("comparison")}};
    }
    else
    {
        Json operations = Json::array();
        const Json refs = MeasurementUi::Lines(Utf8(m_sources->GetValue()));
        const auto quantity = [&refs](wxTextCtrl* input, const std::string& unit)
        {
            return Json{{"text", Utf8(input->GetValue())}, {"unit", unit}, {"source_refs", refs}};
        };
        const auto frequency = [&refs](const std::shared_ptr<MeasurementQuantityGroup>& group, std::size_t index)
        {
            auto input = group->Input(index);
            input["source_refs"] = refs;
            return input;
        };
        for (std::size_t index = 0; index < m_order.size(); ++index)
        {
            if (!m_operations->IsChecked(static_cast<unsigned int>(index)))
            {
                continue;
            }
            const auto& kind = m_order.at(index);
            if (kind == "permute_ports")
            {
                Json order = Json::array();
                for (auto* port : m_ports)
                {
                    order.push_back(port->GetSelection());
                }
                operations.push_back({{"kind", kind}, {"order", order}});
            }
            else if (kind == "renormalize")
            {
                Json references = Json::array();
                for (auto* reference : m_references)
                {
                    references.push_back(quantity(reference, "ohm"));
                }
                operations.push_back({{"kind", kind}, {"references", references}});
            }
            else
            {
                Json frequencies;
                if (m_frequencyMode->GetSelection() == 0)
                {
                    frequencies = {{"mode", "range"},
                                   {"start", frequency(m_frequencyInputs, 0)},
                                   {"stop", frequency(m_frequencyInputs, 1)},
                                   {"count", m_count->GetValue()}};
                }
                else
                {
                    Json values = Json::array();
                    for (const auto& text : MeasurementUi::Lines(Utf8(m_explicit->GetValue())))
                    {
                        values.push_back({{"text", text}, {"unit", "GHz"}, {"source_refs", refs}});
                    }
                    frequencies = {{"mode", "explicit"}, {"values", values}};
                }
                operations.push_back(
                    {{"kind", kind}, {"frequencies", frequencies}, {"max_gap", frequency(m_gapInputs, 0)}});
            }
        }
        parameters = {{"source", m_selection.at("source")},
                      {"pin", m_selection.at("pin")},
                      {"record", m_selection.value("record_ref", m_selection.value("measurement_ref", Json(nullptr)))},
                      {"name", Utf8(m_name->GetValue())},
                      {"specification",
                       {{"schema", "rfad.measurement-alignment-input/0.1"},
                        {"operations", operations},
                        {"reason", Utf8(m_reason->GetValue())},
                        {"source_refs", refs}}}};
    }
    return {{"expected_revision", m_revision},
            {"draft_time_utc", m_draftTime},
            {"operation", m_operation},
            {"parameters", parameters}};
}
