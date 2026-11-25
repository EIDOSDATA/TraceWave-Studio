#include "accessibility.h"
#include "b0_samples.h"
#include "renderer.h"

#if defined(_WIN32)
#include "prototype_archive.h"
#include "prototype_canvas.h"
#include "prototype_manufacturing.h"
#include "prototype_recent.h"
#include "prototype_model.h"
#include "prototype_template_panel.h"
#include "prototype_setup_panel.h"
#include "../wxwidgets/network_export_files.h"

#include <commdlg.h>
#include <future>
#endif

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <numbers>
#include <string>
#include <string_view>

#define SDL_MAIN_HANDLED
#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>
#include <imgui.h>
#include <imgui_impl_sdl3.h>
#include <imgui_internal.h>
#include <misc/cpp/imgui_stdlib.h>
#include <implot.h>

namespace
{
constexpr char boardTitle[] = "기판###board";
constexpr char resultTitle[] = "RF 결과###results";
constexpr char inputTitle[] = "입력###input";
constexpr char detachedInputTitle[] = "입력###detached-input";
#if defined(_WIN32)
constexpr std::array<std::string_view, 5> targetFieldKeys{
    "name", "band.start.value", "band.end.value", "sampling.count", "criteria.s11_db.value"};
#endif
constexpr char committedText[] = "한글 검수";
constexpr char editingText[] = "한";
constexpr int initialWidth = 1120;
constexpr int initialHeight = 720;
using accessibility::Control;
using accessibility::Operation;

struct Options
{
    bool smoke = false;
    const char* font = nullptr;
#if defined(_WIN32)
    PrototypeServiceOptions service;
    bool serviceCheck = false;
    bool serviceReplay = false;
    const char* openProject = nullptr;
#endif
};

struct Shell
{
    bool boardOpen = true;
    bool resultOpen = true;
    bool inputOpen = true;
    bool focusInput = false;
    bool detachInput = false;
    bool placeInput = false;
    bool restoreMainFocus = false;
    bool detachResult = false;
    bool undockNextFrame = false;
    bool resetLayout = false;
    bool noteActive = false;
    bool plotDrawn = false;
    bool boardDrawn = false;
    std::array<char, accessibility::noteCapacity> note{};
    std::string preedit;
    SDL_WindowID preeditWindow = 0;
    SDL_WindowID noteWindow = 0;
    SDL_WindowID detachedResultWindow = 0;
    SDL_WindowID detachedNoteWindow = 0;
    float zoom = 1.0f;
    ImVec2 pan{};
    ImGuiID noteId = 0;
    Control requestedFocus = Control::root;
    bool openMenu = false;
    bool closeMenu = false;
    accessibility::Bridge access;
#if defined(_WIN32)
    PrototypeProject* project = nullptr;
    PrototypeModel model;
    bool sectionOpen = false;
    bool sectionUpper = true;
    std::size_t sectionAxis = 2;
    double sectionPosition = 0.0;
    std::string sectionModel;
    void drawSection(const DisplayMesh::Scene& scene);
    PrototypeManufacturing manufacturing;
    PrototypeRecent recent;
    PrototypeArchive archive;
    bool archiveOpen = false;
    bool endpointOpen = false;
    PrototypeEndpoint endpoint;
    void drawEndpoint();
    bool renameOpen = false;
    bool renameLoaded = false;
    bool renameDetails = false;
    ImGuiID renameNameId = 0;
    std::array<char, accessibility::projectNameCapacity> renameName{};
    std::string renameTarget;
    std::string renamedObjectId;
    void drawRename();
    void closeRename();
    void setRenameName(std::string_view value);
    void selectEndpoint(CanvasPrecision::Endpoint side);
    bool canSwitchProject() const;
    void drawArchive();
    std::size_t recentIndex = 0;
    std::string recordedProject;
    bool modelOpen = false;
    bool analysisOpen = false;
    bool resultHistoryOpen = false;
    bool exchangeOpen = false;
    bool rfExportOpen = false;
    std::size_t rfFormatIndex = 0;
    std::string matrixArtifact;
    std::size_t matrixRow = 0;
    std::size_t matrixColumn = 0;
    std::size_t matrixSample = 0;
    bool showMatrixTable = false;
    const char* workspacePath = nullptr;
    std::unique_ptr<PrototypeProject> nextProject;
    std::array<char, accessibility::projectNameCapacity> projectName{};
    std::string chooserStatus;
    ImGuiID projectNameId = 0;
    SDL_WindowID projectTextWindow = 0;
    bool projectTextActive = false;
    bool serviceReady = false;
    bool chooserOpen = false;
    bool createProject = false;
    bool recoveryOpen = false;
    std::size_t recoveryIndex = 0;
    void drawRecovery();
    enum class EvidencePage { records, assumptions, history };
    bool evidenceOpen = false;
    EvidencePage evidencePage = EvidencePage::records;
    std::size_t evidenceIndex = 0;
    std::size_t evidenceValue = 0;
    void drawEvidence();
    void moveEvidence(Control control);
    bool targetOpen = false;
    PrototypeTarget::Page targetPage = PrototypeTarget::Page::band;
    bool targetRemove = false;
    std::size_t targetChange = 0;
    int targetInputGeneration = 0;
    std::array<ImGuiID, targetFieldKeys.size() + 1> targetInputIds{};
    void drawTarget();
    void drawTargetSources();
    void setTargetText(Control control, const std::string& value);
    void targetAction(Control control);
    bool templateOpen = false;
    PrototypeTemplatePanel templatePanel;
    bool setupOpen = false;
    PrototypeSetupPanel setupPanel;
    void submitProject();
    void updateProjects(SDL_Window* window, std::unique_ptr<PrototypeProject>& current, PrototypeService& service);
    void setProjectName(std::string_view value);
    void drawProjectChooser();
    std::future<std::string> rfDelivery;
    std::string rfDeliveryStatus;
    void drawLiveBoard();
    void drawLiveModel();
    void drawExchange();
    void drawLiveResult();
    void drawMatrix(const PrototypeMatrix::Matrix& matrix);
    void selectMatrixAxis(Control control);
    void drawResultHistory();
    void drawRfExport();
    void deliverRfExport(SDL_Window* mainWindow);
    void drawAnalysis();
    void panelButton(Control control, const char* label, bool enabled, bool checked = false,
        Control parent = Control::board);
#endif

