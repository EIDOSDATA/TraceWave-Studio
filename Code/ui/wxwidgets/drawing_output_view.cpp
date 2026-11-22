/** @file @brief 도면 옵션만 수집하며 원본 단위/물리량 계산은 서비스에 맡긴다. */
#include "drawing_output_view.h"
#include "drawing_sheet_canvas.h"
#include "output_model.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/checkbox.h>
#include <wx/checklst.h>
#include <wx/choice.h>
#include <wx/sizer.h>
#include <wx/spinctrl.h>
#include <wx/stattext.h>
#include <wx/wrapsizer.h>
#include <wx/dialog.h>
#include <wx/msgdlg.h>
#include <wx/textctrl.h>
#include <algorithm>

DrawingOutputView::DrawingOutputView(wxWindow* parent)
    : wxScrolledWindow(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL)
{
    StudioTheme::BindSurface(*this);
    SetScrollRate(0, FromDIP(16));
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* title = new wxStaticText(this, wxID_ANY, Display("기술 도면"));
    StudioTheme::Title(*title);
    layout->Add(title, 0, wxALL, FromDIP(12));
    auto* body = new wxBoxSizer(wxHORIZONTAL);
    auto* paper = new wxBoxSizer(wxVERTICAL);
    m_canvas = new DrawingSheetCanvas(this);
    m_canvas->SetMinSize(FromDIP(wxSize(260, 200)));
    paper->Add(m_canvas, 1, wxEXPAND | wxBOTTOM, FromDIP(8));
    m_page = new wxChoice(this, wxID_ANY);
    m_page->SetName(Display("도면 페이지"));
    m_page->Append(Display("미리보기 페이지 미조회"));
    m_page->SetSelection(0);
    paper->Add(m_page, 0, wxEXPAND);
    body->Add(paper, 1, wxEXPAND | wxRIGHT, FromDIP(16));
    auto* properties =
        new wxScrolledWindow(this, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL);
    StudioTheme::BindSurface(*properties);
    properties->SetMinSize(FromDIP(wxSize(250, 200)));
    properties->SetScrollRate(0, FromDIP(16));
    auto* form = new wxBoxSizer(wxVERTICAL);
    const auto choice = [this, properties, form](const char* label, const std::vector<const char*>& options)
    {
        form->Add(new wxStaticText(properties, wxID_ANY, Display(label)), 0, wxTOP | wxBOTTOM, FromDIP(8));
        auto* input = new wxChoice(properties, wxID_ANY);
        input->SetMinSize(FromDIP(wxSize(230, -1)));
        for (const auto* option : options)
        {
            input->Append(Display(option));
        }
        input->SetSelection(0);
        form->Add(input, 0, wxEXPAND);
        input->Bind(wxEVT_CHOICE,
                    [this](wxCommandEvent&)
                    {
                        Changed();
                    });
        return input;
    };
    m_format = choice("출력 형식", {"PDF", "SVG", "DXF"});
    m_mode = choice("파일 용도", {"기술 도면 / 치수와 주석", "1:1 형상 / 도체와 외곽만"});
    m_sheet = choice("용지", {"A4", "A3"});
    m_orientation = choice("방향", {"가로", "세로"});
    form->Add(new wxStaticText(properties, wxID_ANY, Display("출력 축척 (종이 / 실제)")), 0, wxTOP | wxBOTTOM,
              FromDIP(8));
    m_scale = new wxSpinCtrlDouble(properties, wxID_ANY, "1", wxDefaultPosition, wxDefaultSize, wxSP_ARROW_KEYS, 0.01,
                                   100.0, 1.0, 0.1);
    m_scale->SetDigits(3);
    form->Add(m_scale, 0, wxEXPAND);
    form->Add(new wxStaticText(properties, wxID_ANY, Display("출력 뷰 / 최대 8개")), 0, wxTOP | wxBOTTOM, FromDIP(8));
    m_views = new wxCheckListBox(properties, wxID_ANY);
    m_views->SetMinSize(FromDIP(wxSize(230, 130)));
    form->Add(m_views, 0, wxEXPAND);
    auto* detailActions = new wxWrapSizer(wxHORIZONTAL);
    m_detailAdd = new wxButton(properties, wxID_ANY, Display("상세 뷰 추가"));
    m_detailRemove = new wxButton(properties, wxID_ANY, Display("상세 뷰 제거"));
    detailActions->Add(m_detailAdd, 0, wxTOP | wxRIGHT, FromDIP(4));
    detailActions->Add(m_detailRemove, 0, wxTOP, FromDIP(4));
    form->Add(detailActions, 0, wxEXPAND);
    m_detailAdd->Bind(wxEVT_BUTTON,
                      [this](wxCommandEvent&)
                      {
                          AddDetail();
                      });
    m_detailRemove->Bind(wxEVT_BUTTON,
                         [this](wxCommandEvent&)
                         {
                             const int selected = m_views->GetSelection();
                             if (selected >= 0 && static_cast<std::size_t>(selected) < m_viewValues.size() &&
                                 m_viewValues[selected].value("kind", "") == "detail")
                             {
                                 m_views->Delete(selected);
                                 m_viewValues.erase(m_viewValues.begin() + selected);
                                 Changed();
                             }
                         });
    m_dimensions = new wxCheckBox(properties, wxID_ANY, Display("연관 치수 포함"));
    m_notes = new wxCheckBox(properties, wxID_ANY, Display("제작/측정 안내 포함"));
    m_dimensions->SetValue(true);
    m_notes->SetValue(true);
    form->Add(m_dimensions, 0, wxTOP, FromDIP(12));
    form->Add(m_notes, 0, wxTOP, FromDIP(8));
    properties->SetSizer(form);
    body->Add(properties, 0, wxEXPAND);
    layout->Add(body, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    m_summary = new wxStaticText(this, wxID_ANY, Display("형상·치수와 출력 조건을 검토한 뒤 파일을 생성하세요."));
    m_summary->SetName(Display("도면 검토 요약"));
    layout->Add(m_summary, 0, wxEXPAND | wxALL, FromDIP(12));
    auto* actions = new wxWrapSizer(wxHORIZONTAL);
    m_preview = new wxButton(this, wxID_ANY, Display("출력 내용 검토"));
    m_build = new wxButton(this, wxID_ANY, Display("검토한 도면 생성"));
    StudioTheme::Button(*m_preview, true);
    StudioTheme::Button(*m_build);
    actions->Add(m_preview, 0, wxALL, FromDIP(4));
    actions->Add(m_build, 0, wxALL, FromDIP(4));
    m_annotationEdit = new wxButton(this, wxID_ANY, Display("자동 치수"));
    m_annotationInspect = new wxButton(this, wxID_ANY, Display("치수 검사"));
    m_annotationSave = new wxButton(this, wxID_ANY, Display("치수 설정 저장"));
    for (auto* button : {m_annotationEdit, m_annotationInspect, m_annotationSave})
    {
        StudioTheme::Button(*button);
        actions->Add(button, 0, wxALL, FromDIP(4));
    }
    m_annotationEdit->Bind(wxEVT_BUTTON,
                           [this](wxCommandEvent&)
                           {
                               EditAnnotations();
                           });
    m_annotationInspect->Bind(wxEVT_BUTTON,
                              [this](wxCommandEvent&)
                              {
                                  InspectAnnotations();
                              });
    m_annotationSave->Bind(wxEVT_BUTTON,
                           [this](wxCommandEvent&)
                           {
                               if (onSaveAnnotations)
                               {
                                   onSaveAnnotations(m_annotation);
                               }
                           });
    layout->Insert(1, actions, 0, wxEXPAND | wxLEFT | wxBOTTOM, FromDIP(8));
    SetSizer(layout);
    m_page->Bind(wxEVT_CHOICE,
                 [this](wxCommandEvent&)
                 {
                     m_canvas->SetPage(m_page->GetSelection());
                 });
    m_scale->Bind(wxEVT_SPINCTRLDOUBLE,
                  [this](wxSpinDoubleEvent&)
                  {
                      Changed();
                  });
    m_scale->Bind(wxEVT_TEXT,
                  [this](wxCommandEvent&)
                  {
                      Changed();
                  });
    m_views->Bind(wxEVT_CHECKLISTBOX,
                  [this](wxCommandEvent&)
                  {
                      Changed();
                  });
    m_dimensions->Bind(wxEVT_CHECKBOX,
                       [this](wxCommandEvent&)
                       {
                           Changed();
                       });
    m_notes->Bind(wxEVT_CHECKBOX,
                  [this](wxCommandEvent&)
                  {
                      Changed();
                  });
    m_preview->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        if (onPreview)
                        {
                            onPreview();
                        }
                    });
    m_build->Bind(wxEVT_BUTTON,
                  [this](wxCommandEvent&)
                  {
                      if (onBuild)
                      {
                          onBuild();
                      }
                  });
    Bind(wxEVT_SIZE,
         [this](wxSizeEvent& event)
         {
             Layout();
             FitInside();
             event.Skip();
         });
    SetAvailable(false, false, false);
}

