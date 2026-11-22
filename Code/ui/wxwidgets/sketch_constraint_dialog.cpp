/** @file @brief 평면 스케치 후보, 충돌 및 저장한 관계의 Windows 작업 흐름이다. */
#include "sketch_constraint_dialog.h"
#include "design_canvas.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <algorithm>
#include <wx/checklst.h>
#include <wx/wx.h>

namespace
{
std::string State(const std::string& state)
{
    if (state == "conflict")
    {
        return "충돌";
    }
    if (state == "redundant")
    {
        return "중복";
    }
    if (state == "selected")
    {
        return "추가";
    }
    return "제안";
}
}

SketchConstraintDialog::SketchConstraintDialog(wxWindow* parent, const Json& context, const Json& scene,
                                               const Json& selection, DialogGateway gateway)
    : ProjectSetupDialog(parent, "스케치 자동 치수와 구속", context, std::move(gateway)), m_context(context)
{
    SetName("sketch.constraints");
    StudioTheme::ApplyTypography(*this);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* workspace = new wxBoxSizer(wxHORIZONTAL);
    auto* left = new wxBoxSizer(wxVERTICAL);
    left->SetMinSize(FromDIP(wxSize(310, -1)));
    auto* fields = new wxFlexGridSizer(2, FromDIP(8), FromDIP(8));
    fields->AddGrowableCol(1, 1);
    const auto choice = [this, fields](const char* title, const char* name)
    {
        fields->Add(new wxStaticText(this, wxID_ANY, Display(title)), 0, wxALIGN_CENTER_VERTICAL);
        auto* result = new wxChoice(this, wxID_ANY);
        result->SetName(name);
        result->SetMinSize(FromDIP(wxSize(208, -1)));
        fields->Add(result, 1, wxEXPAND);
        return result;
    };
    m_group = choice("저장 구속", "sketch.groups");
    m_group->Append(Display("새 구속"));
    for (const auto& group : m_context.at("groups"))
    {
        m_group->Append(Display(group.at("name").get<std::string>()));
    }
    m_group->SetSelection(0);
    m_datum = choice("기준점", "sketch.datum");
    m_axis = choice("기준축", "sketch.axis");
    m_axis->Append(Display("기판 X축"));
    m_axis->Append(Display("기판 Y축"));
    m_axis->SetSelection(0);
    fields->Add(new wxStaticText(this, wxID_ANY, Display("이름")), 0, wxALIGN_CENTER_VERTICAL);
    m_name = new wxTextCtrl(this, wxID_ANY, Display("스케치 구속"));
    m_name->SetName("sketch.name");
    m_name->SetMaxLength(256);
    fields->Add(m_name, 1, wxEXPAND);
    left->Add(fields, 0, wxEXPAND | wxBOTTOM, FromDIP(12));

    left->Add(new wxStaticText(this, wxID_ANY, Display("대상 선·원호·패드")), 0, wxBOTTOM, FromDIP(6));
    m_shapes = new wxCheckListBox(this, wxID_ANY);
    m_shapes->SetName("sketch.shapes");
    const auto initial = selection.value("id", Json(nullptr));
    for (const auto& shape : m_context.at("shapes"))
    {
        const auto index = m_shapes->Append(Display(shape.at("name").get<std::string>()));
        m_shapes->Check(index, shape.at("id") == initial);
    }
    left->Add(m_shapes, 1, wxEXPAND | wxBOTTOM, FromDIP(8));
    m_canvas = new DesignCanvas(this);
    m_canvas->SetName("sketch.canvas");
    m_canvas->SetMinSize(FromDIP(wxSize(280, 240)));
    m_canvas->SetEditingEnabled(false);
    m_canvas->SetScene(scene);
    left->Add(m_canvas, 2, wxEXPAND);
    workspace->Add(left, 1, wxEXPAND | wxRIGHT, FromDIP(12));

    auto* review = new wxBoxSizer(wxVERTICAL);
    m_freedom = new wxStaticText(this, wxID_ANY, Display("적용 전후 자유도"));
    m_freedom->SetName("sketch.freedom");
    StudioTheme::Heading(*m_freedom);
    review->Add(m_freedom, 0, wxBOTTOM, FromDIP(8));
    m_proposals = new wxCheckListBox(this, wxID_ANY);
    m_proposals->SetName("sketch.proposals");
    review->Add(m_proposals, 2, wxEXPAND | wxBOTTOM, FromDIP(8));
    m_report = new wxTextCtrl(this, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(440, 150)),
                              wxTE_MULTILINE | wxTE_READONLY);
    m_report->SetName("sketch.report");
    review->Add(m_report, 1, wxEXPAND);
    workspace->Add(review, 2, wxEXPAND);
    layout->Add(workspace, 1, wxEXPAND | wxBOTTOM, FromDIP(8));

    m_status = new wxStaticText(this, wxID_ANY, wxEmptyString);
    m_status->SetName("sketch.status");
    layout->Add(m_status, 0, wxEXPAND | wxBOTTOM, FromDIP(8));
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    m_preview = new wxButton(this, wxID_ANY, Display("제안 검토"));
    m_preview->SetName("sketch.preview");
    m_automatic = new wxButton(this, wxID_ANY, Display("독립 제안 다시 선택"));
    m_automatic->SetName("sketch.auto");
    m_remove = new wxButton(this, wxID_ANY, Display("삭제 검토"));
    m_remove->SetName("sketch.remove");
    m_apply = new wxButton(this, wxID_ANY, Display("적용"));
    m_apply->SetName("sketch.apply");
    auto* close = new wxButton(this, wxID_CANCEL, Display("닫기"));
    for (auto* button : {m_preview, m_automatic, m_remove, m_apply, close})
    {
        StudioTheme::Button(*button, button == m_apply);
        actions->Add(button, 0, wxLEFT, FromDIP(8));
    }
    layout->Add(actions, 0, wxALIGN_RIGHT);
    auto* outer = new wxBoxSizer(wxVERTICAL);
    outer->Add(layout, 1, wxEXPAND | wxALL, FromDIP(12));
    SetSizer(outer);
    Layout();
    m_canvas->FitView();
    FillPoints();

    m_group->Bind(wxEVT_CHOICE, [this](wxCommandEvent&)
    {
        if (m_mutating || !ConfirmDiscard())
        {
            m_group->SetSelection(m_groupIndex);
            return;
        }
        m_groupIndex = m_group->GetSelection();
        LoadGroup();
    });
    m_shapes->Bind(wxEVT_CHECKLISTBOX, [this](wxCommandEvent&)
    {
        FillPoints();
        SetupChanged();
    });
    for (auto* control : {m_datum, m_axis})
    {
        control->Bind(wxEVT_CHOICE, [this](wxCommandEvent&)
        {
            SetupChanged();
        });
    }
    m_name->Bind(wxEVT_TEXT, [this](wxCommandEvent&)
    {
        SetupChanged();
    });
    m_proposals->Bind(wxEVT_CHECKLISTBOX, [this](wxCommandEvent&)
    {
        InvalidateRead();
        m_review = nullptr;
        SetStatus("선택이 바뀌었습니다. 제안을 다시 검토하세요.");
        UpdateActions();
    });
    m_preview->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        Preview();
    });
    m_automatic->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        Preview(true);
    });
    m_remove->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        Preview(false, true);
    });
    m_apply->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        Apply();
    });
    ShowGeometry();
    SetStatus("대상 형상과 기준점, 기준축을 선택한 뒤 제안을 검토하세요.");
    UpdateActions();
}

