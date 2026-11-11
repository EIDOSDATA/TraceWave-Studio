/** @file @brief 명시적 층 두께와 기존 객체 대응, 포트 좌표 폼을 처리한다. */
#include "pcb_selection_dialog.h"
#include "pcb_selection_view_support.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/grid.h>
#include <wx/listbox.h>
#include <wx/notebook.h>
#include <wx/panel.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <algorithm>

namespace
{
const std::vector<std::string> Roles = {"conductor", "dielectric", "coating", "adhesive", "air"};
const std::vector<std::string> RoleNames = {"도체", "유전체", "코팅", "접착층", "공기"};

wxString RoleLabel(const std::string& role)
{
    const auto found = std::find(Roles.begin(), Roles.end(), role);
    return Display(found == Roles.end() ? role : RoleNames.at(static_cast<std::size_t>(found - Roles.begin())));
}

std::string RoleValue(const wxString& label)
{
    const auto found = std::find(RoleNames.begin(), RoleNames.end(), Utf8(label));
    if (found == RoleNames.end())
    {
        throw std::runtime_error("층 역할을 목록에서 선택하세요.");
    }
    return Roles.at(static_cast<std::size_t>(found - RoleNames.begin()));
}
}

wxPanel* PcbSelectionDialog::BuildLayersPage()
{
    auto* panel = new wxPanel(m_notebook);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    layout->Add(new wxStaticText(panel, wxID_ANY,
                                 Display("아래에서 위 순서입니다. 빈 두께는 미정이며 이후 층 위치도 미정입니다. 기존 "
                                         "패턴을 유지하려면 층 연결을 직접 선택하세요.")),
                0, wxEXPAND | wxALL, FromDIP(10));
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    m_manualButton = new wxButton(panel, wxID_ANY, Display("층 목록 직접 편집"));
    m_manualButton->SetName("pcb.manual");
    m_addLayer = new wxButton(panel, wxID_ANY, Display("유전체 층 추가"));
    m_addLayer->SetName("pcb.add_layer");
    m_removeLayer = new wxButton(panel, wxID_ANY, Display("선택 층 제거"));
    m_removeLayer->SetName("pcb.remove_layer");
    actions->Add(m_manualButton, 0, wxRIGHT, FromDIP(8));
    actions->Add(m_addLayer, 0, wxRIGHT, FromDIP(8));
    actions->Add(m_removeLayer);
    layout->Add(actions, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(10));
    m_layers = new wxGrid(panel, wxID_ANY);
    m_layers->SetName("pcb.layers");
    m_layers->CreateGrid(0, 6);
    const char* labels[] = {"층 이름", "역할", "두께 mm", "두께/참조 수정 이유", "기존 층 연결", "재료 연결"};
    const int widths[] = {150, 85, 100, 205, 235, 195};
    for (int column = 0; column < 6; ++column)
    {
        m_layers->SetColLabelValue(column, Display(labels[column]));
        m_layers->SetColSize(column, FromDIP(widths[column]));
    }
    m_layers->SetRowLabelSize(FromDIP(38));
    layout->Add(m_layers, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(10));
    auto* settings = new wxFlexGridSizer(2, FromDIP(8), FromDIP(8));
    settings->AddGrowableCol(1);
    settings->Add(new wxStaticText(panel, wxID_ANY, Display("직접 구성 이유")), 0, wxALIGN_CENTER_VERTICAL);
    m_layoutReason = new wxTextCtrl(panel, wxID_ANY);
    m_layoutReason->SetName("pcb.layout_reason");
    settings->Add(m_layoutReason, 1, wxEXPAND);
    settings->Add(new wxStaticText(panel, wxID_ANY, Display("아래쪽 기준 z (mm)")), 0, wxALIGN_CENTER_VERTICAL);
    m_zOrigin = new wxTextCtrl(panel, wxID_ANY);
    m_zOrigin->SetName("pcb.z_origin");
    m_zOrigin->SetHint(Display("생략하면 좌표 기준 0 mm"));
    settings->Add(m_zOrigin, 1, wxEXPAND);
    layout->Add(settings, 0, wxEXPAND | wxALL, FromDIP(10));
    panel->SetSizer(layout);
    m_layers->Bind(wxEVT_GRID_CELL_CHANGED,
                   [this](wxGridEvent& event)
                   {
                       Changed();
                       event.Skip();
                   });
    m_layers->Bind(wxEVT_GRID_EDITOR_SHOWN,
                   [this](wxGridEvent& event)
                   {
                       Changed();
                       event.Skip();
                   });
    m_layoutReason->Bind(wxEVT_TEXT,
                         [this](wxCommandEvent&)
                         {
                             Changed();
                         });
    m_zOrigin->Bind(wxEVT_TEXT,
                    [this](wxCommandEvent&)
                    {
                        Changed();
                    });
    m_manualButton->Bind(wxEVT_BUTTON,
                         [this](wxCommandEvent&)
                         {
                             UseManual();
                         });
    m_addLayer->Bind(wxEVT_BUTTON,
                     [this](wxCommandEvent&)
                     {
                         if (!m_manual || m_rows.size() >= 32)
                         {
                             return;
                         }
                         m_layers->SaveEditControlValue();
                         try
                         {
                             Json rows = ReadLayerRows();
                             rows.push_back({{"key", "manual-" + Uuid()},
                                             {"name", "새 유전체"},
                                             {"role", "dielectric"},
                                             {"thickness_mm", nullptr},
                                             {"existing_layer_id", nullptr},
                                             {"material_id", nullptr}});
                             PopulateLayers(rows, true);
                             Changed();
                         }
                         catch (const std::exception& error)
                         {
                             SetStatus(error.what());
                         }
                     });
    m_removeLayer->Bind(wxEVT_BUTTON,
                        [this](wxCommandEvent&)
                        {
                            const int row = m_layers->GetGridCursorRow();
                            if (m_manual && m_rows.size() > 1 && row >= 0)
                            {
                                m_rows.erase(m_rows.begin() + row);
                                m_layers->DeleteRows(row);
                                Changed();
                                UpdateControls();
                            }
                        });
    return panel;
}

