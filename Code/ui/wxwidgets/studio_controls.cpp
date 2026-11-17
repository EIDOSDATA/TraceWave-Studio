/** @file @brief 주 창의 controls 책임을 구현한다. */
#include "studio_internal.h"
#include "editor_sync.h"
#include "output_controller.h"
#include <wx/srchctrl.h>

void StudioFrame::UpdateControls()
{
    const bool ready = m_connected && !m_busy && m_pcbDialog == nullptr && m_setupDialog == nullptr;
    const bool hasProject = !m_project.empty();
    const bool opened = ready && Studio::EditableProject(m_editor, m_scene, m_project, m_revision);
    const bool cadRunning = m_cadPreparing || !m_cadTask.Id().empty();
    const bool outputRunning = m_output && m_output->Active();
    const bool canSwitch = ready && m_studyDialog == nullptr && !cadRunning && !outputRunning &&
                           !m_solverWorkflow.Active() && !m_solverRestoring && !m_cadRestoring &&
                           !m_modelView->IsLoading();
    GetMenuBar()->Enable(IdCreate, canSwitch);
    GetMenuBar()->Enable(IdOpen, canSwitch);
    GetMenuBar()->Enable(IdSave, opened);
    GetMenuBar()->Enable(IdSnapshot, opened);
    GetMenuBar()->Enable(IdRefresh, hasProject && canSwitch);
    GetMenuBar()->Enable(IdNewParameter, opened);
    GetMenuBar()->Enable(IdPcbSelection, opened && m_pcbSelectionSupported);
    GetMenuBar()->Enable(IdProjectStudy, opened && m_studySupported);
    GetMenuBar()->Enable(IdTargets, opened && m_targetsSupported);
    GetMenuBar()->Enable(IdTemplates, opened && m_templatesSupported);
    GetMenuBar()->Enable(IdDesignRules, opened && m_designRulesSupported);
    GetMenuBar()->Enable(IdPhysicalSetup, opened && m_physicalSetupSupported);
    for (const int id : {IdNewMaterial, IdNewNet, IdNewPort})
    {
        GetMenuBar()->Enable(id, opened);
    }
    const Json history = m_editor.value("history", Json::object());
    GetMenuBar()->Enable(IdUndo, opened && history.value("can_undo", false));
    GetMenuBar()->Enable(IdRedo, opened && history.value("can_redo", false));
    m_tree->Enable(opened);
    m_objectSearch->Enable(opened);
    m_objectFilter->Enable(opened);
    m_name->Enable(opened);
    m_description->Enable(opened);
    m_editorPanel->Enable(opened);
    const bool board = m_scene.contains("board") && !m_scene.at("board").is_null();
    const bool synchronized = Studio::EditableProject(m_editor, m_scene, m_project, m_revision);
    const bool drawing = opened && synchronized && board && !m_activeLayer.empty();
    for (const int id : {IdPolygon, IdCirclePad, IdRectanglePad, IdVia})
    {
        GetMenuBar()->Enable(id, drawing);
    }
    for (const auto& item : m_tools)
    {
        bool enabled = opened;
        if (item.first == IdCreate || item.first == IdOpen)
        {
            enabled = canSwitch;
        }
        else if (item.first == IdUndo || item.first == IdRedo)
        {
            enabled = opened && history.value(item.first == IdUndo ? "can_undo" : "can_redo", false);
        }
        else if (item.first == IdBoard || item.first == IdCircularBoard)
        {
            enabled = opened && !board;
        }
        else if (item.first == IdLayer || item.first == IdDielectric)
        {
            enabled = opened && board;
        }
        else if (item.first == IdPcbSelection)
        {
            enabled = opened && m_pcbSelectionSupported;
        }
        else if (item.first == IdTargets || item.first == IdTemplates)
        {
            enabled = opened && (item.first == IdTargets ? m_targetsSupported : m_templatesSupported);
        }
        else if (item.first == IdPhysicalSetup)
        {
            enabled = opened && m_physicalSetupSupported;
        }
        else if (item.first == IdDesignRules)
        {
            enabled = opened && m_designRulesSupported;
        }
        else if (item.first == IdLine || item.first == IdArc || item.first == IdCoordinates)
        {
            enabled = drawing;
        }
        else if (item.first == IdDeleteShape)
        {
            enabled = opened && m_selection.value("kind", "") == "geometry";
        }
        else if (item.first == IdPrecision)
        {
            enabled = opened && synchronized && m_precisionSupported;
        }
        else if (item.first == IdExportStep || item.first == IdBuild3D)
        {
            enabled = opened && m_cadConfigured && !cadRunning && !outputRunning && !m_cadRestoring &&
                      !m_modelView->IsLoading();
        }
        else if (item.first == IdCancelCad)
        {
            enabled = m_connected && cadRunning && !m_cadCancelRequested;
        }
        else if (item.first == IdOutputFolder)
        {
            enabled = !m_cadResult.empty() && m_cadResult.value("projection_purpose", "") != "geometry";
        }
        else if (item.first == IdRunSolver)
        {
            enabled = opened && m_solverConfigured && !m_solverWorkflow.Active() && !m_solverRestoring;
        }
        else if (item.first == IdCancelSolver)
        {
            enabled = m_connected && m_solverWorkflow.CanRequestCancel();
        }
        else if (item.first == IdRadiation)
        {
            enabled =
                opened && !m_solverSamples.empty() && m_solverSamples.at("metadata").contains("radiation_summary");
        }
        else if (item.first == IdProjectStudy)
        {
            enabled = opened && m_studySupported;
        }
        else if (item.first == IdFit3D || item.first == IdTop3D || item.first == IdIso3D)
        {
            enabled = m_modelView->HasMesh();
        }
        item.second->Enable(enabled);
    }
    for (const int id :
         {IdBoard, IdCircularBoard, IdLayer, IdDielectric, IdCoordinates, IdDeleteShape, IdValidate, IdExportStep,
          IdBuild3D, IdCancelCad, IdOutputFolder, IdRunSolver, IdCancelSolver, IdRadiation})
    {
        GetMenuBar()->Enable(id, m_tools.at(id)->IsEnabled());
    }
    m_steps->Enable(opened);
    GetMenuBar()->Enable(IdPrecision, opened && synchronized && m_precisionSupported);
    m_recordRadiation->Enable(opened && m_solverConfigured && !m_solverWorkflow.Active() && !m_solverRestoring);
    m_layerChoice->Enable(drawing);
    m_width->Enable(drawing);
    m_snapCheck->Enable(opened && synchronized);
    m_canvas->SetEditingEnabled(opened && synchronized);
    if (hasProject && !synchronized)
    {
        m_canvasHint->SetLabel(
            Display("편집 원본과 화면이 일치하지 않아 편집을 잠갔습니다. F5로 최신 프로젝트를 다시 읽으세요."));
    }
    else if (synchronized && m_canvasHint->GetLabel().StartsWith(Display("편집 원본과 화면이")))
    {
        m_canvasHint->SetLabel(Display(m_activeLayer.empty()
                                           ? "도체층을 추가한 뒤 선 또는 원호 도구를 선택하세요."
                                           : "선택: 객체 속성 / 휠: 확대·축소 / 가운데 버튼: 이동 / Esc: 취소"));
    }
    UpdateDraftState();
    UpdateModelState();
    UpdateWorkspace();
}