    bool processEvent(const SDL_Event& event);
    void draw(const Renderer& renderer, SDL_Window* mainWindow, bool koreanFont, const char* serviceStatus);
    void finishFrame(SDL_Window* mainWindow);
    void handleShortcuts(bool hasViewports);
    void drawMenus(bool hasViewports);
    void drawBoard();
    void drawResult(bool hasViewports);
    void drawInput(SDL_Window* mainWindow);
    void drawNote(const ImGuiViewport* mainViewport);
    void activate(Control control);
    void applyActions();
    void setNote(std::string_view text);
    void focusItem(Control control);
};

bool parseOptions(int argc, char** argv, Options& options)
{
    for (int index = 1; index < argc; ++index)
    {
        const std::string_view argument = argv[index];
        if (argument == "--smoke")
        {
            options.smoke = true;
        }
        else if (argument == "--font" && index + 1 < argc)
        {
            options.font = argv[++index];
        }
#if defined(_WIN32)
        else if (argument == "--service-check")
        {
            options.serviceCheck = true;
        }
        else if (argument == "--service-replay")
        {
            options.serviceReplay = true;
        }
        else if (argument == "--open-project" && index + 1 < argc)
        {
            options.openProject = argv[++index];
            if (!*options.openProject)
            {
                return false;
            }
        }
        else if (argument == "--python" && index + 1 < argc)
        {
            options.service.python = argv[++index];
        }
        else if (argument == "--source" && index + 1 < argc)
        {
            options.service.source = argv[++index];
        }
        else if (argument == "--cad-python" && index + 1 < argc)
        {
            options.service.cadPython = argv[++index];
            if (!*options.service.cadPython)
            {
                return false;
            }
        }
        else if (argument == "--exchange-python" && index + 1 < argc)
        {
            options.service.exchangePython = argv[++index];
            if (!*options.service.exchangePython)
            {
                return false;
            }
        }
        else if (argument == "--workspace" && index + 1 < argc)
        {
            options.service.workspace = argv[++index];
        }
#endif
        else
        {
            return false;
        }
    }
#if defined(_WIN32)
    const bool requested = options.serviceCheck || options.serviceReplay || options.service.python ||
        options.service.source || options.service.workspace || options.service.cadPython ||
        options.service.exchangePython || options.openProject;
    if (requested && (!options.service.python || !options.service.source || !options.service.workspace ||
        ((options.serviceCheck || options.serviceReplay) && options.smoke) ||
        (options.serviceCheck && options.serviceReplay) ||
        (options.openProject && (options.serviceCheck || options.serviceReplay || options.smoke))))
    {
        return false;
    }
#endif
    return true;
}

/** @brief 시스템 또는 지정 글꼴에서 메모와 화면의 글자 범위를 읽는다. */
ImFont* installFont(const char* requested)
{
    ImGuiIO& io = ImGui::GetIO();
    const char* candidates[] = {
#if defined(_WIN32)
        "C:/Windows/Fonts/malgun.ttf",
#elif defined(__APPLE__)
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
#else
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
#endif
    };
    const char* filename = requested;
    if (filename)
    {
        SDL_PathInfo info;
        if (!SDL_GetPathInfo(filename, &info) || info.type != SDL_PATHTYPE_FILE)
        {
            std::fprintf(stderr, "Font file is unavailable: %s\n", filename);
            return nullptr;
        }
    }
    else
    {
        for (const char* candidate : candidates)
        {
            SDL_PathInfo info;
            if (SDL_GetPathInfo(candidate, &info) && info.type == SDL_PATHTYPE_FILE)
            {
                filename = candidate;
                break;
            }
        }
    }
    if (!filename)
    {
        return io.Fonts->AddFontDefault();
    }

    ImFontConfig config;
    config.RasterizerDensity = 2.0f;
#if defined(_WIN32)
    /** @brief 텍스처 최대 크기가 4096인 장치에서도 한글과 한자를 함께 올린다. */
    const bool compactAtlas = bgfx::getCaps()->limits.maxTextureSize <= 4096;
    config.RasterizerDensity = compactAtlas ? 1.5f : 2.0f;
#endif
    ImFont* font = io.Fonts->AddFontFromFileTTF(filename, 18.0f, &config, io.Fonts->GetGlyphRangesKorean());
#if defined(_WIN32)
    if (font)
    {
        /** @brief 한자 통합 및 호환 범위를 같은 글꼴에 병합하고 텍스처의 빈 행을 줄인다. */
        static constexpr ImWchar hanjaRanges[] = {0x3400, 0x4dbf, 0x4e00, 0x9fff, 0xf900, 0xfaff, 0};
        io.Fonts->Flags |= ImFontAtlasFlags_NoPowerOfTwoHeight;
        config.MergeMode = true;
        config.RasterizerDensity = compactAtlas ? 1.0f : 1.5f;
        io.Fonts->AddFontFromFileTTF(filename, 18.0f, &config, hanjaRanges);
    }
#endif
    return font;
}

SDL_WindowID windowId(const ImGuiViewport* viewport)
{
    return static_cast<SDL_WindowID>(reinterpret_cast<std::uintptr_t>(viewport->PlatformHandle));
}

/** @brief 운영체제 UI 배율과 프레임버퍼 픽셀 밀도를 구분한다. */
float windowDpiScale(ImGuiViewport* viewport)
{
    SDL_Window* window = SDL_GetWindowFromID(windowId(viewport));
    if (window)
    {
        const float density = SDL_GetWindowPixelDensity(window);
        const float displayScale = SDL_GetWindowDisplayScale(window);
        if (density > 0.0f && displayScale > 0.0f)
        {
            return displayScale / density;
        }
    }
    return 1.0f;
}

/** @brief 조합과 확정 이벤트를 현재 편집란이 속한 SDL 창으로 제한한다. */
bool Shell::processEvent(const SDL_Event& event)
{
    if (event.type == SDL_EVENT_WINDOW_CLOSE_REQUESTED
        && (event.window.windowID == detachedResultWindow || event.window.windowID == detachedNoteWindow))
    {
        if (event.window.windowID == detachedNoteWindow)
        {
            detachInput = false;
            focusInput = true;
        }
        else if (!detachInput)
        {
            focusInput = true;
        }
        else
        {
            requestedFocus = Control::windowMenu;
        }
        restoreMainFocus = true;
    }
    const auto textWindow = [this](SDL_WindowID id)
    {
#if defined(_WIN32)
        if (projectTextActive)
        {
            return id == projectTextWindow;
        }
#endif
        return noteActive && id == noteWindow;
    };
    if (event.type == SDL_EVENT_TEXT_EDITING)
    {
        if (!textWindow(event.edit.windowID))
        {
            return false;
        }
        preedit = event.edit.text ? event.edit.text : "";
        preeditWindow = preedit.empty() ? 0 : event.edit.windowID;
    }
    else if ((event.type == SDL_EVENT_TEXT_INPUT && preeditWindow == event.text.windowID)
        || (event.type == SDL_EVENT_WINDOW_FOCUS_LOST && preeditWindow == event.window.windowID))
    {
        preedit.clear();
        preeditWindow = 0;
    }
    if (event.type == SDL_EVENT_KEY_DOWN && event.key.scancode == SDL_SCANCODE_ESCAPE
        && preeditWindow && preeditWindow == event.key.windowID)
    {
        if (SDL_Window* window = SDL_GetWindowFromID(preeditWindow))
        {
            SDL_ClearComposition(window);
        }
        preedit.clear();
        preeditWindow = 0;
        return false;
    }
    return event.type != SDL_EVENT_TEXT_INPUT || textWindow(event.text.windowID);
}

/** @brief 바로 가기, 메뉴 및 UI Automation에서 같은 명령을 사용한다. */
#if defined(_WIN32)
double sectionCenter(const DisplayMesh::Scene& scene, std::size_t axis)
{
    return std::array{scene.center.x, scene.center.y, scene.center.z}[axis];
}
#endif

void Shell::activate(Control control)
{
#if defined(_WIN32)
    if (renameOpen && control != Control::renameApply && control != Control::renameCancel &&
        control != Control::renameDetails && control != Control::renameCopy)
    {
        return;
    }
#endif
    switch (control)
    {
        case Control::showBoard: boardOpen = !boardOpen; break;
        case Control::showResult: resultOpen = !resultOpen; break;
        case Control::focusNote: focusInput = true; break;
        case Control::detachResult: resultOpen = detachResult = undockNextFrame = true; break;
        case Control::detachNote: detachInput = placeInput = focusInput = true; break;
        case Control::resetLayout: resetLayout = true; break;
        case Control::resetBoard:
#if defined(_WIN32)
            if (modelOpen)
            {
                model.resetView();
                break;
            }
#endif
            zoom = 1.0f;
            pan = {};
            break;
        case Control::clearNote: setNote({}); break;
#if defined(_WIN32)
        case Control::showProjectChooser:
            if (!nextProject && (project->view() || !chooserOpen))
            {
                chooserOpen = !chooserOpen;
            }
            break;
        case Control::createProjectMode:
            if (!nextProject)
            {
                createProject = !createProject;
            }
            break;
        case Control::submitProject: submitProject(); break;
        case Control::renameToggle:
            if (project && !modelOpen && !evidenceOpen && !targetOpen && !templateOpen && !setupOpen && !nextProject && !archive.busy() && project->canRename())
            {
                const auto* view = project->view();
                const auto* shape = view->canvas.Find(view->selection);
                renameTarget = shape ? shape->label : "프로젝트";
                renamedObjectId = shape ? shape->id : view->id;
                boardOpen = renameOpen = true;
                renameDetails = renameLoaded = false;
                renameName.fill('\0');
                renameNameId = 0;
                project->readRename();
            }
            break;
        case Control::renameApply:
            if (renameOpen && renameLoaded)
            {
                project->renameObject(renameName.data());
            }
            break;
        case Control::renameDetails:
            if (renameOpen)
            {
                renameDetails = !renameDetails;
            }
            break;
        case Control::renameCopy:
            if (renameOpen && renameDetails)
            {
                ImGui::SetClipboardText(renamedObjectId.c_str());
            }
            break;
        case Control::renameCancel:
            if (renameOpen && !project->busy())
            {
                closeRename();
            }
            break;
        case Control::recentPrevious:
            if (recentIndex > 0)
            {
                --recentIndex;
            }
            break;
        case Control::recentNext:
            if (recentIndex + 1 < recent.paths().size())
            {
                ++recentIndex;
            }
            break;
        case Control::recentOpen:
            if (recentIndex < recent.paths().size() && project->canSwitch() && !nextProject)
            {
                createProject = false;
                setProjectName(std::string_view(recent.paths()[recentIndex]).substr(9));
                submitProject();
            }
            break;
        case Control::setupToggle:
            if (project && project->view() && !project->busy())
            {
                setupOpen = !setupOpen;
                if (setupOpen && !project->setup().context.is_object())
                {
                    project->readSetup();
                }
            }
            break;
        case Control::setupBoard:
        case Control::setupPhysical:
        case Control::setupRules:
        case Control::setupRead:
        case Control::setupReview:
        case Control::setupApply:
        case Control::setupRemove:
        case Control::setupDiscard:
        case Control::setupCheck:
        case Control::setupPrevious:
        case Control::setupNext:
        case Control::setupJump:
        case Control::catalogConnect:
        case Control::catalogSearch:
        case Control::catalogNext:
        case Control::catalogDetail:
            if (setupOpen && setupPanel.action(*project, control))
            {
                setupOpen = modelOpen = templateOpen = evidenceOpen = false;
            }
            break;
        case Control::templateToggle:
            if (project && project->view() && !project->busy())
            {
                templateOpen = !templateOpen;
                if (templateOpen && !project->literature().hasContext())
                {
                    project->readTemplate();
                }
            }
            break;
        case Control::templateRead:
        case Control::templateInput:
        case Control::templateReview:
        case Control::templatePreview:
        case Control::templateApply:
        case Control::templateDiscard:
            if (templateOpen)
            {
                templatePanel.action(*project, control);
            }
            break;
        case Control::targetToggle:
        case Control::targetNew:
        case Control::targetBand:
        case Control::targetCriteria:
        case Control::targetSources:
        case Control::targetApply:
        case Control::targetApplyRemoval:
        case Control::targetRemove:
        case Control::targetDiscard:
        case Control::targetRead:
        case Control::targetPrevChange:
        case Control::targetNextChange: targetAction(control); break;
        case Control::evidenceToggle:
            evidenceOpen = !evidenceOpen;
            if (evidenceOpen && !project->evidence())
            {
                project->readRecovery();
            }
            break;
        case Control::evidenceReload: project->readRecovery(); break;
        case Control::evidenceRecords:
        case Control::evidenceAssumptions:
        case Control::evidenceHistory:
            evidencePage = control == Control::evidenceHistory ? EvidencePage::history :
                control == Control::evidenceAssumptions ? EvidencePage::assumptions : EvidencePage::records;
            evidenceIndex = evidenceValue = 0;
            break;
        case Control::evidencePrevious:
        case Control::evidenceNext:
        case Control::evidencePreviousValue:
        case Control::evidenceNextValue: moveEvidence(control); break;
        case Control::showRecovery:
            recoveryOpen = !recoveryOpen;
            if (recoveryOpen)
            {
                recoveryIndex = 0;
                project->readRecovery();
            }
            break;
        case Control::readRecovery: project->readRecovery(); break;
        case Control::priorRecoveryField:
            if (recoveryIndex > 0)
            {
                --recoveryIndex;
            }
            break;
        case Control::nextRecoveryField:
            if (const auto& data = project->recovery(); data.is_object() &&
                recoveryIndex + 1 < data.at("recovery_details").at("rows").size())
            {
                ++recoveryIndex;
            }
            break;
        case Control::archiveToggle: archiveOpen = !archiveOpen; break;
        case Control::archivePick:
            if (serviceReady && canSwitchProject())
            {
                archive.choose();
            }
            break;
        case Control::archiveApply:
            if (serviceReady && canSwitchProject())
            {
                archive.approve();
            }
            break;
        case Control::archiveCancel:
            if (archive.busy() || canSwitchProject())
            {
                archive.cancel();
            }
            break;
        case Control::archiveOpen:
            if (archive.restoredPath().starts_with("projects/") && canSwitchProject())
            {
                createProject = false;
                setProjectName(std::string_view(archive.restoredPath()).substr(9));
                submitProject();
            }
            break;
        case Control::endpointToggle:
            endpointOpen = !endpointOpen;
            endpoint.picking = false;
            break;
        case Control::endpointStart: selectEndpoint(CanvasPrecision::Endpoint::Start); break;
        case Control::endpointEnd: selectEndpoint(CanvasPrecision::Endpoint::End); break;
        case Control::endpointReset: selectEndpoint(endpoint.side); break;
        case Control::endpointSnap: endpoint.snap = !endpoint.snap; break;
        case Control::endpointPick:
            if (project->canMoveEndpoint(endpoint.side))
            {
                endpoint.picking = !endpoint.picking;
            }
            break;
        case Control::endpointApply:
            if (const auto* view = project->view(); view && view->revision == endpoint.revision &&
                view->selection == endpoint.id)
            {
                project->moveEndpoint(endpoint.side, endpoint.point);
            }
            break;
        case Control::reloadProject: project->reopen(); break;
        case Control::saveProject: project->save(); break;
        case Control::undoProject: project->undo(); break;
        case Control::moveLeft: project->translate(-1.0, 0.0); break;
        case Control::moveRight: project->translate(1.0, 0.0); break;
        case Control::moveDown: project->translate(0.0, -1.0); break;
        case Control::moveUp: project->translate(0.0, 1.0); break;
        case Control::toggleModel:
            modelOpen = !modelOpen;
            if (modelOpen && !project->cad().scene())
            {
                project->readCad();
            }
            break;
        case Control::sectionToggle:
            if (!model.sectionPending())
            {
                sectionOpen = !sectionOpen;
                if (!sectionOpen)
                {
                    model.setSection(std::nullopt);
                }
            }
            break;
        case Control::sectionAxis:
            if (const auto& scene = project->cad().scene(); scene && !model.sectionPending())
            {
                sectionAxis = (sectionAxis + 1) % 3;
                sectionPosition = sectionCenter(*scene, sectionAxis);
            }
            break;
        case Control::sectionSide:
            if (!model.sectionPending())
            {
                sectionUpper = !sectionUpper;
            }
            break;
        case Control::sectionApply:
            if (const auto& scene = project->cad().scene(); scene && std::isfinite(sectionPosition))
            {
                const auto side = sectionUpper ? 1.0 : -1.0;
                PrototypeSection::Plane plane{0, 0, 0, side * (sectionCenter(*scene, sectionAxis) - sectionPosition)};
                plane[sectionAxis] = side;
                model.setSection(plane);
            }
            break;
        case Control::reloadModel: project->readCad(); break;
        case Control::buildModel: project->startCad(PrototypeCadJob::Output::geometry); break;
        case Control::exportStep: project->startCad(PrototypeCadJob::Output::step); break;
        case Control::cancelCad: project->cancelCad(); break;
        case Control::showExchange: exchangeOpen = !exchangeOpen; break;
        case Control::priorExchange: project->moveExchangeFormat(-1); break;
        case Control::nextExchange: project->moveExchangeFormat(1); break;
        case Control::priorFootprint: project->moveExchangeFootprint(-1); break;
        case Control::nextFootprint: project->moveExchangeFootprint(1); break;
        case Control::reviewFootprint:
        case Control::reviewExchange: project->reviewExchange(); break;
        case Control::buildExchange: project->approveExchange(); break;
        case Control::verifyExchange: project->verifyExchange(); break;
        case Control::cancelExchange: project->cancelExchange(); break;
        case Control::reloadExchange: project->reloadExchange(); break;
        case Control::manufacturingFormat: manufacturing.chooseFormat(); break;
        case Control::buildManufacturing:
            if (project->writable() && !project->exchange().active() && project->exchange().showingBoard() &&
                project->exchange().published())
            {
                manufacturing.select(*project->exchange().published());
            }
            break;
        case Control::reloadResult: project->readResult(); break;
        case Control::showSolver: analysisOpen = !analysisOpen; break;
        case Control::readSolverConditions: project->readSolverConditions(); break;
        case Control::priorSolverCondition: project->moveSolverCondition(-1); break;
        case Control::nextSolverCondition: project->moveSolverCondition(1); break;
        case Control::reviewSolver: project->reviewSolver(); break;
        case Control::approveSolver: project->approveSolver(); break;
        case Control::cancelSolver: project->cancelSolver(); break;
        case Control::showResultHistory:
            resultHistoryOpen = !resultHistoryOpen;
            if (resultHistoryOpen && !project->result().historyChoice())
            {
                project->readResultHistory();
            }
            break;
        case Control::reloadResultHistory: project->readResultHistory(); break;
        case Control::priorResult: project->browseResultHistory(-1); break;
        case Control::nextResult: project->browseResultHistory(1); break;
        case Control::openHistoryResult: project->openHistoryResult(); break;
        case Control::matrixPriorRow:
        case Control::matrixNextRow:
        case Control::matrixPriorColumn:
        case Control::matrixNextColumn:
        case Control::matrixPriorSample:
        case Control::matrixNextSample: selectMatrixAxis(control); break;
        case Control::matrixTable: showMatrixTable = !showMatrixTable; break;
        case Control::showRfExport: rfExportOpen = !rfExportOpen; break;
        case Control::previousRfExport:
            if (rfFormatIndex > 0)
            {
                --rfFormatIndex;
            }
            break;
        case Control::nextRfExport:
        case Control::saveRfExport:
            if (const auto& series = project->result().series(); series && rfFormatIndex < series->exportFormats.size())
            {
                if (control == Control::nextRfExport && rfFormatIndex + 1 < series->exportFormats.size())
                {
                    ++rfFormatIndex;
                }
                else if (control == Control::saveRfExport && !rfDelivery.valid())
                {
                    rfDeliveryStatus.clear();
                    project->prepareRfExport(series->exportFormats[rfFormatIndex]);
                }
            }
            break;
#endif
        default: break;
    }
}

#if defined(_WIN32)
void Shell::selectMatrixAxis(Control control)
{
    const auto& matrix = project->result().matrix();
    if (!matrix || matrix->artifact != matrixArtifact)
    {
        return;
    }
    const auto step = [](std::size_t& index, std::size_t count, bool prior)
    {
        if (prior && index > 0)
        {
            --index;
        }
        else if (!prior && index + 1 < count)
        {
            ++index;
        }
    };
    switch (control)
    {
        case Control::matrixPriorRow:
        case Control::matrixNextRow: step(matrixRow, matrix->ports.size(), control == Control::matrixPriorRow); break;
        case Control::matrixPriorColumn:
        case Control::matrixNextColumn:
            step(matrixColumn, matrix->ports.size(), control == Control::matrixPriorColumn);
            break;
        case Control::matrixPriorSample:
        case Control::matrixNextSample:
            step(matrixSample, matrix->hertz.size(), control == Control::matrixPriorSample);
            break;
        default: break;
    }
}
#endif

void Shell::setNote(std::string_view text)
{
    note.fill('\0');
    std::copy(text.begin(), text.end(), note.begin());
    if (ImGuiInputTextState* input = ImGui::GetInputTextState(noteId))
    {
        input->ReloadUserBufAndMoveToEnd();
    }
}

void Shell::applyActions()
{
    for (const auto& action : access.takeActions())
    {
#if defined(_WIN32)
        if (renameOpen && (action.control < Control::renameDialog || action.control > Control::renameCopy))
        {
            continue;
        }
#endif
        switch (action.operation)
        {
            case Operation::invoke:
            case Operation::toggle: activate(action.control); break;
            case Operation::expand: openMenu = true; break;
            case Operation::collapse: closeMenu = true; break;
            case Operation::setValue:
#if defined(_WIN32)
                if (action.control == Control::renameName)
                {
                    if (renameOpen && renameLoaded && project->writable() && project->renameName())
                    {
                        setRenameName(action.value);
                    }
                    break;
                }
                if (action.control >= Control::targetName && action.control <= Control::targetReason)
                {
                    setTargetText(action.control, action.value);
                    break;
                }
                if (action.control == Control::projectName)
                {
                    setProjectName(action.value);
                    break;
                }
                if (action.control == Control::sectionPosition)
                {
                    double candidate = 0.0;
                    const auto* end = action.value.data() + action.value.size();
                    const auto result = std::from_chars(action.value.data(), end, candidate);
                    if (result.ec == std::errc{} && result.ptr == end && std::isfinite(candidate))
                    {
                        sectionPosition = candidate;
                    }
                    break;
                }
                if (action.control == Control::endpointX || action.control == Control::endpointY)
                {
                    const auto* view = project->view();
                    if (view && view->revision == endpoint.revision && view->selection == endpoint.id &&
                        project->canMoveEndpoint(endpoint.side))
                    {
                        auto candidate = endpoint.point;
                        auto& value = action.control == Control::endpointX ? candidate.x : candidate.y;
                        const auto* end = action.value.data() + action.value.size();
                        const auto number = std::from_chars(action.value.data(), end, value);
                        if (number.ec == std::errc{} && number.ptr == end && CanvasGeometry::Valid(candidate))
                        {
                            endpoint.point = candidate;
                            endpoint.snapLabel.clear();
                        }
                    }
                    break;
                }
#endif
                if (action.control == Control::note)
                {
                    setNote(action.value);
                }
                break;
            case Operation::focus:
                if (action.control == Control::note)
                {
                    focusInput = true;
                }
                else
                {
                    requestedFocus = action.control;
                }
                break;
        }
    }
}

void Shell::focusItem(Control control)
{
    if (requestedFocus == control)
    {
        ImGuiWindow* window = ImGui::GetCurrentWindowRead();
        const ImGuiContext& context = *ImGui::GetCurrentContext();
        ImGui::FocusWindow(window);
        ImGui::SetNavID(context.LastItemData.ID, window->DC.NavLayerCurrent, context.CurrentFocusScopeId,
            ImGui::WindowRectAbsToRel(window, context.LastItemData.NavRect));
        ImGui::SetNavCursorVisible(true);
        requestedFocus = Control::root;
    }
}

void Shell::handleShortcuts(bool hasViewports)
{
#if defined(_WIN32)
    if (renameOpen)
    {
        if (!project->busy() && ImGui::IsKeyPressed(ImGuiKey_Escape, false))
        {
            closeRename();
        }
        return;
    }
    if (workspacePath && !nextProject && !archive.busy() && ImGui::GetIO().KeyCtrl &&
        (ImGui::IsKeyPressed(ImGuiKey_O, false) || ImGui::IsKeyPressed(ImGuiKey_N, false)))
    {
        boardOpen = chooserOpen = true;
        createProject = ImGui::IsKeyPressed(ImGuiKey_N, false);
        requestedFocus = Control::projectName;
    }
    if (project && project->configured() && !nextProject && !archive.busy())
    {
        if (endpoint.picking && ImGui::IsKeyPressed(ImGuiKey_Escape, false))
        {
            endpoint.picking = false;
        }
        if (ImGui::IsKeyPressed(ImGuiKey_F2, false) && !ImGui::GetIO().WantTextInput)
        {
            activate(Control::renameToggle);
        }
        if (ImGui::IsKeyPressed(ImGuiKey_F5, false) && !project->target().dirty() && !project->setup().dirty())
        {
            project->reopen();
        }
        if (ImGui::GetIO().KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_S, false))
        {
            if (!project->target().dirty())
            {
                project->save();
            }
        }
    }
#endif
    if (ImGui::IsKeyPressed(ImGuiKey_F6, false))
    {
        activate(Control::focusNote);
    }
    if (ImGui::IsKeyPressed(ImGuiKey_F7, false))
    {
        activate(Control::showResult);
    }
    if (hasViewports && ImGui::IsKeyPressed(ImGuiKey_F8, false))
    {
        activate(ImGui::GetIO().KeyShift ? Control::detachNote : Control::detachResult);
    }
    if (ImGui::IsKeyPressed(ImGuiKey_F9, false))
    {
        activate(Control::resetLayout);
    }
    if (ImGui::IsKeyPressed(ImGuiKey_F10, false))
    {
        openMenu = true;
    }
}

void Shell::drawMenus(bool hasViewports)
{
    handleShortcuts(hasViewports);
    if (ImGui::BeginMainMenuBar())
    {
        const ImGuiViewport* viewport = ImGui::GetWindowViewport();
        access.panel(Control::menuBar);
        const bool keyboardOpen = openMenu && !ImGui::IsPopupOpen("창");
        if (keyboardOpen)
        {
            ImGui::OpenPopup("창", ImGuiPopupFlags_NoReopen);
        }
        openMenu = false;
        const bool menuOpen = ImGui::BeginMenu("창");
        if (!menuOpen)
        {
            focusItem(Control::windowMenu);
        }
        access.item(Control::windowMenu, Control::menuBar, true, menuOpen, viewport);
        if (menuOpen)
        {
            if (keyboardOpen)
            {
                ImGui::NavInitWindow(ImGui::GetCurrentWindowRead(), true);
                ImGui::SetNavCursorVisible(true);
            }
            if (closeMenu)
            {
                ImGui::CloseCurrentPopup();
            }
            const auto menuItem = [this](Control control, const char* name, const char* key, const bool* checked,
                bool enabled)
            {
                if (ImGui::MenuItem(name, key, checked && *checked, enabled))
                {
                    activate(control);
                }
                focusItem(control);
                access.item(control, Control::windowMenu, enabled, checked && *checked);
            };
            menuItem(Control::showBoard, "기판", nullptr, &boardOpen, true);
            menuItem(Control::showResult, "RF 결과", "F7", &resultOpen, true);
            menuItem(Control::focusNote, "입력에 초점", "F6", nullptr, true);
            menuItem(Control::detachResult, "결과를 별도 창으로", "F8", nullptr, hasViewports);
            menuItem(Control::detachNote, "입력을 별도 창으로", "Shift+F8", nullptr, hasViewports);
            menuItem(Control::resetLayout, "기본 배치 복원", "F9", nullptr, true);
            ImGui::EndMenu();
        }
        closeMenu = false;
        ImGui::EndMainMenuBar();
    }
}

