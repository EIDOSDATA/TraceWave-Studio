/** @file @brief 초기식의 조건과 입력을 별도 화면 영역에서 표시하며 계산은 서비스에 위임한다. */
#include "template_dialog.h"
#include "editor_panel.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/choice.h>
#include <wx/panel.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <stdexcept>

void TemplateDialog::BuildSeedControls(wxSizer* layout)
{
    m_seedPanel = new wxPanel(this);
    StudioTheme::BindSurface(*m_seedPanel);
    auto* form = new wxBoxSizer(wxVERTICAL);
    auto* title = new wxStaticText(m_seedPanel, wxID_ANY, Display("초기 길이 추정 / 공진 및 정합 해석은 별도"));
    StudioTheme::Heading(*title);
    form->Add(title, 0, wxBOTTOM, FromDIP(StudioTheme::Space));
    m_seedRecipe = new wxChoice(m_seedPanel, wxID_ANY);
    m_seedRecipe->SetName("template.seed.recipe");
    form->Add(m_seedRecipe, 0, wxEXPAND | wxBOTTOM, FromDIP(StudioTheme::Space));
    m_seedInputs = new EditorPanel(m_seedPanel);
    m_seedInputs->SetName("template.seed.inputs");
    m_seedInputs->SetMinSize(FromDIP(wxSize(-1, 120)));
    form->Add(m_seedInputs, 1, wxEXPAND);
    m_seedPanel->SetSizer(form);
    layout->Add(m_seedPanel, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(StudioTheme::PanelPadding));
    m_seedPanel->Hide();
    m_seedRecipe->Bind(wxEVT_CHOICE, [this](wxCommandEvent&)
    {
        Changed();
    });
    m_seedInputs->Bind(wxEVT_RFAD_EDITOR_CHANGED, [this](wxCommandEvent&)
    {
        Changed();
    });
}

std::string TemplateDialog::DraftKey() const
{
    return m_card.at("template_id").get<std::string>() + (m_activeMode == 1 ? "/initial_estimate" : "");
}

void TemplateDialog::SelectMode(int index)
{
    if (m_loading || !Editable() || m_card.is_null() || index < 0)
    {
        return;
    }
    StoreDraft();
    m_activeMode = index;
    m_cardModes[m_card.at("template_id").get<std::string>()] = index;
    RenderCardInputs();
}

void TemplateDialog::RenderSeedControls()
{
    m_seedRecipe->Clear();
    for (const auto& recipe : m_card.value("seed_recipes", Json::array()))
    {
        m_seedRecipe->Append(Display(recipe.at("label").get<std::string>()));
    }
    m_seedRecipe->SetSelection(m_seedRecipe->IsEmpty() ? wxNOT_FOUND : 0);
    m_seedInputs->SetFields(Json::array({
        Json{{"key", "frequency.value"}, {"label", "주파수"}, {"editor", "text"}, {"value", ""}, {"readonly", false}},
        Json{{"key", "frequency.unit"}, {"label", "단위"}, {"editor", "choice"}, {"value", "GHz"}, {"readonly", false},
             {"choices", Json::array({Json{{"value", "Hz"}, {"label", "Hz"}}, Json{{"value", "MHz"}, {"label", "MHz"}},
                                      Json{{"value", "GHz"}, {"label", "GHz"}}})}},
        Json{{"key", "assumption"}, {"label", "조건을 채택한 가정/사유"}, {"editor", "text"}, {"value", ""}, {"readonly", false}}}));
    if (m_seedDrafts.contains(DraftKey()))
    {
        const auto& draft = m_seedDrafts.at(DraftKey());
        for (const auto& field : draft.at("fields").items())
        {
            m_seedInputs->SetFieldValue(field.key(), field.value());
        }
        const int index = draft.at("recipe");
        if (index >= 0 && index < static_cast<int>(m_seedRecipe->GetCount()))
        {
            m_seedRecipe->SetSelection(index);
        }
    }
    m_seedPanel->Show(m_activeMode == 1);
}

Json TemplateDialog::SeedSpecification() const
{
    if (m_seedRecipe->GetSelection() < 0)
    {
        throw std::runtime_error("근거와 적용 범위를 확인할 초기식을 선택하세요.");
    }
    const auto& recipe = m_card.at("seed_recipes").at(static_cast<std::size_t>(m_seedRecipe->GetSelection()));
    return Json{{"recipe_id", recipe.at("id")},
                {"frequency", Json{{"value", m_seedInputs->FieldValue("frequency.value")},
                                   {"unit", m_seedInputs->FieldValue("frequency.unit")}}},
                {"assumption", m_seedInputs->FieldValue("assumption")}};
}

std::string TemplateDialog::SeedDescription() const
{
    if (m_activeMode != 1 || m_seedRecipe->GetSelection() < 0)
    {
        return "";
    }
    const auto& recipe = m_card.at("seed_recipes").at(static_cast<std::size_t>(m_seedRecipe->GetSelection()));
    std::string text = "\n\n초기식: " + recipe.at("formula").get<std::string>() + "\n범위: " +
                       recipe.at("frequency_scope").get<std::string>();
    for (const auto& condition : recipe.at("conditions"))
    {
        text += "\n- " + condition.get<std::string>();
    }
    return text;
}
