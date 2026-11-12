/** @file @brief 주 창의 controls 책임을 구현한다. */
#include "studio_internal.h"

void StudioFrame::UpdateControls()
{
    const bool ready = m_connected && !m_busy && m_pcbDialog == nullptr && m_setupDialog == nullptr;
    const bool opened = ready && !m_project.empty();
    const bool cadRunning = m_cadPreparing || !m_cadTask.Id().empty();
    const bool canSwitch = ready && m_studyDialog == nullptr && !cadRunning && !m_solverWorkflow.Active() &&
                           !m_solverRestoring && !m_cadRestoring && !m_modelView->IsLoading();
    GetMenuBar()->Enable(IdCreate, canSwitch);
    GetMenuBar()->Enable(IdOpen, canSwitch);
    GetMenuBar()->Enable(IdSave, opened);
    GetMenuBar()->Enable(IdSnapshot, opened);
    GetMenuBar()->Enable(IdRefresh, opened && canSwitch);
    GetMenuBar()->Enable(IdNewParameter, opened);
    GetMenuBar()->Enable(IdPcbSelection, opened && m_pcbSelectionSupported);
    GetMenuBar()->Enable(IdProjectStudy, opened && m_studySupported);
    GetMenuBar()->Enable(IdTargets, opened && m_targetsSupported);
    GetMenuBar()->Enable(IdTemplates, opened && m_templatesSupported);
    for (const int id : {IdNewMaterial, IdNewNet, IdNewPort})
    {
        GetMenuBar()->Enable(id, opened);
    }
    const Json history = m_editor.value("history", Json::object());
    GetMenuBar()->Enable(IdUndo, opened && history.value("can_undo", false));
    GetMenuBar()->Enable(IdRedo, opened && history.value("can_redo", false));
    m_tree->Enable(opened);
    m_name->Enable(opened);
    m_description->Enable(opened);
    m_editorPanel->Enable(opened);
    const bool board = m_scene.contains("board") && !m_scene.at("board").is_null();
    const bool synchronized = m_scene.value("revision_id", "") == m_revision;
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
        else if (item.first == IdLine || item.first == IdArc || item.first == IdCoordinates)
        {
            enabled = drawing;
        }
        else if (item.first == IdDeleteShape)
        {
            enabled = opened && m_selection.value("kind", "") == "geometry";
        }
        else if (item.first == IdExportStep || item.first == IdBuild3D)
        {
            enabled = opened && m_cadConfigured && !cadRunning && !m_cadRestoring && !m_modelView->IsLoading();
        }
        else if (item.first == IdCancelCad)
        {
            enabled = m_connected && cadRunning && !m_cadCancelRequested;
        }
        else if (item.first == IdOutputFolder)
        {
            enabled = !m_cadResult.empty();
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
    m_recordRadiation->Enable(opened && m_solverConfigured && !m_solverWorkflow.Active() && !m_solverRestoring);
    m_layerChoice->Enable(drawing);
    m_width->Enable(drawing);
    m_canvas->SetEditingEnabled(opened && synchronized);
    if (opened && !synchronized)
    {
        m_canvasHint->SetLabel(Display("이전 설계의 표시입니다. F5로 최신 상태를 다시 읽으세요."));
    }
    UpdateDraftState();
    UpdateModelState();
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
        const bool opened = !m_project.empty() && !m_editor.empty();
        const bool draft = opened && HasDraft();
        bool canApply = draft;
        if (opened && m_selection.value("kind", "project") == "new_parameter")
        {
            wxString name = Display(m_editorPanel->FieldValue("name").get<std::string>());
            name.Trim(true).Trim(false);
            canApply = canApply && !name.empty();
        }
        m_apply->Enable(m_connected && !m_busy && canApply);
        if (!opened)
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
    if (m_editor.empty())
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
