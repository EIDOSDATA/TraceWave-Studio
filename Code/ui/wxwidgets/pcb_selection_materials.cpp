/** @file @brief 물성별 독립 출처와 사용자 입력을 구조화된 폼으로 만든다. */
#include "pcb_selection_dialog.h"
#include "pcb_selection_view_support.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/listbox.h>
#include <wx/notebook.h>
#include <wx/scrolwin.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <algorithm>

namespace
{
const std::array<std::string, 3> PropertyFields = {"epsilon_r", "tan_delta", "conductivity"};
const std::array<std::string, 3> PropertyNames = {"Dk (무차원)", "Df (무차원)", "전도도 (S/m)"};
}

wxPanel* PcbSelectionDialog::BuildMaterialsPage()
{
    auto* panel = new wxPanel(m_notebook);
    auto* layout = new wxBoxSizer(wxHORIZONTAL);
    auto* sidebar = new wxBoxSizer(wxVERTICAL);
    sidebar->Add(new wxStaticText(panel, wxID_ANY, Display("이번 선택의 재료")), 0, wxBOTTOM, FromDIP(8));
    m_materials = new wxListBox(panel, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(180, -1)));
    m_materials->SetName("pcb.materials");
    sidebar->Add(m_materials, 1, wxEXPAND);
    auto* add = new wxButton(panel, wxID_ANY, Display("새 재료 입력"));
    add->SetName("pcb.new_material");
    auto* remove = new wxButton(panel, wxID_ANY, Display("선택 재료 제거"));
    remove->SetName("pcb.remove_material");
    auto* discard = new wxButton(panel, wxID_ANY, Display("미반영 입력 취소"));
    discard->SetName("pcb.discard_material");
    sidebar->Add(add, 0, wxEXPAND | wxTOP, FromDIP(8));
    sidebar->Add(remove, 0, wxEXPAND | wxTOP, FromDIP(8));
    sidebar->Add(discard, 0, wxEXPAND | wxTOP, FromDIP(8));
    layout->Add(sidebar, 0, wxEXPAND | wxALL, FromDIP(10));
    auto* form = new wxScrolledWindow(panel, wxID_ANY);
    form->SetScrollRate(0, FromDIP(12));
    auto* fields = new wxBoxSizer(wxVERTICAL);
    fields->Add(
        new wxStaticText(
            form, wxID_ANY,
            Display("Dk와 Df는 별도로 선택합니다. 물성 관측을 검색한 뒤 해당 버튼으로 연결하세요.\n범위/한정자/시험 "
                    "조건은 서비스가 확인합니다. 직접 근사한 값에는 원문과 이유를 함께 남깁니다.")),
        0, wxEXPAND | wxBOTTOM, FromDIP(10));
    auto* identity = new wxFlexGridSizer(2, FromDIP(8), FromDIP(8));
    identity->AddGrowableCol(1);
    identity->Add(new wxStaticText(form, wxID_ANY, Display("재료 이름")), 0, wxALIGN_CENTER_VERTICAL);
    m_materialName = new wxTextCtrl(form, wxID_ANY);
    m_materialName->SetName("pcb.material_name");
    identity->Add(m_materialName, 1, wxEXPAND);
    identity->Add(new wxStaticText(form, wxID_ANY, Display("기존 재료 변경")), 0, wxALIGN_CENTER_VERTICAL);
    m_replaceMaterial = new wxChoice(form, wxID_ANY);
    m_replaceMaterial->SetName("pcb.replace_material");
    m_replaceMaterial->Append(Display("새 재료로 추가"));
    m_materialReplaceIds = {""};
    for (const auto& material : m_context.at("materials"))
    {
        m_replaceMaterial->Append(
            Display(std::to_string(m_materialReplaceIds.size()) + ". " + material.at("name").get<std::string>()));
        m_materialReplaceIds.push_back(material.at("id"));
    }
    m_replaceMaterial->SetSelection(0);
    identity->Add(m_replaceMaterial, 1, wxEXPAND);
    fields->Add(identity, 0, wxEXPAND | wxBOTTOM, FromDIP(10));
    for (std::size_t index = 0; index < m_properties.size(); ++index)
    {
        auto& property = m_properties[index];
        auto* box = new wxStaticBoxSizer(wxVERTICAL, form, Display(PropertyNames[index]));
        auto* values = new wxBoxSizer(wxHORIZONTAL);
        property.mode = new wxChoice(form, wxID_ANY);
        property.mode->SetName(Display("pcb." + PropertyFields[index] + ".mode"));
        property.mode->Append(Display("미정"));
        if (index < 2)
        {
            property.mode->Append(Display("연결한 관측의 공개값"));
        }
        property.mode->Append(Display("사용자가 직접 입력"));
        property.mode->SetSelection(0);
        property.value = new wxTextCtrl(form, wxID_ANY);
        property.value->SetName(Display("pcb." + PropertyFields[index] + ".value"));
        property.value->SetHint(Display("직접 입력할 수치"));
        property.value->Enable(false);
        values->Add(property.mode, 0, wxRIGHT, FromDIP(8));
        values->Add(property.value, 1);
        box->Add(values, 0, wxEXPAND | wxALL, FromDIP(6));
        property.reason = new wxTextCtrl(form, wxID_ANY);
        property.reason->SetName(Display("pcb." + PropertyFields[index] + ".reason"));
        property.reason->SetHint(Display("선택 / 근사 / 미정으로 남긴 이유"));
        box->Add(property.reason, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(6));
        property.source = new wxStaticText(form, wxID_ANY, Display("연결한 관측 없음"));
        property.source->SetName(Display("pcb." + PropertyFields[index] + ".source"));
        box->Add(property.source, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(6));
        if (index < 2)
        {
            auto* buttons = new wxBoxSizer(wxHORIZONTAL);
            auto* attach = new wxButton(form, wxID_ANY, Display("검색에서 선택한 관측 연결"));
            attach->SetName(Display("pcb." + PropertyFields[index] + ".attach"));
            auto* clear = new wxButton(form, wxID_ANY, Display("관측 연결 해제"));
            clear->SetName(Display("pcb." + PropertyFields[index] + ".clear"));
            buttons->Add(attach, 0, wxRIGHT, FromDIP(8));
            buttons->Add(clear);
            box->Add(buttons, 0, wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(6));
            attach->Bind(wxEVT_BUTTON,
                         [this, index](wxCommandEvent&)
                         {
                             AttachObservation(index);
                         });
            clear->Bind(wxEVT_BUTTON,
                        [this, index](wxCommandEvent&)
                        {
                            ClearObservation(index);
                        });
        }
        fields->Add(box, 0, wxEXPAND | wxBOTTOM, FromDIP(8));
        property.mode->Bind(wxEVT_CHOICE,
                            [this, index](wxCommandEvent&)
                            {
                                m_properties[index].value->Enable(m_properties[index].mode->GetSelection() ==
                                                                  (index < 2 ? 2 : 1));
                                MaterialChanged();
                            });
        property.value->Bind(wxEVT_TEXT,
                             [this](wxCommandEvent&)
                             {
                                 MaterialChanged();
                             });
        property.reason->Bind(wxEVT_TEXT,
                              [this](wxCommandEvent&)
                              {
                                  MaterialChanged();
                              });
    }
    auto* band = new wxStaticBoxSizer(wxVERTICAL, form, Display("상수 재료 모델의 적용 대역 가정"));
    auto* bounds = new wxBoxSizer(wxHORIZONTAL);
    m_bandMin = new wxTextCtrl(form, wxID_ANY);
    m_bandMin->SetName("pcb.band_min");
    m_bandMin->SetHint(Display("최소 Hz (빈칸=미정)"));
    m_bandMax = new wxTextCtrl(form, wxID_ANY);
    m_bandMax->SetName("pcb.band_max");
    m_bandMax->SetHint(Display("최대 Hz (빈칸=미정)"));
    bounds->Add(m_bandMin, 1, wxRIGHT, FromDIP(8));
    bounds->Add(m_bandMax, 1);
    band->Add(bounds, 0, wxEXPAND | wxALL, FromDIP(6));
    m_bandReason = new wxTextCtrl(form, wxID_ANY);
    m_bandReason->SetName("pcb.band_reason");
    m_bandReason->SetHint(Display("대역 가정 또는 미정 이유 (제조사 보증 대역으로 취급하지 않음)"));
    band->Add(m_bandReason, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(6));
    fields->Add(band, 0, wxEXPAND | wxBOTTOM, FromDIP(8));
    auto* save = new wxButton(form, wxID_ANY, Display("재료 입력을 이번 선택에 반영"));
    save->SetName("pcb.save_material");
    fields->Add(save, 0, wxEXPAND | wxBOTTOM, FromDIP(10));
    form->SetSizer(fields);
    layout->Add(form, 1, wxEXPAND | wxALL, FromDIP(10));
    panel->SetSizer(layout);
    for (auto* text : {m_materialName, m_bandMin, m_bandMax, m_bandReason})
    {
        text->Bind(wxEVT_TEXT,
                   [this](wxCommandEvent&)
                   {
                       MaterialChanged();
                   });
    }
    m_replaceMaterial->Bind(wxEVT_CHOICE,
                            [this](wxCommandEvent&)
                            {
                                MaterialChanged();
                            });
    add->Bind(wxEVT_BUTTON,
              [this](wxCommandEvent&)
              {
                  NewMaterial();
              });
    remove->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     RemoveMaterial();
                 });
    discard->Bind(wxEVT_BUTTON,
                  [this](wxCommandEvent&)
                  {
                      NewMaterial(true);
                      SetStatus("아직 반영하지 않은 재료 입력을 취소했습니다. 이미 반영한 재료는 목록에 남습니다.");
                  });
    save->Bind(wxEVT_BUTTON,
               [this](wxCommandEvent&)
               {
                   SaveMaterial();
               });
    m_materials->Bind(wxEVT_LISTBOX,
                      [this](wxCommandEvent& event)
                      {
                          LoadMaterial(event.GetSelection());
                      });
    return panel;
}

