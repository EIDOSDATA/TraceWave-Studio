/** @file @brief 급전, 비아 및 좌표 간극에 지정한 국부 격자 조건과 결과를 표시한다. */
#include "solver_local_mesh_panel.h"
#include "studio_support.h"
#include "studio_theme.h"

#include <algorithm>
#include <cmath>
#include <optional>
#include <utility>
#include <wx/listctrl.h>
#include <wx/wx.h>

namespace
{
constexpr const char* Axes[] = {"x", "y", "z"};
constexpr const char* AxisLabels[] = {"X", "Y", "Z"};

wxString TargetLabel(const Json& target)
{
    return Display((target.at("kind") == "port" ? "급전 / " : "비아 / ") + target.at("name").get<std::string>());
}

/** @brief 간극에는 위치 범위를 받고 객체에는 현재 개정의 안정 ID를 저장한다. */
std::optional<Json> EditRule(wxWindow* parent, const Json& targets, const Json& rule)
{
    wxDialog dialog(parent, wxID_ANY, Display("국부 격자 조건"));
    dialog.SetName("solver.local.editor");
    StudioTheme::ApplyTypography(dialog);
    StudioTheme::BindSurface(dialog);
    const int gap = dialog.FromDIP(StudioTheme::InputGap);
    auto* root = new wxBoxSizer(wxVERTICAL);
    auto* target = new wxChoice(&dialog, wxID_ANY);
    target->SetName("solver.local.target");
    root->Add(new wxStaticText(&dialog, wxID_ANY, Display("적용 대상")), 0, wxLEFT | wxTOP, gap);
    root->Add(target, 0, wxEXPAND | wxALL, gap);
    target->Append(Display("좁은 간극 / 좌표 상자"));
    Json options = Json::array({Json{{"kind", "gap"}}});
    int selected = 0;
    for (const auto& item : targets)
    {
        target->Append(TargetLabel(item));
        options.push_back(item);
        if (rule.contains("object_id") && item.at("id") == rule.at("object_id") && item.at("kind") == rule.at("kind"))
        {
            selected = target->GetCount() - 1;
        }
    }
    if (rule.contains("object_id") && selected == 0)
    {
        target->Append(Display("현재 개정에 대상 없음 / " + rule.at("object_id").get<std::string>()));
        options.push_back(Json{{"kind", rule.at("kind")}, {"id", rule.at("object_id")}});
        selected = target->GetCount() - 1;
    }
    target->SetSelection(selected);

    const auto input = [&](wxSizer& group, const std::string& key, const wxString& label, const Json& value)
    {
        auto* row = new wxBoxSizer(wxHORIZONTAL);
        auto* caption = new wxStaticText(&dialog, wxID_ANY, label);
        auto* field = new wxTextCtrl(&dialog, wxID_ANY, value.is_null() ? wxString() :
            Display(value.is_string() ? value.get<std::string>() : value.dump()));
        field->SetName(Display("solver.local." + key));
        field->SetToolTip(label);
        row->Add(caption, 1, wxALIGN_CENTER_VERTICAL | wxRIGHT, gap);
        row->Add(field, 1, wxALIGN_CENTER_VERTICAL);
        group.Add(row, 0, wxEXPAND | wxBOTTOM, gap);
        return field;
    };
    auto* fields = new wxBoxSizer(wxVERTICAL);
    root->Add(fields, 0, wxEXPAND | wxLEFT | wxRIGHT, gap);
    auto* priority = input(*fields, "priority", Display("우선순위 (0~100)"), rule.value("priority", 50));
    std::array<wxTextCtrl*, 3> widths{};
    const auto targetWidths = rule.value("max_cell_mm", Json::object());
    for (std::size_t axis = 0; axis < widths.size(); ++axis)
    {
        widths[axis] = input(*fields, Axes[axis], wxString::Format(Display("%s축 목표 최대 폭 (mm)"), Display(AxisLabels[axis])),
                             targetWidths.value(Axes[axis], Json()));
    }
    auto* note = new wxStaticText(&dialog, wxID_ANY, Display("빈 축은 기존 격자를 사용합니다. 겹치면 큰 우선순위가 먼저 적용됩니다."));
    note->Wrap(dialog.FromDIP(440));
    StudioTheme::BindSecondary(*note);
    fields->Add(note, 0, wxEXPAND | wxBOTTOM, gap);

    auto* box = new wxBoxSizer(wxVERTICAL);
    fields->Add(box, 0, wxEXPAND);
    auto* name = input(*box, "name", Display("간극 이름"), rule.value("name", Json()));
    std::array<std::array<wxTextCtrl*, 2>, 3> bounds{};
    const auto initialBounds = rule.value("bounds_mm", Json::array({Json::array({nullptr, nullptr}),
                                              Json::array({nullptr, nullptr}), Json::array({nullptr, nullptr})}));
    for (std::size_t axis = 0; axis < bounds.size(); ++axis)
    {
        for (std::size_t end = 0; end < 2; ++end)
        {
            const auto term = end == 0 ? " 시작 (mm)" : " 끝 (mm)";
            bounds[axis][end] = input(*box, std::string(Axes[axis]) + (end == 0 ? ".low" : ".high"),
                                      Display(std::string(AxisLabels[axis]) + term), initialBounds.at(axis).at(end));
        }
    }
    auto* status = new wxStaticText(&dialog, wxID_ANY, wxEmptyString);
    status->SetName("solver.local.editor.status");
    root->Add(status, 0, wxEXPAND | wxLEFT | wxRIGHT, gap);
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    actions->AddStretchSpacer();
    auto* cancel = new wxButton(&dialog, wxID_CANCEL, Display("취소"));
    auto* apply = new wxButton(&dialog, wxID_OK, Display("조건 반영"));
    apply->SetName("solver.local.editor.apply");
    StudioTheme::Button(*cancel);
    StudioTheme::Button(*apply, true);
    actions->Add(cancel);
    actions->Add(apply, 0, wxLEFT, gap);
    root->Add(actions, 0, wxEXPAND | wxALL, gap);
    dialog.SetSizer(root);
    const auto resize = [&]()
    {
        fields->Show(box, target->GetSelection() == 0, true);
        root->Fit(&dialog);
        dialog.SetSize(std::max(dialog.GetSize().x, dialog.FromDIP(510)), dialog.GetSize().y);
        dialog.Layout();
    };
    target->Bind(wxEVT_CHOICE, [&](wxCommandEvent&) { resize(); });

    std::optional<Json> accepted;
    apply->Bind(wxEVT_BUTTON, [&](wxCommandEvent&)
    {
        const auto error = [&](wxWindow* field, const char* message)
        {
            status->SetLabel(Display(message));
            status->Wrap(dialog.FromDIP(440));
            resize();
            field->SetFocus();
        };
        long rank = 0;
        if (!priority->GetValue().ToLong(&rank) || rank < 0 || rank > 100)
        {
            error(priority, "우선순위를 0~100 사이의 정수로 입력하세요.");
            return;
        }
        Json sizes = Json::object();
        for (std::size_t axis = 0; axis < widths.size(); ++axis)
        {
            const auto text = widths[axis]->GetValue().Strip(wxString::both);
            double value = 0;
            if (text.empty())
            {
                continue;
            }
            if (!text.ToDouble(&value) || !std::isfinite(value) || value < .001 || value > 5)
            {
                error(widths[axis], "목표 최대 폭은 0.001~5 mm입니다.");
                return;
            }
            sizes[Axes[axis]] = value;
        }
        if (sizes.empty())
        {
            error(widths.front(), "한 축 이상의 목표 최대 폭을 입력하세요.");
            return;
        }
        const auto& object = options.at(target->GetSelection());
        Json result{{"kind", object.at("kind")}, {"priority", rank}, {"max_cell_mm", sizes}};
        if (object.at("kind") == "gap")
        {
            const auto label = name->GetValue().Strip(wxString::both);
            if (label.empty() || label.size() > 64)
            {
                error(name, "간극 이름을 1~64자로 입력하세요.");
                return;
            }
            Json intervals = Json::array();
            for (const auto& [start, stop] : bounds)
            {
                double low = 0, high = 0;
                if (!start->GetValue().ToDouble(&low) || !std::isfinite(low) || low < -1000 || low > 1000)
                {
                    error(start, "시작 좌표는 -1000~1000 mm입니다.");
                    return;
                }
                if (!stop->GetValue().ToDouble(&high) || !std::isfinite(high) || high <= low || high > 1000)
                {
                    error(stop, "끝 좌표는 시작 좌표보다 크고 1000 mm 이하여야 합니다.");
                    return;
                }
                intervals.push_back({low, high});
            }
            result["name"] = Utf8(label);
            result["bounds_mm"] = std::move(intervals);
        }
        else
        {
            result["object_id"] = object.at("id");
        }
        accepted = std::move(result);
        dialog.EndModal(wxID_OK);
    });
    resize();
    dialog.CentreOnParent();
    target->SetFocus();
    dialog.ShowModal();
    return accepted;
}
}

