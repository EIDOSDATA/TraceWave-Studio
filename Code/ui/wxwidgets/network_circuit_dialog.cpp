/** @file @brief 정합망의 초안, 단위 변환과 검토 해시를 서비스 요청에 연결한다. */
#include "network_circuit_dialog.h"
#include "network_chart.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include <wx/wx.h>
#include <wx/listctrl.h>
#include <algorithm>
#include <array>
#include <stdexcept>

namespace
{
const std::array<std::string, 3> Kinds{"R", "L", "C"};
const std::array<std::string, 2> Connections{"series", "shunt"};
const std::array<std::string, 4> States{"connected", "open", "short", "dnp"};

}

NetworkCircuitDialog::NetworkCircuitDialog(wxWindow* parent, const Json& context, const Json& selection,
                                           DialogGateway gateway)
    : ProjectSetupDialog(parent, "외부 정합망 (기본 RLC)", context, std::move(gateway)), m_context(context),
      m_selection(selection)
{
    SetName("network.circuit.dialog");
    BuildInterface();
    m_loading = true;
    m_circuits->Append(Display("새 정합망"));
    for (const auto& row : context.at("circuits"))
    {
        m_circuits->Append(Display(row.at("name").get<std::string>()));
    }
    m_circuits->SetSelection(0);
    int selected = wxNOT_FOUND;
    for (const auto& row : context.at("datasets"))
    {
        const int index = m_datasets->Append(Display(row.at("name").get<std::string>()));
        if (!selection.is_null() && row.at("id") == selection.at("entry").at("id"))
        {
            selected = index;
        }
    }
    m_datasets->SetSelection(selected);
    m_loading = false;
    LoadCircuit(0);
    RenderData();
    UpdateActions();
}

void NetworkCircuitDialog::LoadCircuit(int index)
{
    m_loading = true;
    m_circuitIndex = index;
    if (index == 0)
    {
        m_definition = {{"schema", "rfad.ideal-rlc/0.1"},  {"name", "정합망 01"},
                        {"em_scope", "outside_em"},        {"input_reference_plane", nullptr},
                        {"load_reference_plane", nullptr}, {"elements", Json::array()},
                        {"source_refs", Json::array()},    {"assumptions", Json::array()}};
        m_elements = Json::array();
        m_savedCircuitId.clear();
    }
    else
    {
        const auto& row = m_context.at("circuits").at(index - 1);
        m_definition = row.at("definition");
        m_elements = row.at("display").at("elements");
        m_savedCircuitId = row.at("id");
    }
    m_name->ChangeValue(Display(m_definition.at("name").get<std::string>()));
    m_inputPlane->ChangeValue(m_definition.at("input_reference_plane").is_null()
                                  ? wxString()
                                  : Display(m_definition.at("input_reference_plane").get<std::string>()));
    m_loadPlane->ChangeValue(m_definition.at("load_reference_plane").is_null()
                                 ? wxString()
                                 : Display(m_definition.at("load_reference_plane").get<std::string>()));
    m_elementIndex = m_elements.empty() ? -1 : 0;
    m_dirty = false;
    m_loading = false;
    InvalidateReview();
    RenderElements();
    RenderElement();
    SetStatus("값이 없는 소자는 미정으로 저장됩니다. 회로 저장과 부하 결합 계산은 별도 동작입니다.");
    UpdateActions();
}

Json NetworkCircuitDialog::Definition() const
{
    Json value = m_definition;
    value["name"] = Utf8(m_name->GetValue());
    value["input_reference_plane"] =
        m_inputPlane->GetValue().empty() ? Json(nullptr) : Json(Utf8(m_inputPlane->GetValue()));
    value["load_reference_plane"] =
        m_loadPlane->GetValue().empty() ? Json(nullptr) : Json(Utf8(m_loadPlane->GetValue()));
    value["elements"] = Json::array();
    for (const auto& element : m_elements)
    {
        Json stored = element;
        stored.erase("value_text");
        stored.erase("value_unit");
        stored.erase("allowed_units");
        value["elements"].push_back(stored);
    }
    return value;
}

