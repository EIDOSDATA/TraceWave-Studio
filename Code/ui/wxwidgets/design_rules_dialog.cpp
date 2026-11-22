/** @file @brief native 규칙 폼과 현재 개정 검사 결과를 연결한다. */
#include "studio_internal.h"
#include "design_rules_dialog.h"
#include "studio_theme.h"
#include <array>

namespace
{
constexpr std::array<const char*, 4> Sections = {"target", "parameter", "connection", "manufacturing_profile"};

/** @brief 선택 항목에 안정 UUID를 보관하고 원래 선택을 복원한다. */
void FillChoice(wxChoice* choice, const Json& rows, const Json& identity, const std::string& empty)
{
    choice->Clear();
    choice->Append(Display(empty), new wxStringClientData(wxEmptyString));
    int index = 0;
    for (const auto& row : rows)
    {
        const int item = choice->Append(Display(row.value("label", row.value("name", ""))),
                                        new wxStringClientData(Display(row.at("id").get<std::string>())));
        if (row.at("id") == identity)
        {
            index = item;
        }
    }
    choice->SetSelection(index);
}

Json ChoiceId(const wxChoice& choice)
{
    const int index = choice.GetSelection();
    if (index <= 0)
    {
        return nullptr;
    }
    return Utf8(static_cast<wxStringClientData*>(choice.GetClientObject(index))->GetData());
}
}

Json DesignRulesDialog::InitialSelection()
{
    return {{"section", "target"}, {"record_id", nullptr}, {"target_id", nullptr}, {"parameter_id", nullptr}};
}