void PcbSelectionDialog::MaterialChanged()
{
    if (!m_loading)
    {
        m_materialDirty = true;
        Changed();
    }
}

void PcbSelectionDialog::NewMaterial(bool discard)
{
    if (m_materialDirty && !discard)
    {
        SetStatus("작성 중인 재료를 먼저 반영하거나 미반영 입력 취소를 선택하세요.");
        return;
    }
    m_loading = true;
    m_materialIndex = -1;
    m_materials->DeselectAll();
    m_materialName->ChangeValue(wxString());
    m_replaceMaterial->SetSelection(0);
    for (auto& property : m_properties)
    {
        property.mode->SetSelection(0);
        property.value->ChangeValue(wxString());
        property.value->Enable(false);
        property.reason->ChangeValue(wxString());
        property.recordId.clear();
        property.catalogId.clear();
        property.source->SetLabel(Display("연결한 관측 없음"));
    }
    m_bandMin->ChangeValue(wxString());
    m_bandMax->ChangeValue(wxString());
    m_bandReason->ChangeValue(wxString());
    m_loading = false;
    m_materialDirty = false;
}

void PcbSelectionDialog::LoadMaterial(int index)
{
    if (m_materialDirty)
    {
        if (m_materialIndex >= 0)
        {
            m_materials->SetSelection(m_materialIndex);
        }
        else
        {
            m_materials->DeselectAll();
        }
        SetStatus("작성 중인 재료를 먼저 반영하거나 미반영 입력 취소를 선택한 뒤 다른 재료로 이동하세요.");
        return;
    }
    if (index < 0 || static_cast<std::size_t>(index) >= m_materialSpecs.size())
    {
        return;
    }
    NewMaterial(true);
    m_loading = true;
    m_materialIndex = index;
    m_materials->SetSelection(index);
    const auto& material = m_materialSpecs.at(static_cast<std::size_t>(index));
    m_materialName->ChangeValue(Display(material.at("name")));
    const std::string key = material.at("key");
    const std::string replacement = m_materialIds.value(key, std::string());
    const auto mapped = std::find(m_materialReplaceIds.begin(), m_materialReplaceIds.end(), replacement);
    m_replaceMaterial->SetSelection(
        mapped == m_materialReplaceIds.end() ? 0 : static_cast<int>(mapped - m_materialReplaceIds.begin()));
    for (std::size_t field = 0; field < m_properties.size(); ++field)
    {
        auto& controls = m_properties[field];
        const auto& value = material.at("properties").at(PropertyFields[field]);
        const std::string mode = value.at("mode");
        controls.mode->SetSelection(mode == "missing" ? 0 : (mode == "catalog" ? 1 : (field < 2 ? 2 : 1)));
        controls.value->Enable(mode == "user");
        controls.value->ChangeValue(PcbView::Number(value.value("value", Json(nullptr))));
        controls.reason->ChangeValue(Display(value.at("reason")));
        controls.recordId = value.value("record_id", std::string());
        controls.catalogId = controls.recordId.empty() ? "" : m_catalogId;
        controls.source->SetLabel(
            Display(controls.recordId.empty() ? "연결한 관측 없음" : "자료 ID: " + controls.recordId));
    }
    const auto& band = material.at("validity_hz");
    m_bandMin->ChangeValue(PcbView::Number(band.at("min")));
    m_bandMax->ChangeValue(PcbView::Number(band.at("max")));
    m_bandReason->ChangeValue(Display(band.at("reason")));
    m_loading = false;
    m_materialDirty = false;
}