void NetworkCircuitDialog::InvalidateReview()
{
    InvalidateRead();
    m_review = nullptr;
    m_reviewInput = nullptr;
    if (m_results)
    {
        m_resultGraph->Clear();
        m_results->DeleteAllItems();
        m_resultDetails->ChangeValue(
            Display("결합 검토 후 실제 원본 및 파생 표본을 표시합니다. 방사 효율은 자동 승계하지 않습니다."));
        m_pageLabel->SetLabel(Display("결합 결과 없음"));
    }
}

void NetworkCircuitDialog::ChangeDefinition()
{
    if (m_loading)
    {
        return;
    }
    m_dirty = true;
    InvalidateReview();
    UpdateActions();
}

void NetworkCircuitDialog::AddElement(const std::string& connection)
{
    if (m_elements.size() >= 16 || !Editable() || m_pending)
    {
        return;
    }
    m_elements.push_back({{"id", Uuid()},
                          {"name", "R" + std::to_string(m_elements.size() + 1)},
                          {"kind", "R"},
                          {"connection", connection},
                          {"state", "connected"},
                          {"value", {{"text", ""}, {"unit", "ohm"}, {"source_refs", Json::array()}}},
                          {"source_refs", Json::array()},
                          {"value_text", ""},
                          {"value_unit", "ohm"}});
    m_elementIndex = static_cast<int>(m_elements.size()) - 1;
    ChangeDefinition();
    RenderElements();
    RenderElement();
}

void NetworkCircuitDialog::RemoveElement()
{
    if (m_elementIndex < 0 || !Editable() || m_pending)
    {
        return;
    }
    m_elements.erase(m_elements.begin() + m_elementIndex);
    m_elementIndex = m_elements.empty() ? -1 : std::min(m_elementIndex, static_cast<int>(m_elements.size()) - 1);
    ChangeDefinition();
    RenderElements();
    RenderElement();
}

void NetworkCircuitDialog::MoveElement(int direction)
{
    const int destination = m_elementIndex + direction;
    if (!Editable() || m_pending || m_elementIndex < 0 || destination < 0 ||
        destination >= static_cast<int>(m_elements.size()))
    {
        return;
    }
    std::swap(m_elements.at(m_elementIndex), m_elements.at(destination));
    m_elementIndex = destination;
    ChangeDefinition();
    RenderElements();
    RenderElement();
}

void NetworkCircuitDialog::EditElement(bool valueChanged, bool kindChanged)
{
    if (m_loading || m_elementIndex < 0 || !Editable() || m_pending)
    {
        return;
    }
    auto& element = m_elements.at(m_elementIndex);
    element["name"] = Utf8(m_elementName->GetValue());
    element["connection"] = Connections.at(m_connection->GetSelection());
    element["state"] = States.at(m_state->GetSelection());
    element["kind"] = Kinds.at(m_kind->GetSelection());
    if (kindChanged)
    {
        const std::string kind = element.at("kind");
        element["value_unit"] = kind == "R" ? "ohm" : kind == "L" ? "nH" : "pF";
        element["value_text"] = "";
        element["value"] = {
            {"text", ""}, {"unit", element.at("value_unit")}, {"source_refs", element.at("value").at("source_refs")}};
    }
    else if (valueChanged)
    {
        element["value_text"] = Utf8(m_value->GetValue());
        element["value"] = {{"text", element.at("value_text")},
                            {"unit", element.at("value_unit")},
                            {"source_refs", element.at("value").at("source_refs")}};
    }
    ChangeDefinition();
    RenderElements();
    if (kindChanged)
    {
        RenderElement();
    }
}

void NetworkCircuitDialog::ChangeUnit()
{
    if (m_loading || m_elementIndex < 0 || !Editable() || m_pending)
    {
        return;
    }
    auto& element = m_elements.at(m_elementIndex);
    const std::string unit = Utf8(m_unit->GetStringSelection());
    const Json quantity = element.at("value");
    const std::string identity = element.at("id");
    ChangeDefinition();
    Request("network.quantity", {{"expected_revision", m_revision}, {"quantity", quantity}, {"display_unit", unit}},
            false,
            [this, identity](const Json& result)
            {
                auto& current = m_elements.at(m_elementIndex);
                if (current.at("id") != identity)
                {
                    return;
                }
                current["value"] = result.at("quantity");
                current["value_text"] = result.at("text");
                current["value_unit"] = result.at("unit");
                RenderElements();
                RenderElement();
            });
    UpdateActions();
}

