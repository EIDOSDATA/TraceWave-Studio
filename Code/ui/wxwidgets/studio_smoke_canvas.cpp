/** @file @brief 주 창의 smoke_canvas 책임을 구현한다. */
#include "studio_internal.h"

/** @brief 실제 캔버스 이벤트 처리기로 좌표 입력을 보내 서비스 저장까지 확인한다. */
void StudioSmokeDriver::CanvasMouse(wxEventType type, double x, double y, bool left, bool middle)
{
    wxMouseEvent event(type);
    event.SetPosition(m_frame.m_canvas->WorldToScreen(wxPoint2DDouble(x, y)));
    event.SetLeftDown(left);
    event.SetMiddleDown(middle);
    event.SetEventObject(m_frame.m_canvas);
    m_frame.m_canvas->GetEventHandler()->ProcessEvent(event);
}

void StudioSmokeDriver::CanvasClick(double x, double y)
{
    CanvasMouse(wxEVT_LEFT_DOWN, x, y, true);
    CanvasMouse(wxEVT_LEFT_UP, x, y);
}

Json StudioSmokeDriver::CanvasShape(const std::string& id) const
{
    for (const auto& shape : m_frame.m_scene.at("shapes"))
    {
        if (shape.at("id") == id)
        {
            return shape;
        }
    }
    throw std::runtime_error("Canvas smoke shape missing.");
}

void StudioSmokeDriver::CanvasAssert(bool condition, const std::string& message) const
{
    if (!condition)
    {
        throw std::runtime_error(message);
    }
}