bool PcbSelectionDialog::SaveMaterial()
{
    try
    {
        Json material = {
            {"key", m_materialIndex < 0
                        ? "material-" + std::to_string(m_materialCounter + 1)
                        : m_materialSpecs.at(static_cast<std::size_t>(m_materialIndex)).at("key").get<std::string>()},
            {"name", PcbView::Reason(m_materialName->GetValue(), "재료 이름")},
            {"properties", Json::object()}};
        for (std::size_t index = 0; index < m_properties.size(); ++index)
        {
            const auto& property = m_properties[index];
            const int mode = property.mode->GetSelection();
            const bool user = mode == (index < 2 ? 2 : 1);
            const bool catalog = index < 2 && mode == 1;
            Json choice = {{"mode", user ? "user" : (catalog ? "catalog" : "missing")},
                           {"reason", PcbView::Reason(property.reason->GetValue(), PropertyNames[index])}};
            if (user)
            {
                const Json value = PcbView::Number(property.value->GetValue(), PropertyNames[index]);
                if (value.is_null())
                {
                    throw std::runtime_error(PropertyNames[index] +
                                             ": 직접 입력할 값을 명시하세요. 미정은 입력 방식을 변경하세요.");
                }
                choice["value"] = value;
            }
            if (catalog && property.recordId.empty())
            {
                throw std::runtime_error(PropertyNames[index] + ": 물성 관측을 검색하고 연결하세요.");
            }
            if (!property.recordId.empty())
            {
                if (property.catalogId != m_catalogId)
                {
                    throw std::runtime_error("재료와 적층은 같은 카탈로그 개정에서 선택하세요.");
                }
                choice["record_id"] = property.recordId;
            }
            material["properties"][PropertyFields[index]] = choice;
        }
        material["validity_hz"] = {{"min", PcbView::Number(m_bandMin->GetValue(), "최소 주파수")},
                                   {"max", PcbView::Number(m_bandMax->GetValue(), "최대 주파수")},
                                   {"reason", PcbView::Reason(m_bandReason->GetValue(), "적용 대역")}};
        if (m_materialIndex < 0)
        {
            if (m_materialSpecs.size() >= 16)
            {
                throw std::runtime_error("한 번에 선택할 재료는 최대 16개입니다.");
            }
            m_materialSpecs.push_back(material);
            m_materialIndex = static_cast<int>(m_materialSpecs.size()) - 1;
            ++m_materialCounter;
            m_materials->Append(Display(material.at("name")));
        }
        else
        {
            m_materialSpecs.at(static_cast<std::size_t>(m_materialIndex)) = material;
            m_materials->SetString(m_materialIndex, Display(material.at("name")));
        }
        const std::string key = material.at("key");
        const int replace = m_replaceMaterial->GetSelection();
        m_materialIds.erase(key);
        if (replace > 0)
        {
            m_materialIds[key] = m_materialReplaceIds.at(static_cast<std::size_t>(replace));
        }
        m_materials->SetSelection(m_materialIndex);
        m_materialDirty = false;
        RefreshMaterialChoices();
        Changed();
        SetStatus("재료 입력을 선택 초안에 반영했습니다. 층의 재료 연결과 변경 미리보기를 확인하세요.");
        return true;
    }
    catch (const std::exception& error)
    {
        SetStatus(error.what());
        return false;
    }
}

