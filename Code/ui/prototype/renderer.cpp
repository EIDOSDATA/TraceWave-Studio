#include "renderer.h"

#include <algorithm>
#include <cstdio>
#include <cstring>

#include <SDL3/SDL.h>
#include <bgfx/embedded_shader.h>
#include <bx/math.h>
#include <imgui.h>

#include <examples/common/imgui/fs_ocornut_imgui.bin.h>
#include <examples/common/imgui/vs_ocornut_imgui.bin.h>

namespace
{
constexpr ImTextureID fontTextureId = 1;
constexpr auto resetFlags = BGFX_RESET_VSYNC;
constexpr auto viewClear = 0x141b24ff;

const bgfx::EmbeddedShader shaders[] = {
    BGFX_EMBEDDED_SHADER(vs_ocornut_imgui),
    BGFX_EMBEDDED_SHADER(fs_ocornut_imgui),
    BGFX_EMBEDDED_SHADER_END()
};

/** @brief SDL이 소유한 표면 핸들을 bgfx의 플랫폼 계약에 맞춘다. */
bgfx::SwapChain nativeChain(SDL_Window* window)
{
    const SDL_PropertiesID properties = SDL_GetWindowProperties(window);
    bgfx::SwapChain data;
    data.flags = BGFX_SWAP_CHAIN_HIDPI;
#if defined(_WIN32)
    data.nwh = SDL_GetPointerProperty(properties, SDL_PROP_WINDOW_WIN32_HWND_POINTER, nullptr);
#elif defined(__APPLE__)
    data.nwh = SDL_GetPointerProperty(properties, SDL_PROP_WINDOW_COCOA_WINDOW_POINTER, nullptr);
#else
    const char* driver = SDL_GetCurrentVideoDriver();
    if (driver && std::strcmp(driver, "wayland") == 0)
    {
        data.nwh = SDL_GetPointerProperty(properties, SDL_PROP_WINDOW_WAYLAND_SURFACE_POINTER, nullptr);
        data.ndt = SDL_GetPointerProperty(properties, SDL_PROP_WINDOW_WAYLAND_DISPLAY_POINTER, nullptr);
    }
    else
    {
        const auto xid = SDL_GetNumberProperty(properties, SDL_PROP_WINDOW_X11_WINDOW_NUMBER, 0);
        data.nwh = reinterpret_cast<void*>(static_cast<std::uintptr_t>(xid));
        data.ndt = SDL_GetPointerProperty(properties, SDL_PROP_WINDOW_X11_DISPLAY_POINTER, nullptr);
    }
#endif
    return data;
}

SDL_Window* viewportWindow(ImGuiViewport* viewport)
{
    return SDL_GetWindowFromID(static_cast<SDL_WindowID>(
        reinterpret_cast<std::uintptr_t>(viewport->PlatformHandle)));
}

/** @brief 좌표와 별도로 실제 픽셀 크기를 읽고 최소화된 표면을 건너뛴다. */
bool pixelSize(SDL_Window* window, bgfx::SwapChain& chain)
{
    int width = 0;
    int height = 0;
    if ((SDL_GetWindowFlags(window) & SDL_WINDOW_MINIMIZED)
        || !SDL_GetWindowSizeInPixels(window, &width, &height)
        || width < 1 || height < 1 || width > UINT16_MAX || height > UINT16_MAX)
    {
        return false;
    }
    chain.width = static_cast<std::uint32_t>(width);
    chain.height = static_cast<std::uint32_t>(height);
    return true;
}

Renderer& currentRenderer()
{
    return *static_cast<Renderer*>(ImGui::GetIO().BackendRendererUserData);
}
}

Renderer::~Renderer()
{
    if (initialized_)
    {
        bgfx::shutdown();
    }
}

