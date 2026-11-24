/** @file @brief 스마트 치수의 화면 기준점 선택, 미리보기와 개정 적용을 제공한다. */
#include "smart_dimension_dialog.h"
#include "design_canvas.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <array>
#include <cmath>
#include <iomanip>
#include <locale>
#include <sstream>
#include <wx/wx.h>

namespace
{
std::string Format(const Json& value)
{
    if (value.is_null())
    {
        return "미정";
    }
    std::ostringstream text;
    text.imbue(std::locale::classic());
    text << std::setprecision(9) << value.get<double>();
    return text.str();
}

wxChoice* Choice(wxWindow* parent, wxFlexGridSizer* form, const char* label, const char* name)
{
    form->Add(new wxStaticText(parent, wxID_ANY, Display(label)), 0, wxALIGN_CENTER_VERTICAL);
    auto* choice = new wxChoice(parent, wxID_ANY);
    choice->SetName(name);
    form->Add(choice, 1, wxEXPAND);
    return choice;
}

wxTextCtrl* Input(wxWindow* parent, wxFlexGridSizer* form, const char* label, const char* name)
{
    form->Add(new wxStaticText(parent, wxID_ANY, Display(label)), 0, wxALIGN_CENTER_VERTICAL);
    auto* text = new wxTextCtrl(parent, wxID_ANY);
    text->SetName(name);
    form->Add(text, 1, wxEXPAND);
    return text;
}

int FindId(const Json& rows, const Json& id)
{
    for (std::size_t index = 0; index < rows.size(); ++index)
    {
        if (rows.at(index).at("id") == id)
        {
            return static_cast<int>(index) + 1;
        }
    }
    return 0;
}

Json Measure(const Json& points)
{
    if (points.size() != 2)
    {
        return nullptr;
    }
    std::array<double, 3> delta{};
    for (std::size_t axis = 0; axis < delta.size(); ++axis)
    {
        delta[axis] = points.at(1).at(axis).get<double>() - points.at(0).at(axis).get<double>();
    }
    const double planar = std::hypot(delta[0], delta[1]);
    const double length = std::hypot(planar, delta[2]);
    const double toDegrees = 180.0 / std::acos(-1.0);
    return {{"points_mm", points}, {"delta_mm", delta}, {"distance_mm", length},
            {"azimuth_deg", planar <= 1e-7 ? Json(nullptr) : Json(std::atan2(delta[1], delta[0]) * toDegrees)},
            {"elevation_deg", length <= 1e-7 ? Json(nullptr) : Json(std::atan2(delta[2], planar) * toDegrees)}};
}
}

