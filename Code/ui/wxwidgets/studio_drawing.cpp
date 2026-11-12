/** @file @brief 주 창의 drawing 책임을 구현한다. */
#include "studio_internal.h"

void StudioFrame::BindCanvas()
{
    m_canvas->onStatus = [this](const std::string& message)
    {
        m_canvasHint->SetLabel(Display(message));
    };
    m_canvas->onSelection = [this](const std::string& identity)
    {
        if (m_busy || !ConfirmDiscard())
        {
            m_canvas->SetSelection(m_selection.value("kind", "") == "geometry" ? m_selection.value("id", "") : "");
            return;
        }
        SelectObject(identity.empty() ? Json{{"kind", "project"}, {"id", m_project}}
                                      : Json{{"kind", "geometry"}, {"id", identity}});
    };
    m_canvas->onAction = [this](const Json& action)
    {
        if (m_busy || !ConfirmDiscard())
        {
            RestoreCanvas();
            return;
        }
        const std::string type = action.at("type");
        Json values = action;
        values.erase("type");
        if (type == "create_line" || type == "create_arc")
        {
            values["id"] = Uuid();
            values["width_mm"] = values.at("width");
            values.erase("width");
            if (type == "create_arc")
            {
                values["radius_mm"] = values.at("radius");
                values["start_angle_deg"] = values.at("start_angle");
                values["sweep_angle_deg"] = values.at("sweep_angle");
                values.erase("radius");
                values.erase("start_angle");
                values.erase("sweep_angle");
            }
        }
        else if (type == "translate")
        {
            values["dx_mm"] = values.at("delta").at(0);
            values["dy_mm"] = values.at("delta").at(1);
            values.erase("delta");
        }
        CanvasCommand(type, values);
    };
    m_layerChoice->Bind(wxEVT_CHOICE,
                        [this](wxCommandEvent&)
                        {
                            const int index = m_layerChoice->GetSelection();
                            if (index >= 0 && static_cast<std::size_t>(index) < m_layerIds.size())
                            {
                                m_activeLayer = m_layerIds[index];
                                m_canvas->SetDrawingLayer(m_activeLayer);
                                RefreshLayerList();
                            }
                        });
    m_width->Bind(wxEVT_SPINCTRLDOUBLE,
                  [this](wxSpinDoubleEvent&)
                  {
                      UpdateStrokeWidth();
                  });
    m_width->Bind(wxEVT_TEXT,
                  [this](wxCommandEvent&)
                  {
                      UpdateStrokeWidth();
                  });
    for (const auto& tool :
         std::vector<std::pair<int, std::string>>{{IdSelect, "select"}, {IdLine, "line"}, {IdArc, "arc"}})
    {
        Bind(
            wxEVT_MENU,
            [this, name = tool.second](wxCommandEvent&)
            {
                if (ConfirmDiscard())
                {
                    auto activate = [this, name]()
                    {
                        m_drawTool = name;
                        m_canvas->SetTool(name);
                        m_canvas->SetFocus();
                    };
                    if (HasDraft())
                    {
                        RefreshEditor(m_selection,
                                      [this, activate]()
                                      {
                                          Ready("미적용 입력을 버리고 도구를 선택했습니다.");
                                          activate();
                                      });
                    }
                    else
                    {
                        activate();
                    }
                }
            },
            tool.first);
    }
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            m_canvas->FitView();
        },
        IdFit);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            m_manager->LoadPerspective(m_defaultLayout);
        },
        IdResetLayout);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            if (!m_busy && ConfirmDiscard())
            {
                Json values{{"width_mm", 40.0}, {"height_mm", 60.0}};
                if (AskNumbers("기판 외형 / mm", {{"width_mm", "폭 (mm)", 40}, {"height_mm", "길이 (mm)", 60}}, values))
                {
                    values["id"] = Uuid();
                    CanvasCommand("create_board", values);
                }
            }
        },
        IdBoard);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            if (!m_busy && ConfirmDiscard())
            {
                Json values{{"center_x_mm", 0.0}, {"center_y_mm", 0.0}, {"radius_mm", 30.0}};
                if (AskNumbers("원형 기판 외형 / mm",
                               {{"center_x_mm", "중심 X (mm)", 0},
                                {"center_y_mm", "중심 Y (mm)", 0},
                                {"radius_mm", "반지름 (mm)", 30}},
                               values))
                {
                    values["id"] = Uuid();
                    CanvasCommand("create_circular_board", values);
                }
            }
        },
        IdCircularBoard);
    for (const auto& object : std::vector<std::pair<int, std::string>>{
             {IdNewMaterial, "new_material"}, {IdNewNet, "new_net"}, {IdNewPort, "new_port"}})
    {
        Bind(
            wxEVT_MENU,
            [this, kind = object.second](wxCommandEvent&)
            {
                if (!m_busy && ConfirmDiscard())
                {
                    SelectObject(Json{{"kind", kind}, {"id", Uuid()}});
                }
            },
            object.first);
    }
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            if (!m_busy && ConfirmDiscard())
            {
                const wxString name = wxGetTextFromUser(Display("도체층 이름. 위치/두께/재료는 미정으로 생성합니다."),
                                                        Display("도체층 추가"), "Top Copper", this);
                if (!name.empty())
                {
                    CanvasCommand("create_layer", Json{{"id", Uuid()}, {"name", Utf8(name)}});
                }
            }
        },
        IdLayer);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            if (!m_busy && ConfirmDiscard())
            {
                const wxString name = wxGetTextFromUser(Display("유전체층 이름. 위치/두께/물성은 직접 입력합니다."),
                                                        Display("유전체층 추가"), Display("기판 유전체"), this);
                if (!name.empty())
                {
                    CanvasCommand("create_dielectric_layer", Json{{"id", Uuid()}, {"name", Utf8(name)}});
                }
            }
        },
        IdDielectric);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            AddCoordinates();
        },
        IdCoordinates);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            AddPolygon();
        },
        IdPolygon);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            AddPad(true);
        },
        IdCirclePad);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            AddPad(false);
        },
        IdRectanglePad);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            AddVia();
        },
        IdVia);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            if (!m_busy && m_selection.value("kind", "") == "geometry" && ConfirmDiscard())
            {
                CanvasCommand("remove", Json{{"id", m_selection.at("id")}});
            }
        },
        IdDeleteShape);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            ValidateInput();
        },
        IdValidate);
    m_steps->Bind(wxEVT_LISTBOX,
                  [this](wxCommandEvent& event)
                  {
                      if (m_busy || !ConfirmDiscard())
                      {
                          return;
                      }
                      const int step = event.GetSelection();
                      if (step == 1)
                      {
                          m_canvas->SetFocus();
                          return;
                      }
                      if (step == 4)
                      {
                          ValidateInput();
                          return;
                      }
                      const std::string kind = step == 0 ? "board" : (step == 2 ? "material" : "port");
                      for (const auto& item : m_editor.at("items"))
                      {
                          if (item.at("kind") == kind)
                          {
                              SelectObject(Json{{"kind", kind}, {"id", item.at("id")}});
                              return;
                          }
                      }
                      Log("해당 객체가 없습니다. 설계 메뉴에서 기판, 재료 또는 급전 포트를 추가하세요.");
                  });
    m_problems->Bind(wxEVT_LIST_ITEM_ACTIVATED,
                     [this](wxListEvent& event)
                     {
                         OpenProblem(event.GetIndex());
                     });
}

