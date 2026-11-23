/** @file @brief 측정 비교의 기록 선택과 원문/정렬 동작을 native 입력으로 제공한다. */
#include "measurement_compare_view.h"
#include "result_compare_view.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/wrapsizer.h>

MeasurementCompareView::MeasurementCompareView(wxWindow* parent) : wxPanel(parent)
{
    SetName("measurement.compare");
    StudioTheme::BindSurface(*this);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* tools = new wxWrapSizer(wxHORIZONTAL);
    tools->Add(new wxStaticText(this, wxID_ANY, Display("시료 / 교정 기록")), 0, wxALIGN_CENTER_VERTICAL | wxALL,
               FromDIP(4));
    m_record = new wxChoice(this, wxID_ANY);
    m_record->SetName("measurement.records");
    m_record->SetMinSize(FromDIP(wxSize(240, -1)));
    tools->Add(m_record, 0, wxALL, FromDIP(4));
    m_refresh = new wxButton(this, wxID_ANY, Display("목록 새로고침"));
    m_add = new wxButton(this, wxID_ANY, Display("기록을 비교에 추가"));
    m_edit = new wxButton(this, wxID_ANY, Display("시료 / 교정 편집"));
    m_new = new wxButton(this, wxID_ANY, Display("선택 원본에 기록 추가"));
    m_import = new wxButton(this, wxID_ANY, Display("자료 가져오기"));
    m_align = new wxButton(this, wxID_ANY, Display("명시 정렬 검토"));
    m_save = new wxButton(this, wxID_ANY, Display("비교 보고서 저장"));
    for (auto* button : {m_refresh, m_add, m_edit, m_new, m_import, m_align, m_save})
    {
        StudioTheme::Button(*button);
        tools->Add(button, 0, wxALL, FromDIP(4));
    }
    layout->Add(tools, 0, wxEXPAND | wxALL, FromDIP(4));
    auto* history = new wxWrapSizer(wxHORIZONTAL);
    history->Add(new wxStaticText(this, wxID_ANY, Display("보존 정렬 / 비교 보고서")), 0,
                 wxALIGN_CENTER_VERTICAL | wxALL, FromDIP(4));
    m_history = new wxChoice(this, wxID_ANY);
    m_history->SetMinSize(FromDIP(wxSize(240, -1)));
    m_readHistory = new wxButton(this, wxID_ANY, Display("당시 보고서 열기"));
    m_recover = new wxButton(this, wxID_ANY, Display("이전 변경 결과 확인"));
    history->Add(m_history, 0, wxALL, FromDIP(4));
    history->Add(m_readHistory, 0, wxALL, FromDIP(4));
    history->Add(m_recover, 0, wxALL, FromDIP(4));
    layout->Add(history, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(4));
    m_history->Bind(wxEVT_CHOICE,
                    [this](wxCommandEvent&)
                    {
                        Actions();
                    });
    m_readHistory->Bind(wxEVT_BUTTON,
                        [this](wxCommandEvent&)
                        {
                            const int selected = m_history->GetSelection();
                            if (onHistory && selected >= 0)
                            {
                                onHistory(m_histories.at(selected));
                            }
                        });
    m_recover->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        if (onRecover)
                        {
                            onRecover();
                        }
                    });
    m_status = new wxStaticText(this, wxID_ANY,
                                Display("선택 기능입니다. 비교할 측정 자료가 있으면 가져오세요."));
    StudioTheme::BindSecondary(*m_status);
    layout->Add(m_status, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    m_compare = new ResultCompareView(this, true);
    m_compare->onActionsChanged = [this]()
    {
        Actions();
    };
    layout->Add(m_compare, 1, wxEXPAND);
    SetSizer(layout);
    m_record->Bind(wxEVT_CHOICE,
                   [this](wxCommandEvent&)
                   {
                       Actions();
                   });
    m_refresh->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        if (onRefresh)
                        {
                            onRefresh();
                        }
                    });
    m_add->Bind(wxEVT_BUTTON,
                [this](wxCommandEvent&)
                {
                    if (onAddRecord && RecordRef().is_object())
                    {
                        onAddRecord(RecordRef());
                    }
                });
    m_edit->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     if (onEditRecord && RecordRef().is_object())
                     {
                         onEditRecord(RecordRef());
                     }
                 });
    m_new->Bind(wxEVT_BUTTON,
                [this](wxCommandEvent&)
                {
                    if (onNewRecord)
                    {
                        onNewRecord();
                    }
                });
    m_import->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       if (onImport)
                       {
                           onImport();
                       }
                   });
    m_align->Bind(wxEVT_BUTTON,
                  [this](wxCommandEvent&)
                  {
                      if (onAlign)
                      {
                          onAlign();
                      }
                  });
    m_save->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     if (onSaveComparison)
                     {
                         onSaveComparison();
                     }
                 });
    Actions();
}