void PcbSelectionDialog::RemoveMaterial()
{
    if (m_materialDirty)
    {
        SetStatus("작성 중인 재료를 먼저 반영하거나 미반영 입력 취소를 선택한 뒤 제거하세요.");
        return;
    }
    if (m_materialIndex < 0)
    {
        return;
    }
    m_materialIds.erase(m_materialSpecs.at(static_cast<std::size_t>(m_materialIndex)).at("key").get<std::string>());
    m_materialSpecs.erase(m_materialSpecs.begin() + m_materialIndex);
    m_materials->Delete(m_materialIndex);
    NewMaterial(true);
    RefreshMaterialChoices();
    Changed();
}

void PcbSelectionDialog::AttachObservation(std::size_t property)
{
    if (m_selected.is_null() || m_selectedEntity != "observations")
    {
        SetStatus("자료 검색에서 물성 관측을 선택한 뒤 연결하세요.");
        return;
    }
    if (!m_catalogId.empty() && m_catalogId != m_selectedCatalog)
    {
        SetStatus("적층과 재료는 같은 카탈로그 개정에서 선택해야 합니다. 화면을 다시 열어 자료를 확인하세요.");
        return;
    }
    m_catalogId = m_selectedCatalog;
    auto& controls = m_properties.at(property);
    controls.recordId = m_selected.at("id");
    controls.catalogId = m_selectedCatalog;
    controls.source->SetLabel(Display(PcbView::Text(m_selected, "publisher") + " / " +
                                      PcbView::Text(m_selected, "product") + " / " + controls.recordId));
    MaterialChanged();
}

void PcbSelectionDialog::ClearObservation(std::size_t property)
{
    auto& controls = m_properties.at(property);
    controls.recordId.clear();
    controls.catalogId.clear();
    controls.source->SetLabel(Display("연결한 관측 없음"));
    MaterialChanged();
}
