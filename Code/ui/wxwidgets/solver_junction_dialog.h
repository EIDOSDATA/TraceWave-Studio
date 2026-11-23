/** @file @brief 해석에 포함한 비아와 등록 재료를 이름으로 선택하여 유한 접합층을 편집한다. */
#pragma once

#include "studio_support.h"
#include "studio_theme.h"
#include <cmath>
#include <optional>
#include <wx/wx.h>

/** @brief 낮은 Z 또는 높은 Z 끝에 지정한 재료와 실제 두께를 독립적으로 관리한다. */
inline std::optional<Json> EditSolverJunctions(wxWindow* owner, const Json& catalog, Json rows)
{
    wxDialog dialog(owner, wxID_ANY, Display("PTH 접합층"), wxDefaultPosition, wxDefaultSize,
                    wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    StudioTheme::BindSurface(dialog);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* existing = new wxListBox(&dialog, wxID_ANY);
    existing->SetName("solver.junctions.list");
    layout->Add(existing, 1, wxEXPAND | wxALL, dialog.FromDIP(8));
    auto* fields = new wxFlexGridSizer(2, dialog.FromDIP(5), dialog.FromDIP(8));
    fields->AddGrowableCol(1);
    auto field = [&](const char* label, wxWindow* control)
    {
        fields->Add(new wxStaticText(&dialog, wxID_ANY, Display(label)), 0, wxALIGN_CENTER_VERTICAL);
        fields->Add(control, 1, wxEXPAND);
    };
    auto* via = new wxChoice(&dialog, wxID_ANY);
    auto* end = new wxChoice(&dialog, wxID_ANY);
    auto* material = new wxChoice(&dialog, wxID_ANY);
    auto* thickness = new wxTextCtrl(&dialog, wxID_ANY);
    Json vias = Json::array();
    const auto materials = catalog.value("junction_materials", Json::array());
    for (const auto& row : catalog.value("local_mesh_targets", Json::array()))
    {
        if (row.value("kind", std::string{}) == "via")
        {
            vias.push_back(row);
            via->Append(Display(row.at("name").get<std::string>()));
        }
    }
    for (const auto& row : materials)
    {
        material->Append(Display(row.at("name").get<std::string>()));
    }
    end->Append(Display("낮은 Z 끝"));
    end->Append(Display("높은 Z 끝"));
    field("비아", via);
    field("배럴 끝", end);
    field("접합 재료", material);
    field("배럴 안쪽 접합 두께 (mm)", thickness);
    layout->Add(fields, 0, wxEXPAND | wxALL, dialog.FromDIP(8));
    auto* commands = new wxBoxSizer(wxHORIZONTAL);
    auto* apply = new wxButton(&dialog, wxID_ANY, Display("추가 / 변경"));
    auto* remove = new wxButton(&dialog, wxID_ANY, Display("선택 삭제"));
    commands->Add(apply, 0, wxRIGHT, dialog.FromDIP(6));
    commands->Add(remove);
    layout->Add(commands, 0, wxALL, dialog.FromDIP(8));
    auto find = [](const Json& pool, const Json& id) -> int
    {
        for (std::size_t index = 0; index < pool.size(); ++index)
        {
            if (pool.at(index).at("id") == id)
            {
                return static_cast<int>(index);
            }
        }
        return wxNOT_FOUND;
    };
    auto refresh = [&]()
    {
        existing->Clear();
        for (const auto& row : rows)
        {
            const int v = find(vias, row.at("via_id"));
            const int m = find(materials, row.at("material_id"));
            const auto vName = v == wxNOT_FOUND ? Display(row.at("via_id").get<std::string>()) : via->GetString(v);
            const auto mName = m == wxNOT_FOUND ? Display(row.at("material_id").get<std::string>()) : material->GetString(m);
            existing->Append(vName + " / " + end->GetString(row.at("end") == "lower" ? 0 : 1) + " / " + mName
                             + wxString::Format(" / %.12g mm", row.at("thickness_mm").get<double>()));
        }
        remove->Disable();
    };
    refresh();
    existing->Bind(wxEVT_LISTBOX, [&](wxCommandEvent&)
    {
        const auto& row = rows.at(existing->GetSelection());
        via->SetSelection(find(vias, row.at("via_id")));
        end->SetSelection(row.at("end") == "lower" ? 0 : 1);
        material->SetSelection(find(materials, row.at("material_id")));
        thickness->ChangeValue(wxString::Format("%.15g", row.at("thickness_mm").get<double>()));
        remove->Enable();
    });
    remove->Bind(wxEVT_BUTTON, [&](wxCommandEvent&)
    {
        const int index = existing->GetSelection();
        if (index != wxNOT_FOUND)
        {
            rows.erase(rows.begin() + index);
            refresh();
        }
    });
    apply->Bind(wxEVT_BUTTON, [&](wxCommandEvent&)
    {
        double value = 0;
        if (via->GetSelection() == wxNOT_FOUND || end->GetSelection() == wxNOT_FOUND
            || material->GetSelection() == wxNOT_FOUND || !thickness->GetValue().ToDouble(&value)
            || !std::isfinite(value) || value < 0.0002 || value >= 1000)
        {
            wxMessageBox(Display("비아, 배럴 끝, 재료를 선택하고 0.0002 mm 이상 1000 mm 미만의 두께를 입력하세요."),
                         dialog.GetTitle(), wxOK | wxICON_INFORMATION, &dialog);
            return;
        }
        Json next{{"via_id", vias.at(via->GetSelection()).at("id")}, {"end", end->GetSelection() == 0 ? "lower" : "upper"},
                  {"material_id", materials.at(material->GetSelection()).at("id")}, {"thickness_mm", value}};
        for (auto& row : rows)
        {
            if (row.at("via_id") == next.at("via_id") && row.at("end") == next.at("end"))
            {
                row = next;
                refresh();
                return;
            }
        }
        rows.push_back(next);
        refresh();
    });
    layout->Add(dialog.CreateSeparatedButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, dialog.FromDIP(8));
    dialog.SetSizer(layout);
    dialog.SetMinSize(dialog.FromDIP(wxSize(510, 390)));
    dialog.Fit();
    dialog.CentreOnParent();
    if (dialog.ShowModal() == wxID_OK)
    {
        return rows;
    }
    return std::nullopt;
}