void DrawingOutputView::SetContext(const Json& context)
{
    m_refreshing = true;
    m_views->Clear();
    m_viewValues.clear();
    for (const auto& layer : context.value("layers", Json::array()))
    {
        if (layer.value("role", "") == "conductor")
        {
            m_views->Append(Display(OutputUi::Text(layer.value("name", Json(nullptr)), "도체층")));
            m_viewValues.push_back({{"kind", "layer"}, {"layer_id", layer.at("id")}});
        }
    }
    m_views->Append(Display("기판 외곽"));
    m_viewValues.push_back({{"kind", "outline"}});
    m_views->Append(Display("적층 단면"));
    m_viewValues.push_back({{"kind", "stackup"}});
    m_annotationCatalog = context.value("drawing_annotations", Json::object());
    m_storedAnnotation = m_annotationCatalog.value("saved", Json(nullptr));
    m_annotation = m_storedAnnotation;
    const auto defaults = context.value("default_options", Json::object());
    m_mode->SetSelection(defaults.value("mode", "drawing") == "drawing" ? 0 : 1);
    m_sheet->SetSelection(defaults.value("sheet", "A4") == "A3" ? 1 : 0);
    m_orientation->SetSelection(defaults.value("orientation", "landscape") == "portrait" ? 1 : 0);
    m_scale->SetValue(defaults.value("scale", 1.0));
    m_dimensions->SetValue(defaults.value("dimensions", true));
    m_notes->SetValue(defaults.value("notes", true));
    for (std::size_t index = 0; index < m_viewValues.size(); ++index)
    {
        for (const auto& view : defaults.value("views", Json::array()))
        {
            if (view == m_viewValues[index])
            {
                m_views->Check(static_cast<unsigned>(index));
            }
        }
    }
    KeepAnnotationView();
    m_refreshing = false;
    UpdateMode();
}

