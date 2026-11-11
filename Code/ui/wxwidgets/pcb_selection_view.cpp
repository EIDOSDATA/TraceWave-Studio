/** @file @brief 카탈로그 검색과 읽기 전용 근거 요약 화면을 구성한다. */
#include "pcb_selection_dialog.h"
#include "pcb_selection_view_support.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/combobox.h>
#include <wx/listctrl.h>
#include <wx/notebook.h>
#include <wx/panel.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/weakref.h>

namespace
{
/** @brief 내부 템플릿 해시 대신 서비스가 연결한 공개 적층 표기를 우선한다. */
std::string NativeLabel(const Json& row)
{
    if (row.contains("stackup_label") && row.at("stackup_label").is_string() &&
        !row.at("stackup_label").get<std::string>().empty())
    {
        return row.at("stackup_label");
    }
    if (row.value("kind", std::string()) == "jlc_user_defined_template")
    {
        return "사용자 정의 구성 (공개 적층명 없음)";
    }
    return "공개 적층명 미연결 (상세 확인)";
}

/** @brief 공개 층수와 공칭값을 완성 두께 또는 해석 준비로 단정하지 않는다. */
std::string NativeDimensions(const Json& row)
{
    return PcbView::Text(row, "layer_count") + "층 / 공칭 " + PcbView::Text(row, "nominal_thickness_mm") + " mm";
}

/** @brief Df 전용 주파수와 기록 공통 조건을 합치지 않고 표시한다. */
std::string FrequencySummary(const Json& frequency)
{
    return "보고값 " + PcbView::Text(frequency, "point_ghz") + " GHz, 범위 " + PcbView::Text(frequency, "minimum_ghz") +
           " ~ " + PcbView::Text(frequency, "maximum_ghz") + " GHz, 원문 표기 " + PcbView::Text(frequency, "text");
}

/** @brief 원문 전체 대신 제한된 물성 요약과 축약 여부를 알려준다. */
std::string PropertySummary(const Json& dto)
{
    std::string summary = "\n\n물성 요약 (원문 전체가 아니며 미제공 조건은 추정하지 않음)";
    for (const char* name : {"dk", "df"})
    {
        const auto& property = dto.at("properties").at(name);
        const auto& value = property.at("value");
        summary += "\n\n" + std::string(name) + ": " + PcbView::Text(value, "scalar") + ", 범위 " +
                   PcbView::Text(value, "minimum") + " ~ " + PcbView::Text(value, "maximum") + ", 종류 " +
                   PcbView::Text(value, "representation") + "\n한정자: " + PcbView::Text(value, "comparison") + " / " +
                   PcbView::Text(value, "limit_operator") + ", 원문 표기: " + PcbView::Text(value, "text") + "\n" +
                   (std::string(name) == "df" ? "Df 전용 주파수: " : "기록 주파수: ") +
                   FrequencySummary(property.at("frequency")) +
                   "\n시험법: " + PcbView::Text(property.at("method"), "value");
    }
    const auto& context = dto.at("record_context");
    summary += "\n\n기록 공통 조건 (Df 전용 조건으로 대체하지 않음)\n" + FrequencySummary(context.at("frequency"));
    for (const auto& item : std::vector<std::pair<std::string, std::string>>{{"method", "시험법"},
                                                                             {"axis", "방향"},
                                                                             {"value_type", "값 구분"},
                                                                             {"material_form", "재료 형태"},
                                                                             {"glass_style", "유리 직조"},
                                                                             {"construction", "구성"},
                                                                             {"conditioning", "조건 처리"},
                                                                             {"thickness_mm", "두께 mm"},
                                                                             {"resin_content_pct", "수지 비율 %"},
                                                                             {"temperature_c", "온도 C"},
                                                                             {"relative_humidity_pct", "상대습도 %"}})
    {
        summary += "\n" + item.second + ": " + PcbView::Text(context, item.first);
    }
    if (!dto.at("truncated_fields").empty())
    {
        summary += "\n일부 긴 조건이 축약되었습니다. 채택 전 원자료와 선택 검토 사유를 확인하세요.";
    }
    return summary;
}
}

