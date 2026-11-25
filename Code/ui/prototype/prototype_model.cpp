#include "prototype_model.h"

#include "../wxwidgets/display_mesh_picking.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <exception>
#include <utility>

#include <bgfx/embedded_shader.h>
#include <bx/math.h>

#include <examples/common/debugdraw/fs_debugdraw_fill_lit.bin.h>
#include <examples/common/debugdraw/vs_debugdraw_fill_lit_mesh.bin.h>

namespace
{
constexpr bgfx::ViewId modelView = 0;
const bgfx::EmbeddedShader shaders[] =
{
    BGFX_EMBEDDED_SHADER(vs_debugdraw_fill_lit_mesh),
    BGFX_EMBEDDED_SHADER(fs_debugdraw_fill_lit),
    BGFX_EMBEDDED_SHADER_END()
};

std::array<float, 4> bodyColour(const std::string& role, bool selected)
{
    if (selected)
    {
        return {0.25f, 0.67f, 1.0f, 1.0f};
    }
    if (role == "conductor")
    {
        return {0.92f, 0.67f, 0.31f, 1.0f};
    }
    if (role == "surface")
    {
        return {0.35f, 0.66f, 0.72f, 1.0f};
    }
    if (role == "environment")
    {
        return {0.66f, 0.60f, 0.77f, 1.0f};
    }
    return {0.37f, 0.69f, 0.54f, 1.0f};
}
}

PrototypeModel::~PrototypeModel()
{
    clearBuffers();
    if (bgfx::isValid(target_))
    {
        bgfx::resetView(modelView);
        bgfx::destroy(target_);
    }
    if (bgfx::isValid(parameters_))
    {
        bgfx::destroy(parameters_);
    }
    if (bgfx::isValid(program_))
    {
        bgfx::destroy(program_);
    }
}

void PrototypeModel::setScene(const PrototypeCad::Scene& scene)
{
    if (scene != scene_)
    {
        clearBuffers();
        scene_ = scene;
        section_.reset();
        error_.clear();
        resetView();
    }
}

void PrototypeModel::resetView()
{
    camera_ = {};
    selected_ = -1;
}

/** @brief 같은 봉인 메시의 잘린 표시 사본을 작업 스레드에서 계산한다. */
void PrototypeModel::setSection(std::optional<PrototypeSection::Plane> plane)
{
    if (pendingSection_.valid())
    {
        return;
    }
    if (!plane)
    {
        section_.reset();
        clearBuffers();
        return;
    }
    if (!scene_ || (section_ && section_->plane == *plane))
    {
        return;
    }
    pendingSection_ = std::async(std::launch::async, [source = scene_, plane = *plane]
    {
        Cut result{source, plane, {}, 0};
        result.positions.reserve(source->bodies.size());
        for (const auto& body : source->bodies)
        {
            auto clipped = PrototypeSection::Clip(body.positions, plane);
            result.triangles += clipped.size() / 9;
            result.positions.push_back(std::move(clipped));
        }
        return result;
    });
}

void PrototypeModel::pollSection()
{
    if (!pendingSection_.valid() ||
        pendingSection_.wait_for(std::chrono::seconds(0)) != std::future_status::ready)
    {
        return;
    }
    try
    {
        auto cut = pendingSection_.get();
        if (cut.source == scene_)
        {
            section_ = std::move(cut);
            selected_ = -1;
            clearBuffers();
        }
    }
    catch (const std::exception& error)
    {
        error_ = std::string("3D 표시 단면을 준비하지 못했습니다. ") + error.what();
    }
}

std::size_t PrototypeModel::visibleTriangles() const
{
    return section_ ? section_->triangles : scene_ ? scene_->triangles : 0;
}

void PrototypeModel::rotate(float dx, float dy)
{
    camera_.Rotate(dx, dy);
}

void PrototypeModel::pan(float dx, float dy, float height)
{
    if (scene_ && height > 0.0f)
    {
        const double units = 2.0 * camera_.HalfHeight(scene_->radius) / height;
        camera_.panX += dx * units;
        camera_.panY -= dy * units;
    }
}

