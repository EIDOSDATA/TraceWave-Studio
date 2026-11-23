/** @file @brief 미확보 시료와 교정 조건은 빈 입력으로 유지하고 명시 변경만 추적한다. */
#include "measurement_record_form.h"
#include "measurement_model.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/collpane.h>
#include <wx/listctrl.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <wx/textdlg.h>
#include <wx/weakref.h>
#include <algorithm>

namespace
{
wxChoice* Choice(wxWindow* parent, std::initializer_list<const char*> labels)
{
    auto* value = new wxChoice(parent, wxID_ANY);
    for (const auto* label : labels)
    {
        value->Append(Display(label));
    }
    value->SetSelection(0);
    return value;
}
}

MeasurementRecordForm::MeasurementRecordForm(wxWindow* parent, DialogGateway gateway)
    : wxScrolledWindow(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL),
      m_gateway(std::move(gateway))
{
    SetName("measurement.record.form");
    SetScrollRate(0, FromDIP(16));
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* general = new wxFlexGridSizer(4, FromDIP(8), FromDIP(12));
    general->AddGrowableCol(1, 1);
    general->AddGrowableCol(3, 1);
    m_name = new wxTextCtrl(this, wxID_ANY);
    m_name->SetName("measurement.name");
    m_class = Choice(this, {"미정", "사용자 제출 측정 자료", "합성 시험 자료"});
    m_class->SetName("measurement.data_class");
    m_author = new wxTextCtrl(this, wxID_ANY);
    m_author->SetName("measurement.author");
    m_reason = new wxTextCtrl(this, wxID_ANY);
    m_reason->SetName("measurement.reason");
    m_name->SetHint(Display("이 기록을 구분할 이름"));
    m_reason->SetHint(Display("기록을 작성하거나 바꾸는 이유"));
    m_sources =
        new wxTextCtrl(this, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 52)), wxTE_MULTILINE);
    m_sources->SetName("measurement.source_refs");
    for (const auto& item : std::vector<std::pair<const char*, wxWindow*>>{
             {"기록 이름 (필수)", m_name}, {"자료 분류", m_class}, {"작성자", m_author}, {"작성 / 변경 사유 (필수)", m_reason}})
    {
        general->Add(new wxStaticText(this, wxID_ANY, Display(item.first)), 0, wxALIGN_CENTER_VERTICAL);
        general->Add(item.second, 1, wxEXPAND);
    }
    layout->Add(general, 0, wxEXPAND | wxALL, FromDIP(12));
    auto* notice = new wxStaticText(this, wxID_ANY,
                                    Display("빈 값은 미정입니다. 값마다 계획 / 사용자 명시 / 제출 근거를 구분합니다. "
                                            "기록 저장은 교정 또는 실측 합격이 아닙니다."));
    notice->Wrap(FromDIP(800));
    StudioTheme::BindSecondary(*notice);
    layout->Add(notice, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(12));
    auto* columns = new wxBoxSizer(wxHORIZONTAL);
    auto* left = new wxPanel(this);
    auto* right = new wxPanel(this);
    auto* leftLayout = new wxBoxSizer(wxVERTICAL);
    auto* rightLayout = new wxBoxSizer(wxVERTICAL);
    BuildSection(left, leftLayout, "specimen", "시료 / 제작·조립");
    BuildSection(left, leftLayout, "acquisition", "취득 / 장비 설정");
    BuildSection(right, rightLayout, "calibration", "교정 / 기준면");
    BuildSection(right, rightLayout, "fixture", "케이블 / 지그 / 급전");
    BuildSection(right, rightLayout, "environment", "환경 / 자세");
    left->SetSizer(leftLayout);
    right->SetSizer(rightLayout);
    columns->Add(left, 1, wxEXPAND | wxRIGHT, FromDIP(6));
    columns->Add(right, 1, wxEXPAND | wxLEFT, FromDIP(6));
    layout->Add(columns, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    BuildCollections(layout);
    layout->Add(new wxStaticText(this, wxID_ANY, Display("전체 출처 (한 줄에 하나 / 기존 원문 보존)")), 0,
                wxLEFT | wxRIGHT | wxTOP, FromDIP(12));
    layout->Add(m_sources, 0, wxEXPAND | wxALL, FromDIP(12));
    SetSizer(layout);
    for (auto* input : {m_name, m_author, m_reason, m_sources})
    {
        input->Bind(wxEVT_TEXT,
                    [this](wxCommandEvent&)
                    {
                        Changed();
                    });
    }
    m_class->Bind(wxEVT_CHOICE,
                  [this](wxCommandEvent&)
                  {
                      Changed();
                  });
    SetRecord(Json::object(), Json::object());
}