void PcbSelectionDialog::BuildInterface()
{
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* heading = new wxStaticText(this, wxID_ANY,
                                     Display("공개 적층을 고르거나 직접 구성한 뒤 변경 내용을 검토하세요. 빈칸은 "
                                             "미정이며 물성을 자동으로 채우지 않습니다."));
    layout->Add(heading, 0, wxEXPAND | wxALL, FromDIP(12));
    m_notebook = new wxNotebook(this, wxID_ANY);
    m_notebook->SetName("pcb.notebook");
    m_notebook->AddPage(BuildCatalogPage(), Display("1. 자료 검색"));
    m_notebook->AddPage(BuildLayersPage(), Display("2. 층과 연결"));
    m_notebook->AddPage(BuildMaterialsPage(), Display("3. 재료 물성"));
    m_notebook->AddPage(BuildPortsPage(), Display("4. 급전 좌표"));
    m_notebook->AddPage(BuildReviewPage(), Display("5. 변경 검토"));
    layout->Add(m_notebook, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    m_status = new wxStaticText(this, wxID_ANY,
                                Display("프로젝트의 기존 적층을 유지합니다. 출처 선택 또는 직접 편집을 시작하세요."));
    m_status->SetName("pcb.status");
    layout->Add(m_status, 0, wxEXPAND | wxALL, FromDIP(12));
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    actions->AddStretchSpacer();
    m_previewButton = new wxButton(this, wxID_ANY, Display("변경 미리보기"));
    m_previewButton->SetName("pcb.preview");
    m_applyButton = new wxButton(this, wxID_ANY, Display("검토한 변경 적용"));
    m_applyButton->SetName("pcb.apply");
    m_cancelButton = new wxButton(this, wxID_CANCEL, Display("닫기"));
    m_cancelButton->SetName("pcb.cancel");
    actions->Add(m_previewButton, 0, wxRIGHT, FromDIP(8));
    actions->Add(m_applyButton, 0, wxRIGHT, FromDIP(8));
    actions->Add(m_cancelButton);
    layout->Add(actions, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(12));
    SetSizer(layout);
    m_previewButton->Bind(wxEVT_BUTTON,
                          [this](wxCommandEvent&)
                          {
                              Preview();
                          });
    m_applyButton->Bind(wxEVT_BUTTON,
                        [this](wxCommandEvent&)
                        {
                            Apply();
                        });
}

wxPanel* PcbSelectionDialog::BuildCatalogPage()
{
    auto* panel = new wxPanel(m_notebook);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* filters = new wxBoxSizer(wxHORIZONTAL);
    m_entity = new wxChoice(panel, wxID_ANY);
    m_entity->SetName("pcb.entity");
    m_entity->Append(Display("제조업체 적층"));
    m_entity->Append(Display("물성 관측"));
    m_entity->SetSelection(0);
    m_publisher = new wxComboBox(panel, wxID_ANY, wxString(), wxDefaultPosition, FromDIP(wxSize(190, -1)));
    m_publisher->SetName("pcb.publisher");
    for (const char* name : {"", "JLCPCB", "PCBWay", "Wurth Elektronik", "OSH Park", "Isola", "Rogers"})
    {
        m_publisher->Append(Display(name));
    }
    m_publisher->SetHint(Display("공개 업체명 (빈칸=전체)"));
    m_query = new wxTextCtrl(panel, wxID_ANY, wxString(), wxDefaultPosition, wxDefaultSize, wxTE_PROCESS_ENTER);
    m_query->SetName("pcb.query");
    m_query->SetHint(Display("제품 또는 적층 표기의 일부"));
    m_search = new wxButton(panel, wxID_ANY, Display("검색"));
    m_search->SetName("pcb.search");
    filters->Add(m_entity, 0, wxRIGHT, FromDIP(8));
    filters->Add(m_publisher, 0, wxRIGHT, FromDIP(8));
    filters->Add(m_query, 1, wxRIGHT, FromDIP(8));
    filters->Add(m_search);
    layout->Add(filters, 0, wxEXPAND | wxALL, FromDIP(10));
    m_results = new wxListCtrl(panel, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_SINGLE_SEL);
    m_results->SetName("pcb.results");
    const char* columns[] = {"공개 주체", "제품 / 적층 표기", "구성 / 형태", "Dk", "Df", "보고 주파수 GHz"};
    const int widths[] = {150, 260, 180, 75, 75, 130};
    for (int column = 0; column < 6; ++column)
    {
        m_results->InsertColumn(column, Display(columns[column]), wxLIST_FORMAT_LEFT, FromDIP(widths[column]));
    }
    layout->Add(m_results, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(10));
    auto* paging = new wxBoxSizer(wxHORIZONTAL);
    m_previous = new wxButton(panel, wxID_ANY, Display("이전"));
    m_previous->SetName("pcb.previous");
    m_next = new wxButton(panel, wxID_ANY, Display("다음"));
    m_next->SetName("pcb.next");
    m_pageLabel = new wxStaticText(panel, wxID_ANY, Display("검색 전"));
    m_useSource = new wxButton(panel, wxID_ANY, Display("선택 자료로 적층 초안 만들기"));
    m_useSource->SetName("pcb.use_source");
    paging->Add(m_previous, 0, wxRIGHT, FromDIP(6));
    paging->Add(m_next, 0, wxRIGHT, FromDIP(12));
    paging->Add(m_pageLabel, 1, wxALIGN_CENTER_VERTICAL);
    paging->Add(m_useSource);
    layout->Add(paging, 0, wxEXPAND | wxALL, FromDIP(10));
    m_detail = new wxTextCtrl(
        panel, wxID_ANY, Display("표의 Dk/Df는 원문 요약입니다. 채택 전 각 물성의 시험 조건과 한정자를 확인하세요."),
        wxDefaultPosition, FromDIP(wxSize(-1, 145)), wxTE_MULTILINE | wxTE_READONLY);
    m_detail->SetName("pcb.detail");
    layout->Add(m_detail, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(10));
    panel->SetSizer(layout);
    const auto change = [this](wxCommandEvent&)
    {
        ++m_filterRevision;
        ++m_detailRevision;
        m_selected = nullptr;
        m_searchResult = Json::object();
        m_results->DeleteAllItems();
        m_pageOffsets = {0};
        Changed();
    };
    m_entity->Bind(wxEVT_CHOICE, change);
    m_publisher->Bind(wxEVT_TEXT, change);
    m_query->Bind(wxEVT_TEXT, change);
    m_query->Bind(wxEVT_TEXT_ENTER,
                  [this](wxCommandEvent&)
                  {
                      Search();
                  });
    m_search->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       Search();
                   });
    m_previous->Bind(wxEVT_BUTTON,
                     [this](wxCommandEvent&)
                     {
                         if (m_pageOffsets.size() > 1)
                         {
                             m_pageOffsets.pop_back();
                             Search(m_pageOffsets.back());
                         }
                     });
    m_next->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     if (m_searchResult.value("has_more", false))
                     {
                         const int offset = m_searchResult.at("next_offset").get<int>();
                         m_pageOffsets.push_back(offset);
                         Search(offset);
                     }
                 });
    m_results->Bind(wxEVT_LIST_ITEM_SELECTED,
                    [this](wxListEvent& event)
                    {
                        SelectResult(event.GetIndex());
                    });
    m_useSource->Bind(wxEVT_BUTTON,
                      [this](wxCommandEvent&)
                      {
                          UseSource();
                      });
    return panel;
}

