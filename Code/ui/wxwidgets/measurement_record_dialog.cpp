/** @file @brief 시료/교정 입력, 실제 곡선 검토와 보존 원문을 분리한다. */
#include "measurement_record_dialog.h"
#include "measurement_record_form.h"
#include "measurement_attachment_dialog.h"
#include "measurement_model.h"
#include "network_chart.h"
#include "frequency_display.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/listctrl.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <wx/weakref.h>
#include <wx/wrapsizer.h>

MeasurementRecordDialog::MeasurementRecordDialog(wxWindow* parent, const Json& context, const Json& selection,
                                                 DialogGateway gateway, std::shared_ptr<MeasurementRecovery> recovery)
    : ProjectSetupDialog(parent, "시료와 교정 기록", context, gateway), m_context(context), m_selection(selection),
      m_gateway(gateway), m_recovery(std::move(recovery))
{
    SetName("measurement.record.dialog");
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* heading = new wxStaticText(this, wxID_ANY, Display("시료와 교정 / 원문 자료를 바꾸지 않는 새 기록"));
    StudioTheme::Title(*heading);
    layout->Add(heading, 0, wxALL, FromDIP(12));
    m_tabs = new StudioNotebook(this);
    m_form = new MeasurementRecordForm(m_tabs, gateway);
    m_form->SetRecovery(m_recovery);
    auto formContext = context;
    if (selection.is_object() && selection.contains("descriptor"))
    {
        formContext["descriptor"] = selection.at("descriptor");
    }
    const auto form = context.value("form", Json::object());
    m_draftTime = form.value("draft_time_utc", std::string());
    m_form->SetRecord(selection.is_object() && selection.value("record", Json(nullptr)).is_object()
                          ? selection.at("record")
                          : form.value("record_template", Json::object()),
                      formContext);
    m_tabs->AddPage(m_form, Display("시료와 교정"));
    auto* review =
        new wxScrolledWindow(m_tabs, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL);
    review->SetScrollRate(0, FromDIP(16));
    auto* reviewLayout = new wxBoxSizer(wxVERTICAL);
    m_summary = new wxTextCtrl(review, wxID_ANY, Display("입력을 검토하면 변경 항목과 미정 조건을 표시합니다."),
                               wxDefaultPosition, FromDIP(wxSize(-1, 130)), wxTE_MULTILINE | wxTE_READONLY);
    reviewLayout->Add(m_summary, 0, wxEXPAND | wxALL, FromDIP(8));
    m_chart = new NetworkChart(review);
    m_chart->SetMinSize(FromDIP(wxSize(340, 220)));
    reviewLayout->Add(m_chart, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    m_changes =
        new wxListCtrl(review, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 140)), wxLC_REPORT | wxLC_SINGLE_SEL);
    m_changes->SetMinSize(FromDIP(wxSize(-1, 140)));
    for (const auto& column :
         std::vector<std::pair<std::string, int>>{{"항목", 220}, {"원래 값", 240}, {"후보 값", 240}, {"상태", 170}})
    {
        m_changes->AppendColumn(Display(column.first), wxLIST_FORMAT_LEFT, FromDIP(column.second));
    }
    StudioTheme::Table(*m_changes);
    reviewLayout->Add(m_changes, 0, wxEXPAND | wxALL, FromDIP(8));
    review->SetSizer(reviewLayout);
    review->Bind(wxEVT_SIZE,
                 [review](wxSizeEvent& event)
                 {
                     review->Layout();
                     review->FitInside();
                     event.Skip();
                 });
    m_tabs->AddPage(review, Display("변경 검토"));
    auto* source = new wxScrolledWindow(m_tabs, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL);
    source->SetScrollRate(0, FromDIP(16));
    auto* sourceLayout = new wxBoxSizer(wxVERTICAL);
    auto* note = new wxStaticText(source, wxID_ANY,
                                  Display("원래 복소 자료와 과거 시료 기록은 보존합니다. 새 기록을 저장해도 불확도 "
                                          "전파, 교정 재현 또는 실측 일치 판정을 자동 수행하지 않습니다."));
    note->Wrap(FromDIP(800));
    sourceLayout->Add(note, 0, wxEXPAND | wxALL, FromDIP(12));
    m_advanced = new wxCollapsiblePane(source, wxID_ANY, Display("고급 / 고정 원문과 출처"), wxDefaultPosition,
                                       wxDefaultSize, wxCP_DEFAULT_STYLE | wxCP_NO_TLW_RESIZE);
    m_advanced->GetPane()->SetSizer(new wxBoxSizer(wxVERTICAL));
    m_source = new wxTextCtrl(m_advanced->GetPane(), wxID_ANY, Display(selection.dump(2)), wxDefaultPosition,
                              FromDIP(wxSize(-1, 320)), wxTE_MULTILINE | wxTE_READONLY | wxHSCROLL);
    m_advanced->GetPane()->GetSizer()->Add(m_source, 1, wxEXPAND | wxALL, FromDIP(8));
    m_advanced->Collapse();
    sourceLayout->Add(m_advanced, 0, wxEXPAND | wxALL, FromDIP(12));
    source->SetSizer(sourceLayout);
    m_advanced->Bind(wxEVT_COLLAPSIBLEPANE_CHANGED,
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
    m_preview = new wxButton(this, wxID_ANY, Display("기록 후보 검토"));
    m_apply = new wxButton(this, wxID_APPLY, Display("새 기록 저장"));
    m_recover = new wxButton(this, wxID_ANY, Display("이전 적용 결과 확인"));
    for (auto* button : {m_preview, m_apply, m_recover, new wxButton(this, wxID_CANCEL, Display("닫기"))})
    {
        StudioTheme::Button(*button, button == m_apply);
        actions->Add(button, 0, wxALL, FromDIP(4));
    }
    layout->Add(actions, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    SetSizer(layout);
    m_form->onChanged = [this]()
    {
        Changed();
    };
    m_form->onStateChanged = [this]()
    {
        UpdateActions();
    };
    m_form->onStatus = [this](const std::string& message)
    {
        SetStatus(message);
    };
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
    if (selection.is_object() && selection.value("page", Json(nullptr)).is_object())
    {
        m_chart->SetFrequencyUnit(StudioFrequency::ForDescriptor(selection.at("descriptor")).unit);
        m_chart->SetPage(selection.at("page"), Display("원래 자료"));
    }
    SetStatus(m_recovery->pending.is_object() ? "이전 변경의 결과를 먼저 확인하세요. 새 요청을 보내지 않습니다."
                                              : "미정은 빈칸으로 유지하고 변경한 필드만 새 기록에 반영합니다.");
    UpdateActions();
}

bool MeasurementRecordDialog::HasDraft() const
{
    return m_form->Dirty();
}

void MeasurementRecordDialog::UpdateActions()
{
    if (!m_preview)
    {
        return;
    }
    const bool ready =
        Editable() && !m_pending && !m_form->Pending() && !m_recovering && !m_recovery->pending.is_object();
    m_form->Enable(ready);
    m_preview->Enable(ready);
    m_apply->Enable(ready && m_review.is_object() && m_review.value("can_apply", false));
    m_recover->Show(m_recovery->pending.is_object());
    m_recover->Enable(m_recovery->pending.is_object() && !m_recovering && !m_mutating && !m_pending);
}

void MeasurementRecordDialog::Changed()
{
    if (m_mutating || m_recovering || m_recovery->pending.is_object())
    {
        return;
    }
    InvalidateRead();
    m_review = nullptr;
    m_reviewInput = nullptr;
    m_changes->DeleteAllItems();
    SetStatus("입력이 바뀌었습니다. 같은 원문의 새 기록 후보를 다시 검토하세요.");
    UpdateActions();
}

Json MeasurementRecordDialog::Input() const
{
    if (!m_selection.is_object() || !m_selection.value("source", Json(nullptr)).is_object() ||
        !m_selection.value("pin", Json(nullptr)).is_object())
    {
        throw std::runtime_error("기록을 연결할 보존 원본을 먼저 선택하세요.");
    }
    return {{"expected_revision", m_revision},
            {"draft_time_utc", m_draftTime},
            {"operation", "record"},
            {"parameters",
             {{"source", m_selection.at("source")},
              {"pin", m_selection.at("pin")},
              {"previous_record", m_selection.value("record_ref", Json(nullptr))},
              {"name", m_form->Name()},
              {"changes", m_form->Changes()},
              {"reason", m_form->Reason()}}}};
}

void MeasurementRecordDialog::Preview()
{
    if (!Editable() || m_pending || m_form->Pending() || m_recovery->pending.is_object())
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
                        response.value("revision_id", "") != m_revision || response.value("operation", "") != "record")
                    {
                        throw std::runtime_error("측정 기록 검토의 프로젝트 또는 개정이 다릅니다.");
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

void MeasurementRecordDialog::Render(const Json& response)
{
    m_changes->DeleteAllItems();
    for (const auto& change : response.value("changes", Json::array()))
    {
        const long row = m_changes->InsertItem(
            m_changes->GetItemCount(), Display(change.value("label", change.value("path", std::string("기록 항목")))));
        m_changes->SetItem(
            row, 1,
            Display(MeasurementUi::Text(change.value("before_display", change.value("before", Json(nullptr))))));
        m_changes->SetItem(
            row, 2, Display(MeasurementUi::Text(change.value("after_display", change.value("after", Json(nullptr))))));
        m_changes->SetItem(row, 3, Display(change.value("unit", std::string("원문 보존"))));
    }
    m_summary->ChangeValue(
        Display(MeasurementUi::Summary(response.value("record", Json(nullptr))) + MeasurementUi::Issues(response)));
    m_source->ChangeValue(Display(response.dump(2)));
    if (response.value("page", Json(nullptr)).is_object())
    {
        m_chart->SetFrequencyUnit(StudioFrequency::ForDescriptor(response.at("descriptor")).unit);
        m_chart->SetPage(response.at("page"), Display("보존 원문 자료"));
    }
    SetStatus(response.value("can_apply", false)
                  ? "원본 데이터는 유지됩니다. 검토한 새 시료 / 교정 기록만 저장할 수 있습니다."
                  : "입력 조건을 확인하세요. 원문과 미적용 초안은 유지됩니다.");
}

void MeasurementRecordDialog::Apply()
{
    if (!Editable() || m_pending || m_form->Pending() || m_recovery->pending.is_object() || !m_review.is_object() ||
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
        input["command_id"] = Uuid();
        input["review_hash"] = m_review.at("review_hash");
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

void MeasurementRecordDialog::Accept(const Json& response)
{
    AcceptMutation(response);
    if (m_recovery->resolved)
    {
        m_recovery->resolved();
    }
    m_recovery->pending = nullptr;
    m_disconnected = false;
    CloseDialog(true);
}

void MeasurementRecordDialog::Recover()
{
    if (m_closed || m_mutating || m_recovering || !m_recovery->pending.is_object())
    {
        return;
    }
    if (m_recovery->pending.value("method", "") == "measurement.attachment.add")
    {
        MeasurementAttachmentDialog dialog(this, m_context, m_gateway, m_recovery);
        dialog.ShowModal();
        m_form->AddAttachment(dialog.Attachment());
        UpdateActions();
        return;
    }
    m_recovering = true;
    const auto pending = m_recovery->pending;
    wxWeakRef<MeasurementRecordDialog> weak(this);
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
                SetStatus("이전 요청의 결과를 확정할 수 없습니다. 같은 키 조회를 유지하며 새 적용을 보내지 않습니다.");
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

void MeasurementRecordDialog::ShowRequestFailure(const Json& error)
{
    m_review = nullptr;
    m_reviewInput = nullptr;
    ProjectSetupDialog::ShowRequestFailure(error);
}
