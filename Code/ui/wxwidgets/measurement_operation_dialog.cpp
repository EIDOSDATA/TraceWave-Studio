/** @file @brief 실제 정렬 후보와 비교 보고서를 봉인 원본과 구분하여 검토한다. */
#include "measurement_operation_dialog.h"
#include "measurement_model.h"
#include "measurement_quantity_group.h"
#include "network_chart.h"
#include "frequency_display.h"
#include "result_presentation.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/collpane.h>
#include <wx/listctrl.h>
#include <wx/scrolwin.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <wx/weakref.h>
#include <wx/wrapsizer.h>

MeasurementOperationDialog::MeasurementOperationDialog(wxWindow* parent, const Json& context, const Json& selection,
                                                       const std::string& operation, DialogGateway gateway,
                                                       std::shared_ptr<MeasurementRecovery> recovery)
    : ProjectSetupDialog(parent, operation == "align" ? "명시 정렬 검토" : "측정 비교 보고서", context, gateway),
      m_context(context), m_selection(selection), m_operation(operation),
      m_draftTime(context.value("form", Json::object()).value("draft_time_utc", std::string())), m_gateway(gateway),
      m_recovery(std::move(recovery))
{
    SetName("measurement.operation.dialog");
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* heading = new wxStaticText(this, wxID_ANY,
                                     Display(operation == "align" ? "명시 정렬 / 원문과 별도 파생 자료"
                                                                  : "측정 비교 / 당시 원본과 조건을 고정한 보고서"));
    StudioTheme::Title(*heading);
    layout->Add(heading, 0, wxALL, FromDIP(12));
    m_tabs = new StudioNotebook(this);
    auto* input = new wxScrolledWindow(m_tabs, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL);
    input->SetScrollRate(0, FromDIP(16));
    auto* inputLayout = new wxBoxSizer(wxVERTICAL);
    auto* fields = new wxFlexGridSizer(2, FromDIP(8), FromDIP(12));
    fields->AddGrowableCol(1, 1);
    m_name = new wxTextCtrl(input, wxID_ANY);
    m_reason = new wxTextCtrl(input, wxID_ANY);
    for (const auto& item :
         std::vector<std::pair<std::string, wxWindow*>>{{"새 이름", m_name}, {"명시 사유", m_reason}})
    {
        fields->Add(new wxStaticText(input, wxID_ANY, Display(item.first)), 0, wxALIGN_CENTER_VERTICAL);
        fields->Add(item.second, 1, wxEXPAND);
    }
    inputLayout->Add(fields, 0, wxEXPAND | wxALL, FromDIP(12));
    if (operation == "align")
    {
        BuildAlignment(input, inputLayout);
    }
    else
    {
        auto* notice =
            new wxStaticText(input, wxID_ANY,
                             Display("선택한 계산·측정 원본, 시료 기록의 고정 개정과 명시 포트 대응을 저장합니다. 비교 "
                                     "보고서는 차이의 기록이며 실측 일치 합격 판정이 아닙니다."));
        notice->Wrap(FromDIP(800));
        inputLayout->Add(notice, 0, wxEXPAND | wxALL, FromDIP(12));
    }
    input->SetSizer(inputLayout);
    m_tabs->AddPage(input, Display("명시 조건"));
    auto* review =
        new wxScrolledWindow(m_tabs, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL);
    review->SetScrollRate(0, FromDIP(16));
    auto* reviewLayout = new wxBoxSizer(wxVERTICAL);
    m_summary = new wxTextCtrl(review, wxID_ANY, Display("후보 검토 전입니다."), wxDefaultPosition,
                               FromDIP(wxSize(-1, 130)), wxTE_MULTILINE | wxTE_READONLY);
    reviewLayout->Add(m_summary, 0, wxEXPAND | wxALL, FromDIP(8));
    m_chart = new NetworkChart(review);
    m_chart->SetMinSize(FromDIP(wxSize(360, 230)));
    reviewLayout->Add(m_chart, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    m_points =
        new wxListCtrl(review, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 150)), wxLC_REPORT | wxLC_SINGLE_SEL);
    m_points->SetMinSize(FromDIP(wxSize(-1, 150)));
    for (const auto& column :
         std::vector<std::pair<std::string, int>>{{"주파수", 170}, {"실제 / 파생 복소값", 260}, {"상태 / 출처", 300}})
    {
        m_points->AppendColumn(Display(column.first), wxLIST_FORMAT_LEFT, FromDIP(column.second));
    }
    StudioTheme::Table(*m_points);
    reviewLayout->Add(m_points, 0, wxEXPAND | wxALL, FromDIP(8));
    review->SetSizer(reviewLayout);
    review->Bind(wxEVT_SIZE,
                 [review](wxSizeEvent& event)
                 {
                     review->Layout();
                     review->FitInside();
                     event.Skip();
                 });
    m_tabs->AddPage(review, Display("실제 후보 / 판정"));
    auto* source = new wxScrolledWindow(m_tabs, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL);
    source->SetScrollRate(0, FromDIP(16));
    auto* sourceLayout = new wxBoxSizer(wxVERTICAL);
    auto* note = new wxStaticText(source, wxID_ANY,
                                  Display("원문은 유지합니다. 보간 표본을 실측으로 바꾸지 않으며 불확도 전파·교정 "
                                          "재현·공진 이동 맞춤은 수행하지 않습니다."));
    note->Wrap(FromDIP(800));
    sourceLayout->Add(note, 0, wxEXPAND | wxALL, FromDIP(12));
    auto* advanced = new wxCollapsiblePane(source, wxID_ANY, Display("고급 / 원문과 연산 근거"), wxDefaultPosition,
                                           wxDefaultSize, wxCP_DEFAULT_STYLE | wxCP_NO_TLW_RESIZE);
    advanced->GetPane()->SetSizer(new wxBoxSizer(wxVERTICAL));
    m_source = new wxTextCtrl(advanced->GetPane(), wxID_ANY, Display(selection.dump(2)), wxDefaultPosition,
                              FromDIP(wxSize(-1, 320)), wxTE_MULTILINE | wxTE_READONLY | wxHSCROLL);
    advanced->GetPane()->GetSizer()->Add(m_source, 1, wxEXPAND | wxALL, FromDIP(8));
    advanced->Collapse();
    sourceLayout->Add(advanced, 0, wxEXPAND | wxALL, FromDIP(12));
    source->SetSizer(sourceLayout);
    advanced->Bind(wxEVT_COLLAPSIBLEPANE_CHANGED,
                   [source](wxCollapsiblePaneEvent&)
                   {
                       source->Layout();
                       source->FitInside();
                   });
    m_tabs->AddPage(source, Display("원문과 적용 범위"));
    layout->Add(m_tabs, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    m_status = new wxStaticText(this, wxID_ANY, wxEmptyString);
    layout->Add(m_status, 0, wxEXPAND | wxALL, FromDIP(12));
    auto* actions = new wxWrapSizer(wxHORIZONTAL);
    m_preview = new wxButton(this, wxID_ANY, Display("후보 검토"));
    m_apply = new wxButton(this, wxID_APPLY, Display(operation == "align" ? "파생 자료 저장" : "비교 보고서 저장"));
    m_recover = new wxButton(this, wxID_ANY, Display("이전 저장 결과 확인"));
    for (auto* button : {m_preview, m_apply, m_recover, new wxButton(this, wxID_CANCEL, Display("닫기"))})
    {
        StudioTheme::Button(*button, button == m_apply);
        actions->Add(button, 0, wxALL, FromDIP(4));
    }
    layout->Add(actions, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    SetSizer(layout);
    m_name->Bind(wxEVT_TEXT,
                 [this](wxCommandEvent&)
                 {
                     Changed();
                 });
    m_reason->Bind(wxEVT_TEXT,
                   [this](wxCommandEvent&)
                   {
                       Changed();
                   });
    m_preview->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        Preview();
                    });
    m_apply->Bind(wxEVT_BUTTON,
                  [this](wxCommandEvent&)
                  {
                      Apply();
                  });
    m_recover->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        Recover();
                    });
    SetStatus("원문과 시료 기록의 고정 참조를 확인하고 명시 후보를 검토하세요.");
    UpdateActions();
}