/** @brief 검색어와 개정에 묶인 제한된 페이지 한 개만 표시한다. */
void PcbSelectionDialog::Search(int offset)
{
    if (m_closed || m_applying || m_disconnected)
    {
        return;
    }
    try
    {
        if (offset == 0)
        {
            m_pageOffsets = {0};
        }
        const std::string entity = m_entity->GetSelection() == 0 ? "native_templates" : "observations";
        Json input = {{"entity", entity},
                      {"query", Utf8(m_query->GetValue())},
                      {"filters", Json::object()},
                      {"limit", 25},
                      {"offset", offset}};
        if (!m_publisher->GetValue().empty())
        {
            input["filters"]["publisher"] = Utf8(m_publisher->GetValue());
        }
        if (offset > 0)
        {
            input["catalog_id"] = m_searchResult.at("catalog_id");
        }
        m_selected = nullptr;
        ++m_detailRevision;
        const auto filter = m_filterRevision;
        const auto token = m_model.BeginRequest("search");
        SetStatus("카탈로그의 제한된 목록을 읽고 있습니다. 직접 층 구성도 사용할 수 있습니다.");
        UpdateControls();
        wxWeakRef<PcbSelectionDialog> weak(this);
        m_gateway(
            "catalog.search", input, false,
            [weak, token, filter, entity](const Json& result)
            {
                if (!weak || weak->m_closed || weak->m_disconnected || filter != weak->m_filterRevision ||
                    !weak->m_model.AcceptSearch(token, result))
                {
                    return;
                }
                weak->m_searchResult = result;
                weak->m_results->DeleteAllItems();
                for (const auto& row : result.at("items"))
                {
                    const long index = weak->m_results->InsertItem(weak->m_results->GetItemCount(),
                                                                   Display(PcbView::Text(row, "publisher")));
                    weak->m_results->SetItem(
                        index, 1,
                        Display(entity == "native_templates" ? NativeLabel(row) : PcbView::Text(row, "product")));
                    weak->m_results->SetItem(index, 2,
                                             Display(entity == "native_templates"
                                                         ? NativeDimensions(row)
                                                         : PcbView::Text(row, "material_form")));
                    for (int column = 3; column < 6; ++column)
                    {
                        const char* field = column == 3 ? "dk" : (column == 4 ? "df" : "frequency_ghz");
                        weak->m_results->SetItem(index, column, Display(PcbView::Text(row, field)));
                    }
                }
                weak->m_pageLabel->SetLabel(Display(std::to_string(result.at("offset").get<int>() + 1) + "번째부터 " +
                                                    std::to_string(result.at("returned_count").get<int>()) + "개"));
                weak->SetStatus("검색 결과는 공개 자료 요약입니다. 제품이나 해석 준비가 확인되었다는 뜻은 아닙니다.");
                weak->UpdateControls();
            },
            [weak, token, filter](const Json& error)
            {
                if (weak && !weak->m_closed && !weak->m_disconnected && filter == weak->m_filterRevision &&
                    weak->m_model.Fail(token, error))
                {
                    weak->ShowFailure(error);
                }
            });
    }
    catch (const std::exception& error)
    {
        SetStatus(error.what());
    }
}

