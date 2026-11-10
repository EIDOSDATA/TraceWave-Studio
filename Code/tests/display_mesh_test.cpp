#include "../ui/wxwidgets/display_mesh.h"

#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <functional>

using namespace DisplayMesh;

/** @brief Release에서도 잘못된 입력과 카메라 결과를 실패 종료로 기록한다. */
void Check(bool condition, const char* message)
{
    if (!condition)
    {
        std::fprintf(stderr, "Display mesh test failed: %s\n", message);
        std::exit(1);
    }
}

void Reject(const std::function<void()>& action, const char* message)
{
    try
    {
        action();
    }
    catch (const std::exception&)
    {
        return;
    }
    Check(false, message);
}

Json Fixture(const Json& snapshot)
{
    return {{"schema", "rfad.display-mesh/0.1"}, {"unit", "mm"}, {"purpose", "display_only"},
        {"snapshot", snapshot}, {"run_id", "run-1"}, {"bodies", Json::array({
            {{"id", "body-back"}, {"layer_id", "core"}, {"role", "dielectric"},
                {"source_entity_ids", Json::array({"layer-core"})},
                {"vertices", Json::array({{0.0, 0.0, 0.0}, {2.0, 0.0, 0.0}, {0.0, 2.0, 0.0}})},
                {"triangles", Json::array({{0, 1, 2}})}},
            {{"id", "body-front"}, {"layer_id", "copper"}, {"role", "conductor"},
                {"source_entity_ids", Json::array({"arc-a", "line-b"})},
                {"vertices", Json::array({{0.0, 0.0, 0.035}, {2.0, 0.0, 0.035}, {0.0, 2.0, 0.035}})},
                {"triangles", Json::array({{0, 1, 2}})}}
        })}};
}