SolverLocalMeshPanel::SolverLocalMeshPanel(wxWindow* parent, const Json& targets, std::function<void()> changed,
    std::function<void(int, const std::array<double, 2>&, long, bool)> locate)
    : wxPanel(parent), m_targets(targets), m_changed(std::move(changed))
{
    StudioTheme::BindSurface(*this);
    const int gap = FromDIP(StudioTheme::InputGap);
    auto* root = new wxBoxSizer(wxVERTICAL);
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    const auto button = [&](wxSizer& row, const char* name, const char* caption)
    {
        auto* control = new wxButton(this, wxID_ANY, Display(caption));
        control->SetName(Display(std::string("solver.local.") + name));
        StudioTheme::Button(*control);
        row.Add(control, 0, wxRIGHT, gap);
        return control;
    };
    auto* hint = new wxStaticText(this, wxID_ANY,
        Display("급전과 비아의 위치를 자동으로 사용합니다. 좁은 간극은 기판 좌표로 입력합니다. 격자선은 다른 축의 전체 영역을 가로지릅니다."));
    StudioTheme::BindSecondary(*hint);
    hint->Wrap(FromDIP(680));
    root->Add(hint, 0, wxEXPAND | wxALL, gap);
    m_add = button(*actions, "add", "조건 추가");
    m_edit = button(*actions, "edit", "선택 조건 편집");
    m_remove = button(*actions, "remove", "선택 조건 삭제");
    root->Add(actions, 0, wxLEFT | wxRIGHT | wxBOTTOM, gap);
    const auto table = [&](const char* name)
    {
        auto* view = new wxListCtrl(this, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_SINGLE_SEL);
        view->SetName(Display(name));
        StudioTheme::Table(*view);
        view->SetMinSize(FromDIP(wxSize(-1, 95)));
        root->Add(view, 1, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, gap);
        return view;
    };
    m_list = table("solver.local.rules");
    m_list->AppendColumn(Display("대상"), wxLIST_FORMAT_LEFT, FromDIP(275));
    for (const auto* axis : AxisLabels)
    {
        m_list->AppendColumn(Display(std::string(axis) + " 목표 (mm)"), wxLIST_FORMAT_RIGHT, FromDIP(105));
    }
    m_list->AppendColumn(Display("우선순위"), wxLIST_FORMAT_RIGHT, FromDIP(90));
    root->Add(new wxStaticText(this, wxID_ANY, Display("검토한 격자의 실제 적용 구간")), 0, wxLEFT | wxTOP | wxBOTTOM, gap);
    m_report = table("solver.local.report");
    m_report->AppendColumn(Display("대상"), wxLIST_FORMAT_LEFT, FromDIP(182));
    m_report->AppendColumn(Display("축"), wxLIST_FORMAT_LEFT, FromDIP(38));
    m_report->AppendColumn(Display("구간 (mm)"), wxLIST_FORMAT_LEFT, FromDIP(151));
    m_report->AppendColumn(Display("실제 최대 (mm)"), wxLIST_FORMAT_RIGHT, FromDIP(123));
    m_report->AppendColumn(Display("셀 수"), wxLIST_FORMAT_RIGHT, FromDIP(57));
    m_report->AppendColumn(Display("상태"), wxLIST_FORMAT_LEFT, FromDIP(113));
    auto* bottom = new wxBoxSizer(wxHORIZONTAL);
    m_locate = button(*bottom, "locate", "선택 구간을 격자에서 보기");
    root->Add(bottom, 0, wxLEFT | wxRIGHT | wxBOTTOM, gap);
    SetSizer(root);

    const auto onSelection = [this](wxListEvent&) { UpdateActions(); };
    for (auto* view : {m_list, m_report})
    {
        view->Bind(wxEVT_LIST_ITEM_SELECTED, onSelection);
        view->Bind(wxEVT_LIST_ITEM_DESELECTED, onSelection);
    }
    m_add->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { Edit(-1); });
    m_edit->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { Edit(m_list->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED)); });
    m_list->Bind(wxEVT_LIST_ITEM_ACTIVATED, [this](wxListEvent& event) { Edit(event.GetIndex()); });
    m_remove->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        const long index = m_list->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
        if (index >= 0)
        {
            m_rules.erase(static_cast<std::size_t>(index));
            FillRules(std::min(index, static_cast<long>(m_rules.size()) - 1));
            m_changed();
        }
    });
    const auto showBand = [this, locate](long index)
    {
        if (index >= 0)
        {
            const auto& row = m_segments.at(static_cast<std::size_t>(index));
            locate(row.at("axis"), row.at("bounds_mm").get<std::array<double, 2>>(), row.at("first_line"), row.at("applied"));
        }
    };
    m_report->Bind(wxEVT_LIST_ITEM_ACTIVATED, [showBand](wxListEvent& event) { showBand(event.GetIndex()); });
    m_locate->Bind(wxEVT_BUTTON, [this, showBand](wxCommandEvent&)
    {
        showBand(m_report->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED));
    });
    UpdateActions();
}