void NetworkCircuitDialog::SelectDataset()
{
    if (m_loading)
    {
        return;
    }
    InvalidateReview();
    m_selection = nullptr;
    RenderData();
    const int index = m_datasets->GetSelection();
    if (index < 0)
    {
        UpdateActions();
        return;
    }
    const Json id = m_context.at("datasets").at(index).at("id");
    Request("network.get",
            {{"expected_revision", m_revision},
             {"dataset_id", id},
             {"offset", 0},
             {"limit", 201},
             {"row", 0},
             {"column", 0}},
            false,
            [this, id](const Json& result)
            {
                if (result.at("entry").at("id") != id)
                {
                    throw std::runtime_error("선택한 네트워크 자료와 응답이 다릅니다.");
                }
                m_selection = result;
                RenderData();
            });
}

void NetworkCircuitDialog::Preview(bool calculate)
{
    if (!Editable() || m_pending || (calculate && (m_selection.is_null() || m_savedCircuitId.empty() || m_dirty)))
    {
        return;
    }
    const std::string operation = calculate ? "circuit_apply" : "circuit_save";
    Json parameters = calculate ? Json{{"name", Utf8(m_resultName->GetValue())},
                                       {"dataset_id", m_selection.at("entry").at("id")},
                                       {"circuit_id", m_savedCircuitId}}
                                : Json{{"name", Utf8(m_name->GetValue())}, {"definition", Definition()}};
    const Json input{{"expected_revision", m_revision}, {"operation", operation}, {"parameters", parameters}};
    InvalidateReview();
    Request("network.preview", input, false,
            [this, input, calculate](const Json& result)
            {
                if (result.at("project_id") != m_projectId || result.at("revision_id") != m_revision ||
                    (result.value("can_apply", false) && result.at("operation") != input.at("operation")))
                {
                    throw std::runtime_error("정합망 후보의 프로젝트, 개정 또는 작업이 다릅니다.");
                }
                m_review = result;
                m_reviewInput = input;
                if (result.value("can_apply", false))
                {
                    if (calculate)
                    {
                        RenderResult(result);
                        m_tabs->SetSelection(2);
                    }
                    else if (result.contains("circuit_display") && result.at("circuit_display").is_object())
                    {
                        m_elements = result.at("circuit_display").at("elements");
                        RenderElements();
                        RenderElement();
                    }
                    SetStatus(calculate ? "결합 후보를 검토했습니다. 결과 저장 전이며 원본 부하와 회로는 보존됩니다."
                                        : "회로 정의를 검토했습니다. 저장하면 독립 회로 사본이 추가됩니다.");
                }
                else
                {
                    std::string reason = "검토를 완료할 수 없습니다.";
                    for (const auto& issue : result.at("issues"))
                    {
                        reason += "\n" + issue.value("message", "입력 확인 필요");
                    }
                    SetStatus(reason);
                }
            });
}

void NetworkCircuitDialog::Apply()
{
    if (!Editable() || m_pending || m_review.is_null() || !m_review.value("can_apply", false))
    {
        return;
    }
    Json input = m_reviewInput;
    input["command_id"] = Uuid();
    input["review_hash"] = m_review.at("review_hash");
    Request("network.apply", input, true,
            [this, input](const Json& result)
            {
                if (result.at("operation") != input.at("operation"))
                {
                    throw std::runtime_error("정합망 적용 응답의 작업이 다릅니다.");
                }
                AcceptMutation(result);
                const bool savedDefinition = result.at("operation") == "circuit_save";
                m_dirty = false;
                m_review = nullptr;
                m_reviewInput = nullptr;
                if (savedDefinition)
                {
                    m_savedCircuitId = result.at("record_id");
                    SetStatus("회로 사본을 저장했습니다. 목록을 갱신하고 있습니다.");
                    RefreshLibrary(m_savedCircuitId);
                }
                else
                {
                    SetStatus("결합 결과를 별도 자료로 저장했습니다. 닫으면 결과 목록에 반영됩니다.");
                    CloseDialog();
                }
            });
}

