/** @file @brief 카탈로그 검색과 읽기 전용 근거 요약 화면을 구성한다. */
#include "pcb_selection_dialog.h"
#include "pcb_catalog_table.h"
#include "pcb_selection_view_support.h"
#include "pcb_suggestion_model.h"
#include <algorithm>
#include <utility>
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
                                     Display("적층과 대응 물성을 함께 확인한 뒤 제안을 사용하거나 직접 입력하세요. "
                                             "미정값과 근사가 필요한 값은 구분해 표시합니다."));
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
    m_results = new PcbCatalogTable(panel, [this](long row) { QueueCatalogPage(row); });
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
    auto* rowLabel = new wxStaticText(panel, wxID_ANY, Display("행으로 이동"));
    m_catalogRowEntry = new wxTextCtrl(panel, wxID_ANY, wxString(), wxDefaultPosition,
                                     FromDIP(wxSize(84, -1)), wxTE_PROCESS_ENTER);
    m_catalogRowEntry->SetName(Display("검색 결과 행으로 이동"));
    m_catalogRowEntry->SetHint(Display("행 번호"));
    m_catalogRowEntry->SetMaxLength(7);
    m_useSource = new wxButton(panel, wxID_ANY, Display("선택 적층과 물성 제안 보기"));
    m_useSource->SetName("pcb.use_source");
    paging->Add(m_previous, 0, wxRIGHT, FromDIP(6));
    paging->Add(m_next, 0, wxRIGHT, FromDIP(12));
    paging->Add(m_pageLabel, 1, wxALIGN_CENTER_VERTICAL);
    paging->Add(rowLabel, 0, wxALIGN_CENTER_VERTICAL | wxRIGHT, FromDIP(6));
    paging->Add(m_catalogRowEntry, 0, wxRIGHT, FromDIP(12));
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
        ResetCatalogRows();
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
                         MoveCatalogView(m_results->GetTopItem() - std::max(1, m_results->GetCountPerPage()));
                     });
    m_next->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     MoveCatalogView(m_results->GetTopItem() + 2 * std::max(1, m_results->GetCountPerPage()) - 1);
                 });
    m_catalogRowEntry->Bind(wxEVT_TEXT_ENTER,
                            [this](wxCommandEvent&)
                            {
                                long row = 0;
                                if (m_catalogRowEntry->GetValue().ToLong(&row) && row >= 1 && row <= m_catalogRowCount)
                                {
                                    MoveCatalogView(row - 1);
                                }
                                else
                                {
                                    SetStatus("결과 범위 안의 행 번호를 입력하세요.");
                                }
                            });
    m_results->Bind(wxEVT_LIST_ITEM_SELECTED,
                    [this](wxListEvent& event)
                    {
                        SelectResult(event.GetIndex());
                    });
    m_results->Bind(wxEVT_LIST_ITEM_DESELECTED,
                    [this](wxListEvent&)
                    {
                        if (m_results->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED) < 0)
                        {
                            ++m_detailRevision;
                            m_selected = nullptr;
                            m_detail->ChangeValue(Display("표에서 자료를 선택해 원문 요약과 시험 조건을 확인하세요."));
                            UpdateControls();
                        }
                    });
    m_useSource->Bind(wxEVT_BUTTON,
                      [this](wxCommandEvent&)
                      {
                          UseSource();
                      });
    return panel;
}

/** @brief 이전 검색 세대를 폐기하고 상세/선택과 행 범위를 함께 초기화한다. */
void PcbSelectionDialog::ResetCatalogRows()
{
    ++m_filterRevision;
    ++m_detailRevision;
    m_selected = nullptr;
    m_catalogSearchInput = Json::object();
    m_catalogRowCount = 0;
    m_catalogWantedRow = -1;
    m_catalogPageQueued = false;
    m_catalogPageLoading = false;
    m_results->Reset();
    m_pageLabel->SetLabel(Display("검색 전"));
    m_catalogRowEntry->ChangeValue(wxString());
    m_detail->ChangeValue(Display("표에서 자료를 선택해 원문 요약과 시험 조건을 확인하세요."));
}

