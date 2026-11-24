#include "b0_samples.h"
#include "renderer.h"

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
constexpr char committedText[] = "한글 검수";
constexpr char editingText[] = "한";
constexpr int initialWidth = 1120;
constexpr int initialHeight = 720;

struct Options
{
    bool smoke = false;
    const char* font = nullptr;
};

struct Shell
{
    bool boardOpen = true;
    bool resultOpen = true;
    bool inputOpen = true;
    bool focusInput = false;
    bool detachResult = false;
    bool undockNextFrame = false;
    bool resetLayout = false;
    bool noteActive = false;
    bool plotDrawn = false;
    bool boardDrawn = false;
    std::array<char, 256> note{};
    std::string preedit;
    SDL_WindowID preeditWindow = 0;
    float zoom = 1.0f;
    ImVec2 pan{};

    void processEvent(const SDL_Event& event);
    void draw(const Renderer& renderer, SDL_Window* mainWindow, bool koreanFont);
    void drawMenus(bool hasViewports);
    void drawBoard();
    void drawResult(bool hasViewports);
    void drawInput();
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
        else
        {
            return false;
        }
    }
    return true;
}

ImFont* installFont(const char* requested)
{
    ImGuiIO& io = ImGui::GetIO();
    ImFontConfig config;
    config.RasterizerDensity = 2.0f;
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
    if (requested)
    {
        SDL_PathInfo info;
        if (!SDL_GetPathInfo(requested, &info) || info.type != SDL_PATHTYPE_FILE)
        {
            std::fprintf(stderr, "Font file is unavailable: %s\n", requested);
            return nullptr;
        }
        return io.Fonts->AddFontFromFileTTF(requested, 18.0f, &config, io.Fonts->GetGlyphRangesKorean());
    }
    for (const char* candidate : candidates)
    {
        SDL_PathInfo info;
        if (SDL_GetPathInfo(candidate, &info) && info.type == SDL_PATHTYPE_FILE)
        {
            return io.Fonts->AddFontFromFileTTF(candidate, 18.0f, &config, io.Fonts->GetGlyphRangesKorean());
        }
    }
    return io.Fonts->AddFontDefault();
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

void Shell::processEvent(const SDL_Event& event)
{
    if (event.type == SDL_EVENT_TEXT_EDITING)
    {
        preedit = event.edit.text ? event.edit.text : "";
        preeditWindow = preedit.empty() ? 0 : event.edit.windowID;
    }
    else if ((event.type == SDL_EVENT_TEXT_INPUT && preeditWindow == event.text.windowID)
        || (event.type == SDL_EVENT_WINDOW_FOCUS_LOST && preeditWindow == event.window.windowID))
    {
        preedit.clear();
        preeditWindow = 0;
    }
}

void Shell::drawMenus(bool hasViewports)
{
    if (ImGui::IsKeyPressed(ImGuiKey_F6, false))
    {
        focusInput = true;
    }
    if (ImGui::IsKeyPressed(ImGuiKey_F7, false))
    {
        resultOpen = !resultOpen;
    }
    if (hasViewports && ImGui::IsKeyPressed(ImGuiKey_F8, false))
    {
        resultOpen = detachResult = undockNextFrame = true;
    }
    if (ImGui::IsKeyPressed(ImGuiKey_F9, false))
    {
        resetLayout = true;
    }

    if (ImGui::BeginMainMenuBar())
    {
        if (ImGui::BeginMenu("창"))
        {
            ImGui::MenuItem("기판", nullptr, &boardOpen);
            ImGui::MenuItem("S11 결과", "F7", &resultOpen);
            if (ImGui::MenuItem("입력에 초점", "F6"))
            {
                focusInput = true;
            }
            if (ImGui::MenuItem("결과를 별도 창으로", "F8", false, hasViewports))
            {
                resultOpen = detachResult = undockNextFrame = true;
            }
            if (ImGui::MenuItem("기본 배치 복원", "F9"))
            {
                resetLayout = true;
            }
            ImGui::EndMenu();
        }
        ImGui::EndMainMenuBar();
    }
}

void Shell::draw(const Renderer& renderer, SDL_Window* mainWindow, bool koreanFont)
{
    const bool hasViewports = renderer.hasViewports();
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
        }
    }
    ImGui::DockSpaceOverViewport(dockspace);
    plotDrawn = boardDrawn = false;
    drawBoard();
    drawResult(hasViewports);
    drawInput();

    if (ImGui::BeginViewportSideBar("###status", ImGui::GetMainViewport(), ImGuiDir_Down,
        ImGui::GetFrameHeight(), ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoSavedSettings))
    {
        int pixelWidth = 0;
        int pixelHeight = 0;
        SDL_GetWindowSizeInPixels(mainWindow, &pixelWidth, &pixelHeight);
        ImGui::Text("%s  |  %s  |  %d × %d px  |  %.0f%%", renderer.name(), SDL_GetCurrentVideoDriver(),
            pixelWidth, pixelHeight, 100.0f * SDL_GetWindowDisplayScale(mainWindow));
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
    if (ImGui::Begin(boardTitle, &boardOpen))
    {
        ImGui::TextUnformatted("원형 PCB 표시 예제");
        ImGui::SameLine();
        if (ImGui::SmallButton("보기 초기화"))
        {
            zoom = 1.0f;
            pan = {};
        }
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
    if (ImGui::Begin(resultTitle, &resultOpen))
    {
        if (ImGui::IsWindowDocked())
        {
            detachResult = false;
        }
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

void Shell::drawInput()
{
    noteActive = false;
    if (focusInput)
    {
        inputOpen = true;
        ImGui::SetNextWindowFocus();
    }
    if (!inputOpen)
    {
        return;
    }
    if (ImGui::Begin(inputTitle, &inputOpen))
    {
        ImGui::TextUnformatted("검수 메모");
        ImGui::SetNextItemWidth(-1.0f);
        if (focusInput)
        {
            ImGui::SetKeyboardFocusHere();
        }
        ImGui::InputText("###note", note.data(), note.size());
        noteActive = ImGui::IsItemActive();
        if (noteActive && !preedit.empty() && preeditWindow == windowId(ImGui::GetWindowViewport()))
        {
            ImGui::Text("조합 중  %s", preedit.c_str());
        }
        if (ImGui::Button("메모 지우기"))
        {
            note.fill('\0');
        }
    }
    ImGui::End();
    focusInput = false;
}

bool queueKey(Uint32 type, SDL_WindowID window, SDL_Scancode scan)
{
    SDL_Event event{};
    event.type = type;
    event.key.windowID = window;
    event.key.scancode = scan;
    event.key.key = SDL_GetKeyFromScancode(scan, SDL_KMOD_NONE, false);
    event.key.down = type == SDL_EVENT_KEY_DOWN;
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
            {
                SDL_Event event{};
                event.type = SDL_EVENT_TEXT_EDITING;
                event.edit.windowID = windowID;
                event.edit.text = editingText;
                check(SDL_PushEvent(&event), "synthetic SDL composition queued");
                break;
            }
            case 11:
            {
                SDL_Event event{};
                event.type = SDL_EVENT_TEXT_INPUT;
                event.text.windowID = windowID;
                event.text.text = committedText;
                check(SDL_PushEvent(&event), "synthetic SDL UTF-8 commit queued");
                break;
            }
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
            default:
                break;
        }
        ++frame;
    }

    SDL_Window* window;
    SDL_WindowID windowID;
    SDL_WindowID secondaryID = 0;
    SDL_DisplayID movedDisplay = 0;
    float secondaryScale = 0.0f;
    unsigned secondaryFrames = 0;
    int frame = 0;
    bool hasViewports;
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
            if (options.smoke)
            {
                std::printf("Renderer=%s video=%s device=0x%04x viewports=%s\n", renderer.name(),
                    SDL_GetCurrentVideoDriver(), bgfx::getCaps()->deviceId, smoke.hasViewports ? "yes" : "no");
                smoke.check(korean, "Hangul glyph in font atlas");
            }

            const auto mainID = SDL_GetWindowID(window);
            bool closing = false;
            while (!closing && (!options.smoke || smoke.frame < 57) && renderer.healthy())
            {
                if (options.smoke)
                {
                    smoke.beforeEvents();
                }
                SDL_Event event;
                while (SDL_PollEvent(&event))
                {
                    ImGui_ImplSDL3_ProcessEvent(&event);
                    shell.processEvent(event);
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
                    shell.draw(renderer, window, korean);
                    ImGui::Render();
                    renderer.renderFrame();
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
                smoke.check(closing && smoke.frame == 52, "normal main window shutdown");
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

int main(int argc, char** argv)
{
    Options options;
    if (!parseOptions(argc, argv, options))
    {
        std::fputs("Usage: tracewave_shell_prototype [--smoke] [--font <font-file>]\n", stderr);
        return 2;
    }
    SDL_SetMainReady();
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
