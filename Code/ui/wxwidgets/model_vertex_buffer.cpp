/** @file @brief 위치와 법선을 다시 전송하지 않고 동일한 검증된 메시로 그린다. */
#include "model_vertex_buffer.h"
#include "display_mesh.h"

#include <cstdint>
#include <cstring>
#include <new>
#include <utility>

namespace
{
constexpr GLenum ArrayBuffer = 0x8892;
constexpr GLenum StaticDraw = 0x88e4;
constexpr std::size_t MaxBytes = DisplayMesh::MaxTriangles * 3 * 3 * 2 * sizeof(GLfloat);

/** @brief 해당 context가 제공한 확장 주소만 사용한다. */
template<typename Function>
Function Address(const char* name)
{
    const auto proc = wglGetProcAddress(name);
    const auto value = reinterpret_cast<std::uintptr_t>(proc);
    if (value <= 3 || value == UINTPTR_MAX)
    {
        return nullptr;
    }
    // @brief Windows가 같은 context에 돌려준 주소를 명세의 호출 형식으로 옮긴다.
    Function address = nullptr;
    static_assert(sizeof(address) == sizeof(proc));
    std::memcpy(&address, &proc, sizeof(address));
    return address;
}

/** @brief 업로드 중 오류는 제한된 횟수만 읽고 CPU 배열로 다시 그릴 수 있게 한다. */
bool UploadSucceeded()
{
    GLenum error = glGetError();
    const bool succeeded = error == GL_NO_ERROR;
    for (unsigned attempt = 0; error != GL_NO_ERROR && attempt < 7; ++attempt)
    {
        error = glGetError();
    }
    return succeeded;
}
}

void ModelVertexBuffer::Invalidate()
{
    m_dirty = true;
}

void ModelVertexBuffer::ContextDiscarded()
{
    m_gl = {};
    m_ranges.clear();
    m_buffer = 0;
    m_bytes = 0;
    m_resolved = false;
    Invalidate();
}

bool ModelVertexBuffer::Bind(const DisplayMesh::Scene& scene)
{
    if (m_dirty)
    {
        Release();
        m_dirty = false;
        if (!m_resolved)
        {
            m_gl = {Address<decltype(m_gl.generate)>("glGenBuffers"), Address<decltype(m_gl.remove)>("glDeleteBuffers"),
                    Address<decltype(m_gl.bind)>("glBindBuffer"), Address<decltype(m_gl.allocate)>("glBufferData"),
                    Address<decltype(m_gl.write)>("glBufferSubData")};
            m_resolved = true;
        }
        if (m_gl.generate && m_gl.remove && m_gl.bind && m_gl.allocate && m_gl.write)
        {
            try
            {
                Upload(scene);
            }
            catch (const std::bad_alloc&)
            {
                // @brief 오프셋은 GPU 할당 전에 준비하므로 기존 CPU 배열 경로를 바로 사용할 수 있다.
            }
        }
    }
    if (m_buffer == 0)
    {
        return false;
    }
    m_gl.bind(ArrayBuffer, m_buffer);
    return true;
}

void ModelVertexBuffer::Upload(const DisplayMesh::Scene& scene)
{
    std::size_t bytes = 0;
    std::vector<Range> ranges;
    ranges.reserve(scene.bodies.size());
    for (const auto& body : scene.bodies)
    {
        if (body.positions.size() != body.normals.size() ||
            body.positions.size() > (MaxBytes - bytes) / (2 * sizeof(GLfloat)))
        {
            return;
        }
        const std::size_t stride = body.positions.size() * sizeof(GLfloat);
        ranges.push_back({bytes, bytes + stride});
        bytes += 2 * stride;
    }
    if (bytes == 0)
    {
        return;
    }
    m_gl.generate(1, &m_buffer);
    if (!UploadSucceeded() || m_buffer == 0)
    {
        Release();
        return;
    }
    m_gl.bind(ArrayBuffer, m_buffer);
    m_gl.allocate(ArrayBuffer, static_cast<std::ptrdiff_t>(bytes), nullptr, StaticDraw);
    if (UploadSucceeded())
    {
        for (std::size_t index = 0; index < scene.bodies.size(); ++index)
        {
            const auto& body = scene.bodies[index];
            const auto length = static_cast<std::ptrdiff_t>(body.positions.size() * sizeof(GLfloat));
            m_gl.write(ArrayBuffer, static_cast<std::ptrdiff_t>(ranges[index].positions), length, body.positions.data());
            m_gl.write(ArrayBuffer, static_cast<std::ptrdiff_t>(ranges[index].normals), length, body.normals.data());
        }
        if (UploadSucceeded())
        {
            m_ranges = std::move(ranges);
            m_bytes = bytes;
            ++m_uploads;
            Unbind();
            return;
        }
    }
    Release();
}

void ModelVertexBuffer::BodyPointers(std::size_t body) const
{
    const auto& range = m_ranges[body];
    glVertexPointer(3, GL_FLOAT, 0, reinterpret_cast<const void*>(range.positions));
    glNormalPointer(GL_FLOAT, 0, reinterpret_cast<const void*>(range.normals));
}

void ModelVertexBuffer::Unbind() const
{
    m_gl.bind(ArrayBuffer, 0);
}

void ModelVertexBuffer::Release()
{
    if (m_buffer != 0)
    {
        Unbind();
        glVertexPointer(3, GL_FLOAT, 0, nullptr);
        glNormalPointer(GL_FLOAT, 0, nullptr);
        m_gl.remove(1, &m_buffer);
        m_buffer = 0;
    }
    m_bytes = 0;
    m_ranges.clear();
}

std::size_t ModelVertexBuffer::Bytes() const
{
    return m_bytes;
}

std::size_t ModelVertexBuffer::Uploads() const
{
    return m_uploads;
}