/** @brief 검색 범위와 첫 페이지를 동일 카탈로그 개정에서 가져온다. */
void PcbSelectionDialog::Search()
{
    if (m_closed || m_applying || m_disconnected)
    {
        return;
    }
    try
    {
        ResetCatalogRows();
        const std::string entity = m_entity->GetSelection() == 0 ? "native_templates" : "observations";
        Json input = {{"entity", entity},
                      {"query", Utf8(m_query->GetValue())},
                      {"filters", Json::object()},
                      {"limit", PcbCatalogTable::PageSize},
                      {"include_total", true}};
        if (!m_publisher->GetValue().empty())
        {
            input["filters"]["publisher"] = Utf8(m_publisher->GetValue());
        }
        const auto filter = m_filterRevision;
        const auto token = m_model.BeginRequest("search");
        m_pageLabel->SetLabel(Display("검색 중"));
        SetStatus("카탈로그 검색 결과를 읽고 있습니다. 직접 층 구성도 사용할 수 있습니다.");
        UpdateControls();
        wxWeakRef<PcbSelectionDialog> weak(this);
        m_gateway(
            "catalog.search", input, false,
            [weak, token, filter, input, entity](const Json& result)
            {
                if (!weak || weak->m_closed || weak->m_disconnected || filter != weak->m_filterRevision ||
                    !weak->m_model.AcceptSearch(token, result))
                {
                    return;
                }
                const auto total = result.at("total_count").get<long long>();
                constexpr long SearchableRows = 1000001;
                weak->m_catalogRowCount = static_cast<long>(std::min<long long>(total, SearchableRows));
                weak->m_catalogSearchInput = input;
                weak->m_catalogSearchInput.erase("include_total");
                weak->m_catalogSearchInput["catalog_id"] = result.at("catalog_id");
                weak->m_results->Begin(entity, weak->m_catalogRowCount, result.at("items"));
                const std::string count = total > SearchableRows
                    ? std::to_string(SearchableRows) + " / " + std::to_string(total) + "건 (검색 범위를 좁히세요)"
                    : std::to_string(total) + "건";
                weak->m_pageLabel->SetLabel(Display(count));
                weak->SetStatus(total == 0 ? "검색 조건과 일치하는 공개 자료가 없습니다."
                                           : "검색 결과는 공개 자료 요약입니다. 상세에서 원문과 시험 조건을 확인하세요.");
                weak->UpdateControls();
                weak->m_pageLabel->GetParent()->Layout();
            },
            [weak, token, filter](const Json& error)
            {
                if (weak && !weak->m_closed && !weak->m_disconnected && filter == weak->m_filterRevision &&
                    weak->m_model.Fail(token, error))
                {
                    weak->m_pageLabel->SetLabel(Display("검색 실패"));
                    weak->ShowFailure(error);
                }
            });
    }
    catch (const std::exception& error)
    {
        SetStatus(error.what());
    }
}

/** @brief 필요한 행만 한 요청씩 가져오며 포커스를 둔 행을 먼저 처리한다. */
void PcbSelectionDialog::QueueCatalogPage(long row, bool selected)
{
    if (m_closed || m_disconnected || m_applying || row < 0 || row >= m_catalogRowCount ||
        m_catalogSearchInput.empty() || m_results->Row(row) != nullptr)
    {
        return;
    }
    if (selected || m_catalogWantedRow < 0)
    {
        m_catalogWantedRow = row;
    }
    if (!m_catalogPageQueued && !m_catalogPageLoading)
    {
        m_catalogPageQueued = true;
        const auto filter = m_filterRevision;
        CallAfter(
            [this, filter]()
            {
                if (filter == m_filterRevision)
                {
                    m_catalogPageQueued = false;
                    LoadCatalogPage();
                }
            });
    }
}

/** @brief 표시용 페이지를 읽되 초안과 변경 검토 토큰을 건드리지 않는다. */
void PcbSelectionDialog::LoadCatalogPage()
{
    if (m_closed || m_disconnected || m_applying || m_catalogSearchInput.empty() || m_catalogWantedRow < 0)
    {
        return;
    }
    const long row = std::exchange(m_catalogWantedRow, -1);
    if (m_results->Row(row) != nullptr)
    {
        return;
    }
    const long offset = m_results->MissingOffset(row);
    Json input = m_catalogSearchInput;
    input["offset"] = offset;
    const long blockEnd = (offset / PcbCatalogTable::PageSize + 1) * PcbCatalogTable::PageSize;
    input["limit"] = std::min(blockEnd, m_catalogRowCount) - offset;
    m_catalogPageLoading = true;
    const auto filter = m_filterRevision;
    wxWeakRef<PcbSelectionDialog> weak(this);
    m_gateway(
        "catalog.search", input, false,
        [weak, filter, offset, row](const Json& result)
        {
            if (!weak || weak->m_closed || weak->m_disconnected || filter != weak->m_filterRevision)
            {
                return;
            }
            weak->m_catalogPageLoading = false;
            if (result.at("items").empty() || result.at("offset") != offset ||
                result.at("catalog_id") != weak->m_catalogSearchInput.at("catalog_id"))
            {
                weak->ResetCatalogRows();
                weak->SetStatus("검색 범위가 변경되었습니다. 다시 검색하세요.");
                weak->UpdateControls();
                return;
            }
            weak->m_results->StorePage(offset, result.at("items"));
            const long selected = weak->m_results->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
            if (selected >= 0 && weak->m_selected.is_null() && weak->m_results->Row(selected))
            {
                weak->SelectResult(selected);
            }
            const long top = weak->m_results->GetTopItem();
            const long visibleEnd = std::min<long>(weak->m_catalogRowCount, top + weak->m_results->GetCountPerPage() + 1);
            const long pending = std::exchange(weak->m_catalogWantedRow, -1);
            weak->QueueCatalogPage(pending);
            if ((row >= top && row < visibleEnd) || selected == row)
            {
                weak->QueueCatalogPage(row);
            }
            for (long visible = top; visible < visibleEnd && weak->m_catalogWantedRow < 0; ++visible)
            {
                weak->QueueCatalogPage(visible);
            }
        },
        [weak, filter](const Json& error)
        {
            if (weak && !weak->m_closed && !weak->m_disconnected && filter == weak->m_filterRevision)
            {
                weak->ResetCatalogRows();
                weak->ShowFailure(error);
            }
        });
}

