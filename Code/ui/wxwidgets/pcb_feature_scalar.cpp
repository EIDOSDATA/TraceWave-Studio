/** @file @brief 단위 변경을 서비스에 맡기고 값 입력과 표시 단위를 분리한다. */
#include "pcb_feature_form.h"
#include "pcb_feature_model.h"
#include "studio_support.h"
#include <wx/choice.h>
#include <wx/sizer.h>
#include <wx/textctrl.h>
#include <wx/weakref.h>

void PcbFeatureForm::BuildScalar(const std::shared_ptr<Field>& field, wxBoxSizer* row)
{
    auto* parent = field->row;
    field->quantity = field->descriptor.value("quantity", field->original);
    field->shownUnit = field->descriptor.value("unit", field->quantity.value("display_unit", "mm"));
    field->mode = new wxChoice(parent, wxID_ANY);
    for (const auto* label : {"직접 입력", "매개변수", "미정"})
    {
        field->mode->Append(Display(label));
    }
    const bool bound = field->original.is_object() && field->original.contains("parameter_id");
    const bool missing =
        field->quantity.is_object() && field->quantity.contains("value_si") && field->quantity.at("value_si").is_null();
    field->mode->SetSelection(bound ? 1 : missing ? 2 : 0);
    row->Add(field->mode, 0, wxRIGHT, FromDIP(6));
    field->text = new wxTextCtrl(parent, wxID_ANY, Display(field->descriptor.value("text", "")));
    field->text->SetMinSize(FromDIP(wxSize(110, -1)));
    row->Add(field->text, 1, wxRIGHT, FromDIP(6));
    field->unit = new wxChoice(parent, wxID_ANY);
    const auto units = field->descriptor.value("units", Json::array({field->shownUnit}));
    for (const auto& unit : units)
    {
        field->unit->Append(Display(unit.get<std::string>()));
    }
    field->unit->SetStringSelection(Display(field->shownUnit));
    row->Add(field->unit, 0, wxRIGHT, FromDIP(6));
    field->parameter = new wxChoice(parent, wxID_ANY);
    field->choices = Json::array();
    const auto dimension = field->descriptor.value("dimension", field->quantity.value("dimension", ""));
    for (const auto& parameter : m_context.value("parameters", Json::array()))
    {
        if (parameter.value("dimension", "") == dimension)
        {
            field->choices.push_back(parameter);
            field->parameter->Append(Display(parameter.value("label", parameter.value("name", "매개변수"))));
            if (bound && parameter.at("id") == field->original.at("parameter_id"))
            {
                field->parameter->SetSelection(static_cast<int>(field->choices.size() - 1));
            }
        }
    }
    row->Add(field->parameter, 1);
    field->parameter->Show(bound);
    field->text->Show(!bound);
    field->text->Enable(!missing);
    field->unit->Enable(!bound && !missing);
    field->text->Bind(wxEVT_TEXT,
                      [this, field](wxCommandEvent&)
                      {
                          ReadScalar(field);
                      });
    field->parameter->Bind(wxEVT_CHOICE,
                           [this, field](wxCommandEvent&)
                           {
                               ReadScalar(field);
                           });
    field->mode->Bind(wxEVT_CHOICE,
                      [this, field](wxCommandEvent&)
                      {
                          const int mode = field->mode->GetSelection();
                          field->parameter->Show(mode == 1);
                          field->text->Show(mode != 1);
                          field->text->Enable(mode == 0);
                          field->unit->Enable(mode == 0);
                          field->row->Layout();
                          Layout();
                          FitInside();
                          ReadScalar(field);
                      });
    field->unit->Bind(wxEVT_CHOICE,
                      [this, field](wxCommandEvent&)
                      {
                          ChangeUnit(field);
                      });
}

void PcbFeatureForm::ReadScalar(const std::shared_ptr<Field>& field)
{
    if (field->loading)
    {
        return;
    }
    const int mode = field->mode->GetSelection();
    if (mode == 1)
    {
        const int selected = field->parameter->GetSelection();
        Changed(field, {{"parameter_id", selected < 0 ? Json(nullptr) : field->choices.at(selected).at("id")}});
    }
    else if (mode == 2)
    {
        Changed(field,
                {{"value_si", nullptr},
                 {"dimension", field->descriptor.value("dimension", field->quantity.value("dimension", "length"))},
                 {"display_unit", field->shownUnit},
                 {"status", "missing"},
                 {"source_refs", field->quantity.value("source_refs", Json::array())}});
    }
    else
    {
        Changed(field, {{"text", Utf8(field->text->GetValue())},
                        {"unit", field->shownUnit},
                        {"source_refs", field->quantity.value("source_refs", Json::array())}});
    }
}

void PcbFeatureForm::ChangeUnit(const std::shared_ptr<Field>& field)
{
    const auto nextUnit = Utf8(field->unit->GetStringSelection());
    if (nextUnit == field->shownUnit || field->loading)
    {
        return;
    }
    if (field->changed || !field->quantity.is_object() || !field->quantity.contains("value_si"))
    {
        field->unit->SetStringSelection(Display(field->shownUnit));
        if (onStatus)
        {
            onStatus("변경한 값은 현재 단위로 검토하세요. 단위만 바꾸는 조회는 저장 원문을 기준으로 합니다.");
        }
        return;
    }
    const auto generation = m_generation;
    field->loading = true;
    field->row->Enable(false);
    ++m_pending;
    StateChanged();
    wxWeakRef<PcbFeatureForm> weak(this);
    m_gateway(
        "network.quantity",
        {{"expected_revision", m_context.at("revision_id")}, {"quantity", field->quantity}, {"display_unit", nextUnit}},
        false,
        [weak, generation, field, nextUnit](const Json& result)
        {
            if (!weak || generation != weak->m_generation)
            {
                return;
            }
            field->text->ChangeValue(Display(result.at("text").get<std::string>()));
            field->shownUnit = nextUnit;
            field->loading = false;
            field->row->Enable(true);
            --weak->m_pending;
            weak->StateChanged();
        },
        [weak, generation, field](const Json& error)
        {
            if (!weak || generation != weak->m_generation)
            {
                return;
            }
            field->unit->SetStringSelection(Display(field->shownUnit));
            field->loading = false;
            field->row->Enable(true);
            --weak->m_pending;
            if (weak->onStatus)
            {
                weak->onStatus(DiagnosticMessage(error));
            }
            weak->StateChanged();
        });
}
