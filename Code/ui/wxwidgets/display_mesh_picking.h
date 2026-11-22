/** @file @brief 검증한 삼각형 순서를 별도 경계 트리로 보강해 3D 클릭 후보만 좁힌다. */
#pragma once

#include "display_mesh.h"

namespace DisplayMesh
{
/** @brief 아티팩트를 변경하지 않는 메모리 내 선택 인덱스다. */
struct PickIndex final
{
    struct Node
    {
        std::array<float, 3> lower;
        std::array<float, 3> upper;
        std::uint32_t first;
        std::uint32_t count;
        std::uint32_t right;
    };

    struct BodyTree
    {
        std::vector<Node> nodes;
        std::vector<std::uint32_t> order;
    };

    std::vector<BodyTree> bodies;
};

/** @brief 검증 이후 작업 스레드에서 인덱스를 생성하며 로딩과 함께 취소할 수 있다. */
void BuildPickIndex(Scene& scene, const std::atomic<bool>* cancelled = nullptr);

/** @brief 화면 범위와 접할 가능성이 있는 바디는 전체 삼각형을 그린다. */
bool MayIntersectView(const Scene& scene, std::size_t bodyIndex, const Camera& camera,
    double halfWidth, double halfHeight);

/** @brief 숨긴 층, 화면 투영의 실제 깊이와 기존 바디 순서의 동률 우선을 유지한다. */
int PickIndexed(const Scene& scene, const Camera& camera, double x, double y,
    const std::set<std::string>& hiddenLayers = {}, const std::array<double, 4>* section = nullptr);
}
