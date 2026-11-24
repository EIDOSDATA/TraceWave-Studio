/** @file @brief 연구 초안/검토 해시와 원자 저장의 요청 수명을 관리한다. */
#include "sweep_dialog.h"
#include "sweep_model.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include <wx/wx.h>
#include <wx/checklst.h>
#include <wx/grid.h>
#include <wx/listctrl.h>
#include <wx/spinctrl.h>
#include <array>
#include <sstream>
#include <stdexcept>

namespace
{
const std::array<const char*, 3> Types{{"grid_sweep", "numerical_study", "circuit_sweep"}};
const std::array<const char*, 3> Combinations{{"cartesian", "paired", "explicit_rows"}};
const std::array<const char*, 4> States{{"connected", "open", "short", "dnp"}};
Json Sources(wxTextCtrl* input)
{
    Json result = Json::array();
    std::istringstream lines(Utf8(input->GetValue()));
    std::string line;
    while (std::getline(lines, line))
    {
        if (!line.empty())
        {
            result.push_back(line);
        }
    }
    return result;
}
}

SweepDialog::SweepDialog(wxWindow* parent, const Json& context, DialogGateway gateway)
    : ProjectSetupDialog(parent, "새 다축 설계 스윕", context, std::move(gateway)),
      m_context(context), m_basis(context.at("initial_specification"))
{
    SetName("sweep.dialog");
    m_loading = true;
    BuildInterface();
    m_name->ChangeValue(Display(m_basis.value("name", "연구 01")));
    m_type->SetSelection(0);
    m_combination->SetSelection(0);
    m_loading = false;
    LoadCatalog();
    RefreshPorts();
    UpdateActions();
}

bool SweepDialog::HasDraft() const
{
    return m_dirty && !m_saved;
}

void SweepDialog::Changed()
{
    if (m_loading || m_saved)
    {
        return;
    }
    m_dirty = true;
    InvalidateRead();
    m_review = nullptr;
    m_reviewInput = nullptr;
    m_previewRows->DeleteAllItems();
    m_reviewSummary->SetLabel(Display("입력이 변경되었습니다. 후보를 다시 검토하세요."));
    m_diagnostics->Clear();
    UpdateActions();
}