void Shell::draw(const Renderer& renderer, SDL_Window* mainWindow, bool koreanFont, const char* serviceStatus)
{
    const bool hasViewports = renderer.hasViewports();
    applyActions();
    drawMenus(hasViewports);
    const ImGuiID dockspace = ImHashStr("TraceWavePrototypeDock");
    if (resetLayout || !ImGui::DockBuilderGetNode(dockspace))
    {
        ImGui::DockBuilderRemoveNode(dockspace);
        ImGui::DockBuilderAddNode(dockspace, ImGuiDockNodeFlags_DockSpace);
        ImGui::DockBuilderSetNodeSize(dockspace, ImGui::GetMainViewport()->WorkSize);
        ImGuiID board = dockspace;
        const auto inputs = ImGui::DockBuilderSplitNode(board, ImGuiDir_Right, 0.28f, nullptr, &board);
        const auto results = ImGui::DockBuilderSplitNode(board, ImGuiDir_Down, 0.49f, nullptr, &board);
        ImGui::DockBuilderDockWindow(boardTitle, board);
        ImGui::DockBuilderDockWindow(resultTitle, results);
        ImGui::DockBuilderDockWindow(inputTitle, inputs);
        ImGui::DockBuilderFinish(dockspace);
        if (resetLayout)
        {
            boardOpen = resultOpen = inputOpen = true;
            detachResult = undockNextFrame = resetLayout = false;
            if (detachInput)
            {
                detachInput = false;
                focusInput = true;
                restoreMainFocus = true;
            }
        }
    }
    ImGui::DockSpaceOverViewport(dockspace);
    plotDrawn = boardDrawn = false;
#if defined(_WIN32)
    projectTextActive = false;
    model.pollSection();
#endif
    drawBoard();
    drawResult(hasViewports);
    drawInput(mainWindow);

    if (ImGui::BeginViewportSideBar("###status", ImGui::GetMainViewport(), ImGuiDir_Down,
        ImGui::GetFrameHeight(), ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoSavedSettings))
    {
        int pixelWidth = 0;
        int pixelHeight = 0;
        SDL_GetWindowSizeInPixels(mainWindow, &pixelWidth, &pixelHeight);
        ImGui::Text("%s  |  %s  |  %d × %d px  |  %.0f%%", renderer.name(), SDL_GetCurrentVideoDriver(),
            pixelWidth, pixelHeight, 100.0f * SDL_GetWindowDisplayScale(mainWindow));
        if (serviceStatus && *serviceStatus)
        {
            ImGui::SameLine();
            ImGui::TextUnformatted(serviceStatus);
        }
        if (!koreanFont)
        {
            ImGui::SameLine();
            ImGui::TextUnformatted("Hangul font missing (see --font)");
        }
        if (!hasViewports)
        {
            ImGui::SameLine();
            ImGui::TextUnformatted("Docking in the main window");
        }
    }
    ImGui::End();
}

void Shell::drawBoard()
{
    if (!boardOpen)
    {
        return;
    }
    if (requestedFocus == Control::board || requestedFocus == Control::resetBoard ||
        requestedFocus == Control::reloadProject || requestedFocus == Control::saveProject ||
        requestedFocus == Control::undoProject || requestedFocus == Control::moveLeft ||
        requestedFocus == Control::moveRight || requestedFocus == Control::moveDown ||
        requestedFocus == Control::moveUp || requestedFocus == Control::toggleModel ||
        requestedFocus == Control::reloadModel || requestedFocus == Control::buildModel ||
        requestedFocus == Control::exportStep || requestedFocus == Control::cancelCad ||
        (requestedFocus >= Control::showExchange && requestedFocus <= Control::reloadExchange) ||
        requestedFocus == Control::manufacturingFormat || requestedFocus == Control::buildManufacturing ||
        (requestedFocus >= Control::showProjectChooser && requestedFocus <= Control::submitProject) ||
        (requestedFocus >= Control::showRecovery && requestedFocus <= Control::nextRecoveryField) ||
        (requestedFocus >= Control::recentPrevious && requestedFocus <= Control::recentOpen) ||
        (requestedFocus >= Control::archiveToggle && requestedFocus <= Control::archiveOpen) ||
        (requestedFocus >= Control::endpointToggle && requestedFocus <= Control::endpointReset) ||
        (requestedFocus >= Control::sectionToggle && requestedFocus <= Control::sectionApply) ||
        requestedFocus == Control::renameToggle ||
        (requestedFocus >= Control::evidenceToggle && requestedFocus <= Control::evidenceNextValue) ||
        (requestedFocus >= Control::targetToggle && requestedFocus <= Control::targetReason) ||
        (requestedFocus >= Control::templateToggle && requestedFocus <= Control::templateDiscard) ||
        (requestedFocus >= Control::setupToggle && requestedFocus <= Control::catalogDetail))
    {
        ImGui::SetNextWindowFocus();
        if (requestedFocus == Control::board)
        {
            requestedFocus = Control::root;
        }
    }
    if (ImGui::Begin(boardTitle, &boardOpen))
    {
        access.panel(Control::board);
#if defined(_WIN32)
        if (workspacePath && project)
        {
            if (project->view() || !project->busy())
            {
                drawProjectChooser();
            }
            if (project->configured() && !nextProject && !archive.busy())
            {
                drawLiveBoard();
            }
            ImGui::End();
            return;
        }
#endif
        ImGui::TextUnformatted("원형 PCB 표시 예제");
        ImGui::SameLine();
        if (ImGui::SmallButton("보기 초기화"))
        {
            activate(Control::resetBoard);
        }
        focusItem(Control::resetBoard);
        access.item(Control::resetBoard, Control::board);
        const ImVec2 origin = ImGui::GetCursorScreenPos();
        const ImVec2 available = ImGui::GetContentRegionAvail();
        if (available.x >= 24.0f && available.y >= 24.0f)
        {
            ImGui::InvisibleButton("###pcb-canvas", available, ImGuiButtonFlags_MouseButtonLeft);
            const ImGuiIO& io = ImGui::GetIO();
            if (ImGui::IsItemHovered() && io.MouseWheel != 0.0f)
            {
                zoom = std::clamp(zoom * std::pow(1.15f, io.MouseWheel), 0.35f, 6.0f);
            }
            if (ImGui::IsItemActive() && ImGui::IsMouseDragging(ImGuiMouseButton_Left))
            {
                pan.x += io.MouseDelta.x;
                pan.y += io.MouseDelta.y;
            }
            const ImVec2 end(origin.x + available.x, origin.y + available.y);
            const ImVec2 center(origin.x + 0.5f * available.x + pan.x, origin.y + 0.5f * available.y + pan.y);
            const float radius = 0.41f * std::min(available.x, available.y) * zoom;
            ImDrawList* draw = ImGui::GetWindowDrawList();
            draw->PushClipRect(origin, end, true);
            draw->AddRectFilled(origin, end, IM_COL32(17, 26, 35, 255));
            const float grid = 24.0f;
            for (float x = origin.x + grid; x < end.x; x += grid)
            {
                draw->AddLine({x, origin.y}, {x, end.y}, IM_COL32(36, 50, 63, 255));
            }
            for (float y = origin.y + grid; y < end.y; y += grid)
            {
                draw->AddLine({origin.x, y}, {end.x, y}, IM_COL32(36, 50, 63, 255));
            }
            draw->AddCircleFilled(center, radius, IM_COL32(24, 73, 71, 255), 96);
            draw->AddCircle(center, radius, IM_COL32(95, 199, 181, 255), 96, 1.5f);
            draw->PathArcTo(center, radius * 0.69f, -0.82f * std::numbers::pi_v<float>,
                0.62f * std::numbers::pi_v<float>, 64);
            draw->PathStroke(IM_COL32(244, 165, 80, 255), ImDrawFlags_None, std::max(2.0f, 0.08f * radius));
            draw->AddLine({center.x, center.y + radius}, {center.x, center.y + 0.30f * radius},
                IM_COL32(244, 165, 80, 255), std::max(2.0f, 0.045f * radius));
            draw->AddCircleFilled({center.x, center.y + 0.30f * radius}, std::max(2.0f, 0.06f * radius),
                IM_COL32(255, 218, 142, 255));
            draw->PopClipRect();
            boardDrawn = true;
        }
    }
    ImGui::End();
}

#if defined(_WIN32)
bool Shell::canSwitchProject() const
{
    return !renameOpen && !project->target().dirty() && !project->literature().dirty() && !project->setup().dirty() &&
        !nextProject && !archive.busy() && !manufacturing.active() && !rfDelivery.valid() && project->canSwitch();
}

/** @brief 이전 프로젝트가 저장된 상태에서만 같은 서비스로 다른 프로젝트를 요청한다. */
void Shell::submitProject()
{
    if (!serviceReady || !canSwitchProject() || projectName.front() == '\0')
    {
        return;
    }
    const std::string name(projectName.data());
    const std::string path = "projects/" + name;
    nextProject = std::make_unique<PrototypeProject>(path.c_str(), workspacePath, createProject ? name : std::string{});
    chooserStatus.clear();
}

/** @brief 다음 프로젝트의 개정과 장면이 확인된 뒤 현재 프로젝트를 한 번에 교체한다. */
void Shell::updateProjects(SDL_Window* window, std::unique_ptr<PrototypeProject>& current, PrototypeService& service)
{
    serviceReady = service.state() == PrototypeService::State::connected;
    if (archive.busy())
    {
        archive.update(window, service);
        return;
    }
    if (serviceReady && project->view() && project->path() != recordedProject)
    {
        recordedProject = project->path();
        recent.remember(recordedProject);
        recentIndex = 0;
    }
    if (!nextProject)
    {
        project->update(service);
        return;
    }
    nextProject->update(service);
    if (nextProject->view())
    {
        current = std::move(nextProject);
        project = current.get();
        chooserOpen = createProject = recoveryOpen = endpointOpen = false;
        endpoint = {};
        recoveryIndex = 0;
        evidenceOpen = targetOpen = targetRemove = templateOpen = setupOpen = false;
        templatePanel = {};
        setupPanel = {};
        targetPage = PrototypeTarget::Page::band;
        targetChange = 0;
        evidencePage = EvidencePage::records;
        evidenceIndex = evidenceValue = 0;
        modelOpen = analysisOpen = resultHistoryOpen = exchangeOpen = rfExportOpen = false;
        sectionOpen = false;
        sectionModel.clear();
        model.setScene({});
        rfFormatIndex = 0;
        rfDeliveryStatus.clear();
        zoom = 1.0f;
        pan = {};
    }
    else if (!nextProject->busy())
    {
        chooserStatus = nextProject->message();
        nextProject.reset();
    }
}

void Shell::setProjectName(std::string_view value)
{
    if (nextProject || value.size() >= projectName.size())
    {
        return;
    }
    projectName.fill('\0');
    std::copy(value.begin(), value.end(), projectName.begin());
    if (auto* field = ImGui::GetInputTextState(projectNameId))
    {
        field->ReloadUserBufAndMoveToEnd();
    }
}

void Shell::drawProjectChooser()
{
    if (project->view() || !chooserOpen)
    {
        panelButton(Control::showProjectChooser, "프로젝트 선택", !nextProject, chooserOpen);
    }
    if (!chooserOpen)
    {
        return;
    }
    if (!serviceReady)
    {
        ImGui::TextUnformatted("프로젝트를 열려면 Python 서비스에 연결해야 합니다.");
        return;
    }
    const bool ready = canSwitchProject();
    if (!recent.paths().empty())
    {
        panelButton(Control::recentPrevious, "이전 최근 프로젝트", ready && recentIndex > 0);
        ImGui::SameLine();
        panelButton(Control::recentNext, "다음", ready && recentIndex + 1 < recent.paths().size());
        ImGui::SameLine();
        panelButton(Control::recentOpen, "최근 프로젝트 열기", ready);
        const auto& path = recent.paths()[recentIndex];
        ImGui::TextWrapped("%s", path.c_str());
        access.text(Control::recentPath, Control::board, path);
    }
    panelButton(Control::createProjectMode, "새 프로젝트", !nextProject, createProject);
    ImGui::AlignTextToFramePadding();
    ImGui::TextUnformatted("projects/");
    ImGui::SameLine();
    ImGui::SetNextItemWidth(ImGui::GetFontSize() * 17.0f);
    ImGui::BeginDisabled(!ready);
    if (requestedFocus == Control::projectName)
    {
        ImGui::SetKeyboardFocusHere();
    }
    const bool enter = ImGui::InputTextWithHint("##project-name", "프로젝트 폴더 이름",
        projectName.data(), projectName.size(), ImGuiInputTextFlags_EnterReturnsTrue);
    projectNameId = ImGui::GetItemID();
    projectTextActive = ImGui::IsItemActive();
    projectTextWindow = windowId(ImGui::GetWindowViewport());
    focusItem(Control::projectName);
    access.item(Control::projectName, Control::board, ready, false, nullptr, projectName.data());
    ImGui::EndDisabled();
    ImGui::SameLine();
    panelButton(Control::submitProject, createProject ? "프로젝트 만들기" : "프로젝트 열기",
        ready && projectName.front() != '\0');
    if (enter)
    {
        submitProject();
    }
    if (projectTextActive && !preedit.empty() && preeditWindow == projectTextWindow)
    {
        ImGui::Text("조합 중  %s", preedit.c_str());
    }
    panelButton(Control::archiveToggle, "보존 묶음 복원", !archive.busy(), archiveOpen);
    if (archiveOpen)
    {
        drawArchive();
    }
    const char* status = chooserStatus.c_str();
    if (nextProject)
    {
        status = createProject ? "새 프로젝트를 만드는 중" : "프로젝트를 여는 중";
    }
    else if (auto* view = project->view(); view && view->revision != view->savedRevision)
    {
        status = "현재 개정을 저장한 뒤 다른 프로젝트를 선택하세요.";
    }
    else if (!ready)
    {
        status = "현재 프로젝트 작업이 끝나면 열 수 있습니다.";
    }
    if (*status)
    {
        ImGui::TextWrapped("%s", status);
        access.text(Control::projectChooserStatus, Control::board, status);
    }
}

/** @brief 목적지, 개정과 누락 원문을 확인한 뒤 별도 승인으로 복원한다. */
void Shell::drawArchive()
{
    const bool ready = serviceReady && canSwitchProject();
    panelButton(Control::archivePick, "보존 ZIP 검토", ready && archive.canChoose());
    ImGui::SameLine();
    panelButton(Control::archiveApply, "승인 후 복원", ready && archive.canApprove());
    ImGui::SameLine();
    panelButton(Control::archiveCancel, "복원 검토 취소", archive.canCancel());
    const auto& review = archive.review();
    if (review.is_object())
    {
        const auto summary = review.at("path").get<std::string>() + " | 저장본 " +
            review.at("saved_revision").get<std::string>() + " | 복원 개정 " + review.at("revision_id").get<std::string>() +
            " | 파일 " + std::to_string(review.at("files").get<std::size_t>()) +
            "개 | 누락 또는 제외 " + std::to_string(review.at("missing_count").get<std::size_t>()) + "개";
        ImGui::TextWrapped("%s", summary.c_str());
        access.text(Control::archiveReview, Control::board, summary);
        if (ImGui::IsItemHovered())
        {
            ImGui::BeginTooltip();
            ImGui::Text("원문 SHA-256 %s", review.at("archive_sha256").get_ref<const std::string&>().c_str());
            for (const auto& omission : review.at("omitted_preview"))
            {
                ImGui::TextWrapped("%s | %s", omission.at("reference").at("uri").get_ref<const std::string&>().c_str(),
                    omission.at("reason").get_ref<const std::string&>().c_str());
            }
            ImGui::EndTooltip();
        }
    }
    if (!archive.restoredPath().empty())
    {
        panelButton(Control::archiveOpen, "복원한 프로젝트 열기", ready);
    }
    if (!archive.status().empty())
    {
        ImGui::TextWrapped("%s", archive.status().c_str());
        access.text(Control::archiveStatus, Control::board, archive.status());
    }
}

/** @brief 정상 저장본과 영속 편집 개정의 변경 값만 읽기 전용으로 표시한다. */
void Shell::drawRecovery()
{
    panelButton(Control::readRecovery, "비교 다시 읽기", project->writable());
    const auto& message = project->recoveryStatus();
    if (!message.empty())
    {
        ImGui::TextWrapped("%s", message.c_str());
        access.text(Control::recoverySummary, Control::board, message);
        return;
    }
    const auto& data = project->recovery();
    if (!data.is_object())
    {
        return;
    }
    const auto saved = data.at("saved_revision").get<std::string>();
    const auto current = data.at("revision_id").get<std::string>();
    const auto& details = data.at("recovery_details");
    const auto& rows = details.at("rows");
    const auto summary = "저장본 " + saved.substr(0, 12) + " | 현재 개정 " + current.substr(0, 12) +
        " | 변경 " + std::to_string(rows.size()) + (details.at("has_more") == true ? "건 이상" : "건");
    ImGui::TextWrapped("%s", summary.c_str());
    access.text(Control::recoverySummary, Control::board, summary);
    if (ImGui::IsItemHovered())
    {
        ImGui::SetTooltip("저장본 %s\n현재 개정 %s", saved.c_str(), current.c_str());
    }
    if (rows.empty())
    {
        return;
    }
    if (recoveryIndex >= rows.size())
    {
        recoveryIndex = 0;
    }
    panelButton(Control::priorRecoveryField, "이전 변경", recoveryIndex > 0);
    ImGui::SameLine();
    panelButton(Control::nextRecoveryField, "다음 변경", recoveryIndex + 1 < rows.size());
    const auto& row = rows.at(recoveryIndex);
    const std::array fields{
        std::pair{Control::recoveryField, std::to_string(recoveryIndex + 1) + " / " + std::to_string(rows.size()) + " | " +
            row.at(0).get<std::string>() + " | " + row.at(1).get<std::string>() + " | " + row.at(2).get<std::string>()},
        std::pair{Control::recoveryBefore, "저장본 " + row.at(3).get<std::string>()},
        std::pair{Control::recoveryAfter, "현재 개정 " + row.at(4).get<std::string>()}
    };
    for (const auto& [control, text] : fields)
    {
        ImGui::TextWrapped("%s", text.c_str());
        access.text(control, Control::board, text);
    }
}

void Shell::moveEvidence(Control control)
{
    const auto& evidence = project->evidence();
    if (!evidence)
    {
        return;
    }
    if (control == Control::evidencePreviousValue || control == Control::evidenceNextValue)
    {
        if (evidencePage == EvidencePage::records && evidenceIndex < evidence->records.size())
        {
            const auto size = evidence->records[evidenceIndex].values.size();
            if (control == Control::evidencePreviousValue && evidenceValue > 0)
            {
                --evidenceValue;
            }
            else if (control == Control::evidenceNextValue && evidenceValue + 1 < size)
            {
                ++evidenceValue;
            }
        }
        return;
    }
    const auto size = evidencePage == EvidencePage::history ? evidence->changes.size() : evidence->records.size();
    if (control == Control::evidencePrevious && evidenceIndex > 0)
    {
        --evidenceIndex;
    }
    else if (control == Control::evidenceNext && evidenceIndex + 1 < size)
    {
        ++evidenceIndex;
    }
    evidenceValue = 0;
}