DesignRulesDialog::DesignRulesDialog(wxWindow* parent, const Json& context, DialogGateway gateway)
    : ProjectSetupDialog(parent, "목표 제약 / 연결 / 기본 DRC", context, std::move(gateway))
{
    SetName("design.rules.dialog");
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* top = new wxBoxSizer(wxHORIZONTAL);
    m_section = new wxChoice(this, wxID_ANY);
    m_section->SetName("rules.section");
    for (const auto* label : {"기판 크기 / 제조 규칙 연결", "매개변수 범위 / 정수", "기대 연결 / 분리", "제조 규칙"})
    {
        m_section->Append(Display(label));
    }
    m_subject = new wxChoice(this, wxID_ANY);
    m_parameter = new wxChoice(this, wxID_ANY);
    m_inclusion = new wxChoice(this, wxID_ANY);
    for (const auto* label : {"모든 도체", "해석 포함 도체", "출력 포함 도체"})
    {
        m_inclusion->Append(Display(label));
    }
    m_inclusion->SetSelection(0);
    const auto addChoice = [&](wxChoice& choice, const char* text)
    {
        auto* field = new wxBoxSizer(wxVERTICAL);
        auto* label = new wxStaticText(this, wxID_ANY, Display(text));
        StudioTheme::Heading(*label);
        field->Add(label, 0, wxBOTTOM, FromDIP(StudioTheme::Space));
        field->Add(&choice, 0, wxEXPAND);
        top->Add(field, 1, wxEXPAND | wxRIGHT, FromDIP(StudioTheme::InputGap));
        return label;
    };
    addChoice(*m_section, "규칙 종류");
    addChoice(*m_subject, "목표 / 규칙");
    m_parameterLabel = addChoice(*m_parameter, "매개변수");
    addChoice(*m_inclusion, "검사 대상 도체");
    layout->Add(top, 0, wxEXPAND | wxALL, FromDIP(StudioTheme::PanelPadding));
    auto* body = new wxBoxSizer(wxHORIZONTAL);
    m_fields = new EditorPanel(this);
    body->Add(m_fields, 1, wxEXPAND);
    auto* review = new wxBoxSizer(wxVERTICAL);
    m_canvas = new DesignCanvas(this);
    m_canvas->SetEditingEnabled(false);
    review->Add(m_canvas, 1, wxEXPAND | wxBOTTOM, FromDIP(8));
    m_issues = new wxListCtrl(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 125)), wxLC_REPORT | wxLC_SINGLE_SEL);
    m_issues->AppendColumn(Display("판정"), wxLIST_FORMAT_LEFT, FromDIP(75));
    m_issues->AppendColumn(Display("규칙"), wxLIST_FORMAT_LEFT, FromDIP(170));
    m_issues->AppendColumn(Display("측정 / 한계"), wxLIST_FORMAT_LEFT, FromDIP(180));
    review->Add(m_issues, 0, wxEXPAND);
    m_detail = new wxTextCtrl(this, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 78)), wxTE_MULTILINE | wxTE_READONLY);
    review->Add(m_detail, 0, wxEXPAND);
    body->Add(review, 1, wxEXPAND | wxLEFT, FromDIP(StudioTheme::PanelPadding));
    layout->Add(body, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(StudioTheme::PanelPadding));
    m_status = new wxStaticText(this, wxID_ANY, wxEmptyString);
    layout->Add(m_status, 0, wxEXPAND | wxALL, FromDIP(8));
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    actions->Add(new wxStaticText(this, wxID_ANY, Display("변경 사유 / 출처")), 0, wxALIGN_CENTER_VERTICAL | wxRIGHT, FromDIP(8));
    m_reason = new wxTextCtrl(this, wxID_ANY);
    actions->Add(m_reason, 1, wxEXPAND | wxRIGHT, FromDIP(8));
    m_set = new wxButton(this, wxID_ANY, Display("적용"));
    m_remove = new wxButton(this, wxID_ANY, Display("제거"));
    m_check = new wxButton(this, wxID_ANY, Display("현재 개정 검사"));
    for (auto* button : {m_set, m_remove, m_check, new wxButton(this, wxID_CANCEL, Display("닫기"))})
    {
        StudioTheme::Button(*button, button == m_check);
        actions->Add(button, 0, wxLEFT, FromDIP(6));
    }
    layout->Add(actions, 0, wxEXPAND | wxALL, FromDIP(StudioTheme::PanelPadding));
    SetSizer(layout);
    for (auto* choice : {m_section, m_subject, m_parameter})
    {
        choice->Bind(wxEVT_CHOICE, [this](wxCommandEvent&) { ChangeSelection(); });
    }
    m_inclusion->Bind(wxEVT_CHOICE, [this](wxCommandEvent&) { ClearReport(); });
    m_reason->Bind(wxEVT_TEXT, [this](wxCommandEvent&) { UpdateActions(); });
    m_fields->Bind(wxEVT_RFAD_EDITOR_CHANGED, [this](wxCommandEvent&) { UpdateActions(); });
    m_set->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { Apply(false); });
    m_remove->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { Apply(true); });
    m_check->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { Check(); });
    m_issues->Bind(wxEVT_LIST_ITEM_SELECTED, [this](wxListEvent& event) { ShowIssue(event.GetIndex()); });
    Render(context);
}

void DesignRulesDialog::Render(const Json& context)
{
    if (context.at("project_id") != m_projectId || context.at("revision_id") != m_revision)
    {
        throw std::runtime_error("규칙 조회의 프로젝트 또는 개정이 다릅니다.");
    }
    m_loading = true;
    m_context = context;
    const auto& selection = context.at("selection");
    const auto section = selection.at("section").get<std::string>();
    m_section->SetSelection(static_cast<int>(std::find(Sections.begin(), Sections.end(), section) - Sections.begin()));
    const bool target = section == "target" || section == "parameter";
    FillChoice(m_subject, context.at(target ? "targets" : "records"), selection.at(target ? "target_id" : "record_id"),
               target ? "목표 선택" : "새 규칙");
    FillChoice(m_parameter, context.at("parameters"), selection.at("parameter_id"), "매개변수 선택");
    m_parameter->Show(section == "parameter");
    m_parameterLabel->Show(section == "parameter");
    m_fields->SetFields(context.at("fields"));
    m_reason->ChangeValue(wxEmptyString);
    m_canvas->SetScene(context.at("scene"));
    m_loading = false;
    m_reloading = false;
    ClearReport();
    SetStatus(context.at("fields").empty() ? "편집할 목표 또는 매개변수를 고르거나 현재 개정을 검사하세요."
                                          : "미정값과 출처는 편집 폼의 상세에서 확인할 수 있습니다.");
    m_canvas->FitView();
    UpdateActions();
}