/** @brief 화면의 기존 층은 명시적 연결을 보존하고 새 출처의 층은 추정 연결하지 않는다. */
void PcbSelectionDialog::PopulateLayers(const Json& rows, bool preserveExisting)
{
    m_loading = true;
    m_rows = rows;
    if (m_layers->GetNumberRows() > 0)
    {
        m_layers->DeleteRows(0, m_layers->GetNumberRows());
    }
    if (!rows.empty())
    {
        m_layers->AppendRows(static_cast<int>(rows.size()));
    }
    wxArrayString existing;
    existing.Add(Display("새 층"));
    m_layerIds = {""};
    m_layerLabels = {"새 층"};
    for (const auto& layer : m_context.at("layers"))
    {
        existing.Add(Display(std::to_string(existing.size()) + ". " + layer.at("name").get<std::string>() + " (") +
                     RoleLabel(layer.at("role")) + ")");
        m_layerIds.push_back(layer.at("id"));
        m_layerLabels.push_back(Utf8(existing.Last()));
    }
    wxArrayString roles;
    for (const auto& role : RoleNames)
    {
        roles.Add(Display(role));
    }
    for (std::size_t index = 0; index < rows.size(); ++index)
    {
        const int row = static_cast<int>(index);
        const auto& value = rows.at(index);
        m_layers->SetCellValue(row, 0, Display(value.at("name")));
        m_layers->SetCellEditor(row, 1, new wxGridCellChoiceEditor(roles, false));
        m_layers->SetCellValue(row, 1, RoleLabel(value.at("role")));
        m_layers->SetCellValue(row, 2, PcbView::Number(value.value("thickness_mm", Json(nullptr))));
        m_layers->SetCellValue(row, 3, Display(value.value("edit_reason", std::string())));
        m_layers->SetCellEditor(row, 4, new wxGridCellChoiceEditor(existing, false));
        std::string identifier;
        if (preserveExisting && value.contains("existing_layer_id") && value.at("existing_layer_id").is_string())
        {
            identifier = value.at("existing_layer_id");
        }
        const auto found = std::find(m_layerIds.begin(), m_layerIds.end(), identifier);
        m_layers->SetCellValue(
            row, 4, existing[found == m_layerIds.end() ? 0 : static_cast<std::size_t>(found - m_layerIds.begin())]);
        m_layers->SetReadOnly(row, 0, !m_manual);
        m_layers->SetReadOnly(row, 1, !m_manual);
        m_layers->SetReadOnly(row, 2, !m_manual && m_source.is_null());
        m_layers->SetReadOnly(row, 3, !m_manual && m_source.is_null());
        m_layers->SetReadOnly(row, 4, !m_manual && m_source.is_null());
    }
    m_layoutReason->Enable(m_manual);
    m_zOrigin->Enable(m_manual || !m_source.is_null());
    RefreshMaterialChoices();
    m_loading = false;
    UpdateControls();
}

