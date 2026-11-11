/** @file @brief 선택한 적층의 두께와 Dk/Df를 함께 표시하고 명시적으로 재료 초안에 연결한다. */
#include "pcb_selection_dialog.h"
#include "pcb_selection_view_support.h"
#include "pcb_suggestion_model.h"
#include <wx/button.h>
#include <wx/grid.h>
#include <wx/listbox.h>
#include <wx/listctrl.h>
#include <wx/notebook.h>
#include <wx/panel.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/weakref.h>
#include <algorithm>

namespace
{
/** @brief 공개값과 근사 필요 상태를 함께 표시하며 비수치 값을 추정하지 않는다. */
std::string PropertyLabel(const Json& property)
{
    return PcbView::Text(property, "value") + " / " +
           Studio::PcbSuggestions::StateLabel(property.at("state").get<std::string>());
}

/** @brief 제조사 원문의 물성별 조건을 사용자가 읽을 수 있는 항목으로 표시한다. */
std::string ConditionsLabel(const Json& property)
{
    std::string result = property.at("reason").get<std::string>();
    const auto& conditions = property.at("conditions");
    for (const auto& field : std::vector<std::pair<std::string, std::string>>{{"manufacturer", "자료 업체"},
                                                                              {"product", "제품"},
                                                                              {"laminate_manufacturer", "소재 제조사"},
                                                                              {"frequency_ghz", "시험 주파수 GHz"},
                                                                              {"method", "시험법"},
                                                                              {"axis", "방향"},
                                                                              {"temperature_c", "온도 C"},
                                                                              {"material_form", "재료 형태"},
                                                                              {"construction", "구성"},
                                                                              {"glass_style", "유리 직조"},
                                                                              {"resin_content_pct", "수지 비율 %"}})
    {
        result += "\n" + field.second + ": " + PcbView::Text(conditions, field.first);
    }
    result += "\n자료 기록: " + PcbView::Text(property, "record_id");
    if (property.contains("source"))
    {
        result += "\n출처: " + PcbView::Text(property.at("source"), "publisher") + " / " +
                  PcbView::Text(property.at("source"), "source_id") +
                  "\n원문 위치: " + PcbView::Text(property.at("source"), "source_location");
    }
    if (property.contains("reported_limits"))
    {
        result += "\n원문 범위: " + PcbView::Text(property.at("reported_limits"), "_min") + " ~ " +
                  PcbView::Text(property.at("reported_limits"), "_max") +
                  " / 한정자: " + PcbView::Text(property.at("reported_limits"), "_comparison") +
                  " / 상한 조건: " + PcbView::Text(property.at("reported_limits"), "_limit_operator");
    }
    if (property.contains("reported_value"))
    {
        result += "\n원문 수치 (자동 적용하지 않음): " + PcbView::Text(property, "reported_value");
    }
    if (property.value("candidate_count", 0) > 1)
    {
        result += "\n대응 관측 수: " + PcbView::Text(property, "candidate_count") + " (자동 선택하지 않음)";
    }
    return result;
}
}