void MeasurementRecordForm::BuildSection(wxWindow* parent, wxBoxSizer* layout, const std::string& section,
                                         const std::string& title)
{
    auto* group = new wxCollapsiblePane(parent, wxID_ANY, Display(title));
    auto* panel = group->GetPane();
    auto* fields = new wxBoxSizer(wxVERTICAL);
    for (const auto& definition : MeasurementUi::Fields())
    {
        if (definition.path.substr(0, definition.path.find('.')) != section)
        {
            continue;
        }
        auto field = std::make_shared<Field>();
        field->path = definition.path;
        field->kind = definition.kind;
        fields->Add(new wxStaticText(panel, wxID_ANY, Display(definition.label)), 0, wxTOP | wxBOTTOM, FromDIP(4));
        auto* row = new wxBoxSizer(wxHORIZONTAL);
        field->text = new wxTextCtrl(panel, wxID_ANY, wxEmptyString, wxDefaultPosition,
                                     field->kind == "texts" ? FromDIP(wxSize(-1, 52)) : wxDefaultSize,
                                     field->kind == "texts" ? wxTE_MULTILINE : 0);
        field->text->SetName(Display("measurement." + field->path));
        field->text->SetHint(Display("미정"));
        row->Add(field->text, 1, wxEXPAND | wxRIGHT, FromDIP(4));
        if (!definition.units.empty())
        {
            field->unit = new wxChoice(panel, wxID_ANY);
            for (const auto& unit : definition.units)
            {
                field->unit->Append(Display(unit));
            }
            field->unit->SetSelection(0);
            field->shownUnit = definition.units.front();
            row->Add(field->unit, 0, wxRIGHT, FromDIP(4));
            field->unit->Bind(wxEVT_CHOICE,
                              [this, field](wxCommandEvent&)
                              {
                                  ChangeUnit(field);
                              });
        }
        field->evidence = Choice(panel, {"미정", "계획", "명시", "제출 근거"});
        field->evidence->SetToolTip(
            Display("제출 근거는 사용자가 제출한 기록의 구분이며 독립 인증이나 물리 합격을 뜻하지 않습니다."));
        row->Add(field->evidence, 0);
        fields->Add(row, 0, wxEXPAND);
        field->sources = new wxTextCtrl(panel, wxID_ANY);
        field->sources->Hide();
        auto* evidence = new wxButton(panel, wxID_ANY, Display("근거 / 출처..."));
        fields->Add(evidence, 0, wxALIGN_RIGHT | wxBOTTOM, FromDIP(4));
        evidence->Bind(wxEVT_BUTTON,
                       [this, field](wxCommandEvent&)
                       {
                           wxTextEntryDialog dialog(
                               this,
                               Display("출처를 한 줄에 하나씩 입력하세요. 원문 파일은 아래 근거 파일에서 보관합니다."),
                               Display("필드 출처"), field->sources->GetValue(), wxOK | wxCANCEL | wxTE_MULTILINE);
                           if (dialog.ShowModal() == wxID_OK)
                           {
                               field->sources->ChangeValue(dialog.GetValue());
                               ChangeField(field);
                           }
                       });
        field->text->Bind(wxEVT_TEXT,
                          [this, field](wxCommandEvent&)
                          {
                              ChangeField(field);
                          });
        field->evidence->Bind(wxEVT_CHOICE,
                              [this, field](wxCommandEvent&)
                              {
                                  ChangeField(field);
                              });
        m_fields.push_back(field);
    }
    panel->SetSizer(fields);
    group->Collapse(section != "specimen" && section != "calibration");
    group->Bind(wxEVT_COLLAPSIBLEPANE_CHANGED,
                [this](wxCollapsiblePaneEvent&)
                {
                    Layout();
                    FitInside();
                });
    layout->Add(group, 0, wxEXPAND | wxBOTTOM, FromDIP(8));
}

