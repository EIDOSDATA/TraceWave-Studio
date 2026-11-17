/** @file @brief PCB 편집의 검토 해시, 원자 적용과 같은 요청의 복구를 관리한다. */
#include "pcb_feature_dialog.h"
#include "pcb_feature_form.h"
#include "pcb_feature_model.h"
#include "design_canvas.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include <wx/choice.h>
#include <wx/listctrl.h>
#include <wx/textctrl.h>
#include <wx/button.h>
#include <wx/msgdlg.h>
#include <wx/weakref.h>
#include <algorithm>
#include <map>

namespace
{
std::string OperationLabel(const std::string& operation)
{
    const auto dot = operation.find('.');
    const auto action = dot == std::string::npos ? operation : operation.substr(dot + 1);
    static const std::map<std::string, std::string> labels{{"set", "입력 / 수정"},
                                                           {"remove", "삭제"},
                                                           {"place", "배치 이동 / 면 전환"},
                                                           {"member_edit", "소유 항목 수정"},
                                                           {"detach", "그룹 해제 / 형상 보존"}};
    const auto found = labels.find(action);
    return found == labels.end() ? "지원 동작" : found->second;
}

std::string SectionOf(const Json& row)
{
    const auto kind = row.value("section", row.value("kind", row.value("collection", "")));
    static const std::map<std::string, std::string> names{{"board.cutouts", "cutout"},
                                                          {"cutouts", "cutout"},
                                                          {"pcb.holes", "hole"},
                                                          {"holes", "hole"},
                                                          {"pcb.footprints", "footprint"},
                                                          {"footprints", "footprint"},
                                                          {"pcb.artwork_layers", "artwork_layer"},
                                                          {"artwork_layers", "artwork_layer"},
                                                          {"pcb.apertures", "aperture"},
                                                          {"apertures", "aperture"},
                                                          {"pcb.keepouts", "keepout"},
                                                          {"keepouts", "keepout"}};
    const auto found = names.find(kind);
    return found == names.end() ? kind : found->second;
}
}

bool PcbFeatureDialog::HasDraft() const
{
    return m_dirty || (m_form && m_form->Dirty());
}

void PcbFeatureDialog::Load(const std::string& section, const Json& id, const Json& transition)
{
    Json input{{"expected_revision", m_revision}, {"section", section}, {"record_id", id}};
    for (const auto& [key, value] : transition.items())
    {
        input[key] = value;
    }
    Request("pcb.features.get", input, false,
            [this](const Json& result)
            {
                if (result.value("project_id", "") != m_projectId || result.value("revision_id", "") != m_revision)
                {
                    throw std::runtime_error("PCB 폼이 현재 프로젝트/개정과 다릅니다.");
                }
                Render(result);
            });
}

void PcbFeatureDialog::Render(const Json& context)
{
    m_loading = true;
    m_context = context;
    m_review = nullptr;
    m_reviewInput = nullptr;
    const auto form = context.value("form", Json::object());
    m_sectionName = form.value("section", "hole");
    m_recordId = form.value("record_id", Json(nullptr));
    const auto found = std::find(m_sections.begin(), m_sections.end(), m_sectionName);
    m_section->SetSelection(found == m_sections.end() ? 1 : static_cast<int>(found - m_sections.begin()));
    m_recordIds = Json::array({nullptr});
    m_record->Clear();
    m_record->Append(Display("새 객체 / 미적용"));
    m_record->SetSelection(0);
    for (const auto& row : context.value("rows", Json::array()))
    {
        if (SectionOf(row) != m_sectionName)
        {
            continue;
        }
        m_recordIds.push_back(row.at("id"));
        m_record->Append(Display(row.value("label", row.value("name", "이름 미정"))));
        if (row.at("id") == m_recordId)
        {
            m_record->SetSelection(static_cast<int>(m_recordIds.size() - 1));
        }
    }
    m_operations.clear();
    m_operation->Clear();
    const auto templates = context.value("operation_inputs", Json::object());
    for (const auto& operation : context.value("operations", Json::array()))
    {
        const auto id = operation.is_string() ? operation.get<std::string>()
                                              : operation.value("id", operation.value("operation", ""));
        const bool allowed = !operation.is_object() || operation.value("allowed", true);
        if (allowed && templates.contains(id) && (!m_recordId.is_null() || id == m_sectionName + ".set"))
        {
            m_operations.push_back(id);
            m_operation->Append(
                Display(operation.is_object() ? operation.value("label", OperationLabel(id)) : OperationLabel(id)));
        }
    }
    if (!m_operations.empty())
    {
        bool owned = false;
        for (const auto& row : context.value("rows", Json::array()))
        {
            if (row.at("id") == m_recordId && !row.value("owner_footprint_id", Json(nullptr)).is_null())
            {
                owned = true;
            }
        }
        const auto original = form.value("original_record", form.at("record"));
        const bool envelopeChanged = m_sectionName == "footprint" && !m_recordId.is_null() &&
                                     original.value("placement_envelope", Json(nullptr)) !=
                                         form.at("record").value("placement_envelope", Json(nullptr));
        const auto preferred = std::find(m_operations.begin(), m_operations.end(),
                                         owned || envelopeChanged ? "footprint.member_edit" : m_sectionName + ".set");
        m_operation->SetSelection(preferred == m_operations.end() ? 0
                                                                  : static_cast<int>(preferred - m_operations.begin()));
    }
    m_form->SetForm(form, context);
    m_operationIndex = m_operation->GetSelection();
    if (m_operationIndex >= 0)
    {
        m_form->SetOperation(m_operations.at(m_operationIndex), m_sectionName);
    }
    m_reason->ChangeValue("");
    m_dirty = form.value("original_record", form.at("record")) != form.at("record");
    m_changes->DeleteAllItems();
    m_issues->ChangeValue(Display(PcbFeatureUi::Issues(context.value("issues", Json::array()))));
    m_conditions->ChangeValue(Display(PcbFeatureUi::Conditions(context)));
    m_source->ChangeValue(Display(context.dump(2)));
    RefreshSelectors();
    m_loading = false;
    ShowScene();
    SetStatus(m_recovery->pending.is_object()
                  ? "이전 적용의 결과를 먼저 확인하세요. 같은 영수증을 조회하며 새 요청은 보내지 않습니다."
                  : "원문과 미정값을 보존한 입력입니다. 바꾼 항목을 검토한 뒤 한 번에 적용합니다.");
    Layout();
    UpdateActions();
}