void NetworkCircuitDialog::RefreshLibrary(const std::string& selectedId)
{
    Request("network.library", {{"expected_revision", m_revision}}, false,
            [this, selectedId](const Json& result)
            {
                m_context = result;
                m_loading = true;
                m_circuits->Clear();
                m_circuits->Append(Display("새 정합망"));
                int selected = 0;
                for (const auto& row : result.at("circuits"))
                {
                    const int index = m_circuits->Append(Display(row.at("name").get<std::string>()));
                    if (row.at("id") == selectedId)
                    {
                        selected = index;
                    }
                }
                m_circuits->SetSelection(selected);
                m_loading = false;
                LoadCircuit(selected);
            });
}

bool NetworkCircuitDialog::HasDraft() const
{
    return m_dirty || (!m_review.is_null() && m_review.value("can_apply", false));
}

void NetworkCircuitDialog::UpdateActions()
{
    if (!m_apply)
    {
        return;
    }
    const bool enabled = Editable() && !m_pending;
    for (auto* control :
         std::vector<wxWindow*>{m_circuits, m_datasets, m_name, m_inputPlane, m_loadPlane, m_resultName, m_table})
    {
        control->Enable(enabled);
    }
    m_elementFields->Enable(enabled && m_elementIndex >= 0);
    for (std::size_t index = 0; index < m_editButtons.size(); ++index)
    {
        const bool allowed = index < 2    ? m_elements.size() < 16
                             : index == 2 ? m_elementIndex >= 0
                             : index == 3
                                 ? m_elementIndex > 0
                                 : m_elementIndex >= 0 && m_elementIndex + 1 < static_cast<int>(m_elements.size());
        m_editButtons[index]->Enable(enabled && allowed);
    }
    const bool draft = m_dirty || m_savedCircuitId.empty();
    const bool reviewed = !m_review.is_null() && m_review.value("can_apply", false);
    const auto stage = Display(m_pending ? "검토 또는 저장 응답을 기다리고 있습니다."
        : draft && m_elements.empty() ? "직렬 또는 병렬 소자를 추가하고 값을 입력하세요."
        : draft && reviewed ? "회로 검토 완료. 회로 사본을 저장하면 결합 검토를 할 수 있습니다."
        : draft ? "입력 기준면과 소자 값을 확인한 뒤 회로 검토를 누르세요."
        : m_selection.is_null() ? "결합할 안테나 또는 부하 자료를 선택하세요."
        : reviewed ? "결합 검토 완료. 원본과 계산값을 확인한 뒤 별도 결과로 저장하세요."
        : "회로 사본과 부하가 준비됐습니다. 결합 검토를 누르세요.");
    if (m_step->GetLabel() != stage)
    {
        m_step->SetLabel(stage);
        Layout();
    }
    const auto planes = m_selection.is_object() ? m_selection.at("descriptor").value("reference_planes", Json::array())
                                               : Json::array();
    m_useLoadPlane->Enable(enabled && planes.size() == 1 && planes.front().is_string());
    m_reviewDefinition->Enable(enabled && !m_elements.empty() && draft);
    m_reviewCalculation->Enable(enabled && !m_dirty && !m_savedCircuitId.empty() && !m_selection.is_null());
    m_apply->Enable(enabled && !m_review.is_null() && m_review.value("can_apply", false));
    m_apply->SetLabel(Display(!m_reviewInput.is_null() && m_reviewInput.value("operation", "") == "circuit_apply"
                                  ? "검토한 결과 저장"
                                  : "검토한 회로 저장"));
}

void NetworkCircuitDialog::ShowRequestFailure(const Json& error)
{
    m_review = nullptr;
    m_reviewInput = nullptr;
    RenderElement();
    ProjectSetupDialog::ShowRequestFailure(error);
}
