/** @file @brief 수량/출처와 현재 적층 단면 표를 GUI 컨트롤에 표시한다. */
#include "studio_internal.h"
#include "physical_setup_dialog.h"
#include "studio_theme.h"
#include <wx/dcclient.h>
#include <wx/scrolwin.h>

namespace
{
std::string Mm(const Json& value)
{
    return value.is_null() ? "미정" : Utf8(wxString::Format("%.10g", value.get<double>() * 1000.0));
}

Json WidgetValue(wxWindow& window)
{
    if (auto* choice = dynamic_cast<wxChoice*>(&window))
    {
        const int index = choice->GetSelection();
        if (index < 0)
        {
            return "";
        }
        return Utf8(static_cast<wxStringClientData*>(choice->GetClientObject(index))->GetData());
    }
    if (auto* check = dynamic_cast<wxCheckBox*>(&window))
    {
        return check->GetValue();
    }
    return Utf8(static_cast<wxTextCtrl&>(window).GetValue());
}
}

void PhysicalSetupDialog::RenderFields()
{
    m_inputs.clear();
    auto* sizer = m_form->GetSizer();
    sizer->Clear(true);
    auto* grid = new wxFlexGridSizer(2, FromDIP(8), FromDIP(10));
    grid->AddGrowableCol(1, 1);
    for (const auto& row : m_context.at("fields"))
    {
        const std::string key = row.at("key");
        const std::string kind = row.at("kind");
        std::string label = row.at("label");
        if (kind == "quantity")
        {
            label += " (" + row.at("unit").get<std::string>() + ")";
        }
        grid->Add(new wxStaticText(m_form, wxID_ANY, Display(label)), 0, wxALIGN_CENTER_VERTICAL);
        wxWindow* input = nullptr;
        if (kind == "choice")
        {
            auto* choice = new wxChoice(m_form, wxID_ANY);
            for (const auto& option : row.at("choices"))
            {
                const int index = choice->Append(Display(option.at("label")),
                                                 new wxStringClientData(Display(option.at("value"))));
                if (option.at("value") == row.at("value"))
                {
                    choice->SetSelection(index);
                }
            }
            choice->Bind(wxEVT_CHOICE, [this](wxCommandEvent&) { UpdateActions(); });
            input = choice;
        }
        else if (kind == "bool")
        {
            auto* check = new wxCheckBox(m_form, wxID_ANY, wxEmptyString);
            check->SetValue(row.at("value").get<bool>());
            check->Bind(wxEVT_CHECKBOX, [this](wxCommandEvent&) { UpdateActions(); });
            input = check;
        }
        else
        {
            const bool lines = kind == "lines";
            auto* entry = new wxTextCtrl(m_form, wxID_ANY, Display(row.at("value")), wxDefaultPosition,
                                         lines ? wxSize(-1, FromDIP(60)) : wxDefaultSize, lines ? wxTE_MULTILINE : 0);
            if (!lines)
            {
                entry->SetMaxLength(kind == "quantity" ? 64 : 128);
            }
            if (kind == "quantity")
            {
                entry->SetHint(Display("미정"));
                const auto& original = row.at("original");
                std::string detail = "원본 상태 " + original.value("status", std::string("매개변수 참조"));
                for (const auto& source : original.value("source_refs", Json::array()))
                {
                    detail += "\n" + source.get<std::string>();
                }
                entry->SetToolTip(Display(detail));
            }
            entry->Bind(wxEVT_TEXT, [this](wxCommandEvent&) { UpdateActions(); });
            input = entry;
        }
        input->SetName(Display("physical.field." + key));
        m_inputs.emplace(key, input);
        grid->Add(input, 1, wxEXPAND);
    }
    sizer->Add(grid, 0, wxEXPAND | wxALL, FromDIP(StudioTheme::PanelPadding));
    m_form->Scroll(0, 0);
    m_form->FitInside();
    m_form->Layout();
}