/** @brief 파일 무결성, 원본 대응, picking 깊이와 표시 상한을 함께 검증한다. */
int main()
{
    const Json snapshot{{"snapshot_id", "snapshot-1"}, {"revision_id", "revision-1"}, {"content_hash", "sealed"}};
    const auto fixture = Fixture(snapshot);
    const auto scene = Parse(fixture, snapshot, "run-1");
    Check(scene.bodies.size() == 2 && scene.triangles == 2 && scene.vertices == 6, "counts");
    Check(scene.bodies[1].sources == std::vector<std::string>({"arc-a", "line-b"}), "merged source mapping");
    Check(std::abs(scene.center.z - 0.0175) < 1e-12, "physical thin copper retained");
    Check(std::abs(scene.bodies[0].normals[2] - 1.0f) < 1e-6f, "triangle winding normal");
    Camera camera;
    camera.yaw = 0.0;
    camera.pitch = 0.0;
    Check(Pick(scene, camera, -0.5, -0.5) == 1, "nearest visible surface");
    Check(Pick(scene, camera, -0.5, -0.5, {"copper"}) == 0, "hidden layer picking");
    Check(Pick(scene, camera, 9.0, 9.0) == -1, "outside picking");
    camera.panX = 5.0;
    camera.panY = -3.0;
    Check(Pick(scene, camera, 4.5, -3.5) == 1, "panning picking");
    camera.Rotate(100000.0, 100000.0);
    Check(std::abs(camera.yaw) <= 180.0 && camera.pitch == 89.9, "rotation limits");
    camera.Zoom(1000.0);
    Check(camera.zoom == 100.0, "maximum zoom");
    camera.Zoom(-1000.0);
    Check(camera.zoom == 0.02, "minimum zoom");
    const double zoom = camera.zoom;
    camera.Zoom(std::numeric_limits<double>::infinity());
    Check(camera.zoom == zoom, "invalid zoom ignored");
    auto wrong = fixture;
    wrong["bodies"][0]["triangles"][0][2] = 3;
    Reject([&]()
    {
        Parse(wrong, snapshot, "run-1");
    }, "out of bounds index");
    wrong = fixture;
    wrong["bodies"][0]["triangles"][0][2] = -1;
    Reject([&]()
    {
        Parse(wrong, snapshot, "run-1");
    }, "negative index");
    wrong = fixture;
    wrong["bodies"][0]["triangles"][0][2] = 1;
    Reject([&]()
    {
        Parse(wrong, snapshot, "run-1");
    }, "degenerate triangle");
    wrong = fixture;
    wrong["bodies"][0]["vertices"][0][0] = std::numeric_limits<double>::infinity();
    Reject([&]()
    {
        Parse(wrong, snapshot, "run-1");
    }, "nonfinite coordinate");
    wrong = fixture;
    wrong["bodies"][1]["id"] = "body-back";
    Reject([&]()
    {
        Parse(wrong, snapshot, "run-1");
    }, "duplicate body");
    wrong = fixture;
    wrong["bodies"][1]["source_entity_ids"] = Json::array({"arc-a", "arc-a"});
    Reject([&]()
    {
        Parse(wrong, snapshot, "run-1");
    }, "duplicate source mapping");
    wrong = fixture;
    wrong["bodies"][0]["triangles"] = std::vector<std::array<int, 3>>(MaxTriangles, {0, 1, 2});
    Reject([&]()
    {
        Parse(wrong, snapshot, "run-1");
    }, "aggregate triangle limit");
    wrong = fixture;
    wrong["bodies"][0]["vertices"] = Json::array({{0.0, 0.0, 0.0}, {1000000.0, 0.0, 0.0}, {0.0, 1000000.0, 0.0}});
    wrong["bodies"][1]["vertices"] = Json::array({{600000.0, 600000.0, 0.035},
        {600000.001, 600000.0, 0.035}, {600000.0, 600001.0, 0.035}});
    Reject([&]()
    {
        Parse(wrong, snapshot, "run-1");
    }, "float collapse on large board");
    Reject([&]()
    {
        Parse(fixture, snapshot, "other-run");
    }, "run mismatch");
    const Json otherSnapshot{{"snapshot_id", "snapshot-2"}, {"revision_id", "revision-1"}};
    Reject([&]()
    {
        Parse(fixture, otherSnapshot, "run-1");
    }, "snapshot mismatch");
    Check(Sha256("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", "known SHA256 vector");
    const auto root = std::filesystem::temp_directory_path() /
        (std::wstring(L"TraceWave 3D ") + std::to_wstring(GetCurrentProcessId()) + L" 한글");
    std::filesystem::create_directories(root / "artifacts");
    const auto file = root / "artifacts" / "mesh.json";
    const std::string bytes = fixture.dump();
    {
        std::ofstream output(file, std::ios::binary);
        output << bytes;
    }
    Json artifact{{"role", "display_mesh"}, {"run_id", "run-1"}, {"snapshot_id", "snapshot-1"},
        {"uri", "artifacts/mesh.json"}, {"bytes", bytes.size()}, {"sha256", Sha256(bytes)}};
    Check(Load(root, artifact, snapshot, "run-1").triangles == 2, "verified file and Korean workspace");
    auto badArtifact = artifact;
    badArtifact["sha256"] = std::string(64, '0');
    Reject([&]()
    {
        Load(root, badArtifact, snapshot, "run-1");
    }, "changed file hash");
    badArtifact = artifact;
    badArtifact["bytes"] = bytes.size() + 1;
    Reject([&]()
    {
        Load(root, badArtifact, snapshot, "run-1");
    }, "changed file length");
    for (const std::string path : {"../mesh.json", "C:/mesh.json", "/mesh.json", "artifacts\\mesh.json", "artifacts/../mesh.json", "artifacts/mesh.json:stream"})
    {
        badArtifact = artifact;
        badArtifact["uri"] = path;
        Reject([&]()
        {
            Load(root, badArtifact, snapshot, "run-1");
        }, "unsafe path");
    }
    std::atomic<bool> cancelled{true};
    Reject([&]()
    {
        Load(root, artifact, snapshot, "run-1", &cancelled);
    }, "cancelled read");
    std::filesystem::create_hard_link(file, root / "alias.json");
    Reject([&]()
    {
        Load(root, artifact, snapshot, "run-1");
    }, "hardlinked file");
    std::filesystem::remove(root / "alias.json");
    std::filesystem::remove(file);
    std::filesystem::remove(root / "artifacts");
    std::filesystem::remove(root);
    std::puts("Display mesh file, validation, camera and picking checks passed.");
    return 0;
}
