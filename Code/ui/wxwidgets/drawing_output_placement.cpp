/** @file @brief 선택한 치수의 종이 좌표와 수동 고정 해제를 기술 도면에 연결한다. */
#include "drawing_output_view.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/dialog.h>
#include <wx/msgdlg.h>
#include <wx/sizer.h>
#include <wx/spinctrl.h>
#include <wx/stattext.h>
#include <algorithm>

namespace
{
/** @brief 동일 원본이라도 다른 뷰의 수동 위치를 독립적으로 선택한다. */
bool SameDimension(const Json& stored, const Json& view, const Json& item)
{
    return stored.at("view_id") == view && stored.at("source_id") == item.at("source_id") &&
           stored.at("key") == item.at("key");
}
}

Json DrawingOutputView::CurrentAnnotation() const
{
    Json result = m_annotation;
    if (result.is_object())
    {
        auto placement = result.value("placement", Json{{"profile", "rfad.drawing-placement/0.1"}, {"pins", Json::array()}});
        placement["paper"] = {{"sheet", m_sheet->GetSelection() == 0 ? "A4" : "A3"},
                              {"orientation", m_orientation->GetSelection() == 0 ? "landscape" : "portrait"},
                              {"scale", m_scale->GetValue()}};
        result["placement"] = std::move(placement);
    }
    return result;
}

void DrawingOutputView::MoveDimension(const Json& item, const Json& point)
{
    if (!m_available || !m_annotation.is_object() || !m_placements.is_object())
    {
        return;
    }
    auto candidate = CurrentAnnotation();
    auto& pins = candidate.at("placement").at("pins");
    const auto& view = candidate.at("view");
    const Json viewId = view.contains("layer_id") ? view.at("layer_id") : view.at("kind");
    const auto found = std::find_if(pins.begin(), pins.end(),
                                    [&](const Json& row)
                                    {
                                        return SameDimension(row, viewId, item);
                                    });
    if (point.is_null())
    {
        if (found == pins.end())
        {
            return;
        }
        pins.erase(found);
    }
    else
    {
        const auto& limit = item.at("pin_bounds_mm");
        const auto x = std::clamp(point.at(0).get<double>(), limit.at(0).get<double>(), limit.at(2).get<double>());
        const auto y = std::clamp(point.at(1).get<double>(), limit.at(1).get<double>(), limit.at(3).get<double>());
        const Json pin{{"view_id", viewId}, {"source_id", item.at("source_id")}, {"key", item.at("key")},
                       {"point_mm", Json::array({x, y})}};
        if (found != pins.end())
        {
            if (*found == pin)
            {
                return;
            }
            *found = pin;
        }
        else if (pins.size() < 256)
        {
            pins.push_back(pin);
        }
        else
        {
            wxMessageBox(Display("수동 위치는 최대 256개까지 저장할 수 있습니다."), Display("도면 치수 위치"),
                         wxOK | wxICON_INFORMATION, this);
            return;
        }
    }
    m_annotation = std::move(candidate);
    Changed();
    if (onPreview)
    {
        onPreview();
    }
}

void DrawingOutputView::EditPlacement()
{
    if (!m_placements.is_object() || m_placements.at("items").empty())
    {
        return;
    }
    const auto rows = m_placements.at("items");
    const auto annotation = CurrentAnnotation();
    const auto& view = annotation.at("view");
    const Json viewId = view.contains("layer_id") ? view.at("layer_id") : view.at("kind");
    const auto& pins = annotation.at("placement").at("pins");
    wxDialog dialog(this, wxID_ANY, Display("도면 치수 위치"), wxDefaultPosition, wxDefaultSize,
                    wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    StudioTheme::BindSurface(dialog);
    auto* body = new wxBoxSizer(wxVERTICAL);
    body->Add(new wxStaticText(&dialog, wxID_ANY, Display("치수")), 0, wxLEFT | wxRIGHT | wxTOP, dialog.FromDIP(14));
    auto* choice = new wxChoice(&dialog, wxID_ANY);
    choice->SetName(Display("이동할 치수"));
    for (const auto& row : rows)
    {
        choice->Append(Display(row.at("title").get<std::string>() + " / " + row.at("label").get<std::string>() +
                               (row.at("pinned").get<bool>() ? " / 수동 고정" : "")));
    }
    choice->SetSelection(0);
    choice->SetMinSize(dialog.FromDIP(wxSize(465, -1)));
    body->Add(choice, 0, wxEXPAND | wxLEFT | wxRIGHT | wxTOP, dialog.FromDIP(14));

    auto* coordinates = new wxFlexGridSizer(2, dialog.FromDIP(8), dialog.FromDIP(12));
    coordinates->AddGrowableCol(1);
    const auto coordinate = [&](const char* label)
    {
        coordinates->Add(new wxStaticText(&dialog, wxID_ANY, Display(label)), 0, wxALIGN_CENTER_VERTICAL);
        auto* input = new wxSpinCtrlDouble(&dialog, wxID_ANY, "0", wxDefaultPosition, wxDefaultSize, wxSP_ARROW_KEYS,
                                           0, 420, 0, 0.5);
        input->SetName(Display(label));
        input->SetDigits(3);
        coordinates->Add(input, 1, wxEXPAND);
        return input;
    };
    auto* x = coordinate("종이 X (mm)");
    auto* y = coordinate("종이 Y (mm)");
    body->Add(coordinates, 0, wxEXPAND | wxALL, dialog.FromDIP(14));

    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    auto* reset = new wxButton(&dialog, wxID_REMOVE, Display("자동 위치로 복귀"));
    auto* cancel = new wxButton(&dialog, wxID_CANCEL, Display("취소"));
    auto* apply = new wxButton(&dialog, wxID_OK, Display("위치 고정"));
    StudioTheme::Button(*apply, true);
    actions->AddStretchSpacer();
    for (auto* button : {reset, cancel, apply})
    {
        actions->Add(button, 0, wxLEFT, dialog.FromDIP(8));
    }
    body->Add(actions, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, dialog.FromDIP(14));

    const auto update = [&]()
    {
        const auto& selected = rows.at(choice->GetSelection());
        const auto& limits = selected.at("pin_bounds_mm");
        const auto& point = selected.at("point_mm");
        x->SetRange(limits.at(0), limits.at(2));
        y->SetRange(limits.at(1), limits.at(3));
        x->SetValue(point.at(0).get<double>());
        y->SetValue(point.at(1).get<double>());
        reset->Enable(std::any_of(pins.begin(), pins.end(),
                                   [&](const Json& pin)
                                   {
                                       return SameDimension(pin, viewId, selected);
                                   }));
    };
    choice->Bind(wxEVT_CHOICE,
                 [&](wxCommandEvent&)
                 {
                     update();
                 });
    reset->Bind(wxEVT_BUTTON,
                [&dialog](wxCommandEvent&)
                {
                    dialog.EndModal(wxID_REMOVE);
                });
    update();
    dialog.SetSizerAndFit(body);
    dialog.SetMinSize(dialog.GetSize());
    apply->SetDefault();
    choice->SetFocus();
    const int result = dialog.ShowModal();
    if (result == wxID_OK || result == wxID_REMOVE)
    {
        MoveDimension(rows.at(choice->GetSelection()),
                      result == wxID_OK ? Json::array({x->GetValue(), y->GetValue()}) : Json(nullptr));
    }
}