Json SweepDialog::Specification() const
{
    Json spec = m_basis;
    const int type = m_type->GetSelection();
    const int combination = m_combination->GetSelection();
    if (type < 0 || combination < 0)
    {
        throw std::runtime_error("연구 유형과 조합을 선택하세요.");
    }
    spec["name"] = Utf8(m_name->GetValue());
    spec["type"] = Types.at(type);
    spec["combination"] = Combinations.at(combination);
    spec["variables"] = m_variables;
    spec["rows"] = Json::array();
    if (combination == 2)
    {
        for (int row = 0; row < m_rows->GetNumberRows(); ++row)
        {
            Json indices = Json::array();
            for (int column = 0; column < m_rows->GetNumberCols(); ++column)
            {
                const auto text = m_rows->GetCellValue(row, column).BeforeFirst(':');
                long ordinal = 0;
                if (!text.ToLong(&ordinal) || ordinal < 1)
                {
                    throw std::runtime_error("명시 후보 행의 각 변수 값을 선택하세요.");
                }
                indices.push_back(ordinal - 1);
            }
            spec["rows"].push_back(indices);
        }
    }
    spec["network"] = nullptr;
    if (type == 2)
    {
        spec["settings"] = nullptr;
        if (m_datasets->GetSelection() < 0 || m_circuits->GetSelection() < 0)
        {
            throw std::runtime_error("기준 자료와 정합망을 명시적으로 선택하세요.");
        }
        spec["network"] = {{"dataset_id", m_context.at("datasets").at(m_datasets->GetSelection()).at("id")},
                           {"circuit_id", m_context.at("circuits").at(m_circuits->GetSelection()).at("id")}};
    }
    Json settingInputs = Json::object();
    if (type != 2)
    {
        const auto defaults = m_context.value("optional_settings_defaults", Json::object());
        if (m_recordRadiation->GetValue())
        {
            spec["settings"]["radiation"] = defaults.at("radiation");
        }
        if (m_featureSubdivisions->GetValue())
        {
            spec["settings"]["feature_subdivisions"] = defaults.at("feature_subdivisions");
        }
        if (m_recordLosses->GetValue())
        {
            if (!m_recordRadiation->GetValue())
            {
                throw std::runtime_error("독립 손실 기록에는 NF2FF 방사 기록을 함께 지정하세요.");
            }
            spec["settings"]["power_balance"] = defaults.at("power_balance");
        }
        for (const auto& item : m_settings)
        {
            if (item.second.dirty && item.second.eligible)
            {
                settingInputs[item.first] =
                    item.second.quantityCurrent
                        ? item.second.quantity
                        : Json{{"text", Utf8(item.second.text->GetValue())},
                               {"unit", item.second.displayUnit},
                               {"source_refs", item.second.quantity.value("source_refs", Json::array())}};
            }
        }
        if (m_recordRadiation->GetValue() && m_radiationDirty)
        {
            Json frequencies = Json::array();
            for (int index = 0; index < m_radiationCount->GetValue(); ++index)
            {
                const auto& field = m_radiationFields.at(index);
                frequencies.push_back(field.dirty
                                          ? Json{{"text", Utf8(field.text->GetValue())},
                                                 {"unit", field.displayUnit},
                                                 {"source_refs", field.quantity.value("source_refs", Json::array())}}
                                          : field.quantity);
            }
            settingInputs["radiation.frequency_hz"] = frequencies;
        }
    }
    spec.erase("settings_inputs");
    if (!settingInputs.empty())
    {
        spec["settings_inputs"] = settingInputs;
    }
    spec["target_ids"] = Json::array();
    spec["target_contexts"] = Json::array();
    for (unsigned index = 0; index < m_targets->GetCount(); ++index)
    {
        if (!m_targets->IsChecked(index))
        {
            continue;
        }
        const auto& target = m_context.at("targets").at(index);
        spec["target_ids"].push_back(target.at("id"));
        if (m_explicitContext->GetValue())
        {
            if (m_port->GetSelection() < 0)
            {
                throw std::runtime_error("평가할 자료 포트를 명시적으로 선택하세요.");
            }
            const auto reference = Utf8(m_referencePlane->GetValue());
            spec["target_contexts"].push_back(
                {{"target_id", target.at("id")},
                 {"context",
                  {{"port_id", m_portIds.at(m_port->GetSelection())},
                   {"target_port_id", target.value("port_id", Json(nullptr))},
                   {"reference_plane", reference.empty() ? Json(nullptr) : Json(reference)},
                   {"frequency_policy", "exact_only"}}}});
        }
    }
    spec["budget"]["max_candidates"] = m_candidateBudget->GetValue();
    spec["budget"]["max_native_solves"] = m_nativeBudget->GetValue();
    spec["budget"]["concurrency"] = 1;
    spec.erase("budget_inputs");
    Json budgetInputs = Json::object();
    for (const auto& item : m_budgetText)
    {
        if (m_budgetDirty.at(item.first))
        {
            budgetInputs[item.first] = {{"text", Utf8(item.second->GetValue())},
                                        {"unit", m_budgetUnits.at(item.first)}};
        }
    }
    if (!budgetInputs.empty())
    {
        spec["budget_inputs"] = budgetInputs;
    }
    spec["source_refs"] = Sources(m_sources);
    return spec;
}

void SweepDialog::Preview()
{
    if (!Editable() || m_pending || m_saved)
    {
        return;
    }
    try
    {
        if (m_rows->IsCellEditControlEnabled())
        {
            m_rows->SaveEditControlValue();
        }
        const Json spec = Specification();
        m_review = nullptr;
        m_reviewInput = nullptr;
        Request("sweep.preview", {{"expected_revision", m_revision}, {"specification", spec}}, false,
                [this, spec](const Json& result)
                {
                    m_review = result;
                    m_reviewInput = spec;
                    RenderReview(result);
                    m_pages->SetSelection(3);
                });
    }
    catch (const std::exception& error)
    {
        SetStatus(error.what());
    }
}