void PcbFeatureDialog::Changed()
{
    if (m_loading || m_mutating || m_recovering || m_recovery->pending.is_object())
    {
        return;
    }
    InvalidateRead();
    m_review = nullptr;
    m_reviewInput = nullptr;
    m_dirty = true;
    m_changes->DeleteAllItems();
    ShowScene();
    m_issues->ChangeValue(Display("입력이 바뀌어 이전 후보 판정을 표시하지 않습니다. 다시 검토하세요."));
    SetStatus("입력이 바뀌었습니다. 변경 후보를 다시 검토하세요.");
    UpdateActions();
}

Json PcbFeatureDialog::Input() const
{
    const int index = m_operation->GetSelection();
    if (index < 0 || static_cast<std::size_t>(index) >= m_operations.size())
    {
        throw std::runtime_error("현재 객체에서 지원되는 동작을 선택하세요.");
    }
    const auto operation = m_operations.at(index);
    const auto record = m_form->Record();
    const auto templates = m_context.value("operation_inputs", Json::object());
    Json values = templates.value(operation, Json::object());
    if (operation == "footprint.place")
    {
        values["id"] = record.at("id");
        values["placement"] = record.at("placement");
    }
    else if (operation == "footprint.member_edit")
    {
        if (!values.contains("changes"))
        {
            throw std::runtime_error("소유 항목을 편집할 원문 대응이 없습니다. 소유 풋프린트에서 항목을 선택하세요.");
        }
        if (m_sectionName == "footprint")
        {
            values["members"] = record.at("members");
            values["pins"] = record.at("pins");
            values["placement_envelope"] = record.at("placement_envelope");
        }
        for (auto& change : values.at("changes"))
        {
            if (change.value("id", Json(nullptr)) == record.value("id", Json(nullptr)))
            {
                change["record"] = record;
            }
        }
    }
    else if (operation.size() >= 4 && operation.substr(operation.size() - 4) == ".set")
    {
        values["record"] = record;
        if (operation == "artwork_layer.set" && !values.contains("remove_aperture_ids"))
        {
            values["remove_aperture_ids"] = Json::array();
        }
        if (operation == "artwork_layer.set" && record.value("use_state", "") != "used")
        {
            values["remove_aperture_ids"] =
                templates.value("artwork_layer.remove", Json::object()).value("remove_aperture_ids", Json::array());
        }
    }
    else
    {
        values["id"] = record.at("id");
    }
    return {{"expected_revision", m_revision},
            {"operation", operation},
            {"values", values},
            {"reason", Utf8(m_reason->GetValue())}};
}