/** @brief 현재 개정의 문헌, 채택 값, 가정과 적용 이력을 읽기 전용으로 탐색한다. */
void Shell::drawEvidence()
{
    const auto& evidence = project->evidence();
    panelButton(Control::evidenceReload, "출처 다시 읽기", project->view() && project->writable());
    ImGui::SameLine();
    panelButton(Control::evidenceRecords, "채택 이력", true, evidencePage == EvidencePage::records);
    ImGui::SameLine();
    panelButton(Control::evidenceAssumptions, "가정과 생략", true, evidencePage == EvidencePage::assumptions);
    ImGui::SameLine();
    panelButton(Control::evidenceHistory, "변경 이력", true, evidencePage == EvidencePage::history);
    const auto display = [&](Control control, const std::string& value)
    {
        ImGui::TextWrapped("%s", value.c_str());
        access.text(control, Control::board, value);
    };
    if (!project->recoveryStatus().empty())
    {
        display(Control::evidenceStatus, project->recoveryStatus());
    }
    if (!evidence)
    {
        evidenceIndex = evidenceValue = 0;
        return;
    }
    const bool changes = evidencePage == EvidencePage::history;
    const auto size = changes ? evidence->changes.size() : evidence->records.size();
    if (evidenceIndex >= size)
    {
        evidenceIndex = evidenceValue = 0;
    }
    if (!size)
    {
        display(Control::evidenceSummary, changes ? "표시할 변경 이력이 없습니다." : "표시할 채택 기록이 없습니다.");
        return;
    }
    const auto page = std::to_string(evidenceIndex + 1) + " / " + std::to_string(size);
    display(Control::evidenceSummary, changes ? page + "건 표시 / 전체 " + std::to_string(evidence->changeCount) +
        "건 / 다시 실행 가능 " + std::to_string(evidence->redoCount) + "건" : page + " 기록");
    panelButton(Control::evidencePrevious, "이전 기록", evidenceIndex > 0);
    ImGui::SameLine();
    panelButton(Control::evidenceNext, "다음 기록", evidenceIndex + 1 < size);
    if (changes)
    {
        const auto& row = evidence->changes[evidenceIndex];
        display(Control::evidenceTitle, row.target.empty() ? row.command : row.target + " / " + row.command);
        display(Control::evidenceSource, "변경 전 " + row.before + "\n변경 후 " + row.after +
            (row.targetId.empty() ? "" : "\n대상 ID " + row.targetId));
        display(Control::evidenceValues, "접수 시각 " + (row.time.empty() ? "미기록" : row.time) +
            "\n변경 사유 " + (row.reason.empty() ? "미기록" : row.reason));
        return;
    }
    const auto& row = evidence->records[evidenceIndex];
    display(Control::evidenceTitle, row.label);
    if (evidencePage == EvidencePage::assumptions)
    {
        display(Control::evidenceSource, row.assumptions.empty() ? "기록된 가정과 생략이 없습니다." : row.assumptions);
        return;
    }
    display(Control::evidenceSource, row.source.empty() ? "기록된 원본 출처가 없습니다." : row.source);
    if (!row.values.empty())
    {
        evidenceValue = std::min(evidenceValue, row.values.size() - 1);
        panelButton(Control::evidencePreviousValue, "이전 값", evidenceValue > 0);
        ImGui::SameLine();
        panelButton(Control::evidenceNextValue, "다음 값", evidenceValue + 1 < row.values.size());
        const auto& values = row.values[evidenceValue];
        display(Control::evidenceValues, std::to_string(evidenceValue + 1) + " / " + std::to_string(row.values.size()) +
            " " + values[0] + "\n원본 자료 " + values[1] + "\n채택 시 " + values[2] + "\n현재 값 " + values[3]);
    }
}

void Shell::targetAction(Control control)
{
    auto& target = project->target();
    if (control == Control::targetToggle)
    {
        if (project->view() && !target.dirty() && !project->busy())
        {
            targetOpen = !targetOpen;
            targetRemove = false;
        }
        return;
    }
    if (!targetOpen)
    {
        return;
    }
    switch (control)
    {
        case Control::targetNew:
            project->readTarget({});
            targetRemove = false;
            break;
        case Control::targetBand: targetPage = PrototypeTarget::Page::band; break;
        case Control::targetCriteria: targetPage = PrototypeTarget::Page::criteria; break;
        case Control::targetSources:
            targetPage = PrototypeTarget::Page::sources;
            targetChange = 0;
            if (!project->targetEvidence())
            {
                project->readTargetEvidence();
            }
            break;
        case Control::targetApply:
        case Control::targetApplyRemoval:
            if (targetRemove == (control == Control::targetApplyRemoval))
            {
                project->applyTarget(targetRemove);
                targetRemove = false;
            }
            break;
        case Control::targetRemove:
            if (project->writable() && !project->targetId().empty())
            {
                targetRemove = !targetRemove;
            }
            break;
        case Control::targetDiscard:
            if (!project->busy())
            {
                target.discard();
                targetRemove = false;
                ++targetInputGeneration;
            }
            break;
        case Control::targetRead:
            if (targetPage == PrototypeTarget::Page::sources && target.loaded)
            {
                project->readTargetEvidence();
            }
            else
            {
                project->readTarget(project->targetId(), project->targetPreset());
            }
            break;
        case Control::targetPrevChange:
            if (targetChange)
            {
                --targetChange;
            }
            break;
        case Control::targetNextChange:
            if (const auto& evidence = project->targetEvidence(); evidence && targetChange + 1 < evidence->changes.size())
            {
                ++targetChange;
            }
            break;
        default: break;
    }
}

/** @brief 자동화가 요청한 값도 현재 탭의 활성 입력에만 반영한다. */
void Shell::setTargetText(Control control, const std::string& value)
{
    if (!targetOpen || !project->writable() || !project->target().loaded)
    {
        return;
    }
    auto& target = project->target();
    const auto index = static_cast<std::size_t>(control) - static_cast<std::size_t>(Control::targetName);
    if (control == Control::targetReason)
    {
        target.reason = value;
    }
    else
    {
        const auto field = std::ranges::find(target.fields, targetFieldKeys.at(index), &PrototypeTarget::Field::key);
        if (field == target.fields.end() || field->page != targetPage || targetRemove || !target.available(*field))
        {
            return;
        }
        field->draft = value;
    }
    if (auto* input = ImGui::GetInputTextState(targetInputIds.at(index)))
    {
        input->ReloadUserBufAndMoveToEnd();
    }
}

void Shell::drawTargetSources()
{
    const auto& target = project->target();
    const auto& evidence = project->targetEvidence();
    if (evidence && !evidence->changes.empty())
    {
        targetChange = std::min(targetChange, evidence->changes.size() - 1);
        const auto& row = evidence->changes[targetChange];
        panelButton(Control::targetPrevChange, "이전 변경", targetChange > 0);
        ImGui::SameLine();
        panelButton(Control::targetNextChange, "다음 변경", targetChange + 1 < evidence->changes.size());
        const auto text = std::to_string(targetChange + 1) + " / " + std::to_string(evidence->changes.size()) +
            " 표시, 전체 " + std::to_string(evidence->changeCount) + "건\n변경 전 " + row.before +
            "\n변경 후 " + row.after + "\n접수 시각 " + row.time + "\n변경 사유 " + row.reason;
        ImGui::TextWrapped("%s", text.c_str());
        access.text(Control::targetHistory, Control::board, text);
    }
    else if (project->targetId().empty())
    {
        ImGui::TextUnformatted("목표 적용 후 변경 이력을 확인할 수 있습니다.");
    }
    else if (evidence)
    {
        ImGui::TextUnformatted("표시할 목표 변경 이력이 없습니다.");
    }
    for (const auto& field : target.fields)
    {
        if (field.readonly && !field.original.empty())
        {
            ImGui::SeparatorText(field.label.c_str());
            ImGui::TextWrapped("%s", field.original.c_str());
        }
    }
}

/** @brief 대역, 표본과 성능 기준의 초안을 해당 서비스 입력 형식으로 표시한다. */
void Shell::drawTarget()
{
    using Page = PrototypeTarget::Page;
    auto& target = project->target();
    if (!target.loaded && project->writable() && project->targetStatus().empty())
    {
        project->readTarget(project->targetId(), project->targetPreset());
    }
    const bool idle = project->writable();
    const bool editable = idle && target.loaded;
    panelButton(Control::targetNew, "새 목표", idle && !target.dirty());
    ImGui::SameLine();
    panelButton(Control::targetRead, "목표 다시 읽기",
        idle && (targetPage != Page::sources ? !target.dirty() : !project->targetId().empty()));
    if (target.loaded)
    {
        const auto selected = std::ranges::find(target.items, project->targetId(), &PrototypeTarget::Option::value);
        const auto preset = std::ranges::find(target.presets, project->targetPreset(), &PrototypeTarget::Preset::id);
        const char* label = selected != target.items.end() ? selected->label.c_str() :
            preset != target.presets.end() ? preset->name.c_str() : "새 목표";
        ImGui::BeginDisabled(!editable || target.dirty());
        if (ImGui::BeginCombo("목표 목록", label))
        {
            for (const auto& item : target.items)
            {
                ImGui::PushID(item.value.c_str());
                if (ImGui::Selectable(item.label.c_str(), item.value == project->targetId()))
                {
                    targetRemove = false;
                    project->readTarget(item.value);
                }
                ImGui::PopID();
            }
            ImGui::EndCombo();
        }
        if (ImGui::BeginCombo("대역 프리셋", preset != target.presets.end() ? preset->name.c_str() : "선택"))
        {
            for (const auto& item : target.presets)
            {
                ImGui::PushID(item.id.c_str());
                const auto label = item.name + " / " + item.version + " / " + item.scope;
                if (ImGui::Selectable(label.c_str(), item.id == project->targetPreset()))
                {
                    targetRemove = false;
                    project->readTarget({}, item.id);
                }
                ImGui::PopID();
            }
            ImGui::EndCombo();
        }
        ImGui::EndDisabled();
    }
    panelButton(Control::targetBand, "대역과 표본", true, targetPage == Page::band);
    ImGui::SameLine();
    panelButton(Control::targetCriteria, "성능 기준", true, targetPage == Page::criteria);
    ImGui::SameLine();
    panelButton(Control::targetSources, "출처와 이력", true, targetPage == Page::sources);
    const auto& status = project->targetStatus().empty() ? project->message() : project->targetStatus();
    if (!status.empty())
    {
        ImGui::TextWrapped("%s", status.c_str());
        access.text(Control::targetStatus, Control::board, status);
    }
    if (!target.loaded)
    {
        return;
    }
    ImGui::TextWrapped("%s", target.summary.c_str());
    access.text(Control::targetSummary, Control::board, target.summary);
    const auto drawText = [&](Control id, const char* caption, std::string& value, bool enabled, bool multiline)
    {
        ImGui::BeginDisabled(!enabled);
        if (requestedFocus == id && id != Control::root)
        {
            ImGui::SetKeyboardFocusHere();
        }
        if (multiline)
        {
            ImGui::InputTextMultiline(caption, &value, ImVec2(ImGui::CalcItemWidth(), ImGui::GetTextLineHeight() * 5.0f));
        }
        else
        {
            ImGui::InputText(caption, &value);
        }
        const bool active = ImGui::IsItemActive();
        if (active)
        {
            projectTextActive = true;
            projectTextWindow = windowId(ImGui::GetWindowViewport());
        }
        if (id != Control::root)
        {
            const auto index = static_cast<std::size_t>(id) - static_cast<std::size_t>(Control::targetName);
            targetInputIds.at(index) = ImGui::GetItemID();
            focusItem(id);
            access.item(id, Control::board, enabled, false, nullptr, value);
        }
        ImGui::EndDisabled();
        if (active && !preedit.empty() && preeditWindow == projectTextWindow)
        {
            ImGui::Text("조합 중  %s", preedit.c_str());
        }
    };
    ImGui::PushID(targetInputGeneration);
    drawText(Control::targetReason, "변경 사유", target.reason, editable, false);
    panelButton(targetRemove ? Control::targetApplyRemoval : Control::targetApply,
        targetRemove ? "삭제 적용" : "목표 적용", editable && !target.reason.empty() &&
        (targetRemove || !project->targetPreset().empty() || target.hasChanges()));
    ImGui::SameLine();
    panelButton(Control::targetRemove, "목표 삭제", editable && !project->targetId().empty(), targetRemove);
    ImGui::SameLine();
    panelButton(Control::targetDiscard, "초안 취소", !project->busy() && (target.dirty() || targetRemove));
    if (targetRemove)
    {
        ImGui::TextUnformatted("선택 목표를 삭제하려면 사유를 입력하고 삭제 적용을 누르세요.");
    }
    const auto height = std::max(ImGui::GetContentRegionAvail().y, ImGui::GetTextLineHeightWithSpacing() * 8.0f);
    if (ImGui::BeginChild("###target-fields", {0.0f, height}, ImGuiChildFlags_Borders))
    {
        if (targetPage == Page::sources)
        {
            drawTargetSources();
        }
        else
        {
            for (auto& field : target.fields)
            {
                if (field.page != targetPage)
                {
                    continue;
                }
                ImGui::PushID(field.key.c_str());
                const bool enabled = editable && !targetRemove && target.available(field);
                if (field.choices.empty())
                {
                    const auto found = std::ranges::find(targetFieldKeys, field.key);
                    const auto index = static_cast<int>(found - targetFieldKeys.begin());
                    const auto id = found == targetFieldKeys.end() ? Control::root :
                        static_cast<Control>(static_cast<int>(Control::targetName) + index);
                    drawText(id, field.label.c_str(), field.draft, enabled, field.multiline);
                }
                else
                {
                    ImGui::BeginDisabled(!enabled);
                    const auto choice = std::ranges::find(field.choices, field.draft, &PrototypeTarget::Option::value);
                    if (ImGui::BeginCombo(field.label.c_str(), choice == field.choices.end() ? "" : choice->label.c_str()))
                    {
                        for (const auto& option : field.choices)
                        {
                            ImGui::PushID(option.value.c_str());
                            if (ImGui::Selectable(option.label.c_str(), option.value == field.draft))
                            {
                                field.draft = option.value;
                            }
                            ImGui::PopID();
                        }
                        ImGui::EndCombo();
                    }
                    ImGui::EndDisabled();
                }
                if (!field.help.empty() && ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled))
                {
                    ImGui::SetTooltip("%s", field.help.c_str());
                }
                ImGui::PopID();
            }
        }
    }
    ImGui::EndChild();
    ImGui::PopID();
}

/** @brief 선택한 경로의 두 끝점을 읽고 미리보기, 스냅 및 명시 적용을 제공한다. */
void Shell::drawEndpoint()
{
    auto* view = project->view();
    const auto* shape = view ? view->canvas.Find(view->selection) : nullptr;
    const bool path = shape && shape->selectionKind == "geometry" && CanvasPrecision::HasEndpoints(*shape);
    panelButton(Control::endpointToggle, "끝점 편집", endpointOpen || path, endpointOpen);
    if (!endpointOpen || !path)
    {
        endpoint.picking = false;
        return;
    }
    if (endpoint.id != shape->id || endpoint.revision != view->revision)
    {
        endpoint.id = shape->id;
        endpoint.revision = view->revision;
        endpoint.point = CanvasPrecision::At(*shape, endpoint.side);
        endpoint.picking = false;
        endpoint.snapLabel.clear();
    }
    const auto start = CanvasPrecision::Endpoint::Start;
    const auto end = CanvasPrecision::Endpoint::End;
    const bool editable = project->canMoveEndpoint(endpoint.side);
    panelButton(Control::endpointStart, "시작점", true, endpoint.side == start);
    ImGui::SameLine();
    panelButton(Control::endpointEnd, "끝점", true, endpoint.side == end);
    ImGui::SameLine();
    panelButton(Control::endpointSnap, "스냅", editable, endpoint.snap);
    ImGui::SameLine();
    panelButton(Control::endpointPick, "캔버스에서 지정", editable, endpoint.picking);
    if (endpoint.picking)
    {
        ImGui::TextUnformatted("캔버스에서 위치를 선택하세요. Esc로 취소합니다.");
    }
    if (!editable)
    {
        ImGui::TextUnformatted("현재 작업 또는 원본 구속을 확인하세요.");
    }
    const auto setCoordinate = [&](Control control, const char* label, double& value)
    {
        ImGui::SetNextItemWidth(115.0f);
        ImGui::BeginDisabled(!editable);
        if (requestedFocus == control)
        {
            ImGui::SetKeyboardFocusHere();
        }
        if (ImGui::InputDouble(label, &value, 0.0, 0.0, "%.12g"))
        {
            endpoint.snapLabel.clear();
        }
        if (ImGui::IsItemActive())
        {
            projectTextActive = true;
            projectTextWindow = windowId(ImGui::GetWindowViewport());
        }
        focusItem(control);
        char number[40];
        std::snprintf(number, sizeof(number), "%.17g", value);
        access.item(control, Control::board, editable, false, nullptr, number);
        ImGui::EndDisabled();
    };
    setCoordinate(Control::endpointX, "X (mm)", endpoint.point.x);
    ImGui::SameLine();
    setCoordinate(Control::endpointY, "Y (mm)", endpoint.point.y);
    auto preview = *shape;
    const bool changed = !CanvasPrecision::EndpointUnchanged(*shape, endpoint.side, endpoint.point) &&
        CanvasPrecision::Preview(preview, endpoint.side, endpoint.point);
    panelButton(Control::endpointApply, "끝점 적용", editable && changed);
    ImGui::SameLine();
    panelButton(Control::endpointReset, "좌표 되돌리기", editable);
    if (!endpoint.snapLabel.empty())
    {
        ImGui::SameLine();
        ImGui::TextUnformatted(endpoint.snapLabel.c_str());
        access.text(Control::endpointSnapStatus, Control::board, endpoint.snapLabel);
    }
}