void PrototypeModel::zoom(float steps)
{
    camera_.Zoom(steps);
}

void PrototypeModel::pick(float x, float y, float width, float height)
{
    if (scene_ && height > 0.0f)
    {
        const double units = 2.0 * camera_.HalfHeight(scene_->radius) / height;
        selected_ = DisplayMesh::PickIndexed(*scene_, camera_,
            (x - width / 2.0) * units, (height / 2.0 - y) * units, {}, section_ ? &section_->plane : nullptr);
    }
}

const DisplayMesh::Body* PrototypeModel::selected() const
{
    return scene_ && selected_ >= 0 ? &scene_->bodies[static_cast<std::size_t>(selected_)] : nullptr;
}

bgfx::TextureHandle PrototypeModel::texture() const
{
    return bgfx::isValid(target_) ? bgfx::getTexture(target_) : bgfx::TextureHandle BGFX_INVALID_HANDLE;
}

void PrototypeModel::clearBuffers()
{
    for (const auto buffer : buffers_)
    {
        if (bgfx::isValid(buffer))
        {
            bgfx::destroy(buffer);
        }
    }
    buffers_.clear();
    buffersReady_ = false;
}

/** @brief 검증된 삼각형을 장면 교체 때만 GPU에 올린다. */
bool PrototypeModel::prepare()
{
    if (!bgfx::isValid(program_))
    {
        const auto type = bgfx::getRendererType();
        const auto vertex = bgfx::createEmbeddedShader(shaders, type, "vs_debugdraw_fill_lit_mesh");
        const auto fragment = bgfx::createEmbeddedShader(shaders, type, "fs_debugdraw_fill_lit");
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
        parameters_ = bgfx::createUniform("u_params", bgfx::UniformType::Vec4, 4);
    }
    if (!bgfx::isValid(program_) || !bgfx::isValid(parameters_))
    {
        return false;
    }
    if (!buffersReady_)
    {
        bgfx::VertexLayout layout;
        layout.begin().add(bgfx::Attrib::Position, 3, bgfx::AttribType::Float).end();
        for (std::size_t index = 0; index < scene_->bodies.size(); ++index)
        {
            const auto& positions = section_ ? section_->positions[index] : scene_->bodies[index].positions;
            if (positions.empty())
            {
                buffers_.push_back(bgfx::VertexBufferHandle BGFX_INVALID_HANDLE);
                continue;
            }
            const auto bytes = static_cast<std::uint32_t>(positions.size() * sizeof(float));
            const auto buffer = bgfx::createVertexBuffer(bgfx::copy(positions.data(), bytes), layout);
            if (!bgfx::isValid(buffer))
            {
                clearBuffers();
                return false;
            }
            buffers_.push_back(buffer);
        }
        buffersReady_ = true;
    }
    return true;
}

/** @brief UI에 보낼 색상과 별도의 깊이 첨부를 함께 만들고 전부 성공했을 때 교체한다. */
bool PrototypeModel::resize(std::uint16_t width, std::uint16_t height)
{
    if (width == width_ && height == height_ && bgfx::isValid(target_))
    {
        return true;
    }
    constexpr auto colourFlags = BGFX_TEXTURE_RT | BGFX_SAMPLER_U_CLAMP | BGFX_SAMPLER_V_CLAMP;
    constexpr auto depthFlags = BGFX_TEXTURE_RT_WRITE_ONLY;
    constexpr auto colourFormat = bgfx::TextureFormat::BGRA8;
    constexpr auto depthFormat = bgfx::TextureFormat::D24S8;
    if (!bgfx::isTextureValid(0, false, 1, colourFormat, colourFlags) ||
        !bgfx::isTextureValid(0, false, 1, depthFormat, depthFlags))
    {
        return false;
    }
    const std::array attachments
    {
        bgfx::createTexture2D(width, height, false, 1, colourFormat, colourFlags),
        bgfx::createTexture2D(width, height, false, 1, depthFormat, depthFlags)
    };
    if (!bgfx::isValid(attachments[0]) || !bgfx::isValid(attachments[1]))
    {
        for (const auto attachment : attachments)
        {
            if (bgfx::isValid(attachment))
            {
                bgfx::destroy(attachment);
            }
        }
        return false;
    }
    const auto next = bgfx::createFrameBuffer(2, attachments.data(), true);
    if (!bgfx::isValid(next))
    {
        for (const auto attachment : attachments)
        {
            bgfx::destroy(attachment);
        }
        return false;
    }
    if (bgfx::isValid(target_))
    {
        bgfx::destroy(target_);
    }
    target_ = next;
    width_ = width;
    height_ = height;
    return true;
}