Json DrawingOutputView::Options() const
{
    Json views = Json::array();
    for (std::size_t index = 0; index < m_viewValues.size(); ++index)
    {
        if (m_views->IsChecked(static_cast<unsigned>(index)))
        {
            views.push_back(m_viewValues[index]);
        }
    }
    Json result{{"mode", m_mode->GetSelection() == 0 ? "drawing" : "fabrication_geometry"},
            {"sheet", m_sheet->GetSelection() == 0 ? "A4" : "A3"},
            {"orientation", m_orientation->GetSelection() == 0 ? "landscape" : "portrait"},
            {"scale", m_scale->GetValue()},
            {"views", views},
            {"dimensions", m_dimensions->GetValue()},
            {"notes", m_notes->GetValue()}};
    if (m_annotation.is_object() && m_dimensions->GetValue() && m_mode->GetSelection() == 0 &&
        std::find(views.begin(), views.end(), m_annotation.at("view")) != views.end())
    {
        result["annotations"] = m_annotation;
    }
    return result;
}

std::string DrawingOutputView::Format() const
{
    const char* formats[] = {"pdf", "svg", "dxf"};
    return formats[std::max(0, m_format->GetSelection())];
}

void DrawingOutputView::UpdateMode()
{
    const bool fabrication = m_mode->GetSelection() == 1;
    m_scale->Enable(m_available && !fabrication);
    m_dimensions->Enable(m_available && !fabrication);
    m_notes->Enable(m_available && !fabrication);
    if (fabrication)
    {
        m_refreshing = true;
        m_scale->SetValue(1.0);
        m_dimensions->SetValue(false);
        m_notes->SetValue(false);
        if (m_format->GetSelection() == 0)
        {
            m_format->SetSelection(1);
        }
        m_refreshing = false;
    }
    UpdateAnnotationActions();
}