void Shell::selectEndpoint(CanvasPrecision::Endpoint side)
{
    if (auto* view = project->view())
    {
        if (const auto* shape = view->canvas.Find(view->selection); shape && CanvasPrecision::HasEndpoints(*shape))
        {
            endpoint.id = shape->id;
            endpoint.revision = view->revision;
            endpoint.side = side;
            endpoint.point = CanvasPrecision::At(*shape, side);
            endpoint.picking = false;
            endpoint.snapLabel.clear();
        }
    }
}

void Shell::setRenameName(std::string_view value)
{
    if (value.size() >= renameName.size())
    {
        return;
    }
    renameName.fill('\0');
    std::copy(value.begin(), value.end(), renameName.begin());
    if (auto* field = ImGui::GetInputTextState(renameNameId))
    {
        field->ReloadUserBufAndMoveToEnd();
    }
}

void Shell::closeRename()
{
    renameOpen = false;
    requestedFocus = Control::renameToggle;
}

/** @brief 이름 초안을 편집하고 기존 이름, 오류 및 적용 여부를 같은 대화 상자에 표시한다. */
void Shell::drawRename()
{
    constexpr char title[] = "이름 바꾸기###rename-object";
    if (renameOpen && !ImGui::IsPopupOpen(title))
    {
        ImGui::OpenPopup(title);
    }
    ImGui::SetNextWindowSize(ImVec2(ImGui::GetFontSize() * 27.0f, 0.0f), ImGuiCond_Appearing);
    if (!ImGui::BeginPopupModal(title, nullptr, ImGuiWindowFlags_AlwaysAutoResize))
    {
        return;
    }
    const auto* original = project->renameName();
    if (!renameOpen || (renameLoaded && !original && !project->busy() && project->message().empty()))
    {
        closeRename();
        ImGui::CloseCurrentPopup();
        ImGui::EndPopup();
        return;
    }
    access.panel(Control::renameDialog);
    const auto target = "대상: " + renameTarget;
    ImGui::TextWrapped("%s", target.c_str());
    access.text(Control::renameTarget, Control::renameDialog, target);
    if (original && !renameLoaded)
    {
        setRenameName(*original);
        renameLoaded = true;
        requestedFocus = Control::renameName;
    }
    const bool editable = original && project->writable();
    ImGui::SetNextItemWidth(-ImGui::GetFontSize());
    ImGui::BeginDisabled(!editable);
    if (requestedFocus == Control::renameName)
    {
        ImGui::SetKeyboardFocusHere();
    }
    const bool enter = ImGui::InputTextWithHint("##rename-name", "새 표시 이름", renameName.data(),
        renameName.size(), ImGuiInputTextFlags_AutoSelectAll | ImGuiInputTextFlags_EnterReturnsTrue);
    renameNameId = ImGui::GetItemID();
    const bool active = ImGui::IsItemActive();
    if (active)
    {
        projectTextActive = true;
        projectTextWindow = windowId(ImGui::GetWindowViewport());
    }
    focusItem(Control::renameName);
    access.item(Control::renameName, Control::renameDialog, editable, false, nullptr, renameName.data());
    ImGui::EndDisabled();
    if (active && !preedit.empty() && preeditWindow == projectTextWindow)
    {
        ImGui::Text("조합 중  %s", preedit.c_str());
    }
    ImGui::TextWrapped("같은 종류의 객체에는 서로 다른 이름을 사용하세요.");
    ImGui::TextWrapped("형상과 물리값, 연결, 원본 출처와 과거 결과는 그대로 유지됩니다.");
    panelButton(Control::renameDetails, "고급 정보", true, renameDetails, Control::renameDialog);
    if (renameDetails)
    {
        const auto id = "고유 ID: " + renamedObjectId;
        ImGui::TextWrapped("%s", id.c_str());
        access.text(Control::renameId, Control::renameDialog, id);
        panelButton(Control::renameCopy, "고유 ID 복사", true, false, Control::renameDialog);
    }
    const auto& error = project->renameStatus();
    const auto& status = project->message();
    const char* feedback = !error.empty() ? error.c_str() : !status.empty() ? status.c_str() :
        !original && project->busy() ? "현재 이름을 읽는 중" : nullptr;
    if (feedback)
    {
        ImGui::TextWrapped("%s", feedback);
        access.text(Control::renameStatus, Control::renameDialog, feedback);
    }
    panelButton(Control::renameCancel, "취소", !project->busy(), false, Control::renameDialog);
    ImGui::SameLine();
    panelButton(Control::renameApply, "이름 변경", editable && renameName.front() != '\0' && *original != renameName.data(),
        false, Control::renameDialog);
    if (enter)
    {
        activate(Control::renameApply);
    }
    ImGui::EndPopup();
}

/** @brief 실제 프로젝트와 권위 있는 개정, 기판 장면 및 저장 동작을 같은 패널에 제공한다. */
void Shell::drawLiveBoard()
{
    ImGui::TextUnformatted(project->path().c_str());
    ImGui::SameLine();
    panelButton(Control::showRecovery, "저장본 비교", recoveryOpen || (project->view() && project->writable()), recoveryOpen);
    if (recoveryOpen)
    {
        drawRecovery();
    }
    else
    {
        ImGui::SameLine();
    }
    panelButton(Control::targetToggle, "목표 편집", project->view() && !project->target().dirty() && !project->busy(), targetOpen);
    if (targetOpen)
    {
        drawTarget();
        return;
    }
    ImGui::SameLine();
    panelButton(Control::setupToggle, "기판과 설계 규칙", project->view() && !project->busy(), setupOpen);
    if (setupOpen)
    {
        if (setupPanel.draw(*project, access, requestedFocus))
        {
            projectTextActive = true;
            projectTextWindow = windowId(ImGui::GetWindowViewport());
            if (!preedit.empty() && preeditWindow == projectTextWindow)
            {
                ImGui::Text("조합 중  %s", preedit.c_str());
            }
        }
        if (setupPanel.takeJump())
        {
            setupOpen = modelOpen = templateOpen = evidenceOpen = false;
        }
        return;
    }
    ImGui::SameLine();
    panelButton(Control::templateToggle, "문헌 후보", project->view() && !project->busy(), templateOpen);
    if (templateOpen)
    {
        if (templatePanel.draw(*project, access, requestedFocus))
        {
            projectTextActive = true;
            projectTextWindow = windowId(ImGui::GetWindowViewport());
            if (!preedit.empty() && preeditWindow == projectTextWindow)
            {
                ImGui::Text("조합 중  %s", preedit.c_str());
            }
        }
        return;
    }
    ImGui::SameLine();
    panelButton(Control::evidenceToggle, "출처와 변경 이력", evidenceOpen || project->view(), evidenceOpen);
    if (evidenceOpen)
    {
        drawEvidence();
        return;
    }
    panelButton(Control::toggleModel, modelOpen ? "2D 편집" : "3D 형상", project->view() != nullptr, modelOpen);
    ImGui::SameLine();
    panelButton(Control::showExchange, "출력 도구", project->view() != nullptr, exchangeOpen);
    if (exchangeOpen)
    {
        drawExchange();
    }
    else
    {
        ImGui::SameLine();
    }
    if (modelOpen)
    {
        drawLiveModel();
        return;
    }
    panelButton(Control::reloadProject, "다시 열기", project->canReopen());
    ImGui::SameLine();
    auto* view = project->view();
    panelButton(Control::saveProject, "저장", view && project->writable() && view->revision != view->savedRevision);
    ImGui::SameLine();
    panelButton(Control::undoProject, "되돌리기", view && project->writable() && view->canUndo);
    ImGui::SameLine();
    panelButton(Control::resetBoard, "보기 초기화", view != nullptr);
    ImGui::SameLine();
    panelButton(Control::renameToggle, "이름 바꾸기 (F2)", project->canRename());
    drawRename();

    ImGui::AlignTextToFramePadding();
    ImGui::TextUnformatted("도체 이동 (1 mm)");
    const bool movable = project->canTranslate();
    ImGui::SameLine();
    panelButton(Control::moveLeft, "-X", movable);
    ImGui::SameLine();
    panelButton(Control::moveRight, "+X", movable);
    ImGui::SameLine();
    panelButton(Control::moveDown, "-Y", movable);
    ImGui::SameLine();
    panelButton(Control::moveUp, "+Y", movable);
    drawEndpoint();

    if (!project->message().empty())
    {
        ImGui::TextWrapped("%s", project->message().c_str());
    }
    else
    {
        ImGui::Dummy({0.0f, ImGui::GetTextLineHeight()});
    }
    if (view)
    {
        ImGui::Text("저장 개정 %.12s%s", view->savedRevision.c_str(),
            view->revision != view->savedRevision ? "  |  저장되지 않은 변경" : "");
        if (ImGui::IsItemHovered())
        {
            ImGui::SetTooltip("현재 %s\n저장 %s", view->revision.c_str(), view->savedRevision.c_str());
        }
        if (const auto* selected = view->canvas.Find(view->selection))
        {
            ImGui::Text("선택: %s", selected->label.c_str());
            if (ImGui::IsItemHovered())
            {
                ImGui::SetTooltip("%s", selected->id.c_str());
            }
        }
        else
        {
            ImGui::Dummy({0.0f, ImGui::GetTextLineHeight()});
        }
        if (const auto omissions = view->canvas.omissionCount + view->canvas.rangeOmissionCount; omissions)
        {
            ImGui::Text("표시 생략 %zu건", omissions);
        }
        boardDrawn = drawProjectCanvas(*view, zoom, pan, endpointOpen ? &endpoint : nullptr);
    }
}

void Shell::panelButton(Control control, const char* label, bool enabled, bool checked, Control parent)
{
    ImGui::BeginDisabled(!enabled);
    if (ImGui::SmallButton(label))
    {
        activate(control);
    }
    focusItem(control);
    access.item(control, parent, enabled, checked);
    ImGui::EndDisabled();
}

/** @brief 선택한 도면 또는 제조 교환 출력을 검토하고 원본 게시 상태를 표시한다. */
void Shell::drawExchange()
{
    const auto& job = project->exchange();
    const bool ready = project->writable();
    panelButton(Control::priorExchange, "이전 형식", ready && job.canMove(-1));
    ImGui::SameLine();
    panelButton(Control::nextExchange, "다음 형식", ready && job.canMove(1));
    ImGui::SameLine();
    ImGui::TextUnformatted(job.name());
    access.text(Control::exchangeFormat, Control::board, job.name());
    if (const auto* choice = job.footprint())
    {
        if (job.choosingFootprint())
        {
            panelButton(Control::priorFootprint, "이전 풋프린트", ready && job.canMoveFootprint(-1));
            ImGui::SameLine();
            panelButton(Control::nextFootprint, "다음 풋프린트", ready && job.canMoveFootprint(1));
            ImGui::SameLine();
        }
        ImGui::TextUnformatted(choice->name.c_str());
        access.text(Control::exchangeFootprint, Control::board, choice->name);
        if (ImGui::IsItemHovered())
        {
            ImGui::SetTooltip("풋프린트 ID %s", choice->id.c_str());
        }
    }
    if (job.choosingFootprint())
    {
        panelButton(Control::reviewFootprint, "선택 검토", project->canReviewExchange());
    }
    else
    {
        panelButton(Control::reviewExchange, "출력 검토", project->canReviewExchange());
    }
    ImGui::SameLine();
    panelButton(Control::buildExchange, "승인 후 생성", project->canApproveExchange());
    ImGui::SameLine();
    panelButton(Control::cancelExchange, "출력 취소", job.canCancel());
    ImGui::SameLine();
    panelButton(Control::verifyExchange, "재검수", project->canVerifyExchange());
    ImGui::SameLine();
    panelButton(Control::reloadExchange, "기록 다시 읽기", project->canReadExchange());
    if (job.showingBoard())
    {
        const bool available = ready && !job.active() && job.published() && !manufacturing.active();
        panelButton(Control::manufacturingFormat, "제조 형식 변경", !manufacturing.active());
        ImGui::SameLine();
        ImGui::TextUnformatted(manufacturing.format());
        access.text(Control::manufacturingChoice, Control::board, manufacturing.format());
        ImGui::SameLine();
        panelButton(Control::buildManufacturing, "제조 후보 ZIP 저장", available);
        if (!manufacturing.status().empty())
        {
            ImGui::TextWrapped("%s", manufacturing.status().c_str());
            access.text(Control::manufacturingStatus, Control::board, manufacturing.status());
        }
    }

    const auto& info = job.review();
    if (info.is_object())
    {
        const auto& options = info.at("options");
        const auto& omissions = info.at("omissions");
        const auto revision = info.at("revision_id").get<std::string>();
        auto summary = "개정 " + revision.substr(0, 12) + " | 검토 " +
            std::to_string(info.at("pages").size()) + "쪽 | 제외 " + std::to_string(omissions.size()) + "건";
        if (options.contains("sheet"))
        {
            summary += " | " + options.at("sheet").get<std::string>() +
                (options.at("orientation") == "landscape" ? " 가로" : " 세로") +
                " | 축척 " + options.at("scale").dump();
        }
        else if (options.contains("layer_ids"))
        {
            summary += " | 출력 층 " + std::to_string(options.at("layer_ids").size()) + "개";
        }
        ImGui::TextWrapped("%s", summary.c_str());
        access.text(Control::exchangeReview, Control::board, summary);
        if (ImGui::IsItemHovered())
        {
            ImGui::BeginTooltip();
            ImGui::Text("개정 %s", revision.c_str());
            ImGui::Text("검토 SHA-256 %s", info.at("review_hash").get_ref<const std::string&>().c_str());
            for (const auto& item : omissions)
            {
                ImGui::Text("%s: %s", item.at("label").get_ref<const std::string&>().c_str(),
                    item.at("reason_label").get_ref<const std::string&>().c_str());
            }
            ImGui::EndTooltip();
        }
    }
    if (const auto& record = job.published())
    {
        const auto* view = project->view();
        const auto current = view && view->revision == record->revision;
        const auto summary = "게시 개정 " + record->revision.substr(0, 12) +
            (current ? " | 현재 설계" : " | 이전 설계");
        ImGui::Text("%s", summary.c_str());
        access.text(Control::exchangePublication, Control::board, summary);
        if (ImGui::IsItemHovered())
        {
            ImGui::SetTooltip("개정 %s\n%s\n파일 SHA-256 %s\nManifest SHA-256 %s", record->revision.c_str(),
                record->uri.c_str(), record->sha256.c_str(), record->manifest.c_str());
        }
    }
    const std::string status = !job.status().empty() ? job.status() :
        (!project->exchangeReady() ? "생성 및 재검수를 하려면 출력 Python을 연결하세요." : "");
    if (!status.empty())
    {
        ImGui::TextWrapped("%s", status.c_str());
        access.text(Control::exchangeStatus, Control::board, status);
    }
}

/** @brief 검증한 표시 장면으로만 카메라를 그리고 같은 개정의 원본 선택을 연결한다. */
/** @brief 실제 모델 좌표의 축, 위치, 보존 방향을 선택하고 단면을 확정한다. */
void Shell::drawSection(const DisplayMesh::Scene& scene)
{
    if (sectionModel != scene.runId)
    {
        sectionModel = scene.runId;
        sectionOpen = false;
        sectionAxis = 2;
        sectionUpper = true;
        sectionPosition = sectionCenter(scene, sectionAxis);
    }
    const bool ready = !model.sectionPending();
    panelButton(Control::sectionToggle, "단면 도구", ready, sectionOpen);
    if (!sectionOpen)
    {
        return;
    }
    constexpr std::array names{"X", "Y", "Z"};
    panelButton(Control::sectionAxis, "축 변경", ready);
    ImGui::SameLine();
    ImGui::TextUnformatted(names[sectionAxis]);
    access.text(Control::sectionAxisValue, Control::board, names[sectionAxis]);
    ImGui::SameLine();
    panelButton(Control::sectionSide, "큰 좌표 쪽 보존", ready, sectionUpper);
    ImGui::BeginDisabled(!ready);
    ImGui::SetNextItemWidth(143.0f);
    if (requestedFocus == Control::sectionPosition)
    {
        ImGui::SetKeyboardFocusHere();
    }
    ImGui::InputDouble("단면 위치 (mm)", &sectionPosition, 0.0, 0.0, "%.12g");
    if (ImGui::IsItemActive())
    {
        projectTextActive = true;
        projectTextWindow = windowId(ImGui::GetWindowViewport());
    }
    focusItem(Control::sectionPosition);
    char position[48];
    std::snprintf(position, sizeof(position), "%.17g", sectionPosition);
    access.item(Control::sectionPosition, Control::board, ready, false, nullptr, position);
    ImGui::EndDisabled();
    ImGui::SameLine();
    panelButton(Control::sectionApply, "단면 적용", ready && std::isfinite(sectionPosition));
    auto summary = std::string("표시 삼각형 ") + std::to_string(model.visibleTriangles()) + "개";
    if (model.sectionPending())
    {
        summary = "단면을 계산하는 중";
    }
    else if (const auto* plane = model.sectionPlane())
    {
        const auto normal = std::find_if(plane->begin(), plane->begin() + 3, [](double value)
        {
            return value != 0.0;
        });
        const auto axis = static_cast<std::size_t>(normal - plane->begin());
        char applied[89];
        std::snprintf(applied, sizeof(applied), "%s %s %.12g mm | ", names[axis], *normal > 0.0 ? ">=" : "<=",
            sectionCenter(scene, axis) - plane->back() / *normal);
        summary = applied + summary;
    }
    ImGui::TextUnformatted(summary.c_str());
    access.text(Control::sectionStatus, Control::board, summary);
}