void PcbFeatureDialog::Preview()
{
    try
    {
        const auto input = Input();
        const auto values = input.at("values");
        if ((input.at("operation") == "artwork_layer.set" &&
             !values.value("remove_aperture_ids", Json::array()).empty()) ||
            input.at("operation").get<std::string>().find(".remove") != std::string::npos ||
            input.at("operation") == "footprint.detach")
        {
            wxMessageDialog confirm(this,
                                    Display("이 후보는 객체 삭제 또는 소유 관계 해제를 포함합니다. 연결된 항목의 "
                                            "변경도 검토표에 함께 표시합니다. 후보 검토를 진행하시겠습니까?"),
                                    Display("관계 변경 검토"), wxYES_NO | wxNO_DEFAULT | wxICON_QUESTION);
            if (confirm.ShowModal() != wxID_YES)
            {
                return;
            }
        }
        Request(
            "pcb.features.preview", input, false,
            [this, input](const Json& result)
            {
                if (result.value("project_id", "") != m_projectId ||
                    result.value("source_revision_id", result.value("revision_id", "")) != m_revision)
                {
                    throw std::runtime_error("변경 후보의 원본 프로젝트/개정이 다릅니다.");
                }
                m_review = result;
                m_reviewInput = input;
                m_changes->DeleteAllItems();
                for (const auto& change : result.value("changes", Json::array()))
                {
                    const long row =
                        m_changes->InsertItem(m_changes->GetItemCount(), Display(change.value("label", "변경 항목")));
                    m_changes->SetItem(row, 1,
                                       Display(PcbFeatureUi::Text(
                                           change.value("before_display", change.value("before", Json(nullptr))))));
                    m_changes->SetItem(row, 2,
                                       Display(PcbFeatureUi::Text(
                                           change.value("after_display", change.value("after", Json(nullptr))))));
                    m_changes->SetItem(row, 3, Display(PcbFeatureUi::Text(change.value("unit", Json(nullptr)), "")));
                }
                m_issues->ChangeValue(Display(PcbFeatureUi::Issues(result.value("issues", Json::array()))));
                m_source->ChangeValue(Display(result.dump(2)));
                m_tabs->SetSelection(1);
                ShowScene();
                SetStatus(result.value("can_apply", false)
                              ? "변경 전후 형상과 참조를 확인했습니다. 검토한 입력만 원자 적용할 수 있습니다."
                              : "후보를 적용할 수 없습니다. 누락 입력과 지원 범위를 확인하세요.");
            });
    }
    catch (const std::exception& error)
    {
        SetStatus(error.what());
    }
}

void PcbFeatureDialog::Apply()
{
    if (!Editable() || m_pending || m_form->Pending() || m_recovery->pending.is_object() ||
        !PcbFeatureUi::MatchesReview(m_review, m_reviewInput, m_projectId))
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
        Request("pcb.features.apply", input, true,
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

void PcbFeatureDialog::Accept(const Json& result)
{
    if (!PcbFeatureUi::MatchesApplied(result, m_projectId))
    {
        throw std::runtime_error(
            "PCB 적용 응답의 프로젝트와 개정을 확인할 수 없습니다. 같은 요청 영수증을 조회하세요.");
    }
    AcceptMutation(result);
    if (m_recovery->resolved)
    {
        m_recovery->resolved();
    }
    m_recovery->pending = nullptr;
    m_dirty = false;
    m_closed = true;
    EndModal(wxID_APPLY);
}

void PcbFeatureDialog::Recover()
{
    if (!m_recovery->pending.is_object() || m_recovering || m_mutating)
    {
        return;
    }
    m_recovering = true;
    UpdateActions();
    wxWeakRef<PcbFeatureDialog> weak(this);
    const auto pending = m_recovery->pending;
    m_gateway(
        "pcb.features.receipt",
        {{"request_key", pending.at("request_key")}, {"request_key_epoch", pending.at("request_key_epoch")}}, false,
        [weak](const Json& receipt)
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
                    weak->Accept(receipt.at("response"));
                    return;
                }
                weak->SetStatus("이전 적용의 결과가 아직 확정되지 않았습니다. 새 키로 다시 적용하지 않습니다. 같은 "
                                "요청을 다시 조회하세요.");
            }
            catch (const std::exception& error)
            {
                weak->SetStatus(error.what());
            }
            weak->UpdateActions();
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

void PcbFeatureDialog::ShowScene()
{
    Json scene = m_review.is_object()
                     ? m_review.value(m_sceneChoice->GetSelection() == 1 ? "before_scene" : "scene",
                                      m_sceneChoice->GetSelection() == 1 ? m_context.value("scene", Json(nullptr))
                                                                         : Json(nullptr))
                     : m_context.value("scene", Json(nullptr));
    if (!scene.is_object())
    {
        scene = {
            {"board", nullptr}, {"layers", Json::array()}, {"shapes", Json::array()}, {"omissions", Json::array()}};
    }
    m_canvas->SetScene(scene);
    m_canvas->FitView();
    wxWeakRef<DesignCanvas> weak(m_canvas);
    CallAfter(
        [weak]()
        {
            if (weak)
            {
                weak->FitView();
            }
        });
}

void PcbFeatureDialog::UpdateActions()
{
    const bool unknown = m_recovery->pending.is_object();
    const bool ready = Editable() && !m_pending && !m_recovering && !unknown && !m_form->Pending();
    m_form->Enable(ready);
    m_section->Enable(ready);
    m_record->Enable(ready);
    m_shape->Enable(ready);
    m_definition->Enable(ready);
    m_envelope->Enable(ready);
    m_operation->Enable(ready);
    m_reason->Enable(ready);
    m_preview->Enable(ready && m_form->Supported() && !m_operations.empty());
    m_apply->Enable(ready && PcbFeatureUi::MatchesReview(m_review, m_reviewInput, m_projectId));
    m_recover->Show(unknown);
    m_recover->Enable(unknown && !m_recovering && !m_mutating);
    Layout();
}

void PcbFeatureDialog::ShowRequestFailure(const Json& error)
{
    ProjectSetupDialog::ShowRequestFailure(error);
    m_review = nullptr;
    m_reviewInput = nullptr;
}