/** @brief 화면 초안을 도메인 명령 하나로 적용하고 권위 scene을 다시 읽는다. */
void StudioFrame::CanvasCommand(const std::string& operation, const Json& values, std::function<void()> completed)
{
    m_busy = true;
    UpdateControls();
    Send(
        "canvas.apply",
        Json{{"expected_revision", m_revision}, {"command_id", Uuid()}, {"operation", operation}, {"values", values}},
        true, Context(),
        [this, operation, values, completed](const Json& result)
        {
            m_revision = result.at("new_revision");
            const std::string kind =
                (operation == "create_board" || operation == "create_circular_board")
                    ? "board"
                    : ((operation == "create_layer" || operation == "create_dielectric_layer") ? "layer" : "geometry");
            const Json selection = operation == "remove" ? Json{{"kind", "project"}, {"id", m_project}}
                                                         : Json{{"kind", kind}, {"id", values.at("id")}};
            RefreshEditor(selection,
                          [this, completed]()
                          {
                              Ready("2D 편집을 적용했습니다.");
                              if (completed)
                              {
                                  completed();
                              }
                              else if (m_options.canvasSmoke)
                              {
                                  m_smoke->CanvasSmokeNext();
                              }
                          });
        },
        [this](const Json& error)
        {
            RestoreCanvas();
            Failure(error.value("message", std::string("2D 편집을 적용하지 못했습니다.")));
        });
}

/** @brief 거절된 드래그의 강조를 속성 패널의 권위 선택으로 되돌린다. */
void StudioFrame::RestoreCanvas()
{
    m_canvas->SetScene(m_scene);
    m_canvas->SetSelection(m_selection.value("kind", "") == "geometry" ? m_selection.value("id", "") : "");
}
