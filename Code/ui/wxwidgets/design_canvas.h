#pragma once

#include <wx/wx.h>
#include <wx/geometry.h>
#include <nlohmann/json.hpp>
#include "canvas_scene.h"
#include "canvas_viewport.h"
#include "canvas_gesture.h"

class CanvasRenderer;

#include <functional>
#include <set>
#include <string>
#include <vector>

/** @brief mm 표시 DTO를 그리며 한 번의 제스처를 하나의 편집 요청으로 내보낸다. */
class DesignCanvas final : public wxPanel
{
public:
    using Json = nlohmann::json;

    explicit DesignCanvas(wxWindow* parent);
    ~DesignCanvas() override;
    void SetScene(const Json& scene);
    void SetSelection(const std::string& identity);
    void SetTool(const std::string& tool);
    void SetDrawingLayer(const std::string& identity);
    void SetStrokeWidth(double widthMm);
    void SetEditingEnabled(bool enabled);
    void SetLayerVisible(const std::string& identity, bool visible);
    bool IsLayerVisible(const std::string& identity) const;
    void SetBoardVisible(bool visible);
    bool IsBoardVisible() const;
    void SetGridVisible(bool visible);
    void FitView();
    void CancelGesture();

    wxPoint WorldToScreen(const wxPoint2DDouble& point) const;
    wxPoint2DDouble ScreenToWorld(const wxPoint& point) const;
    std::string HitTest(const wxPoint& point) const;
    std::string Selection() const;
    bool HasGesture() const;
    std::size_t DisplayOmissionCount() const;

    std::function<void(const Json&)> onAction;
    std::function<void(const std::string&)> onSelection;
    std::function<void(const std::string&)> onStatus;

private:
    using Shape = CanvasScene::Shape;

    void OnPaint(wxPaintEvent& event);
    void OnLeftDown(wxMouseEvent& event);
    void OnLeftUp(wxMouseEvent& event);
    void OnMotion(wxMouseEvent& event);
    void OnMiddleDown(wxMouseEvent& event);
    void OnMiddleUp(wxMouseEvent& event);
    void OnWheel(wxMouseEvent& event);
    void OnKeyDown(wxKeyEvent& event);
    void OnCaptureLost(wxMouseCaptureLostEvent& event);
    void OnSize(wxSizeEvent& event);
    void Status(const std::string& message);
    void ReleaseOwnedCapture();
    void DrawPreview(wxDC& dc, CanvasRenderer& renderer) const;
    bool Visible(const Shape& shape) const;
    bool Renderable(const Shape& shape, const wxPoint2DDouble& offset = wxPoint2DDouble(0.0, 0.0)) const;
    CanvasViewport Viewport() const;
    const Shape* FindShape(const std::string& identity) const;
    Shape ArcPreview(bool clockwise) const;
    void CommitDrawing(bool clockwise);
    void Emit(const Json& action);

    CanvasScene::Model m_scene;
    std::set<std::string> m_hiddenLayers;
    wxPoint2DDouble m_viewCenter{0.0, 0.0};
    double m_pixelsPerMm = 8.0;
    std::string m_selection;
    std::string m_tool = "select";
    std::string m_drawingLayer;
    double m_strokeWidth = 1.0;
    bool m_editingEnabled = true;
    bool m_showGrid = true;
    bool m_showBoard = true;
    bool m_fitted = false;
    CanvasGestureState m_gesture;
    bool m_clockwise = false;
    wxPoint m_mouseDown;
    wxPoint m_panLast;
    wxPoint2DDouble m_dragAnchor;
    wxPoint2DDouble m_dragOffset{0.0, 0.0};
    wxPoint2DDouble m_cursor;
    std::vector<wxPoint2DDouble> m_points;
    std::string m_pendingId;
    wxPoint2DDouble m_pendingOffset{0.0, 0.0};
};
