/** @file @brief 제출된 외부 보정 이력을 실제 내부 보정 실행과 구분하여 기록한다. */
#include "measurement_collection_dialog.h"
#include "measurement_model.h"
#include "studio_support.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/dialog.h>
#include <wx/listbox.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <map>

namespace
{
bool EditProcessing(wxWindow* parent, Json& row, const Json& context)
{
    wxDialog dialog(parent, wxID_ANY, Display("외부 처리 기록"), wxDefaultPosition, parent->FromDIP(wxSize(780, 650)),
                    wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* fields = new wxFlexGridSizer(2, parent->FromDIP(8), parent->FromDIP(12));
    fields->AddGrowableCol(1, 1);
    std::map<std::string, wxTextCtrl*> inputs;
    for (const auto& field :
         std::vector<std::pair<std::string, std::string>>{{"name", "처리 이름"},
                                                          {"tool", "도구"},
                                                          {"version", "도구 버전"},
                                                          {"reference_plane_before", "처리 전 기준면"},
                                                          {"reference_plane_after", "처리 후 기준면"},
                                                          {"uncertainty_notes", "불확도 처리 기록"},
                                                          {"source_refs", "출처 (한 줄에 하나)"}})
    {
        fields->Add(new wxStaticText(&dialog, wxID_ANY, Display(field.second)), 0, wxALIGN_CENTER_VERTICAL);
        const auto value = row.value(field.first, Json(nullptr));
        auto* input = new wxTextCtrl(&dialog, wxID_ANY,
                                     Display(field.first == "source_refs" ? MeasurementUi::Lines(value)
                                             : value.is_string()          ? value.get<std::string>()
                                                                          : ""));
        input->SetHint(Display("미정"));
        fields->Add(input, 1, wxEXPAND);
        inputs[field.first] = input;
    }
    std::map<std::string, wxChoice*> anchors;
    const auto anchor = context.value("record", Json::object()).value("data_anchor", Json(nullptr));
    for (const auto& field : std::vector<std::pair<std::string, std::string>>{{"input_anchor", "입력 원본 연결"},
                                                                              {"output_anchor", "출력 원본 연결"}})
    {
        fields->Add(new wxStaticText(&dialog, wxID_ANY, Display(field.second)), 0, wxALIGN_CENTER_VERTICAL);
        auto* choice = new wxChoice(&dialog, wxID_ANY);
        choice->Append(Display("기존 기록 보존"));
        choice->Append(Display("미정"));
        if (anchor.is_object())
        {
            choice->Append(Display("현재 시료 기록의 고정 자료"));
        }
        choice->SetSelection(0);
        anchors[field.first] = choice;
        fields->Add(choice, 1, wxEXPAND);
    }
    layout->Add(fields, 1, wxEXPAND | wxALL, parent->FromDIP(12));
    auto* note = new wxStaticText(&dialog, wxID_ANY,
                                  Display("제출한 도구와 처리 순서를 보존합니다. 이 기록은 Studio가 보정·디임베딩을 "
                                          "다시 실행했거나 검증했다는 뜻이 아닙니다."));
    note->Wrap(parent->FromDIP(720));
    layout->Add(note, 0, wxEXPAND | wxALL, parent->FromDIP(12));
    layout->Add(dialog.CreateButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, parent->FromDIP(12));
    dialog.SetSizer(layout);
    dialog.CentreOnParent();
    if (dialog.ShowModal() != wxID_OK)
    {
        return false;
    }
    for (const auto& field : inputs)
    {
        row[field.first] = field.first == "source_refs" ? MeasurementUi::Lines(Utf8(field.second->GetValue()))
                           : field.second->IsEmpty()    ? Json(nullptr)
                                                        : Json(Utf8(field.second->GetValue()));
    }
    for (const auto& field : anchors)
    {
        if (field.second->GetSelection() == 1)
        {
            row[field.first] = nullptr;
        }
        else if (field.second->GetSelection() == 2)
        {
            row[field.first] = anchor;
        }
    }
    return true;
}
}

MeasurementCollectionEdit EditMeasurementProcessing(wxWindow* parent, const Json& current, const Json& context)
{
    Json rows = current.is_array() ? current : Json::array();
    wxDialog dialog(parent, wxID_ANY, Display("외부 처리 순서"), wxDefaultPosition, parent->FromDIP(wxSize(730, 450)),
                    wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* list = new wxListBox(&dialog, wxID_ANY);
    layout->Add(list, 1, wxEXPAND | wxALL, parent->FromDIP(12));
    const auto refresh = [&]()
    {
        list->Clear();
        for (std::size_t index = 0; index < rows.size(); ++index)
        {
            rows.at(index)["order"] = index;
            list->Append(Display(std::to_string(index + 1) + ". " +
                                 MeasurementUi::Text(rows.at(index).value("name", Json(nullptr)))));
        }
    };
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    auto* add = new wxButton(&dialog, wxID_ADD, Display("처리 추가"));
    auto* edit = new wxButton(&dialog, wxID_EDIT, Display("선택 편집"));
    auto* remove = new wxButton(&dialog, wxID_REMOVE, Display("제외"));
    auto* up = new wxButton(&dialog, wxID_UP, Display("위로"));
    auto* down = new wxButton(&dialog, wxID_DOWN, Display("아래로"));
    for (auto* button : {add, edit, remove, up, down})
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
                  Json row{{"name", ""},
                           {"tool", nullptr},
                           {"version", nullptr},
                           {"input_anchor", nullptr},
                           {"output_anchor", nullptr},
                           {"order", rows.size()},
                           {"reference_plane_before", nullptr},
                           {"reference_plane_after", nullptr},
                           {"uncertainty_notes", nullptr},
                           {"source_refs", Json::array()}};
                  if (EditProcessing(&dialog, row, context))
                  {
                      rows.push_back(row);
                      refresh();
                  }
              });
    edit->Bind(wxEVT_BUTTON,
               [&](wxCommandEvent&)
               {
                   const int selected = list->GetSelection();
                   if (selected >= 0 && EditProcessing(&dialog, rows.at(static_cast<std::size_t>(selected)), context))
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
    const auto move = [&](int delta)
    {
        const int selected = list->GetSelection();
        const int next = selected + delta;
        if (selected >= 0 && next >= 0 && next < static_cast<int>(rows.size()))
        {
            std::swap(rows.at(static_cast<std::size_t>(selected)), rows.at(static_cast<std::size_t>(next)));
            refresh();
            list->SetSelection(next);
        }
    };
    up->Bind(wxEVT_BUTTON,
             [&](wxCommandEvent&)
             {
                 move(-1);
             });
    down->Bind(wxEVT_BUTTON,
               [&](wxCommandEvent&)
               {
                   move(1);
               });
    refresh();
    dialog.CentreOnParent();
    return dialog.ShowModal() == wxID_OK ? MeasurementCollectionEdit{true, false, rows} : MeasurementCollectionEdit{};
}
