/** @file @brief 수치 계산 없이 정밀 편집 입력과 읽기 전용 후보를 연결한다. */
#include "precision_dialog.h"
#include "design_canvas.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/wx.h>
#include <wx/checklst.h>
#include <wx/scrolwin.h>
#include <wx/display.h>
#include <cmath>

PrecisionDialog::PrecisionDialog(wxWindow* parent, const Json& context, const Json& objects, const Json& scene, DialogGateway gateway)
    : ProjectSetupDialog(parent, "정밀 2D 편집", context, std::move(gateway)), m_context(context),
      m_objects(objects), m_originalScene(scene)
{
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* heading = new wxStaticText(this, wxID_ANY, Display("치수, 회전, 미러 및 평면 연산"));
    StudioTheme::Heading(*heading);
    layout->Add(heading, 0, wxALL, FromDIP(12));
    auto* body = new wxBoxSizer(wxHORIZONTAL);
    auto* left = new wxBoxSizer(wxVERTICAL);
    left->Add(new wxStaticText(this, wxID_ANY, Display("대상 도형 (최대 16개)")), 0, wxBOTTOM, FromDIP(8));
    m_selection = new wxCheckListBox(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(195, 240)));
    m_selection->SetName("precision.selection");
    for (const auto& object : m_objects)
    {
        const auto index = m_selection->Append(Display(object.at("label").get<std::string>()));
        for (const auto& selected : context.at("selection"))
        {
            if (selected.at("id") == object.at("id"))
            {
                m_selection->Check(index);
            }
        }
    }
    left->Add(m_selection, 1, wxEXPAND);
    auto* notice = new wxStaticText(this, wxID_ANY, Display("빼기: 목록에서 가장 위에\n있는 체크 도형에서 나머지를\n뺍니다. 클릭 순서가 아닙니다."));
    left->Add(notice, 0, wxTOP, FromDIP(8));
    body->Add(left, 0, wxEXPAND | wxALL, FromDIP(12));
    m_canvas = new DesignCanvas(this);
    m_canvas->SetMinSize(FromDIP(wxSize(280, 260)));
    m_canvas->SetEditingEnabled(false);
    body->Add(m_canvas, 1, wxEXPAND | wxTOP | wxBOTTOM, FromDIP(12));
    auto* right = new wxBoxSizer(wxVERTICAL);
    m_operation = new wxChoice(this, wxID_ANY);
    m_operation->SetName("precision.operation");
    right->Add(new wxStaticText(this, wxID_ANY, Display("편집 작업")), 0, wxBOTTOM, FromDIP(8));
    right->Add(m_operation, 0, wxEXPAND | wxBOTTOM, FromDIP(12));
    auto* scroll = new wxScrolledWindow(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(290, 280)), wxVSCROLL);
    scroll->SetScrollRate(0, FromDIP(12));
    auto* scrollSizer = new wxBoxSizer(wxVERTICAL);
    m_fields = new wxPanel(scroll);
    scrollSizer->Add(m_fields, 1, wxEXPAND);
    scroll->SetSizer(scrollSizer);
    right->Add(scroll, 1, wxEXPAND);
    right->Add(new wxStaticText(this, wxID_ANY, Display("변경 이유 또는 메모")), 0, wxTOP | wxBOTTOM, FromDIP(8));
    m_reason = new wxTextCtrl(this, wxID_ANY, wxEmptyString);
    m_reason->SetName("precision.reason");
    right->Add(m_reason, 0, wxEXPAND);
    body->Add(right, 0, wxEXPAND | wxALL, FromDIP(12));
    layout->Add(body, 1, wxEXPAND);
    m_summary = new wxTextCtrl(this, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 95)), wxTE_MULTILINE | wxTE_READONLY);
    layout->Add(m_summary, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    m_status = new wxStaticText(this, wxID_ANY, Display("현재 형상입니다. 대상과 치수를 입력하고 후보를 검토하세요."));
    layout->Add(m_status, 0, wxEXPAND | wxALL, FromDIP(12));
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    actions->AddStretchSpacer();
    auto* close = new wxButton(this, wxID_CANCEL, Display("닫기"));
    m_preview = new wxButton(this, wxID_ANY, Display("후보 검토"));
    m_preview->SetName("precision.preview");
    m_apply = new wxButton(this, wxID_APPLY, Display("검토한 후보 적용"));
    m_apply->SetName("precision.apply");
    for (auto* button : {close, m_preview, m_apply})
    {
        actions->Add(button, 0, wxLEFT, FromDIP(8));
    }
    layout->Add(actions, 0, wxEXPAND | wxALL, FromDIP(12));
    SetSizer(layout);
    const int display = wxDisplay::GetFromWindow(parent);
    const wxSize area = wxDisplay(display == wxNOT_FOUND ? 0U : static_cast<unsigned int>(display)).GetClientArea().GetSize();
    const wxSize available(std::max(320, area.x - FromDIP(32)), std::max(300, area.y - FromDIP(48)));
    SetMinSize(wxSize(std::min(FromDIP(870), available.x), std::min(FromDIP(570), available.y)));
    SetSize(wxSize(std::min(FromDIP(1160), available.x), std::min(FromDIP(790), available.y)));
    CentreOnParent();
    LoadContext(context);
    m_operation->Bind(wxEVT_CHOICE, [this](wxCommandEvent&) { BuildFields(); ChangeInputs(); });
    m_reason->Bind(wxEVT_TEXT, [this](wxCommandEvent&) { m_dirty = true; });
    m_selection->Bind(wxEVT_CHECKLISTBOX, [this](wxCommandEvent&)
    {
        ChangeInputs();
        m_context["operations"] = Json::array();
        UpdateActions();
        Request("precision.get", {{"expected_revision", m_revision}, {"selection_ids", SelectionIds()}}, false,
                [this](const Json& result) { LoadContext(result); });
    });
    m_preview->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { Preview(); });
    m_apply->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { Apply(); });
    close->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { CloseDialog(); });
    UpdateActions();
    // @brief 최종 sizer 크기에서 첫 장면을 맞춰 생성 직후 임시 크기의 축소 배율을 남기지 않는다.
    Layout();
    m_canvas->SetScene(scene);
    m_canvas->FitView();
}