void PcbSelectionDialog::BuildSuggestions(wxPanel* panel, wxBoxSizer* layout)
{
    auto* box = new wxStaticBoxSizer(wxVERTICAL, panel, Display("선택 적층의 두께와 물성 제안"));
    m_suggestions =
        new wxListCtrl(panel, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 110)), wxLC_REPORT | wxLC_SINGLE_SEL);
    m_suggestions->SetName("pcb.suggestions");
    const char* columns[] = {"층", "두께 mm / 상태", "Dk / 상태", "Df / 상태"};
    const int widths[] = {180, 215, 230, 230};
    for (int column = 0; column < 4; ++column)
    {
        m_suggestions->InsertColumn(column, Display(columns[column]), wxLIST_FORMAT_LEFT, FromDIP(widths[column]));
    }
    box->Add(m_suggestions, 0, wxEXPAND | wxALL, FromDIP(6));
    auto* review = new wxBoxSizer(wxHORIZONTAL);
    m_suggestionDetail = new wxTextCtrl(
        panel, wxID_ANY,
        Display("자료 검색에서 적층을 선택하면 대응 물성을 제안합니다. 공개값도 해석 적용 대역은 별도로 확인하세요."),
        wxDefaultPosition, FromDIP(wxSize(-1, 70)), wxTE_MULTILINE | wxTE_READONLY);
    m_suggestionDetail->SetName("pcb.suggestion_detail");
    m_useSuggestion = new wxButton(panel, wxID_ANY, Display("선택 제안 사용"));
    m_useSuggestion->SetName("pcb.use_suggestion");
    m_useSuggestion->Enable(false);
    auto* navigation = new wxBoxSizer(wxVERTICAL);
    m_suggestionPage = new wxStaticText(panel, wxID_ANY, Display("제안 조회 전"));
    m_suggestionPage->SetName("pcb.suggestion_page");
    navigation->Add(m_suggestionPage, 0, wxBOTTOM, FromDIP(4));
    auto* paging = new wxBoxSizer(wxHORIZONTAL);
    m_suggestionPrevious = new wxButton(panel, wxID_ANY, Display("이전 제안"));
    m_suggestionPrevious->SetName("pcb.suggestion_previous");
    m_suggestionNext = new wxButton(panel, wxID_ANY, Display("다음 제안"));
    m_suggestionNext->SetName("pcb.suggestion_next");
    paging->Add(m_suggestionPrevious, 0, wxRIGHT, FromDIP(4));
    paging->Add(m_suggestionNext);
    navigation->Add(paging, 0, wxBOTTOM, FromDIP(4));
    navigation->Add(m_useSuggestion, 0, wxEXPAND);
    review->Add(m_suggestionDetail, 1, wxEXPAND | wxRIGHT, FromDIP(8));
    review->Add(navigation, 0, wxALIGN_CENTER_VERTICAL);
    box->Add(review, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(6));
    layout->Add(box, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(10));
    m_suggestions->Bind(wxEVT_LIST_ITEM_SELECTED,
                        [this](wxListEvent& event)
                        {
                            SelectSuggestion(event.GetIndex());
                        });
    m_useSuggestion->Bind(wxEVT_BUTTON,
                          [this](wxCommandEvent&)
                          {
                              UseSuggestion();
                          });
    m_suggestionPrevious->Bind(wxEVT_BUTTON,
                               [this](wxCommandEvent&)
                               {
                                   if (m_suggestionOffsets.size() > 1)
                                   {
                                       LoadSuggestionPage(m_suggestionOffsets.at(m_suggestionOffsets.size() - 2));
                                   }
                               });
    m_suggestionNext->Bind(wxEVT_BUTTON,
                           [this](wxCommandEvent&)
                           {
                               if (!m_suggestionData.is_null() && !m_suggestionData.at("next_offset").is_null())
                               {
                                   LoadSuggestionPage(m_suggestionData.at("next_offset").get<int>());
                               }
                           });
}

void PcbSelectionDialog::PopulateSuggestions(const Json& response)
{
    Studio::PcbSuggestions::Validate(m_source, response);
    m_suggestionData = response;
    m_suggestionLoading = false;
    m_suggestionIndex = -1;
    m_suggestions->DeleteAllItems();
    const auto offset = response.at("offset").get<std::size_t>();
    const auto count = response.at("returned_count").get<std::size_t>();
    const auto previous = std::find(m_suggestionOffsets.begin(), m_suggestionOffsets.end(), static_cast<int>(offset));
    if (offset == 0)
    {
        m_suggestionOffsets = {0};
    }
    else if (previous == m_suggestionOffsets.end())
    {
        m_suggestionOffsets.push_back(static_cast<int>(offset));
    }
    else
    {
        m_suggestionOffsets.erase(previous + 1, m_suggestionOffsets.end());
    }
    m_suggestionPage->SetLabel(
        Display((count == 0 ? "0" : std::to_string(offset + 1) + "-" + std::to_string(offset + count)) + " / " +
                PcbView::Text(response, "total_count") + "층"));
    for (const auto& item : response.at("layers"))
    {
        const auto index = m_suggestions->InsertItem(m_suggestions->GetItemCount(), Display(item.at("name")));
        m_suggestions->SetItem(
            index, 1,
            Display(PcbView::Text(item, "thickness_mm") + " / " +
                    Studio::PcbSuggestions::StateLabel(item.at("thickness_state").get<std::string>())));
        m_suggestions->SetItem(index, 2, Display(PropertyLabel(item.at("properties").at("epsilon_r"))));
        m_suggestions->SetItem(index, 3, Display(PropertyLabel(item.at("properties").at("tan_delta"))));
    }
    std::string detail = "층을 선택해 물성별 출처와 시험 조건을 확인하세요. "
                         "미정값은 그대로 남고 근사가 필요한 값은 직접 입력해야 합니다.";
    for (const auto& issue : response.at("issues"))
    {
        detail += "\n- " + DiagnosticMessage(issue);
    }
    m_suggestionDetail->ChangeValue(Display(detail));
    UpdateControls();
}

