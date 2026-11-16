/** @file @brief 실제 2D 스냅, 끝점 입력, 화면 미리보기와 이력을 검증한다. */
#include "studio_internal.h"

namespace
{
using CanvasGeometry::Point;

Point ArcEndpoint(const Json& arc, bool last)
{
    const auto& center = arc.at("center");
    const double angle = arc.at("start_angle").get<double>() + (last ? arc.at("sweep_angle").get<double>() : 0.0);
    return CanvasGeometry::ArcPoint({center.at(0), center.at(1)}, arc.at("radius"), angle);
}

bool Near(const Json& values, Point point)
{
    return std::hypot(values.at(0).get<double>() - point.x, values.at(1).get<double>() - point.y) < 1e-9;
}

/** @brief 스냅 반경 안의 짧은 드래그가 서비스 명령을 내보내는지 실제 이벤트 처리기로 확인한다. */
std::size_t SnappedNoopRequests(DesignCanvas& canvas, Point start)
{
    const auto originalAction = canvas.onAction;
    std::size_t requests = 0;
    canvas.onAction = [&requests](const Json&)
    {
        ++requests;
    };
    const wxPoint first = canvas.WorldToScreen({start.x, start.y});
    const wxPoint last = first + wxPoint(canvas.FromDIP(4), 0);
    const auto mouse = [&canvas](wxEventType type, const wxPoint& position, bool left)
    {
        wxMouseEvent event(type);
        event.SetPosition(position);
        event.SetLeftDown(left);
        event.SetEventObject(&canvas);
        canvas.GetEventHandler()->ProcessEvent(event);
    };
    mouse(wxEVT_LEFT_DOWN, first, true);
    mouse(wxEVT_MOTION, last, true);
    mouse(wxEVT_LEFT_UP, last, false);
    canvas.onAction = originalAction;
    return requests;
}
}