void SweepDialog::Create()
{
    if (!Editable() || m_pending || m_saved || m_review.is_null() || !m_review.value("can_create", false))
    {
        return;
    }
    try
    {
        if (m_rows->IsCellEditControlEnabled())
        {
            m_rows->SaveEditControlValue();
        }
        const auto spec = Specification();
        if (spec != m_reviewInput)
        {
            Changed();
            SetStatus("변경한 입력을 다시 검토하세요.");
            return;
        }
        Request(
            "sweep.create",
            {{"expected_revision", m_revision}, {"specification", spec}, {"review_hash", m_review.at("review_hash")}},
            true,
            [this](const Json& result)
            {
                m_applied = result;
                m_saved = true;
                m_dirty = false;
                SetStatus("연구를 저장했습니다. 실행은 연구 화면에서 별도로 선택합니다.");
                CloseDialog();
            });
    }
    catch (const std::exception& error)
    {
        SetStatus(error.what());
    }
}

void SweepDialog::LoadCatalog()
{
    const std::string circuit =
        m_circuits->GetSelection() >= 0
            ? m_context.at("circuits").at(m_circuits->GetSelection()).at("id").get<std::string>()
            : "";
    Json context = m_context;
    for (auto& field : context["numerical_fields"])
    {
        if (m_settings.count(field.at("id")) != 0)
        {
            const auto& input = m_settings.at(field.at("id"));
            field["eligible"] = input.eligible;
            if (input.eligible)
            {
                field["quantity"] = input.quantity;
            }
        }
    }
    m_catalog = SweepUi::Variables(context, Types.at(std::max(0, m_type->GetSelection())), circuit);
    m_availableVariables->Clear();
    for (const auto& row : m_catalog)
    {
        const bool allowed = !row.value("read_only", false) && row.value("eligible", true);
        m_availableVariables->Append(Display(row.at("name").get<std::string>() + (allowed ? "" : " (선택 불가)")));
    }
    if (!m_catalog.empty())
    {
        m_availableVariables->SetSelection(0);
    }
    UpdateActions();
}

void SweepDialog::AddVariable()
{
    const int index = m_availableVariables->GetSelection();
    if (index < 0 || m_variables.size() >= 8)
    {
        return;
    }
    const auto& chosen = m_catalog.at(index);
    if (chosen.value("read_only", false) || !chosen.value("eligible", true))
    {
        SetStatus(chosen.value("reason", Json(nullptr)).is_string() ? chosen.at("reason").get<std::string>()
                                                                    : "현재 입력은 스윕할 수 없습니다.");
        return;
    }
    for (const auto& variable : m_variables)
    {
        if (variable.at("id") == chosen.at("id") && variable.at("kind") == chosen.at("kind"))
        {
            SetStatus("이미 추가한 변수입니다.");
            return;
        }
    }
    m_variables.push_back({{"kind", chosen.at("kind")},
                           {"id", chosen.at("id")},
                           {"dimension", chosen.at("dimension")},
                           {"values", Json::array()}});
    m_variableNames.push_back(chosen.at("name"));
    Changed();
    RenderVariables();
    SelectVariable(static_cast<int>(m_variables.size()) - 1);
    RenderRows();
}

void SweepDialog::SelectVariable(int index)
{
    const int previousIndex = m_variableIndex;
    const std::string previousUnit = Utf8(m_valueUnit->GetStringSelection());
    m_variableIndex = index;
    m_loading = true;
    m_values->Clear();
    m_valueUnit->Clear();
    if (index >= 0 && static_cast<std::size_t>(index) < m_variables.size())
    {
        const auto& variable = m_variables.at(index);
        const auto found =
            std::find_if(m_catalog.begin(), m_catalog.end(),
                         [&variable](const Json& item)
                         {
                             return item.at("kind") == variable.at("kind") && item.at("id") == variable.at("id");
                         });
        if (found != m_catalog.end())
        {
            for (const auto& unit : found->value("units", Json::array()))
            {
                m_valueUnit->Append(Display(unit));
            }
            if (m_valueUnit->GetCount() > 0)
            {
                m_valueUnit->SetSelection(0);
                const auto quantity = found->value("quantity", Json(nullptr));
                const std::string recommended = quantity.is_object()
                                                    ? quantity.value("display_unit", found->value("unit", ""))
                                                    : found->value("unit", "");
                m_valueUnit->SetStringSelection(
                    Display(previousIndex == index && !previousUnit.empty() ? previousUnit : recommended));
            }
            m_variableNotice->SetLabel(Display(found->at("name").get<std::string>() + ", 원본: " +
                                               SweepUi::Quantity(found->value("quantity", Json(nullptr)))));
        }
        m_valueMode->SetSelection(variable.contains("range") ? 1 : 0);
        for (const auto& value : variable.value("values", Json::array()))
        {
            m_values->Append(Display(SweepUi::Quantity(value)));
        }
        if (variable.contains("range"))
        {
            const auto& range = variable.at("range");
            m_rangeStart->ChangeValue(Display(range.at("start").value("text", "")));
            m_rangeStop->ChangeValue(Display(range.at("stop").value("text", "")));
            m_rangeCount->SetValue(range.at("count").get<int>());
            m_valueUnit->SetStringSelection(Display(range.at("start").value("unit", "")));
        }
        else if (previousIndex != index)
        {
            m_valueText->ChangeValue(wxEmptyString);
            m_rangeStart->ChangeValue(wxEmptyString);
            m_rangeStop->ChangeValue(wxEmptyString);
            m_rangeCount->SetValue(3);
        }
    }
    m_loading = false;
    UpdateActions();
}

