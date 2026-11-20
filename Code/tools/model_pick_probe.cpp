/** @file @brief 동일 100만 삼각형의 3D 선택 결과와 계산 시간을 전수 검사와 대조한다. */
#include "display_mesh_picking.h"
#include "large_display_fixture.h"

#include <chrono>
#include <fstream>
#include <iostream>

int main(int argc, char** argv)
{
    if (argc != 3)
    {
        return 2;
    }
    try
    {
        const auto workspace = std::filesystem::absolute(std::filesystem::path(argv[1]));
        const auto output = std::filesystem::path(argv[2]);
        DisplayMesh::Require(!std::filesystem::exists(output), "새 3D 선택 보고서가 필요합니다.");
        const auto fixture = ReadLargeDisplayFixture(workspace);
        const auto& artifact = fixture.at("artifact");
        auto scene = DisplayMesh::Load(workspace, artifact, fixture.at("snapshot"), artifact.at("run_id"));
        DisplayMesh::Require(scene.triangles == 1000000 && scene.bodies.size() == 2, "대형 3D 선택 자료가 다릅니다.");

        using Clock = std::chrono::steady_clock;
        const auto started = Clock::now();
        DisplayMesh::BuildPickIndex(scene);
        const auto elapsed = [](Clock::time_point start)
        {
            return std::chrono::duration<double, std::milli>(Clock::now() - start).count();
        };
        const double buildMs = elapsed(started);
        DisplayMesh::Require(scene.pickIndex != nullptr, "대형 선택 인덱스를 만들지 못했습니다.");
        std::size_t nodes = 0;
        std::size_t indexBytes = 0;
        for (const auto& tree : scene.pickIndex->bodies)
        {
            nodes += tree.nodes.size();
            indexBytes += tree.nodes.capacity() * sizeof(DisplayMesh::PickIndex::Node) +
                tree.order.capacity() * sizeof(std::uint32_t);
        }
        auto samples = DisplayMesh::Json::array();
        std::array<unsigned, 3> hits{};
        for (int sample = 0; sample < 48; ++sample)
        {
            DisplayMesh::Camera camera;
            camera.yaw = -45.0 + 15.0 * (sample % 7);
            camera.pitch = 10.0 + 15.0 * (sample % 5);
            camera.panX = 0.04 * (sample % 3 - 1);
            camera.panY = 0.02 * (sample % 4 - 2);
            const auto& body = scene.bodies[(sample / 2) % 2];
            const auto base = static_cast<std::size_t>((sample * 7907) % 500000) * 9;
            const auto point = camera.Transform({
                (body.positions[base] + body.positions[base + 3] + body.positions[base + 6]) / 3.0,
                (body.positions[base + 1] + body.positions[base + 4] + body.positions[base + 7]) / 3.0,
                (body.positions[base + 2] + body.positions[base + 5] + body.positions[base + 8]) / 3.0});
            const bool outside = sample % 8 == 0;
            const double x = outside ? point.x + 5.0 : point.x;
            const double y = point.y;
            const std::set<std::string> hidden = sample % 7 == 1 ? std::set<std::string>{body.layer} : std::set<std::string>{};
            const auto before = Clock::now();
            const int exact = DisplayMesh::Pick(scene, camera, x, y, hidden);
            const double exactMs = elapsed(before);
            const auto fast = Clock::now();
            const int actual = DisplayMesh::PickIndexed(scene, camera, x, y, hidden);
            const double indexMs = elapsed(fast);
            DisplayMesh::Require(actual == exact, "선택 인덱스의 실제 바디가 모든 삼각형 검사와 다릅니다.");
            ++hits.at(static_cast<std::size_t>(actual + 1));
            samples.push_back({{"sample", sample}, {"body", actual}, {"x", x}, {"y", y},
                {"yaw", camera.yaw}, {"pitch", camera.pitch}, {"pan_x", camera.panX}, {"pan_y", camera.panY},
                {"hidden", hidden}, {"exhaustive_ms", exactMs}, {"indexed_ms", indexMs}});
        }
        DisplayMesh::Require(std::all_of(hits.begin(), hits.end(), [](unsigned count)
        {
            return count > 0;
        }), "두 바디 선택과 배경을 모두 검사해야 합니다.");

        std::ofstream report(output, std::ios::binary);
        report << DisplayMesh::Json{{"schema", "rfad.windows-display-pick-probe/0.1"}, {"artifact", artifact},
            {"samples", samples}, {"miss_and_body_hits", hits}, {"node_count", nodes}, {"buffer_capacity_bytes", indexBytes},
            {"index_build_ms", buildMs}, {"all_match", true}}.dump(2) << '\n';
        return report ? 0 : 2;
    }
    catch (const std::exception& error)
    {
        std::cerr << error.what() << '\n';
        return 2;
    }
}