Json PrecisionDialog::SelectionIds() const
{
    Json ids = Json::array();
    for (unsigned index = 0; index < m_selection->GetCount(); ++index)
    {
        if (m_selection->IsChecked(index))
        {
            ids.push_back(m_objects.at(index).at("id"));
        }
    }
    return ids;
}

void PrecisionDialog::LoadContext(const Json& context)
{
    const auto old = m_operation->GetSelection();
    const std::string operation = old >= 0 && static_cast<std::size_t>(old) < m_context.at("operations").size()
        ? m_context.at("operations").at(old).value("id", "") : "";
    m_context = context;
    m_operation->Clear();
    int selected = 0;
    for (const auto& item : context.at("operations"))
    {
        const int index = m_operation->Append(Display(item.at("label").get<std::string>()));
        if (item.at("id") == operation)
        {
            selected = index;
        }
    }
    if (!m_operation->IsEmpty())
    {
        m_operation->SetSelection(selected);
    }
    BuildFields();
    std::string summary = "현재 개정의 연관 치수\n";
    for (const auto& dimension : context.at("dimensions"))
    {
        summary += dimension.at("label").get<std::string>() + ": " +
            (dimension.at("value").is_null() ? "미정" : dimension.at("value").dump()) + " " + dimension.at("unit").get<std::string>();
        if (!dimension.value("parameter_id", Json()).is_null())
        {
            summary += " (매개변수 연결)";
        }
        summary += "\n";
    }
    m_summary->ChangeValue(Display(summary));
    UpdateActions();
}