void PhysicalSetupDialog::DrawSection()
{
    wxPaintDC dc(m_sectionView);
    dc.SetBackground(wxBrush(wxColour(246, 249, 253)));
    dc.Clear();
    struct Band
    {
        double lower;
        double upper;
        wxColour color;
    };
    std::vector<Band> bands;
    const auto& review = m_context.at("stack_review");
    for (const auto& row : review.at("rows"))
    {
        if (!row.at("z_min").is_null() && !row.at("z_max").is_null())
        {
            bands.push_back({row.at("z_min"), row.at("z_max"),
                             row.at("role") == "conductor" ? wxColour(223, 141, 57) : wxColour(140, 191, 156)});
        }
    }
    for (const auto& row : review.at("surfaces"))
    {
        const auto& interval = row.at("interval_si");
        if (!interval.is_null())
        {
            bands.push_back({interval.at(0), interval.at(1), wxColour(81, 155, 188)});
        }
    }
    dc.SetTextForeground(wxColour(36, 55, 74));
    const int margin = FromDIP(10);
    dc.DrawText(Display("적층 단면 (z)"), margin, margin / 2);
    if (bands.empty())
    {
        dc.DrawText(Display("확정된 z 범위가 없습니다."), margin, FromDIP(32));
        return;
    }
    double lower = bands.front().lower;
    double upper = bands.front().upper;
    for (const auto& band : bands)
    {
        lower = std::min(lower, band.lower);
        upper = std::max(upper, band.upper);
    }
    const auto size = m_sectionView->GetClientSize();
    const int top = FromDIP(26);
    const int height = std::max(1, size.y - top - margin);
    const double span = upper - lower;
    if (span <= 0.0 || !std::isfinite(span))
    {
        return;
    }
    dc.SetPen(*wxTRANSPARENT_PEN);
    for (const auto& band : bands)
    {
        const int start = top + static_cast<int>(std::lround((upper - band.upper) / span * height));
        const int end = top + static_cast<int>(std::lround((upper - band.lower) / span * height));
        dc.SetBrush(wxBrush(band.color));
        dc.DrawRectangle(margin, start, std::max(1, size.x - 2 * margin), std::max(1, end - start));
    }
}