SmartDimensionDialog::SmartDimensionDialog(wxWindow* parent, const Json& context, const Json& scene,
                                           const Json& selection, DialogGateway gateway)
    : ProjectSetupDialog(parent, "스마트 치수", context, std::move(gateway)), m_context(context), m_scene(scene)
{
    SetName("smart.dimension");
    StudioTheme::ApplyTypography(*this);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* workspace = new wxBoxSizer(wxHORIZONTAL);
    auto* fields = new wxBoxSizer(wxVERTICAL);
    auto* form = new wxFlexGridSizer(2, FromDIP(8), FromDIP(8));
    form->AddGrowableCol(1, 1);
    m_records = Choice(this, form, "저장 치수", "smart.dimension.records");
    m_records->Append(Display("새 치수"));
    for (const auto& row : m_context.at("items"))
    {
        const auto mode = row.at("mode") == "driving" ? " [구동]" : " [참조]";
        m_records->Append(Display(row.at("name").get<std::string>() + mode));
    }
    m_records->SetSelection(0);
    m_kind = Choice(this, form, "기준 종류", "smart.dimension.kind");
    m_kind->Append(Display("두 홀 중심"));
    m_kind->Append(Display("급전 양단"));
    m_kind->SetSelection(0);
    m_first = Choice(this, form, "기준 홀 A", "smart.dimension.first");
    m_second = Choice(this, form, "이동 홀 B", "smart.dimension.second");
    m_port = Choice(this, form, "급전", "smart.dimension.port");
    for (auto* choice : {m_first, m_second, m_port})
    {
        choice->Append(Display("선택하세요"));
        choice->SetSelection(0);
        choice->SetMinSize(FromDIP(wxSize(212, -1)));
    }
    for (const auto& row : m_context.at("holes"))
    {
        m_first->Append(Display(row.at("name").get<std::string>()));
        m_second->Append(Display(row.at("name").get<std::string>()));
    }
    for (const auto& row : m_context.at("ports"))
    {
        m_port->Append(Display(row.at("name").get<std::string>()));
    }
    m_mode = Choice(this, form, "모드", "smart.dimension.mode");
    m_mode->Append(Display("참조 치수"));
    m_mode->Append(Display("구동 치수"));
    m_mode->SetSelection(0);
    m_name = Input(this, form, "이름", "smart.dimension.name");
    m_name->ChangeValue(Display("새 치수"));
    m_name->SetMaxLength(256);
    m_target = Input(this, form, "구동 거리 (mm)", "smart.dimension.target");
    fields->Add(form, 0, wxEXPAND | wxBOTTOM, FromDIP(12));
    m_summary = new wxTextCtrl(this, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(370, 174)),
                               wxTE_MULTILINE | wxTE_READONLY);
    m_summary->SetName("smart.dimension.measurement");
    fields->Add(m_summary, 1, wxEXPAND);
    workspace->Add(fields, 0, wxEXPAND | wxRIGHT, FromDIP(12));
    m_canvas = new DesignCanvas(this);
    m_canvas->SetName("smart.dimension.canvas");
    m_canvas->SetEditingEnabled(false);
    m_canvas->SetScene(m_scene);
    m_canvas->Bind(wxEVT_LEFT_DOWN, &SmartDimensionDialog::Pick, this);
    workspace->Add(m_canvas, 1, wxEXPAND);
    layout->Add(workspace, 1, wxEXPAND | wxBOTTOM, FromDIP(8));

    m_status = new wxStaticText(this, wxID_ANY, wxEmptyString);
    m_status->SetName("smart.dimension.status");
    layout->Add(m_status, 0, wxEXPAND | wxBOTTOM, FromDIP(8));
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    m_preview = new wxButton(this, wxID_ANY, Display("미리 보기"));
    m_preview->SetName("smart.dimension.preview");
    m_remove = new wxButton(this, wxID_ANY, Display("삭제 검토"));
    m_remove->SetName("smart.dimension.remove");
    m_apply = new wxButton(this, wxID_ANY, Display("적용"));
    m_apply->SetName("smart.dimension.apply");
    auto* close = new wxButton(this, wxID_CANCEL, Display("닫기"));
    for (auto* button : {m_preview, m_remove, m_apply, close})
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

    const auto identity = selection.value("id", Json(nullptr));
    const int port = FindId(m_context.at("ports"), identity);
    const int hole = FindId(m_context.at("holes"), identity);
    if (port)
    {
        m_kind->SetSelection(1);
        m_port->SetSelection(port);
    }
    else if (hole)
    {
        m_first->SetSelection(hole);
    }

    m_records->Bind(wxEVT_CHOICE, [this](wxCommandEvent&)
    {
        if (m_mutating || !ConfirmDiscard())
        {
            m_records->SetSelection(m_record);
            return;
        }
        m_record = m_records->GetSelection();
        LoadRecord();
    });
    for (auto* choice : {m_kind, m_first, m_second, m_port, m_mode})
    {
        choice->Bind(wxEVT_CHOICE, [this](wxCommandEvent&)
        {
            m_firstPort = m_firstEnd = wxNOT_FOUND;
            if (m_mode->GetSelection() == 1 && m_target->GetValue().empty())
            {
                const auto metrics = Measure(Points());
                if (metrics.is_object())
                {
                    m_target->ChangeValue(Display(Format(metrics.at("distance_mm"))));
                }
            }
            ChangeInputs();
        });
    }
    for (auto* text : {m_name, m_target})
    {
        text->Bind(wxEVT_TEXT, [this](wxCommandEvent&)
        {
            ChangeInputs();
        });
    }
    m_preview->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        Preview(false);
    });
    m_remove->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        Preview(true);
    });
    m_apply->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        Apply();
    });
    ShowSelection();
}