void StudioSmokeDriver::CanvasPrecisionSmokeNext()
{
    switch (m_canvasStage)
    {
    case 20:
    {
        auto* check = m_frame.m_snapCheck;
        check->SetValue(true);
        wxCommandEvent toggle(wxEVT_CHECKBOX, check->GetId());
        toggle.SetEventObject(check);
        check->GetEventHandler()->ProcessEvent(toggle);
        CanvasAssert(m_frame.GetStatusBar()->GetStatusText(2) == Display("mm / 스냅 켬"),
                     "스냅 체크 상자와 상태 표시줄이 일치하지 않습니다.");
        m_frame.m_canvas->SetTool("line");
        const auto arcStart = ArcEndpoint(CanvasShape(m_canvasArc), false);
        m_canvasStage = 21;
        CanvasClick(10.35, 20.35);
        CanvasClick(arcStart.x + 0.30, arcStart.y + 0.30);
        break;
    }
    case 21:
    {
        m_canvasSnappedLine = m_frame.m_selection.at("id");
        m_canvasBeforeEndpoint = CanvasShape(m_canvasSnappedLine);
        CanvasAssert(Near(m_canvasBeforeEndpoint.at("start"), {10, 20}) &&
                     Near(m_canvasBeforeEndpoint.at("end"), ArcEndpoint(CanvasShape(m_canvasArc), false)),
                     "그리기 좌표가 표시 격자/같은 층의 원호 끝점에 맞지 않습니다.");
        m_canvasChecks.push_back("grid_and_endpoint_snap");
        m_frame.m_canvas->SetTool("select");
        const std::string revision = m_frame.m_revision;
        const auto unchangedHistory = m_frame.m_editor.at("history");
        CanvasAssert(SnappedNoopRequests(*m_frame.m_canvas, {10, 20}) == 0 &&
                     !m_frame.m_canvas->HasGesture() && m_frame.m_revision == revision &&
                     m_frame.m_editor.at("history") == unchangedHistory &&
                     CanvasShape(m_canvasSnappedLine) == m_canvasBeforeEndpoint,
                     "같은 격자 끝점으로 돌아온 드래그가 명령이나 이력을 만들었습니다.");
        CanvasMouse(wxEVT_LEFT_DOWN, 10, 20, true);
        CanvasMouse(wxEVT_MOTION, 20.35, 20.35, true);
        wxKeyEvent escape(wxEVT_KEY_DOWN);
        escape.m_keyCode = WXK_ESCAPE;
        m_frame.m_canvas->GetEventHandler()->ProcessEvent(escape);
        CanvasMouse(wxEVT_LEFT_UP, 20.35, 20.35);
        CanvasAssert(!m_frame.m_canvas->HasGesture() && m_frame.m_revision == revision &&
                     CanvasShape(m_canvasSnappedLine) == m_canvasBeforeEndpoint,
                     "Esc가 끝점 미리보기를 취소하지 못했습니다.");
        m_canvasUndoBefore = m_frame.m_editor.at("history").at("undo_count");
        m_canvasStage = 22;
        CanvasMouse(wxEVT_LEFT_DOWN, 10, 20, true);
        CanvasMouse(wxEVT_MOTION, 20.35, 20.35, true);
        CanvasAssert(m_frame.m_revision == revision, "끝점 드래그 미리보기가 원본을 변경했습니다.");
        CanvasMouse(wxEVT_LEFT_UP, 20.35, 20.35);
        break;
    }
    case 22:
    {
        m_canvasAfterEndpoint = CanvasShape(m_canvasSnappedLine);
        const Json start = m_canvasAfterEndpoint.at("start");
        m_canvasAfterEndpoint["start"] = m_canvasBeforeEndpoint.at("start");
        CanvasAssert(Near(start, {20, 20}) && m_canvasAfterEndpoint == m_canvasBeforeEndpoint &&
                     m_frame.m_editor.at("history").at("undo_count").get<int>() == m_canvasUndoBefore + 1,
                     "끝점 편집이 다른 형상 속성을 바꾸었거나 단일 명령으로 적용되지 않았습니다.");
        m_canvasAfterEndpoint["start"] = start;
        m_canvasChecks.push_back("endpoint_escape_then_one_command");
        m_canvasStage = 23;
        m_frame.History("project.undo", [this]() { CanvasSmokeNext(); });
        break;
    }
    case 23:
        CanvasAssert(CanvasShape(m_canvasSnappedLine) == m_canvasBeforeEndpoint, "끝점 실행 취소가 실패했습니다.");
        m_canvasStage = 24;
        m_frame.History("project.redo", [this]() { CanvasSmokeNext(); });
        break;
    case 24:
    {
        CanvasAssert(CanvasShape(m_canvasSnappedLine) == m_canvasAfterEndpoint, "끝점 다시 실행이 실패했습니다.");
        m_canvasChecks.push_back("endpoint_undo_redo");
        const auto arc = CanvasShape(m_canvasArc);
        const auto& center = arc.at("center");
        const double angle = arc.at("start_angle").get<double>() + arc.at("sweep_angle").get<double>() / 2.0;
        const auto middle = CanvasGeometry::ArcPoint({center.at(0), center.at(1)}, arc.at("radius"), angle);
        m_canvasBeforeEndpoint = arc;
        m_canvasStage = 25;
        m_canvasAwaitSelection = true;
        CanvasClick(middle.x, middle.y);
        break;
    }
    case 25:
    {
        CanvasAssert(m_frame.m_selection.at("id") == m_canvasArc, "원호 선택이 속성에 전달되지 않았습니다.");
        const std::string revision = m_frame.m_revision;
        const auto unchangedHistory = m_frame.m_editor.at("history");
        CanvasAssert(SnappedNoopRequests(*m_frame.m_canvas, ArcEndpoint(m_canvasBeforeEndpoint, false)) == 0 &&
                     !m_frame.m_canvas->HasGesture() && m_frame.m_revision == revision &&
                     m_frame.m_editor.at("history") == unchangedHistory && CanvasShape(m_canvasArc) == m_canvasBeforeEndpoint,
                     "같은 원호 시작점으로 스냅된 드래그가 명령이나 이력을 만들었습니다.");
        m_canvasChecks.push_back("endpoint_noop_omits_command");
        const auto end = ArcEndpoint(m_canvasBeforeEndpoint, true);
        const auto& center = m_canvasBeforeEndpoint.at("center");
        const double x = center.at(0).get<double>() - m_canvasBeforeEndpoint.at("radius").get<double>();
        const double y = center.at(1);
        m_canvasStage = 26;
        CanvasMouse(wxEVT_LEFT_DOWN, end.x, end.y, true);
        CanvasMouse(wxEVT_MOTION, x, y, true);
        CanvasMouse(wxEVT_LEFT_UP, x, y);
        break;
    }
    case 26:
    {
        auto arc = CanvasShape(m_canvasArc);
        const double sweep = arc.at("sweep_angle");
        arc["sweep_angle"] = m_canvasBeforeEndpoint.at("sweep_angle");
        CanvasAssert(arc == m_canvasBeforeEndpoint && std::abs(sweep - 180.0) < 2.0,
                     "원호 끝점 편집에서 중심/반지름/시작각이 바뀌었거나 회전 방향이 다릅니다.");
        m_canvasChecks.push_back("arc_endpoint_fixed_radius");
        CanvasSmokeSave();
        break;
    }
    }
}
