/** @file @brief 실행 옵션을 읽고 주 창을 생성하는 진입점이다. */
#include "studio_frame.h"
#include "studio_support.h"
#include <wx/app.h>
#include <wx/cmdline.h>
#include <wx/filename.h>
#include <wx/msgdlg.h>

/** @brief 명시한 실행 경로로 wxWidgets GUI를 초기화한다. */
class StudioApp final : public wxApp
{
public:
    bool OnInit() override
    {
        wxCmdLineParser parser(argc, argv);
        parser.AddOption("", "python", "Python executable path");
        parser.AddOption("", "source", "rfad source directory");
        parser.AddOption("", "workspace", "Project workspace directory");
        parser.AddOption("", "cad-python", "Isolated CAD Python executable path");
        parser.AddOption("", "catalog", "Read-only PCB catalog SQLite path");
        parser.AddSwitch("", "openems-wsl", "Enable fixed WSL openEMS runtime");
        parser.AddSwitch("", "solver-smoke-test", "Run PCB solver GUI workflow and exit");
        parser.AddSwitch("", "solver-expect-failure", "Verify missing PCB physics inputs are rejected");
        parser.AddOption("", "solver-settings", "Explicit solver smoke settings JSON path");
        parser.AddSwitch("", "study-smoke-test", "Run project study GUI workflow and exit");
        parser.AddSwitch("", "study-expect-failure", "Expect study source preflight rejection");
        parser.AddSwitch("", "design-setup-smoke-test", "Run target/template GUI workflow and exit");
        parser.AddSwitch("", "printed-seed-smoke-test", "Run printed reference/seed and workspace GUI workflow and exit");
        parser.AddOption("", "study-specification", "Explicit study smoke specification JSON path");
        parser.AddOption("", "open-project", "Registered project path relative to workspace");
        parser.AddSwitch("", "smoke-test", "Run GUI/service smoke test and exit");
        parser.AddSwitch("", "editor-smoke-test", "Run editor/undo/restart smoke test and exit");
        parser.AddSwitch("", "pcb-selection-smoke-test", "Run PCB catalog selection and preview workflow and exit");
        parser.AddSwitch("", "canvas-smoke-test", "Run 2D mouse/command/history/restart smoke test and exit");
        parser.AddSwitch("", "primitives-smoke-test",
                         "Run polygon/pad/via input/display/history/restart smoke test and exit");
        parser.AddSwitch("", "coordinate-table-smoke-test",
                         "Run 64-point coordinate table edit/history/restart smoke test and exit");
        parser.AddSwitch("", "cad-smoke-test", "Run CAD export/view/cancel/restart smoke test and exit");
        parser.AddSwitch("", "cad-expect-failure", "Verify invalid CAD input without publishing output");
        parser.AddOption("", "smoke-report", "Smoke JSON output path");
        parser.AddSwitch("h", "help", "Show help", wxCMD_LINE_OPTION_HELP);
        if (parser.Parse() != 0)
        {
            return false;
        }
        Options options;
        parser.Found("python", &options.python);
        parser.Found("source", &options.source);
        parser.Found("workspace", &options.workspace);
        parser.Found("cad-python", &options.cadPython);
        parser.Found("catalog", &options.catalog);
        parser.Found("open-project", &options.openProject);
        parser.Found("smoke-report", &options.smokeReport);
        options.editorSmoke = parser.Found("editor-smoke-test");
        options.pcbSmoke = parser.Found("pcb-selection-smoke-test");
        options.canvasSmoke = parser.Found("canvas-smoke-test");
        options.coordinatesSmoke = parser.Found("coordinate-table-smoke-test");
        options.primitivesSmoke = parser.Found("primitives-smoke-test") || options.coordinatesSmoke;
        options.cadSmoke = parser.Found("cad-smoke-test");
        options.cadExpectFailure = parser.Found("cad-expect-failure");
        options.openEmsWsl = parser.Found("openems-wsl");
        options.solverSmoke = parser.Found("solver-smoke-test");
        options.solverExpectFailure = parser.Found("solver-expect-failure");
        parser.Found("solver-settings", &options.solverSettings);
        options.studySmoke = parser.Found("study-smoke-test");
        options.studyExpectFailure = parser.Found("study-expect-failure");
        options.printedSeedSmoke = parser.Found("printed-seed-smoke-test");
        options.setupSmoke = parser.Found("design-setup-smoke-test") || options.printedSeedSmoke;
        parser.Found("study-specification", &options.studySpecification);
        options.smoke = parser.Found("smoke-test") || options.editorSmoke || options.canvasSmoke ||
                        options.primitivesSmoke || options.cadSmoke || options.solverSmoke || options.pcbSmoke ||
                        options.studySmoke || options.setupSmoke;
        if (options.python.empty() || options.source.empty() || options.workspace.empty())
        {
            wxMessageBox(Display("--python, --source, --workspace 경로를 지정하십시오."), Display("실행 설정"),
                         wxOK | wxICON_ERROR);
            ExitCode = 2;
            return false;
        }
        if (!wxFileName(options.python).IsAbsolute() || !wxFileName(options.source).IsAbsolute() ||
            !wxFileName(options.workspace).IsAbsolute() ||
            (!options.cadPython.empty() && !wxFileName(options.cadPython).IsAbsolute()) ||
            (!options.catalog.empty() && !wxFileName(options.catalog).IsAbsolute()))
        {
            wxMessageBox(Display("실행 경로는 절대 경로로 지정하십시오."), Display("실행 설정"), wxOK | wxICON_ERROR);
            ExitCode = 2;
            return false;
        }
        auto* frame = new StudioFrame(std::move(options));
        SetTopWindow(frame);
        frame->Show();
        return true;
    }

    int OnRun() override
    {
        wxApp::OnRun();
        return ExitCode;
    }
};

wxIMPLEMENT_APP(StudioApp);