void SweepDialog::AddValue()
{
    if (m_variableIndex < 0)
    {
        return;
    }
    auto& values = m_variables.at(m_variableIndex)["values"];
    if (values.size() >= 128)
    {
        SetStatus("한 변수의 값 목록은 최대 128개입니다.");
        return;
    }
    if (m_variables.at(m_variableIndex).at("dimension") == "state")
    {
        values.push_back(States.at(std::max(0, m_valueState->GetSelection())));
    }
    else
    {
        const auto text = Utf8(m_valueText->GetValue());
        if (text.empty() || m_valueUnit->GetSelection() < 0)
        {
            SetStatus("새 값과 단위를 입력하세요.");
            return;
        }
        values.push_back(
            {{"text", text}, {"unit", Utf8(m_valueUnit->GetStringSelection())}, {"source_refs", Sources(m_sources)}});
    }
    Changed();
    RenderVariables();
    SelectVariable(m_variableIndex);
    RenderRows();
}

void SweepDialog::UpdateRange()
{
    if (m_loading || m_variableIndex < 0 || m_valueMode->GetSelection() != 1)
    {
        return;
    }
    auto& variable = m_variables.at(m_variableIndex);
    if (variable.at("dimension") == "state")
    {
        return;
    }
    const auto unit = Utf8(m_valueUnit->GetStringSelection());
    variable.erase("values");
    variable["range"] = {
        {"start", {{"text", Utf8(m_rangeStart->GetValue())}, {"unit", unit}, {"source_refs", Sources(m_sources)}}},
        {"stop", {{"text", Utf8(m_rangeStop->GetValue())}, {"unit", unit}, {"source_refs", Sources(m_sources)}}},
        {"count", m_rangeCount->GetValue()}};
    Changed();
    RenderVariables();
    RenderRows();
}

void SweepDialog::RenderVariables()
{
    m_loading = true;
    m_variableList->DeleteAllItems();
    for (std::size_t index = 0; index < m_variables.size(); ++index)
    {
        const long row = m_variableList->InsertItem(m_variableList->GetItemCount(), Display(m_variableNames.at(index)));
        m_variableList->SetItem(row, 1, Display(SweepUi::VariableSummary(m_variables.at(index))));
    }
    if (m_variableIndex >= 0 && static_cast<std::size_t>(m_variableIndex) < m_variables.size())
    {
        m_variableList->SetItemState(m_variableIndex, wxLIST_STATE_SELECTED, wxLIST_STATE_SELECTED);
    }
    m_loading = false;
}

