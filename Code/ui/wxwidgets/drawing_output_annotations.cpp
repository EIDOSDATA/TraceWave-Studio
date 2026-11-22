/** @file @brief 고정 도면 뷰의 자동 치수 설정과 중복·누락 검토를 표시한다. */
#include "drawing_output_view.h"
#include "output_model.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/checkbox.h>
#include <wx/checklst.h>
#include <wx/choice.h>
#include <wx/dialog.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <algorithm>
#include <array>
#include <string>
#include <vector>

namespace
{
constexpr std::array<const char*, 4> Categories = {"board", "holes", "arcs", "feeds"};
constexpr std::array<const char*, 3> Styles = {"baseline", "chain", "ordinate"};

/** @brief 발생한 검사 행 전체를 키보드로 탐색하고 복사할 수 있는 문자열로 만든다. */
wxString ReviewText(const Json& report)
{
    wxString text;
    const auto add = [&text, &report](const char* key, const char* label)
    {
        const auto rows = report.value(key, Json::array());
        text += Display(label) + wxString::Format(" (%zu)\n", rows.size());
        for (const auto& row : rows)
        {
            text += Display("  " + row.value("title", std::string()) + " / " + row.value("reason", std::string())) +
                    "\n";
        }
        text += "\n";
    };
    add("missing", "누락");
    add("duplicates", "병합한 중복");
    add("not_applicable", "대상 없음");
    return text;
}
}

void DrawingOutputView::KeepAnnotationView()
{
    if (m_annotation.is_object())
    {
        const auto found = std::find(m_viewValues.begin(), m_viewValues.end(), m_annotation.at("view"));
        if (found != m_viewValues.end())
        {
            m_views->Check(static_cast<unsigned>(std::distance(m_viewValues.begin(), found)));
        }
    }
}

void DrawingOutputView::SetStoredAnnotation(const Json& settings)
{
    m_storedAnnotation = settings;
    UpdateAnnotationActions();
}

void DrawingOutputView::UpdateAnnotationActions()
{
    const bool technical = m_mode->GetSelection() == 0 && m_dimensions->GetValue();
    const bool missingView = m_annotation.is_object() &&
                             std::find(m_viewValues.begin(), m_viewValues.end(), m_annotation.at("view")) ==
                                 m_viewValues.end();
    m_annotationEdit->SetLabel(Display(missingView ? "자동 치수 / 뷰 확인" : "자동 치수"));
    m_annotationEdit->Enable(m_available && m_hasSnapshot && technical);
    m_annotationSave->Enable(m_available && technical && m_annotation != m_storedAnnotation);
    m_annotationInspect->Enable(m_available && m_annotationReview.is_object());
}

