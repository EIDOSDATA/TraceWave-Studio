/** @file @brief 표시 단면의 교차, 경계와 감김을 검사한다. */
#include "prototype_section.h"

#include <cmath>
#include <vector>

namespace
{
double Area(const std::vector<float>& mesh)
{
    double area = 0;
    for (std::size_t point = 0; point + 8 < mesh.size(); point += 9)
    {
        const double abx = mesh[point + 3] - mesh[point];
        const double aby = mesh[point + 4] - mesh[point + 1];
        const double acx = mesh[point + 6] - mesh[point];
        const double acy = mesh[point + 7] - mesh[point + 1];
        area += (abx * acy - aby * acx) / 2;
    }
    return area;
}
}

int main()
{
    const std::vector<float> original{-1, 0, 0, 2, 0, 0, 2, 3, 0};
    const auto upper = PrototypeSection::Clip(original, {1, 0, 0, 0});
    const auto lower = PrototypeSection::Clip(original, {-1, 0, 0, 0});
    if (upper.size() != 18 || lower.size() != 9 || std::abs(Area(upper) + Area(lower) - Area(original)) > 1e-6 ||
        Area(upper) <= 0 || Area(lower) <= 0)
    {
        return 1;
    }

    const std::vector<float> boundary{0, 0, 0, 0, 2, 0, -1, 0, 0};
    if (!PrototypeSection::Clip(boundary, {1, 0, 0, 0}).empty() ||
        PrototypeSection::Clip(boundary, {-1, 0, 0, 0}) != boundary ||
        PrototypeSection::Clip(boundary, {1, 0, 0, 2}) != boundary ||
        !PrototypeSection::Clip(boundary, {1, 0, 0, -2}).empty())
    {
        return 2;
    }
    return 0;
}
