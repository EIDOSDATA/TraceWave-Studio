/** @file @brief KiCad/Gerber/드릴/Job을 실제 서비스 profile과 연결한 native 탭이다. */
#include "pcb_cam_output_view.h"
#include "drawing_sheet_canvas.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include "studio_theme.h"
#include "output_model.h"
#include <wx/choice.h>
#include <wx/button.h>
#include <wx/listctrl.h>
#include <wx/stattext.h>
#include <wx/sizer.h>
#include <wx/wrapsizer.h>
#include <algorithm>

namespace
{
wxListCtrl* Page(StudioNotebook* tabs, const std::string& label,
                 const std::vector<std::pair<std::string, int>>& columns)
{
    auto* page = new wxPanel(tabs);
    page->SetSizer(new wxBoxSizer(wxVERTICAL));
    auto* table = new wxListCtrl(page, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_SINGLE_SEL);
    StudioTheme::Table(*table);
    for (const auto& column : columns)
    {
        table->AppendColumn(Display(column.first), wxLIST_FORMAT_LEFT, page->FromDIP(column.second));
    }
    page->GetSizer()->Add(table, 1, wxEXPAND | wxALL, page->FromDIP(4));
    tabs->AddPage(page, Display(label));
    return table;
}
}

PcbCamOutputView::PcbCamOutputView(wxWindow* parent)
    : wxScrolledWindow(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL)
{
    SetScrollRate(0, FromDIP(16));
    StudioTheme::BindSurface(*this);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* actions = new wxWrapSizer(wxHORIZONTAL);
    m_format = new wxChoice(this, wxID_ANY);
    m_format->Append(Display("KiCad 보드"));
    m_format->Append(Display("KiCad 풋프린트"));
    m_format->SetSelection(0);
    m_footprint = new wxChoice(this, wxID_ANY);
    m_footprint->SetMinSize(FromDIP(wxSize(170, -1)));
    m_preview = new wxButton(this, wxID_ANY, Display("포함 범위 검토"));
    m_build = new wxButton(this, wxID_ANY, Display("검토한 패키지 생성"));
    m_manufacturing = new wxButton(this, wxID_ANY, Display("IPC-2581C / ODB++ 내보내기"));
    m_manufacturing->SetToolTip(Display("선택한 KiCad 보드 출력 기록에서 원본과 제조 파일을 담은 ZIP을 만듭니다."));
    m_manufacturing->Disable();
    m_import = new wxButton(this, wxID_ANY, Display("PCB 파일 가져오기"));
    for (auto* control : std::vector<wxWindow*>{m_format, m_footprint, m_preview, m_build, m_manufacturing, m_import})
    {
        actions->Add(control, 0, wxALL | wxALIGN_CENTER_VERTICAL, FromDIP(4));
    }
    layout->Add(actions, 0, wxEXPAND | wxALL, FromDIP(4));
    m_tabs = new StudioNotebook(this);
    m_tabs->SetMinSize(FromDIP(wxSize(-1, 170)));
    m_kicad =
        Page(m_tabs, "KiCad", {{"원본 층", 200}, {"출력 대응", 220}, {"역할", 140}, {"면", 90}, {"포함 상태", 150}});
    m_gerber =
        Page(m_tabs, "Gerber", {{"원본 층", 200}, {"출력 대응", 220}, {"역할", 140}, {"면", 90}, {"포함 상태", 150}});
    m_drills =
        Page(m_tabs, "드릴 / 라우트",
             {{"이름", 190}, {"기계 형상", 120}, {"완성 치수 / mm", 180}, {"공구 지름 / mm", 130}, {"도금 상태", 150}});
    m_files = Page(m_tabs, "Job / 검수", {{"파일", 300}, {"역할", 160}, {"크기 / bytes", 120}, {"보존 상태", 190}});
    layout->Add(m_tabs, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    auto* layerRow = new wxWrapSizer(wxHORIZONTAL);
    layerRow->Add(new wxStaticText(this, wxID_ANY, Display("미리보기 층")), 0, wxALL | wxALIGN_CENTER_VERTICAL,
                  FromDIP(4));
    m_layer = new wxChoice(this, wxID_ANY);
    m_layer->SetMinSize(FromDIP(wxSize(220, -1)));
    layerRow->Add(m_layer, 0, wxALL, FromDIP(4));
    m_coordinates = new wxStaticText(this, wxID_ANY, Display("원본 XY / 위에서 본 좌표 / 1:1 / 임의 미러 없음"));
    layerRow->Add(m_coordinates, 0, wxALL | wxALIGN_CENTER_VERTICAL, FromDIP(4));
    layout->Add(layerRow, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    m_canvas = new DrawingSheetCanvas(this);
    m_canvas->SetMinSize(FromDIP(wxSize(280, 240)));
    layout->Add(m_canvas, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    m_notice = new wxStaticText(
        this, wxID_ANY,
        Display("고정 입력의 원본 층과 사용 여부를 선택합니다. 제작/측정 합격과 수신 도구의 채움은 별도 검증입니다."));
    layout->Add(m_notice, 0, wxEXPAND | wxALL, FromDIP(8));
    SetSizer(layout);
    m_format->Bind(wxEVT_CHOICE,
                   [this](wxCommandEvent&)
                   {
                       SelectionChanged();
                   });
    m_footprint->Bind(wxEVT_CHOICE,
                      [this](wxCommandEvent&)
                      {
                          if (!m_refreshing && onChanged)
                          {
                              onChanged();
                          }
                      });
    m_layer->Bind(wxEVT_CHOICE,
                  [this](wxCommandEvent&)
                  {
                      if (!m_refreshing && onPreview)
                      {
                          onPreview();
                      }
                  });
    m_tabs->onSelectionChanged = [this](int)
    {
        SelectionChanged();
    };
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
    m_manufacturing->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        if (onManufacturing)
        {
            onManufacturing();
        }
    });
    m_import->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       if (onImport)
                       {
                           onImport();
                       }
                   });
    Bind(wxEVT_SIZE,
         [this](wxSizeEvent& event)
         {
             m_notice->Wrap(std::max(FromDIP(240), GetClientSize().x - FromDIP(20)));
             Layout();
             FitInside();
             event.Skip();
         });
    SelectionChanged();
}

