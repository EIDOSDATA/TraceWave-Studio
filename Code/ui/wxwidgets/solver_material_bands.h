/** @file @brief 등록된 재료 이름과 직접 주파수 구간으로 대역별 물성의 출처를 지정한다. */
#pragma once

#include "studio_support.h"
#include "studio_theme.h"
#include <algorithm>
#include <cmath>
#include <optional>
#include <wx/grid.h>
#include <wx/wx.h>

/** @brief 비어 있는 선택은 유지하고 신뢰할 수 있는 물성 목록에서 표시 이름으로 매핑한다. */
inline std::optional<Json> EditSolverMaterialBands(wxWindow* owner, const Json& materials, const Json& rows)
{
    wxDialog dialog(owner, wxID_ANY, Display("대역별 재료"), wxDefaultPosition, wxDefaultSize,
                    wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    StudioTheme::ApplyTypography(dialog);
    StudioTheme::BindSurface(dialog);
    auto* root = new wxBoxSizer(wxVERTICAL);
    wxArrayString choices;
    for (const auto& m : materials)
    {
        choices.Add(Display(m.at("name").get<std::string>() + ", " + m.at("id").get<std::string>()));
    }
    auto* grid = new wxGrid(&dialog, wxID_ANY);
    grid->SetName("solver.material_bands.grid");
    grid->CreateGrid(static_cast<int>(rows.size()), 4);
    grid->SetColLabelValue(0, Display("설계 재료"));
    grid->SetColLabelValue(1, Display("출처 재료"));
    grid->SetColLabelValue(2, Display("시작 (Hz)"));
    grid->SetColLabelValue(3, Display("끝 (Hz)"));
    grid->SetRowLabelSize(dialog.FromDIP(36));
    for (int col = 0; col < 4; ++col)
    {
        grid->SetColSize(col, dialog.FromDIP(col < 2 ? 232 : 128));
        if (col < 2)
        {
            auto* attr = new wxGridCellAttr();
            attr->SetEditor(new wxGridCellChoiceEditor(choices, false));
            grid->SetColAttr(col, attr);
        }
    }
    auto display = [&](const Json& id)
    {
        for (std::size_t j = 0; j < materials.size(); ++j)
        {
            if (materials.at(j).at("id") == id)
            {
                return choices[j];
            }
        }
        return Display(id.get<std::string>());
    };
    for (std::size_t i = 0; i < rows.size(); ++i)
    {
        const auto& row = rows.at(i);
        const int r = static_cast<int>(i);
        grid->SetCellValue(r, 0, display(row.at("material_id")));
        grid->SetCellValue(r, 1, display(row.at("source_material_id")));
        grid->SetCellValue(r, 2, wxString::Format("%.17g", row.at("start_hz").get<double>()));
        grid->SetCellValue(r, 3, wxString::Format("%.17g", row.at("stop_hz").get<double>()));
    }
    root->Add(grid, 1, wxEXPAND | wxALL, dialog.FromDIP(8));
    auto* commands = new wxBoxSizer(wxHORIZONTAL);
    auto* add = new wxButton(&dialog, wxID_ANY, Display("구간 추가"));
    auto* remove = new wxButton(&dialog, wxID_ANY, Display("현재 행 삭제"));
    commands->Add(add, 0, wxRIGHT, dialog.FromDIP(6));
    commands->Add(remove);
    root->Add(commands, 0, wxALL, dialog.FromDIP(8));
    add->Bind(wxEVT_BUTTON, [&](wxCommandEvent&)
    {
        if (grid->GetNumberRows() < 64)
        {
            grid->AppendRows();
            const int row = grid->GetNumberRows() - 1;
            grid->SetGridCursor(row, 0);
            grid->MakeCellVisible(row, 0);
        }
    });
    remove->Bind(wxEVT_BUTTON, [&](wxCommandEvent&)
    {
        const int row = grid->GetGridCursorRow();
        if (row >= 0 && row < grid->GetNumberRows())
        {
            grid->DeleteRows(row);
        }
    });
    Json edited = Json::array();
    dialog.Bind(wxEVT_BUTTON, [&](wxCommandEvent&)
    {
        grid->SaveEditControlValue();
        edited = Json::array();
        for (int row = 0; row < grid->GetNumberRows(); ++row)
        {
            const int target = choices.Index(grid->GetCellValue(row, 0));
            const int source = choices.Index(grid->GetCellValue(row, 1));
            double low = 0, high = 0;
            if (target < 0 || source < 0 || !grid->GetCellValue(row, 2).ToDouble(&low) ||
                !grid->GetCellValue(row, 3).ToDouble(&high) || !std::isfinite(low) || !std::isfinite(high)
                || low < 1e6 || low >= high || high > 50e9)
            {
                grid->SetGridCursor(row, target < 0 ? 0 : source < 0 ? 1 : 2);
                wxMessageBox(Display("두 재료와 1 MHz~50 GHz 안의 시작과 끝 주파수를 확인하세요."),
                             dialog.GetTitle(), wxOK | wxICON_INFORMATION, &dialog);
                return;
            }
            const auto& id = materials.at(target).at("id");
            if (std::any_of(edited.begin(), edited.end(), [&](const Json& prior)
                { return prior.at("material_id") == id && prior.at("start_hz").get<double>() < high && low < prior.at("stop_hz").get<double>(); }))
            {
                grid->SetGridCursor(row, 2);
                wxMessageBox(Display("동일한 설계 재료에 겹치는 주파수 구간이 있습니다."), dialog.GetTitle(), wxOK, &dialog);
                return;
            }
            edited.push_back({{"material_id", id}, {"source_material_id", materials.at(source).at("id")},
                              {"start_hz", low}, {"stop_hz", high}});
        }
        dialog.EndModal(wxID_OK);
    }, wxID_OK);
    root->Add(dialog.CreateSeparatedButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, dialog.FromDIP(8));
    dialog.SetSizer(root);
    dialog.SetMinSize(dialog.FromDIP(wxSize(830, 330)));
    dialog.Fit();
    dialog.CentreOnParent();
    if (dialog.ShowModal() == wxID_OK)
    {
        return edited;
    }
    return std::nullopt;
}