bool Renderer::initialize(SDL_Window* window)
{
    main_.window = window;
    main_.chain = nativeChain(window);
    if (!main_.chain.nwh || !pixelSize(window, main_.chain))
    {
        std::fputs("Missing native window or framebuffer size.\n", stderr);
        return false;
    }

    bgfx::Init init;
#if defined(__APPLE__)
    init.type = bgfx::RendererType::Metal;
#else
    init.type = bgfx::RendererType::Vulkan;
#endif
#if defined(__linux__)
    if (std::strcmp(SDL_GetCurrentVideoDriver(), "wayland") == 0)
    {
        init.platformData.type = bgfx::NativeWindowHandleType::Wayland;
    }
#endif
    init.swapChain = main_.chain;
    init.reset = resetFlags;
    init.fallback = false;
    initialized_ = bgfx::init(init);
    if (!initialized_ || bgfx::getRendererType() != init.type)
    {
        std::fprintf(stderr, "Unable to start requested renderer: %s\n", bgfx::getRendererName(init.type));
        return false;
    }
    return true;
}

bool Renderer::attachWidgets()
{
    ImGuiIO& io = ImGui::GetIO();
    io.BackendRendererName = "TraceWave bgfx";
    io.BackendRendererUserData = this;
    io.BackendFlags |= ImGuiBackendFlags_RendererHasVtxOffset;

    layout_.begin()
        .add(bgfx::Attrib::Position, 2, bgfx::AttribType::Float)
        .add(bgfx::Attrib::TexCoord0, 2, bgfx::AttribType::Float)
        .add(bgfx::Attrib::Color0, 4, bgfx::AttribType::Uint8, true)
        .end();
    static_assert(sizeof(ImDrawVert) == 20);

    const auto type = bgfx::getRendererType();
    const auto vertex = bgfx::createEmbeddedShader(shaders, type, "vs_ocornut_imgui");
    const auto fragment = bgfx::createEmbeddedShader(shaders, type, "fs_ocornut_imgui");
    if (!bgfx::isValid(vertex) || !bgfx::isValid(fragment))
    {
        if (bgfx::isValid(vertex))
        {
            bgfx::destroy(vertex);
        }
        if (bgfx::isValid(fragment))
        {
            bgfx::destroy(fragment);
        }
        return false;
    }
    program_ = bgfx::createProgram(vertex, fragment, true);
    sampler_ = bgfx::createUniform("s_tex", bgfx::UniformType::Sampler);

    unsigned char* pixels = nullptr;
    int width = 0;
    int height = 0;
    io.Fonts->GetTexDataAsRGBA32(&pixels, &width, &height);
    const auto maxSize = bgfx::getCaps()->limits.maxTextureSize;
    if (!pixels || width < 1 || height < 1
        || static_cast<unsigned>(width) > maxSize || static_cast<unsigned>(height) > maxSize)
    {
        return false;
    }
    font_ = bgfx::createTexture2D(static_cast<std::uint16_t>(width), static_cast<std::uint16_t>(height),
        false, 1, bgfx::TextureFormat::RGBA8, BGFX_SAMPLER_U_CLAMP | BGFX_SAMPLER_V_CLAMP,
        bgfx::copy(pixels, static_cast<std::uint32_t>(width) * static_cast<std::uint32_t>(height) * 4));
    io.Fonts->SetTexID(fontTextureId);
    io.Fonts->ClearTexData();

    if (hasViewports())
    {
        ImGuiPlatformIO& platform = ImGui::GetPlatformIO();
        platform.Renderer_CreateWindow = createViewport;
        platform.Renderer_DestroyWindow = destroyViewport;
        platform.Renderer_RenderWindow = renderViewport;
        io.BackendFlags |= ImGuiBackendFlags_RendererHasViewports;
    }
    return bgfx::isValid(program_) && bgfx::isValid(sampler_) && bgfx::isValid(font_);
}

void Renderer::detachWidgets()
{
    ImGui::DestroyPlatformWindows();
    ImGuiPlatformIO& platform = ImGui::GetPlatformIO();
    platform.Renderer_CreateWindow = nullptr;
    platform.Renderer_DestroyWindow = nullptr;
    platform.Renderer_RenderWindow = nullptr;

    ImGuiIO& io = ImGui::GetIO();
    io.BackendFlags &= ~(ImGuiBackendFlags_RendererHasVtxOffset | ImGuiBackendFlags_RendererHasViewports);
    io.BackendRendererName = nullptr;
    io.BackendRendererUserData = nullptr;
    io.Fonts->SetTexID(0);
    if (bgfx::isValid(font_))
    {
        bgfx::destroy(font_);
    }
    if (bgfx::isValid(sampler_))
    {
        bgfx::destroy(sampler_);
    }
    if (bgfx::isValid(program_))
    {
        bgfx::destroy(program_);
    }
}