bool MeasurementOperationDialog::HasDraft() const
{
    return m_dirty;
}
void MeasurementOperationDialog::Changed()
{
    if (m_mutating || m_recovering || m_recovery->pending.is_object())
    {
        return;
    }
    InvalidateRead();
    m_dirty = true;
    m_review = nullptr;
    m_reviewInput = nullptr;
    if (m_chart)
    {
        m_chart->Clear();
        m_points->DeleteAllItems();
        SetStatus("입력이 바뀌었습니다. 이전 후보는 적용할 수 없습니다.");
        UpdateActions();
    }
}
void MeasurementOperationDialog::UpdateActions()
{
    if (!m_preview)
    {
        return;
    }
    const bool ready = Editable() && !m_pending && !(m_frequencyInputs && m_frequencyInputs->Pending()) &&
                       !(m_gapInputs && m_gapInputs->Pending()) && !m_recovering && !m_recovery->pending.is_object();
    m_tabs->GetPage(0)->Enable(ready);
    m_preview->Enable(ready);
    m_apply->Enable(ready && m_review.is_object() && m_review.value("can_apply", false));
    m_recover->Show(m_recovery->pending.is_object());
    m_recover->Enable(m_recovery->pending.is_object() && !m_pending && !m_mutating && !m_recovering);
}
void MeasurementOperationDialog::Preview()
{
    if (!Editable() || m_pending || m_recovery->pending.is_object())
    {
        return;
    }
    try
    {
        const auto input = Input();
        m_review = nullptr;
        m_reviewInput = nullptr;
        Request("measurement.preview", input, false,
                [this, input](const Json& response)
                {
                    if (response.value("project_id", "") != m_projectId ||
                        response.value("revision_id", "") != m_revision ||
                        response.value("operation", "") != m_operation)
                    {
                        throw std::runtime_error("측정 후보의 프로젝트, 개정 또는 동작이 다릅니다.");
                    }
                    m_review = response;
                    m_reviewInput = input;
                    Render(response);
                    m_tabs->SetSelection(1);
                });
    }
    catch (const std::exception& error)
    {
        SetStatus(error.what());
    }
    UpdateActions();
}
void MeasurementOperationDialog::Render(const Json& response)
{
    m_points->DeleteAllItems();
    m_chart->Clear();
    std::string text = response.value("can_apply", false) ? "명시 후보 검토 완료 / 원문 보존\n" : "후보 적용 불가\n";
    text += MeasurementUi::Issues(response);
    text += "실측 일치: 미확립 / 불확도 전파: 수행하지 않음\n";
    const auto comparison = response.value("comparison_preview", Json(nullptr));
    if (comparison.is_object())
    {
        const auto& points = comparison.at("points");
        const auto scale = StudioFrequency::ForSamples(points);
        const int total = comparison.at("total").get<int>();
        const int comparable = comparison.at("comparable_points").get<int>();
        text += "비교 가능 " + std::to_string(comparable) + " / " + std::to_string(total) + " 표본\n";
        text += "검토에는 첫 " + std::to_string(points.size()) +
                "개를 표시합니다. 저장 후 전체 조건과 표본을 조회할 수 있습니다.\n";
        m_points->SetColumnWidth(2, FromDIP(610));
        Json curve = Json::array();
        for (const auto& point : points)
        {
            const auto& frequency = point.at("frequency_hz");
            const auto& difference = point.at("difference_ri");
            const long row = m_points->InsertItem(m_points->GetItemCount(),
                                                  Display(StudioFrequency::Value(frequency, scale) + " " + scale.unit));
            m_points->SetItem(row, 1, Display(ResultUi::Complex(difference)));
            m_points->SetItem(row, 2, Display(point.at("reason").get<std::string>()));
            curve.push_back({{"frequency_hz", frequency},
                             {"real", difference.is_array() ? difference.at(0) : Json(nullptr)},
                             {"status", difference.is_array() ? "valid" : "missing"}});
        }
        m_chart->SetMetric("real", Display("비교 - 기준 / 실수부"));
        m_chart->SetFrequencyUnit(scale.unit);
        m_chart->SetPage({{"samples", curve}}, Display("비교 후보"));
    }
    m_summary->ChangeValue(Display(text));
    m_source->ChangeValue(Display(response.dump(2)));
    const auto page = response.value("page", Json(nullptr));
    if (page.is_object())
    {
        const auto scale = StudioFrequency::ForDescriptor(response.value("descriptor", Json::object()));
        m_chart->SetFrequencyUnit(scale.unit);
        if (m_selection.value("page", Json(nullptr)).is_object())
        {
            m_chart->SetComparison(m_selection.at("page"), page, Display("원문"), Display("정렬 후보"));
        }
        else
        {
            m_chart->SetPage(page, Display("정렬 후보"));
        }
        for (const auto& sample : page.value("samples", Json::array()))
        {
            const long row = m_points->InsertItem(
                m_points->GetItemCount(),
                Display(StudioFrequency::Value(sample.value("frequency_hz", Json(nullptr)), scale) + " " + scale.unit));
            m_points->SetItem(row, 1,
                              Display(ResultUi::Complex(Json::array(
                                  {sample.value("real", Json(nullptr)), sample.value("imag", Json(nullptr))}))));
            m_points->SetItem(row, 2,
                              Display(ResultUi::State(sample.value("status", Json(nullptr))) + " / " +
                                      ResultUi::State(sample.value("origin", Json(nullptr)))));
        }
    }
    SetStatus(response.value("can_apply", false) ? "같은 고정 원본과 검토 해시의 후보만 저장할 수 있습니다."
                                                 : "입력과 적용 범위 안내를 확인하세요.");
}
void MeasurementOperationDialog::Apply()
{
    if (!Editable() || m_pending || m_recovery->pending.is_object() || !m_review.is_object() ||
        !m_review.value("can_apply", false))
    {
        return;
    }
    try
    {
        if (Input() != m_reviewInput)
        {
            Changed();
            return;
        }
        auto input = m_reviewInput;
        input["review_hash"] = m_review.at("review_hash");
        input["command_id"] = Uuid();
        Request("measurement.apply", input, true,
                [this](const Json& response)
                {
                    Accept(response);
                });
    }
    catch (const std::exception& error)
    {
        SetStatus(error.what());
    }
}
void MeasurementOperationDialog::Accept(const Json& response)
{
    AcceptMutation(response);
    if (m_recovery->resolved)
    {
        m_recovery->resolved();
    }
    m_recovery->pending = nullptr;
    m_disconnected = false;
    m_dirty = false;
    CloseDialog(true);
}
void MeasurementOperationDialog::Recover()
{
    if (m_closed || m_mutating || m_recovering || !m_recovery->pending.is_object())
    {
        return;
    }
    m_recovering = true;
    const auto pending = m_recovery->pending;
    wxWeakRef<MeasurementOperationDialog> weak(this);
    UpdateActions();
    m_gateway(
        "measurement.receipt",
        {{"request_key", pending.at("request_key")}, {"request_key_epoch", pending.at("request_key_epoch")}}, false,
        [this, weak, pending](const Json& response)
        {
            if (!weak || m_closed || m_recovery->pending != pending)
            {
                return;
            }
            m_recovering = false;
            if (response.value("authoritative", false) && response.value("status", "") == "found" &&
                response.value("response", Json(nullptr)).is_object())
            {
                Accept(response.at("response"));
            }
            else
            {
                SetStatus("원래 저장 결과가 아직 확정되지 않았습니다. 같은 키 조회만 유지합니다.");
                UpdateActions();
            }
        },
        [this, weak](const Json& error)
        {
            if (!weak || m_closed)
            {
                return;
            }
            m_recovering = false;
            SetStatus(DiagnosticMessage(error));
            UpdateActions();
        });
}
void MeasurementOperationDialog::ShowRequestFailure(const Json& error)
{
    m_review = nullptr;
    m_reviewInput = nullptr;
    ProjectSetupDialog::ShowRequestFailure(error);
}