void PrecisionDialog::BuildFields()
{
    m_loadingFields = true;
    m_fields->DestroyChildren();
    m_numbers.clear();
    m_dimension = nullptr;
    m_parameter = nullptr;
    m_axis = nullptr;
    m_trimTarget = nullptr;
    m_patternExclusions = nullptr;
    m_join = nullptr;
    m_unit = nullptr;
    m_dimensionNote = nullptr;
    m_parameterIds.clear();
    auto* layout = new wxBoxSizer(wxVERTICAL);
    m_fields->SetSizer(layout);
    const auto row = [this, layout](const std::string& label, wxWindow* control)
    {
        layout->Add(new wxStaticText(m_fields, wxID_ANY, Display(label)), 0, wxBOTTOM, FromDIP(4));
        layout->Add(control, 0, wxEXPAND | wxBOTTOM, FromDIP(12));
    };
    const auto number = [this, row](const std::string& key, const std::string& label, const std::string& value)
    {
        auto* input = new wxTextCtrl(m_fields, wxID_ANY, Display(value));
        input->SetName(Display("precision." + key));
        m_numbers[key] = input;
        row(label, input);
        input->Bind(wxEVT_TEXT, [this](wxCommandEvent&) { ChangeInputs(); });
    };
    const int index = m_operation->GetSelection();
    if (index < 0 || static_cast<std::size_t>(index) >= m_context.at("operations").size())
    {
        m_loadingFields = false;
        return;
    }
    const auto& operation = m_context.at("operations").at(index);
    const std::string id = operation.at("id");
    if (id == "rotate")
    {
        number("pivot_x_mm", "회전 중심 X (mm)", "0");
        number("pivot_y_mm", "회전 중심 Y (mm)", "0");
        number("angle_deg", "회전각 (deg, 반시계 양수)", "90");
    }
    else if (id == "mirror")
    {
        m_axis = new wxChoice(m_fields, wxID_ANY);
        m_axis->Append(Display("수평축 Y = 위치"));
        m_axis->Append(Display("수직축 X = 위치"));
        m_axis->SetSelection(0);
        row("대칭축 (층은 바꾸지 않음)", m_axis);
        m_axis->Bind(wxEVT_CHOICE, [this](wxCommandEvent&) { ChangeInputs(); });
        number("offset_mm", "축 위치 (mm)", "0");
    }
    else if (id == "linear_pattern" || id == "circular_pattern" ||
             id == "edit_linear_pattern" || id == "edit_circular_pattern")
    {
        const Json previous = operation.value("values", Json::object());
        const auto initial = [&previous](const std::string& key, const std::string& fallback)
        {
            return previous.contains(key) ? previous.at(key).dump() : fallback;
        };
        number("count", "반복 수 (원본 포함)", initial("count", "3"));
        if (id == "linear_pattern" || id == "edit_linear_pattern")
        {
            number("dx_mm", "X 피치 (mm)", initial("dx_mm", "2"));
            number("dy_mm", "Y 피치 (mm)", initial("dy_mm", "0"));
        }
        else
        {
            number("pivot_x_mm", "회전 중심 X (mm)", initial("pivot_x_mm", "0"));
            number("pivot_y_mm", "회전 중심 Y (mm)", initial("pivot_y_mm", "0"));
            number("step_deg", "회전 간격 (deg, 반시계 양수)", initial("step_deg", "90"));
        }
        wxString disabled;
        for (const auto& value : previous.value("excluded_instances", Json::array()))
        {
            if (!disabled.empty())
            {
                disabled += ", ";
            }
            disabled += wxString::Format("%d", value.get<int>());
        }
        m_patternExclusions = new wxTextCtrl(m_fields, wxID_ANY, disabled);
        m_patternExclusions->SetName("precision.excluded_instances");
        row("제외할 순번 (예: 2, 4. 원본은 1)", m_patternExclusions);
        m_patternExclusions->Bind(wxEVT_TEXT, [this](wxCommandEvent&) { ChangeInputs(); });
    }
    else if (id == "copper_pour")
    {
        const Json previous = operation.value("values", Json::object());
        number("clearance_mm", "다른 넷과 금지 영역 간격 (mm)", previous.value("clearance_mm", Json(0.25)).dump());
        number("tolerance_mm", "곡선 다각형 근사 허용값 (mm)", previous.value("tolerance_mm", Json(0.01)).dump());
    }
    else if (id == "curve_chamfer")
    {
        const auto& selection = m_context.at("selection");
        if (selection.size() == 2)
        {
            number("first_setback_mm", selection[0].at("label").get<std::string>() + " 절삭 길이 (mm)", "1");
            number("second_setback_mm", selection[1].at("label").get<std::string>() + " 절삭 길이 (mm)", "1");
        }
    }
    else if (id == "line_fillet" || id == "curved_fillet")
    {
        number("radius_mm", "필렛 반경 (mm)", "1");
    }
    else if ((id == "curve_trim" || id == "extend_to_boundary") && operation.at("enabled") == true)
    {
        m_trimTarget = new wxChoice(m_fields, wxID_ANY);
        m_trimTarget->SetName("precision.trim_target");
        for (const auto& item : m_context.at("selection"))
        {
            m_trimTarget->Append(Display(item.at("label")));
        }
        m_trimTarget->SetSelection(0);
        row(id == "curve_trim" ? "자를 도체" : "연장할 도체", m_trimTarget);
        m_trimTarget->Bind(wxEVT_CHOICE, [this](wxCommandEvent&) { ChangeInputs(); });
        m_axis = new wxChoice(m_fields, wxID_ANY);
        m_axis->SetName("precision.trim_keep");
        m_axis->Append(Display(id == "curve_trim" ? "시작점에서 마지막 교차점까지 남기기" : "시작점에서 바깥으로 연장"));
        m_axis->Append(Display(id == "curve_trim" ? "첫 교차점에서 끝점까지 남기기" : "끝점에서 바깥으로 연장"));
        m_axis->SetSelection(0);
        row(id == "curve_trim" ? "남길 부분" : "연장 방향", m_axis);
        m_axis->Bind(wxEVT_CHOICE, [this](wxCommandEvent&) { ChangeInputs(); });
    }
    else if (id == "curve_split")
    {
        number("percent", "시작점부터의 중심선 길이 (%)", "50");
    }
    else if (id == "curve_extend")
    {
        number("distance_mm", "중심선 연장 길이 (mm)", "1");
        m_axis = new wxChoice(m_fields, wxID_ANY);
        m_axis->SetName("precision.extend_endpoint");
        m_axis->Append(Display("시작점"));
        m_axis->Append(Display("끝점"));
        m_axis->SetSelection(1);
        row("연장할 끝", m_axis);
        m_axis->Bind(wxEVT_CHOICE, [this](wxCommandEvent&) { ChangeInputs(); });
    }
    else if (id == "arc_offset")
    {
        number("distance_mm", "중심선 오프셋 (mm, 양수: 반경 증가)", "1");
    }
    else if (id == "offset")
    {
        number("distance_mm", "오프셋 (mm, 양수: 확장)", "1");
        m_join = new wxChoice(m_fields, wxID_ANY);
        m_join->Append(Display("모서리 교차 연장"));
        m_join->Append(Display("모서리 절단"));
        m_join->SetSelection(0);
        row("모서리 처리", m_join);
        m_join->Bind(wxEVT_CHOICE, [this](wxCommandEvent&) { ChangeInputs(); });
        number("mitre_limit", "모서리 연장 한계 (비율)", "5");
    }
    else if (id == "dimension_set" || id == "bind_dimension")
    {
        m_dimension = new wxChoice(m_fields, wxID_ANY);
        for (const auto& dimension : m_context.at("dimensions"))
        {
            m_dimension->Append(Display(dimension.at("label").get<std::string>()));
        }
        row("연관 치수", m_dimension);
        if (!m_dimension->IsEmpty())
        {
            m_dimension->SetSelection(0);
        }
        if (id == "dimension_set")
        {
            number("value", "새 값 (미정은 빈칸으로 표시)", "");
            m_unit = new wxChoice(m_fields, wxID_ANY);
            row("입력 단위", m_unit);
            m_unit->Bind(wxEVT_CHOICE, [this](wxCommandEvent&) { ChangeInputs(); });
        }
        else
        {
            m_parameter = new wxChoice(m_fields, wxID_ANY);
            row("연결할 매개변수", m_parameter);
            m_parameter->Bind(wxEVT_CHOICE, [this](wxCommandEvent&) { ChangeInputs(); });
        }
        m_dimensionNote = new wxStaticText(m_fields, wxID_ANY, wxEmptyString);
        layout->Add(m_dimensionNote, 0, wxEXPAND | wxBOTTOM, FromDIP(8));
        const auto choose = [this]()
        {
            const int selected = m_dimension->GetSelection();
            if (selected < 0)
            {
                return;
            }
            const auto& dimension = m_context.at("dimensions").at(selected);
            const std::string unit = dimension.at("unit");
            m_dimensionNote->SetLabel(Display(dimension.value("read_only_reason", "")));
            m_dimensionNote->Wrap(FromDIP(265));
            if (m_unit)
            {
                m_unit->Clear();
                m_unit->Append(Display(unit));
                m_unit->SetSelection(0);
                m_numbers.at("value")->ChangeValue(dimension.at("value").is_null() ? wxString() : Display(dimension.at("value").dump()));
            }
            if (m_parameter)
            {
                m_parameter->Clear();
                m_parameterIds.clear();
                for (const auto& parameter : m_context.at("parameters"))
                {
                    if (parameter.value("dimension", "") == (unit == "deg" ? "angle" : "length") &&
                        parameter.value("status", "") != "missing")
                    {
                        m_parameter->Append(Display(parameter.at("label").get<std::string>()));
                        m_parameterIds.push_back(parameter.at("id").get<std::string>());
                    }
                }
                if (!m_parameter->IsEmpty())
                {
                    m_parameter->SetSelection(0);
                }
            }
            m_fields->Layout();
            m_fields->GetParent()->FitInside();
            ChangeInputs();
        };
        m_dimension->Bind(wxEVT_CHOICE, [choose](wxCommandEvent&) { choose(); });
        choose();
    }
    auto* note = new wxStaticText(m_fields, wxID_ANY, Display(operation.value("reason", "")));
    note->Wrap(FromDIP(265));
    layout->Add(note, 0, wxEXPAND | wxBOTTOM, FromDIP(8));
    m_fields->Layout();
    m_fields->GetParent()->FitInside();
    Layout();
    m_loadingFields = false;
}