/** @brief 마우스 스크롤과 같은 표를 키보드로도 원하는 행까지 이동한다. */
void PcbSelectionDialog::MoveCatalogView(long row)
{
    if (m_catalogRowCount > 0)
    {
        row = std::clamp(row, 0L, m_catalogRowCount - 1);
        m_results->EnsureVisible(row);
        QueueCatalogPage(row, true);
    }
}

/** @brief 선택한 관측의 조건을 읽기 전용 문구로 표시한다. 큰 원문을 재작성하지 않는다. */
void PcbSelectionDialog::SelectResult(long index)
{
    ++m_detailRevision;
    m_selected = nullptr;
    if (m_model.CurrentStage() == Studio::PcbSelectionModel::Stage::LoadingDraft)
    {
        m_model.Invalidate();
    }
    const Json* row = m_results->Row(index);
    if (row == nullptr)
    {
        m_detail->ChangeValue(Display("선택한 행을 읽고 있습니다."));
        QueueCatalogPage(index, true);
        UpdateControls();
        return;
    }
    m_selected = *row;
    m_selectedCatalog = m_catalogSearchInput.at("catalog_id");
    m_selectedEntity = m_catalogSearchInput.at("entity");
    const auto detail = ++m_detailRevision;
    m_detail->ChangeValue(Display(
        "선택: " + PcbView::Text(m_selected, "publisher") + " / " +
        (m_selectedEntity == "native_templates" ? PcbCatalogTable::NativeLabel(m_selected) : PcbView::Text(m_selected, "product")) +
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
                summary += "\n공개 적층명: " + PcbCatalogTable::NativeLabel(item) + "\n공개 구성: " + PcbCatalogTable::NativeDimensions(item) +
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
        ++m_suggestionRevision;
        m_suggestionLoading = false;
        const auto token = m_model.BeginRequest("draft");
        SetStatus("선택한 적층의 두께와 연결 가능한 물성 자료를 확인하고 있습니다.");
        UpdateControls();
        wxWeakRef<PcbSelectionDialog> weak(this);
        m_gateway(
            "catalog.stackup_suggestions", Json{{"source", source}}, false,
            [weak, token, source](const Json& response)
            {
                if (!weak || weak->m_closed || weak->m_disconnected || !weak->m_model.IsCurrent(token))
                {
                    return;
                }
                try
                {
                    Studio::PcbSuggestions::Validate(source, response);
                    const auto& draft = response.at("draft");
                    if (!weak->m_model.SelectSource(token, source, draft))
                    {
                        return;
                    }
                    weak->m_source = source;
                    weak->m_catalogId = source.at("catalog_id");
                    weak->m_manual = false;
                    weak->PopulateLayers(weak->m_model.LayerRows(), false);
                    weak->PopulateSuggestions(response);
                    weak->m_notebook->SetSelection(1);
                    std::string message =
                        "적층과 물성 제안을 불러왔습니다. 제안은 확인 후 사용하며 기존 직접 입력은 유지됩니다.";
                    if (!draft.at("issues").empty())
                    {
                        message += "\n확인할 사항 " + std::to_string(draft.at("issues").size()) +
                                   "개는 제안 상세와 변경 미리보기에서 확인하세요.";
                    }
                    weak->SetStatus(message);
                }
                catch (const std::exception& error)
                {
                    weak->m_model.Fail(token, {{"message_ko", error.what()}});
                    weak->SetStatus(error.what());
                }
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