void DrawingOutputView::Changed()
{
    if (m_refreshing)
    {
        return;
    }
    if (m_mode->GetSelection() == 0 && m_dimensions->GetValue())
    {
        KeepAnnotationView();
    }
    UpdateMode();
    if (onChanged)
    {
        onChanged();
    }
}

void DrawingOutputView::SetPreview(const Json& review)
{
    m_canvas->SetPages(review.at("pages"));
    m_page->Clear();
    int chosen = 0;
    for (std::size_t index = 0; index < m_canvas->PageCount(); ++index)
    {
        const auto& page = review.at("pages").at(index);
        std::string label = "페이지 " + std::to_string(index + 1);
        if (page.contains("annotation_review"))
        {
            chosen = static_cast<int>(index);
            label += " / 참조 치수";
        }
        else if (page.value("page_role", "") == "hole_table")
        {
            label += " / 홀 표";
        }
        m_page->Append(Display(label));
    }
    m_page->SetSelection(chosen);
    m_canvas->SetPage(chosen);
    const auto issues = OutputUi::Issues(review.value("issues", Json::array()));
    auto message = issues.empty() ? "고정 입력의 실제 종이 배치입니다. 생성 전 포함/누락 목록을 확인하세요." : issues;
    m_annotationReview = review.value("annotation_review", Json(nullptr));
    if (m_annotationReview.is_object())
    {
        message = Utf8(wxString::Format(Display("기입 %d개 / 누락 %zu개 / 병합 중복 %zu개 / 홀 표 %d행"),
                                        m_annotationReview.value("dimension_count", 0),
                                        m_annotationReview.at("missing").size(), m_annotationReview.at("duplicates").size(),
                                        m_annotationReview.value("hole_count", 0))) +
                  (issues.empty() ? "" : "\n" + issues);
    }
    m_summary->SetLabel(Display(message));
    UpdateAnnotationActions();
    Layout();
    FitInside();
}

void DrawingOutputView::ClearPreview(const std::string& message)
{
    m_annotationReview = nullptr;
    UpdateAnnotationActions();
    m_canvas->Clear(message);
    m_page->Clear();
    m_summary->SetLabel(Display(message));
    m_build->Disable();
    Layout();
    FitInside();
}

void DrawingOutputView::SetAvailable(bool available, bool busy, bool reviewed, bool hasSnapshot)
{
    m_available = available && !busy;
    m_hasSnapshot = hasSnapshot;
    for (wxWindow* input : std::vector<wxWindow*>{m_format, m_mode, m_sheet, m_orientation, m_scale, m_views,
                                                  m_dimensions, m_notes, m_detailAdd, m_detailRemove})
    {
        input->Enable(m_available);
    }
    m_preview->Enable(m_available && hasSnapshot);
    m_build->Enable(m_available && reviewed);
    UpdateMode();
}