void PcbSelectionDialog::UseManual()
{
    if (m_applying || m_disconnected)
    {
        return;
    }
    Json rows;
    try
    {
        m_layers->SaveEditControlValue();
        rows = ReadLayerRows();
    }
    catch (const std::exception& error)
    {
        SetStatus(error.what());
        return;
    }
    m_manual = true;
    if (rows.empty())
    {
        rows = Json::array();
        for (const auto& row : m_context.at("layers"))
        {
            Json value = row;
            value["key"] = row.at("id");
            value["existing_layer_id"] = row.at("id");
            rows.push_back(value);
        }
    }
    if (rows.empty())
    {
        rows.push_back({{"key", "manual-" + Uuid()},
                        {"name", "새 유전체"},
                        {"role", "dielectric"},
                        {"thickness_mm", nullptr},
                        {"existing_layer_id", nullptr},
                        {"material_id", nullptr}});
    }
    PopulateLayers(rows, true);
    Changed();
    m_notebook->SetSelection(1);
    SetStatus("층 목록을 직접 편집합니다. 아래에서 위 순서와 구성 이유를 명시하세요. 출처가 있으면 함께 보존합니다.");
}

/** @brief 재료 선택의 표시 라벨과 내부 식별자를 분리한다. */
void PcbSelectionDialog::RefreshMaterialChoices()
{
    wxArrayString labels;
    labels.Add(Display("재료 미정"));
    std::vector<std::string> values{""};
    for (const auto& material : m_context.at("materials"))
    {
        labels.Add(Display("기존 " + std::to_string(labels.size()) + ". " + material.at("name").get<std::string>()));
        values.push_back(material.at("id"));
    }
    for (const auto& material : m_materialSpecs)
    {
        labels.Add(Display("선택 " + std::to_string(labels.size()) + ". " + material.at("name").get<std::string>()));
        values.push_back(material.at("key"));
    }
    for (int row = 0; row < m_layers->GetNumberRows(); ++row)
    {
        std::string previous;
        const wxString text = m_layers->GetCellValue(row, 5);
        if (!text.empty())
        {
            const auto found = std::find(m_materialLabels.begin(), m_materialLabels.end(), Utf8(text));
            if (found != m_materialLabels.end())
            {
                previous = m_materialValues.at(static_cast<std::size_t>(found - m_materialLabels.begin()));
            }
        }
        else if (m_rows.at(static_cast<std::size_t>(row)).contains("material_id") &&
                 m_rows.at(static_cast<std::size_t>(row)).at("material_id").is_string())
        {
            previous = m_rows.at(static_cast<std::size_t>(row)).at("material_id");
        }
        const auto found = std::find(values.begin(), values.end(), previous);
        m_layers->SetCellEditor(row, 5, new wxGridCellChoiceEditor(labels, false));
        m_layers->SetCellValue(row, 5,
                               labels[found == values.end() ? 0 : static_cast<std::size_t>(found - values.begin())]);
    }
    m_materialValues = std::move(values);
    m_materialLabels.clear();
    for (const auto& label : labels)
    {
        m_materialLabels.push_back(Utf8(label));
    }
}

