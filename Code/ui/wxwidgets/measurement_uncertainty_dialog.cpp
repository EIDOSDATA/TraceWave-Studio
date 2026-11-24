/** @file @brief 불확도의 정의와 적용 범위를 입력하며 k나 상관 가정을 생성하지 않는다. */
#include "measurement_collection_dialog.h"
#include "measurement_model.h"
#include "measurement_quantity_group.h"
#include "studio_support.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/dialog.h>
#include <wx/listbox.h>
#include <wx/msgdlg.h>
#include <wx/scrolwin.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <map>
#include <sstream>
#include <iomanip>

namespace
{
std::string Exact(const Json& value)
{
    if (value.is_string())
    {
        return value.get<std::string>();
    }
    if (value.is_number())
    {
        std::ostringstream stream;
        stream << std::setprecision(17) << value.get<double>();
        return stream.str();
    }
    if (value.is_object() && value.value("text", Json(nullptr)).is_string())
    {
        return value.at("text").get<std::string>();
    }
    return "";
}

bool EditRow(wxWindow* parent, Json& row, const Json& context, DialogGateway gateway)
{
    const auto descriptor = context.value("descriptor", Json::object());
    const auto ports = descriptor.value("port_ids", Json::array());
    const auto names = descriptor.value("port_names", Json::array());
    if (ports.empty())
    {
        wxMessageBox(Display("먼저 원문 자료를 검토하여 실제 자료 포트를 조회하세요."), Display("불확도 적용 대상"),
                     wxOK | wxICON_INFORMATION, parent);
        return false;
    }
    wxDialog dialog(parent, wxID_ANY, Display("불확도 항목"), wxDefaultPosition, parent->FromDIP(wxSize(850, 700)),
                    wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    auto* outer = new wxBoxSizer(wxVERTICAL);
    auto* scroll =
        new wxScrolledWindow(&dialog, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL);
    scroll->SetScrollRate(0, parent->FromDIP(16));
    auto* fields = new wxFlexGridSizer(2, parent->FromDIP(8), parent->FromDIP(12));
    fields->AddGrowableCol(1, 1);
    std::map<std::string, wxTextCtrl*> text;
    std::map<std::string, std::string> originalText;
    std::map<std::string, wxChoice*> choice;
    std::map<std::string, std::vector<std::string>> keys;
    const auto addText = [&](const std::string& key, const std::string& label, const std::string& value)
    {
        fields->Add(new wxStaticText(scroll, wxID_ANY, Display(label)), 0, wxALIGN_CENTER_VERTICAL);
        auto* input = new wxTextCtrl(scroll, wxID_ANY, Display(value));
        input->SetHint(Display("미정"));
        input->SetName(Display("measurement.uncertainty." + key));
        fields->Add(input, 1, wxEXPAND);
        text[key] = input;
        originalText[key] = value;
    };
    const auto addChoice = [&](const std::string& key, const std::string& label,
                               const std::vector<std::pair<std::string, std::string>>& options,
                               const std::string& value)
    {
        fields->Add(new wxStaticText(scroll, wxID_ANY, Display(label)), 0, wxALIGN_CENTER_VERTICAL);
        auto* input = new wxChoice(scroll, wxID_ANY);
        int selection = wxNOT_FOUND;
        for (const auto& option : options)
        {
            const int index = input->Append(Display(option.second));
            keys[key].push_back(option.first);
            if (option.first == value)
            {
                selection = index;
            }
        }
        input->SetSelection(selection);
        fields->Add(input, 1, wxEXPAND);
        choice[key] = input;
    };
    const auto& measurand = row.at("measurand");
    std::vector<std::pair<std::string, std::string>> portOptions;
    for (std::size_t index = 0; index < ports.size(); ++index)
    {
        portOptions.emplace_back(ports.at(index).get<std::string>(), index < names.size() && names.at(index).is_string()
                                                                         ? names.at(index).get<std::string>()
                                                                         : "자료 포트 " + std::to_string(index + 1));
    }
    addChoice("row_port_id", "응답 포트", portOptions, measurand.value("row_port_id", std::string()));
    addChoice("column_port_id", "입력 포트", portOptions, measurand.value("column_port_id", std::string()));
    addChoice("representation", "대상 표현",
              {{"real", "실수부"},
               {"imag", "허수부"},
               {"magnitude", "선형 크기"},
               {"magnitude_db", "크기 dB"},
               {"phase_deg", "위상 deg"}},
              measurand.value("representation", "magnitude"));
    addChoice("form", "불확도 종류",
              {{"unspecified", "미정"}, {"standard", "표준"}, {"combined_standard", "결합 표준"}, {"expanded", "확장"}},
              row.value("form", "unspecified"));
    addChoice("scale", "값 정의", {{"unspecified", "미정"}, {"absolute", "절대"}, {"relative", "상대"}},
              row.value("scale", "unspecified"));
    const auto value = row.value("value", Json(nullptr));
    addText("value", "불확도 크기",
            value.is_object() ? Exact(value.value("number", value.value("text", Json(nullptr)))) : "");
    addChoice("unit", "불확도 단위", {{"1", "1"}, {"%", "%"}, {"dB", "dB"}, {"deg", "deg"}, {"ohm", "ohm"}, {"S", "S"}},
              value.is_object() ? value.value("unit", std::string("1")) : "1");
    for (const auto& entry :
         std::vector<std::pair<std::string, std::string>>{{"coverage_factor", "포함 인자 k"},
                                                          {"coverage_probability", "포함 확률 (0~1)"},
                                                          {"degrees_of_freedom", "자유도"},
                                                          {"repetitions", "반복 횟수"}})
    {
        addText(entry.first, entry.second, Exact(row.value(entry.first, Json(nullptr))));
    }
    addChoice("estimation", "평가 방법", {{"unspecified", "미정"}, {"type_a", "A형"}, {"type_b", "B형"}},
              row.value("estimation", "unspecified"));
    addText("distribution", "분포", Exact(row.value("distribution", Json(nullptr))));
    addText("method", "평가 절차와 근거", Exact(row.value("method", Json(nullptr))));
    const auto correlation = row.value("correlation", Json::object());
    addChoice("correlation", "상관 상태",
              {{"unknown", "미정"}, {"declared_independent", "독립이라고 명시"}, {"documented", "근거 문서 있음"}},
              correlation.value("state", "unknown"));
    std::vector<std::pair<std::string, std::string>> references{{"keep", "보존 원문 유지"}, {"", "근거 미정"}};
    const auto attachments = context.value("attachments", Json::array());
    int referenceIndex = -1;
    for (std::size_t index = 0; index < attachments.size(); ++index)
    {
        references.emplace_back(std::to_string(index), attachments.at(index).value("name", std::string("보관 원문")));
        if (attachments.at(index).value("artifact", Json(nullptr)) == correlation.value("reference", Json(nullptr)))
        {
            referenceIndex = static_cast<int>(index);
        }
    }
    addChoice("reference", "상관 근거 파일", references, referenceIndex < 0 ? "keep" : std::to_string(referenceIndex));
    const auto scope = row.at("scope");
    const auto range = scope.value("frequency_range_hz", Json(nullptr));
    addText("start", "시작 주파수",
            range.is_array()    ? Exact(range.at(0))
            : range.is_object() ? Exact(range.value("start", Json(nullptr)))
                                : "");
    addText("stop", "끝 주파수",
            range.is_array()    ? Exact(range.at(1))
            : range.is_object() ? Exact(range.value("stop", Json(nullptr)))
                                : "");
    addChoice("frequency_unit", "명시 범위 입력 단위", {{"Hz", "Hz"}, {"kHz", "kHz"}, {"MHz", "MHz"}, {"GHz", "GHz"}},
              range.is_object() ? range.value("start", Json::object()).value("unit", std::string("Hz")) : "Hz");
    auto frequencies = MeasurementQuantityGroup::Create(
        &dialog, choice.at("frequency_unit"),
        {{"uncertainty.frequency_range_hz.start", text.at("start"), range.is_array() ? range.at(0) : Json(nullptr),
          range.is_object() ? range.value("start", Json(nullptr)) : Json(nullptr)},
         {"uncertainty.frequency_range_hz.stop", text.at("stop"), range.is_array() ? range.at(1) : Json(nullptr),
          range.is_object() ? range.value("stop", Json(nullptr)) : Json(nullptr)}},
        gateway);
    frequencies->onStatus = [&dialog](const std::string& message)
    {
        wxMessageBox(Display(message), Display("주파수 표시 단위"), wxOK | wxICON_INFORMATION, &dialog);
    };
    std::string indices;
    for (const auto& index :
         scope.value("sample_indices", Json(nullptr)).is_array() ? scope.at("sample_indices") : Json::array())
    {
        indices += (indices.empty() ? "" : " ") + index.dump();
    }
    addText("indices", "표본 순번 (0부터, 공백 구분)", indices);
    addText("source_refs", "출처 (한 줄에 하나)", MeasurementUi::Lines(row.value("source_refs", Json::array())));
    scroll->SetSizer(fields);
    outer->Add(scroll, 1, wxEXPAND | wxALL, parent->FromDIP(12));
    auto* note = new wxStaticText(&dialog, wxID_ANY,
                                  Display("값과 범위의 해석은 서비스가 검사합니다. k=2, 정규분포, 독립 또는 불확도 "
                                          "전파를 자동으로 가정하지 않습니다."));
    note->Wrap(parent->FromDIP(790));
    outer->Add(note, 0, wxEXPAND | wxLEFT | wxRIGHT, parent->FromDIP(12));
    outer->Add(dialog.CreateButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, parent->FromDIP(12));
    dialog.SetSizer(outer);
    dialog.CentreOnParent();
    const auto selected = [&](const std::string& key)
    {
        const int index = choice.at(key)->GetSelection();
        if (index < 0)
        {
            throw std::runtime_error("불확도 대상과 포트를 명시 선택하세요.");
        }
        return keys.at(key).at(static_cast<std::size_t>(index));
    };
    while (dialog.ShowModal() == wxID_OK)
    {
        try
        {
            Json candidate = row;
            for (const auto* key : {"row_port_id", "column_port_id", "representation"})
            {
                candidate["measurand"][key] = selected(key);
            }
            for (const auto* key : {"form", "scale", "estimation"})
            {
                candidate[key] = selected(key);
            }
            const auto unit = selected("unit");
            if (Utf8(text.at("value")->GetValue()) != originalText.at("value") ||
                (!value.is_null() && unit != value.value("unit", std::string())))
            {
                candidate["value"] = text.at("value")->IsEmpty()
                                         ? Json(nullptr)
                                         : Json{{"text", Utf8(text.at("value")->GetValue())}, {"unit", unit}};
            }
            for (const auto* key : {"coverage_factor", "coverage_probability", "degrees_of_freedom", "repetitions"})
            {
                if (Utf8(text.at(key)->GetValue()) != originalText.at(key))
                {
                    candidate[key] = text.at(key)->IsEmpty()
                                         ? Json(nullptr)
                                         : Json{{"text", Utf8(text.at(key)->GetValue())}, {"unit", "1"}};
                }
            }
            for (const auto* key : {"distribution", "method"})
            {
                candidate[key] = text.at(key)->IsEmpty() ? Json(nullptr) : Json(Utf8(text.at(key)->GetValue()));
            }
            candidate["correlation"]["state"] = selected("correlation");
            const auto reference = selected("reference");
            if (reference != "keep")
            {
                candidate["correlation"]["reference"] =
                    reference.empty() ? Json(nullptr)
                                      : attachments.at(static_cast<std::size_t>(std::stoul(reference))).at("artifact");
            }
            if (frequencies->Edited())
            {
                candidate["scope"]["frequency_range_hz"] =
                    text.at("start")->IsEmpty() && text.at("stop")->IsEmpty()
                        ? Json(nullptr)
                        : Json{{"start", frequencies->Input(0)}, {"stop", frequencies->Input(1)}};
            }
            if (Utf8(text.at("indices")->GetValue()) != originalText.at("indices"))
            {
                Json values = Json::array();
                std::istringstream input(Utf8(text.at("indices")->GetValue()));
                std::string token;
                while (input >> token)
                {
                    if (token.empty() || token.find_first_not_of("0123456789") != std::string::npos)
                    {
                        throw std::runtime_error("표본 순번은 0부터 시작하는 정수를 공백으로 구분하세요.");
                    }
                    values.push_back(std::stoul(token));
                }
                candidate["scope"]["sample_indices"] = text.at("indices")->IsEmpty() ? Json(nullptr) : values;
            }
            candidate["source_refs"] = MeasurementUi::Lines(Utf8(text.at("source_refs")->GetValue()));
            row = candidate;
            return true;
        }
        catch (const std::exception& error)
        {
            wxMessageBox(Display(error.what()), Display("불확도 입력"), wxOK | wxICON_INFORMATION, &dialog);
        }
    }
    return false;
}
}

MeasurementCollectionEdit EditMeasurementUncertainty(wxWindow* parent, const Json& current, const Json& context,
                                                     DialogGateway gateway)
{
    Json rows = current.is_array() ? current : Json::array();
    wxDialog dialog(parent, wxID_ANY, Display("불확도 항목 목록"), wxDefaultPosition, parent->FromDIP(wxSize(710, 440)),
                    wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* list = new wxListBox(&dialog, wxID_ANY);
    layout->Add(list, 1, wxEXPAND | wxALL, parent->FromDIP(12));
    const auto refresh = [&]()
    {
        list->Clear();
        for (std::size_t index = 0; index < rows.size(); ++index)
        {
            list->Append(Display("불확도 " + std::to_string(index + 1) + ", " +
                                 rows.at(index).at("measurand").value("representation", std::string()) + ", " +
                                 MeasurementUi::Text(rows.at(index).value("value", Json(nullptr)))));
        }
    };
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    auto* add = new wxButton(&dialog, wxID_ADD, Display("항목 추가"));
    auto* edit = new wxButton(&dialog, wxID_EDIT, Display("선택 항목 편집"));
    auto* remove = new wxButton(&dialog, wxID_REMOVE, Display("목록에서 제외"));
    for (auto* button : {add, edit, remove})
    {
        actions->Add(button, 0, wxALL, parent->FromDIP(4));
    }
    layout->Add(actions, 0, wxALL, parent->FromDIP(8));
    layout->Add(dialog.CreateButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, parent->FromDIP(12));
    dialog.SetSizer(layout);
    add->Bind(wxEVT_BUTTON,
              [&](wxCommandEvent&)
              {
                  if (rows.size() >= 32)
                  {
                      return;
                  }
                  const auto descriptor = context.value("descriptor", Json::object());
                  Json row{{"id", Uuid()},
                           {"measurand",
                            {{"parameter_kind", descriptor.value("parameter_kind", std::string("S"))},
                             {"row_port_id", ""},
                             {"column_port_id", ""},
                             {"representation", "magnitude"}}},
                           {"scope", {{"frequency_range_hz", nullptr}, {"sample_indices", nullptr}}},
                           {"form", "unspecified"},
                           {"scale", "unspecified"},
                           {"value", nullptr},
                           {"coverage_factor", nullptr},
                           {"coverage_probability", nullptr},
                           {"distribution", nullptr},
                           {"estimation", "unspecified"},
                           {"degrees_of_freedom", nullptr},
                           {"correlation", {{"state", "unknown"}, {"reference", nullptr}}},
                           {"method", nullptr},
                           {"repetitions", nullptr},
                           {"source_refs", Json::array()}};
                  if (EditRow(&dialog, row, context, gateway))
                  {
                      rows.push_back(row);
                      refresh();
                  }
              });
    edit->Bind(wxEVT_BUTTON,
               [&](wxCommandEvent&)
               {
                   const int selected = list->GetSelection();
                   if (selected >= 0 && EditRow(&dialog, rows.at(static_cast<std::size_t>(selected)), context, gateway))
                   {
                       refresh();
                   }
               });
    remove->Bind(wxEVT_BUTTON,
                 [&](wxCommandEvent&)
                 {
                     const int selected = list->GetSelection();
                     if (selected >= 0)
                     {
                         rows.erase(rows.begin() + selected);
                         refresh();
                     }
                 });
    refresh();
    dialog.CentreOnParent();
    return dialog.ShowModal() == wxID_OK ? MeasurementCollectionEdit{true, true, rows} : MeasurementCollectionEdit{};
}