ResultCompareView* MeasurementCompareView::Comparison() const
{
    return m_compare;
}

Json MeasurementCompareView::RecordRef() const
{
    const int selected = m_record->GetSelection();
    return selected >= 0 && static_cast<std::size_t>(selected) < m_records.size()
               ? m_records.at(static_cast<std::size_t>(selected))
               : Json(nullptr);
}

/** @brief 방금 저장한 정확한 원본 참조가 있으면 기존 선택보다 우선한다. */
void MeasurementCompareView::SetRecords(const Json& context, const Json& preferred)
{
    const auto previous = RecordRef();
    int preferredRow = wxNOT_FOUND;
    m_records = context.value("items", Json::array());
    m_record->Clear();
    int selected = wxNOT_FOUND;
    for (std::size_t index = 0; index < m_records.size(); ++index)
    {
        const auto& record = m_records.at(index);
        m_record->Append(Display(record.value("name", std::string("이름 미기록"))));
        if (preferred.is_object() && record.value("record_ref", Json(nullptr)) == preferred)
        {
            preferredRow = static_cast<int>(index);
        }
        if (previous.is_object() &&
            record.value("record_ref", Json(nullptr)) == previous.value("record_ref", Json(nullptr)))
        {
            selected = static_cast<int>(index);
        }
    }
    m_record->SetSelection(preferredRow == wxNOT_FOUND ? selected : preferredRow);
    const int previousHistory = m_history->GetSelection();
    const auto previousRef = previousHistory >= 0 && static_cast<std::size_t>(previousHistory) < m_histories.size()
                                 ? m_histories.at(previousHistory)
                                 : Json(nullptr);
    m_histories = Json::array();
    m_history->Clear();
    for (const auto* collection : {"alignments", "comparisons"})
    {
        for (auto item : context.value(collection, Json::array()))
        {
            item["collection"] = collection;
            const int index =
                m_history->Append(Display((std::string(collection) == "alignments" ? "정렬 / " : "비교 / ") +
                                          item.value("name", std::string("이름 미기록"))));
            m_histories.push_back(item);
            if (item == previousRef)
            {
                m_history->SetSelection(index);
            }
        }
    }
    if (preferredRow != wxNOT_FOUND)
    {
        SetStatus("방금 저장한 시료 / 교정 기록이 선택되었습니다. 비교에 추가하거나 기록을 확인하세요.");
    }
    else if (m_records.empty())
    {
        SetStatus("측정 기록이 없습니다. 비교할 자료가 있을 때 가져오거나 원본에 기록을 추가하세요.");
    }
    else if (selected == wxNOT_FOUND)
    {
        SetStatus("시료 / 교정 기록을 선택한 뒤 비교에 추가하세요.");
    }
    else
    {
        SetStatus("선택한 시료 / 교정 기록의 당시 출처가 유지됩니다.");
    }
    Actions();
}

void MeasurementCompareView::SetAvailable(bool available)
{
    m_available = available;
    m_compare->SetAvailable(available);
    Actions();
}

void MeasurementCompareView::SetSelectionAvailable(bool selected)
{
    m_selectedSource = selected;
    Actions();
}

void MeasurementCompareView::SetStatus(const std::string& message)
{
    m_status->SetLabel(Display(message));
    m_status->Wrap(std::max(FromDIP(240), GetClientSize().x - FromDIP(24)));
    Layout();
}

void MeasurementCompareView::Clear()
{
    m_records = Json::array();
    m_histories = Json::array();
    m_history->Clear();
    m_record->Clear();
    m_selectedSource = false;
    m_compare->Clear();
    SetStatus("측정 파일 비교는 선택 기능입니다. 현재 프로젝트의 기록을 조회할 수 있습니다.");
    Actions();
}

void MeasurementCompareView::Actions()
{
    m_record->Enable(m_available);
    m_history->Enable(m_available);
    m_readHistory->Enable(m_available && m_history->GetSelection() >= 0);
    m_recover->Enable(m_available);
    m_refresh->Enable(m_available);
    m_import->Enable(m_available);
    m_new->Enable(m_available && m_selectedSource);
    m_add->Enable(m_available && RecordRef().is_object());
    m_edit->Enable(m_available && RecordRef().is_object());
    m_align->Enable(m_available && RecordRef().is_object());
    const int selected = m_compare->Selected();
    m_save->Enable(m_available && selected > 0 &&
                   static_cast<std::size_t>(selected) < m_compare->Descriptions().size() &&
                   m_compare->PortOrder(static_cast<std::size_t>(selected)).is_array());
}
