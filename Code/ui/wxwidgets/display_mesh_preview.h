/** @file @brief 봉인된 표시 장면에서 화면 오차를 제한한 저해상도 표현을 만든다. */
#pragma once

#include "display_mesh.h"

namespace DisplayMesh
{
struct Preview
{
    Scene mesh;
    double maximumDisplacement = 0.0;
};

/** @brief 충분히 줄어든 경우에만 보기 전용의 두 번째 장면을 보관한다. */
std::unique_ptr<Preview> BuildPreview(const Scene& scene, const std::atomic<bool>* cancelled);
}