bool SketchConstraintDialog::HasDraft() const
{
    return m_dirty;
}

Json SketchConstraintDialog::SelectedShapes() const
{
    Json ids = Json::array();
    for (unsigned int index = 0; index < m_shapes->GetCount(); ++index)
    {
        if (m_shapes->IsChecked(index))
        {
            ids.push_back(m_context.at("shapes").at(index).at("id"));
        }
    }
    return ids;
}

void SketchConstraintDialog::FillPoints()
{
    const int previous = m_datum->GetSelection();
    const Json selected = previous == wxNOT_FOUND ? Json(nullptr) : m_points.at(previous).at("ref");
    m_datum->Clear();
    m_points = Json::array();
    int same = wxNOT_FOUND;
    for (unsigned int index = 0; index < m_shapes->GetCount(); ++index)
    {
        if (!m_shapes->IsChecked(index))
        {
            continue;
        }
        const auto& shape = m_context.at("shapes").at(index);
        for (const auto& point : shape.at("points"))
        {
            const auto label = shape.at("name").get<std::string>() + " / " + point.at("name").get<std::string>();
            const int added = m_datum->Append(Display(label));
            m_points.push_back(point);
            if (point.at("ref") == selected)
            {
                same = added;
            }
        }
    }
    if (!m_points.empty())
    {
        m_datum->SetSelection(same == wxNOT_FOUND ? 0 : same);
    }
}