void PrecisionDialog::ChangeInputs()
{
    if (m_loadingFields)
    {
        return;
    }
    InvalidateRead();
    m_review = nullptr;
    m_reviewInput = nullptr;
    m_dirty = true;
    m_canvas->SetScene(m_originalScene);
    SetStatus("입력이 바뀌었습니다. 후보를 다시 검토하세요.");
    UpdateActions();
}

Json PrecisionDialog::Input() const
{
    const int index = m_operation->GetSelection();
    if (index < 0 || static_cast<std::size_t>(index) >= m_context.at("operations").size())
    {
        throw std::runtime_error("편집 작업을 선택하세요.");
    }
    Json values = Json::object();
    for (const auto& [key, input] : m_numbers)
    {
        double value = 0;
        if (!input->GetValue().ToDouble(&value) || !std::isfinite(value))
        {
            input->SetFocus();
            throw std::runtime_error("유한한 수치를 입력하세요. 미정 치수를 임의의 0으로 채우지 않습니다.");
        }
        values[key] = value;
    }
    if (m_patternExclusions && !m_patternExclusions->GetValue().Strip(wxString::both).empty())
    {
        Json skipped = Json::array();
        for (auto number : wxSplit(m_patternExclusions->GetValue(), ','))
        {
            long value = 0;
            if (!number.Strip(wxString::both).ToLong(&value) || value < 2 || value > 16)
            {
                m_patternExclusions->SetFocus();
                throw std::runtime_error("제외할 순번을 2~반복 수 범위의 정수로 입력하세요.");
            }
            skipped.push_back(value);
        }
        values["excluded_instances"] = skipped;
    }
    if (m_trimTarget)
    {
        values["target_id"] = m_context.at("selection").at(m_trimTarget->GetSelection()).at("id");
        const auto key = m_context.at("operations").at(index).at("id") == "curve_trim" ? "keep" : "endpoint";
        values[key] = m_axis->GetSelection() == 0 ? "start" : "end";
    }
    else if (m_axis)
    {
        if (m_context.at("operations").at(index).at("id") == "curve_extend")
        {
            values["endpoint"] = m_axis->GetSelection() == 0 ? "start" : "end";
        }
        else
        {
            values["axis"] = m_axis->GetSelection() == 0 ? "x" : "y";
        }
    }
    if (m_join)
    {
        values["join"] = m_join->GetSelection() == 0 ? "mitre" : "bevel";
    }
    if (m_dimension)
    {
        if (m_dimension->GetSelection() < 0)
        {
            throw std::runtime_error("치수를 선택하세요.");
        }
        values["dimension_key"] = m_context.at("dimensions").at(m_dimension->GetSelection()).at("key");
    }
    if (m_parameter)
    {
        if (m_parameter->GetSelection() < 0)
        {
            throw std::runtime_error("매개변수를 선택하세요.");
        }
        values["parameter_id"] = m_parameterIds.at(m_parameter->GetSelection());
    }
    if (m_unit)
    {
        values["unit"] = Utf8(m_unit->GetStringSelection());
    }
    return {{"expected_revision", m_revision}, {"selection_ids", SelectionIds()},
            {"operation", m_context.at("operations").at(index).at("id")}, {"values", values}};
}

