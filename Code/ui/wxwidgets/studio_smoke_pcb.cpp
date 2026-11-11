/** @file @brief 실제 PCB 설정 컨트롤과 공개 서비스의 비동기 통합 시험이다. */
#include "studio_internal.h"
#include "pcb_selection_dialog.h"
#include <wx/combobox.h>
#include <wx/grid.h>

namespace
{
/** @brief 제품 버튼과 같은 이벤트 처리 경로를 사용한다. */
void ClickPcbButton(wxButton* button)
{
    if (button == nullptr || !button->IsEnabled())
    {
        throw std::runtime_error("PCB smoke: 필요한 버튼이 없거나 비활성입니다.");
    }
    wxCommandEvent clicked(wxEVT_BUTTON, button->GetId());
    clicked.SetEventObject(button);
    button->GetEventHandler()->ProcessEvent(clicked);
}

/** @brief 선택 변경 이벤트가 검색 세대와 적용 승인을 실제로 무효화하게 한다. */
void ChoosePcbValue(wxChoice* choice, int index)
{
    choice->SetSelection(index);
    wxCommandEvent changed(wxEVT_CHOICE, choice->GetId());
    changed.SetInt(index);
    changed.SetEventObject(choice);
    choice->GetEventHandler()->ProcessEvent(changed);
}

/** @brief 화면이 제공한 이름으로 실제 동작 버튼을 찾는다. */
wxButton* PcbButton(wxWindow& dialog, const char* name)
{
    return dynamic_cast<wxButton*>(wxWindow::FindWindowByName(name, &dialog));
}

/** @brief 좌표 편집 시험과 같은 실제 wxGrid 변경 이벤트를 전달한다. */
void EditPcbCell(wxGrid* grid, int row, int column, const std::string& value)
{
    if (row >= grid->GetNumberRows() || grid->IsReadOnly(row, column))
    {
        throw std::runtime_error("PCB smoke: 편집할 격자 셀을 사용할 수 없습니다.");
    }
    grid->SetGridCursor(row, column);
    grid->SetCellValue(row, column, Display(value));
    wxGridEvent changed(grid->GetId(), wxEVT_GRID_CELL_CHANGED, grid, row, column);
    grid->GetEventHandler()->ProcessEvent(changed);
}
}

void StudioSmokeDriver::PcbSmokeTick()
{
    if (!m_frame.m_options.pcbSmoke || m_frame.m_finishing || !m_frame.m_connected || m_pcbStage == 0)
    {
        return;
    }
    ++m_pcbTicks;
    try
    {
        if (Clock::now() - m_pcbStarted > std::chrono::seconds(60))
        {
            throw std::runtime_error("PCB smoke 단계 " + std::to_string(m_pcbStage) +
                                     "의 전체 제한 시간을 초과했습니다.");
        }
        if (m_frame.m_pcbDialog != nullptr)
        {
            if (m_frame.m_requests.Size() != 0)
            {
                ++m_pcbRequestTicks;
            }
            PcbSmokeDialog(*m_frame.m_pcbDialog);
        }
        else if (!m_frame.m_busy && !m_frame.m_cadRestoring && !m_frame.m_solverRestoring)
        {
            if (m_pcbStage <= 4)
            {
                PcbSmokePrepare();
            }
            else
            {
                PcbSmokeHistory();
            }
        }
    }
    catch (const std::exception& error)
    {
        FinishSmoke(false, "PCB smoke 단계 " + std::to_string(m_pcbStage) + ": " + error.what());
    }
}

