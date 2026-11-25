/** @file @brief 표시 삼각형을 단면의 보존 쪽에서만 남긴다. */
#pragma once

#include <array>
#include <cstddef>
#include <vector>

namespace PrototypeSection
{
using Plane = std::array<double, 4>;
using Vertex = std::array<float, 3>;

/** @brief 평면을 가로지르는 삼각형은 교차점에서 잘라 기존 감김을 유지한다. */
inline std::vector<float> Clip(const std::vector<float>& positions, const Plane& plane)
{
    const auto side = [&plane](const Vertex& vertex)
    {
        return plane[0] * vertex[0] + plane[1] * vertex[1] + plane[2] * vertex[2] + plane[3];
    };
    std::vector<float> clipped;
    clipped.reserve(positions.size());
    for (std::size_t offset = 0; offset + 8 < positions.size(); offset += 9)
    {
        const auto point = [&](std::size_t index)
        {
            return Vertex{positions[offset + index], positions[offset + index + 1], positions[offset + index + 2]};
        };
        std::array<Vertex, 4> polygon{};
        std::size_t count = 0;
        auto previous = point(6);
        double from = side(previous);
        for (std::size_t index = 0; index < 9; index += 3)
        {
            const auto current = point(index);
            const auto to = side(current);
            if ((from < 0 && to > 0) || (from > 0 && to < 0))
            {
                const auto ratio = from / (from - to);
                Vertex crossing{};
                for (std::size_t axis = 0; axis < crossing.size(); ++axis)
                {
                    crossing[axis] = static_cast<float>(previous[axis] +
                        ratio * (static_cast<double>(current[axis]) - previous[axis]));
                }
                polygon[count++] = crossing;
            }
            if (to >= 0)
            {
                polygon[count++] = current;
            }
            previous = current;
            from = to;
        }
        for (std::size_t index = 2; index < count; ++index)
        {
            for (const auto* vertex : {&polygon[0], &polygon[index - 1], &polygon[index]})
            {
                clipped.insert(clipped.end(), vertex->begin(), vertex->end());
            }
        }
    }
    return clipped;
}
}