void Shell::drawLiveModel()
{
    const auto& cad = project->cad();
    const auto& scene = cad.scene();
    const auto& job = project->cadJob();
    panelButton(Control::reloadModel, "3D 다시 읽기", project->writable() && !cad.loading() && !job.active());
    ImGui::SameLine();
    panelButton(Control::resetBoard, "보기 초기화", scene != nullptr);
    panelButton(Control::buildModel, "3D 생성", project->canStartCad());
    if (!project->cadReady() && ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled))
    {
        ImGui::SetTooltip("--cad-python으로 설치한 CAD 환경을 연결하세요.");
    }
    ImGui::SameLine();
    panelButton(Control::exportStep, "STEP 출력", project->canStartCad());
    ImGui::SameLine();
    panelButton(Control::cancelCad, "CAD 취소", job.canCancel());
    model.setScene(scene);
    if (!job.status().empty())
    {
        ImGui::TextWrapped("%s", job.status().c_str());
    }
    if (const auto& step = job.step())
    {
        ImGui::Text("STEP 개정 %.12s", step->revision.c_str());
        if (ImGui::IsItemHovered())
        {
            ImGui::SetTooltip("작업 영역 파일 %s\nSHA-256 %s", step->uri.c_str(), step->sha256.c_str());
        }
    }
    if (!cad.status().empty())
    {
        ImGui::TextWrapped("%s", cad.status().c_str());
    }
    if (!scene)
    {
        if (cad.status().empty())
        {
            ImGui::TextUnformatted("게시된 3D 형상이 없습니다.");
        }
        return;
    }
    drawSection(*scene);
    auto* view = project->view();
    const bool current = view && view->revision == scene->revisionId;
    ImGui::Text("3D 개정 %.12s  |  %s", scene->revisionId.c_str(),
        current ? "현재 설계" : "이전 설계");
    if (ImGui::IsItemHovered())
    {
        ImGui::SetTooltip("개정 %s\n스냅샷 %s\n실행 %s", scene->revisionId.c_str(),
            scene->snapshotId.c_str(), scene->runId.c_str());
    }
    if (const auto* body = model.selected())
    {
        const std::string& id = body->sources.front();
        const auto* shape = current ? view->canvas.Find(id) : nullptr;
        ImGui::Text("선택: %s", shape && body->sources.size() == 1 ? shape->label.c_str() : body->id.c_str());
        if (ImGui::IsItemHovered())
        {
            ImGui::BeginTooltip();
            for (const auto& source : body->sources)
            {
                ImGui::TextUnformatted(source.c_str());
            }
            ImGui::EndTooltip();
        }
    }
    else
    {
        ImGui::Dummy({0.0f, ImGui::GetTextLineHeight()});
    }

    const auto origin = ImGui::GetCursorScreenPos();
    const auto size = ImGui::GetContentRegionAvail();
    if (size.x < 24.0f || size.y < 24.0f)
    {
        return;
    }
    const bool clicked = ImGui::InvisibleButton("###cad-model", size,
        ImGuiButtonFlags_MouseButtonLeft | ImGuiButtonFlags_MouseButtonMiddle);
    const auto& io = ImGui::GetIO();
    if (ImGui::IsItemHovered() && io.MouseWheel != 0.0f)
    {
        model.zoom(io.MouseWheel);
    }
    if (ImGui::IsItemActive() && ImGui::IsMouseDragging(ImGuiMouseButton_Left))
    {
        model.rotate(io.MouseDelta.x, io.MouseDelta.y);
    }
    if (ImGui::IsItemActive() && ImGui::IsMouseDragging(ImGuiMouseButton_Middle))
    {
        model.pan(io.MouseDelta.x, io.MouseDelta.y, size.y);
    }
    if (clicked && ImGui::IsMouseReleased(ImGuiMouseButton_Left) &&
        !ImGui::IsMouseDragPastThreshold(ImGuiMouseButton_Left))
    {
        model.pick(io.MousePos.x - origin.x, io.MousePos.y - origin.y, size.x, size.y);
        const auto* body = model.selected();
        if (current)
        {
            view->selection.clear();
            if (body && body->sources.size() == 1 && view->canvas.Find(body->sources.front()))
            {
                view->selection = body->sources.front();
            }
        }
    }
    const float maxSize = static_cast<float>(std::min(2048u, bgfx::getCaps()->limits.maxTextureSize));
    const float scale = std::min(ImGui::GetWindowViewport()->DpiScale, maxSize / std::max(size.x, size.y));
    const auto pixelsWide = static_cast<std::uint16_t>(std::max(1.0f, std::round(size.x * scale)));
    const auto pixelsHigh = static_cast<std::uint16_t>(std::max(1.0f, std::round(size.y * scale)));
    model.submit(pixelsWide, pixelsHigh, current ? view->selection : std::string{});
    if (!model.error().empty())
    {
        ImGui::SetCursorScreenPos(origin);
        ImGui::TextUnformatted(model.error().c_str());
        return;
    }
    const bool flip = bgfx::getCaps()->originBottomLeft;
    ImGui::GetWindowDrawList()->AddImage(Renderer::modelTextureId, origin,
        {origin.x + size.x, origin.y + size.y}, {0.0f, flip ? 1.0f : 0.0f},
        {1.0f, flip ? 0.0f : 1.0f});
}
#endif

void Shell::drawResult(bool hasViewports)
{
    if (!resultOpen)
    {
        return;
    }
    if (hasViewports && detachResult)
    {
        ImGuiWindowClass windowClass;
        windowClass.ViewportFlagsOverrideSet = ImGuiViewportFlags_NoAutoMerge;
        ImGui::SetNextWindowClass(&windowClass);
    }
    if (undockNextFrame)
    {
        const ImGuiViewport* main = ImGui::GetMainViewport();
        ImGui::SetNextWindowDockID(0, ImGuiCond_Always);
        ImGui::SetNextWindowPos({main->Pos.x + 48.0f, main->Pos.y + 68.0f}, ImGuiCond_Always);
        ImGui::SetNextWindowSize({640.0f, 385.0f}, ImGuiCond_Always);
        undockNextFrame = false;
    }
    if (requestedFocus == Control::result || requestedFocus == Control::reloadResult ||
        (requestedFocus >= Control::showSolver && requestedFocus <= Control::cancelSolver) ||
        (requestedFocus >= Control::showResultHistory && requestedFocus <= Control::openHistoryResult) ||
        (requestedFocus >= Control::showRfExport && requestedFocus <= Control::saveRfExport) ||
        (requestedFocus >= Control::matrixPriorRow && requestedFocus <= Control::matrixTable))
    {
        ImGui::SetNextWindowFocus();
        if (requestedFocus == Control::result)
        {
            requestedFocus = Control::root;
        }
    }
    if (ImGui::Begin(resultTitle, &resultOpen))
    {
        access.panel(Control::result);
        if (ImGui::IsWindowDocked())
        {
            detachResult = false;
        }
#if defined(_WIN32)
        if (workspacePath && project)
        {
            if (project->view() && !nextProject && !archive.busy())
            {
                drawLiveResult();
            }
            ImGui::End();
            return;
        }
#endif
        ImGui::Text("B0 · S11 · %zu개 표본", b0::magnitudeDb.size());
        if (ImPlot::BeginPlot("###s11", {-1.0f, -1.0f}, ImPlotFlags_NoLegend))
        {
            ImPlot::SetupAxes("주파수 (GHz)", "|S11| (dB)");
            ImPlot::SetupAxesLimits(7.9, 12.1, -4.5, 0.0, ImPlotCond_Once);
            ImPlot::SetNextLineStyle(ImVec4(0.32f, 0.82f, 0.78f, 1.0f), 2.0f);
            ImPlot::SetNextMarkerStyle(ImPlotMarker_Circle, 2.5f);
            ImPlot::PlotLine("S11", b0::frequenciesGhz.data(), b0::magnitudeDb.data(),
                static_cast<int>(b0::magnitudeDb.size()));
            ImPlot::EndPlot();
            plotDrawn = true;
        }
    }
    ImGui::End();
}

#if defined(_WIN32)
/** @brief 현재 프로젝트에서 선택한 완료 실행의 봉인된 S 표본과 출처를 표시한다. */
void Shell::drawLiveResult()
{
    const auto& result = project->result();
    const auto& series = result.series();
    if (!series && !result.matrix() && result.status().empty())
    {
        project->readResult();
    }
    panelButton(Control::showSolver, "해석 도구", project->view() != nullptr, analysisOpen, Control::result);
    ImGui::SameLine();
    panelButton(Control::reloadResult, "결과 다시 읽기", project->writable(), false, Control::result);
    ImGui::SameLine();
    panelButton(Control::showResultHistory, "과거 결과",
        resultHistoryOpen || (project->view() && project->writable()), resultHistoryOpen, Control::result);
    ImGui::SameLine();
    panelButton(Control::showRfExport, "RF 내보내기", series || rfExportOpen, rfExportOpen, Control::result);
    if (resultHistoryOpen)
    {
        drawResultHistory();
    }
    if (rfExportOpen)
    {
        drawRfExport();
    }
    if (analysisOpen)
    {
        drawAnalysis();
    }
    if (!result.status().empty())
    {
        ImGui::TextWrapped("%s", result.status().c_str());
        access.text(Control::resultReadStatus, Control::result, result.status());
    }
    if (result.matrix())
    {
        drawMatrix(*result.matrix());
        return;
    }
    if (!series)
    {
        return;
    }

    const auto* view = project->view();
    const bool current = view && view->revision == series->revision;
    char summary[160];
    std::snprintf(summary, sizeof(summary), "결과 개정 %.12s  |  %s  |  %zu개 표본",
        series->revision.c_str(), current ? "현재 설계" : "이전 설계", series->total);
    ImGui::TextUnformatted(summary);
    access.text(Control::resultSummary, Control::result, summary);
    if (ImGui::IsItemHovered())
    {
        ImGui::BeginTooltip();
        ImGui::TextUnformatted(series->label.c_str());
        ImGui::Text("개정 %s", series->revision.c_str());
        ImGui::Text("자료 SHA-256 %s", series->pin.at("dataset_sha256").get_ref<const std::string&>().c_str());
        for (const auto& reference : series->references)
        {
            ImGui::TextUnformatted(reference.get_ref<const std::string&>().c_str());
        }
        ImGui::EndTooltip();
    }
    ImGui::PushID(series->source.at("artifact_id").get_ref<const std::string&>().c_str());
    if (ImPlot::BeginPlot("###project-s11", {-1.0f, -1.0f}, ImPlotFlags_NoLegend))
    {
        ImPlot::SetupAxes("주파수 (GHz)", "|S11| (dB)");
        ImPlot::SetNextLineStyle(ImVec4(0.32f, 0.82f, 0.78f, 1.0f), 2.0f);
        ImPlot::SetNextMarkerStyle(ImPlotMarker_Circle, 2.5f);
        ImPlot::PlotLine("S11", series->frequenciesGhz.data(), series->magnitudeDb.data(),
            static_cast<int>(series->total));
        ImPlot::EndPlot();
        plotDrawn = true;
    }
    ImGui::PopID();
}

/** @brief 수신 포트, 입사 포트와 주파수 선택에 맞춰 봉인된 값과 S 곡선을 표시한다. */
void Shell::drawMatrix(const PrototypeMatrix::Matrix& matrix)
{
    if (matrixArtifact != matrix.artifact)
    {
        matrixArtifact = matrix.artifact;
        matrixRow = matrixColumn = matrixSample = 0;
    }
    const auto ports = matrix.ports.size();
    const auto* view = project->view();
    const auto* relation = view && view->revision == matrix.revision ? "현재 설계" : "이전 설계";
    char summary[240];
    std::snprintf(summary, sizeof(summary), "결과 개정 %.12s | %s | %zu x %zu S 행렬 | %zu개 표본",
        matrix.revision.c_str(), relation, ports, ports, matrix.hertz.size());
    ImGui::TextUnformatted(summary);
    access.text(Control::resultSummary, Control::result, summary);
    if (ImGui::IsItemHovered())
    {
        ImGui::BeginTooltip();
        ImGui::TextUnformatted(matrix.label.c_str());
        ImGui::Text("개정 %s", matrix.revision.c_str());
        ImGui::Text("아티팩트 %s", matrix.artifact.c_str());
        ImGui::Text("원문 SHA-256 %s", matrix.sha256.c_str());
        ImGui::Text("파동 %s | 페이저 %s", matrix.wave.c_str(), matrix.phasor.c_str());
        ImGui::EndTooltip();
    }

    panelButton(Control::matrixPriorRow, "이전 수신", matrixRow > 0, false, Control::result);
    ImGui::SameLine();
    panelButton(Control::matrixNextRow, "다음 수신", matrixRow + 1 < ports, false, Control::result);
    ImGui::SameLine();
    panelButton(Control::matrixPriorColumn, "이전 입사", matrixColumn > 0, false, Control::result);
    ImGui::SameLine();
    panelButton(Control::matrixNextColumn, "다음 입사", matrixColumn + 1 < ports, false, Control::result);
    const auto& receive = matrix.ports[matrixRow];
    const auto& incident = matrix.ports[matrixColumn];
    const auto portLabel = [&](std::size_t index, const PrototypeMatrix::Port& port)
    {
        const auto& z = matrix.impedances[matrixSample * ports + index];
        char impedance[80] = "";
        if (z)
        {
            std::snprintf(impedance, sizeof(impedance), " | Z0 %.12g %+.12gj ohm", z->real, z->imag);
        }
        return std::to_string(index + 1) + " " + (port.name.empty() ? port.id : port.name) +
            (port.referencePlane.empty() ? "" : " | 기준면 " + port.referencePlane) + impedance;
    };
    const auto axes = "수신 " + portLabel(matrixRow, receive) + " / 입사 " + portLabel(matrixColumn, incident);
    ImGui::TextWrapped("%s", axes.c_str());
    access.text(Control::matrixAxes, Control::result, axes);
    if (ImGui::IsItemHovered())
    {
        ImGui::SetTooltip("수신 ID %s\n입사 ID %s", receive.id.c_str(), incident.id.c_str());
    }

    panelButton(Control::matrixPriorSample, "이전 주파수", matrixSample > 0, false, Control::result);
    ImGui::SameLine();
    panelButton(Control::matrixNextSample, "다음 주파수", matrixSample + 1 < matrix.hertz.size(), false, Control::result);
    ImGui::SameLine();
    panelButton(Control::matrixTable, "행렬 표", true, showMatrixTable, Control::result);
    const auto name = PrototypeMatrix::ChannelName(matrixRow, matrixColumn);
    const auto& channel = matrix.channel(matrixRow, matrixColumn);
    const auto describe = [](char* buffer, std::size_t size, const PrototypeMatrix::Sample& sample, int digits)
    {
        if (sample.state == PrototypeMatrix::State::valid)
        {
            std::snprintf(buffer, size, "Re %.*g  Im %.*g", digits, sample.value.real, digits, sample.value.imag);
        }
        else
        {
            std::snprintf(buffer, size, "%s", PrototypeMatrix::StateLabel(sample.state));
        }
    };
    char value[112];
    describe(value, sizeof(value), channel.samples[matrixSample], 17);
    char sample[220];
    std::snprintf(sample, sizeof(sample), "%s  |  %.17g Hz  |  %s", name.c_str(), matrix.hertz[matrixSample], value);
    ImGui::TextWrapped("%s", sample);
    access.text(Control::matrixSample, Control::result, sample);

    ImGui::PushID(matrix.artifact.c_str());
    if (showMatrixTable)
    {
        const auto flags = ImGuiTableFlags_Borders | ImGuiTableFlags_ScrollX | ImGuiTableFlags_ScrollY;
        if (ImGui::BeginTable("##matrix", static_cast<int>(ports + 1), flags, {-1.0f, -1.0f}))
        {
            ImGui::TableSetupScrollFreeze(1, 1);
            ImGui::TableSetupColumn("수신 / 입사", ImGuiTableColumnFlags_WidthFixed, 96.0f);
            for (std::size_t column = 0; column < ports; ++column)
            {
                const auto header = "입사 " + std::to_string(column + 1);
                ImGui::TableSetupColumn(header.c_str(), ImGuiTableColumnFlags_WidthFixed, 185.0f);
            }
            ImGui::TableHeadersRow();
            for (std::size_t row = 0; row < ports; ++row)
            {
                ImGui::TableNextRow();
                ImGui::TableNextColumn();
                ImGui::Text("수신 %zu", row + 1);
                for (std::size_t column = 0; column < ports; ++column)
                {
                    ImGui::TableNextColumn();
                    const auto& cell = matrix.channel(row, column).samples[matrixSample];
                    describe(value, sizeof(value), cell, 7);
                    const auto text = PrototypeMatrix::ChannelName(row, column) + "\n" + value;
                    if (ImGui::Selectable(text.c_str(), row == matrixRow && column == matrixColumn))
                    {
                        matrixRow = row;
                        matrixColumn = column;
                    }
                }
            }
            ImGui::EndTable();
        }
    }
    else
    {
        // @brief 각 채널은 자신의 축 범위와 확대 상태를 갖는다.
        const auto plot = "###matrix-" + name;
        if (ImPlot::BeginPlot(plot.c_str(), {-1.0f, -1.0f}, ImPlotFlags_NoLegend))
        {
            const auto ordinate = "|" + name + "| (dB)";
            ImPlot::SetupAxes("주파수 (GHz)", ordinate.c_str());
            ImPlot::SetNextLineStyle(ImVec4(0.32f, 0.82f, 0.78f, 1.0f), 2.0f);
            ImPlot::SetNextMarkerStyle(ImPlotMarker_Circle, 2.5f);
            ImPlot::PlotLine(name.c_str(), matrix.ghz.data(), channel.db.data(), static_cast<int>(matrix.ghz.size()));
            ImPlot::EndPlot();
            plotDrawn = true;
        }
    }
    ImGui::PopID();
}

