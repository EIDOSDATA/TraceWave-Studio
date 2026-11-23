/** @file @brief PCB/CAM의 형식별 실제 포함 범위와 공통 출력 미리보기를 표시한다. */
#pragma once
#include "studio_types.h"
#include <wx/scrolwin.h>
#include <functional>
class StudioNotebook;
class DrawingSheetCanvas;
class wxChoice;
class wxListCtrl;
class wxStaticText;
class wxButton;

class PcbCamOutputView final : public wxScrolledWindow
{
public:
    explicit PcbCamOutputView(wxWindow* parent);
    void SetContext(const Json& context);
    void SetPreview(const Json& review);
    void SetRecord(const Json& record);
    void Clear(const std::string& message);
    void SetAvailable(bool ready, bool reviewed, bool snapshot);
    void SetImportAvailable(bool available);
    void SetManufacturingAvailable(bool available);
    Json Input() const;
    Json DisplaySelection() const;
    std::function<void()> onChanged, onPreview, onBuild, onImport, onManufacturing;

private:
    friend class StudioSmokeDriver;
    void RenderLayers(const Json& rows);
    void RenderDrills(const Json& pcb);
    void RenderFiles(const Json& record);
    void SelectionChanged();
    Json m_context = nullptr, m_review = nullptr;
    std::vector<Json> m_layers, m_footprints;
    bool m_refreshing = false;
    bool m_ready = false, m_importAvailable = false;
    int m_family = 0;
    StudioNotebook* m_tabs = nullptr;
    DrawingSheetCanvas* m_canvas = nullptr;
    wxChoice* m_format = nullptr;
    wxChoice* m_footprint = nullptr;
    wxChoice* m_layer = nullptr;
    wxListCtrl* m_kicad = nullptr;
    wxListCtrl* m_gerber = nullptr;
    wxListCtrl* m_drills = nullptr;
    wxListCtrl* m_files = nullptr;
    wxStaticText* m_notice = nullptr;
    wxStaticText* m_coordinates = nullptr;
    wxButton* m_preview = nullptr;
    wxButton* m_build = nullptr;
    wxButton* m_import = nullptr;
    wxButton* m_manufacturing = nullptr;
};
