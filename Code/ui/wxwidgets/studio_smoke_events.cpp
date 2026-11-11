/** @file @brief 제품 이벤트를 실제 GUI 통합 시험의 다음 단계로 연결한다. */
#include "studio_internal.h"

void StudioSmokeDriver::OnConnected()
{
    ++m_serviceSessions;
    if (!m_frame.m_options.smoke)
    {
        return;
    }
    if (m_frame.m_options.pcbSmoke)
    {
        m_smokePath = "projects/pcb-" + Uuid();
        m_frame.OpenProject("create", m_smokePath, "GUI PCB 선택 검증");
    }
    else if (m_frame.m_options.cadSmoke || !m_frame.m_options.openProject.empty())
    {
        m_frame.OpenProject("open", Utf8(m_frame.m_options.openProject));
    }
    else if (m_frame.m_options.primitivesSmoke)
    {
        if (m_primitivesStage == 21 || m_primitivesStage == 106)
        {
            m_frame.OpenProject("open", m_smokePath);
        }
        else
        {
            m_smokePath = "projects/primitives-" + Uuid();
            m_frame.OpenProject("create", m_smokePath, "GUI 면 패드 비아 검증");
        }
    }
    else if (m_frame.m_options.canvasSmoke)
    {
        if (m_canvasStage == 14)
        {
            m_frame.OpenProject("open", m_smokePath);
        }
        else
        {
            m_smokePath = "projects/canvas-" + Uuid();
            m_frame.OpenProject("create", m_smokePath, "GUI 2D 선 원호 검증");
        }
    }
    else if (m_frame.m_options.editorSmoke)
    {
        if (m_editorStage == 10)
        {
            m_frame.OpenProject("open", m_smokePath);
        }
        else
        {
            m_smokePath = "projects/editor-" + Uuid();
            m_frame.OpenProject("create", m_smokePath, "GUI 설계 편집 검증");
        }
    }
    else if (m_frame.m_options.smoke)
    {
        if (m_smokeStage == 4)
        {
            m_frame.OpenProject("open", m_smokePath);
        }
        else
        {
            m_smokePath = "projects/gui-" + Uuid();
            m_frame.OpenProject("create", m_smokePath, "GUI 초기 프로젝트");
        }
    }
}

void StudioSmokeDriver::OnOpened()
{
    if (m_frame.m_options.studySmoke)
    {
        if (m_studyStage == 0)
        {
            m_studyStage = 1;
        }
    }
    else if (m_frame.m_options.pcbSmoke)
    {
        if (m_pcbStage == 0)
        {
            m_pcbStage = 1;
            m_pcbStarted = Clock::now();
        }
    }
    else if (m_frame.m_options.solverSmoke)
    {
        if (m_solverSmokeStage == 0)
        {
            m_solverSmokeStage = 1;
        }
    }
    else if (m_frame.m_options.cadSmoke)
    {
        if (m_cadSmokeStage == 0)
        {
            m_cadSmokeStage = 1;
        }
    }
    else if (m_frame.m_options.primitivesSmoke)
    {
        if (m_primitivesStage == 0)
        {
            m_primitivesStage = 1;
        }
    }
    else if (m_frame.m_options.canvasSmoke)
    {
        CanvasSmokeNext();
    }
    else if (m_frame.m_options.editorSmoke)
    {
        EditorSmokeNext();
    }
    else if (m_frame.m_options.smoke && m_smokeStage == 0)
    {
        m_smokeStage = 1;
        m_frame.m_name->SetValue(Display("GUI 변경된 프로젝트"));
        m_frame.m_description->SetValue(Display("한글 설명 및 공백 경로 검증"));
        m_frame.ApplyProperties();
    }
    else if (m_frame.m_options.smoke && m_smokeStage == 4)
    {
        if (m_frame.m_editor.at("metadata").at("name") != "GUI 변경된 프로젝트" ||
            m_frame.m_editor.at("metadata").at("description") != "한글 설명 및 공백 경로 검증" ||
            m_frame.m_editor.at("saved_revision") != m_frame.m_revision ||
            m_frame.m_savedRevision != m_frame.m_revision)
        {
            FinishSmoke(false, "Reopened values do not match saved revision.");
            return;
        }
        m_smokeStage = 5;
        FinishSmoke(true, "");
    }
}

void StudioSmokeDriver::OnSaved()
{
    if (m_frame.m_options.pcbSmoke && m_pcbStage == 31)
    {
        m_pcbStage = 32;
    }
    else if (m_frame.m_options.canvasSmoke && m_canvasStage == 12)
    {
        m_canvasStage = 13;
        m_frame.Snapshot();
    }
    else if (m_frame.m_options.editorSmoke && m_editorStage == 8)
    {
        CheckUxState("saved", false);
        m_uxChecks.push_back("saved_after_apply");
        m_editorStage = 9;
        m_frame.Snapshot();
    }
    else if (m_frame.m_options.smoke && m_smokeStage == 2)
    {
        m_smokeStage = 3;
        m_frame.Snapshot();
    }
}

void StudioSmokeDriver::OnSnapshotCreated()
{
    if (m_frame.m_options.canvasSmoke && m_canvasStage == 13)
    {
        m_canvasStage = 14;
        m_frame.m_connected = false;
        m_frame.m_transportFailed = false;
        m_frame.m_restarting = true;
        m_frame.BeginShutdown();
    }
    else if (m_frame.m_options.editorSmoke && m_editorStage == 9)
    {
        m_editorStage = 10;
        m_frame.m_connected = false;
        m_frame.m_transportFailed = false;
        m_frame.m_restarting = true;
        m_frame.BeginShutdown();
    }
    else if (m_frame.m_options.smoke && m_smokeStage == 3)
    {
        m_smokeStage = 4;
        m_frame.m_connected = false;
        m_frame.m_transportFailed = false;
        m_frame.m_restarting = true;
        m_frame.BeginShutdown();
    }
}

void StudioSmokeDriver::OnApplied()
{
    if (m_frame.m_options.smoke && !m_frame.m_options.editorSmoke && m_smokeStage == 1)
    {
        m_smokeStage = 2;
        m_frame.SaveProject();
    }
}

void StudioSmokeDriver::OnSelected()
{
    if (m_canvasAwaitSelection)
    {
        m_canvasAwaitSelection = false;
        CanvasSmokeNext();
    }
}