bool SmartDimensionDialog::HasDraft() const
{
    return m_dirty;
}

Json SmartDimensionDialog::Anchors() const
{
    Json ids = Json::array();
    if (m_kind->GetSelection() == 0)
    {
        for (const auto* choice : {m_first, m_second})
        {
            const int selected = choice->GetSelection();
            if (selected > 0)
            {
                ids.push_back(m_context.at("holes").at(selected - 1).at("id"));
            }
        }
        if (ids.size() != 2 || ids.at(0) == ids.at(1))
        {
            return nullptr;
        }
        return {{"kind", "holes"}, {"ids", ids}};
    }
    const int selected = m_port->GetSelection();
    if (selected <= 0)
    {
        return nullptr;
    }
    return {{"kind", "feed"}, {"ids", Json::array({m_context.at("ports").at(selected - 1).at("id")})}};
}

Json SmartDimensionDialog::Points() const
{
    if (m_record > 0)
    {
        const auto& measured = m_context.at("items").at(m_record - 1).at("measurement");
        return measured.is_object() ? measured.at("points_mm") : Json::array();
    }
    if (!Anchors().is_object())
    {
        return Json::array();
    }
    if (m_kind->GetSelection() == 1)
    {
        const auto& measured = m_context.at("ports").at(m_port->GetSelection() - 1).at("measurement");
        return measured.is_object() ? measured.at("points_mm") : Json::array();
    }
    const auto& holes = m_context.at("holes");
    return Json::array({holes.at(m_first->GetSelection() - 1).at("point_mm"),
                        holes.at(m_second->GetSelection() - 1).at("point_mm")});
}

void SmartDimensionDialog::LoadRecord()
{
    InvalidateRead();
    m_review = nullptr;
    m_dirty = false;
    m_firstPort = m_firstEnd = wxNOT_FOUND;
    m_canvas->SetScene(m_scene);
    m_first->SetSelection(0);
    m_second->SetSelection(0);
    m_port->SetSelection(0);
    m_kind->SetSelection(0);
    m_mode->SetSelection(0);
    m_name->ChangeValue(Display("새 치수"));
    m_target->ChangeValue("");
    if (m_record > 0)
    {
        const auto& row = m_context.at("items").at(m_record - 1);
        const auto& anchor = row.at("anchors");
        const auto& ids = anchor.at("ids");
        if (anchor.at("kind") == "feed")
        {
            m_kind->SetSelection(1);
            m_port->SetSelection(FindId(m_context.at("ports"), ids.at(0)));
        }
        else
        {
            m_first->SetSelection(FindId(m_context.at("holes"), ids.at(0)));
            m_second->SetSelection(FindId(m_context.at("holes"), ids.at(1)));
        }
        m_name->ChangeValue(Display(row.at("name").get<std::string>()));
        if (row.at("mode") == "driving")
        {
            m_mode->SetSelection(1);
            m_target->ChangeValue(Display(row.at("target_mm").dump()));
        }
    }
    ShowSelection();
}

void SmartDimensionDialog::ChangeInputs()
{
    InvalidateRead();
    m_dirty = true;
    if (!m_review.is_null())
    {
        m_canvas->SetScene(m_scene);
    }
    m_review = nullptr;
    ShowSelection();
}

void SmartDimensionDialog::ShowSelection()
{
    Present(Measure(Points()), m_mode->GetSelection() ? "현재 형상 (구동 치수)" : "현재 형상 (참조 치수)");
    SetStatus(m_kind->GetSelection() == 0 ? "2D에서 홀 중심을 차례대로 찍거나 목록에서 선택하세요."
                                         : "2D에서 같은 급전의 양단을 차례대로 찍거나 목록에서 선택하세요.");
    UpdateActions();
}