void PcbSelectionDialog::SelectSuggestion(long index)
{
    if (m_suggestionData.is_null() || index < 0 ||
        static_cast<std::size_t>(index) >= m_suggestionData.at("layers").size())
    {
        return;
    }
    m_suggestionIndex = index;
    const auto& item = m_suggestionData.at("layers").at(static_cast<std::size_t>(index));
    std::string text =
        item.at("name").get<std::string>() +
        "\n공개 물성의 시험 조건과 해석 적용 대역은 다릅니다. 이 제안은 제조 및 해석 준비를 승인하지 않습니다.";
    for (const auto& field : std::vector<std::pair<std::string, std::string>>{{"epsilon_r", "Dk"}, {"tan_delta", "Df"}})
    {
        const auto& property = item.at("properties").at(field.first);
        text += "\n\n" + field.second + ": " + PropertyLabel(property) + "\n" + ConditionsLabel(property);
    }
    for (const auto& note : item.at("notes"))
    {
        text += "\n" + note.get<std::string>();
    }
    m_suggestionDetail->ChangeValue(Display(text));
    UpdateControls();
}

void PcbSelectionDialog::UseSuggestion()
{
    if (m_closed || m_disconnected || m_applying || m_suggestionLoading || m_suggestionIndex < 0 ||
        m_model.CurrentStage() == Studio::PcbSelectionModel::Stage::LoadingDraft)
    {
        return;
    }
    try
    {
        if (m_materialDirty)
        {
            SetStatus("작성 중인 재료 입력을 먼저 반영하거나 취소한 뒤 제안을 사용하세요. 입력은 유지했습니다.");
            return;
        }
        m_layers->SaveEditControlValue();
        const auto usage = Studio::PcbSuggestions::PrepareUse(
            m_source, m_suggestionData, static_cast<std::size_t>(m_suggestionIndex), ReadLayerRows(), m_materialSpecs);
        const auto& material = usage.at("material");
        m_materialSpecs.push_back(material);
        m_materialProposalDisplays[material.at("key").get<std::string>()] =
            m_suggestionData.at("layers").at(static_cast<std::size_t>(m_suggestionIndex)).at("properties");
        m_materials->Append(Display(material.at("name")));
        RefreshMaterialChoices();
        const auto key = material.at("key").get<std::string>();
        const auto choice = std::find(m_materialValues.begin(), m_materialValues.end(), key);
        for (std::size_t index = 0; index < m_rows.size(); ++index)
        {
            if (m_rows.at(index).at("key") == usage.at("layer_key"))
            {
                m_layers->SetCellValue(
                    static_cast<int>(index), 5,
                    Display(m_materialLabels.at(static_cast<std::size_t>(choice - m_materialValues.begin()))));
            }
        }
        LoadMaterial(static_cast<int>(m_materialSpecs.size()) - 1);
        Changed();
        m_notebook->SetSelection(2);
        SetStatus("제안을 새 재료로 추가하고 해당 층에 연결했습니다. 미정 물성, 적용 대역과 필요 시 근사값을 "
                  "확인한 뒤 변경 미리보기를 실행하세요.");
    }
    catch (const std::exception& error)
    {
        SetStatus(error.what());
    }
}

/** @brief 제안 페이지만 다시 읽고 기존 층, 재료, 미반영 폼이나 검토 결과는 초기화하지 않는다. */
void PcbSelectionDialog::LoadSuggestionPage(int offset)
{
    if (m_closed || m_disconnected || m_applying || m_source.is_null() || m_suggestionLoading ||
        m_model.CurrentStage() == Studio::PcbSelectionModel::Stage::LoadingDraft)
    {
        return;
    }
    const auto revision = ++m_suggestionRevision;
    const auto source = m_source;
    m_suggestionLoading = true;
    UpdateControls();
    wxWeakRef<PcbSelectionDialog> weak(this);
    m_gateway(
        "catalog.stackup_suggestions", {{"source", source}, {"offset", offset}, {"limit", 8}}, false,
        [weak, revision, source](const Json& response)
        {
            if (!weak || weak->m_closed || weak->m_disconnected || revision != weak->m_suggestionRevision ||
                source != weak->m_source)
            {
                return;
            }
            try
            {
                Studio::PcbSuggestions::Validate(source, response);
                weak->PopulateSuggestions(response);
                weak->SetStatus("제안 페이지를 불러왔습니다. 작성 중인 층과 재료 입력은 유지했습니다.");
            }
            catch (const std::exception& error)
            {
                weak->m_suggestionLoading = false;
                weak->SetStatus(error.what());
                weak->UpdateControls();
            }
        },
        [weak, revision, source](const Json& error)
        {
            if (weak && !weak->m_closed && !weak->m_disconnected && revision == weak->m_suggestionRevision &&
                source == weak->m_source)
            {
                weak->m_suggestionLoading = false;
                weak->SetStatus(DiagnosticMessage(error));
                weak->UpdateControls();
            }
        });
}
