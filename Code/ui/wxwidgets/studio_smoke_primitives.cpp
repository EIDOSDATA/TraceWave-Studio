/** @file @brief 주 창의 smoke_primitives 책임을 구현한다. */
#include "studio_internal.h"

/** @brief 새로운 면/패드/비아를 실제 선택과 드래그 및 속성 명령으로 검증한다. */
void StudioSmokeDriver::PrimitivesSmokeTick()
{
    if (!m_frame.m_options.primitivesSmoke || m_frame.m_busy || m_frame.m_cadRestoring || m_frame.m_solverRestoring ||
        !m_frame.m_connected || m_frame.m_finishing || m_primitivesStage == 0)
    {
        return;
    }
    auto create = [this](int next, const std::string& operation, const Json& values)
    {
        m_primitivesStage = next;
        m_frame.CanvasCommand(operation, values);
    };
    if (m_primitivesStage == 1)
    {
        create(2, "create_circular_board",
               Json{{"id", Uuid()}, {"center_x_mm", 0}, {"center_y_mm", 0}, {"radius_mm", 35}});
    }
    else if (m_primitivesStage == 2)
    {
        m_primitivesLayerA = Uuid();
        create(3, "create_layer", Json{{"id", m_primitivesLayerA}, {"name", "Top"}});
    }
    else if (m_primitivesStage == 3 && m_frame.m_options.coordinatesSmoke)
    {
        Json outer = Json::array();
        for (int index = 0; index < 64; ++index)
        {
            const double angle = index * 2.0 * 3.14159265358979323846 / 64;
            outer.push_back(Json::array({10.0 * std::cos(angle), 10.0 * std::sin(angle)}));
        }
        m_primitivesPolygon = Uuid();
        create(101, "create_polygon",
               Json{{"id", m_primitivesPolygon},
                    {"layer_id", m_primitivesLayerA},
                    {"outer", outer},
                    {"holes", Json::array()}});
    }
    else if (m_primitivesStage == 3)
    {
        m_primitivesLayerB = Uuid();
        create(4, "create_layer", Json{{"id", m_primitivesLayerB}, {"name", "Bottom"}});
    }
    else if (m_primitivesStage == 4)
    {
        Json values = ParsePolygonInput("-20,-20\n20,-20\n20,20\n-20,20\n\n-4,-4\n4,-4\n4,4\n-4,4\n");
        m_primitivesPolygon = Uuid();
        values["id"] = m_primitivesPolygon;
        values["layer_id"] = m_primitivesLayerA;
        create(5, "create_polygon", values);
    }
    else if (m_primitivesStage == 5 || m_primitivesStage == 6 || m_primitivesStage == 7)
    {
        const bool rectangle = m_primitivesStage == 6;
        const std::string id = Uuid();
        if (rectangle)
        {
            m_primitivesRectangle = id;
        }
        else
        {
            m_primitivesPads.push_back(id);
        }
        create(m_primitivesStage + 1, "create_pad",
               Json{{"id", id},
                    {"layer_id", m_primitivesStage == 7 ? m_primitivesLayerB : m_primitivesLayerA},
                    {"pad_shape", rectangle ? "rectangle" : "circle"},
                    {"center", Json::array({rectangle ? -10.0 : 10.0, 0.0})},
                    {"width_mm", 4.0},
                    {"height_mm", rectangle ? 2.0 : 4.0},
                    {"rotation_deg", rectangle ? 45.0 : 0.0}});
    }
    else if (m_primitivesStage == 8 || m_primitivesStage == 9)
    {
        const bool missing = m_primitivesStage == 8;
        const std::string id = Uuid();
        if (missing)
        {
            m_primitivesMissingVia = id;
        }
        else
        {
            m_primitivesVia = id;
        }
        create(m_primitivesStage + 1, "create_via",
               Json{{"id", id},
                    {"layer_id", m_primitivesLayerA},
                    {"end_layer_id", m_primitivesLayerB},
                    {"center", Json::array({missing ? -10.0 : 10.0, missing ? 10.0 : 0.0})},
                    {"finished_hole_diameter_mm", missing ? Json(nullptr) : Json(0.8)},
                    {"plating_thickness_mm", missing ? Json(nullptr) : Json(0.1)},
                    {"tool_hole_diameter_mm", missing ? Json(nullptr) : Json(1.0)},
                    {"pad_ids", missing ? Json::array() : m_primitivesPads}});
    }
    else if (m_primitivesStage == 10)
    {
        CanvasAssert(m_frame.m_scene.at("shapes").size() == 6, "Primitive creation omitted display objects.");
        m_frame.m_canvas->FitView();
        m_frame.m_canvas->SetTool("select");
        CanvasAssert(m_frame.m_canvas->HitTest(m_frame.m_canvas->WorldToScreen(wxPoint2DDouble(0, 0))).empty(),
                     "Polygon hole was filled or selectable.");
        CanvasAssert(m_frame.m_canvas->HitTest(m_frame.m_canvas->WorldToScreen(wxPoint2DDouble(0, 15))) ==
                         m_primitivesPolygon,
                     "Polygon interior is not selectable.");
        CanvasAssert(CanvasShape(m_primitivesVia).at("span_layer_ids").size() == 2, "Via layer span is incomplete.");
        CanvasAssert(CanvasShape(m_primitivesMissingVia).at("finished_hole_diameter").is_null(),
                     "Missing via diameter was fabricated.");
        m_primitivesChecks.push_back("polygon_holes_and_pad_via_display");
        CanvasAssert(m_frame.m_editorPanel->FieldValue("pad_ids").size() == 2 && !m_frame.HasDraft(),
                     "Via pad references were not read without changing order.");
        m_frame.m_editorPanel->SetFieldValue("pad_ids", Json::array({m_primitivesPads.at(0)}));
        m_primitivesStage = 23;
        m_frame.ApplyCurrent(
            []()
            {
            });
    }
    else if (m_primitivesStage == 23)
    {
        CanvasAssert(m_frame.m_editorPanel->FieldValue("pad_ids").size() == 1,
                     "Via pad multichoice edit did not persist.");
        m_primitivesStage = 24;
        m_frame.History("project.undo",
                        [this]()
                        {
                            m_frame.SelectObject(Json{{"kind", "geometry"}, {"id", m_primitivesVia}});
                        });
    }
    else if (m_primitivesStage == 24)
    {
        CanvasAssert(m_frame.m_editorPanel->FieldValue("pad_ids").size() == 2, "Via pad reference undo failed.");
        m_primitivesChecks.push_back("via_pad_multichoice_and_undo");
        m_primitivesStage = 11;
        CanvasClick(-10, 0);
    }
    else if (m_primitivesStage == 11)
    {
        CanvasAssert(m_frame.m_selection.at("id") == m_primitivesRectangle &&
                         m_frame.m_canvas->Selection() == m_primitivesRectangle,
                     "Rotated pad selection did not reach properties.");
        m_frame.m_editorPanel->SetFieldValue("center.0.value", "-9");
        m_primitivesStage = 12;
        m_frame.ApplyCurrent(
            []()
            {
            });
    }
    else if (m_primitivesStage == 12)
    {
        CanvasAssert(CanvasShape(m_primitivesRectangle).at("center").at(0) == -9.0,
                     "Pad property edit did not reach canvas.");
        m_primitivesChecks.push_back("rotated_pad_selection_and_properties");
        m_primitivesOriginalPolygon = CanvasShape(m_primitivesPolygon);
        m_canvasUndoBefore = m_frame.m_editor.at("history").at("undo_count");
        m_primitivesStage = 13;
        CanvasMouse(wxEVT_LEFT_DOWN, 0, 15, true);
        CanvasMouse(wxEVT_MOTION, 2, 16, true);
        CanvasMouse(wxEVT_LEFT_UP, 2, 16);
    }
    else if (m_primitivesStage == 13)
    {
        const Json polygon = CanvasShape(m_primitivesPolygon);
        const double dx = polygon.at("outer").at(0).at(0).get<double>() + 20.0;
        CanvasAssert(std::abs(dx - 2) < 0.25 &&
                         std::abs(polygon.at("holes").at(0).at(0).at(0).get<double>() + 4.0 - dx) < 1e-8,
                     "Polygon drag failed to move its hole with its outline.");
        CanvasAssert(m_frame.m_editor.at("history").at("undo_count").get<int>() == m_canvasUndoBefore + 1,
                     "Polygon drag produced several history commands.");
        m_primitivesMovedPolygon = polygon;
        m_primitivesStage = 14;
        m_frame.History("project.undo");
    }
    else if (m_primitivesStage == 14)
    {
        CanvasAssert(CanvasShape(m_primitivesPolygon) == m_primitivesOriginalPolygon, "Polygon undo lost its hole.");
        m_primitivesStage = 15;
        m_frame.History("project.redo");
    }
    else if (m_primitivesStage == 15)
    {
        CanvasAssert(CanvasShape(m_primitivesPolygon) == m_primitivesMovedPolygon, "Polygon redo failed.");
        m_primitivesChecks.push_back("polygon_drag_single_command_and_history");
        m_frame.m_canvas->SetLayerVisible(m_primitivesLayerA, false);
        CanvasAssert(m_frame.m_canvas->HitTest(m_frame.m_canvas->WorldToScreen(wxPoint2DDouble(10, 0))) ==
                         m_primitivesVia,
                     "Via disappeared on its visible end layer.");
        m_frame.m_canvas->SetLayerVisible(m_primitivesLayerB, false);
        CanvasAssert(m_frame.m_canvas->HitTest(m_frame.m_canvas->WorldToScreen(wxPoint2DDouble(10, 0))).empty(),
                     "Fully hidden via remained selectable.");
        m_frame.m_canvas->SetLayerVisible(m_primitivesLayerA, true);
        m_frame.m_canvas->SetLayerVisible(m_primitivesLayerB, true);
        m_primitivesChecks.push_back("via_visibility_uses_full_layer_span");
        m_primitivesStage = 16;
        m_frame.SelectObject(Json{{"kind", "geometry"}, {"id", m_primitivesMissingVia}});
    }
    else if (m_primitivesStage == 16)
    {
        CanvasAssert(m_frame.m_editorPanel->FieldValue("finished_hole_diameter.mode") == "missing",
                     "Via missing input mode was lost.");
        m_frame.m_editorPanel->SetFieldValue("plating_thickness.mode", "value");
        m_frame.m_editorPanel->SetFieldValue("plating_thickness.unit", "mm");
        m_frame.m_editorPanel->SetFieldValue("plating_thickness.value", "0.1");
        m_primitivesStage = 17;
        m_frame.ApplyCurrent(
            []()
            {
            });
    }
    else if (m_primitivesStage == 17)
    {
        const Json via = CanvasShape(m_primitivesMissingVia);
        CanvasAssert(via.at("finished_hole_diameter").is_null() && via.at("tool_hole_diameter").is_null() &&
                         via.at("plating_thickness") == 0.1,
                     "Via editing fabricated missing manufacturing inputs.");
        m_primitivesStage = 18;
        m_frame.History("project.undo");
    }
    else if (m_primitivesStage == 18)
    {
        CanvasAssert(CanvasShape(m_primitivesMissingVia).at("plating_thickness").is_null(),
                     "Via undo did not restore missing input.");
        m_primitivesChecks.push_back("via_missing_inputs_edit_and_undo");
        m_primitivesSavedShapes = m_frame.m_scene.at("shapes");
        m_primitivesStage = 19;
        m_frame.SaveProject();
    }
    else if (m_primitivesStage == 19)
    {
        CanvasAssert(m_frame.m_savedRevision == m_frame.m_revision, "Primitive save did not settle.");
        m_primitivesStage = 20;
        m_frame.Snapshot();
    }
    else if (m_primitivesStage == 20)
    {
        CanvasAssert(!m_frame.m_snapshot.empty(), "Primitive snapshot was not created.");
        m_primitivesStage = 21;
        m_frame.m_connected = false;
        m_frame.m_transportFailed = false;
        m_frame.m_restarting = true;
        m_frame.BeginShutdown();
    }
    else if (m_primitivesStage == 101)
    {
        Json coordinates = m_frame.m_editorPanel->FieldValue("outer");
        CanvasAssert(coordinates.size() == 64 && !m_frame.HasDraft(),
                     "A 64-point coordinate table changed source or exceeded the DTO.");
        m_primitivesStage = 102;
        m_frame.m_busy = true;
        m_frame.m_editorPanel->EditCoordinateCellForSmoke("outer", 0, 0, "11");
        m_frame.m_busy = false;
        m_frame.ApplyCurrent(
            []()
            {
            });
    }
    else if (m_primitivesStage == 102)
    {
        CanvasAssert(CanvasShape(m_primitivesPolygon).at("outer").at(0).at(0) == 11.0 &&
                         m_frame.m_editorPanel->FieldValue("outer").size() == 64,
                     "Coordinate table edit did not preserve all vertices.");
        m_primitivesChecks.push_back("64_point_coordinate_table_edit");
        m_primitivesStage = 103;
        m_frame.History("project.undo");
    }
    else if (m_primitivesStage == 103)
    {
        CanvasAssert(CanvasShape(m_primitivesPolygon).at("outer").at(0).at(0) == 10.0, "Coordinate table undo failed.");
        m_primitivesChecks.push_back("coordinate_table_undo");
        m_primitivesSavedShapes = m_frame.m_scene.at("shapes");
        m_primitivesStage = 104;
        m_frame.SaveProject();
    }
    else if (m_primitivesStage == 104)
    {
        CanvasAssert(m_frame.m_savedRevision == m_frame.m_revision, "Coordinate table save failed.");
        m_primitivesStage = 105;
        m_frame.Snapshot();
    }
    else if (m_primitivesStage == 105)
    {
        m_primitivesStage = 106;
        m_frame.m_connected = false;
        m_frame.m_transportFailed = false;
        m_frame.m_restarting = true;
        m_frame.BeginShutdown();
    }
    else if (m_primitivesStage == 21 || m_primitivesStage == 106)
    {
        CanvasAssert(m_serviceSessions == 2 && m_frame.m_scene.at("shapes") == m_primitivesSavedShapes &&
                         m_frame.m_editor.at("saved_revision") == m_frame.m_revision,
                     "Primitive source or missing inputs changed after reopening.");
        m_primitivesChecks.push_back("save_snapshot_restart_preserves_primitives");
        m_primitivesStage = 22;
        FinishSmoke(true, "");
    }
}
