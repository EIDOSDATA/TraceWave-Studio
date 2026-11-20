/** @file @brief 현재 OpenGL context의 불변 표시 메시 정점 저장소를 관리한다. */
#pragma once

#include <windows.h>
#include <GL/gl.h>
#include <cstddef>
#include <vector>

namespace DisplayMesh
{
struct Scene;
}

/** @brief 모델 보기의 UI 스레드에서만 사용하며 CPU 메시와 원본 파일을 수정하지 않는다. */
class ModelVertexBuffer final
{
public:
    /** @brief 새 메시가 도착하면 다음 그리기에서 한 번 다시 올린다. */
    void Invalidate();
    /** @brief 소유 context를 파기한 뒤 그 context의 이름과 함수 주소를 폐기한다. */
    void ContextDiscarded();
    /** @brief 소유 context가 current일 때 GPU 저장소를 사용하고 미지원이면 false를 반환한다. */
    bool Bind(const DisplayMesh::Scene& scene);
    /** @brief 바인딩한 저장소의 바디별 위치/법선 오프셋을 사용한다. */
    void BodyPointers(std::size_t body) const;
    /** @brief CPU 배열을 해석하는 다른 코드에 GPU 바인딩을 남기지 않는다. */
    void Unbind() const;
    /** @brief 소유 context가 current일 때 사용하던 저장소를 해제한다. */
    void Release();
    std::size_t Bytes() const;
    std::size_t Uploads() const;

private:
    struct Functions
    {
        void (APIENTRY* generate)(GLsizei, GLuint*) = nullptr;
        void (APIENTRY* remove)(GLsizei, const GLuint*) = nullptr;
        void (APIENTRY* bind)(GLenum, GLuint) = nullptr;
        void (APIENTRY* allocate)(GLenum, std::ptrdiff_t, const void*, GLenum) = nullptr;
        void (APIENTRY* write)(GLenum, std::ptrdiff_t, std::ptrdiff_t, const void*) = nullptr;
    };
    struct Range
    {
        std::size_t positions;
        std::size_t normals;
    };

    void Upload(const DisplayMesh::Scene& scene);

    Functions m_gl;
    std::vector<Range> m_ranges;
    GLuint m_buffer = 0;
    std::size_t m_bytes = 0;
    std::size_t m_uploads = 0;
    bool m_resolved = false;
    bool m_dirty = true;
};