void MeasurementRecordForm::SetRecord(const Json& record, const Json& context)
{
    ++m_generation;
    m_pending = 0;
    m_loading = true;
    m_record = record.is_object() ? record : Json::object();
    m_context = context;
    m_originalName = m_record.value("name", std::string());
    m_originalReason = m_record.value("reason", std::string());
    m_originalAuthor =
        m_record.value("author", Json(nullptr)).is_string() ? m_record.at("author").get<std::string>() : "";
    m_originalSources = MeasurementUi::Lines(m_record.value("source_refs", Json::array()));
    const auto kind = m_record.value("data_class", std::string("unknown"));
    m_originalClass = kind == "measurement" ? 1 : kind == "synthetic_fixture" ? 2 : 0;
    m_name->ChangeValue(Display(m_originalName));
    m_reason->ChangeValue(Display(m_originalReason));
    m_author->ChangeValue(Display(m_originalAuthor));
    m_sources->ChangeValue(Display(m_originalSources));
    m_class->SetSelection(m_originalClass);
    for (const auto& field : m_fields)
    {
        ++field->generation;
        field->original = MeasurementUi::Leaf(m_record, field->path);
        field->rawInput = nullptr;
        field->changed = false;
        const auto value = field->original.is_object() ? field->original.value("value", Json(nullptr)) : Json(nullptr);
        std::string text;
        if (!value.is_null())
        {
            text = field->kind == "texts" ? MeasurementUi::Lines(value) : MeasurementUi::Text(value);
            if (value.is_object() && value.contains("number"))
            {
                text = MeasurementUi::Text(value.at("number"));
                if (field->unit)
                {
                    field->shownUnit = value.value("unit", field->shownUnit);
                    field->unit->SetStringSelection(Display(field->shownUnit));
                }
            }
        }
        field->text->ChangeValue(Display(text));
        field->evidence->SetSelection(MeasurementUi::Evidence(field->original));
        field->sources->ChangeValue(Display(
            field->original.is_object() ? MeasurementUi::Lines(field->original.value("source_refs", Json::array()))
                                        : ""));
    }
    m_collections = Json::object();
    m_collectionInputs = Json::object();
    m_collectionChanged.clear();
    for (const auto* key :
         {"uncertainty", "external_processing", "attachments", "calibration.port_ids", "calibration.reference_planes",
          "calibration.frequency_range_hz", "calibration.certificate_refs", "acquisition.setting_artifacts",
          "specimen.design_snapshot", "specimen.delivered_materials", "environment.physical_setup_snapshot"})
    {
        m_collections[key] = MeasurementUi::Leaf(m_record, key);
        m_collectionChanged[key] = false;
    }
    RefreshCollections();
    m_loading = false;
    Layout();
    FitInside();
}

void MeasurementRecordForm::ChangeField(const std::shared_ptr<Field>& field)
{
    if (m_loading || field->loading)
    {
        return;
    }
    field->changed = true;
    ++field->generation;
    if (field->kind == "quantity")
    {
        field->rawInput = {{"text", Utf8(field->text->GetValue())},
                           {"unit", field->shownUnit},
                           {"evidence", MeasurementUi::Evidence(field->evidence->GetSelection())},
                           {"source_refs", MeasurementUi::Lines(Utf8(field->sources->GetValue()))}};
    }
    Changed();
}
void MeasurementRecordForm::SetDescriptor(const Json& descriptor)
{
    m_context["descriptor"] = descriptor;
}

void MeasurementRecordForm::Changed()
{
    if (!m_loading && onChanged)
    {
        onChanged();
    }
}