void StudioSmokeDriver::PcbSmokePrepare()
{
    if (m_pcbStage == 1)
    {
        m_pcbStage = 2;
        m_frame.CanvasCommand("create_circular_board",
                              {{"id", Uuid()}, {"center_x_mm", 0.0}, {"center_y_mm", 0.0}, {"radius_mm", 30.0}});
    }
    else if (m_pcbStage == 2)
    {
        m_pcbLayer = Uuid();
        m_pcbStage = 3;
        m_frame.CanvasCommand("create_layer", {{"id", m_pcbLayer}, {"name", "기존 도체층"}});
    }
    else if (m_pcbStage == 3)
    {
        m_pcbPattern = Uuid();
        m_pcbStage = 4;
        m_frame.CanvasCommand("create_line", {{"id", m_pcbPattern},
                                              {"layer_id", m_pcbLayer},
                                              {"width_mm", 1.0},
                                              {"start", Json::array({-10.0, 0.0})},
                                              {"end", Json::array({10.0, 0.0})}});
    }
    else if (m_pcbStage == 4)
    {
        m_pcbOriginalBoard = m_frame.m_scene.at("board");
        m_pcbOriginalPattern = CanvasShape(m_pcbPattern);
        m_pcbOriginalLayers = m_frame.m_scene.at("layers");
        m_pcbBeforeRevision = m_frame.m_revision;
        m_pcbUndoBefore = m_frame.m_editor.at("history").at("undo_count");
        CanvasAssert(m_pcbOriginalBoard.at("kind") == "circle" && m_pcbOriginalPattern.at("layer_id") == m_pcbLayer,
                     "원형 외곽과 기존 패턴 참조를 준비하지 못했습니다.");
        m_pcbChecks.push_back("circular_outline_and_pattern_fixture");
        m_pcbStage = 5;
        m_frame.CallAfter(
            [this]()
            {
                m_frame.OpenPcbSelection();
            });
    }
}