void PhysicalSetupDialog::RenderReview()
{
    const auto& review = m_context.at("stack_review");
    m_sectionView->Refresh(false);
    m_stack->DeleteAllItems();
    for (const auto& row : review.at("rows"))
    {
        const long item = m_stack->InsertItem(m_stack->GetItemCount(), Display(row.at("name")));
        m_stack->SetItem(item, 1, Display(Mm(row.at("z_min"))));
        m_stack->SetItem(item, 2, Display(Mm(row.at("z_max"))));
        m_stack->SetItem(item, 3, Display(Mm(row.at("thickness"))));
        if (row.at("role") == "conductor")
        {
            m_stack->SetItemBackgroundColour(item, wxColour(255, 234, 206));
        }
        else if (row.at("role") == "dielectric")
        {
            m_stack->SetItemBackgroundColour(item, wxColour(222, 240, 228));
        }
        if (row.at("material_id").is_null())
        {
            m_stack->SetItemText(item, Display(row.at("name").get<std::string>() + " (물성 미정)"));
        }
    }
    for (const auto& row : review.at("surfaces"))
    {
        const long item = m_stack->InsertItem(m_stack->GetItemCount(),
                                              Display(row.at("name").get<std::string>() + " (" +
                                                      (row.at("side") == "top" ? "상면)" : "하면)")));
        const auto& z = row.at("interval_si");
        m_stack->SetItem(item, 1, Display(Mm(z.is_null() ? Json(nullptr) : z.at(0))));
        m_stack->SetItem(item, 2, Display(Mm(z.is_null() ? Json(nullptr) : z.at(1))));
        m_stack->SetItem(item, 3, Display(Mm(row.at("thickness_si"))));
        m_stack->SetItemBackgroundColour(item, wxColour(226, 234, 250));
    }
    std::string text = "기본 층 두께 합 " + Mm(review.at("base_sum_si")) + " mm\n기본 적층 외면 간 거리 " +
                       Mm(review.at("base_extent_si")) + " mm\n표면층 포함 외면 간 거리 " +
                       Mm(review.at("full_extent_si")) + " mm\n명목과의 차이 (계산 - 명목) " +
                       Mm(review.at("nominal_difference_si")) + " mm";
    for (const auto& gap : review.at("gaps"))
    {
        text += "\n기본 적층 z 간격 " + Mm(gap.at("length_si")) + " mm";
    }
    text += "\n\n해석 미반영 " + std::to_string(m_context.at("em_status").size()) + "개";
    if (std::any_of(m_context.at("em_status").begin(), m_context.at("em_status").end(),
                    [](const Json& row) { return row.at("reason") == "unsupported_in_profile"; }))
    {
        text += "\n해석 포함으로 선택한 미지원 항목은 해석을 차단합니다.";
    }
    if (m_context.at("section") == "part")
    {
        text += "\n하부 개방 케이스는 바깥 치수와 벽 두께, 재료가 필요합니다. 해석에서는 Z축 회전 0도를 지정하십시오.";
        text += "\n비접촉 금속 상자는 이상 도체(PEC)로 계산합니다. PCB·케이스·다른 금속과 간극이 필요합니다.";
        text += "\n접지 금속은 최상층의 사각 급전 기준 접지 패드 윗면에 놓으십시오.";
    }
    if (!m_stepReview.is_null())
    {
        const auto& box = m_stepReview.at("bbox_mm");
        text += "\n\nSTEP 미리보기 " + m_stepReview.at("name").get<std::string>() +
                "\n닫힌 단일 고체 / mm / 면 " + std::to_string(m_stepReview.at("faces").get<int>()) +
                "개\n원본 범위 " + box.dump() + " mm\nSHA-256 " +
                m_stepReview.at("sha256").get<std::string>() + "\n재료 미정";
    }
    else if (!m_context.at("step").is_null())
    {
        const auto& step = m_context.at("step");
        text += "\n\n보존 STEP " + step.at("name").get<std::string>() + "\nSHA-256 " + step.at("sha256").get<std::string>();
    }
    for (const auto& source : m_context.at("source_refs"))
    {
        text += "\n" + source.get<std::string>();
    }
    m_review->ChangeValue(Display(text));
}

Json PhysicalSetupDialog::Changes() const
{
    Json changed = Json::object();
    for (const auto& row : m_context.at("fields"))
    {
        const std::string key = row.at("key");
        if (key == "case_thickness" && Value("kind") != "dielectric_case")
        {
            continue;
        }
        if (const Json value = WidgetValue(*m_inputs.at(key)); value != row.at("value"))
        {
            changed[key] = value;
        }
    }
    return changed;
}

std::string PhysicalSetupDialog::Value(const std::string& key) const
{
    const auto entry = m_inputs.find(key);
    return entry == m_inputs.end() ? "" : WidgetValue(*entry->second).get<std::string>();
}

bool PhysicalSetupDialog::HasDraft() const
{
    return !m_refreshing && (!Changes().empty() || !m_stepReview.is_null());
}

void PhysicalSetupDialog::UpdateActions()
{
    const bool ready = Editable() && !m_pending && !m_refreshing;
    const std::string section = m_context.at("section");
    const bool list = m_context.at("records").contains(section);
    m_section->Enable(ready);
    m_record->Enable(ready && list);
    m_form->Enable(ready);
    if (const auto wall = m_inputs.find("case_thickness"); wall != m_inputs.end())
    {
        wall->second->Enable(ready && Value("kind") == "dielectric_case");
    }
    m_reason->Enable(ready);
    m_browse->Enable(ready && section == "part" && m_context.at("cad_configured") == true);
    const bool reason = !m_reason->GetValue().Trim().Trim(false).empty();
    m_apply->Enable(ready && reason && HasDraft());
    m_remove->Enable(ready && reason && section != "activation" && m_context.at("exists") == true);
}
