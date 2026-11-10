#pragma once

#include <wx/wx.h>
#include <wx/geometry.h>
#include <nlohmann/json.hpp>

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
    struct Shape
    {
        std::string id;
        std::string kind;
        std::string label;
        std::string layer;
        std::string role;
        wxPoint2DDouble start;
        wxPoint2DDouble end;
        wxPoint2DDouble center;
        double radius = 0.0;
        double startAngle = 0.0;
        double sweepAngle = 0.0;
        double width = 0.0;
        bool movable = false;
    };

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
    void DrawGrid(wxDC& dc) const;
    bool DrawShape(wxDC& dc, const Shape& shape, const wxPoint2DDouble& offset,
        const wxColour& colour, bool highlight) const;
    void DrawPreview(wxDC& dc) const;
    bool Visible(const Shape& shape) const;
    bool Renderable(const Shape& shape, const wxPoint2DDouble& offset = wxPoint2DDouble(0.0, 0.0)) const;
    wxPoint2DDouble PixelPoint(const wxPoint2DDouble& point, const wxPoint2DDouble& offset) const;
    const Shape* FindShape(const std::string& identity) const;
    Shape ArcPreview(bool clockwise) const;
    void CommitDrawing(bool clockwise);
    void Emit(const Json& action);

    std::vector<Shape> m_shapes;
    std::set<std::string> m_layers;
    std::set<std::string> m_hiddenLayers;
    bool m_hasBoard = false;
    double m_boardWidth = 0.0;
    double m_boardHeight = 0.0;
    wxPoint2DDouble m_viewCenter{0.0, 0.0};
    double m_pixelsPerMm = 8.0;
    std::string m_selection;
    std::string m_tool = "select";
    std::string m_drawingLayer;
    double m_strokeWidth = 1.0;
    bool m_editingEnabled = true;
    bool m_showGrid = true;
    bool m_fitted = false;
    bool m_panning = false;
    bool m_selecting = false;
    bool m_drawingClick = false;
    bool m_dragging = false;
    bool m_clockwise = false;
    wxPoint m_mouseDown;
    wxPoint m_panLast;
    wxPoint2DDouble m_dragAnchor;
    wxPoint2DDouble m_dragOffset{0.0, 0.0};
    wxPoint2DDouble m_cursor;
    std::vector<wxPoint2DDouble> m_points;
    std::string m_pendingId;
    wxPoint2DDouble m_pendingOffset{0.0, 0.0};
    std::size_t m_omissionCount = 0;
    std::size_t m_rangeOmissionCount = 0;
};
