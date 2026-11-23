/** @file @brief 손실 승인과 명시 대응을 검토 해시에 묶고 영수증만으로 복구한다. */
#include <algorithm>
#include "pcb_import_dialog.h"
#include "pcb_feature_model.h"
#include "output_model.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include <wx/checkbox.h>
#include <wx/checklst.h>
#include <wx/choice.h>
#include <wx/listctrl.h>
#include <wx/textctrl.h>
#include <wx/weakref.h>

Json PcbImportDialog::Input() const
{
    if (m_upload.empty() || !m_mappingLoaded || !m_boardConfirmed->GetValue() ||
        m_context.value("board_id", Json(nullptr)).is_null())
    {
        throw std::runtime_error("현재 기판 / 좌표계와 원문 대응을 먼저 확인하세요.");
    }
    Json mapping{{"board_id", m_context.at("board_id")},
                 {"frame_id", m_context.at("frame_id")},
                 {"layers", Json::array()},
                 {"nets", Json::array()},
                 {"placement", nullptr}};
    const std::string format = m_uploadState.value("format", "");
    const bool manufacturing = format == "ipc2581_revc" || format == "odbpp_zip";
    const bool contacts = manufacturing && m_contacts->GetValue();
    const bool regions = manufacturing && m_regions->GetValue();
    if (manufacturing)
    {
        mapping["include_contacts"] = contacts;
        mapping["include_regions"] = regions;
        mapping["adopt_stack"] = m_adoptStack->GetValue();
        mapping["include_components"] = m_components->GetValue();
    }
    const auto noTargets = [contacts, regions](const auto& rows)
    {
        return std::none_of(rows.begin(), rows.end(), [contacts, regions](const auto& row)
        {
            return row.Included(contacts, regions) && row.choice->GetSelection() > 0;
        });
    };
    const bool outlineOnly = manufacturing && !contacts && !regions &&
                             noTargets(m_layerRows) && noTargets(m_netRows);
    for (const auto& kind : {std::string("layers"), std::string("nets")})
    {
        if (outlineOnly)
        {
            break;
        }
        for (const auto& row : kind == "layers" ? m_layerRows : m_netRows)
        {
            if (!row.Included(contacts, regions))
            {
                continue;
            }
            const int index = row.choice->GetSelection();
            if (index <= 0 || static_cast<std::size_t>(index) >= row.targets.size())
            {
                throw std::runtime_error(
                    "모든 원문 층과 넷의 대응을 명시하세요. 넷을 할당하지 않을 때도 미할당을 직접 선택해야 합니다.");
            }
            mapping[kind].push_back(
                {{"source", row.source}, {"target", row.targets.at(static_cast<std::size_t>(index))}});
        }
    }
    const bool vendor = VendorFormat();
    if (m_uploadState.value("format", "") == "kicad_mod" || vendor)
    {
        if ((!vendor && m_side->GetSelection() <= 0) || m_x->IsEmpty() || m_y->IsEmpty() || m_rotation->IsEmpty())
        {
            throw std::runtime_error(
                "원본 배치의 X / Y / 회전을 입력하세요. KiCad 풋프린트에는 배치 면도 필요합니다.");
        }
        const auto quantity = [](wxTextCtrl* value, wxChoice* unit)
        {
            return Json{{"text", Utf8(value->GetValue())},
                        {"unit", Utf8(unit->GetStringSelection())},
                        {"source_refs", Json::array()}};
        };
        mapping["placement"] = {{"origin", Json::array({quantity(m_x, m_lengthUnit), quantity(m_y, m_lengthUnit)})},
                                {"rotation", quantity(m_rotation, m_angleUnit)}};
        if (!vendor)
        {
            mapping["placement"]["side"] = m_side->GetSelection() == 1 ? "top" : "bottom";
        }
    }
    Json acknowledged = Json::array();
    for (unsigned int index = 0; index < m_losses->GetCount(); ++index)
    {
        if (m_losses->IsChecked(index))
        {
            acknowledged.push_back(m_lossKeys.at(index));
        }
    }
    return {{"upload_id", m_upload},
            {"expected_revision", m_revision},
            {"mapping", mapping},
            {"acknowledged_losses", acknowledged},
            {"reason", Utf8(m_reason->GetValue())}};
}

