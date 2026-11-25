/** @file @brief 검증된 CAD 메시의 깊이 렌더링과 화면 선택을 관리한다. */
#pragma once

#include "prototype_cad.h"
#include "prototype_section.h"

#include <bgfx/bgfx.h>

class PrototypeModel
{
public:
    PrototypeModel() = default;
    ~PrototypeModel();
    PrototypeModel(const PrototypeModel&) = delete;
    PrototypeModel& operator=(const PrototypeModel&) = delete;

    void setScene(const PrototypeCad::Scene& scene);
    void resetView();
    void setSection(std::optional<PrototypeSection::Plane> plane);
    void pollSection();
    bool sectionPending() const { return pendingSection_.valid(); }
    std::size_t visibleTriangles() const;
    const PrototypeSection::Plane* sectionPlane() const { return section_ ? &section_->plane : nullptr; }
    void submit(std::uint16_t width, std::uint16_t height, const std::string& source);
    void rotate(float dx, float dy);
    void pan(float dx, float dy, float height);
    void zoom(float steps);
    void pick(float x, float y, float width, float height);

    bgfx::TextureHandle texture() const;
    const DisplayMesh::Body* selected() const;
    const std::string& error() const { return error_; }

private:
    bool prepare();
    bool resize(std::uint16_t width, std::uint16_t height);
    void clearBuffers();

    struct Cut
    {
        PrototypeCad::Scene source;
        PrototypeSection::Plane plane;
        std::vector<std::vector<float>> positions;
        std::size_t triangles = 0;
    };
    PrototypeCad::Scene scene_;
    std::optional<Cut> section_;
    std::future<Cut> pendingSection_;
    bool buffersReady_ = false;
    DisplayMesh::Camera camera_;
    std::vector<bgfx::VertexBufferHandle> buffers_;
    bgfx::FrameBufferHandle target_ = BGFX_INVALID_HANDLE;
    bgfx::ProgramHandle program_ = BGFX_INVALID_HANDLE;
    bgfx::UniformHandle parameters_ = BGFX_INVALID_HANDLE;
    std::uint16_t width_ = 0;
    std::uint16_t height_ = 0;
    int selected_ = -1;
    std::string error_;
};