void StudioSmokeDriver::PcbSmokeDialog(PcbSelectionDialog& dialog)
{
    const bool requestPending = m_frame.m_requests.Size() != 0;
    if (m_pcbStage == 40)
    {
        dialog.m_notebook->SetSelection(0);
        ClickPcbButton(dialog.m_search);
        CanvasAssert(m_frame.m_requests.Size() != 0 && !dialog.m_closed,
                     "부모 종료 검사에 필요한 열린 모달과 미응답 조회가 없습니다.");
        m_pcbStage = 41;
        const bool closed = m_frame.Close(false);
        CanvasAssert(!closed && m_frame.m_closeAfterPcb && !m_frame.m_closing,
                     "부모 종료가 모달 반환까지 연기되지 않았습니다.");
        return;
    }
    if (m_pcbStage == 5 || m_pcbStage == 8 || m_pcbStage == 33)
    {
        if (requestPending || (!dialog.m_searchResult.contains("items") && dialog.m_model.Error().is_null()))
        {
            return;
        }
        if (m_pcbStage == 33)
        {
            CanvasAssert(!dialog.m_context.at("selection").is_null() && dialog.m_context.at("layers").size() == 3,
                         "저장 후 다시 연 화면에 적용한 선택이 없습니다.");
            CanvasAssert(std::abs(dialog.m_context.at("layers").at(1).at("thickness_mm").get<double>() - 1.5) < 1e-10,
                         "다시 연 화면의 유전체 두께가 다릅니다.");
            CanvasAssert(dialog.m_context.at("materials").size() == 1 &&
                             dialog.m_context.at("layers").at(1).at("material_id") == m_pcbExpectedMaterial.at("id"),
                         "재열기한 층의 재료 연결이 보존되지 않았습니다.");
            m_pcbChecks.push_back("saved_selection_dialog_reopened");
            m_pcbStage = 36;
            m_frame.Send("pcb.selection.get", Json::object(), false, m_frame.Context(),
                         [this](const Json& result)
                         {
                             CanvasAssert(!result.at("modified_since_selection").get<bool>(),
                                          "저장 후 재료 선택의 원문과 현재 값이 달라졌습니다.");
                             int checked = 0;
                             for (const auto& decision : result.at("selection").at("decisions"))
                             {
                                 const auto& target = decision.at("target");
                                 const std::string field = target.at("field");
                                 if (target.at("collection") != "materials" ||
                                     target.at("id") != m_pcbExpectedMaterial.at("id") ||
                                     (field != "epsilon_r" && field != "tan_delta" && field != "conductivity"))
                                 {
                                     continue;
                                 }
                                 CanvasAssert(Json::parse(decision.at("value_json").get<std::string>()) ==
                                                      m_pcbExpectedMaterial.at(field) &&
                                                  !decision.at("reason").get<std::string>().empty(),
                                              "재열기한 물성의 선택값이나 이유가 다릅니다.");
                                 const bool published = field == "epsilon_r" && !m_frame.m_options.catalog.empty();
                                 const bool override = field == "tan_delta" && !m_frame.m_options.catalog.empty();
                                 CanvasAssert(
                                     decision.at("basis") ==
                                         (published ? "published" : (override ? "user_override" : "user_assumption")),
                                     "Dk 관측과 사용자 가정의 출처 구분이 바뀌었습니다.");
                                 if (published)
                                 {
                                     CanvasAssert(decision.at("source_pointer") == "/dk" &&
                                                      !decision.at("evidence_id").is_null(),
                                                  "Dk 원문 위치와 근거가 보존되지 않았습니다.");
                                 }
                                 ++checked;
                             }
                             CanvasAssert(checked == 3, "저장한 세 물성의 선택 기록이 불완전합니다.");
                             m_pcbChecks.push_back("saved_material_values_and_provenance");
                             m_pcbStage = 37;
                         });
            return;
        }
        m_pcbExistingLabel = Utf8(dialog.m_layers->GetCellValue(0, 4));
        if (m_frame.m_options.catalog.empty())
        {
            dialog.m_notebook->SetSelection(1);
            ClickPcbButton(dialog.m_manualButton);
            ClickPcbButton(dialog.m_addLayer);
            ClickPcbButton(dialog.m_addLayer);
            EditPcbCell(dialog.m_layers, 0, 0, "아래 동박");
            EditPcbCell(dialog.m_layers, 0, 1, "도체");
            EditPcbCell(dialog.m_layers, 1, 0, "검증 코어");
            EditPcbCell(dialog.m_layers, 1, 1, "유전체");
            EditPcbCell(dialog.m_layers, 2, 0, "위 동박");
            EditPcbCell(dialog.m_layers, 2, 1, "도체");
            m_pcbChecks.push_back("manual_input_without_catalog");
            m_pcbStage = 16;
            return;
        }
        ChoosePcbValue(dialog.m_entity, 1);
        dialog.m_publisher->SetValue(Display("OSH Park"));
        dialog.m_query->SetValue("2 layer 1.6");
        ClickPcbButton(dialog.m_search);
        if (m_pcbStage == 5)
        {
            dialog.m_query->SetValue("discarded search must not replace this input");
            m_pcbStage = 6;
        }
        else
        {
            m_pcbStage = 9;
        }
    }
    else if (m_pcbStage == 6 && !requestPending)
    {
        CanvasAssert(dialog.m_results->GetItemCount() == 0 &&
                         dialog.m_query->GetValue() == "discarded search must not replace this input",
                     "늦은 검색 응답이 변경된 검색 조건에 적용되었습니다.");
        m_pcbChecks.push_back("late_search_response_ignored");
        dialog.m_query->SetValue("2 layer 1.6");
        ClickPcbButton(dialog.m_search);
        m_pcbStage = 7;
        ClickPcbButton(dialog.m_cancelButton);
    }
    else if (m_pcbStage == 9 && !requestPending)
    {
        CanvasAssert(dialog.m_searchResult.contains("items") && !dialog.m_searchResult.at("items").empty(),
                     "실제 카탈로그 검색 결과가 없습니다.");
        long selected = -1;
        for (std::size_t index = 0; index < dialog.m_searchResult.at("items").size(); ++index)
        {
            if (dialog.m_searchResult.at("items").at(index).at("id") == "PCB056952")
            {
                selected = static_cast<long>(index);
            }
        }
        CanvasAssert(selected >= 0, "검증용 2층 관측을 찾지 못했습니다.");
        dialog.m_results->SetItemState(selected, wxLIST_STATE_SELECTED, wxLIST_STATE_SELECTED);
        wxListEvent chosen(wxEVT_LIST_ITEM_SELECTED, dialog.m_results->GetId());
        chosen.SetIndex(selected);
        chosen.SetEventObject(dialog.m_results);
        dialog.m_results->GetEventHandler()->ProcessEvent(chosen);
        m_pcbStage = 10;
    }
    else if (m_pcbStage == 10 && !requestPending)
    {
        m_pcbStage = 11;
        ClickPcbButton(dialog.m_useSource);
    }
    else if (m_pcbStage == 11 && !requestPending)
    {
        CanvasAssert(!dialog.m_model.Draft().is_null() && dialog.m_layers->GetNumberRows() == 3,
                     "선택 자료가 세 물리 층의 검토용 초안으로 표시되지 않았습니다.");
        CanvasAssert(dialog.m_suggestions->GetItemCount() == 3 && dialog.m_materialSpecs.empty() &&
                         dialog.m_suggestionData.at("layers").at(1).at("properties").at("epsilon_r").at("state") ==
                             "published" &&
                         dialog.m_suggestionData.at("layers").at(1).at("properties").at("tan_delta").at("state") ==
                             "missing",
                     "적층 물성 제안이 공개 Dk와 미정 Df를 구분하지 않거나 조회만으로 채택되었습니다.");
        dialog.m_materialName->SetValue(Display("페이지 조회 중 작성한 입력"));
        EditPcbCell(dialog.m_layers, 1, 2, "1.51");
        EditPcbCell(dialog.m_layers, 1, 3, "페이지 조회 입력 보존 시험");
        dialog.LoadSuggestionPage(1);
        m_pcbStage = 12;
    }
    else if (m_pcbStage == 12 && !requestPending)
    {
        CanvasAssert(dialog.m_suggestionData.at("offset") == 1 && dialog.m_suggestions->GetItemCount() == 2 &&
                         dialog.m_materialName->GetValue() == Display("페이지 조회 중 작성한 입력") &&
                         dialog.m_materialDirty && dialog.m_layers->GetCellValue(1, 2) == "1.51",
                     "제안 페이지 조회가 기존 층 또는 미반영 재료 입력을 변경했습니다.");
        dialog.m_suggestions->SetItemState(0, wxLIST_STATE_SELECTED, wxLIST_STATE_SELECTED);
        wxListEvent suggestion(wxEVT_LIST_ITEM_SELECTED, dialog.m_suggestions->GetId());
        suggestion.SetIndex(0);
        suggestion.SetEventObject(dialog.m_suggestions);
        dialog.m_suggestions->GetEventHandler()->ProcessEvent(suggestion);
        ClickPcbButton(dialog.m_useSuggestion);
        CanvasAssert(dialog.m_materialDirty && dialog.m_materialSpecs.empty() &&
                         dialog.m_materialName->GetValue() == Display("페이지 조회 중 작성한 입력"),
                     "제안 채택이 미반영 재료 입력을 덮어썼습니다.");
        ClickPcbButton(PcbButton(dialog, "pcb.discard_material"));
        ClickPcbButton(dialog.m_useSuggestion);
        CanvasAssert(dialog.m_materialSpecs.size() == 1 &&
                         dialog.m_materialSpecs.at(0).at("properties").at("tan_delta").at("mode") == "missing" &&
                         dialog.m_materialSpecs.at(0).at("validity_hz").at("min").is_null() &&
                         dialog.m_materialSpecs.at(0).at("validity_hz").at("max").is_null() &&
                         dialog.m_materialSpecs.at(0).at("model") == "isotropic_constant_total_tan_delta",
                     "제안 사용이 미정 물성이나 적용 대역을 임의로 채웠거나 손실 모델을 누락했습니다.");
        const Json selected = dialog.m_materialSpecs;
        ClickPcbButton(dialog.m_useSuggestion);
        CanvasAssert(dialog.m_materialSpecs == selected, "제안 중복 채택이 기존 재료를 덮어썼습니다.");
        m_pcbChecks.push_back("stackup_suggestions_published_and_missing");
        m_pcbChecks.push_back("explicit_suggestion_use_preserves_missing_and_model");
        m_pcbChecks.push_back("suggestion_duplicate_does_not_overwrite");
        m_pcbChecks.push_back("search_controls_and_source_selection");
        m_pcbChecks.push_back("suggestion_page_preserves_dirty_input_and_layers");
        ClickPcbButton(dialog.m_suggestionPrevious);
        m_pcbStage = 13;
    }
    else if (m_pcbStage == 13 && !requestPending)
    {
        CanvasAssert(dialog.m_suggestionData.at("offset") == 0 && dialog.m_suggestions->GetItemCount() == 3 &&
                         dialog.m_materialSpecs.size() == 1 && dialog.m_layers->GetCellValue(1, 2) == "1.51" &&
                         dialog.ReadLayerRows().at(1).at("material_id") == dialog.m_materialSpecs.at(0).at("key"),
                     "이전 제안 페이지로 이동하며 채택한 재료 연결 또는 직접 입력 두께가 변경되었습니다.");
        m_pcbChecks.push_back("suggestion_previous_page_preserves_material_assignment");
        dialog.LoadSuggestionPage(2);
        m_pcbStage = 14;
    }
    else if (m_pcbStage == 14 && !requestPending)
    {
        CanvasAssert(dialog.m_suggestionData.at("offset") == 2 && dialog.m_suggestions->GetItemCount() == 1,
                     "제안의 마지막 동박 페이지만 조회하지 못했습니다.");
        dialog.LoadMaterial(0);
        CanvasAssert(dialog.m_properties[0].value->GetValue() == "4.5" && !dialog.m_properties[0].value->IsEnabled() &&
                         dialog.m_materialProposalDisplays.size() == 1 && !dialog.m_materialDirty,
                     "제안 페이지 이동 후 이미 채택한 재료의 공개값 표시가 사라졌습니다.");
        m_pcbChecks.push_back("accepted_suggestion_display_survives_page_change");
        ClickPcbButton(dialog.m_suggestionPrevious);
        m_pcbStage = 15;
    }
    else if (m_pcbStage == 15 && !requestPending)
    {
        CanvasAssert(dialog.m_suggestionData.at("offset") == 0 && dialog.m_materialSpecs.size() == 1,
                     "채택 재료를 보존한 채 이전 제안 페이지로 돌아오지 못했습니다.");
        m_pcbStage = 16;
    }
    else if (m_pcbStage == 16)
    {
        CanvasAssert(dialog.m_layers->GetNumberRows() == 3, "PCB 층 입력 표의 행 수가 다릅니다.");
        dialog.m_notebook->SetSelection(1);
        EditPcbCell(dialog.m_layers, 0, 4, "새 층");
        EditPcbCell(dialog.m_layers, 2, 4, m_pcbExistingLabel);
        for (int row = 0; row < 3; ++row)
        {
            EditPcbCell(dialog.m_layers, row, 2, row == 1 ? "1.524" : "0.035");
            EditPcbCell(dialog.m_layers, row, 3, "GUI 시험에서 명시한 가정 두께");
        }
        if (dialog.m_layoutReason->IsEnabled())
        {
            dialog.m_layoutReason->SetValue(Display("GUI 시험용 명시 구성. 기존 패턴의 위 동박 연결을 보존합니다."));
        }
        PcbSmokeMaterial(dialog);
        CanvasAssert(!dialog.m_applyButton->IsEnabled(), "검토 전 적용 버튼이 활성화되었습니다.");
        m_pcbChecks.push_back("layer_grid_input_and_explicit_mapping");
        m_pcbStage = 17;
        ClickPcbButton(dialog.m_previewButton);
    }
    else if ((m_pcbStage == 17 || m_pcbStage == 20) && !requestPending)
    {
        CanvasAssert(dialog.m_model.StageName() == "reviewed" && dialog.m_model.CanApply(),
                     "검토가 적용 가능 상태를 반환하지 않았습니다: " + Utf8(dialog.m_status->GetLabel()));
        const double expected = m_pcbStage == 17 ? 1.594 : 1.57;
        CanvasAssert(dialog.m_model.CandidateLayers().size() == 3 &&
                         std::abs(dialog.m_model.Preview().at("modeled_total_thickness_mm").get<double>() - expected) <
                             1e-9,
                     "서버 후보 적층과 표시 두께 합계가 입력과 다릅니다.");
        const auto& materials = dialog.m_model.Preview().at("candidate").at("materials");
        CanvasAssert(materials.size() == 1, "재료 입력 폼의 새 재료가 후보에 반영되지 않았습니다.");
        m_pcbExpectedMaterial = materials.at(0);
        const double dk = m_frame.m_options.catalog.empty() ? 4.2 : 4.5;
        CanvasAssert(std::abs(m_pcbExpectedMaterial.at("epsilon_r").at("value_si").get<double>() - dk) < 1e-12 &&
                         std::abs(m_pcbExpectedMaterial.at("tan_delta").at("value_si").get<double>() - 0.02) < 1e-12 &&
                         m_pcbExpectedMaterial.at("conductivity").at("value_si") == 0.0 &&
                         dialog.m_model.CandidateLayers().at(1).at("material_id") == m_pcbExpectedMaterial.at("id"),
                     "Dk/Df/전도도 폼 또는 유전체 재료 연결의 DTO 변환이 다릅니다.");
        if (!m_frame.m_options.catalog.empty())
        {
            CanvasAssert(m_pcbExpectedMaterial.at("model") == "isotropic_constant_total_tan_delta",
                         "제안 재료를 직접 수정한 뒤 손실 모델이 변경되었습니다.");
            m_pcbChecks.push_back("suggestion_model_preserved_after_manual_edit");
        }
        if (m_pcbStage == 17)
        {
            m_pcbChecks.push_back("material_layer_assignment_preview");
            m_pcbStage = 18;
            m_frame.Send("pcb.selection.context", Json::object(), false, m_frame.Context(),
                         [this](const Json& context)
                         {
                             CanvasAssert(context.at("revision_id") == m_pcbBeforeRevision &&
                                              context.at("layers").size() == 1,
                                          "미리보기가 원본 프로젝트를 변경했습니다.");
                             m_pcbChecks.push_back("preview_is_read_only");
                             m_pcbStage = 19;
                         });
        }
        else
        {
            m_pcbStage = 21;
            ClickPcbButton(dialog.m_applyButton);
            const bool closed = m_frame.Close(false);
            CanvasAssert(!closed && m_frame.m_pcbDialog == &dialog && dialog.m_applying && !dialog.m_closed &&
                             !m_frame.m_closeAfterPcb,
                         "적용 응답 대기 중 부모 닫기 요청이 veto되지 않았습니다.");
            m_pcbChecks.push_back("parent_close_veto_during_apply");
        }
    }
    else if (m_pcbStage == 19)
    {
        dialog.m_notebook->SetSelection(1);
        EditPcbCell(dialog.m_layers, 1, 2, "1.5");
        CanvasAssert(!dialog.m_applyButton->IsEnabled() && !dialog.m_model.CanApply(),
                     "입력 변경 후 이전 미리보기의 적용 승인이 유지되었습니다.");
        m_pcbChecks.push_back("preview_invalidated_on_input_change");
        m_pcbStage = 20;
        ClickPcbButton(dialog.m_previewButton);
    }
    else if (m_pcbStage == 37)
    {
        m_pcbStage = 34;
        ClickPcbButton(dialog.m_cancelButton);
    }
}