void SketchConstraintDialog::ShowGeometry()
{
    const auto ids = SelectedShapes().get<std::vector<std::string>>();
    const int index = m_datum->GetSelection();
    if (index == wxNOT_FOUND)
    {
        m_canvas->SetInspection(ids, std::nullopt);
        return;
    }
    const auto& point = m_points.at(index).at("point_mm");
    m_canvas->SetInspection(ids, wxPoint2DDouble(point.at(0).get<double>(), point.at(1).get<double>()));
}

void SketchConstraintDialog::SetupChanged()
{
    InvalidateRead();
    m_review = nullptr;
    m_rows = Json::array();
    m_proposals->Clear();
    m_freedom->SetLabel(Display("적용 전후 자유도"));
    m_report->ChangeValue("");
    ShowGeometry();
    SetStatus("기준이 바뀌었습니다. 현재 형상에서 제안을 다시 검토하세요.");
    UpdateActions();
}

void SketchConstraintDialog::LoadGroup()
{
    SetupChanged();
    m_dirty = false;
    const Json group = m_groupIndex ? m_context.at("groups").at(m_groupIndex - 1) : Json(nullptr);
    const auto ids = group.is_object() ? group.at("selection_ids") : Json::array();
    for (unsigned int index = 0; index < m_shapes->GetCount(); ++index)
    {
        const auto& identity = m_context.at("shapes").at(index).at("id");
        m_shapes->Check(index, std::find(ids.begin(), ids.end(), identity) != ids.end());
    }
    FillPoints();
    if (group.is_object())
    {
        for (std::size_t index = 0; index < m_points.size(); ++index)
        {
            if (m_points.at(index).at("ref") == group.at("datum"))
            {
                m_datum->SetSelection(index);
            }
        }
        m_axis->SetSelection(group.at("axis") == "x" ? 0 : 1);
        m_name->ChangeValue(Display(group.at("name").get<std::string>()));
        std::string text = "저장 구속 " + std::to_string(group.at("constraints").size()) + "개\n";
        for (const auto& row : group.at("labels"))
        {
            text += row.get<std::string>() + "\n";
        }
        text += "\n보존 관계 " + std::to_string(group.at("preserved").size()) + "개\n";
        for (const auto& row : group.at("preserved"))
        {
            text += row.get<std::string>() + "\n";
        }
        m_report->ChangeValue(Display(text));
        SetStatus("저장한 구속입니다. 제안 검토에서 현재 자유도를 확인할 수 있습니다.");
    }
    else
    {
        m_axis->SetSelection(0);
        m_name->ChangeValue(Display("스케치 구속"));
        SetStatus("대상 형상과 기준점, 기준축을 선택한 뒤 제안을 검토하세요.");
    }
    ShowGeometry();
    UpdateActions();
}

