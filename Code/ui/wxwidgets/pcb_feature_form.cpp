/** @file @brief PCB 폼의 표시 수명과 원문 필드 교체를 담당한다. */
#include "pcb_feature_form.h"
#include "pcb_feature_model.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <wx/choice.h>
#include <wx/checkbox.h>
#include <wx/checklst.h>
#include <algorithm>
#include <stdexcept>

PcbFeatureForm::PcbFeatureForm(wxWindow* parent, DialogGateway gateway)
    : wxScrolledWindow(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL),
      m_gateway(std::move(gateway))
{
    StudioTheme::BindSurface(*this);
    SetScrollRate(0, FromDIP(16));
    m_layout = new wxBoxSizer(wxVERTICAL);
    SetSizer(m_layout);
}

void PcbFeatureForm::SetForm(const Json& form, const Json& context)
{
    ++m_generation;
    m_pending = 0;
    m_form = form;
    m_context = context;
    m_fields.clear();
    m_supported = true;
    Freeze();
    m_layout->Clear(true);
    const auto fields = form.value("fields", Json::array());
    if (!fields.is_array() || fields.size() > 256)
    {
        throw std::runtime_error("PCB 입력 필드의 표시 상한을 초과했습니다.");
    }
    for (const auto& descriptor : fields)
    {
        auto field = std::make_shared<Field>();
        field->descriptor = descriptor;
        field->original = PcbFeatureUi::Field(form.at("record"), descriptor.at("path"));
        field->value = field->original;
        auto* label = new wxStaticText(this, wxID_ANY, Display(descriptor.value("label", "입력")));
        m_layout->Add(label, 0, wxLEFT | wxRIGHT | wxTOP, FromDIP(8));
        field->row = new wxPanel(this);
        auto* row = new wxBoxSizer(wxHORIZONTAL);
        field->row->SetSizer(row);
        m_layout->Add(field->row, 0, wxEXPAND | wxALL, FromDIP(8));
        const auto kind = descriptor.value("kind", "");
        if (kind == "scalar")
        {
            BuildScalar(field, row);
        }
        else if (kind == "coordinates" || kind == "coordinate_loops" || kind == "members" || kind == "pins" ||
                 kind == "source_refs")
        {
            BuildList(field, row);
        }
        else
        {
            BuildSimple(field, row);
        }
        field->row->Enable(!descriptor.value("read_only", false));
        const auto note = descriptor.value("reason", descriptor.value("help", ""));
        if (!note.empty())
        {
            auto* help = new wxStaticText(this, wxID_ANY, Display(note));
            StudioTheme::BindSecondary(*help);
            help->Wrap(FromDIP(430));
            m_layout->Add(help, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
        }
        m_fields.push_back(field);
    }
    Layout();
    FitInside();
    Scroll(0, 0);
    Thaw();
}

Json PcbFeatureForm::Record() const
{
    Json record = m_form.at("record");
    for (const auto& field : m_fields)
    {
        if (field->changed)
        {
            PcbFeatureUi::ReplaceField(record, field->descriptor.at("path"), field->value);
        }
    }
    return record;
}

void PcbFeatureForm::SetOperation(const std::string& operation, const std::string& section)
{
    for (const auto& field : m_fields)
    {
        const std::string key = field->descriptor.at("path").at(0).get<std::string>();
        bool editable = operation.find(".remove") == std::string::npos && operation != "footprint.detach";
        if (section == "footprint" && !m_form.value("record_id", Json(nullptr)).is_null())
        {
            if (operation == "footprint.place")
            {
                editable = key == "placement";
            }
            else if (operation == "footprint.member_edit")
            {
                editable = key == "members" || key == "pins" || key == "placement_envelope";
            }
            else if (operation == "footprint.set")
            {
                editable = key != "placement" && key != "members" && key != "pins" && key != "placement_envelope";
            }
        }
        field->row->Enable(editable && !field->descriptor.value("read_only", false));
    }
}

bool PcbFeatureForm::Dirty() const
{
    for (const auto& field : m_fields)
    {
        if (field->changed)
        {
            return true;
        }
    }
    return false;
}

bool PcbFeatureForm::Pending() const
{
    return m_pending != 0;
}

bool PcbFeatureForm::Supported() const
{
    return m_supported;
}

void PcbFeatureForm::Changed(const std::shared_ptr<Field>& field, const Json& value)
{
    if (field->loading)
    {
        return;
    }
    field->value = value;
    field->changed = value != field->original;
    if (onChanged)
    {
        onChanged();
    }
}

void PcbFeatureForm::StateChanged()
{
    if (onStateChanged)
    {
        onStateChanged();
    }
}

void PcbFeatureForm::BuildSimple(const std::shared_ptr<Field>& field, wxBoxSizer* row)
{
    const auto kind = field->descriptor.value("kind", "");
    auto* parent = field->row;
    if (kind == "text" || kind == "string")
    {
        field->text = new wxTextCtrl(parent, wxID_ANY, Display(PcbFeatureUi::Text(field->original, "")));
        row->Add(field->text, 1, wxEXPAND);
        if (field->descriptor.value("nullable", field->original.is_null()))
        {
            field->known = new wxCheckBox(parent, wxID_ANY, Display("명시 값"));
            field->known->SetValue(!field->original.is_null());
            field->text->Enable(field->known->GetValue());
            row->Add(field->known, 0, wxLEFT | wxALIGN_CENTER_VERTICAL, FromDIP(8));
            field->known->Bind(wxEVT_CHECKBOX,
                               [this, field](wxCommandEvent&)
                               {
                                   field->text->Enable(field->known->GetValue());
                                   Changed(field, field->known->GetValue() ? Json(Utf8(field->text->GetValue()))
                                                                           : Json(nullptr));
                               });
        }
        field->text->Bind(wxEVT_TEXT,
                          [this, field](wxCommandEvent&)
                          {
                              Changed(field, field->known && !field->known->GetValue()
                                                 ? Json(nullptr)
                                                 : Json(Utf8(field->text->GetValue())));
                          });
    }
    else if (kind == "boolean" || kind == "bool")
    {
        field->check = new wxCheckBox(parent, wxID_ANY, Display("사용"));
        field->check->SetValue(field->original.is_boolean() && field->original.get<bool>());
        row->Add(field->check, 0, wxALIGN_CENTER_VERTICAL);
        field->check->Bind(wxEVT_CHECKBOX,
                           [this, field](wxCommandEvent&)
                           {
                               Changed(field, field->check->GetValue());
                           });
    }
    else if (kind == "choice" || kind == "reference" || kind == "enum")
    {
        field->choice = new wxChoice(parent, wxID_ANY);
        field->choices = field->descriptor.value("choices", Json::array());
        for (const auto& choice : field->choices)
        {
            const auto value = choice.is_object() ? choice.value("value", choice.value("id", Json(nullptr))) : choice;
            field->choice->Append(Display(choice.is_object() ? choice.value("label", choice.value("name", "미정"))
                                                             : PcbFeatureUi::Text(choice)));
            if (value == field->original)
            {
                field->choice->SetSelection(static_cast<int>(field->choice->GetCount() - 1));
            }
        }
        row->Add(field->choice, 1, wxEXPAND);
        field->choice->Bind(wxEVT_CHOICE,
                            [this, field](wxCommandEvent&)
                            {
                                const int selected = field->choice->GetSelection();
                                if (selected >= 0)
                                {
                                    const auto& choice = field->choices.at(static_cast<std::size_t>(selected));
                                    Changed(field, choice.is_object()
                                                       ? choice.value("value", choice.value("id", Json(nullptr)))
                                                       : choice);
                                }
                            });
    }
    else if (kind == "reference_list")
    {
        field->choices = field->descriptor.value("choices", Json::array());
        field->checks = new wxCheckListBox(parent, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 120)));
        for (const auto& choice : field->choices)
        {
            const auto value = choice.is_object() ? choice.value("value", choice.value("id", Json(nullptr))) : choice;
            field->checks->Append(Display(choice.is_object() ? choice.value("label", choice.value("name", "항목"))
                                                             : PcbFeatureUi::Text(choice)));
            if (field->original.is_array() &&
                std::find(field->original.begin(), field->original.end(), value) != field->original.end())
            {
                field->checks->Check(field->checks->GetCount() - 1);
            }
        }
        row->Add(field->checks, 1, wxEXPAND);
        field->checks->Bind(wxEVT_CHECKLISTBOX,
                            [this, field](wxCommandEvent&)
                            {
                                Json values = Json::array();
                                for (unsigned index = 0; index < field->checks->GetCount(); ++index)
                                {
                                    if (field->checks->IsChecked(index))
                                    {
                                        const auto& choice = field->choices.at(index);
                                        values.push_back(choice.is_object()
                                                             ? choice.value("value", choice.value("id", Json(nullptr)))
                                                             : choice);
                                    }
                                }
                                Changed(field, values);
                            });
    }
    else
    {
        row->Add(
            new wxStaticText(parent, wxID_ANY, Display("이 입력 형식은 아직 편집할 수 없습니다. 원문은 보존됩니다.")),
            1);
        m_supported = false;
    }
}
