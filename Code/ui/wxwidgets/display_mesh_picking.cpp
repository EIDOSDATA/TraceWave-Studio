/** @file @brief 월드 좌표 경계에 포함되는 3D 선택 후보만 원래 삼각형 판정에 전달한다. */
#include "display_mesh_picking.h"

#include <numeric>

namespace DisplayMesh
{
namespace
{
constexpr std::size_t IndexedBodyMinimum = 2048;
constexpr std::uint32_t LeafCapacity = 16;
using AxisValues = std::array<float, 3>;

/** @brief 트리의 각 노드는 부모 삼각형의 실제 float 정점을 포함한다. */
std::uint32_t BuildNode(const Body& body, PickIndex::BodyTree& tree,
    const std::vector<AxisValues>& centers, std::uint32_t begin, std::uint32_t end,
    const std::atomic<bool>* cancelled)
{
    CheckCancelled(cancelled);
    const float infinity = std::numeric_limits<float>::infinity();
    PickIndex::Node node{{infinity, infinity, infinity}, {-infinity, -infinity, -infinity},
        begin, end - begin, 0};
    AxisValues centerLow = node.lower;
    AxisValues centerHigh = node.upper;
    for (std::uint32_t index = begin; index < end; ++index)
    {
        if ((index & 4095u) == 0)
        {
            CheckCancelled(cancelled);
        }
        const auto triangle = tree.order[index];
        const auto base = static_cast<std::size_t>(triangle) * 9;
        for (std::size_t axis = 0; axis < 3; ++axis)
        {
            const auto value = centers[triangle][axis];
            centerLow[axis] = std::min(centerLow[axis], value);
            centerHigh[axis] = std::max(centerHigh[axis], value);
            for (std::size_t corner = 0; corner < 3; ++corner)
            {
                const auto vertex = body.positions[base + corner * 3 + axis];
                node.lower[axis] = std::min(node.lower[axis], vertex);
                node.upper[axis] = std::max(node.upper[axis], vertex);
            }
        }
    }
    const auto current = static_cast<std::uint32_t>(tree.nodes.size());
    tree.nodes.push_back(node);
    std::size_t axis = 0;
    for (std::size_t candidate = 1; candidate < 3; ++candidate)
    {
        if (centerHigh[candidate] - centerLow[candidate] > centerHigh[axis] - centerLow[axis])
        {
            axis = candidate;
        }
    }
    if (node.count <= LeafCapacity || centerLow[axis] == centerHigh[axis])
    {
        return current;
    }
    const auto middle = begin + node.count / 2;
    std::nth_element(tree.order.begin() + begin, tree.order.begin() + middle, tree.order.begin() + end,
        [axis, &centers](std::uint32_t left, std::uint32_t right)
        {
            return centers[left][axis] < centers[right][axis];
        });
    BuildNode(body, tree, centers, begin, middle, cancelled);
    const auto right = BuildNode(body, tree, centers, middle, end, cancelled);
    tree.nodes[current].count = 0;
    tree.nodes[current].right = right;
    return current;
}

/** @brief 정확한 평행 투영과 절대 여유를 사용해 삼각형 모서리 허용 범위도 포함한다. */
class ProjectedBounds final
{
public:
    explicit ProjectedBounds(const Camera& camera)
        : m_camera(camera)
    {
        const double yaw = camera.yaw * Pi / 180.0;
        const double pitch = camera.pitch * Pi / 180.0;
        m_rowX = {std::abs(std::cos(yaw)), std::abs(std::sin(yaw)), 0.0};
        m_rowY = {std::abs(std::cos(pitch) * std::sin(yaw)), std::abs(std::cos(pitch) * std::cos(yaw)),
            std::abs(std::sin(pitch))};
    }