void PrecisionDialog::Preview()
{
    try
    {
        const Json input = Input();
        m_review = nullptr;
        m_reviewInput = nullptr;
        Request("precision.preview", input, false, [this, input](const Json& result)
        {
            m_review = result;
            m_reviewInput = input;
            m_canvas->SetScene(result.at("scene").is_null() ? m_originalScene : result.at("scene"));
            m_canvas->FitView();
            std::string summary = "읽기 전용 후보 (원본에 적용 전)\n";
            for (const auto& change : result.at("changes"))
            {
                const std::string action = change.value("action", "");
                summary += change.value("label", "") + ": " + (action == "remove" ? "교체로 제거" : (action == "create" ? "새 도형" : "수정")) + "\n";
            }
            for (const auto& notice : result.value("notices", Json::array()))
            {
                summary += (notice.is_string() ? notice.get<std::string>() : notice.value("message", notice.dump())) + "\n";
            }
            for (const auto& dimension : result.value("dimensions", Json::array()))
            {
                summary += dimension.value("label", "치수") + ": " +
                    (dimension.at("value").is_null() ? "미정" : dimension.at("value").dump()) + " " + dimension.value("unit", "") + "\n";
            }
            m_summary->ChangeValue(Display(summary));
            SetStatus(result.value("can_apply", false) ? "후보를 확인했습니다. 적용하면 하나의 실행 취소 명령으로 저장됩니다." : "후보를 적용할 수 없습니다. 조건과 안내를 확인하세요.");
        });
    }
    catch (const std::exception& error)
    {
        SetStatus(error.what());
    }
    UpdateActions();
}