wxString SolverLocalMeshPanel::Label(const Json& rule) const
{
    if (rule.at("kind") == "gap")
    {
        return Display("간극 / " + rule.at("name").get<std::string>());
    }
    for (const auto& item : m_targets)
    {
        if (item.at("kind") == rule.at("kind") && item.at("id") == rule.at("object_id"))
        {
            return TargetLabel(item);
        }
    }
    return Display("대상 없음 / " + rule.at("object_id").get<std::string>());
}

void SolverLocalMeshPanel::LoadRules(const Json& rules)
{
    m_rules = rules;
    FillRules(-1);
}

void SolverLocalMeshPanel::Edit(long index)
{
    const auto rule = EditRule(this, m_targets, index < 0 ? Json::object() : m_rules.at(static_cast<std::size_t>(index)));
    if (!rule)
    {
        return;
    }
    if (index < 0)
    {
        index = static_cast<long>(m_rules.size());
        m_rules.push_back(*rule);
    }
    else
    {
        m_rules.at(static_cast<std::size_t>(index)) = *rule;
    }
    FillRules(index);
    m_changed();
}

void SolverLocalMeshPanel::FillRules(long selected)
{
    m_list->DeleteAllItems();
    for (const auto& rule : m_rules)
    {
        const long row = m_list->InsertItem(m_list->GetItemCount(), Label(rule));
        for (int axis = 0; axis < 3; ++axis)
        {
            const auto& widths = rule.at("max_cell_mm");
            m_list->SetItem(row, axis + 1, widths.contains(Axes[axis]) ? Display(widths.at(Axes[axis]).dump()) : Display("-"));
        }
        m_list->SetItem(row, 4, Display(rule.at("priority").dump()));
    }
    if (selected >= 0)
    {
        m_list->SetItemState(selected, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
        m_list->EnsureVisible(selected);
    }
    UpdateActions();
}

void SolverLocalMeshPanel::DisplayReport(const Json& report)
{
    m_report->DeleteAllItems();
    m_segments.clear();
    for (const auto& rule : report.value("rules", Json::array()))
    {
        for (int axis = 0; axis < 3; ++axis)
        {
            if (!rule.at("axes").contains(Axes[axis]))
            {
                continue;
            }
            for (auto segment : rule.at("axes").at(Axes[axis]).at("segments"))
            {
                const auto bounds = segment.at("bounds_mm").get<std::array<double, 2>>();
                const auto row = m_report->InsertItem(m_report->GetItemCount(), Label(rule));
                m_report->SetItem(row, 1, Display(AxisLabels[axis]));
                m_report->SetItem(row, 2, wxString::Format("%.8g ~ %.8g", bounds[0], bounds[1]));
                m_report->SetItem(row, 3, wxString::Format("%.8g", segment.at("max_cell_mm").get<double>()));
                m_report->SetItem(row, 4, Display(segment.at("cells").dump()));
                m_report->SetItem(row, 5, Display(segment.at("applied").get<bool>() ? "적용" : "상위 규칙 적용"));
                segment["axis"] = axis;
                m_segments.push_back(std::move(segment));
            }
        }
    }
    UpdateActions();
}

void SolverLocalMeshPanel::FocusRule(const std::string& path)
{
    const auto open = path.find('[');
    const auto close = path.find(']');
    unsigned long index = 0;
    if (open != std::string::npos && close != std::string::npos && close > open &&
        Display(path.substr(open + 1, close - open - 1)).ToULong(&index) && index < m_rules.size())
    {
        const auto row = static_cast<long>(index);
        m_list->SetItemState(row, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
        m_list->EnsureVisible(row);
        UpdateActions();
        m_edit->SetFocus();
    }
    else
    {
        m_list->SetFocus();
    }
}

void SolverLocalMeshPanel::UpdateActions()
{
    const bool selected = m_list->GetSelectedItemCount() != 0;
    m_add->Enable(m_rules.size() < 16);
    m_edit->Enable(selected);
    m_remove->Enable(selected);
    m_locate->Enable(m_report->GetSelectedItemCount() != 0);
}
