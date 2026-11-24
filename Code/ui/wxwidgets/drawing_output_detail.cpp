/** @file @brief 상세 뷰의 도체층과 표시 영역을 native 입력으로 명시한다. */
#include "drawing_output_view.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/checklst.h>
#include <wx/dialog.h>
#include <wx/msgdlg.h>
#include <wx/sizer.h>
#include <wx/spinctrl.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <array>

void DrawingOutputView::AddDetail()
{
    wxDialog dialog(this, wxID_ANY, Display("상세 뷰 영역"), wxDefaultPosition, FromDIP(wxSize(440, 450)),
                    wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    StudioTheme::ApplyTypography(dialog);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* note = new wxStaticText(
        &dialog, wxID_ANY,
        Display("고정 입력의 실제 mm 좌표 영역을 지정하세요.\n원점과 권장 급전 치수를 자동으로 정하지 않습니다."));
    layout->Add(note, 0, wxALL | wxEXPAND, FromDIP(12));
    auto* form = new wxFlexGridSizer(2, FromDIP(8), FromDIP(8));
    form->AddGrowableCol(1);
    form->Add(new wxStaticText(&dialog, wxID_ANY, Display("도체층")), 0, wxALIGN_CENTER_VERTICAL);
    auto* layer = new wxChoice(&dialog, wxID_ANY);
    std::vector<std::string> ids;
    for (std::size_t index = 0; index < m_viewValues.size(); ++index)
    {
        if (m_viewValues[index].value("kind", "") == "layer")
        {
            layer->Append(m_views->GetString(index));
            ids.push_back(m_viewValues[index].at("layer_id"));
        }
    }
    if (!ids.empty())
    {
        layer->SetSelection(0);
    }
    form->Add(layer, 1, wxEXPAND);
    form->Add(new wxStaticText(&dialog, wxID_ANY, Display("뷰 이름")), 0, wxALIGN_CENTER_VERTICAL);
    auto* name = new wxTextCtrl(&dialog, wxID_ANY, Display("상세 뷰"));
    form->Add(name, 1, wxEXPAND);
    const std::array<const char*, 4> labels{{"최소 X (mm)", "최소 Y (mm)", "최대 X (mm)", "최대 Y (mm)"}};
    std::array<wxSpinCtrlDouble*, 4> bounds{};
    for (std::size_t index = 0; index < bounds.size(); ++index)
    {
        form->Add(new wxStaticText(&dialog, wxID_ANY, Display(labels[index])), 0, wxALIGN_CENTER_VERTICAL);
        bounds[index] = new wxSpinCtrlDouble(&dialog, wxID_ANY, "0", wxDefaultPosition, wxDefaultSize, wxSP_ARROW_KEYS,
                                             -10000, 10000, 0, 0.1);
        bounds[index]->SetDigits(6);
        form->Add(bounds[index], 1, wxEXPAND);
    }
    layout->Add(form, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    auto* buttons = dialog.CreateSeparatedButtonSizer(wxOK | wxCANCEL);
    layout->Add(buttons, 0, wxEXPAND | wxALL, FromDIP(12));
    dialog.SetSizer(layout);
    dialog.CentreOnParent();
    dialog.Bind(
        wxEVT_BUTTON,
        [&dialog, layer, name, bounds](wxCommandEvent&)
        {
            if (layer->GetSelection() == wxNOT_FOUND || name->GetValue().Strip().empty() ||
                bounds[0]->GetValue() >= bounds[2]->GetValue() || bounds[1]->GetValue() >= bounds[3]->GetValue())
            {
                wxMessageBox(Display("도체층, 이름과 최소값보다 큰 최대 X/Y 좌표를 지정하세요."),
                             Display("상세 뷰 입력"), wxOK | wxICON_INFORMATION, &dialog);
                return;
            }
            dialog.EndModal(wxID_OK);
        },
        wxID_OK);
    if (dialog.ShowModal() != wxID_OK)
    {
        return;
    }
    Json region = Json::array();
    for (auto* input : bounds)
    {
        region.push_back(input->GetValue());
    }
    m_viewValues.push_back({{"kind", "detail"},
                            {"layer_id", ids.at(layer->GetSelection())},
                            {"bounds_mm", region},
                            {"label", Utf8(name->GetValue())}});
    const auto row = m_views->Append(name->GetValue() + Display(" (상세 영역)"));
    m_views->Check(row);
    m_views->SetSelection(row);
    Changed();
}