void SmartDimensionDialog::Present(const Json& measurement, const std::string& heading)
{
    Draw(measurement);
    if (measurement.is_null())
    {
        std::string reason;
        if (m_record > 0)
        {
            reason = m_context.at("items").at(m_record - 1).value("reason", "");
        }
        else if (m_kind->GetSelection() == 1 && m_port->GetSelection() > 0)
        {
            reason = m_context.at("ports").at(m_port->GetSelection() - 1).value("reason", "");
        }
        m_summary->ChangeValue(Display(reason.empty() ? "두 기준점을 선택하세요." : reason));
        return;
    }

    const auto& delta = measurement.at("delta_mm");
    std::string text = heading + "\n거리  " + Format(measurement.at("distance_mm")) + " mm\n"
        "A에서 B 방향  X " + Format(delta.at(0)) + ", Y " + Format(delta.at(1)) + ", Z " +
        Format(delta.at(2)) + " mm\nXY 방향각  " + Format(measurement.at("azimuth_deg")) +
        " deg, 기울기 " + Format(measurement.at("elevation_deg")) + " deg\n";
    if (m_kind->GetSelection() == 1 && m_port->GetSelection() > 0)
    {
        const auto& port = m_context.at("ports").at(m_port->GetSelection() - 1);
        text += "A 기준단  " + port.at("reference_name").get<std::string>() +
            "\nB 신호단  " + port.at("positive_name").get<std::string>() + "\n";
        if (m_mode->GetSelection() == 1 && !port.at("drive_reason").get<std::string>().empty())
        {
            text += port.at("drive_reason").get<std::string>();
        }
    }
    else
    {
        text += "구동 시 A는 고정하고 B를 옮깁니다.";
    }
    m_summary->ChangeValue(Display(text));
}

void SmartDimensionDialog::Draw(const Json& measurement)
{
    m_canvas->SetInspection({}, std::nullopt);
    if (measurement.is_null())
    {
        m_canvas->SetDimensions(Json::array());
        return;
    }
    m_canvas->SetDimensions(Json::array({{{"independent", true}, {"anchors_mm", measurement.at("points_mm")},
        {"value", measurement.at("distance_mm")}, {"unit", "mm"}, {"label", m_mode->GetSelection() ? "구동" : "참조"}}}));
}

void SmartDimensionDialog::Pick(wxMouseEvent& event)
{
    if (m_record != 0 || !Editable())
    {
        event.Skip();
        return;
    }
    const wxPoint pixel = event.GetPosition();
    m_canvas->SetFocus();
    int found = wxNOT_FOUND, endpoint = wxNOT_FOUND;
    double best = FromDIP(13);
    const auto hit = [this, pixel, &best](const Json& point)
    {
        const auto screen = m_canvas->WorldToScreen({point.at(0).get<double>(), point.at(1).get<double>()});
        const double distance = std::hypot(static_cast<double>(screen.x - pixel.x), static_cast<double>(screen.y - pixel.y));
        if (distance >= best)
        {
            return false;
        }
        best = distance;
        return true;
    };
    if (m_kind->GetSelection() == 0)
    {
        const auto& rows = m_context.at("holes");
        for (std::size_t index = 0; index < rows.size(); ++index)
        {
            if (hit(rows.at(index).at("point_mm")))
            {
                found = static_cast<int>(index) + 1;
            }
        }
        if (found == wxNOT_FOUND)
        {
            return;
        }
        if (m_first->GetSelection() > 0 && m_second->GetSelection() == 0 && found != m_first->GetSelection())
        {
            m_second->SetSelection(found);
        }
        else
        {
            m_first->SetSelection(found);
            m_second->SetSelection(0);
        }
        ChangeInputs();
        if (m_second->GetSelection() == 0)
        {
            const auto& point = rows.at(found - 1).at("point_mm");
            m_canvas->SetInspection({}, wxPoint2DDouble(point.at(0), point.at(1)));
            SetStatus("기준 홀 A를 선택했습니다. 이동 홀 B를 선택하세요.");
        }
        return;
    }

    const auto& ports = m_context.at("ports");
    for (std::size_t index = 0; index < ports.size(); ++index)
    {
        const auto& measured = ports.at(index).at("measurement");
        if (measured.is_null())
        {
            continue;
        }
        for (int side = 0; side < 2; ++side)
        {
            if (hit(measured.at("points_mm").at(side)))
            {
                found = static_cast<int>(index) + 1;
                endpoint = side;
            }
        }
    }
    if (found == wxNOT_FOUND)
    {
        return;
    }
    if (m_firstPort == found && m_firstEnd != endpoint)
    {
        m_port->SetSelection(found);
        m_firstPort = m_firstEnd = wxNOT_FOUND;
        ChangeInputs();
        return;
    }
    m_port->SetSelection(0);
    m_firstPort = found;
    m_firstEnd = endpoint;
    ChangeInputs();
    const auto& point = ports.at(found - 1).at("measurement").at("points_mm").at(endpoint);
    m_canvas->SetInspection({}, wxPoint2DDouble(point.at(0), point.at(1)));
    SetStatus("같은 급전의 반대쪽 단자를 선택하세요.");
}