Json PcbSelectionDialog::ReadLayerRows() const
{
    Json rows = m_rows;
    for (std::size_t index = 0; index < rows.size(); ++index)
    {
        const int row = static_cast<int>(index);
        rows[index]["name"] = Utf8(m_layers->GetCellValue(row, 0));
        rows[index]["role"] = RoleValue(m_layers->GetCellValue(row, 1));
        rows[index]["thickness_mm"] = PcbView::Number(m_layers->GetCellValue(row, 2), "층 두께");
        rows[index]["edit_reason"] = Utf8(m_layers->GetCellValue(row, 3));
        for (int column : {4, 5})
        {
            const auto& labels = column == 4 ? m_layerLabels : m_materialLabels;
            const auto& values = column == 4 ? m_layerIds : m_materialValues;
            const auto found = std::find(labels.begin(), labels.end(), Utf8(m_layers->GetCellValue(row, column)));
            if (found == labels.end())
            {
                throw std::runtime_error("층과 재료 연결은 목록에서 선택하세요.");
            }
            const std::string value = values.at(static_cast<std::size_t>(found - labels.begin()));
            rows[index][column == 4 ? "existing_layer_id" : "material_id"] =
                value.empty() ? Json(nullptr) : Json(value);
        }
    }
    return rows;
}

/** @brief 화면에서 명시한 값만 API specification으로 만든다. */
Json PcbSelectionDialog::CollectSpecification()
{
    Json specification = {{"source", m_source},
                          {"materials", m_materialSpecs},
                          {"material_ids", m_materialIds},
                          {"material_assignments", Json::object()},
                          {"port_updates", CollectPorts()}};
    if (!m_catalogId.empty())
    {
        specification["catalog_id"] = m_catalogId;
    }
    if (m_manual)
    {
        specification["layers"] = Json::array();
        specification["layout_reason"] = PcbView::Reason(m_layoutReason->GetValue(), "직접 구성");
    }
    if (m_manual || !m_source.is_null())
    {
        specification["layer_ids"] = Json::object();
        specification["thickness_overrides"] = Json::object();
        const Json origin = PcbView::Number(m_zOrigin->GetValue(), "기준 z");
        if (!origin.is_null())
        {
            specification["z_origin_mm"] = origin;
        }
    }
    for (int row = 0; row < m_layers->GetNumberRows(); ++row)
    {
        const auto& original = m_rows.at(static_cast<std::size_t>(row));
        const std::string key = original.at("key");
        if (m_manual)
        {
            specification["layers"].push_back(
                {{"key", key},
                 {"name", Utf8(m_layers->GetCellValue(row, 0))},
                 {"role", RoleValue(m_layers->GetCellValue(row, 1))},
                 {"thickness_mm", PcbView::Number(m_layers->GetCellValue(row, 2), "층 두께")}});
            if (original.value("parameter_bound", false))
            {
                specification["thickness_overrides"][key] = {
                    {"value_mm", PcbView::Number(m_layers->GetCellValue(row, 2), "층 두께")},
                    {"reason",
                     PcbView::Reason(m_layers->GetCellValue(row, 3), "매개변수 참조를 직접값으로 바꾸는 이유")}};
            }
        }
        else if (!m_source.is_null())
        {
            const Json thickness = PcbView::Number(m_layers->GetCellValue(row, 2), "층 두께");
            if (thickness != original.value("thickness_mm", Json(nullptr)))
            {
                specification["thickness_overrides"][key] = {
                    {"value_mm", thickness}, {"reason", PcbView::Reason(m_layers->GetCellValue(row, 3), "두께 수정")}};
            }
        }
        for (int column : {4, 5})
        {
            const auto& labels = column == 4 ? m_layerLabels : m_materialLabels;
            const auto found = std::find(labels.begin(), labels.end(), Utf8(m_layers->GetCellValue(row, column)));
            if (found == labels.end())
            {
                throw std::runtime_error("기존 층과 재료는 제공된 목록에서 선택하세요.");
            }
            const auto selected = static_cast<std::size_t>(found - labels.begin());
            const std::string value =
                (column == 4 ? m_layerIds : m_materialValues).at(static_cast<std::size_t>(selected));
            if (column == 4 && (m_manual || !m_source.is_null()) && !value.empty())
            {
                specification["layer_ids"][key] = value;
            }
            if (column == 5)
            {
                specification["material_assignments"][key] = value.empty() ? Json(nullptr) : Json(value);
            }
        }
    }
    return specification;
}

