#include "accessibility.h"
#include "b0_samples.h"
#include "renderer.h"

#if defined(_WIN32)
#include "prototype_canvas.h"
#include "prototype_model.h"
#endif

#include <algorithm>
#include <array>
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
#include <implot.h>

namespace
{
constexpr char boardTitle[] = "기판###board";
constexpr char resultTitle[] = "S11 결과###results";
constexpr char inputTitle[] = "입력###input";
constexpr char detachedInputTitle[] = "입력###detached-input";
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
    bool modelOpen = false;
    void drawLiveBoard();
    void drawLiveModel();
    void drawLiveResult();
    void boardButton(Control control, const char* label, bool enabled, bool checked = false);
#endif

    bool processEvent(const SDL_Event& event);
    void draw(const Renderer& renderer, SDL_Window* mainWindow, bool koreanFont, const char* serviceStatus);
    void finishFrame(SDL_Window* mainWindow);
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
        options.service.source || options.service.workspace || options.openProject;
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

/** @brief 조합과 확정 이벤트를 현재 메모가 속한 SDL 창으로 제한한다. */
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
    if (event.type == SDL_EVENT_TEXT_EDITING)
    {
        if (!noteActive || event.edit.windowID != noteWindow)
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
    return event.type != SDL_EVENT_TEXT_INPUT || (noteActive && event.text.windowID == noteWindow);
}

/** @brief 바로 가기, 메뉴 및 UI Automation에서 같은 명령을 사용한다. */
void Shell::activate(Control control)
{
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
        case Control::reloadModel: project->readCad(); break;
        case Control::reloadResult: project->readResult(); break;
#endif
        default: break;
    }
}

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
        switch (action.operation)
        {
            case Operation::invoke:
            case Operation::toggle: activate(action.control); break;
            case Operation::expand: openMenu = true; break;
            case Operation::collapse: closeMenu = true; break;
            case Operation::setValue: setNote(action.value); break;
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

void Shell::drawMenus(bool hasViewports)
{
#if defined(_WIN32)
    if (project && project->configured())
    {
        if (ImGui::IsKeyPressed(ImGuiKey_F5, false))
        {
            project->reopen();
        }
        if (ImGui::GetIO().KeyCtrl && ImGui::IsKeyPressed(ImGuiKey_S, false))
        {
            project->save();
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
            menuItem(Control::showResult, "S11 결과", "F7", &resultOpen, true);
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
        requestedFocus == Control::reloadModel)
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
        if (project && project->configured())
        {
            drawLiveBoard();
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
/** @brief 실제 프로젝트와 권위 있는 개정, 기판 장면 및 저장 동작을 같은 패널에 제공한다. */
void Shell::drawLiveBoard()
{
    ImGui::TextUnformatted(project->path().c_str());
    boardButton(Control::toggleModel, modelOpen ? "2D 편집" : "3D 형상", project->view() != nullptr, modelOpen);
    ImGui::SameLine();
    if (modelOpen)
    {
        drawLiveModel();
        return;
    }
    boardButton(Control::reloadProject, "다시 열기", !project->busy());
    ImGui::SameLine();
    auto* view = project->view();
    boardButton(Control::saveProject, "저장", view && project->writable() && view->revision != view->savedRevision);
    ImGui::SameLine();
    boardButton(Control::undoProject, "되돌리기", view && project->writable() && view->canUndo);
    ImGui::SameLine();
    boardButton(Control::resetBoard, "보기 초기화", view != nullptr);

    ImGui::AlignTextToFramePadding();
    ImGui::TextUnformatted("도체 이동 (1 mm)");
    const bool movable = project->canTranslate();
    ImGui::SameLine();
    boardButton(Control::moveLeft, "-X", movable);
    ImGui::SameLine();
    boardButton(Control::moveRight, "+X", movable);
    ImGui::SameLine();
    boardButton(Control::moveDown, "-Y", movable);
    ImGui::SameLine();
    boardButton(Control::moveUp, "+Y", movable);

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
        boardDrawn = drawProjectCanvas(*view, zoom, pan);
    }
}

void Shell::boardButton(Control control, const char* label, bool enabled, bool checked)
{
    ImGui::BeginDisabled(!enabled);
    if (ImGui::SmallButton(label))
    {
        activate(control);
    }
    focusItem(control);
    access.item(control, Control::board, enabled, checked);
    ImGui::EndDisabled();
}

/** @brief 검증한 표시 장면으로만 카메라를 그리고 같은 개정의 원본 선택을 연결한다. */
void Shell::drawLiveModel()
{
    const auto& cad = project->cad();
    const auto& scene = cad.scene();
    boardButton(Control::reloadModel, "3D 다시 읽기", project->writable() && !cad.loading());
    ImGui::SameLine();
    boardButton(Control::resetBoard, "보기 초기화", scene != nullptr);
    model.setScene(scene);
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
    if (requestedFocus == Control::result || requestedFocus == Control::reloadResult)
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
        if (project && project->configured())
        {
            drawLiveResult();
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
/** @brief 현재 프로젝트의 최신 완료 실행에서 고정한 S11 표본과 출처를 표시한다. */
void Shell::drawLiveResult()
{
    const auto& result = project->result();
    const auto& series = result.series();
    if (!series && result.status().empty())
    {
        project->readResult();
    }
    ImGui::BeginDisabled(!project->writable());
    if (ImGui::SmallButton("결과 다시 읽기"))
    {
        activate(Control::reloadResult);
    }
    focusItem(Control::reloadResult);
    access.item(Control::reloadResult, Control::result, project->writable());
    ImGui::EndDisabled();
    if (!series)
    {
        if (!result.status().empty())
        {
            ImGui::TextWrapped("%s", result.status().c_str());
        }
        return;
    }

    const auto* view = project->view();
    const bool current = view && view->revision == series->revision;
    ImGui::SameLine();
    ImGui::Text("결과 개정 %.12s  |  %s  |  %zu개 표본", series->revision.c_str(),
        current ? "현재 설계" : "이전 설계", series->total);
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
    if (!result.status().empty())
    {
        ImGui::TextWrapped("%s", result.status().c_str());
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
            PrototypeProject project(options.openProject, options.service.workspace);
            shell.project = &project;
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
                    project.update(service);
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
                   "--python <python.exe> --source <Code/src> --workspace <path>\n", stderr);
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
