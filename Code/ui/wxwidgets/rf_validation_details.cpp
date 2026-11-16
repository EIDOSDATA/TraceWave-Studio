/** @file @brief 판정 표와 출처를 표시하며 미정값과 불변 보고서 식별자를 유지한다. */
#include "rf_validation_view.h"
#include "rf_validation_model.h"
#include "result_presentation.h"
#include "studio_support.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/listctrl.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <algorithm>

void RfValidationView::SetCatalog(const Json& result, const std::string& selected)
{
    m_rebuilding = true;
    m_catalog = result;
    m_records->DeleteAllItems();
    for (const auto& item : result.at("items"))
    {
        const auto row = m_records->InsertItem(m_records->GetItemCount(), Display(ResultUi::Text(item.at("name"))));
        m_records->SetItem(row, 1, Display(RfValidationUi::State(item.value("state", Json(nullptr)))));
        if (item.at("validation_id") == selected)
        {
            m_records->SetItemState(row, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED,
                                    wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
        }
    }
    const int count = static_cast<int>(result.at("items").size()), offset = result.at("offset").get<int>();
    m_catalogRange->SetLabel(Display("기록 " + std::to_string(offset + (count ? 1 : 0)) + "~" +
                                     std::to_string(offset + count) + " / " +
                                     std::to_string(result.at("total").get<int>())));
    m_rebuilding = false;
    if (result.at("total") == 0)
    {
        ClearRecord("보존한 독립 RF 검증 기록이 없습니다. 새 참조 계산이나 실측 판정을 만들어 표시하지 않습니다.");
    }
    UpdateActions();
}

void RfValidationView::SetReports(const Json& result, const Json& selectedReport)
{
    m_rebuilding = true;
    m_reports = result;
    m_reportChoice->Clear();
    m_reportIds = {Json(nullptr)};
    m_reportChoice->Append(Display("계획 / 현재 작업 상태 (판정 아님)"));
    int selected = selectedReport.is_null() ? 0 : -1;
    int ordinal = result.at("total").get<int>() - result.at("offset").get<int>();
    for (const auto& item : result.at("items"))
    {
        m_reportIds.push_back(item.at("report_id"));
        m_reportChoice->Append(Display("판정 " + std::to_string(ordinal--) + " / " +
                                       RfValidationUi::Time(item.value("created_at", Json(nullptr))) + " / " +
                                       RfValidationUi::State(item.value("status", Json(nullptr)))));
        if (item.at("report_id") == selectedReport)
        {
            selected = static_cast<int>(m_reportIds.size()) - 1;
        }
    }
    if (selected < 0)
    {
        m_reportIds.push_back(selectedReport);
        selected = static_cast<int>(m_reportIds.size()) - 1;
        m_reportChoice->Append(Display("현재 선택 판정 / 다른 목록 페이지"));
    }
    m_reportChoice->SetSelection(selected);
    const int count = static_cast<int>(result.at("items").size()), offset = result.at("offset").get<int>();
    m_reportRange->SetLabel(Display(
        "보존 판정 " + std::to_string(offset + (count ? 1 : 0)) + "~" + std::to_string(offset + count) + " / " +
        std::to_string(result.at("total").get<int>()) + " / 계획 조회는 최신 판정으로 자동 대체되지 않습니다."));
    m_rebuilding = false;
    UpdateActions();
    Relayout();
}

void RfValidationView::SetRecord(const Json& result)
{
    m_record = result;
    const bool assessed = result.value("report_id", Json(nullptr)).is_string();
    m_identity->SetLabel(Display(ResultUi::Text(result.at("name")) + "\n" +
                                 (assessed ? "선택한 불변 판정 / " : "계획과 현재 작업 / ") +
                                 RfValidationUi::State(result.value("status", Json(nullptr)))));
    Populate(m_cases, RfValidationUi::Cases(result));
    Populate(m_states, RfValidationUi::States(result));
    Populate(m_metrics, RfValidationUi::Metrics(result));
    m_original->ChangeValue(
        Display("검증 묶음\n" + ResultUi::Text(result.at("name")) + "\n\n" +
                (assessed ? "보존 판정 조회 / 재평가하지 않음" : "판정 미선택 / 계획과 실제 작업 상태만 조회") +
                "\n프로젝트 설계와 별도 합성 검증 사례\n\n예약 예산\n" +
                RfValidationUi::Resources(result.value("budget", Json(nullptr))) + "\n누적 예약과 실행 기록\n" +
                RfValidationUi::Resources(result.value("usage", Json(nullptr)))));
    m_basis->ChangeValue(
        Display("출처\n" + RfValidationUi::Notes(result.value("source_refs", Json(nullptr))) +
                "\n\n가정 / 적용 범위\n" + RfValidationUi::Notes(result.value("assumptions", Json(nullptr))) +
                "\n\n사전 고정한 기준\n" + RfValidationUi::Criteria(result.value("criteria", Json(nullptr)))));
    m_limits->ChangeValue(Display(
        "제작 조건: " +
        (result.value("manufacturing", Json(nullptr)).is_null()
             ? std::string("미정")
             : std::string("원문 기록 있음 / 확정 여부는 출처 확인")) +
        "\n측정 조건: " +
        (result.value("measurement", Json(nullptr)).is_null() ? std::string("미정")
                                                              : std::string("원문 기록 있음 / 실측 검증과 별도")) +
        "\n\n남은 한계\n" + RfValidationUi::Notes(result.value("limitations", Json(nullptr)))));
    m_metricDetail->ChangeValue(Display("지표를 선택하면 오차 정의, 고정 한계와 출처를 확인할 수 있습니다."));
    m_raw->ChangeValue(Display(result.dump(2, ' ', false, Json::error_handler_t::replace)));
    for (auto* text : {m_original, m_basis, m_limits, m_metricDetail, m_raw})
    {
        text->ShowPosition(0);
    }
    SetPending(false, assessed
                          ? "당시 고정한 기준의 판정입니다. 다른 모델이나 실제 납품/측정 정확도로 확대하지 않습니다."
                          : "현재 작업의 완료는 독립 참조 또는 실측 합격이 아닙니다. 보존 판정을 명시 선택하세요.");
    Relayout();
}

void RfValidationView::ShowCase()
{
    UpdateActions();
    const long selected = m_cases->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
    if (selected < 0 || !m_record.is_object())
    {
        return;
    }
    const auto& item = m_record.at("cases").at(static_cast<std::size_t>(selected));
    m_metricDetail->ChangeValue(Display(
        "사례: " + ResultUi::Text(item.value("name", Json(nullptr))) +
        "\n실행: " + RfValidationUi::State(item.value("execution_state", Json(nullptr))) + "\n차단 사유: " +
        (item.value("blocked_reason", Json(nullptr)).is_null() ? "차단 없음"
                                                               : RfValidationUi::Reason(item.at("blocked_reason"))) +
        "\n\n" +
        (RfValidationUi::HasSource(item) ? "원본 고정 해시를 확인한 뒤 기존 결과 화면으로 엽니다."
         : m_record.value("report_id", Json(nullptr)).is_null() && item.value("blocked_reason", Json(nullptr)).is_null()
             ? "계획 조회는 관련 결과 참조를 제공하지 않습니다. 보존 판정을 선택해 확인하세요."
             : "보존된 결과 원본이 없어 결과 열기를 사용할 수 없습니다.")));
}

void RfValidationView::ShowMetric()
{
    const long selected = m_metrics->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
    if (selected < 0 || !m_record.is_object())
    {
        return;
    }
    const auto& item = m_record.at("rows").at(static_cast<std::size_t>(selected));
    m_metricDetail->ChangeValue(Display(ResultUi::Text(item.value("label", Json(nullptr))) + "\n" +
                                        RfValidationUi::State(item.value("state", Json(nullptr))) + "\n\n판정 사유\n" +
                                        RfValidationUi::Reason(item.value("reason", Json(nullptr))) +
                                        "\n\n기준의 출처\n" +
                                        RfValidationUi::Notes(item.value("criterion_source_refs", Json(nullptr)))));
    m_metricDetail->ShowPosition(0);
}

void RfValidationView::ClearRecord(const std::string& message)
{
    m_record = nullptr;
    m_identity->SetLabel(wxEmptyString);
    m_cases->DeleteAllItems();
    m_states->DeleteAllItems();
    m_metrics->DeleteAllItems();
    m_original->ChangeValue(Display(message));
    m_basis->ChangeValue(Display("실제 출처와 가정은 기록 선택 후 표시합니다."));
    m_limits->ChangeValue(Display("제작 / 측정 조건 미정\n독립 참조 / 실측 검증 미확립"));
    m_metricDetail->ChangeValue(wxEmptyString);
    m_raw->ChangeValue(wxEmptyString);
    SetPending(false, message);
    Relayout();
}

void RfValidationView::Clear(const std::string& message)
{
    m_catalog = nullptr;
    m_reports = nullptr;
    m_records->DeleteAllItems();
    m_reportChoice->Clear();
    m_reportIds.clear();
    m_reportRange->SetLabel(wxEmptyString);
    m_catalogRange->SetLabel(Display("기록 미조회"));
    ClearRecord(message);
}

void RfValidationView::SetAvailable(bool available)
{
    m_available = available;
    UpdateActions();
}
void RfValidationView::SetStatus(const std::string& message)
{
    m_status->SetLabel(Display(message));
    Relayout();
}
void RfValidationView::SetPending(bool pending, const std::string& message)
{
    m_pending = pending;
    if (!message.empty())
    {
        m_status->SetLabel(Display(message));
    }
    UpdateActions();
    Relayout();
}

void RfValidationView::UpdateActions()
{
    m_refresh->Enable(m_available);
    m_records->Enable(m_available);
    m_reportChoice->Enable(m_available && !m_reportIds.empty());
    m_previous->Enable(m_available && m_catalog.is_object() && m_catalog.value("offset", 0) > 0);
    m_next->Enable(m_available && m_catalog.is_object() && !m_catalog.value("next_offset", Json(nullptr)).is_null());
    m_reportsPrevious->Enable(m_available && m_reports.is_object() && m_reports.value("offset", 0) > 0);
    m_reportsNext->Enable(m_available && m_reports.is_object() &&
                          !m_reports.value("next_offset", Json(nullptr)).is_null());
    const long selected = m_cases->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
    m_openResult->Enable(m_available && !m_pending && selected >= 0 && m_record.is_object() &&
                         RfValidationUi::HasSource(m_record.at("cases").at(static_cast<std::size_t>(selected))));
}