void SweepDialog::RenderRows()
{
    m_loading = true;
    if (m_rows->GetNumberCols() != static_cast<int>(m_variables.size()))
    {
        if (m_rows->GetNumberRows() > 0)
        {
            m_rows->DeleteRows(0, m_rows->GetNumberRows());
        }
        if (m_rows->GetNumberCols() > 0)
        {
            m_rows->DeleteCols(0, m_rows->GetNumberCols());
        }
        if (!m_variables.empty())
        {
            m_rows->AppendCols(static_cast<int>(m_variables.size()));
        }
    }
    for (std::size_t column = 0; column < m_variables.size(); ++column)
    {
        m_rows->SetColLabelValue(static_cast<int>(column), Display(m_variableNames.at(column)));
        m_rows->SetColSize(static_cast<int>(column), FromDIP(180));
        wxArrayString choices;
        int ordinal = 0;
        for (const auto& value : m_variables.at(column).value("values", Json::array()))
        {
            choices.Add(Display(std::to_string(++ordinal) + ": " + SweepUi::Quantity(value)));
        }
        auto* attributes = new wxGridCellAttr();
        attributes->SetEditor(new wxGridCellChoiceEditor(choices));
        m_rows->SetColAttr(static_cast<int>(column), attributes);
    }
    m_rows->Enable(m_combination->GetSelection() == 2);
    m_loading = false;
}

void SweepDialog::ChangeSettingUnit(const std::string& id)
{
    if (m_loading || !Editable() || m_pending)
    {
        return;
    }
    auto& input = m_settings.at(id);
    const auto requested = Utf8(input.unit->GetStringSelection());
    const Json quantity = !input.quantityCurrent
                              ? Json{{"text", Utf8(input.text->GetValue())},
                                     {"unit", input.displayUnit},
                                     {"source_refs", input.quantity.value("source_refs", Json::array())}}
                              : input.quantity;
    input.unit->SetStringSelection(Display(input.displayUnit));
    Request("sweep.quantity", {{"expected_revision", m_revision}, {"quantity", quantity}, {"display_unit", requested}},
            false,
            [this, id](const Json& result)
            {
                auto& current = m_settings.at(id);
                m_loading = true;
                current.quantity = result.at("quantity");
                current.quantityCurrent = true;
                current.displayUnit = result.at("unit");
                current.text->ChangeValue(Display(result.at("text")));
                current.unit->SetStringSelection(Display(current.displayUnit));
                m_loading = false;
                if (current.dirty)
                {
                    Changed();
                }
            });
}

void SweepDialog::RefreshPorts()
{
    m_port->Clear();
    m_portIds.clear();
    Json ports = m_context.value("ports", Json::array());
    if (m_type->GetSelection() == 2 && m_datasets->GetSelection() >= 0)
    {
        ports = Json::array();
        const auto& descriptor = m_context.at("datasets").at(m_datasets->GetSelection()).at("descriptor");
        const auto ids = descriptor.value("port_ids", Json::array());
        const auto names = descriptor.value("port_names", Json::array());
        for (std::size_t index = 0; index < ids.size(); ++index)
        {
            const auto original = index < names.size() ? names.at(index) : Json(nullptr);
            ports.push_back({{"id", ids.at(index)},
                             {"name", original.is_string() && !original.get<std::string>().empty()
                                          ? original
                                          : Json("자료 포트 " + std::to_string(index + 1) + " (이름 미정)")}});
        }
    }
    for (const auto& port : ports)
    {
        m_portIds.push_back(port.at("id"));
        const auto name = port.value("name", Json(nullptr));
        m_port->Append(Display(name.is_string() && !name.get<std::string>().empty()
                                   ? name.get<std::string>()
                                   : "포트 " + std::to_string(m_portIds.size()) + " (이름 미정)"));
    }
    m_port->SetSelection(wxNOT_FOUND);
}

void SweepDialog::RefreshOptionalInputs()
{
    for (const auto& field : m_context.value("optional_numerical_fields", Json::array()))
    {
        const std::string id = field.at("id");
        auto found = m_settings.find(id);
        if (found == m_settings.end())
        {
            continue;
        }
        auto& input = found->second;
        input.eligible =
            id == "feature_subdivisions" ? m_featureSubdivisions->GetValue() : m_recordRadiation->GetValue();
        if (input.eligible && input.quantity.is_null())
        {
            input.quantity = field.at("quantity");
            input.displayUnit = field.value("display_unit", field.at("quantity").value("display_unit", "1"));
            input.text->ChangeValue(Display(field.at("text")));
            input.unit->SetStringSelection(Display(input.displayUnit));
        }
    }
    LoadCatalog();
    UpdateActions();
}