void PrecisionDialog::Apply()
{
    if (!Editable() || m_pending || m_review.is_null() || !m_review.value("can_apply", false))
    {
        return;
    }
    Json input = m_reviewInput;
    input["command_id"] = Uuid();
    input["review_hash"] = m_review.at("review_hash");
    input["reason"] = Utf8(m_reason->GetValue());
    Request("precision.apply", input, true, [this](const Json& result)
    {
        AcceptMutation(result);
        m_dirty = false;
        CloseDialog();
    });
}

bool PrecisionDialog::HasDraft() const
{
    return m_dirty;
}

void PrecisionDialog::UpdateActions()
{
    if (!m_preview)
    {
        return;
    }
    const bool editable = Editable() && !m_pending;
    m_selection->Enable(editable);
    m_operation->Enable(editable);
    m_fields->Enable(editable);
    m_reason->Enable(editable);
    const int selected = m_operation->GetSelection();
    const bool operation = selected >= 0 && static_cast<std::size_t>(selected) < m_context.at("operations").size() &&
        m_context.at("operations").at(selected).value("enabled", false);
    bool dimensionAllowed = true;
    if (m_dimension && m_dimension->GetSelection() >= 0)
    {
        const auto& dimension = m_context.at("dimensions").at(m_dimension->GetSelection());
        dimensionAllowed = m_parameter ? dimension.value("binding_supported", false) && !m_parameterIds.empty()
                                       : dimension.value("editable", false);
    }
    m_preview->Enable(editable && operation && dimensionAllowed && !SelectionIds().empty());
    m_apply->Enable(editable && !m_review.is_null() && m_review.value("can_apply", false));
}

void PrecisionDialog::ShowRequestFailure(const Json& error)
{
    m_review = nullptr;
    m_reviewInput = nullptr;
    m_canvas->SetScene(m_originalScene);
    ProjectSetupDialog::ShowRequestFailure(error);
}