/** @brief 미적용 입력과 적용 후 저장 필요 상태를 서비스 개정 정보로 구분한다. */
void StudioFrame::UpdateDraftState()
{
    if (m_refreshing || m_updatingDraft)
    {
        return;
    }
    m_updatingDraft = true;
    try
    {
        const bool hasProject = !m_project.empty();
        const bool opened = Studio::EditableProject(m_editor, m_scene, m_project, m_revision);
        const bool draft = opened && HasDraft();
        bool canApply = draft;
        if (opened && m_selection.value("kind", "project") == "new_parameter")
        {
            wxString name = Display(m_editorPanel->FieldValue("name").get<std::string>());
            name.Trim(true).Trim(false);
            canApply = canApply && !name.empty();
        }
        m_apply->Enable(m_connected && !m_busy && canApply);
        if (hasProject && !opened)
        {
            m_editState = "stale";
            SetTitle(Display("TraceWave Studio - 편집 상태 재조회 필요"));
            m_revisionLabel->SetLabel(Display("편집 잠금 / F5로 다시 읽기"));
            m_revisionLabel->SetToolTip(
                Display("현재 프로젝트와 같은 개정의 속성/2D 조회가 모두 완료되어야 편집할 수 있습니다."));
            SetStatusText(Display("표시 동기화 필요"), 1);
        }
        else if (!opened)
        {
            m_editState = "empty";
            SetTitle(Display("TraceWave Studio"));
            m_revisionLabel->SetLabel(Display("프로젝트를 만들거나 열어 시작하세요."));
            m_revisionLabel->UnsetToolTip();
            SetStatusText(Display("프로젝트 없음"), 1);
        }
        else
        {
            const bool saved = m_editor.at("saved_revision") == m_revision;
            m_editState = draft ? "draft" : (saved ? "saved" : "applied");
            const std::string status = draft ? "미적용 입력" : (saved ? "저장됨" : "적용됨 (저장 필요)");
            const std::string name = m_editor.at("metadata").at("name").get<std::string>();
            SetTitle(Display(name + " - " + status + " - TraceWave Studio"));
            m_revisionLabel->SetLabel(Display(status));
            m_revisionLabel->SetToolTip(Display("프로젝트 식별자: " + m_project + "\n설계 버전: " + m_revision +
                                                "\n저장 버전: " + m_editor.at("saved_revision").get<std::string>()));
            SetStatusText(Display(status), 1);
        }
    }
    catch (const std::exception&)
    {
        m_apply->Disable();
    }
    m_updatingDraft = false;
}

/** @brief 적용 전 입력이 선택 변경이나 종료로 조용히 사라지지 않도록 한다. */
bool StudioFrame::HasDraft() const
{
    if (!Studio::EditableProject(m_editor, m_scene, m_project, m_revision))
    {
        return false;
    }
    if (m_selection.value("kind", "project") == "project")
    {
        return Utf8(m_name->GetValue()) != m_editor.at("metadata").at("name") ||
               Utf8(m_description->GetValue()) != m_editor.at("metadata").at("description");
    }
    return m_editorPanel->IsDirty();
}

bool StudioFrame::ConfirmDiscard()
{
    if (!HasDraft())
    {
        return true;
    }
    return wxMessageBox(Display("아직 적용하지 않은 입력을 버리고 계속하시겠습니까?"), Display("입력 변경 확인"),
                        wxYES_NO | wxNO_DEFAULT | wxICON_QUESTION, this) == wxYES;
}