    bool Contains(const PickIndex::Node& node, double x, double y) const
    {
        std::array<double, 3> center{};
        double extentX = 0.0;
        double extentY = 0.0;
        for (std::size_t axis = 0; axis < 3; ++axis)
        {
            const double low = node.lower[axis];
            const double high = node.upper[axis];
            center[axis] = (low + high) * 0.5;
            const double half = (high - low) * 0.5;
            extentX += m_rowX[axis] * half;
            extentY += m_rowY[axis] * half;
        }
        const auto point = m_camera.Transform({center[0], center[1], center[2]});
        const double arithmetic = 1e-12 * std::max({1.0, std::abs(point.x), std::abs(point.y),
            std::abs(center[0]), std::abs(center[1]), std::abs(center[2]), extentX, extentY});
        return std::abs(x - point.x) <= extentX * (1.0 + 4e-9) + arithmetic &&
            std::abs(y - point.y) <= extentY * (1.0 + 4e-9) + arithmetic;
    }

private:
    const Camera& m_camera;
    std::array<double, 3> m_rowX;
    std::array<double, 3> m_rowY;
};

void FindDepth(const Body& body, const PickIndex::BodyTree& tree, std::uint32_t index,
    const ProjectedBounds& bounds, const Camera& camera, double x, double y, double& closest)
{
    const auto& node = tree.nodes[index];
    if (!bounds.Contains(node, x, y))
    {
        return;
    }
    if (node.count == 0)
    {
        FindDepth(body, tree, index + 1, bounds, camera, x, y, closest);
        FindDepth(body, tree, node.right, bounds, camera, x, y, closest);
        return;
    }
    for (auto offset = node.first; offset < node.first + node.count; ++offset)
    {
        const auto triangle = static_cast<std::size_t>(tree.order[offset]);
        closest = std::max(closest, PickTriangleDepth(body, triangle * 9, camera, x, y));
    }
}
}

void BuildPickIndex(Scene& scene, const std::atomic<bool>* cancelled)
{
    auto index = std::make_shared<PickIndex>();
    index->bodies.resize(scene.bodies.size());
    bool indexed = false;
    for (std::size_t bodyIndex = 0; bodyIndex < scene.bodies.size(); ++bodyIndex)
    {
        CheckCancelled(cancelled);
        const auto& body = scene.bodies[bodyIndex];
        const auto count = body.positions.size() / 9;
        if (count < IndexedBodyMinimum)
        {
            continue;
        }
        Require(count <= MaxLargeTriangles, "3D 선택 인덱스가 표시 삼각형 상한을 넘었습니다.");
        auto& tree = index->bodies[bodyIndex];
        tree.order.resize(count);
        std::iota(tree.order.begin(), tree.order.end(), 0u);
        std::vector<AxisValues> centers(count);
        for (std::size_t triangle = 0; triangle < count; ++triangle)
        {
            if ((triangle & 4095u) == 0)
            {
                CheckCancelled(cancelled);
            }
            const auto base = triangle * 9;
            for (std::size_t axis = 0; axis < 3; ++axis)
            {
                centers[triangle][axis] =
                    (body.positions[base + axis] + body.positions[base + 3 + axis] + body.positions[base + 6 + axis]) / 3.0f;
            }
        }
        std::size_t leafBound = 1;
        while (leafBound * LeafCapacity < count)
        {
            leafBound *= 2;
        }
        tree.nodes.reserve(leafBound * 2 - 1);
        BuildNode(body, tree, centers, 0, static_cast<std::uint32_t>(count), cancelled);
        indexed = true;
    }
    if (indexed)
    {
        scene.pickIndex = std::move(index);
    }
}

int PickIndexed(const Scene& scene, const Camera& camera, double x, double y,
    const std::set<std::string>& hiddenLayers)
{
    if (scene.pickIndex == nullptr)
    {
        return Pick(scene, camera, x, y, hiddenLayers);
    }
    const ProjectedBounds bounds(camera);
    double closest = -std::numeric_limits<double>::infinity();
    int selected = -1;
    for (std::size_t bodyIndex = 0; bodyIndex < scene.bodies.size(); ++bodyIndex)
    {
        const auto& body = scene.bodies[bodyIndex];
        if (hiddenLayers.count(body.layer) != 0)
        {
            continue;
        }
        const auto& tree = scene.pickIndex->bodies[bodyIndex];
        double depth = -std::numeric_limits<double>::infinity();
        if (tree.nodes.empty())
        {
            for (std::size_t offset = 0; offset < body.positions.size(); offset += 9)
            {
                depth = std::max(depth, PickTriangleDepth(body, offset, camera, x, y));
            }
        }
        else
        {
            FindDepth(body, tree, 0, bounds, camera, x, y, depth);
        }
        if (depth > closest)
        {
            closest = depth;
            selected = static_cast<int>(bodyIndex);
        }
    }
    return selected;
}
}
