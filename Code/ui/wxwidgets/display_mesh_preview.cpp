/** @file @brief 낮은 확대에서 원본의 인접 정점을 같은 격자에 놓아 표시 비용을 줄인다. */
#include "display_mesh_preview.h"

namespace DisplayMesh
{
namespace
{
constexpr std::size_t MinFullTriangles = 250000;
constexpr std::size_t MaxPreviewTriangles = 200000;

/** @brief 면적이 0인 삼각형은 결과에서 생략한다. */
bool HasArea(const std::array<float, 9>& points)
{
    const double ax = static_cast<double>(points[3]) - points[0];
    const double ay = static_cast<double>(points[4]) - points[1];
    const double az = static_cast<double>(points[5]) - points[2];
    const double bx = static_cast<double>(points[6]) - points[0];
    const double by = static_cast<double>(points[7]) - points[1];
    const double bz = static_cast<double>(points[8]) - points[2];
    return ay * bz != az * by || az * bx != ax * bz || ax * by != ay * bx;
}
}

std::unique_ptr<Preview> BuildPreview(const Scene& scene, const std::atomic<bool>* cancelled)
{
    if (scene.triangles < MinFullTriangles)
    {
        return nullptr;
    }
    auto preview = std::make_unique<Preview>();
    const std::size_t limit = std::min(MaxPreviewTriangles, scene.triangles / 3);
    const double step = scene.radius / 180.0;
    double maximumSquared = 0.0;
    for (const auto& original : scene.bodies)
    {
        CheckCancelled(cancelled);
        Body body{original.id, original.layer, original.role, original.sources, {}, {}};
        for (std::size_t offset = 0; offset < original.positions.size(); offset += 9)
        {
            if (offset % (9 * 4096) == 0)
            {
                CheckCancelled(cancelled);
            }
            std::array<float, 9> points{};
            for (std::size_t corner = 0; corner < 9; corner += 3)
            {
                double squared = 0.0;
                for (std::size_t axis = 0; axis < 3; ++axis)
                {
                    const double before = original.positions[offset + corner + axis];
                    const auto snapped = static_cast<float>(std::round(before / step) * step);
                    points[corner + axis] = snapped;
                    const double distance = snapped - before;
                    squared += distance * distance;
                }
                maximumSquared = std::max(maximumSquared, squared);
            }
            if (HasArea(points))
            {
                if (preview->mesh.triangles >= limit)
                {
                    return nullptr;
                }
                body.positions.insert(body.positions.end(), points.begin(), points.end());
                body.normals.insert(body.normals.end(), original.normals.begin() + offset,
                                    original.normals.begin() + offset + 9);
                ++preview->mesh.triangles;
            }
        }
        if (body.positions.empty())
        {
            /** @brief 작은 독립 바디는 단순화 때문에 완전히 사라지지 않아야 한다. */
            const auto triangles = original.positions.size() / 9;
            if (triangles > limit - preview->mesh.triangles)
            {
                return nullptr;
            }
            body.positions = original.positions;
            body.normals = original.normals;
            preview->mesh.triangles += triangles;
        }
        preview->mesh.bodies.push_back(std::move(body));
    }
    preview->maximumDisplacement = std::sqrt(maximumSquared);
    return preview;
}
}