void StudioSmokeDriver::PcbSmokeMaterial(PcbSelectionDialog& dialog)
{
    dialog.m_notebook->SetSelection(2);
    const bool catalog = !m_frame.m_options.catalog.empty();
    if (catalog)
    {
        dialog.LoadMaterial(0);
    }
    else
    {
        ClickPcbButton(PcbButton(dialog, "pcb.new_material"));
    }
    dialog.m_materialName->SetValue(Display("GUI 검증 유전체"));
    ChoosePcbValue(dialog.m_properties[0].mode, catalog ? 1 : 2);
    if (catalog)
    {
        ClickPcbButton(PcbButton(dialog, "pcb.epsilon_r.attach"));
        CanvasAssert(dialog.m_properties[0].recordId == "PCB056952",
                     "검색에서 고른 Dk 관측이 재료 폼에 연결되지 않았습니다.");
        CanvasAssert(dialog.m_properties[1].recordId == "PCB056952" && dialog.m_properties[1].mode->GetSelection() == 0,
                     "적층의 Df 미제공 기록이 없어지거나 Dk 관측 선택이 미정 상태를 바꿨습니다.");
    }
    else
    {
        dialog.m_properties[0].value->SetValue("4.2");
    }
    dialog.m_properties[0].reason->SetValue(
        Display(catalog ? "GUI 시험: 10 MHz Dk 관측을 명시 선택함. GHz 보증값으로 사용하지 않음."
                        : "GUI 시험에서 직접 지정한 Dk 가정"));
    ChoosePcbValue(dialog.m_properties[1].mode, 2);
    dialog.m_properties[1].value->SetValue("0.02");
    dialog.m_properties[1].reason->SetValue(Display("GUI 시험의 Df 직접 가정이며 Dk 원문의 Df로 취급하지 않음"));
    ChoosePcbValue(dialog.m_properties[2].mode, 1);
    dialog.m_properties[2].value->SetValue("0");
    dialog.m_properties[2].reason->SetValue(Display("GUI 시험: 코어의 추가 도전 손실을 0으로 가정"));
    dialog.m_bandReason->SetValue(Display("적용 대역은 미정이며 제조사 보증 대역을 만들지 않음"));
    ClickPcbButton(PcbButton(dialog, "pcb.save_material"));
    CanvasAssert(dialog.m_materialSpecs.size() == 1 && !dialog.m_materialDirty && dialog.m_materials->GetCount() == 1,
                 "재료 입력 반영 버튼이 폼을 새 재료로 저장하지 못했습니다.");
    const std::string key = dialog.m_materialSpecs.at(0).at("key");
    const auto found = std::find(dialog.m_materialValues.begin(), dialog.m_materialValues.end(), key);
    CanvasAssert(found != dialog.m_materialValues.end(), "재료 연결 choice에 새 재료가 없습니다.");
    dialog.m_notebook->SetSelection(1);
    EditPcbCell(dialog.m_layers, 1, 5,
                dialog.m_materialLabels.at(static_cast<std::size_t>(found - dialog.m_materialValues.begin())));
    m_pcbChecks.push_back(catalog ? "material_form_catalog_dk_user_df_conductivity" : "material_form_direct_values");
}