void PcbCamOutputView::SelectionChanged()
{
    const int family = m_tabs->GetSelection() == 0 ? m_format->GetSelection() : 2;
    m_format->Show(m_tabs->GetSelection() == 0);
    m_footprint->Show(family == 1);
    Layout();
    FitInside();
    if (!m_refreshing && family != m_family && onChanged)
    {
        m_family = family;
        onChanged();
    }
    m_family = family;
}

Json PcbCamOutputView::Input() const
{
    if (m_tabs->GetSelection() != 0)
    {
        return {
            {"profile", "rfad.exchange.cam/0.1"},
            {"format", "gerber_job"},
            {"options",
             {{"layer_ids", m_context.is_object()
                                ? m_context.value("pcb", Json::object()).value("default_cam_layer_ids", Json::array())
                                : Json::array()}}}};
    }
    if (m_format->GetSelection() == 1)
    {
        const int index = m_footprint->GetSelection();
        return {{"profile", "rfad.exchange.kicad-footprint/0.1"},
                {"format", "kicad_mod"},
                {"options",
                 {{"footprint_id", index >= 0 && static_cast<std::size_t>(index) < m_footprints.size()
                                       ? m_footprints.at(index)
                                       : Json(nullptr)}}}};
    }
    return {{"profile", "rfad.exchange.kicad-board/0.1"}, {"format", "kicad_pcb"}, {"options", Json::object()}};
}

Json PcbCamOutputView::DisplaySelection() const
{
    const int index = m_layer->GetSelection();
    return index >= 0 && static_cast<std::size_t>(index) < m_layers.size() ? Json{{"view_layer_id", m_layers.at(index)}}
                                                                           : Json::object();
}

void PcbCamOutputView::SetContext(const Json& context)
{
    m_refreshing = true;
    m_context = context;
    m_layers.clear();
    m_layer->Clear();
    m_footprints.clear();
    m_footprint->Clear();
    const auto pcb = context.value("pcb", Json::object());
    Json layers = Json::array();
    for (auto layer : context.value("layers", Json::array()))
    {
        if (layer.value("role", "") == "conductor")
        {
            layer["state"] = "explicit_conductor";
            layer["selected"] = true;
            layers.push_back(layer);
        }
    }
    for (auto layer : pcb.value("artwork_layers", Json::array()))
    {
        layer["state"] = layer.value("use_state", "unknown");
        layer["selected"] = layer.value("use_state", "unknown") == "used";
        layers.push_back(layer);
    }
    RenderLayers(layers);
    for (const auto& footprint : pcb.value("footprints", Json::array()))
    {
        m_footprints.push_back(footprint.at("id"));
        m_footprint->Append(Display(OutputUi::Text(footprint.value("name", Json(nullptr)), "풋프린트 / 이름 미정")));
    }
    m_footprint->SetSelection(wxNOT_FOUND);
    m_refreshing = false;
}

void PcbCamOutputView::SetAvailable(bool ready, bool reviewed, bool snapshot)
{
    m_ready = ready;
    const auto request = Input();
    const auto profiles = m_context.is_object() ? m_context.value("profiles", Json::array()) : Json::array();
    const bool profile = std::any_of(profiles.begin(), profiles.end(),
                                     [&](const Json& candidate)
                                     {
                                         return candidate.is_object() &&
                                                candidate.value("id", Json(nullptr)) == request.at("profile") &&
                                                candidate.value("supported", false);
                                     });
    const bool footprint = request.at("format") != "kicad_mod" || !request.at("options").at("footprint_id").is_null();
    m_tabs->Enable(ready);
    m_format->Enable(ready);
    m_footprint->Enable(ready);
    m_layer->Enable(ready && snapshot && profile && !m_layers.empty());
    m_preview->Enable(ready && snapshot && profile && footprint);
    m_build->Enable(ready && snapshot && profile && footprint && reviewed && m_context.is_object() &&
                    m_context.value("runtime_configured", false));
    m_import->Enable(ready && m_importAvailable && static_cast<bool>(onImport));
}

void PcbCamOutputView::SetManufacturingAvailable(bool available)
{
    m_manufacturing->Enable(available && static_cast<bool>(onManufacturing));
}

void PcbCamOutputView::SetImportAvailable(bool available)
{
    m_importAvailable = available;
    m_import->Enable(m_ready && available && static_cast<bool>(onImport));
}

void PcbCamOutputView::Clear(const std::string& message)
{
    m_review = nullptr;
    m_canvas->Clear(message);
    m_drills->DeleteAllItems();
    m_files->DeleteAllItems();
    m_notice->SetLabel(Display(message));
    m_notice->Wrap(std::max(FromDIP(240), GetClientSize().x - FromDIP(20)));
    Layout();
    FitInside();
}