wxPanel* PcbSelectionDialog::BuildPortsPage()
{
    auto* panel = new wxPanel(m_notebook);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    layout->Add(
        new wxStaticText(panel, wxID_ANY,
                         Display("층 위치를 바꿀 때 기존 포트 좌표를 확인하세요. 단위는 mm이며 빈칸은 미정입니다. "
                                 "이유만 입력해 같은 좌표를 명시적으로 확인할 수도 있습니다.\n"
                                 "좌표 변경 또는 확인 이유가 있는 행은 직접값으로 적용하여 매개변수 참조를 해제합니다. "
                                 "빈 이유의 미수정 행은 기존 참조를 보존합니다.")),
        0, wxEXPAND | wxALL, FromDIP(10));
    m_ports = new wxGrid(panel, wxID_ANY);
    m_ports->SetName("pcb.ports");
    m_ports->CreateGrid(static_cast<int>(m_context.at("ports").size()), 8);
    const char* labels[] = {"포트", "시작 X", "시작 Y", "시작 Z", "끝 X", "끝 Y", "끝 Z", "변경 이유"};
    for (int column = 0; column < 8; ++column)
    {
        m_ports->SetColLabelValue(column, Display(labels[column]));
        m_ports->SetColSize(column, FromDIP(column == 0 ? 145 : (column == 7 ? 250 : 85)));
    }
    for (std::size_t row = 0; row < m_context.at("ports").size(); ++row)
    {
        const auto& port = m_context.at("ports").at(row);
        m_ports->SetCellValue(
            static_cast<int>(row), 0,
            Display(port.at("name").get<std::string>() + (port.value("parameter_bound", false) ? " (매개변수)" : "")));
        m_ports->SetReadOnly(static_cast<int>(row), 0);
        for (int column = 1; column <= 6; ++column)
        {
            const auto& coordinates = port.at(column <= 3 ? "start_mm" : "stop_mm");
            m_ports->SetCellValue(static_cast<int>(row), column,
                                  coordinates.is_array() ? PcbView::Number(coordinates.at((column - 1) % 3))
                                                         : wxString());
        }
    }
    m_ports->Bind(wxEVT_GRID_CELL_CHANGED,
                  [this](wxGridEvent& event)
                  {
                      Changed();
                      event.Skip();
                  });
    m_ports->Bind(wxEVT_GRID_EDITOR_SHOWN,
                  [this](wxGridEvent& event)
                  {
                      Changed();
                      event.Skip();
                  });
    layout->Add(m_ports, 1, wxEXPAND | wxALL, FromDIP(10));
    panel->SetSizer(layout);
    return panel;
}

Json PcbSelectionDialog::CollectPorts() const
{
    Json result = Json::array();
    for (int row = 0; row < m_ports->GetNumberRows(); ++row)
    {
        Json start = Json::array();
        Json stop = Json::array();
        for (int axis = 0; axis < 3; ++axis)
        {
            start.push_back(PcbView::Number(m_ports->GetCellValue(row, 1 + axis), "포트 시작"));
            stop.push_back(PcbView::Number(m_ports->GetCellValue(row, 4 + axis), "포트 끝"));
        }
        const auto& original = m_context.at("ports").at(static_cast<std::size_t>(row));
        const Json oldStart =
            original.at("start_mm").is_array() ? original.at("start_mm") : Json::array({nullptr, nullptr, nullptr});
        const Json oldStop =
            original.at("stop_mm").is_array() ? original.at("stop_mm") : Json::array({nullptr, nullptr, nullptr});
        wxString reason = m_ports->GetCellValue(row, 7);
        reason.Trim(true).Trim(false);
        if (start != oldStart || stop != oldStop || !reason.empty())
        {
            result.push_back({{"id", original.at("id")},
                              {"start_mm", start},
                              {"stop_mm", stop},
                              {"reason", PcbView::Reason(m_ports->GetCellValue(row, 7), "포트 좌표 변경")}});
        }
    }
    return result;
}