void StudioSmokeDriver::PcbSmokeHistory()
{
    if (m_pcbStage == 7)
    {
        if (m_frame.m_requests.Size() != 0)
        {
            return;
        }
        m_pcbChecks.push_back("close_during_request_and_reopen");
        m_pcbStage = 8;
        m_frame.CallAfter(
            [this]()
            {
                m_frame.OpenPcbSelection();
            });
    }
    else if (m_pcbStage == 21)
    {
        CanvasAssert(m_frame.m_scene.at("board") == m_pcbOriginalBoard &&
                         CanvasShape(m_pcbPattern) == m_pcbOriginalPattern,
                     "PCB 적용이 원형 외곽이나 기존 패턴 참조를 변경했습니다.");
        CanvasAssert(m_frame.m_scene.at("layers").size() == 3 &&
                         m_frame.m_editor.at("history").at("undo_count").get<int>() == m_pcbUndoBefore + 1,
                     "PCB 적용이 세 층과 단일 undo 명령으로 반영되지 않았습니다.");
        m_pcbAppliedLayers = m_frame.m_scene.at("layers");
        m_pcbChecks.push_back("single_apply_preserves_outline_and_pattern");
        m_pcbStage = 22;
        m_frame.History("project.undo");
    }
    else if (m_pcbStage == 22)
    {
        CanvasAssert(m_frame.m_scene.at("layers") == m_pcbOriginalLayers &&
                         m_frame.m_scene.at("board") == m_pcbOriginalBoard &&
                         CanvasShape(m_pcbPattern) == m_pcbOriginalPattern &&
                         m_frame.m_editor.at("history").at("undo_count").get<int>() == m_pcbUndoBefore,
                     "한 번의 undo가 기존 층과 패턴을 복원하지 못했습니다.");
        m_pcbStage = 23;
        m_frame.History("project.redo");
    }
    else if (m_pcbStage == 23)
    {
        CanvasAssert(m_frame.m_scene.at("layers") == m_pcbAppliedLayers &&
                         m_frame.m_scene.at("board") == m_pcbOriginalBoard &&
                         CanvasShape(m_pcbPattern) == m_pcbOriginalPattern,
                     "redo가 PCB 선택의 동일한 층 ID와 패턴을 복원하지 못했습니다.");
        m_pcbChecks.push_back("single_step_undo_redo");
        m_pcbStage = 31;
        m_frame.SaveProject();
    }
    else if (m_pcbStage == 32)
    {
        m_pcbStage = 33;
        m_frame.CallAfter(
            [this]()
            {
                m_frame.OpenPcbSelection();
            });
    }
    else if (m_pcbStage == 34)
    {
        m_pcbStage = 40;
        m_frame.CallAfter(
            [this]()
            {
                m_frame.OpenPcbSelection();
            });
    }
}

void StudioSmokeDriver::OnPcbShutdownComplete()
{
    if (!m_frame.m_options.pcbSmoke || m_frame.m_finishing)
    {
        return;
    }
    try
    {
        CanvasAssert(m_pcbStage == 41 && m_frame.m_pcbDialog == nullptr && m_frame.m_closing &&
                         !m_frame.m_shutdown.joinable() && !m_frame.m_timer.IsRunning(),
                     "조회 중 부모 종료가 모달 반환과 서비스 회수를 끝내지 못했습니다.");
        m_pcbChecks.push_back("parent_close_during_lookup_safe_shutdown");
        m_pcbStage = 35;
        FinishSmoke(true, "");
    }
    catch (const std::exception& error)
    {
        FinishSmoke(false, error.what());
    }
}