const char* Renderer::name() const
{
    return bgfx::getRendererName(bgfx::getRendererType());
}

bool Renderer::hasViewports() const
{
    return (bgfx::getCaps()->supported & BGFX_CAPS_SWAP_CHAIN)
        && (ImGui::GetIO().BackendFlags & ImGuiBackendFlags_PlatformHasViewports);
}

void Renderer::renderFrame()
{
    const ImGuiIO& io = ImGui::GetIO();
    const bool viewports = (io.ConfigFlags & ImGuiConfigFlags_ViewportsEnable) != 0;
    if (viewports)
    {
        ImGui::UpdatePlatformWindows();
    }

    auto chain = main_.chain;
    if (pixelSize(main_.window, chain))
    {
        if (chain.width != main_.chain.width || chain.height != main_.chain.height)
        {
            bgfx::reset(resetFlags, &chain);
            main_.chain = chain;
        }
        renderDrawData(*ImGui::GetDrawData(), 0, main_);
    }
    if (viewports)
    {
        ImGui::RenderPlatformWindowsDefault();
    }
    bgfx::frame();
}

/** @brief 분리 창마다 화면 버퍼와 bgfx 뷰 번호를 배정한다. */
void Renderer::createViewport(ImGuiViewport* viewport)
{
    Renderer& renderer = currentRenderer();
    const auto found = std::find_if(renderer.secondary_.begin(), renderer.secondary_.end(),
        [](const Surface& surface) { return !surface.window; });
    SDL_Window* window = viewportWindow(viewport);
    if (window && found != renderer.secondary_.end())
    {
        auto chain = nativeChain(window);
        if (chain.nwh && pixelSize(window, chain))
        {
            found->buffer = bgfx::createFrameBuffer(chain);
            if (bgfx::isValid(found->buffer))
            {
                found->window = window;
                found->chain = chain;
                viewport->RendererUserData = &*found;
                return;
            }
        }
    }
    renderer.failed_ = true;
    std::fputs("Unable to create a secondary swap chain.\n", stderr);
}

/** @brief SDL 창이 닫히기 전에 분리 스왑 체인을 렌더러에서 해제한다. */
void Renderer::destroyViewport(ImGuiViewport* viewport)
{
    auto* surface = static_cast<Surface*>(viewport->RendererUserData);
    if (surface)
    {
        auto& renderer = currentRenderer();
        const auto id = static_cast<bgfx::ViewId>(surface - renderer.secondary_.data() + 1);
        bgfx::resetView(id);
        bgfx::destroy(surface->buffer);
        bgfx::frame();
        *surface = Surface{};
        viewport->RendererUserData = nullptr;
    }
}

void Renderer::renderViewport(ImGuiViewport* viewport, void*)
{
    auto* surface = static_cast<Surface*>(viewport->RendererUserData);
    if (!surface)
    {
        return;
    }
    auto chain = surface->chain;
    if (!pixelSize(surface->window, chain))
    {
        return;
    }
    auto& renderer = currentRenderer();
    if (chain.width != surface->chain.width || chain.height != surface->chain.height)
    {
        bgfx::updateSwapChain(surface->buffer, chain);
        surface->chain = chain;
    }
    const auto id = static_cast<bgfx::ViewId>(surface - renderer.secondary_.data() + 1);
    if (renderer.renderDrawData(*viewport->DrawData, id, *surface))
    {
        ++renderer.secondaryFrames_;
    }
}