/** @brief 선택 계산과 같은 카메라를 쓰고 앞쪽 삼각형을 깊이 첨부에 남긴다. */
void PrototypeModel::submit(std::uint16_t width, std::uint16_t height, const std::string& source)
{
    if (!scene_ || !error_.empty())
    {
        return;
    }
    if (!prepare() || !resize(width, height))
    {
        error_ = "3D 화면 버퍼를 준비하지 못했습니다.";
        return;
    }
    const auto origin = camera_.Transform({});
    const auto a = camera_.Transform({1, 0, 0});
    const auto b = camera_.Transform({0, 1, 0});
    const auto c = camera_.Transform({0, 0, 1});
    const float view[16] =
    {
        float(a.x - origin.x), float(a.y - origin.y), float(a.z), 0.0f,
        float(b.x - origin.x), float(b.y - origin.y), float(b.z), 0.0f,
        float(c.x - origin.x), float(c.y - origin.y), float(c.z), 0.0f,
        float(origin.x), float(origin.y), 0.0f, 1.0f
    };
    const auto halfHeight = static_cast<float>(camera_.HalfHeight(scene_->radius));
    const auto halfWidth = halfHeight * width / height;
    const auto depth = static_cast<float>(scene_->radius * 4.0);
    float projection[16];
    bx::mtxOrtho(projection, -halfWidth, halfWidth, -halfHeight, halfHeight, -depth, depth,
        0.0f, bgfx::getCaps()->homogeneousDepth, bx::Handedness::Right);
    bgfx::setViewName(modelView, "CAD display mesh");
    bgfx::setViewFrameBuffer(modelView, target_);
    bgfx::setViewRect(modelView, 0, 0, width, height);
    bgfx::setViewTransform(modelView, view, projection);
    bgfx::setViewClear(modelView, BGFX_CLEAR_COLOR | BGFX_CLEAR_DEPTH, 0x111a23ff, 1.0f);
    bgfx::touch(modelView);

    for (std::size_t index = 0; index < buffers_.size(); ++index)
    {
        const auto& body = scene_->bodies[index];
        if (!bgfx::isValid(buffers_[index]) || !DisplayMesh::MayIntersectView(*scene_, index, camera_, halfWidth, halfHeight))
        {
            continue;
        }
        const bool highlighted = static_cast<int>(index) == selected_ ||
            (!source.empty() && std::find(body.sources.begin(), body.sources.end(), source) != body.sources.end());
        const std::array<std::array<float, 4>, 4> lighting
        {{
            {0.3f, 0.4f, 0.85f, 0.0f},
            {1.0f, 1.0f, 1.0f, 0.0f},
            {0.48f, 0.48f, 0.48f, 0.0f},
            bodyColour(body.role, highlighted)
        }};
        bgfx::setUniform(parameters_, lighting.data(), 4);
        bgfx::setVertexBuffer(0, buffers_[index]);
        bgfx::setState(BGFX_STATE_WRITE_RGB | BGFX_STATE_WRITE_A | BGFX_STATE_WRITE_Z | BGFX_STATE_DEPTH_TEST_LESS);
        bgfx::submit(modelView, program_);
    }
}