Json MeasurementRecordForm::Changes() const
{
    Json changes{{"values", Json::object()}, {"quantities", Json::object()}};
    if (m_class->GetSelection() != m_originalClass)
    {
        changes["values"]["data_class"] = m_class->GetSelection() == 1   ? "measurement"
                                          : m_class->GetSelection() == 2 ? "synthetic_fixture"
                                                                         : "unknown";
    }
    if (Utf8(m_author->GetValue()) != m_originalAuthor)
    {
        changes["values"]["author"] = m_author->IsEmpty() ? Json(nullptr) : Json(Utf8(m_author->GetValue()));
    }
    if (Utf8(m_sources->GetValue()) != m_originalSources)
    {
        changes["values"]["source_refs"] = MeasurementUi::Lines(Utf8(m_sources->GetValue()));
    }
    for (const auto& field : m_fields)
    {
        if (!field->changed)
        {
            continue;
        }
        if (field->text->IsEmpty())
        {
            changes["values"][field->path] = nullptr;
        }
        else if (field->kind == "quantity")
        {
            changes["quantities"][field->path] = field->rawInput;
        }
        else
        {
            changes["values"][field->path] = {{"value", field->kind == "texts"
                                                            ? MeasurementUi::Lines(Utf8(field->text->GetValue()))
                                                            : Json(Utf8(field->text->GetValue()))},
                                              {"evidence", MeasurementUi::Evidence(field->evidence->GetSelection())},
                                              {"source_refs", MeasurementUi::Lines(Utf8(field->sources->GetValue()))}};
        }
    }
    for (const auto& entry : m_collectionChanged)
    {
        if (entry.second)
        {
            if (m_collectionInputs.contains(entry.first))
            {
                changes["quantities"][entry.first] = m_collectionInputs.at(entry.first);
            }
            else
            {
                changes["values"][entry.first] = m_collections.at(entry.first);
            }
        }
    }
    return changes;
}

std::string MeasurementRecordForm::Name() const
{
    return Utf8(m_name->GetValue());
}
std::string MeasurementRecordForm::RequiredInput(bool focus)
{
    wxTextCtrl* missing = nullptr;
    std::string message;
    if (m_name->GetValue().Strip(wxString::both).empty())
    {
        missing = m_name;
        message = "기록 이름을 입력하세요.";
    }
    else if (m_reason->GetValue().Strip(wxString::both).empty())
    {
        missing = m_reason;
        message = "작성 / 변경 사유를 입력하세요. 교정 자료가 없으면 그 상태를 명시할 수 있습니다.";
    }
    if (focus && missing != nullptr)
    {
        missing->SetFocus();
    }
    return message;
}

std::string MeasurementRecordForm::Reason() const
{
    return Utf8(m_reason->GetValue());
}
bool MeasurementRecordForm::Pending() const
{
    return m_pending > 0;
}
bool MeasurementRecordForm::Dirty() const
{
    const auto changes = Changes();
    return Name() != m_originalName || Reason() != m_originalReason || !changes.at("values").empty() ||
           !changes.at("quantities").empty();
}

void MeasurementRecordForm::ChangeUnit(const std::shared_ptr<Field>& field)
{
    if (m_loading || field->loading || !field->unit)
    {
        return;
    }
    const auto requested = Utf8(field->unit->GetStringSelection());
    if (requested == field->shownUnit)
    {
        return;
    }
    if (field->text->IsEmpty())
    {
        field->shownUnit = requested;
        return;
    }
    const auto generation = m_generation, serial = ++field->generation;
    const auto previous = field->shownUnit;
    Json input{{"path", field->path},
               {"value", field->original.is_object() ? field->original.value("value", Json(nullptr)) : Json(nullptr)},
               {"input", field->changed
                             ? Json{{"text", field->rawInput.at("text")}, {"unit", field->rawInput.at("unit")}}
                             : Json(nullptr)},
               {"display_unit", requested}};
    ++m_pending;
    field->unit->Enable(false);
    field->text->Enable(false);
    wxWeakRef<MeasurementRecordForm> weak(this);
    const auto finish = [this, weak, field, generation, serial, previous, requested](const Json& result, bool success)
    {
        if (!weak || generation != m_generation || serial != field->generation)
        {
            return;
        }
        --m_pending;
        field->unit->Enable(true);
        field->text->Enable(true);
        field->loading = true;
        if (success)
        {
            field->text->ChangeValue(Display(result.at("text").get<std::string>()));
            field->shownUnit = requested;
        }
        else
        {
            field->unit->SetStringSelection(Display(previous));
            if (onStatus)
            {
                onStatus(DiagnosticMessage(result));
            }
        }
        field->loading = false;
        if (onStateChanged)
        {
            onStateChanged();
        }
    };
    if (onStateChanged)
    {
        onStateChanged();
    }
    m_gateway(
        "measurement.quantity", input, false,
        [finish](const Json& result)
        {
            finish(result, true);
        },
        [finish](const Json& error)
        {
            finish(error, false);
        });
}