/** @brief 실제 서비스가 제공한 형식과 표시 중인 RF 결과를 함께 보여준다. */
void Shell::drawRfExport()
{
    const auto& series = project->result().series();
    const auto count = series ? series->exportFormats.size() : 0;
    if (rfFormatIndex >= count)
    {
        rfFormatIndex = 0;
    }
    const bool allowed = project->writable() && !rfDelivery.valid() && count > 0;
    panelButton(Control::previousRfExport, "이전 RF 형식", allowed && rfFormatIndex > 0, false, Control::result);
    ImGui::SameLine();
    panelButton(Control::nextRfExport, "다음 RF 형식", allowed && rfFormatIndex + 1 < count, false, Control::result);
    ImGui::SameLine();
    panelButton(Control::saveRfExport, "결과와 조건 저장", allowed, false, Control::result);
    if (count > 0)
    {
        const auto& format = series->exportFormats[rfFormatIndex];
        const char* label = format == "csv" ? "CSV" : format == "touchstone" ? "Touchstone" :
            format == "hdf5" ? "HDF5" : "보존 원문";
        ImGui::SameLine();
        ImGui::TextUnformatted(label);
        access.text(Control::rfExportFormat, Control::result, label);
    }
    const auto status = !rfDeliveryStatus.empty() ? rfDeliveryStatus : project->rfExportStatus();
    if (!status.empty())
    {
        ImGui::TextWrapped("%s", status.c_str());
        access.text(Control::rfExportStatus, Control::result, status);
    }
}

/** @brief 붙잡아 둔 봉인 응답만 사용해 외부 새 파일과 조건 파일을 함께 게시한다. */
void Shell::deliverRfExport(SDL_Window* mainWindow)
{
    using namespace std::chrono_literals;
    if (rfDelivery.valid() && rfDelivery.wait_for(0ms) == std::future_status::ready)
    {
        rfDeliveryStatus = rfDelivery.get();
    }
    auto result = project->takeRfExport();
    if (result.is_null())
    {
        return;
    }
    try
    {
        const auto& utf8 = result.at("file_name").get_ref<const std::string&>();
        const auto name = std::filesystem::path(std::u8string(utf8.begin(), utf8.end()));
        if (name.empty() || name != name.filename() || !name.has_extension() || name.native().size() >= 220)
        {
            throw std::runtime_error("서비스가 돌려준 교환 파일 이름을 확인할 수 없습니다.");
        }
        std::vector<wchar_t> filename(32768, L'\0');
        std::copy(name.native().begin(), name.native().end(), filename.begin());
        const auto extension = name.extension().native().substr(1);
        OPENFILENAMEW dialog{};
        dialog.lStructSize = sizeof(dialog);
        dialog.hwndOwner = static_cast<HWND>(SDL_GetPointerProperty(SDL_GetWindowProperties(mainWindow),
            SDL_PROP_WINDOW_WIN32_HWND_POINTER, nullptr));
        dialog.lpstrFile = filename.data();
        dialog.nMaxFile = static_cast<DWORD>(filename.size());
        dialog.lpstrDefExt = extension.c_str();
        dialog.lpstrTitle = L"RF 결과와 조건 저장";
        dialog.Flags = OFN_EXPLORER | OFN_NOCHANGEDIR | OFN_PATHMUSTEXIST | OFN_NOREADONLYRETURN;
        if (!GetSaveFileNameW(&dialog))
        {
            rfDeliveryStatus = CommDlgExtendedError() ? "RF 저장 경로 선택 창을 열지 못했습니다." : "RF 내보내기를 취소했습니다.";
            return;
        }
        const auto target = std::filesystem::path(filename.data());
        if (CompareStringOrdinal(target.extension().c_str(), -1, name.extension().c_str(), -1, TRUE) != CSTR_EQUAL)
        {
            throw std::runtime_error("선택한 RF 형식의 원래 확장자를 유지하세요.");
        }
        const std::string_view workspaceText(workspacePath);
        const auto workspace = std::filesystem::path(std::u8string(workspaceText.begin(), workspaceText.end()));
        rfDeliveryStatus = "교환 파일과 조건 파일을 저장하는 중";
        rfDelivery = std::async(std::launch::async, [result = std::move(result), target, workspace]() -> std::string
        {
            try
            {
                NetworkExportFiles::WriteResult(result, target, workspace);
                return "RF 교환 파일과 .conditions.json을 저장했습니다.";
            }
            catch (const std::exception& error)
            {
                return std::string("RF 내보내기 실패. ") + error.what();
            }
        });
    }
    catch (const std::exception& error)
    {
        rfDeliveryStatus = std::string("RF 내보내기 실패. ") + error.what();
    }
}

/** @brief 완료된 목록에서 열 항목을 고르고 곡선의 교체를 명시적으로 요청한다. */
void Shell::drawResultHistory()
{
    const auto& result = project->result();
    const auto* choice = result.historyChoice();
    const bool ready = project->writable();
    panelButton(Control::reloadResultHistory, "목록 다시 읽기", ready, false, Control::result);
    ImGui::SameLine();
    panelButton(Control::priorResult, "이전 결과", ready && result.canBrowseHistory(-1), false, Control::result);
    ImGui::SameLine();
    panelButton(Control::nextResult, "다음 결과", ready && result.canBrowseHistory(1), false, Control::result);
    ImGui::SameLine();
    panelButton(Control::openHistoryResult, "결과 열기", ready && choice, false, Control::result);
    if (choice)
    {
        const auto* view = project->view();
        const auto state = view && choice->revision == view->revision ? "현재 설계" : "이전 설계";
        const auto summary = choice->label + " | 개정 " + choice->revision.substr(0, 12) + " | " + state;
        ImGui::TextWrapped("%s", summary.c_str());
        access.text(Control::historyChoice, Control::result, summary);
    }
    const auto& status = result.historyStatus();
    if (!status.empty())
    {
        ImGui::TextWrapped("%s", status.c_str());
        access.text(Control::historyStatus, Control::result, status);
    }
}

/** @brief 조건 선택, 계획 승인과 실제 작업 상태를 같은 결과 패널에 표시한다. */
void Shell::drawAnalysis()
{
    const auto& analysis = project->analysis();
    panelButton(Control::readSolverConditions, "조건 읽기", project->canReadSolverConditions(), false, Control::result);
    ImGui::SameLine();
    panelButton(Control::priorSolverCondition, "이전 조건", project->writable() && analysis.canMove(-1), false, Control::result);
    ImGui::SameLine();
    panelButton(Control::nextSolverCondition, "다음 조건", project->writable() && analysis.canMove(1), false, Control::result);
    if (const auto* condition = analysis.condition())
    {
        ImGui::SameLine();
        ImGui::TextUnformatted(condition->name.c_str());
        access.text(Control::solverCondition, Control::result, condition->name);
        if (ImGui::IsItemHovered())
        {
            ImGui::BeginTooltip();
            const auto settings = condition->settings.dump(2);
            ImGui::TextUnformatted(settings.c_str());
            ImGui::EndTooltip();
        }
    }
    panelButton(Control::reviewSolver, "계획 검토", project->canReviewSolver(), false, Control::result);
    ImGui::SameLine();
    panelButton(Control::approveSolver, "해석 실행", project->canApproveSolver(), false, Control::result);
    ImGui::SameLine();
    panelButton(Control::cancelSolver, "해석 취소", analysis.canCancel(), false, Control::result);

    const auto& status = analysis.status();
    if (!status.empty())
    {
        ImGui::TextWrapped("%s", status.c_str());
        access.text(Control::solverStatus, Control::result, status);
    }
    else if (!project->solverReady())
    {
        constexpr char missing[] = "설치 및 감사가 완료된 Windows openEMS가 필요합니다.";
        ImGui::TextUnformatted(missing);
        access.text(Control::solverStatus, Control::result, missing);
    }
    if (const auto& plan = analysis.plan())
    {
        char summary[256];
        std::snprintf(summary, sizeof(summary),
            "계획 %.12s / 개정 %.12s / %.6g~%.6g GHz %zu개 / 격자 %llu / 예상 %.1f MiB / 최대 %d초",
            plan->plan.c_str(), plan->revision.c_str(), plan->startGhz, plan->stopGhz, plan->samples,
            static_cast<unsigned long long>(plan->cells), static_cast<double>(plan->bytes) / (1024.0 * 1024.0), plan->timeout);
        ImGui::TextWrapped("%s", summary);
        access.text(Control::solverPlan, Control::result, summary);
        if (ImGui::IsItemHovered())
        {
            ImGui::BeginTooltip();
            ImGui::TextUnformatted(plan->condition.c_str());
            ImGui::TextUnformatted(plan->settings.c_str());
            ImGui::TextUnformatted(plan->model.c_str());
            ImGui::EndTooltip();
        }
    }
}
#endif

void Shell::drawInput(SDL_Window* mainWindow)
{
    noteActive = false;
    if (focusInput || requestedFocus == Control::input || requestedFocus == Control::clearNote)
    {
        inputOpen = true;
    }
    if (!inputOpen)
    {
        return;
    }
    const bool focusPanel = focusInput || requestedFocus == Control::input || requestedFocus == Control::clearNote;
    const ImGuiViewport* mainViewport = ImGui::GetMainViewport();
    if (focusPanel && !detachInput)
    {
        ImGui::SetNextWindowFocus();
    }
    if (ImGui::Begin(inputTitle, &inputOpen))
    {
        if (!detachInput)
        {
            drawNote(mainViewport);
        }
    }
    ImGui::End();
    if (detachInput)
    {
        ImGuiWindowClass windowClass;
        windowClass.ViewportFlagsOverrideSet = ImGuiViewportFlags_NoAutoMerge;
        windowClass.ViewportFlagsOverrideClear = ImGuiViewportFlags_NoFocusOnAppearing;
        ImGui::SetNextWindowClass(&windowClass);
        if (placeInput)
        {
            ImGui::SetNextWindowPos({mainViewport->Pos.x + 96.0f, mainViewport->Pos.y + 110.0f}, ImGuiCond_Always);
            ImGui::SetNextWindowSize({440.0f, 190.0f}, ImGuiCond_Always);
            placeInput = false;
        }
        if (focusPanel)
        {
            ImGui::SetNextWindowFocus();
        }
        if (ImGui::Begin(detachedInputTitle, &detachInput, ImGuiWindowFlags_NoDocking | ImGuiWindowFlags_NoSavedSettings))
        {
            drawNote(mainViewport);
        }
        ImGui::End();
        if (!detachInput)
        {
            SDL_RaiseWindow(mainWindow);
            restoreMainFocus = focusInput = true;
            return;
        }
    }
    focusInput = false;
}

void Shell::drawNote(const ImGuiViewport* mainViewport)
{
    access.panel(Control::input);
    if (requestedFocus == Control::input)
    {
        requestedFocus = Control::root;
    }
    ImGui::TextUnformatted("검수 메모");
    ImGui::SetNextItemWidth(-1.0f);
    if (focusInput)
    {
        if (ImGui::GetWindowViewport() != mainViewport)
        {
            if (SDL_Window* window = SDL_GetWindowFromID(windowId(ImGui::GetWindowViewport())))
            {
                if (!(SDL_GetWindowFlags(window) & SDL_WINDOW_INPUT_FOCUS))
                {
                    SDL_RaiseWindow(window);
                }
            }
        }
        ImGui::SetKeyboardFocusHere();
    }
    ImGui::InputText("###note", note.data(), note.size());
    noteId = ImGui::GetItemID();
    noteActive = ImGui::IsItemActive();
    noteWindow = windowId(ImGui::GetWindowViewport());
    access.item(Control::note, Control::input);
    if (noteActive && !preedit.empty() && preeditWindow == noteWindow)
    {
        ImGui::Text("조합 중  %s", preedit.c_str());
    }
    if (ImGui::Button("메모 지우기"))
    {
        activate(Control::clearNote);
    }
    focusItem(Control::clearNote);
    access.item(Control::clearNote, Control::input);
}

/** @brief 플랫폼 창이 생성 또는 제거된 뒤 HWND에 접근성 정보와 복귀 초점을 적용한다. */
void Shell::finishFrame(SDL_Window* mainWindow)
{
    const auto detachedWindow = [](const char* title)
    {
        const ImGuiWindow* window = ImGui::FindWindowByName(title);
        if (window && window->Viewport != ImGui::GetMainViewport())
        {
            return windowId(window->Viewport);
        }
        return SDL_WindowID{};
    };
    detachedResultWindow = resultOpen ? detachedWindow(resultTitle) : 0;
    detachedNoteWindow = detachInput ? detachedWindow(detachedInputTitle) : detachedWindow(inputTitle);
    if (restoreMainFocus)
    {
        SDL_RaiseWindow(mainWindow);
        restoreMainFocus = false;
    }
    access.publish(note.data());
}

bool queueKey(Uint32 type, SDL_WindowID window, SDL_Scancode scan, SDL_Keymod modifiers = SDL_KMOD_NONE)
{
    SDL_Event event{};
    event.type = type;
    event.key.windowID = window;
    event.key.scancode = scan;
    event.key.key = SDL_GetKeyFromScancode(scan, modifiers, false);
    event.key.mod = modifiers;
    event.key.down = type == SDL_EVENT_KEY_DOWN;
    return SDL_PushEvent(&event);
}

bool queueComposition(SDL_WindowID window, const char* text)
{
    SDL_Event event{};
    event.type = SDL_EVENT_TEXT_EDITING;
    event.edit.windowID = window;
    event.edit.text = text;
    return SDL_PushEvent(&event);
}

bool queueCommit(SDL_WindowID window, const char* text)
{
    SDL_Event event{};
    event.type = SDL_EVENT_TEXT_INPUT;
    event.text.windowID = window;
    event.text.text = text;
    return SDL_PushEvent(&event);
}

bool queueClose(SDL_WindowID window)
{
    SDL_Event event{};
    event.type = SDL_EVENT_WINDOW_CLOSE_REQUESTED;
    event.window.windowID = window;
    return window && SDL_PushEvent(&event);
}

/** @brief 실제 창 이벤트 큐의 키, 닫기와 합성 UTF-8 입력으로 기본 수명 주기를 검사한다. */
struct Smoke
{
    explicit Smoke(SDL_Window* mainWindow, bool viewports)
        : window(mainWindow), windowID(SDL_GetWindowID(mainWindow)), hasViewports(viewports)
    {
    }

    void check(bool condition, const char* label)
    {
        std::printf("%s %s\n", condition ? "PASS" : "FAIL", label);
        passed &= condition;
    }

    /** @brief 분리 창을 다른 배율의 실제 디스플레이로 옮긴다. */
    void moveToOtherDisplay()
    {
        SDL_Window* secondary = SDL_GetWindowFromID(secondaryID);
        if (!secondary)
        {
            return;
        }
        const SDL_DisplayID source = SDL_GetDisplayForWindow(secondary);
        const float sourceScale = SDL_GetDisplayContentScale(source);
        int count = 0;
        SDL_DisplayID* displays = SDL_GetDisplays(&count);
        for (int index = 0; index < count; ++index)
        {
            const SDL_DisplayID candidate = displays[index];
            const float scale = SDL_GetDisplayContentScale(candidate);
            if (candidate != source && scale > 0.0f && scale != sourceScale)
            {
                movedDisplay = candidate;
                secondaryScale = SDL_GetWindowDisplayScale(secondary);
                check(SDL_SetWindowPosition(secondary, SDL_WINDOWPOS_CENTERED_DISPLAY(candidate),
                    SDL_WINDOWPOS_CENTERED_DISPLAY(candidate)), "secondary window move requested");
                break;
            }
        }
        SDL_free(displays);
        if (!movedDisplay)
        {
            std::puts("SKIP secondary move (no second scale available)");
        }
    }

    /** @brief 활성 IME에 전달한 위치를 메모가 속한 창의 캐럿 좌표와 대조한다. */
    void checkImeArea(SDL_Window* host, const char* label)
    {
        const ImGuiContext& context = *ImGui::GetCurrentContext();
        const ImGuiPlatformImeData& ime = context.PlatformImeData;
        const ImGuiViewport* viewport = ImGui::FindViewportByID(context.PlatformImeViewport);
        SDL_Rect area{};
        int width = 0;
        int height = 0;
        const bool matchesHost = host && ime.WantVisible && viewport && windowId(viewport) == SDL_GetWindowID(host)
            && SDL_TextInputActive(host) && SDL_GetWindowSize(host, &width, &height)
            && SDL_GetTextInputArea(host, &area, nullptr);
        if (matchesHost)
        {
            std::printf("IME window=%u area=(%d,%d %dx%d) client=%dx%d\n", SDL_GetWindowID(host),
                area.x, area.y, area.w, area.h, width, height);
        }
        check(matchesHost && area.x >= 0 && area.y >= 0 && area.x < width && area.y < height
            && area.w > 0 && area.h > 0 && std::abs(area.x + viewport->Pos.x - ime.InputPos.x) <= 1.0f
            && std::abs(area.y + viewport->Pos.y - ime.InputPos.y - ime.InputLineHeight) <= 1.0f, label);
    }