void DesignRulesDialog::Load(const Json& selection)
{
    Request("design.rules.get", {{"expected_revision", m_revision}, {"selection", selection}}, false,
            [this, selection](const Json& result)
            {
                if (result.at("selection") != selection)
                {
                    throw std::runtime_error("규칙 선택 응답이 요청과 다릅니다.");
                }
                Render(result);
            });
}

void DesignRulesDialog::ChangeSelection()
{
    if (m_loading || m_pending || !Editable())
    {
        return;
    }
    Json selection = InitialSelection();
    const std::string section = Sections.at(m_section->GetSelection());
    selection["section"] = section;
    if (section == m_context.at("selection").at("section"))
    {
        if (section == "target" || section == "parameter")
        {
            selection["target_id"] = ChoiceId(*m_subject);
            if (section == "parameter")
            {
                selection["parameter_id"] = ChoiceId(*m_parameter);
            }
        }
        else
        {
            selection["record_id"] = ChoiceId(*m_subject);
        }
    }
    else if (section == "parameter")
    {
        selection["target_id"] = m_context.at("selection").at("target_id");
    }
    const Json original = m_context;
    if (ConfirmDiscard())
    {
        Load(selection);
    }
    else
    {
        const auto old = original.at("selection");
        const auto key = old.at("section").get<std::string>();
        const bool target = key == "target" || key == "parameter";
        m_section->SetSelection(static_cast<int>(std::find(Sections.begin(), Sections.end(), key) - Sections.begin()));
        FillChoice(m_subject, original.at(target ? "targets" : "records"), old.at(target ? "target_id" : "record_id"),
                   target ? "목표 선택" : "새 규칙");
        FillChoice(m_parameter, original.at("parameters"), old.at("parameter_id"), "매개변수 선택");
    }
}

void DesignRulesDialog::Apply(bool remove)
{
    const auto changes = remove ? Json::object() : m_fields->Changes();
    Request("design.rules.apply", {{"expected_revision", m_revision}, {"command_id", Uuid()},
            {"selection", m_context.at("selection")}, {"operation", remove ? "remove" : "set"},
            {"values", changes}, {"reason", Utf8(m_reason->GetValue())}}, true,
            [this, remove](const Json& result)
            {
                AcceptMutation(result);
                m_reloading = true;
                auto selection = result.at("selection");
                if (remove)
                {
                    selection["record_id"] = nullptr;
                }
                ClearReport();
                Load(selection);
            });
}

bool DesignRulesDialog::HasDraft() const
{
    return !m_reloading && (m_fields->IsDirty() || !m_reason->GetValue().empty());
}

void DesignRulesDialog::UpdateActions()
{
    const bool editable = Editable() && !m_pending && !m_reloading && !m_needsReload;
    for (auto* choice : {m_section, m_subject, m_parameter, m_inclusion})
    {
        choice->Enable(editable);
    }
    m_fields->Enable(editable);
    m_reason->Enable(editable);
    const bool explained = !wxString(m_reason->GetValue()).Trim(true).Trim(false).empty();
    m_set->Enable(editable && explained && m_fields->IsDirty());
    m_remove->Enable(editable && explained && m_context.value("exists", false));
    m_check->Enable(editable && !HasDraft());
}

void DesignRulesDialog::ShowRequestFailure(const Json& error)
{
    if (m_reloading)
    {
        m_needsReload = true;
    }
    else
    {
        const auto selection = m_context.at("selection");
        const auto section = selection.at("section").get<std::string>();
        const bool target = section == "target" || section == "parameter";
        m_section->SetSelection(static_cast<int>(std::find(Sections.begin(), Sections.end(), section) - Sections.begin()));
        FillChoice(m_subject, m_context.at(target ? "targets" : "records"), selection.at(target ? "target_id" : "record_id"),
                   target ? "목표 선택" : "새 규칙");
        FillChoice(m_parameter, m_context.at("parameters"), selection.at("parameter_id"), "매개변수 선택");
    }
    ProjectSetupDialog::ShowRequestFailure(error);
}