void SmartDimensionDialog::Preview(bool remove)
{
    Json input{{"expected_revision", m_revision}, {"operation", remove ? "remove" : "save"}};
    const auto identity = m_record > 0 ? m_context.at("items").at(m_record - 1).at("id") : Json(nullptr);
    if (remove)
    {
        input["id"] = identity;
    }
    else
    {
        const auto anchors = m_record > 0 ? m_context.at("items").at(m_record - 1).at("anchors") : Anchors();
        const bool driving = m_mode->GetSelection() == 1;
        double value = 0;
        if (driving && (!m_target->GetValue().ToDouble(&value) || !std::isfinite(value) || value <= 0))
        {
            SetStatus("양수 구동 거리를 mm로 입력하세요.");
            m_target->SetFocus();
            return;
        }
        input["record"] = {{"id", identity}, {"name", m_name->GetValue().utf8_string()}, {"anchors", anchors},
                           {"mode", driving ? "driving" : "reference"}, {"target_mm", driving ? Json(value) : Json(nullptr)}};
    }
    m_review = nullptr;
    m_canvas->SetScene(m_scene);
    Request("precision.smart.preview", input, false, [this, input, remove](const Json& result)
    {
        if (!result.at("can_apply").get<bool>())
        {
            Present(Measure(Points()), "현재 형상");
            SetStatus(result.at("message").get<std::string>());
            return;
        }
        m_review = result;
        m_reviewInput = input;
        m_dirty = true;
        if (result.at("scene").is_object())
        {
            m_canvas->SetScene(result.at("scene"));
        }
        if (remove)
        {
            Draw(nullptr);
            m_summary->ChangeValue(Display("치수 기록을 삭제합니다. 현재 형상은 유지됩니다."));
        }
        else
        {
            Present(result.at("measurement"), "적용 후 미리 보기");
        }
        SetStatus("검토한 후보를 적용하면 현재 프로젝트 개정에 기록합니다.");
    });
}

void SmartDimensionDialog::Apply()
{
    auto input = m_reviewInput;
    input["review_hash"] = m_review.at("review_hash");
    input["command_id"] = Uuid();
    Request("precision.smart.apply", input, true, [this](const Json& result)
    {
        AcceptMutation(result);
        m_dirty = false;
        CloseDialog(true);
    });
}

void SmartDimensionDialog::UpdateActions()
{
    const bool edit = Editable();
    const bool free = edit && m_record == 0;
    const bool holes = m_kind->GetSelection() == 0;
    const bool driving = m_mode->GetSelection() == 1;
    m_records->Enable(!m_mutating);
    m_kind->Enable(free);
    m_first->Enable(free && holes);
    m_second->Enable(free && holes);
    m_port->Enable(free && !holes);
    m_mode->Enable(edit);
    m_name->Enable(edit);
    m_target->Enable(edit && driving);
    m_preview->Enable(edit && !m_pending && (m_record > 0 || Points().size() == 2) &&
                      !m_name->GetValue().Strip(wxString::both).empty());
    m_remove->Enable(edit && !m_pending && m_record > 0);
    m_apply->Enable(edit && !m_pending && m_review.is_object());
}
