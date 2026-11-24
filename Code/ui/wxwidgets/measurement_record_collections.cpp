/** @file @brief 불확도, 교정 포트와 원문 첨부를 별도의 명시 목록으로 편집한다. */
#include "measurement_record_form.h"
#include "measurement_collection_dialog.h"
#include "measurement_attachment_dialog.h"
#include "measurement_model.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/listctrl.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/wrapsizer.h>

namespace
{
const std::vector<std::pair<std::string, std::string>> Collections{
    {"calibration.port_ids", "교정 적용 포트"},
    {"calibration.reference_planes", "포트별 교정 기준면"},
    {"calibration.frequency_range_hz", "교정 주파수 범위"},
    {"uncertainty", "불확도, 범위 및 상관"},
    {"external_processing", "외부 처리 이력"},
    {"attachments", "근거 파일 연결"},
    {"calibration.certificate_refs", "교정 증서 원문"},
    {"acquisition.setting_artifacts", "측정 설정 원문"},
    {"specimen.design_snapshot", "제작 시료의 설계 고정 입력"},
    {"specimen.delivered_materials", "납품 재료 원문"},
    {"environment.physical_setup_snapshot", "실제 설치 환경 원문"}};
}

void MeasurementRecordForm::BuildCollections(wxBoxSizer* layout)
{
    layout->Add(new wxStaticText(this, wxID_ANY, Display("적용 범위, 불확도 및 근거")), 0, wxALL, FromDIP(12));
    m_collectionList =
        new wxListCtrl(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 180)), wxLC_REPORT | wxLC_SINGLE_SEL);
    m_collectionList->SetMinSize(FromDIP(wxSize(-1, 180)));
    m_collectionList->SetName("measurement.collections");
    m_collectionList->AppendColumn(Display("기록 항목"), wxLIST_FORMAT_LEFT, FromDIP(250));
    m_collectionList->AppendColumn(Display("원문과 초안 상태"), wxLIST_FORMAT_LEFT, FromDIP(430));
    StudioTheme::Table(*m_collectionList);
    layout->Add(m_collectionList, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    auto* buttons = new wxWrapSizer(wxHORIZONTAL);
    auto* edit = new wxButton(this, wxID_ANY, Display("선택 항목 편집..."));
    auto* unknown = new wxButton(this, wxID_ANY, Display("선택 항목을 미정으로"));
    auto* upload = new wxButton(this, wxID_ANY, Display("근거 원문 보관..."));
    buttons->Add(edit, 0, wxALL, FromDIP(4));
    buttons->Add(unknown, 0, wxALL, FromDIP(4));
    buttons->Add(upload, 0, wxALL, FromDIP(4));
    upload->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     UploadAttachment();
                 });
    layout->Add(buttons, 0, wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    const auto editSelected = [this]()
    {
        const auto row = m_collectionList->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
        if (row >= 0 && static_cast<std::size_t>(row) < Collections.size())
        {
            EditCollection(Collections.at(static_cast<std::size_t>(row)).first);
        }
    };
    edit->Bind(wxEVT_BUTTON,
               [editSelected](wxCommandEvent&)
               {
                   editSelected();
               });
    m_collectionList->Bind(wxEVT_LIST_ITEM_ACTIVATED,
                           [editSelected](wxListEvent&)
                           {
                               editSelected();
                           });
    unknown->Bind(wxEVT_BUTTON,
                  [this](wxCommandEvent&)
                  {
                      const auto row = m_collectionList->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
                      if (row < 0 || static_cast<std::size_t>(row) >= Collections.size())
                      {
                          return;
                      }
                      const auto key = Collections.at(static_cast<std::size_t>(row)).first;
                      m_collections[key] = key.find('.') == std::string::npos ? Json::array() : Json(nullptr);
                      m_collectionInputs.erase(key);
                      m_collectionChanged[key] = true;
                      RefreshCollections();
                      Changed();
                  });
}

void MeasurementRecordForm::RefreshCollections()
{
    if (!m_collectionList)
    {
        return;
    }
    const long selected = m_collectionList->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
    m_collectionList->DeleteAllItems();
    for (const auto& item : Collections)
    {
        const long row = m_collectionList->InsertItem(m_collectionList->GetItemCount(), Display(item.second));
        auto value = m_collections.value(item.first, Json(nullptr));
        if (value.is_object() && value.contains("value"))
        {
            value = value.at("value");
        }
        const std::string summary = m_collectionInputs.contains(item.first) ? "서비스 검토가 필요한 명시 수량 초안"
                                                                            : MeasurementUi::Text(value);
        m_collectionList->SetItem(
            row, 1, Display(summary + (m_collectionChanged[item.first] ? " (미적용 변경)" : " (원문 보존)")));
    }
    if (selected >= 0 && selected < m_collectionList->GetItemCount())
    {
        m_collectionList->SetItemState(selected, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED,
                                       wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
    }
}

void MeasurementRecordForm::SetRecovery(std::shared_ptr<MeasurementRecovery> recovery)
{
    m_recovery = std::move(recovery);
}

void MeasurementRecordForm::AddAttachment(const Json& attachment)
{
    if (!attachment.is_object())
    {
        return;
    }
    if (!m_context.value("attachments", Json(nullptr)).is_array())
    {
        m_context["attachments"] = Json::array();
    }
    if (!m_collections.value("attachments", Json(nullptr)).is_array())
    {
        m_collections["attachments"] = Json::array();
    }
    const auto append = [&attachment](Json& list)
    {
        if (std::none_of(list.begin(), list.end(),
                         [&attachment](const Json& item)
                         {
                             return item.value("id", Json(nullptr)) == attachment.value("id", Json(nullptr));
                         }))
        {
            list.push_back(attachment);
        }
    };
    append(m_context["attachments"]);
    append(m_collections["attachments"]);
    m_collectionChanged["attachments"] = true;
    RefreshCollections();
    Changed();
    if (onStatus)
    {
        onStatus("원문 파일은 보관되었습니다. 현재 시료 기록에 연결하는 초안을 검토하고 저장하세요.");
    }
}

void MeasurementRecordForm::UploadAttachment()
{
    if (!m_recovery || m_pending != 0 || m_recovery->pending.is_object())
    {
        if (onStatus)
        {
            onStatus("원문 보관 기능에 연결하거나 이전 변경 결과를 먼저 확인하세요.");
        }
        return;
    }
    MeasurementAttachmentDialog dialog(this, m_context, m_gateway, m_recovery);
    dialog.ShowModal();
    AddAttachment(dialog.Attachment());
    if (onStateChanged)
    {
        onStateChanged();
    }
}

void MeasurementRecordForm::EditCollection(const std::string& key)
{
    auto context = m_context;
    context["record"] = m_record;
    const auto current =
        m_collectionInputs.contains(key) ? m_collectionInputs.at(key) : m_collections.value(key, Json(nullptr));
    const auto result = EditMeasurementCollection(this, key, current, context, m_gateway);
    if (!result.accepted)
    {
        return;
    }
    m_collectionChanged[key] = true;
    if (result.quantity)
    {
        m_collectionInputs[key] = result.value;
    }
    else
    {
        m_collections[key] = result.value;
        m_collectionInputs.erase(key);
    }
    RefreshCollections();
    Changed();
}
