/** @file @brief 실행 환경과 명시적 통합 시험 옵션을 보관한다. */
#pragma once
#include <wx/string.h>

/** @brief 도메인 설정과 분리한 GUI 실행 옵션이다. */
struct Options
{
    wxString python;
    wxString source;
    wxString workspace;
    wxString cadPython;
    wxString catalog;
    wxString openProject;
    wxString smokeReport;
    bool smoke = false;
    bool editorSmoke = false;
    bool pcbSmoke = false;
    bool canvasSmoke = false;
    bool primitivesSmoke = false;
    bool coordinatesSmoke = false;
    bool cadSmoke = false;
    bool cadExpectFailure = false;
    bool openEmsWsl = false;
    bool solverSmoke = false;
    bool solverExpectFailure = false;
    wxString solverSettings;
    bool studySmoke = false;
    bool studyExpectFailure = false;
    bool setupSmoke = false;
    wxString studySpecification;
};
