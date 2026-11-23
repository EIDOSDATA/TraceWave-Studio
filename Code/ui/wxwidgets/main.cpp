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
        parser.AddOption("", "exchange-python", "Isolated drawing and exchange Python executable path");
        parser.AddOption("", "catalog", "Read-only PCB catalog SQLite path");
        parser.AddSwitch("", "openems-wsl", "Enable fixed WSL openEMS runtime");
        parser.AddSwitch("", "solver-smoke-test", "Run PCB solver GUI workflow and exit");
        parser.AddSwitch("", "solver-active-cancel-smoke-test", "Cancel the second PCB analysis after it starts");
        parser.AddSwitch("", "solver-expect-failure", "Verify missing PCB physics inputs are rejected");
        parser.AddOption("", "solver-settings", "Explicit solver smoke settings JSON path");
        parser.AddSwitch("", "study-smoke-test", "Run project study GUI workflow and exit");
        parser.AddSwitch("", "study-expect-failure", "Expect study source preflight rejection");
        parser.AddSwitch("", "design-setup-smoke-test", "Run target/template GUI workflow and exit");
        parser.AddSwitch("", "network-modal-smoke-test", "Run named mode import and modal plane shift through Windows controls");
        parser.AddSwitch("", "network-smoke-test", "Run network import, RLC, assessment and restart GUI workflow");
        parser.AddSwitch("", "sweep-smoke-test", "Run finite study create, cancel, resume and reopen GUI workflow");
        parser.AddSwitch("", "results-smoke-test", "Run pinned results, Smith and source comparison GUI workflow");
        parser.AddSwitch("", "validation-smoke-test", "Run immutable RF validation reports GUI workflow");
        parser.AddSwitch("", "selection-smoke-test", "Run candidate editing-copy review and preservation workflow");
        parser.AddSwitch("", "output-smoke-test", "Run frozen-input drawing output and fresh verification workflow");
        parser.AddSwitch("", "features-smoke-test", "Run PCB mechanical and artwork edit preservation workflow");
        parser.AddSwitch("", "pcb-exchange-smoke-test", "Run PCB CAM export and preserved source import workflow");
        parser.AddSwitch("", "printed-seed-smoke-test",
                         "Run printed reference/seed and workspace GUI workflow and exit");
        parser.AddSwitch("", "physical-setup-smoke-test", "Run physical stack, STEP placement and reopen workflow");
        parser.AddSwitch("", "installation-smoke-test", "Run native PCB installation comparison and reopen");
        parser.AddSwitch("", "design-rules-smoke-test", "Run design rules editing, checking and reopen workflow");
        parser.AddSwitch("", "precision-editor-smoke-test", "Run rename, precision preview/apply and restart workflow");
        parser.AddSwitch("", "precision-planar-smoke-test",
                         "Run planar selection, candidates, mirror and restart workflow");
        parser.AddOption("", "study-specification", "Explicit study smoke specification JSON path");
        parser.AddOption("", "open-project", "Registered project path relative to workspace");
        parser.AddSwitch("", "smoke-test", "Run GUI/service smoke test and exit");
        parser.AddSwitch("", "editor-smoke-test", "Run editor/undo/restart smoke test and exit");
        parser.AddSwitch("", "project-switch-smoke-test", "Observe repeated project switching in the running Studio");
        parser.AddSwitch("", "large-results-smoke-test", "Verify registered large result files with the Windows interface");
        parser.AddSwitch("", "catalog-table-smoke-test", "Verify the large catalog table after reopening a saved project");
        parser.AddSwitch("", "pcb-selection-smoke-test", "Run PCB catalog selection and preview workflow and exit");
        parser.AddSwitch("", "canvas-smoke-test", "Run 2D mouse/command/history/restart smoke test and exit");
        parser.AddSwitch("", "primitives-smoke-test",
                         "Run polygon/pad/via input/display/history/restart smoke test and exit");
        parser.AddSwitch("", "coordinate-table-smoke-test",
                         "Run 64-point coordinate table edit/history/restart smoke test and exit");
        parser.AddSwitch("", "cad-smoke-test", "Run CAD export/view/cancel/restart smoke test and exit");
        parser.AddSwitch("", "cad-expect-failure", "Verify invalid CAD input without publishing output");
        parser.AddOption("", "smoke-report", "Smoke JSON output path");
        parser.AddSwitch("", "measure-startup", "Write F0 startup timing to redirected stdout and close");
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
        parser.Found("exchange-python", &options.exchangePython);
        parser.Found("catalog", &options.catalog);
        parser.Found("open-project", &options.openProject);
        parser.Found("smoke-report", &options.smokeReport);
        options.editorSmoke = parser.Found("editor-smoke-test");
        options.pcbSmoke = parser.Found("pcb-selection-smoke-test");
        options.catalogTableSmoke = parser.Found("catalog-table-smoke-test");
        options.projectSwitchSmoke = parser.Found("project-switch-smoke-test");
        options.largeResultsSmoke = parser.Found("large-results-smoke-test");
        options.canvasSmoke = parser.Found("canvas-smoke-test");
        options.coordinatesSmoke = parser.Found("coordinate-table-smoke-test");
        options.primitivesSmoke = parser.Found("primitives-smoke-test") || options.coordinatesSmoke;
        options.cadSmoke = parser.Found("cad-smoke-test");
        options.cadExpectFailure = parser.Found("cad-expect-failure");
        options.openEmsWsl = parser.Found("openems-wsl");
        options.solverActiveCancelSmoke = parser.Found("solver-active-cancel-smoke-test");
        options.solverSmoke = parser.Found("solver-smoke-test") || options.solverActiveCancelSmoke;
        options.solverExpectFailure = parser.Found("solver-expect-failure");
        parser.Found("solver-settings", &options.solverSettings);
        options.studySmoke = parser.Found("study-smoke-test");
        options.studyExpectFailure = parser.Found("study-expect-failure");
        options.printedSeedSmoke = parser.Found("printed-seed-smoke-test");
        options.designRulesSmoke = parser.Found("design-rules-smoke-test");
        options.physicalSetupSmoke = parser.Found("physical-setup-smoke-test");
        options.installationSmoke = parser.Found("installation-smoke-test");
        options.precisionPlanarSmoke = parser.Found("precision-planar-smoke-test");
        options.precisionEditorSmoke = parser.Found("precision-editor-smoke-test") || options.precisionPlanarSmoke;
        options.networkSmoke = parser.Found("network-smoke-test") || parser.Found("network-modal-smoke-test");
        options.sweepSmoke = parser.Found("sweep-smoke-test");
        options.resultsSmoke = parser.Found("results-smoke-test");
        options.validationSmoke = parser.Found("validation-smoke-test");
        options.selectionSmoke = parser.Found("selection-smoke-test");
        options.outputSmoke = parser.Found("output-smoke-test");
        options.featuresSmoke = parser.Found("features-smoke-test");
        options.pcbExchangeSmoke = parser.Found("pcb-exchange-smoke-test");
        options.setupSmoke = parser.Found("design-setup-smoke-test") || options.printedSeedSmoke ||
                             options.designRulesSmoke || options.physicalSetupSmoke || options.installationSmoke || options.precisionEditorSmoke ||
                             options.networkSmoke || options.sweepSmoke || options.resultsSmoke ||
                             options.validationSmoke || options.selectionSmoke || options.outputSmoke ||
                             options.featuresSmoke || options.pcbExchangeSmoke;
        parser.Found("study-specification", &options.studySpecification);
        options.smoke = parser.Found("smoke-test") || options.editorSmoke || options.canvasSmoke ||
                        options.primitivesSmoke || options.cadSmoke || options.solverSmoke || options.pcbSmoke ||
                        options.studySmoke || options.setupSmoke || options.catalogTableSmoke ||
                        options.projectSwitchSmoke || options.largeResultsSmoke;
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
            (!options.exchangePython.empty() && !wxFileName(options.exchangePython).IsAbsolute()) ||
            (!options.catalog.empty() && !wxFileName(options.catalog).IsAbsolute()))
        {
            wxMessageBox(Display("실행 경로는 절대 경로로 지정하십시오."), Display("실행 설정"), wxOK | wxICON_ERROR);
            ExitCode = 2;
            return false;
        }
        const bool measureStartup = parser.Found("measure-startup");
        if (options.solverActiveCancelSmoke && options.solverExpectFailure)
        {
            ExitCode = 2;
            return false;
        }
        if (measureStartup && (options.smoke || !options.openProject.empty() || !options.cadPython.empty() ||
                               !options.exchangePython.empty() || !options.catalog.empty() || options.openEmsWsl))
        {
            ExitCode = 2;
            return false;
        }
        auto* frame = new StudioFrame(std::move(options));
        if (measureStartup)
        {
            frame->EnableStartupProbe();
        }
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