void PcbImportDialog::Preview()
{
    if (!Editable() || m_pending || Uncertain())
    {
        return;
    }
    try
    {
        const auto input = Input();
        Request(
            "pcb.import.preview", input, false,
            [this, input](const Json& response)
            {
                if (response.value("project_id", "") != m_projectId ||
                    response.value("source_revision_id", response.value("revision_id", "")) != m_revision ||
                    response.value("upload_id", "") != m_upload)
                {
                    throw std::runtime_error("가져오기 검토의 프로젝트 / 개정 / 원문 전송이 다릅니다.");
                }
                m_review = response;
                m_reviewInput = input;
                m_changes->DeleteAllItems();
                for (const auto& change : response.value("changes", Json::array()))
                {
                    const long row = m_changes->InsertItem(
                        m_changes->GetItemCount(),
                        Display(OutputUi::Text(change.value("label", Json(nullptr)), "변경 항목")));
                    m_changes->SetItem(
                        row, 1,
                        Display(OutputUi::Text(change.value("before_display", change.value("before", Json(nullptr))))));
                    m_changes->SetItem(
                        row, 2,
                        Display(OutputUi::Text(change.value("after_display", change.value("after", Json(nullptr))))));
                    m_changes->SetItem(row, 3, Display(OutputUi::Text(change.value("unit", Json(nullptr)), "")));
                }
                m_issues->ChangeValue(Display(OutputUi::Issues(response.value("issues", Json::array()))));
                m_raw->ChangeValue(Display(response.dump(2)));
                m_tabs->SetSelection(2);
                ShowScene();
                SetStatus(
                    response.value("can_apply", false)
                        ? "변경 기하와 손실을 확인한 입력만 한 명령으로 적용합니다. 기존 출처 / 미정값과 가져온 원문을 "
                          "보존합니다."
                        : "적용할 수 없는 항목이 있습니다. 대응 / 손실 확인 / 필수 입력을 수정한 뒤 다시 검토하세요.");
            });
    }
    catch (const std::exception& error)
    {
        SetStatus(error.what());
    }
}

void PcbImportDialog::Apply()
{
    if (!Editable() || m_pending || Uncertain() || !m_review.is_object() || !m_review.value("can_apply", false))
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
        Json input = m_reviewInput;
        input["review_hash"] = m_review.at("review_hash");
        input["command_id"] = Uuid();
        Request("pcb.import.apply", input, true,
                [this](const Json& result)
                {
                    Accept(result);
                });
    }
    catch (const std::exception& error)
    {
        SetStatus(error.what());
    }
}

void PcbImportDialog::Accept(const Json& result)
{
    if (!PcbFeatureUi::MatchesApplied(result, m_projectId) || result.value("upload_id", "") != m_upload)
    {
        throw std::runtime_error("가져온 원문과 적용 개정을 확인할 수 없습니다. 같은 요청 영수증을 조회하세요.");
    }
    AcceptMutation(result);
    m_recovery->clear();
    m_recovery->checkpoint = nullptr;
    m_dirty = false;
    m_closed = true;
    m_poll.Stop();
    EndModal(wxID_APPLY);
}

void PcbImportDialog::Confirmed(const std::string& method, const Json& result)
{
    const auto request = m_recovery->checkpoint;
    m_disconnected = false;
    m_pending = false;
    m_mutating = false;
    m_uploading = false;
    const auto input = request.value("input", Json::object());
    m_upload = result.value("upload_id", input.value("upload_id", ""));
    if (m_upload.empty())
    {
        throw std::runtime_error("권위 응답에서 원문 전송을 확인할 수 없습니다.");
    }
    if (method == "pcb.import.apply")
    {
        Accept(result);
        return;
    }
    ReadUpload(m_upload);
}

void PcbImportDialog::Recover()
{
    if (!m_recovery->checkpoint.is_object() || m_recovering || m_mutating)
    {
        return;
    }
    const auto checkpoint = m_recovery->checkpoint;
    if (checkpoint.value("confirmed", false))
    {
        try
        {
            Confirmed(checkpoint.at("method"), checkpoint.at("response"));
        }
        catch (const std::exception& error)
        {
            SetStatus(error.what());
        }
        UpdateActions();
        return;
    }
    m_recovering = true;
    UpdateActions();
    wxWeakRef<PcbImportDialog> weak(this);
    m_gateway(
        "pcb.import.receipt",
        {{"request_key", checkpoint.at("request_key")}, {"request_key_epoch", checkpoint.at("request_key_epoch")}},
        false,
        [weak, checkpoint](const Json& receipt)
        {
            if (!weak || weak->m_closed)
            {
                return;
            }
            weak->m_recovering = false;
            try
            {
                if (receipt.value("status", "") == "found" && receipt.value("authoritative", false))
                {
                    weak->m_recovery->confirmed(receipt.at("response"));
                    weak->Confirmed(checkpoint.at("method"), receipt.at("response"));
                }
                else
                {
                    weak->SetStatus("이전 요청의 결과를 아직 확인하지 못했습니다. 새 키로 전송하거나 중복 적용하지 "
                                    "않습니다. 같은 영수증을 다시 조회하세요.");
                }
            }
            catch (const std::exception& error)
            {
                weak->SetStatus(error.what());
            }
            if (!weak->m_closed)
            {
                weak->UpdateActions();
            }
        },
        [weak](const Json& error)
        {
            if (weak && !weak->m_closed)
            {
                weak->m_recovering = false;
                weak->SetStatus(DiagnosticMessage(error));
                weak->UpdateActions();
            }
        });
}