Json SketchConstraintDialog::Requested() const
{
    Json ids = Json::array();
    for (unsigned int index = 0; index < m_proposals->GetCount(); ++index)
    {
        if (m_proposals->IsChecked(index))
        {
            ids.push_back(m_rows.at(index).at("id"));
        }
    }
    return ids;
}

void SketchConstraintDialog::Preview(bool automatic, bool remove)
{
    Json input{{"expected_revision", m_revision}, {"operation", remove ? "remove" : "complete"}};
    if (remove)
    {
        input["id"] = m_context.at("groups").at(m_groupIndex - 1).at("id");
    }
    else
    {
        input["name"] = m_name->GetValue().utf8_string();
        input["selection_ids"] = SelectedShapes();
        input["datum"] = m_points.at(m_datum->GetSelection()).at("ref");
        input["axis"] = m_axis->GetSelection() == 0 ? "x" : "y";
        input["requested"] = automatic || m_rows.empty() ? Json(nullptr) : Requested();
    }
    m_review = nullptr;
    Request("precision.sketch.preview", input, false, [this, input](const Json& result)
    {
        Present(result);
        if (result.at("can_apply").get<bool>())
        {
            m_review = result;
            m_reviewInput = input;
            m_dirty = true;
        }
    });
}

void SketchConstraintDialog::Present(const Json& result)
{
    m_rows = result.at("proposals");
    m_proposals->Clear();
    for (const auto& row : m_rows)
    {
        const auto caption = State(row.at("state").get<std::string>()) + " / " + row.at("label").get<std::string>();
        const auto index = m_proposals->Append(Display(caption));
        m_proposals->Check(index, row.at("selected").get<bool>());
    }
    if (result.at("before").is_number_integer())
    {
        m_freedom->SetLabel(Display("자유도 " + result.at("before").dump() + " -> " +
                                    result.at("after").dump() + " / 변수 " + result.at("variables").dump()));
    }
    std::string text = "선택한 제안과 기존 관계의 충돌 " + std::to_string(result.at("conflicts").size()) + "개\n";
    for (const auto& row : result.at("conflicts"))
    {
        text += row.get<std::string>() + "\n";
    }
    text += "\n이미 성립하는 치수와 관계\n";
    for (const auto& row : result.at("existing"))
    {
        text += row.get<std::string>() + "\n";
    }
    m_report->ChangeValue(Display(text));
    m_report->ShowPosition(0);
    SetStatus(result.at("can_apply").get<bool>() ? "검토한 구속은 현재 형상에서 성립합니다. 적용 후 프로젝트를 저장하세요."
                                                : result.at("message").get<std::string>());
}

void SketchConstraintDialog::Apply()
{
    auto input = m_reviewInput;
    input["review_hash"] = m_review.at("review_hash");
    input["command_id"] = Uuid();
    Request("precision.sketch.apply", input, true, [this](const Json& result)
    {
        AcceptMutation(result);
        m_dirty = false;
        CloseDialog(true);
    });
}

void SketchConstraintDialog::UpdateActions()
{
    const bool editable = Editable();
    const bool setup = editable && m_groupIndex == 0;
    const bool request = editable && !m_pending && m_datum->GetSelection() != wxNOT_FOUND &&
                         !m_name->GetValue().Strip(wxString::both).empty();
    m_shapes->Enable(setup);
    m_datum->Enable(setup);
    m_axis->Enable(setup);
    m_name->Enable(setup);
    m_proposals->Enable(editable && !m_rows.empty());
    m_group->Enable(!m_mutating);
    m_preview->Enable(request);
    m_automatic->Enable(request && !m_rows.empty());
    m_remove->Enable(editable && !m_pending && m_groupIndex > 0);
    m_apply->Enable(editable && !m_pending && m_review.is_object());
}
