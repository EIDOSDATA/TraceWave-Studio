/** @file @brief 교정 적용 범위와 근거 참조를 명시 선택으로 편집한다. */
#include "measurement_collection_dialog.h"
#include "measurement_model.h"
#include "measurement_quantity_group.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/checklst.h>
#include <wx/choice.h>
#include <wx/dialog.h>
#include <wx/grid.h>
#include <wx/msgdlg.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <algorithm>
#include <iomanip>
#include <sstream>

namespace
{
std::string NumberText(const Json& value)
{
    if (!value.is_number())
    {
        return "";
    }
    std::ostringstream text;
    text << std::setprecision(17) << value.get<double>();
    return text.str();
}
Json LeafValue(const Json& value)
{
    return value.is_object() ? value.value("value", Json(nullptr)) : Json(nullptr);
}
Json Leaf(const Json& value, int evidence, const Json& original)
{
    return {{"value", value},
            {"evidence", MeasurementUi::Evidence(evidence)},
            {"source_refs", original.is_object() ? original.value("source_refs", Json::array()) : Json::array()}};
}
}

MeasurementCollectionEdit EditMeasurementCollection(wxWindow* parent, const std::string& key, const Json& current,
                                                    const Json& context, DialogGateway gateway)
{
    if (key == "uncertainty")
    {
        return EditMeasurementUncertainty(parent, current, context, gateway);
    }
    if (key == "external_processing")
    {
        return EditMeasurementProcessing(parent, current, context);
    }
    wxDialog dialog(parent, wxID_ANY, Display("측정 적용 범위와 근거"), wxDefaultPosition,
                    parent->FromDIP(wxSize(760, 580)), wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* notice = new wxStaticText(
        &dialog, wxID_ANY,
        Display("선택하지 않은 값은 미정입니다. 교정 조건의 선언은 원문 데이터의 기준면을 보정하지 않습니다."));
    notice->Wrap(parent->FromDIP(700));
    layout->Add(notice, 0, wxEXPAND | wxALL, parent->FromDIP(12));
    auto* evidence = new wxChoice(&dialog, wxID_ANY);
    for (const auto* label : {"미정", "계획", "명시", "제출 근거"})
    {
        evidence->Append(Display(label));
    }
    evidence->SetSelection(MeasurementUi::Evidence(current));
    layout->Add(evidence, 0, wxLEFT | wxRIGHT | wxBOTTOM, parent->FromDIP(12));
    const auto descriptor = context.value("descriptor", Json::object());
    const auto ports = descriptor.value("port_ids", Json::array());
    const auto names = descriptor.value("port_names", Json::array());
    const auto value = LeafValue(current);
    wxCheckListBox* list = nullptr;
    wxGrid* grid = nullptr;
    wxTextCtrl* start = nullptr;
    wxTextCtrl* stop = nullptr;
    wxChoice* units = nullptr;
    Json choices = Json::array();
    bool edited = false;
    std::shared_ptr<MeasurementQuantityGroup> quantities;
    evidence->Bind(wxEVT_CHOICE,
                   [&edited](wxCommandEvent&)
                   {
                       edited = true;
                   });
    const bool portMode = key == "calibration.port_ids" || key == "calibration.reference_planes";
    if (portMode)
    {
        if (ports.empty())
        {
            wxMessageBox(
                Display(
                    "원문 자료의 포트를 먼저 조회하세요. 가져오기에서는 파일 검토 후 시료와 교정 탭으로 돌아오세요."),
                Display("자료 포트 필요"), wxOK | wxICON_INFORMATION, parent);
            return {};
        }
        grid = new wxGrid(&dialog, wxID_ANY);
        grid->CreateGrid(static_cast<int>(ports.size()), key == "calibration.port_ids" ? 2 : 3);
        grid->SetColLabelValue(0, Display("적용"));
        grid->SetColLabelValue(1, Display("자료 포트"));
        grid->SetColSize(0, parent->FromDIP(70));
        grid->SetColSize(1, parent->FromDIP(240));
        if (grid->GetNumberCols() == 3)
        {
            grid->SetColLabelValue(2, Display("명시 교정 기준면"));
            grid->SetColSize(2, parent->FromDIP(320));
        }
        for (std::size_t index = 0; index < ports.size(); ++index)
        {
            const int row = static_cast<int>(index);
            grid->SetCellEditor(row, 0, new wxGridCellBoolEditor());
            grid->SetCellRenderer(row, 0, new wxGridCellBoolRenderer());
            grid->SetCellValue(row, 1,
                               Display(index < names.size() && names.at(index).is_string()
                                           ? names.at(index).get<std::string>()
                                           : "자료 포트 " + std::to_string(index + 1)));
            grid->SetReadOnly(row, 1);
            if (value.is_array())
            {
                for (const auto& item : value)
                {
                    if (item == ports.at(index) ||
                        (item.is_object() && item.value("port_id", Json(nullptr)) == ports.at(index)))
                    {
                        grid->SetCellValue(row, 0, "1");
                        if (grid->GetNumberCols() == 3 && item.is_object())
                        {
                            grid->SetCellValue(row, 2, Display(item.value("reference_plane", std::string())));
                        }
                    }
                }
            }
        }
        grid->Bind(wxEVT_GRID_CELL_CHANGED,
                   [&edited](wxGridEvent& event)
                   {
                       edited = true;
                       event.Skip();
                   });
        layout->Add(grid, 1, wxEXPAND | wxALL, parent->FromDIP(12));
    }
    else if (key == "calibration.frequency_range_hz")
    {
        auto* fields = new wxFlexGridSizer(2, parent->FromDIP(8), parent->FromDIP(12));
        fields->AddGrowableCol(1, 1);
        start = new wxTextCtrl(&dialog, wxID_ANY);
        stop = new wxTextCtrl(&dialog, wxID_ANY);
        units = new wxChoice(&dialog, wxID_ANY);
        for (const auto* unit : {"Hz", "kHz", "MHz", "GHz"})
        {
            units->Append(unit);
        }
        units->SetSelection(0);
        if (value.is_array() && value.size() == 2)
        {
            start->ChangeValue(Display(NumberText(value.at(0))));
            stop->ChangeValue(Display(NumberText(value.at(1))));
        }
        else if (current.is_object() && current.value("start", Json(nullptr)).is_object())
        {
            start->ChangeValue(Display(current.at("start").value("text", std::string())));
            stop->ChangeValue(Display(current.at("stop").value("text", std::string())));
            units->SetStringSelection(Display(current.at("start").value("unit", std::string("Hz"))));
            evidence->SetSelection(MeasurementUi::Evidence(current));
        }
        quantities = MeasurementQuantityGroup::Create(
            &dialog, units,
            {{"calibration.frequency_range_hz.start", start, value.is_array() ? value.at(0) : Json(nullptr),
              current.is_object() ? current.value("start", Json(nullptr)) : Json(nullptr)},
             {"calibration.frequency_range_hz.stop", stop, value.is_array() ? value.at(1) : Json(nullptr),
              current.is_object() ? current.value("stop", Json(nullptr)) : Json(nullptr)}},
            gateway);
        quantities->onEdited = [&edited]()
        {
            edited = true;
        };
        quantities->onStatus = [&dialog](const std::string& message)
        {
            wxMessageBox(Display(message), Display("주파수 표시 단위"), wxOK | wxICON_INFORMATION, &dialog);
        };
        for (const auto& item : std::vector<std::pair<const char*, wxWindow*>>{
                 {"시작 주파수", start}, {"끝 주파수", stop}, {"입력 단위", units}})
        {
            fields->Add(new wxStaticText(&dialog, wxID_ANY, Display(item.first)), 0, wxALIGN_CENTER_VERTICAL);
            fields->Add(item.second, 1, wxEXPAND);
        }
        layout->Add(fields, 0, wxEXPAND | wxALL, parent->FromDIP(12));
        layout->AddStretchSpacer();
    }
    else
    {
        choices = context.value("attachments", Json::array());
        if (key == "specimen.design_snapshot")
        {
            choices = context.value("snapshots", Json::array());
        }
        list = new wxCheckListBox(&dialog, wxID_ANY);
        list->Bind(wxEVT_CHECKLISTBOX,
                   [&edited, list, key](wxCommandEvent& event)
                   {
                       edited = true;
                       if (key == "specimen.design_snapshot" && list->IsChecked(event.GetInt()))
                       {
                           for (unsigned int index = 0; index < list->GetCount(); ++index)
                           {
                               if (index != static_cast<unsigned int>(event.GetInt()))
                               {
                                   list->Check(index, false);
                               }
                           }
                       }
                   });
        for (const auto& item : choices)
        {
            const int row = list->Append(Display(item.value("name", item.value("label", std::string("보존 근거")))));
            const auto original = key == "attachments" ? current : value;
            if (key == "specimen.design_snapshot" && original.is_object() &&
                original.value("snapshot_id", Json(nullptr)) == item.value("id", Json(nullptr)) &&
                original.value("content_hash", Json(nullptr)) == item.value("content_hash", Json(nullptr)))
            {
                list->Check(row);
            }
            if (original.is_array())
            {
                for (const auto& reference : original)
                {
                    if (reference == item || reference == item.value("artifact", Json(nullptr)))
                    {
                        list->Check(row);
                    }
                }
            }
        }
        layout->Add(list, 1, wxEXPAND | wxALL, parent->FromDIP(12));
        if (choices.empty())
        {
            layout->Add(new wxStaticText(
                            &dialog, wxID_ANY,
                            Display("먼저 근거 파일을 보관하세요. 아직 기록에 연결하지 않은 원문도 별도 보존됩니다.")),
                        0, wxEXPAND | wxALL, parent->FromDIP(12));
        }
    }
    if (key == "attachments")
    {
        evidence->Hide();
    }
    layout->Add(dialog.CreateButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, parent->FromDIP(12));
    dialog.SetSizer(layout);
    dialog.CentreOnParent();
    if (dialog.ShowModal() != wxID_OK)
    {
        return {};
    }
    if (!edited)
    {
        return {};
    }
    if (grid)
    {
        if (grid->IsCellEditControlShown())
        {
            grid->SaveEditControlValue();
        }
        Json selected = Json::array();
        for (std::size_t index = 0; index < ports.size(); ++index)
        {
            if (grid->GetCellValue(static_cast<int>(index), 0) == "1")
            {
                selected.push_back(
                    grid->GetNumberCols() == 2
                        ? ports.at(index)
                        : Json{{"port_id", ports.at(index)},
                               {"reference_plane", Utf8(grid->GetCellValue(static_cast<int>(index), 2))}});
            }
        }
        return {true, false, Leaf(selected, evidence->GetSelection(), current)};
    }
    if (start)
    {
        if (start->IsEmpty() && stop->IsEmpty())
        {
            return {true, false, nullptr};
        }
        if (quantities && !quantities->Edited() && value.is_array())
        {
            return {true, false, Leaf(value, evidence->GetSelection(), current)};
        }
        return {true,
                true,
                {{"start", quantities->Input(0)},
                 {"stop", quantities->Input(1)},
                 {"evidence", MeasurementUi::Evidence(evidence->GetSelection())},
                 {"source_refs", current.is_object() ? current.value("source_refs", Json::array()) : Json::array()}}};
    }
    Json selected = Json::array();
    for (std::size_t index = 0; index < choices.size(); ++index)
    {
        if (list->IsChecked(static_cast<unsigned int>(index)))
        {
            selected.push_back(key == "attachments" ? choices.at(index)
                                                    : choices.at(index).value("artifact", choices.at(index)));
        }
    }
    if (key == "specimen.design_snapshot")
    {
        Json snapshot = nullptr;
        for (std::size_t index = 0; index < choices.size(); ++index)
        {
            if (list->IsChecked(static_cast<unsigned int>(index)))
            {
                snapshot = {{"snapshot_id", choices.at(index).at("id")},
                            {"content_hash", choices.at(index).at("content_hash")}};
            }
        }
        return {true, false, snapshot.is_null() ? Json(nullptr) : Leaf(snapshot, evidence->GetSelection(), current)};
    }
    return {true, false, key == "attachments" ? selected : Leaf(selected, evidence->GetSelection(), current)};
}
