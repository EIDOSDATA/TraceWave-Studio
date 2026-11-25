#pragma once

#include <array>
#include <cstdint>

#include <SDL3/SDL_video.h>
#include <bgfx/bgfx.h>

struct ImDrawData;
struct ImGuiViewport;

/** @brief SDL 창의 기본 및 분리 스왑 체인에 ImGui 그리기 명령을 제출한다. */
class Renderer
{
public:
    Renderer() = default;
    ~Renderer();
    Renderer(const Renderer&) = delete;
    Renderer& operator=(const Renderer&) = delete;

    bool initialize(SDL_Window* window);
    bool attachWidgets();
    void detachWidgets();
    static constexpr std::uint64_t modelTextureId = 2;

    void renderFrame(bgfx::TextureHandle modelTexture = BGFX_INVALID_HANDLE);

    const char* name() const;
    bool hasViewports() const;
    bool healthy() const { return !failed_; }
    unsigned secondaryFrames() const { return secondaryFrames_; }

private:
    struct Surface
    {
        SDL_Window* window = nullptr;
        bgfx::SwapChain chain;
        bgfx::FrameBufferHandle buffer = BGFX_INVALID_HANDLE;
    };

    static void createViewport(ImGuiViewport* viewport);
    static void destroyViewport(ImGuiViewport* viewport);
    static void renderViewport(ImGuiViewport* viewport, void*);
    bool renderDrawData(const ImDrawData& data, bgfx::ViewId id, const Surface& surface);

    Surface main_;
    std::array<Surface, 15> secondary_;
    bgfx::VertexLayout layout_;
    bgfx::ProgramHandle program_ = BGFX_INVALID_HANDLE;
    bgfx::UniformHandle sampler_ = BGFX_INVALID_HANDLE;
    bgfx::TextureHandle font_ = BGFX_INVALID_HANDLE;
    bgfx::TextureHandle modelTexture_ = BGFX_INVALID_HANDLE;
    bool initialized_ = false;
    bool failed_ = false;
    unsigned secondaryFrames_ = 0;
};