/** @brief 도킹 창과 선/원호의 입력, 선택, 이동, 이력 및 재시작을 통합 검사한다. */
void StudioSmokeDriver::CanvasSmokeNext()
{
    if (m_canvasStage == 0)
    {
        CanvasAssert(m_frame.m_manager->GetPane("canvas").IsOk() && m_frame.m_manager->GetPane("properties").IsOk() &&
                         m_frame.m_manager->GetPane("problems").IsOk(),
                     "Docking shell missing.");
        for (const int id : {IdCreate, IdOpen, IdSave, IdSnapshot, IdUndo, IdRedo})
        {
            const wxButton* button = m_frame.m_tools.at(id);
            const wxSize area = button->GetParent()->GetClientSize();
            CanvasAssert(button->GetRect().GetBottom() <= area.GetHeight() &&
                             button->GetRect().GetRight() <= area.GetWidth() && button->GetSize().GetHeight() > 0,
                         "Workspace toolbar is clipped.");
        }
        m_canvasChecks.push_back("docking_shell");
        m_canvasStage = 1;
        m_frame.CanvasCommand("create_board", Json{{"id", Uuid()}, {"width_mm", 40.0}, {"height_mm", 60.0}});
    }
    else if (m_canvasStage == 1)
    {
        m_canvasStage = 2;
        m_frame.CanvasCommand("create_layer", Json{{"id", Uuid()}, {"name", "검증 도체층"}});
    }
    else if (m_canvasStage == 2)
    {
        CanvasAssert(!m_frame.m_activeLayer.empty() && m_frame.m_scene.at("board").at("width") == 40.0,
                     "Drawing prerequisites not available.");
        m_frame.m_canvas->FitView();
        m_frame.m_canvas->SetTool("line");
        CanvasClick(5, 5);
        wxKeyEvent escape(wxEVT_KEY_DOWN);
        escape.m_keyCode = WXK_ESCAPE;
        m_frame.m_canvas->GetEventHandler()->ProcessEvent(escape);
        CanvasAssert(!m_frame.m_canvas->HasGesture() && m_frame.m_scene.at("shapes").empty(),
                     "Escape committed a drawing.");
        m_canvasChecks.push_back("escape_cancels_preview");
        m_frame.m_canvas->SetTool("line");
        m_canvasStage = 3;
        CanvasClick(5, 5);
        CanvasClick(25, 5);
    }
    else if (m_canvasStage == 3)
    {
        CanvasAssert(m_frame.m_scene.at("shapes").size() == 1 &&
                         m_frame.m_scene.at("shapes").at(0).at("kind") == "line_path",
                     "Two-click line failed.");
        m_canvasLine = m_frame.m_scene.at("shapes").at(0).at("id");
        m_canvasOriginalLine = CanvasShape(m_canvasLine);
        m_canvasChecks.push_back("two_click_line");
        m_frame.m_canvas->SetTool("arc");
        m_canvasStage = 4;
        CanvasClick(20, 30);
        CanvasClick(30, 30);
        CanvasClick(20, 40);
    }
    else if (m_canvasStage == 4)
    {
        CanvasAssert(m_frame.m_scene.at("shapes").size() == 2, "Three-click arc failed.");
        for (const auto& shape : m_frame.m_scene.at("shapes"))
        {
            if (shape.at("kind") == "arc_path")
            {
                m_canvasArc = shape.at("id");
                CanvasAssert(std::abs(shape.at("sweep_angle").get<double>() - 90.0) < 2.0, "Arc direction is not CCW.");
            }
        }
        CanvasAssert(!m_canvasArc.empty() && m_frame.m_canvas->HitTest(m_frame.m_canvas->WorldToScreen(
                                                 wxPoint2DDouble(20, 20))) != m_canvasArc,
                     "Arc hit testing includes the unused circle.");
        m_canvasChecks.push_back("three_click_arc_and_hit_test");
        m_frame.m_canvas->SetTool("select");
        m_canvasStage = 5;
        m_canvasAwaitSelection = true;
        CanvasClick(15, 5);
    }
    else if (m_canvasStage == 5)
    {
        CanvasAssert(m_frame.m_selection.at("id") == m_canvasLine && m_frame.m_canvas->Selection() == m_canvasLine,
                     "Canvas selection does not match properties.");
        m_canvasChecks.push_back("selection_sync");
        m_canvasUndoBefore = m_frame.m_editor.at("history").at("undo_count");
        const std::string before = m_frame.m_revision;
        m_canvasStage = 6;
        CanvasMouse(wxEVT_LEFT_DOWN, 15, 5, true);
        CanvasMouse(wxEVT_MOTION, 18, 7, true);
        CanvasAssert(m_frame.m_revision == before, "Drag preview mutated the project.");
        CanvasMouse(wxEVT_LEFT_UP, 18, 7);
    }
    else if (m_canvasStage == 6)
    {
        const Json moved = CanvasShape(m_canvasLine);
        CanvasAssert(std::abs(moved.at("start").at(0).get<double>() -
                              m_canvasOriginalLine.at("start").at(0).get<double>() - 3.0) < 0.25,
                     "Drag X translation failed.");
        CanvasAssert(m_frame.m_editor.at("history").at("undo_count").get<int>() == m_canvasUndoBefore + 1,
                     "Drag is not one history entry.");
        m_canvasChecks.push_back("drag_one_command");
        m_canvasMovedLine = moved;
        m_canvasStage = 7;
        m_frame.History("project.undo",
                        [this]()
                        {
                            CanvasSmokeNext();
                        });
    }
    else if (m_canvasStage == 7)
    {
        CanvasAssert(CanvasShape(m_canvasLine) == m_canvasOriginalLine, "Undo did not restore line.");
        m_canvasStage = 8;
        m_frame.History("project.redo",
                        [this]()
                        {
                            CanvasSmokeNext();
                        });
    }
    else if (m_canvasStage == 8)
    {
        CanvasAssert(CanvasShape(m_canvasLine) == m_canvasMovedLine, "Redo did not restore moved line.");
        m_canvasChecks.push_back("drag_undo_redo");
        m_frame.RefreshEditor(Json{{"kind", "geometry"}, {"id", m_canvasLine}},
                              [this]()
                              {
                                  m_frame.m_editorPanel->SetFieldValue("end.0.value", "32");
                                  m_canvasStage = 9;
                                  m_frame.ApplyCurrent(
                                      [this]()
                                      {
                                          CanvasSmokeNext();
                                      });
                              });
    }
    else if (m_canvasStage == 9)
    {
        CanvasAssert(CanvasShape(m_canvasLine).at("end").at(0) == 32.0, "Property change did not refresh canvas.");
        m_canvasChecks.push_back("property_to_canvas");
        m_frame.m_canvas->SetSelection(m_canvasArc);
        const std::string before = m_frame.m_revision;
        m_frame.m_busy = true;
        m_frame.m_canvas->onAction(
            Json{{"type", "translate"}, {"id", m_canvasArc}, {"delta", Json::array({1.0, 0.0})}});
        CanvasAssert(m_frame.m_canvas->Selection() == m_canvasLine && m_frame.m_selection.at("id") == m_canvasLine &&
                         m_frame.m_revision == before,
                     "Rejected gesture did not restore authoritative selection.");
        m_frame.m_busy = false;
        m_frame.UpdateControls();
        m_canvasChecks.push_back("rejected_gesture_restores_selection");
        m_canvasStage = 10;
        m_frame.CanvasCommand("remove", Json{{"id", m_canvasLine}});
    }
    else if (m_canvasStage == 10)
    {
        CanvasAssert(m_frame.m_scene.at("shapes").size() == 1, "Delete failed.");
        m_canvasStage = 11;
        m_frame.History("project.undo",
                        [this]()
                        {
                            CanvasSmokeNext();
                        });
    }
    else if (m_canvasStage == 11)
    {
        CanvasAssert(m_frame.m_scene.at("shapes").size() == 2 && CanvasShape(m_canvasLine).at("end").at(0) == 32.0,
                     "Delete undo failed.");
        m_canvasChecks.push_back("delete_undo");
        const Json line = CanvasShape(m_canvasLine);
        const wxPoint2DDouble midpoint(
            (line.at("start").at(0).get<double>() + line.at("end").at(0).get<double>()) / 2.0,
            (line.at("start").at(1).get<double>() + line.at("end").at(1).get<double>()) / 2.0);
        Json boundary = m_frame.m_scene;
        boundary["board"]["width"] = nullptr;
        Json huge = line;
        huge["id"] = Uuid();
        huge["start"] = Json::array({1e10, 1e10});
        huge["end"] = Json::array({1e10 + 10, 1e10});
        boundary["shapes"].push_back(huge);
        m_frame.m_canvas->SetScene(boundary);
        CanvasAssert(m_frame.m_canvas->DisplayOmissionCount() >= 1 &&
                         m_frame.m_canvas->HitTest(m_frame.m_canvas->WorldToScreen(midpoint)) == m_canvasLine,
                     "An unrenderable object hid valid geometry.");
        m_frame.m_canvas->SetScene(m_frame.m_scene);
        m_canvasChecks.push_back("display_limits_preserve_valid_shapes");
        const std::string revision = m_frame.m_revision;
        const wxPoint anchor = m_frame.m_canvas->WorldToScreen(midpoint);
        const auto before = m_frame.m_canvas->ScreenToWorld(anchor);
        wxMouseEvent wheel(wxEVT_MOUSEWHEEL);
        wheel.SetPosition(anchor);
        wheel.m_wheelRotation = 120;
        wheel.m_wheelDelta = 120;
        m_frame.m_canvas->GetEventHandler()->ProcessEvent(wheel);
        const auto after = m_frame.m_canvas->ScreenToWorld(anchor);
        CanvasAssert(std::hypot(before.m_x - after.m_x, before.m_y - after.m_y) < 1e-7, "Zoom moved its world anchor.");
        m_frame.m_canvas->SetLayerVisible(m_frame.m_activeLayer, false);
        CanvasAssert(m_frame.m_canvas->HitTest(anchor).empty(), "Hidden layer remains selectable.");
        m_frame.m_canvas->SetLayerVisible(m_frame.m_activeLayer, true);
        wxMouseEvent panStart(wxEVT_MIDDLE_DOWN);
        panStart.SetPosition(anchor);
        panStart.SetMiddleDown(true);
        m_frame.m_canvas->GetEventHandler()->ProcessEvent(panStart);
        wxMouseEvent panMove(wxEVT_MOTION);
        panMove.SetPosition(anchor + wxPoint(20, 10));
        panMove.SetMiddleDown(true);
        m_frame.m_canvas->GetEventHandler()->ProcessEvent(panMove);
        wxMouseEvent panEnd(wxEVT_MIDDLE_UP);
        panEnd.SetPosition(anchor + wxPoint(20, 10));
        m_frame.m_canvas->GetEventHandler()->ProcessEvent(panEnd);
        CanvasAssert(m_frame.m_canvas->WorldToScreen(midpoint) == anchor + wxPoint(20, 10) &&
                         m_frame.m_revision == revision,
                     "View-only pan mutated geometry or failed.");
        m_frame.m_canvas->FitView();
        m_canvasChecks.push_back("view_controls_do_not_edit");
        m_canvasSavedShapes = m_frame.m_scene.at("shapes");
        m_canvasStage = 12;
        m_frame.ValidateInput(
            [this]()
            {
                CanvasAssert(!m_frame.m_diagnostics.empty() && m_frame.m_problemRevision == m_frame.m_revision,
                             "Missing EM inputs were not shown.");
                for (std::size_t index = 0; index < m_frame.m_diagnostics.size(); ++index)
                {
                    CanvasAssert(Utf8(m_frame.m_problems->GetItemText(static_cast<long>(index), 1)) ==
                                     m_frame.m_diagnostics.at(index).at("message_ko").get<std::string>(),
                                 "The problem list lost the service's Korean diagnostic message.");
                }
                m_canvasChecks.push_back("input_check_not_simulation");
                m_frame.SaveProject();
            });
    }
    else if (m_canvasStage == 14)
    {
        CanvasAssert(m_frame.m_scene.at("shapes") == m_canvasSavedShapes &&
                         m_frame.m_savedRevision == m_frame.m_revision &&
                         m_frame.m_editor.at("saved_revision") == m_frame.m_revision,
                     "Canvas persistence failed.");
        m_canvasChecks.push_back("save_snapshot_restart");
        m_canvasStage = 15;
        FinishSmoke(true, "");
    }
}