    /** @brief 혼합 배율 장비가 없어도 분리 입력 창을 같은 디스플레이에서 옮긴다. */
    void moveDetachedNote()
    {
        SDL_Window* host = SDL_GetWindowFromID(detachedNoteID);
        SDL_Rect workArea{};
        int width = 0;
        const bool readPosition = host && SDL_GetWindowPosition(host, &noteStart.x, &noteStart.y)
            && SDL_GetWindowSize(host, &width, nullptr)
            && SDL_GetDisplayUsableBounds(SDL_GetDisplayForWindow(host), &workArea);
        check(readPosition, "secondary note starting position available");
        if (!readPosition)
        {
            return;
        }
        constexpr int distance = 64;
        noteTargetX = noteStart.x + distance;
        if (noteTargetX + width > workArea.x + workArea.w)
        {
            noteTargetX = noteStart.x - distance;
        }
        check(SDL_SetWindowPosition(host, noteTargetX, noteStart.y), "same-display secondary note move requested");
    }

    void beforeEvents()
    {
        switch (frame)
        {
            case 4:
                check(SDL_SetWindowSize(window, 980, 680), "resize requested");
                check(queueKey(SDL_EVENT_KEY_DOWN, windowID, SDL_SCANCODE_F6), "F6 pressed");
                break;
            case 5:
                check(queueKey(SDL_EVENT_KEY_UP, windowID, SDL_SCANCODE_F6), "F6 released");
                break;
            case 8:
                check(queueComposition(windowID, editingText), "synthetic SDL composition queued");
                break;
            case 11:
                check(queueCommit(windowID, committedText), "synthetic SDL UTF-8 commit queued");
                break;
            case 16:
                if (hasViewports)
                {
                    check(queueKey(SDL_EVENT_KEY_DOWN, windowID, SDL_SCANCODE_F8), "detach requested");
                }
                else
                {
                    check(queueKey(SDL_EVENT_KEY_DOWN, windowID, SDL_SCANCODE_F7), "hide requested");
                }
                break;
            case 17:
                check(queueKey(SDL_EVENT_KEY_UP, windowID, hasViewports ? SDL_SCANCODE_F8 : SDL_SCANCODE_F7),
                    "panel shortcut released");
                break;
            case 22:
                if (hasViewports)
                {
                    moveToOtherDisplay();
                }
                break;
            case 31:
                if (hasViewports)
                {
                    check(queueClose(secondaryID), "native secondary close queued");
                }
                break;
            case 38:
                check(queueKey(SDL_EVENT_KEY_DOWN, windowID, SDL_SCANCODE_F7), "reopen requested");
                break;
            case 39:
                check(queueKey(SDL_EVENT_KEY_UP, windowID, SDL_SCANCODE_F7), "reopen shortcut released");
                break;
            case 44:
                check(queueKey(SDL_EVENT_KEY_DOWN, windowID, SDL_SCANCODE_F9), "default layout requested");
                break;
            case 45:
                check(queueKey(SDL_EVENT_KEY_UP, windowID, SDL_SCANCODE_F9), "restore shortcut released");
                break;
            case 52:
                if (hasViewports)
                {
                    check(queueKey(SDL_EVENT_KEY_DOWN, windowID, SDL_SCANCODE_F8, SDL_KMOD_LSHIFT),
                        "detach input requested");
                }
                break;
            case 53:
                if (hasViewports)
                {
                    check(queueKey(SDL_EVENT_KEY_UP, windowID, SDL_SCANCODE_F8), "detach input shortcut released");
                }
                break;
            case 58:
                if (checkWindowsIme && hasViewports)
                {
                    moveDetachedNote();
                }
                break;
            case 59:
                if (hasViewports)
                {
                    check(queueComposition(detachedNoteID, editingText), "secondary synthetic SDL composition queued");
                    check(queueCommit(windowID, "discard"), "other-window synthetic SDL commit queued");
                }
                break;
            case 61:
                if (hasViewports)
                {
                    check(queueComposition(detachedNoteID, ""), "secondary synthetic SDL cancellation queued");
                }
                break;
            case 63:
                if (hasViewports)
                {
                    check(queueCommit(detachedNoteID, editingText), "secondary synthetic SDL commit queued");
                }
                break;
            case 66:
                if (hasViewports)
                {
                    check(queueClose(detachedNoteID), "secondary input close queued");
                }
                break;
            case 73:
                check(queueClose(windowID), "main close queued");
                break;
            default:
                break;
        }
    }

    void afterFrame(const Shell& shell, const Renderer& renderer)
    {
        const ImGuiWindow* plot = ImGui::FindWindowByName(resultTitle);
        switch (frame)
        {
            case 2:
                check(shell.boardDrawn && shell.plotDrawn && plot && plot->DockIsActive, "board and B0 plot docked");
                check(bgfx::getStats()->numDraw > 1, "nonempty GPU draw submissions");
                break;
            case 8:
            {
                int width = 0;
                int height = 0;
                SDL_GetWindowSizeInPixels(window, &width, &height);
                std::printf("Window=%dx%d px density=%.2f displayScale=%.2f\n", width, height,
                    SDL_GetWindowPixelDensity(window), SDL_GetWindowDisplayScale(window));
                check(width > 0 && height > 0 && bgfx::getStats()->width == width && bgfx::getStats()->height == height,
                    "resized GPU framebuffer matches SDL pixels");
                check(shell.noteActive && shell.preedit == editingText && shell.note[0] == '\0',
                    "keyboard focus and separate IME preedit");
                if (checkWindowsIme)
                {
                    checkImeArea(window, "main IME area follows its note caret");
                }
                break;
            }
            case 14:
                check(shell.preedit.empty() && std::string_view(shell.note.data()) == committedText,
                    "committed UTF-8 reaches focused input");
                break;
            case 21:
                if (hasViewports)
                {
                    if (plot && plot->Viewport != ImGui::GetMainViewport())
                    {
                        secondaryID = windowId(plot->Viewport);
                    }
                    check(secondaryID && SDL_GetWindowFromID(secondaryID) && renderer.secondaryFrames() > 0,
                        "secondary SDL window and bgfx draw submissions");
                    secondaryFrames = renderer.secondaryFrames();
                }
                break;
            case 29:
                if (movedDisplay)
                {
                    SDL_Window* secondary = SDL_GetWindowFromID(secondaryID);
                    const float scale = secondary ? SDL_GetWindowDisplayScale(secondary) : 0.0f;
                    std::printf("Secondary display scale %.2f -> %.2f\n", secondaryScale, scale);
                    check(secondary && SDL_GetDisplayForWindow(secondary) == movedDisplay && scale != secondaryScale
                        && renderer.secondaryFrames() > secondaryFrames, "secondary rendered after mixed-DPI move");
                }
                break;
            case 36:
                check(!shell.resultOpen && (!hasViewports || !SDL_GetWindowFromID(secondaryID)), "panel closed");
                break;
            case 43:
                check(shell.resultOpen && shell.plotDrawn, "panel reopened");
                break;
            case 50:
                check(plot && plot->DockIsActive && plot->Viewport == ImGui::GetMainViewport(),
                    "default layout restored");
                check(std::strstr(ImGui::SaveIniSettingsToMemory(), "[Docking][Data]") != nullptr,
                    "dock layout serialized");
                check(renderer.healthy(), "renderer resources healthy");
                break;
            case 57:
                if (hasViewports)
                {
                    detachedNoteID = shell.detachedNoteWindow;
                    check(detachedNoteID && shell.noteActive && shell.noteWindow == detachedNoteID,
                        "secondary input is active in its own SDL window");
                    if (checkWindowsIme)
                    {
                        checkImeArea(SDL_GetWindowFromID(detachedNoteID), "secondary IME area follows its note caret");
                    }
                }
                break;
            case 59:
                if (hasViewports)
                {
                    check(shell.preedit == editingText && std::string_view(shell.note.data()) == committedText,
                        "secondary composition kept separate and other-window commit discarded");
                }
                break;
            case 61:
                if (hasViewports)
                {
                    check(shell.preedit.empty() && std::string_view(shell.note.data()) == committedText,
                        "cancelled secondary composition did not change the note");
                }
                break;
            case 62:
                if (checkWindowsIme && hasViewports)
                {
                    SDL_Window* host = SDL_GetWindowFromID(detachedNoteID);
                    int x = 0;
                    int y = 0;
                    const bool positionAvailable = host && SDL_GetWindowPosition(host, &x, &y);
                    std::printf("Secondary note position (%d,%d) -> (%d,%d) expected x=%d\n",
                        noteStart.x, noteStart.y, x, y, noteTargetX);
                    check(positionAvailable && x == noteTargetX && y == noteStart.y && x != noteStart.x,
                        "secondary input moved to the requested position");
                    checkImeArea(host, "secondary IME area still follows its note caret after moving");
                }
                break;
            case 65:
                if (hasViewports)
                {
                    const std::string_view noteValue(shell.note.data());
                    check(noteValue.ends_with(editingText) && noteValue != committedText,
                        "synthetic UTF-8 commit reached the secondary input");
                }
                break;
            case 71:
                if (hasViewports)
                {
                    const bool closed = !SDL_GetWindowFromID(detachedNoteID);
                    const bool mainFocused = SDL_GetKeyboardFocus() == window;
                    const bool noteFocused = shell.noteActive && shell.noteWindow == windowID;
                    if (!closed || !mainFocused || !noteFocused)
                    {
                        std::printf("Focus return: secondary closed=%d SDL main focus=%d main note active=%d\n",
                            closed, mainFocused, noteFocused);
                    }
                    check(closed && mainFocused && noteFocused, "input focus returned to the main window");
                    if (checkWindowsIme)
                    {
                        checkImeArea(window, "main IME area follows its note caret after focus returns");
                    }
                }
                break;
            default:
                break;
        }
        ++frame;
    }

    SDL_Window* window;
    SDL_WindowID windowID;
    SDL_WindowID secondaryID = 0;
    SDL_WindowID detachedNoteID = 0;
    SDL_Point noteStart{};
    int noteTargetX = 0;
    SDL_DisplayID movedDisplay = 0;
    float secondaryScale = 0.0f;
    unsigned secondaryFrames = 0;
    int frame = 0;
    bool hasViewports;
#if defined(_WIN32)
    static constexpr bool checkWindowsIme = true;
#else
    static constexpr bool checkWindowsIme = false;
#endif
    bool passed = true;
};

int run(SDL_Window* window, const Options& options)
{
    Renderer renderer;
    if (!renderer.initialize(window))
    {
        return 1;
    }

    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImPlot::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard | ImGuiConfigFlags_DockingEnable
        | ImGuiConfigFlags_DpiEnableScaleFonts | ImGuiConfigFlags_DpiEnableScaleViewports;
    std::string settingsPath;
    io.IniFilename = nullptr;
    if (!options.smoke)
    {
        char* directory = SDL_GetPrefPath("TraceWave", "ShellPrototype");
        if (directory)
        {
            settingsPath = std::string(directory) + "layout.ini";
            SDL_free(directory);
            io.IniFilename = settingsPath.c_str();
        }
    }
    ImGui::StyleColorsDark();
    ImGuiStyle& style = ImGui::GetStyle();
    style.FrameRounding = 4.0f;
    style.GrabRounding = 4.0f;
    style.Colors[ImGuiCol_WindowBg] = {0.08f, 0.11f, 0.15f, 1.0f};
    style.Colors[ImGuiCol_DockingPreview] = {0.32f, 0.82f, 0.78f, 0.7f};
    ImFont* font = installFont(options.font);

#if defined(__APPLE__)
    const bool platformReady = ImGui_ImplSDL3_InitForMetal(window);
#else
    const bool platformReady = ImGui_ImplSDL3_InitForVulkan(window);
#endif
    int code = 1;
    if (platformReady)
    {
        ImGui::GetPlatformIO().Platform_GetWindowDpiScale = windowDpiScale;
        if (renderer.hasViewports())
        {
            io.ConfigFlags |= ImGuiConfigFlags_ViewportsEnable;
        }
        const bool rendererReady = font && renderer.attachWidgets();
        if (rendererReady)
        {
            const bool korean = font->FindGlyphNoFallback(static_cast<ImWchar>(U'한')) != nullptr;
            Shell shell;
            Smoke smoke(window, renderer.hasViewports());
#if defined(_WIN32)
            PrototypeService service;
            auto project = std::make_unique<PrototypeProject>(options.openProject, options.service.workspace);
            shell.project = project.get();
            shell.workspacePath = options.service.workspace;
            shell.recent.load(settingsPath, options.service.workspace);
            shell.chooserOpen = options.service.workspace && !options.openProject;
            if (options.service.python)
            {
                service.start(options.service);
            }
#endif
            if (options.smoke)
            {
                std::printf("Renderer=%s video=%s device=0x%04x viewports=%s\n", renderer.name(),
                    SDL_GetCurrentVideoDriver(), bgfx::getCaps()->deviceId, smoke.hasViewports ? "yes" : "no");
                smoke.check(korean, "Hangul glyph in font atlas");
                if (Smoke::checkWindowsIme && !options.font)
                {
                    smoke.check(font->FindGlyphNoFallback(static_cast<ImWchar>(U'韓'))
                        && font->FindGlyphNoFallback(static_cast<ImWchar>(U'漢')),
                        "Hanja conversion glyphs in Windows font atlas");
                }
            }

            const auto mainID = SDL_GetWindowID(window);
            bool closing = false;
            while (!closing && (!options.smoke || smoke.frame < 78) && renderer.healthy())
            {
                if (options.smoke)
                {
                    smoke.beforeEvents();
                }
                SDL_Event event;
                while (SDL_PollEvent(&event))
                {
                    if (shell.processEvent(event))
                    {
                        ImGui_ImplSDL3_ProcessEvent(&event);
                    }
                    if (event.type == SDL_EVENT_QUIT
                        || (event.type == SDL_EVENT_WINDOW_CLOSE_REQUESTED && event.window.windowID == mainID))
                    {
                        closing = true;
                    }
                }
                if (!closing)
                {
                    ImGui_ImplSDL3_NewFrame();
                    ImGui::NewFrame();
                    const char* serviceStatus = nullptr;
#if defined(_WIN32)
                    service.poll();
                    shell.updateProjects(window, project, service);
                    shell.deliverRfExport(window);
                    shell.manufacturing.update(window, options.service);
                    serviceStatus = service.status().c_str();
#endif
                    shell.draw(renderer, window, korean, serviceStatus);
                    ImGui::Render();
#if defined(_WIN32)
                    renderer.renderFrame(shell.model.texture());
#else
                    renderer.renderFrame();
#endif
                    shell.finishFrame(window);
                    if (options.smoke)
                    {
                        smoke.afterFrame(shell, renderer);
                    }
                    if (SDL_GetWindowFlags(window) & SDL_WINDOW_MINIMIZED)
                    {
                        SDL_Delay(16);
                    }
                }
            }
            if (options.smoke)
            {
                smoke.check(closing && smoke.frame == 73, "normal main window shutdown");
            }
            code = renderer.healthy() && (!options.smoke || smoke.passed) ? 0 : 1;
        }
        else
        {
            std::fputs("Unable to initialize UI shaders or fonts.\n", stderr);
        }
        if (io.BackendRendererUserData)
        {
            renderer.detachWidgets();
        }
        ImGui_ImplSDL3_Shutdown();
    }
    else
    {
        std::fputs("Unable to initialize SDL ImGui integration.\n", stderr);
    }
    ImPlot::DestroyContext();
    ImGui::DestroyContext();
    return code;
}
}

/** @brief SDL에서 전달한 UTF-8 실행 인수로 시제품 또는 연결 검수를 실행한다. */
int runShell(int argc, char** argv)
{
    Options options;
    if (!parseOptions(argc, argv, options))
    {
        std::fputs("Usage: tracewave_shell_prototype [--smoke] [--font <font-file>]\n", stderr);
#if defined(_WIN32)
        std::fputs("       [--service-check | --service-replay | --open-project <projects/name>] "
                   "--python <python.exe> --source <Code/src> --workspace <path> [--cad-python <python.exe>]\n", stderr);
#endif
        return 2;
    }
    SDL_SetMainReady();
#if defined(_WIN32)
    if (options.serviceReplay)
    {
        return runPrototypeServiceReplay(options.service);
    }
    if (options.serviceCheck)
    {
        PrototypeService service;
        service.start(options.service);
        while (service.state() == PrototypeService::State::connecting)
        {
            service.poll();
            SDL_Delay(5);
        }
        return service.state() == PrototypeService::State::connected ? 0 : 1;
    }
#endif
    SDL_SetHint(SDL_HINT_IME_IMPLEMENTED_UI, "composition");
    if (!SDL_Init(SDL_INIT_VIDEO))
    {
        std::fprintf(stderr, "SDL_Init: %s\n", SDL_GetError());
        return 1;
    }
    constexpr auto baseFlags = SDL_WINDOW_RESIZABLE | SDL_WINDOW_HIGH_PIXEL_DENSITY;
#if defined(__APPLE__)
    constexpr auto windowFlags = baseFlags | SDL_WINDOW_METAL;
#else
    constexpr auto windowFlags = baseFlags | SDL_WINDOW_VULKAN;
#endif
    SDL_Window* window = SDL_CreateWindow("TraceWave Studio | Shell Prototype", initialWidth, initialHeight, windowFlags);
    int code = 1;
    if (window)
    {
        SDL_SetWindowMinimumSize(window, 560, 370);
        code = run(window, options);
        SDL_DestroyWindow(window);
    }
    else
    {
        std::fprintf(stderr, "SDL_CreateWindow: %s\n", SDL_GetError());
    }
    SDL_Quit();
    return code;
}

int main([[maybe_unused]] int argc, [[maybe_unused]] char** argv)
{
#if defined(_WIN32)
    return SDL_RunApp(0, nullptr, runShell, nullptr);
#else
    return runShell(argc, argv);
#endif
}
