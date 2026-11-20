/** @file @brief 일반 가져오기와 선택한 측정 기록의 원자 가져오기를 구분한다. */
#include "network_import_dialog.h"
#include "measurement_record_form.h"
#include "measurement_attachment_dialog.h"
#include "studio_support.h"
#include <wx/button.h>
#include <wx/checkbox.h>
#include <wx/sizer.h>
#include <wx/weakref.h>

void NetworkImportDialog::BuildMeasurementPage(wxWindow* page, DialogGateway gateway)
{
    auto* layout = new wxBoxSizer(wxVERTICAL);
    m_measurementEnabled =
        new wxCheckBox(page, wxID_ANY, Display("시료 / 교정 기록을 원문 자료와 함께 한 명령으로 보존"));
    m_measurementEnabled->SetName("network.import.measurement");
    m_measurementEnabled->SetValue(false);
    layout->Add(m_measurementEnabled, 0, wxALL, FromDIP(12));
    m_measurementForm = new MeasurementRecordForm(page, std::move(gateway));
    m_measurementForm->SetRecovery(m_recovery);
    const auto context = m_context.value("measurement", Json::object());
    const auto form = context.value("form", Json::object());
    m_draftTime = form.value("draft_time_utc", std::string());
    m_measurementForm->SetRecord(form.value("record_template", Json::object()), context);
    layout->Add(m_measurementForm, 1, wxEXPAND);
    page->SetSizer(layout);
    m_measurementForm->onChanged = [this]()
    {
        if (MeasurementSelected())
        {
            ChangeInputs();
        }
    };
    m_measurementForm->onStatus = [this](const std::string& message)
    {
        SetStatus(message);
    };
    m_measurementForm->onStateChanged = [this]()
    {
        UpdateActions();
    };
    m_measurementEnabled->Bind(wxEVT_CHECKBOX,
                               [this](wxCommandEvent&)
                               {
                                   ChangeInputs();
                               });
}

bool NetworkImportDialog::MeasurementSelected() const
{
    return m_measurementEnabled && m_measurementEnabled->GetValue();
}

bool NetworkImportDialog::MeasurementUncertain() const
{
    return m_recovery && m_recovery->pending.is_object();
}

void NetworkImportDialog::AcceptImport(const Json& result)
{
    AcceptMutation(result);
    if (MeasurementUncertain())
    {
        if (m_recovery->resolved)
        {
            m_recovery->resolved();
        }
        m_recovery->pending = nullptr;
    }
    m_dirty = false;
    m_disconnected = false;
    CloseDialog(true);
}

void NetworkImportDialog::RecoverMeasurement()
{
    if (!MeasurementUncertain() || m_recovering || m_mutating || m_closed)
    {
        return;
    }
    if (m_recovery->pending.value("method", "") == "measurement.attachment.add")
    {
        MeasurementAttachmentDialog dialog(this, m_context, m_gateway, m_recovery);
        dialog.ShowModal();
        m_measurementForm->AddAttachment(dialog.Attachment());
        UpdateActions();
        return;
    }
    m_recovering = true;
    const auto pending = m_recovery->pending;
    wxWeakRef<NetworkImportDialog> weak(this);
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
                AcceptImport(response.at("response"));
            }
            else
            {
                SetStatus("원래 요청의 적용 결과가 아직 확정되지 않았습니다. 새 키로 다시 가져오지 않습니다.");
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