/** @brief 선택한 관측의 조건을 읽기 전용 문구로 표시한다. 큰 원문을 재작성하지 않는다. */
void PcbSelectionDialog::SelectResult(long index)
{
    if (!m_searchResult.contains("items") || index < 0 ||
        static_cast<std::size_t>(index) >= m_searchResult.at("items").size())
    {
        return;
    }
    m_selected = m_searchResult.at("items").at(static_cast<std::size_t>(index));
    m_selectedCatalog = m_searchResult.at("catalog_id");
    m_selectedEntity = m_searchResult.at("entity");
    const auto detail = ++m_detailRevision;
    m_detail->ChangeValue(Display(
        "선택: " + PcbView::Text(m_selected, "publisher") + " / " +
        (m_selectedEntity == "native_templates" ? NativeLabel(m_selected) : PcbView::Text(m_selected, "product")) +
        "\n자료 ID: " + m_selected.at("id").get<std::string>() + "\n상세 조건을 읽고 있습니다."));
    UpdateControls();
    wxWeakRef<PcbSelectionDialog> weak(this);
    m_gateway(
        "catalog.get",
        {{"entity", m_selectedEntity},
         {"id", m_selected.at("id")},
         {"catalog_id", m_selectedCatalog},
         {"raw_limit", 1}},
        false,
        [weak, detail](const Json& result)
        {
            if (!weak || weak->m_closed || detail != weak->m_detailRevision)
            {
                return;
            }
            const auto& item = result.at("item");
            std::string summary =
                "공개 주체: " + PcbView::Text(item, "publisher") + "\n자료 ID: " + PcbView::Text(item, "id");
            if (result.value("entity", std::string()) == "native_templates")
            {
                summary += "\n공개 적층명: " + NativeLabel(item) + "\n공개 구성: " + NativeDimensions(item) +
                           "\n공칭값은 원문의 완성 두께 포함 범위와 공차를 별도로 확인해야 합니다.";
            }
            for (const char* field :
                 {"product", "template_key", "material_form", "value_type", "source_id", "source_path"})
            {
                if (item.contains(field))
                {
                    summary += "\n" + std::string(field) + ": " + PcbView::Text(item, field);
                }
            }
            if (result.contains("properties"))
            {
                summary += PropertySummary(result.at("properties"));
            }
            if (item.contains("truncated_fields") && !item.at("truncated_fields").empty())
            {
                summary += "\n일부 목록/상세 표기가 축약되었습니다.";
            }
            if (item.contains("review_flags"))
            {
                summary += "\n검토 표식: ";
                for (const auto& flag : item.at("review_flags"))
                {
                    summary += flag.get<std::string>() + "; ";
                }
            }
            weak->m_detail->ChangeValue(Display(summary));
        },
        [weak, detail](const Json& error)
        {
            if (weak && !weak->m_closed && detail == weak->m_detailRevision)
            {
                weak->m_detail->ChangeValue(Display(DiagnosticMessage(error)));
            }
        });
}