void SweepDialog::ChangeRadiationUnit(std::size_t index)
{
    if (m_loading || !Editable() || m_pending)
    {
        return;
    }
    auto& input = m_radiationFields.at(index);
    const auto requested = Utf8(input.unit->GetStringSelection());
    const auto quantity = input.dirty ? Json{{"text", Utf8(input.text->GetValue())},
                                             {"unit", input.displayUnit},
                                             {"source_refs", input.quantity.value("source_refs", Json::array())}}
                                      : input.quantity;
    input.unit->SetStringSelection(Display(input.displayUnit));
    Request("sweep.quantity", {{"expected_revision", m_revision}, {"quantity", quantity}, {"display_unit", requested}},
            false,
            [this, index](const Json& result)
            {
                auto& field = m_radiationFields.at(index);
                field.quantity = result.at("quantity");
                field.displayUnit = result.at("unit");
                field.text->ChangeValue(Display(result.at("text")));
                field.unit->SetStringSelection(Display(field.displayUnit));
                if (field.dirty)
                {
                    field.dirty = false;
                    m_radiationDirty = true;
                    Changed();
                }
            });
}

void SweepDialog::ShowRequestFailure(const Json& error)
{
    SetStatus(DiagnosticMessage(error));
    m_diagnostics->ChangeValue(Display(DiagnosticMessage(error)));
    m_review = nullptr;
    m_reviewInput = nullptr;
}

void SweepDialog::UpdateActions()
{
    if (!m_preview)
    {
        return;
    }
    const bool enabled = Editable() && !m_pending && !m_saved;
    m_pages->Enable(enabled);
    m_preview->Enable(enabled);
    m_create->Enable(enabled && !m_review.is_null() && m_review.value("can_create", false));
    m_close->Enable(!m_mutating);
    const bool selected = m_variableIndex >= 0 && static_cast<std::size_t>(m_variableIndex) < m_variables.size();
    const bool state = selected && m_variables.at(m_variableIndex).at("dimension") == "state";
    const bool range = selected && m_valueMode->GetSelection() == 1 && !state;
    m_addVariable->Enable(enabled && m_availableVariables->GetSelection() >= 0 && m_variables.size() < 8);
    m_removeVariable->Enable(enabled && selected);
    m_addValue->Enable(enabled && selected && !range);
    m_removeValue->Enable(enabled && selected && !range && m_values->GetSelection() >= 0);
    m_valueMode->Enable(enabled && selected && !state);
    m_valueText->Enable(enabled && selected && !state && !range);
    m_valueUnit->Enable(enabled && selected && !state);
    m_valueState->Enable(enabled && selected && state);
    for (auto* input : {m_rangeStart, m_rangeStop})
    {
        input->Enable(enabled && range);
    }
    m_rangeCount->Enable(enabled && range);
    m_datasets->Enable(enabled && m_type->GetSelection() == 2);
    m_circuits->Enable(enabled && m_type->GetSelection() == 2);
    m_port->Enable(enabled && m_explicitContext->GetValue());
    m_referencePlane->Enable(enabled && m_explicitContext->GetValue());
    const bool explicitRows = m_combination->GetSelection() == 2;
    m_rows->Enable(enabled && explicitRows);
    m_addRow->Enable(enabled && explicitRows && !m_variables.empty() && m_rows->GetNumberRows() < 128);
    m_removeRow->Enable(enabled && explicitRows && m_rows->GetNumberRows() > 0);
    for (const auto& setting : m_settings)
    {
        setting.second.text->Enable(enabled && m_type->GetSelection() != 2 && setting.second.eligible);
        setting.second.unit->Enable(enabled && m_type->GetSelection() != 2 && setting.second.eligible);
    }
    for (auto* option : {m_recordRadiation, m_recordLosses, m_featureSubdivisions})
    {
        option->Enable(enabled && m_type->GetSelection() != 2);
    }
    const bool radiation = enabled && m_type->GetSelection() != 2 && m_recordRadiation->GetValue();
    m_radiationCount->Enable(radiation);
    for (std::size_t index = 0; index < m_radiationFields.size(); ++index)
    {
        m_radiationFields[index].text->Enable(radiation &&
                                              index < static_cast<std::size_t>(m_radiationCount->GetValue()));
        m_radiationFields[index].unit->Enable(radiation &&
                                              index < static_cast<std::size_t>(m_radiationCount->GetValue()));
    }
}