/** @brief 논리 좌표에서 투영하고 각 명령의 클립 영역을 표면 픽셀로 변환한다. */
bool Renderer::renderDrawData(const ImDrawData& data, bgfx::ViewId id, const Surface& surface)
{
    if (data.DisplaySize.x <= 0 || data.DisplaySize.y <= 0)
    {
        return false;
    }
    const auto width = static_cast<std::uint16_t>(surface.chain.width);
    const auto height = static_cast<std::uint16_t>(surface.chain.height);
    const float scaleX = width / data.DisplaySize.x;
    const float scaleY = height / data.DisplaySize.y;
    const float left = data.DisplayPos.x;
    const float top = data.DisplayPos.y;
    float projection[16];
    bx::mtxOrtho(projection, left, left + data.DisplaySize.x, top + data.DisplaySize.y, top,
        0.0f, 1000.0f, 0.0f, bgfx::getCaps()->homogeneousDepth);
    bgfx::setViewFrameBuffer(id, surface.buffer);
    bgfx::setViewMode(id, bgfx::ViewMode::Sequential);
    bgfx::setViewClear(id, BGFX_CLEAR_COLOR, viewClear);
    bgfx::setViewRect(id, 0, 0, width, height);
    bgfx::setViewTransform(id, nullptr, projection);
    bgfx::touch(id);

    bool submitted = false;
    for (const ImDrawList* list : data.CmdLists)
    {
        bgfx::TransientVertexBuffer vertices;
        bgfx::TransientIndexBuffer indices;
        const auto vertexCount = static_cast<std::uint32_t>(list->VtxBuffer.Size);
        const auto indexCount = static_cast<std::uint32_t>(list->IdxBuffer.Size);
        if (!vertexCount || !indexCount)
        {
            continue;
        }
        if (!bgfx::allocTransientBuffers(&vertices, layout_, vertexCount, &indices, indexCount,
            sizeof(ImDrawIdx) == 4))
        {
            failed_ = true;
            std::fputs("UI exceeded the bgfx transient buffer budget.\n", stderr);
            break;
        }
        std::memcpy(vertices.data, list->VtxBuffer.Data, vertexCount * sizeof(ImDrawVert));
        std::memcpy(indices.data, list->IdxBuffer.Data, indexCount * sizeof(ImDrawIdx));

        for (const ImDrawCmd& command : list->CmdBuffer)
        {
            if (command.UserCallback)
            {
                if (command.UserCallback != ImDrawCallback_ResetRenderState)
                {
                    command.UserCallback(list, &command);
                }
                continue;
            }
            if (command.GetTexID() != fontTextureId || !command.ElemCount)
            {
                continue;
            }
            const auto x1 = std::clamp((command.ClipRect.x - left) * scaleX, 0.0f, float(width));
            const auto y1 = std::clamp((command.ClipRect.y - top) * scaleY, 0.0f, float(height));
            const auto x2 = std::clamp((command.ClipRect.z - left) * scaleX, 0.0f, float(width));
            const auto y2 = std::clamp((command.ClipRect.w - top) * scaleY, 0.0f, float(height));
            const auto x = static_cast<std::uint16_t>(x1);
            const auto y = static_cast<std::uint16_t>(y1);
            const int clipWidth = static_cast<std::uint16_t>(x2) - x;
            const int clipHeight = static_cast<std::uint16_t>(y2) - y;
            if (clipWidth <= 0 || clipHeight <= 0)
            {
                continue;
            }
            bgfx::setScissor(x, y, static_cast<std::uint16_t>(clipWidth), static_cast<std::uint16_t>(clipHeight));
            bgfx::setState(BGFX_STATE_WRITE_RGB | BGFX_STATE_WRITE_A | BGFX_STATE_MSAA
                | BGFX_STATE_BLEND_FUNC(BGFX_STATE_BLEND_SRC_ALPHA, BGFX_STATE_BLEND_INV_SRC_ALPHA));
            bgfx::setTexture(0, sampler_, font_);
            bgfx::setVertexBuffer(0, &vertices, command.VtxOffset, vertexCount - command.VtxOffset);
            bgfx::setIndexBuffer(&indices, command.IdxOffset, command.ElemCount);
            bgfx::submit(id, program_);
            submitted = true;
        }
    }
    return submitted;
}
