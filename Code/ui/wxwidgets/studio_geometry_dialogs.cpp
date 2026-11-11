/** @file @brief 주 창의 geometry_dialogs 책임을 구현한다. */
#include "studio_internal.h"

/** @brief 키보드만으로 좌표를 지정하며 유한 수치의 판정 후 서비스에 전달한다. */
bool StudioFrame::AskNumbers(const std::string& title, const std::vector<NumericField>& fields, Json& values)
{
    wxDialog dialog(this, wxID_ANY, Display(title), wxDefaultPosition, wxDefaultSize,
                    wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    auto* outer = new wxBoxSizer(wxVERTICAL);
    auto* form = new wxFlexGridSizer(2, 8, 8);
    form->AddGrowableCol(1);
    std::map<std::string, wxTextCtrl*> controls;
    for (const auto& field : fields)
    {
        form->Add(new wxStaticText(&dialog, wxID_ANY, Display(field.label)), 0, wxALIGN_CENTER_VERTICAL);
        auto* input =
            new wxTextCtrl(&dialog, wxID_ANY, wxString::Format("%.12g", values.value(field.key, field.initial)));
        controls[field.key] = input;
        form->Add(input, 1, wxEXPAND);
    }
    outer->Add(form, 1, wxEXPAND | wxALL, 14);
    outer->Add(dialog.CreateSeparatedButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, 10);
    dialog.SetSizerAndFit(outer);
    while (dialog.ShowModal() == wxID_OK)
    {
        bool valid = true;
        for (const auto& item : controls)
        {
            double number = 0;
            if (!item.second->GetValue().ToDouble(&number) || !std::isfinite(number))
            {
                wxMessageBox(Display("유한한 숫자를 입력하세요."), Display(title), wxOK | wxICON_WARNING, &dialog);
                item.second->SetFocus();
                valid = false;
                break;
            }
            values[item.first] = number;
        }
        if (valid)
        {
            return true;
        }
    }
    return false;
}

/** @brief 빈 줄로 구멍을 구분하는 정확한 수치 입력을 단일 생성 명령으로 보낸다. */
void StudioFrame::AddPolygon()
{
    if (m_busy || m_activeLayer.empty() || !ConfirmDiscard())
    {
        return;
    }
    wxDialog dialog(this, wxID_ANY, Display("다각형 도체 면 / mm"), wxDefaultPosition, FromDIP(wxSize(500, 440)),
                    wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* help = new wxStaticText(
        &dialog, wxID_ANY,
        Display("한 줄에 x, y를 입력하세요. 첫 묶음은 외곽, 빈 줄 다음은 구멍입니다.\n마지막 점을 반복하지 않습니다. "
                "총 64점 / 구멍 최대 8개.\n접지 역할, 네트와 재료는 생성 후 속성에서 지정합니다."));
    layout->Add(help, 0, wxEXPAND | wxALL, 12);
    auto* input =
        new wxTextCtrl(&dialog, wxID_ANY, Display(m_polygonDraft), wxDefaultPosition, wxDefaultSize, wxTE_MULTILINE);
    layout->Add(input, 1, wxEXPAND | wxLEFT | wxRIGHT, 12);
    layout->Add(dialog.CreateSeparatedButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, 10);
    dialog.SetSizer(layout);
    while (dialog.ShowModal() == wxID_OK)
    {
        try
        {
            const std::string text = Utf8(input->GetValue());
            Json values = ParsePolygonInput(text);
            values["id"] = Uuid();
            values["layer_id"] = m_activeLayer;
            m_polygonDraft = text;
            CanvasCommand("create_polygon", values);
            return;
        }
        catch (const std::exception& error)
        {
            wxMessageBox(Display(error.what()), Display("다각형 좌표"), wxOK | wxICON_WARNING, &dialog);
            input->SetFocus();
        }
    }
}

/** @brief 원형/회전 사각 패드의 실제 치수를 명시하고 물성을 추정하지 않는다. */
void StudioFrame::AddPad(bool circle)
{
    if (m_busy || m_activeLayer.empty() || !ConfirmDiscard())
    {
        return;
    }
    Json values = Json::object();
    std::vector<NumericField> fields{
        {"x", "중심 X (mm)", 0}, {"y", "중심 Y (mm)", 0}, {"width", circle ? "지름 (mm)" : "폭 (mm)", 2}};
    if (!circle)
    {
        fields.push_back({"height", "높이 (mm)", 2});
        fields.push_back({"rotation", "반시계 회전 (deg)", 0});
    }
    if (AskNumbers(circle ? "원형 패드 치수" : "직사각 패드 치수", fields, values))
    {
        CanvasCommand("create_pad", Json{{"id", Uuid()},
                                         {"layer_id", m_activeLayer},
                                         {"pad_shape", circle ? "circle" : "rectangle"},
                                         {"center", Json::array({values.at("x"), values.at("y")})},
                                         {"width_mm", values.at("width")},
                                         {"height_mm", circle ? values.at("width") : values.at("height")},
                                         {"rotation_deg", circle ? Json(0.0) : values.at("rotation")}});
    }
}

/** @brief 비아의 층 범위와 제작 치수를 입력하며 비운 치수는 미정으로 보존한다. */
void StudioFrame::AddVia()
{
    if (m_busy || m_activeLayer.empty() || !ConfirmDiscard())
    {
        return;
    }
    wxDialog dialog(this, wxID_ANY, Display("도금 비아 / mm"), wxDefaultPosition, wxDefaultSize,
                    wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    layout->Add(
        new wxStaticText(
            &dialog, wxID_ANY,
            Display("시작은 활성 도체층입니다. 적층 순서상 뒤에 있는 끝 도체층을 선택하세요.\n완성 구멍/도금/공구 "
                    "구멍은 서로 다른 값입니다. 빈칸은 미정입니다.\n패드와 도금 물성은 자동으로 생성하지 않습니다.")),
        0, wxEXPAND | wxALL, 12);
    auto* form = new wxFlexGridSizer(2, 8, 8);
    form->AddGrowableCol(1);
    form->Add(new wxStaticText(&dialog, wxID_ANY, Display("끝 도체층")), 0, wxALIGN_CENTER_VERTICAL);
    auto* endLayer = new wxChoice(&dialog, wxID_ANY);
    std::vector<std::string> layerIds;
    bool afterStart = false;
    for (const auto& layer : m_scene.at("layers"))
    {
        if (layer.at("id") == m_activeLayer)
        {
            afterStart = true;
        }
        else if (afterStart && layer.at("role") == "conductor")
        {
            layerIds.push_back(layer.at("id"));
            endLayer->Append(Display(layer.at("label")));
        }
    }
    form->Add(endLayer, 1, wxEXPAND);
    const std::vector<std::pair<std::string, std::string>> names{{"x", "중심 X (mm)"},
                                                                 {"y", "중심 Y (mm)"},
                                                                 {"finished_hole_diameter_mm", "완성 구멍 지름 (mm)"},
                                                                 {"plating_thickness_mm", "도금 두께 (mm)"},
                                                                 {"tool_hole_diameter_mm", "공구 구멍 지름 (mm)"}};
    std::map<std::string, wxTextCtrl*> fields;
    for (const auto& name : names)
    {
        form->Add(new wxStaticText(&dialog, wxID_ANY, Display(name.second)), 0, wxALIGN_CENTER_VERTICAL);
        auto* input = new wxTextCtrl(&dialog, wxID_ANY, name.first == "x" || name.first == "y" ? "0" : "");
        fields[name.first] = input;
        form->Add(input, 1, wxEXPAND);
    }
    layout->Add(form, 0, wxEXPAND | wxLEFT | wxRIGHT, 12);
    layout->Add(new wxStaticText(&dialog, wxID_ANY, Display("연결 패드 (미선택 초안 허용, 물리 검증 전 명시 필요)")), 0,
                wxEXPAND | wxALL, 12);
    auto* pads = new wxCheckListBox(&dialog, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(400, 100)));
    std::vector<std::string> padIds;
    for (const auto& shape : m_scene.at("shapes"))
    {
        if (shape.at("kind") == "pad")
        {
            padIds.push_back(shape.at("id"));
            pads->Append(Display(shape.at("label")));
        }
    }
    layout->Add(pads, 1, wxEXPAND | wxLEFT | wxRIGHT, 12);
    layout->Add(dialog.CreateSeparatedButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, 10);
    dialog.SetSizerAndFit(layout);
    while (dialog.ShowModal() == wxID_OK)
    {
        if (endLayer->GetSelection() == wxNOT_FOUND)
        {
            wxMessageBox(Display("끝 도체층을 선택하세요. 목록이 비어 있으면 적층 순서가 앞선 층을 활성화하거나 "
                                 "도체층을 추가하세요."),
                         Display("비아 층 범위"), wxOK | wxICON_WARNING, &dialog);
            endLayer->SetFocus();
            continue;
        }
        Json values{{"id", Uuid()},
                    {"layer_id", m_activeLayer},
                    {"end_layer_id", layerIds.at(endLayer->GetSelection())},
                    {"pad_ids", Json::array()}};
        bool valid = true;
        for (const auto& field : fields)
        {
            wxString text = field.second->GetValue();
            text.Trim(true).Trim(false);
            if (text.empty() && field.first != "x" && field.first != "y")
            {
                values[field.first] = nullptr;
                continue;
            }
            double number = 0;
            if (!text.ToDouble(&number) || !std::isfinite(number))
            {
                wxMessageBox(Display("좌표에는 유한한 숫자를 입력하세요. 제작 치수의 빈칸은 미정으로 유지합니다."),
                             Display("비아 입력"), wxOK | wxICON_WARNING, &dialog);
                field.second->SetFocus();
                valid = false;
                break;
            }
            values[field.first] = number;
        }
        if (!valid)
        {
            continue;
        }
        values["center"] = Json::array({values.at("x"), values.at("y")});
        values.erase("x");
        values.erase("y");
        for (std::size_t index = 0; index < padIds.size(); ++index)
        {
            if (pads->IsChecked(static_cast<unsigned int>(index)))
            {
                values["pad_ids"].push_back(padIds[index]);
            }
        }
        CanvasCommand("create_via", values);
        return;
    }
}

void StudioFrame::AddCoordinates()
{
    if (m_busy || m_activeLayer.empty() || !ConfirmDiscard())
    {
        return;
    }
    const bool arc = m_drawTool == "arc";
    Json& draft = arc ? m_arcDraft : m_lineDraft;
    std::vector<NumericField> fields;
    if (arc)
    {
        fields = {{"cx", "중심 X (mm)", 20},
                  {"cy", "중심 Y (mm)", 30},
                  {"radius_mm", "반지름 (mm)", 10},
                  {"start_angle_deg", "시작 각도 (deg)", 0},
                  {"sweep_angle_deg", "회전 각도 (deg, +반시계)", 90},
                  {"width_mm", "선폭 (mm)", m_width->GetValue()}};
    }
    else
    {
        fields = {{"x1", "시작 X (mm)", 5},
                  {"y1", "시작 Y (mm)", 5},
                  {"x2", "끝 X (mm)", 25},
                  {"y2", "끝 Y (mm)", 5},
                  {"width_mm", "선폭 (mm)", m_width->GetValue()}};
    }
    if (!AskNumbers(arc ? "원호 좌표 입력" : "선 좌표 입력", fields, draft))
    {
        return;
    }
    Json values{{"id", Uuid()}, {"layer_id", m_activeLayer}, {"width_mm", draft.at("width_mm")}};
    if (arc)
    {
        values["center"] = Json::array({draft.at("cx"), draft.at("cy")});
        for (const auto& key : {"radius_mm", "start_angle_deg", "sweep_angle_deg"})
        {
            values[key] = draft.at(key);
        }
    }
    else
    {
        values["start"] = Json::array({draft.at("x1"), draft.at("y1")});
        values["end"] = Json::array({draft.at("x2"), draft.at("y2")});
    }
    CanvasCommand(arc ? "create_arc" : "create_line", values);
}

/** @brief 잘못된 선폭 입력에는 마지막 유효 표시값을 유지한다. */
void StudioFrame::UpdateStrokeWidth()
{
    const double width = m_width->GetValue();
    if (std::isfinite(width) && width > 0.0 && width <= 1000.0)
    {
        m_canvas->SetStrokeWidth(width);
    }
    else
    {
        m_canvasHint->SetLabel(Display("선폭은 0보다 큰 유한 숫자여야 합니다. 마지막 유효 선폭을 유지합니다."));
    }
}