void PcbSelectionDialog::UseSource()
{
    if (m_selected.is_null())
    {
        return;
    }
    try
    {
        if (!m_catalogId.empty() && m_catalogId != m_selectedCatalog)
        {
            SetStatus("기존 선택 근거와 다른 카탈로그 개정입니다. 화면을 다시 열어 모든 재료와 적층을 같은 개정에서 "
                      "선택하세요.");
            return;
        }
        const Json source = {
            {"catalog_id", m_selectedCatalog}, {"entity", m_selectedEntity}, {"id", m_selected.at("id")}};
        const auto token = m_model.BeginRequest("draft");
        SetStatus("출처에 명시된 구성으로 층 초안을 만들고 있습니다.");
        UpdateControls();
        wxWeakRef<PcbSelectionDialog> weak(this);
        m_gateway(
            "catalog.stackup_draft", source, false,
            [weak, token, source](const Json& draft)
            {
                if (!weak || weak->m_closed || weak->m_disconnected ||
                    !weak->m_model.SelectSource(token, source, draft))
                {
                    return;
                }
                weak->m_source = source;
                weak->m_catalogId = source.at("catalog_id");
                weak->m_manual = false;
                weak->PopulateLayers(weak->m_model.LayerRows(), false);
                weak->m_notebook->SetSelection(1);
                std::string message = "출처 초안을 불러왔습니다. 기존 층 연결, 미정 두께와 물성을 확인하세요.";
                for (const auto& issue : draft.at("issues"))
                {
                    message += "\n- " + DiagnosticMessage(issue);
                }
                weak->SetStatus(message);
                weak->UpdateControls();
            },
            [weak, token](const Json& error)
            {
                if (weak && !weak->m_closed && !weak->m_disconnected && weak->m_model.Fail(token, error))
                {
                    weak->ShowFailure(error);
                }
            });
    }
    catch (const std::exception& error)
    {
        SetStatus(error.what());
    }
}