void DrawingOutputView::EditAnnotations()
{
    wxDialog dialog(this, wxID_ANY, Display("도면 자동 치수"), wxDefaultPosition, wxDefaultSize,
                    wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    StudioTheme::BindSurface(dialog);
    auto* body = new wxBoxSizer(wxVERTICAL);
    auto* form = new wxFlexGridSizer(2, dialog.FromDIP(8), dialog.FromDIP(14));
    form->AddGrowableCol(1);
    const auto choice = [&dialog, form](const char* name)
    {
        form->Add(new wxStaticText(&dialog, wxID_ANY, Display(name)), 0, wxALIGN_CENTER_VERTICAL);
        auto* control = new wxChoice(&dialog, wxID_ANY);
        control->SetName(Display(name));
        form->Add(control, 1, wxEXPAND);
        return control;
    };
    auto* view = choice("대상 도면 뷰");
    auto* datum = choice("기준점");
    auto* style = choice("치수 기입 방식");

    std::vector<Json> views;
    int defaultView = -1;
    for (std::size_t index = 0; index < m_viewValues.size(); ++index)
    {
        const auto& entry = m_viewValues[index];
        if (entry.at("kind") == "layer" || entry.at("kind") == "outline")
        {
            if (defaultView < 0 && m_views->IsChecked(static_cast<unsigned>(index)))
            {
                defaultView = static_cast<int>(views.size());
            }
            if (m_annotation.is_object() && entry == m_annotation.at("view"))
            {
                defaultView = static_cast<int>(views.size());
            }
            view->Append(m_views->GetString(static_cast<unsigned>(index)));
            views.push_back(entry);
        }
    }
    if (views.empty())
    {
        return;
    }
    view->SetSelection(std::max(0, defaultView));

    std::vector<Json> datums = {{{"kind", "board_origin"}, {"id", nullptr}}, {{"kind", "board_min"}, {"id", nullptr}}};
    datum->Append(Display("기판 좌표 원점 (0, 0)"));
    datum->Append(Display("기판 외곽의 X/Y 최솟값"));
    for (const auto& point : m_annotationCatalog.value("datums", Json::array()))
    {
        datum->Append(Display("홀 중심 / " + point.value("name", std::string())));
        datums.push_back({{"kind", "hole"}, {"id", point.at("id")}});
    }
    int datumIndex = 0;
    if (m_annotation.is_object())
    {
        const auto saved = m_annotation.at("datum");
        const auto found = std::find(datums.begin(), datums.end(), saved);
        datumIndex = static_cast<int>(std::distance(datums.begin(), found));
        if (found == datums.end())
        {
            datum->Append(Display("저장한 홀 중심 / 원본 확인 필요"));
            datums.push_back(saved);
        }
    }
    datum->SetSelection(datumIndex);
    for (const auto* name : {"기준선식 / 기준점부터", "연쇄식 / 앞 홀부터", "좌표식 / 순서와 관계없는 X, Y"})
    {
        style->Append(Display(name));
    }
    const std::string storedStyle = m_annotation.is_object() ? m_annotation.value("style", "baseline") : "baseline";
    style->SetSelection(static_cast<int>(std::find(Styles.begin(), Styles.end(), storedStyle) - Styles.begin()));
    body->Add(form, 0, wxEXPAND | wxALL, dialog.FromDIP(14));

    auto* flags = new wxBoxSizer(wxHORIZONTAL);
    std::vector<wxCheckBox*> categories;
    const Json active = m_annotation.is_object() ? m_annotation.at("categories") : Json(Categories);
    const std::array<const char*, 4> labels = {"기판 외곽", "홀 중심", "원호 반경", "급전 간극"};
    for (std::size_t index = 0; index < labels.size(); ++index)
    {
        auto* check = new wxCheckBox(&dialog, wxID_ANY, Display(labels[index]));
        check->SetValue(std::find(active.begin(), active.end(), Categories[index]) != active.end());
        flags->Add(check, 0, wxRIGHT, dialog.FromDIP(12));
        categories.push_back(check);
    }
    body->Add(flags, 0, wxLEFT | wxRIGHT | wxBOTTOM, dialog.FromDIP(14));

    auto* table = new wxCheckBox(&dialog, wxID_ANY, Display("홀 표 별도 페이지"));
    table->SetName(Display("홀 표 별도 페이지"));
    table->SetValue(m_annotation.is_object() && m_annotation.value("hole_table", false));
    body->Add(table, 0, wxLEFT | wxRIGHT | wxBOTTOM, dialog.FromDIP(14));
    body->Add(new wxStaticText(&dialog, wxID_ANY, Display("모델 치수 불러오기 / 기입할 항목 선택")), 0,
              wxLEFT | wxRIGHT, dialog.FromDIP(14));
    auto* models = new wxCheckListBox(&dialog, wxID_ANY);
    models->SetName(Display("모델 치수 불러오기"));
    models->SetMinSize(dialog.FromDIP(wxSize(530, 200)));
    body->Add(models, 1, wxEXPAND | wxALL, dialog.FromDIP(14));

    const Json source = m_annotationCatalog.value("model_dimensions", Json::array());
    std::vector<Json> modelRefs;
    const auto reloadModels = [&]()
    {
        models->Clear();
        modelRefs.clear();
        const auto& selected = views.at(view->GetSelection());
        const std::string key = selected.value("layer_id", selected.value("kind", ""));
        const auto old = m_annotation.is_object() && m_annotation.at("view") == selected
                             ? m_annotation.at("model_dimensions")
                             : Json::array();
        for (const auto& row : source)
        {
            const auto& supported = row.at("views");
            if (std::find(supported.begin(), supported.end(), key) == supported.end())
            {
                continue;
            }
            const Json reference{{"source_id", row.at("source_id")}, {"key", row.at("key")}};
            const std::string amount = row.at("value").is_number()
                                           ? OutputUi::Text(row.at("value")) + " " + row.value("unit", "")
                                           : "미정";
            models->Append(Display(row.value("name", "") + " / " + row.value("label", "") + " / " + amount));
            models->Check(static_cast<unsigned>(modelRefs.size()),
                          std::find(old.begin(), old.end(), reference) != old.end());
            modelRefs.push_back(reference);
        }
        for (const auto& reference : old)
        {
            if (std::find(modelRefs.begin(), modelRefs.end(), reference) == modelRefs.end())
            {
                models->Append(Display("원본 확인 필요 / " + reference.value("key", "")));
                models->Check(static_cast<unsigned>(modelRefs.size()));
                modelRefs.push_back(reference);
            }
        }
    };
    view->Bind(wxEVT_CHOICE,
               [&reloadModels](wxCommandEvent&)
               {
                   reloadModels();
               });
    reloadModels();

    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    auto* apply = new wxButton(&dialog, wxID_OK, Display("도면에 적용"));
    auto* reset = new wxButton(&dialog, wxID_REMOVE, Display("자동 치수 끄기"));
    auto* cancel = new wxButton(&dialog, wxID_CANCEL, Display("취소"));
    auto* message = new wxStaticText(&dialog, wxID_ANY, wxEmptyString);
    body->Add(message, 0, wxLEFT | wxRIGHT, dialog.FromDIP(14));
    StudioTheme::Button(*apply, true);
    actions->AddStretchSpacer();
    for (auto* button : {reset, cancel, apply})
    {
        actions->Add(button, 0, wxLEFT, dialog.FromDIP(8));
    }
    body->Add(actions, 0, wxEXPAND | wxALL, dialog.FromDIP(14));
    Json result = nullptr;
    apply->Bind(wxEVT_BUTTON,
                [&](wxCommandEvent&)
                {
                    Json selected = Json::array(), refs = Json::array();
                    for (std::size_t index = 0; index < categories.size(); ++index)
                    {
                        if (categories[index]->GetValue())
                        {
                            selected.push_back(Categories[index]);
                        }
                    }
                    for (std::size_t index = 0; index < modelRefs.size(); ++index)
                    {
                        if (models->IsChecked(static_cast<unsigned>(index)))
                        {
                            refs.push_back(modelRefs[index]);
                        }
                    }
                    if (refs.size() > 128 || (selected.empty() && refs.empty() && !table->GetValue()))
                    {
                        message->SetLabel(Display(refs.size() > 128 ? "모델 치수는 최대 128개까지 선택하세요."
                                                                   : "자동 치수, 모델 치수 또는 홀 표를 선택하세요."));
                        dialog.Layout();
                        return;
                    }
                    result = {{"view", views.at(view->GetSelection())}, {"datum", datums.at(datum->GetSelection())},
                              {"style", Styles.at(style->GetSelection())}, {"categories", selected},
                              {"model_dimensions", refs}, {"hole_table", table->GetValue()}};
                    dialog.EndModal(wxID_OK);
                });
    reset->Enable(m_annotation.is_object());
    reset->Bind(wxEVT_BUTTON,
                [&dialog](wxCommandEvent&)
                {
                    dialog.EndModal(wxID_REMOVE);
                });
    dialog.SetSizerAndFit(body);
    dialog.SetMinSize(dialog.GetSize());
    apply->SetDefault();
    view->SetFocus();
    const int selected = dialog.ShowModal();
    if (selected == wxID_OK || selected == wxID_REMOVE)
    {
        m_annotation = std::move(result);
        KeepAnnotationView();
        Changed();
        if (m_annotation.is_object() && onPreview)
        {
            onPreview();
        }
    }
}

void DrawingOutputView::InspectAnnotations()
{
    if (!m_annotationReview.is_object())
    {
        return;
    }
    wxDialog dialog(this, wxID_ANY, Display("도면 치수 검사"), wxDefaultPosition, wxDefaultSize,
                    wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    StudioTheme::BindSurface(dialog);
    auto* sizer = new wxBoxSizer(wxVERTICAL);
    const auto summary = wxString::Format(Display("기입 %d개 / 홀 표 %d행"), m_annotationReview.value("dimension_count", 0),
                                          m_annotationReview.value("hole_count", 0));
    sizer->Add(new wxStaticText(&dialog, wxID_ANY, summary), 0, wxALL, dialog.FromDIP(12));
    auto* report = new wxTextCtrl(&dialog, wxID_ANY, ReviewText(m_annotationReview), wxDefaultPosition,
                                  dialog.FromDIP(wxSize(540, 260)), wxTE_MULTILINE | wxTE_READONLY | wxTE_RICH2);
    report->SetName(Display("누락과 중복 검사 결과"));
    sizer->Add(report, 1, wxEXPAND | wxLEFT | wxRIGHT, dialog.FromDIP(12));
    auto* close = new wxButton(&dialog, wxID_OK, Display("닫기"));
    sizer->Add(close, 0, wxALIGN_RIGHT | wxALL, dialog.FromDIP(12));
    dialog.SetSizerAndFit(sizer);
    dialog.SetMinSize(dialog.GetSize());
    report->SetFocus();
    dialog.ShowModal();
}
