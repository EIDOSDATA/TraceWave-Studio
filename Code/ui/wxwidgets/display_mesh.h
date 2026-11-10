#pragma once

#include <windows.h>
#include <bcrypt.h>
#include <nlohmann/json.hpp>

#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <limits>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

/** @brief CAD 원본과 분리된 표시 mesh의 검증, 카메라와 선택 계산이다. */
namespace DisplayMesh
{
using Json = nlohmann::json;
constexpr std::size_t MaxBytes = 16 * 1024 * 1024;
constexpr std::size_t MaxTriangles = 100000;
constexpr std::size_t MaxVertices = 300000;
constexpr double Pi = 3.14159265358979323846;

struct Point
{
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
};

struct Body
{
    std::string id;
    std::string layer;
    std::string role;
    std::vector<std::string> sources;
    std::vector<float> positions;
    std::vector<float> normals;
};

struct Scene
{
    std::vector<Body> bodies;
    Point center;
    double radius = 1.0;
    std::size_t triangles = 0;
    std::size_t vertices = 0;
    std::string snapshotId;
    std::string revisionId;
    std::string runId;
};

/** @brief 표시 투영만 변경하며 설계 좌표와 원본 개정을 수정하지 않는다. */
struct Camera
{
    double yaw = -35.0;
    double pitch = 55.0;
    double zoom = 1.0;
    double panX = 0.0;
    double panY = 0.0;

    void Rotate(double dx, double dy)
    {
        if (std::isfinite(dx) && std::isfinite(dy))
        {
            yaw = std::remainder(yaw + dx * 0.5, 360.0);
            pitch = std::clamp(pitch + dy * 0.5, -89.9, 89.9);
        }
    }

    void Zoom(double steps)
    {
        if (std::isfinite(steps))
        {
            zoom = std::clamp(zoom * std::pow(1.18, std::clamp(steps, -100.0, 100.0)), 0.02, 100.0);
        }
    }

    double HalfHeight(double radius) const
    {
        return std::max(radius, 1e-5) * 1.15 / zoom;
    }

    Point Transform(const Point& point) const
    {
        const double a = yaw * Pi / 180.0;
        const double b = pitch * Pi / 180.0;
        const double x = std::cos(a) * point.x - std::sin(a) * point.y;
        const double y = std::sin(a) * point.x + std::cos(a) * point.y;
        return {x + panX, std::cos(b) * y - std::sin(b) * point.z + panY,
            std::sin(b) * y + std::cos(b) * point.z};
    }
};

inline void Require(bool condition, const char* message)
{
    if (!condition)
    {
        throw std::runtime_error(message);
    }
}

inline void CheckCancelled(const std::atomic<bool>* cancelled)
{
    if (cancelled != nullptr && cancelled->load())
    {
        throw std::runtime_error("3D 파일 읽기를 취소했습니다.");
    }
}

inline std::string Identity(const Json& value)
{
    Require(value.is_string(), "3D 객체 식별자가 올바르지 않습니다.");
    const std::string result = value.get<std::string>();
    Require(!result.empty() && result.size() <= 128 && result.find('\0') == std::string::npos,
        "3D 객체 식별자가 올바르지 않습니다.");
    return result;
}

inline Point ReadPoint(const Json& value)
{
    Require(value.is_array() && value.size() == 3, "3D 정점 좌표가 올바르지 않습니다.");
    std::array<double, 3> numbers{};
    for (std::size_t index = 0; index < 3; ++index)
    {
        Require(value[index].is_number(), "3D 정점에는 숫자가 필요합니다.");
        numbers[index] = value[index].get<double>();
        Require(std::isfinite(numbers[index]) && std::abs(numbers[index]) <= 1000001.0,
            "3D 정점이 표시 범위를 벗어났습니다.");
    }
    return {numbers[0], numbers[1], numbers[2]};
}

/** @brief 제한된 JSON을 검증한 뒤 중심 기준의 렌더링 버퍼만 남긴다. */
inline Scene Parse(const Json& value, const Json& snapshot, const std::string& runId,
    const std::atomic<bool>* cancelled = nullptr)
{
    Require(value.is_object() && value.value("schema", "") == "rfad.display-mesh/0.1" &&
        value.value("unit", "") == "mm" && value.value("purpose", "") == "display_only",
        "지원하지 않는 3D 표시 파일입니다.");
    Require(value.at("snapshot") == snapshot && value.value("run_id", "") == runId,
        "3D 표시 파일과 요청한 스냅샷이 다릅니다.");
    const auto& sourceBodies = value.at("bodies");
    Require(sourceBodies.is_array() && !sourceBodies.empty() && sourceBodies.size() <= 256,
        "3D body 수가 지원 범위를 벗어났습니다.");
    Scene result;
    result.snapshotId = Identity(snapshot.at("snapshot_id"));
    result.revisionId = Identity(snapshot.at("revision_id"));
    result.runId = runId;
    const double infinity = std::numeric_limits<double>::infinity();
    Point minimum{infinity, infinity, infinity};
    Point maximum{-infinity, -infinity, -infinity};
    std::set<std::string> identities;
    for (const auto& source : sourceBodies)
    {
        CheckCancelled(cancelled);
        Require(identities.insert(Identity(source.at("id"))).second, "3D body 식별자가 중복되었습니다.");
        const auto& vertices = source.at("vertices");
        const auto& triangles = source.at("triangles");
        Require(vertices.is_array() && !vertices.empty() && triangles.is_array() && !triangles.empty(),
            "3D body의 정점 또는 삼각형이 비어 있습니다.");
        Require(vertices.size() <= MaxVertices - result.vertices && triangles.size() <= MaxTriangles - result.triangles,
            "3D 표시 크기가 초기 profile 상한을 넘었습니다.");
        result.vertices += vertices.size();
        result.triangles += triangles.size();
        for (const auto& vertex : vertices)
        {
            const Point point = ReadPoint(vertex);
            minimum = {std::min(minimum.x, point.x), std::min(minimum.y, point.y), std::min(minimum.z, point.z)};
            maximum = {std::max(maximum.x, point.x), std::max(maximum.y, point.y), std::max(maximum.z, point.z)};
        }
    }
    result.center = {(minimum.x + maximum.x) / 2.0, (minimum.y + maximum.y) / 2.0, (minimum.z + maximum.z) / 2.0};
    result.radius = std::hypot(std::hypot(maximum.x - minimum.x, maximum.y - minimum.y), maximum.z - minimum.z) / 2.0;
    Require(result.radius > 0.0, "3D 표시 범위가 비어 있습니다.");
    for (const auto& source : sourceBodies)
    {
        CheckCancelled(cancelled);
        Body body;
        body.id = Identity(source.at("id"));
        body.layer = Identity(source.at("layer_id"));
        body.role = Identity(source.at("role"));
        Require(body.role == "dielectric" || body.role == "conductor", "지원하지 않는 3D body 역할입니다.");
        const auto& sources = source.at("source_entity_ids");
        Require(sources.is_array() && !sources.empty() && sources.size() <= 128, "3D 원본 객체 대응이 올바르지 않습니다.");
        std::set<std::string> uniqueSources;
        for (const auto& sourceId : sources)
        {
            const std::string identity = Identity(sourceId);
            Require(uniqueSources.insert(identity).second, "3D 원본 객체 대응이 중복되었습니다.");
            body.sources.push_back(identity);
        }
        const auto& vertices = source.at("vertices");
        const auto& triangles = source.at("triangles");
        body.positions.reserve(triangles.size() * 9);
        body.normals.reserve(triangles.size() * 9);
        for (const auto& triangle : triangles)
        {
            CheckCancelled(cancelled);
            Require(triangle.is_array() && triangle.size() == 3, "3D 삼각형 인덱스가 올바르지 않습니다.");
            std::array<Point, 3> points{};
            for (std::size_t corner = 0; corner < 3; ++corner)
            {
                Require(triangle[corner].is_number_integer() && triangle[corner].get<std::int64_t>() >= 0,
                    "3D 삼각형 인덱스는 음수가 아닌 정수여야 합니다.");
                const auto index = triangle[corner].get<std::uint64_t>();
                Require(index < vertices.size(), "3D 삼각형이 없는 정점을 참조합니다.");
                points[corner] = ReadPoint(vertices[index]);
            }
            const Point a{points[1].x - points[0].x, points[1].y - points[0].y, points[1].z - points[0].z};
            const Point b{points[2].x - points[0].x, points[2].y - points[0].y, points[2].z - points[0].z};
            const Point normal{a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
            const double length = std::hypot(std::hypot(normal.x, normal.y), normal.z);
            Require(std::isfinite(length) && length > 0.0, "3D 표시 파일에 퇴화 삼각형이 있습니다.");
            std::array<Point, 3> displayed{};
            for (std::size_t corner = 0; corner < 3; ++corner)
            {
                displayed[corner] = {static_cast<float>(points[corner].x - result.center.x),
                    static_cast<float>(points[corner].y - result.center.y), static_cast<float>(points[corner].z - result.center.z)};
            }
            const Point fa{displayed[1].x - displayed[0].x, displayed[1].y - displayed[0].y, displayed[1].z - displayed[0].z};
            const Point fb{displayed[2].x - displayed[0].x, displayed[2].y - displayed[0].y, displayed[2].z - displayed[0].z};
            const Point renderedNormal{fa.y * fb.z - fa.z * fb.y, fa.z * fb.x - fa.x * fb.z, fa.x * fb.y - fa.y * fb.x};
            Require(renderedNormal.x * normal.x + renderedNormal.y * normal.y + renderedNormal.z * normal.z > 0.0,
                "큰 좌표와 미세 형상이 현재 3D 표시 정밀도를 넘습니다. STEP 원본은 유지됩니다.");
            for (std::size_t corner = 0; corner < 3; ++corner)
            {
                const std::size_t next = (corner + 1) % 3;
                const double originalEdge = std::hypot(std::hypot(points[corner].x - points[next].x,
                    points[corner].y - points[next].y), points[corner].z - points[next].z);
                const double displayedEdge = std::hypot(std::hypot(displayed[corner].x - displayed[next].x,
                    displayed[corner].y - displayed[next].y), displayed[corner].z - displayed[next].z);
                Require(std::abs(originalEdge - displayedEdge) <= std::max(1e-9, originalEdge * 0.1),
                    "미세 형상의 변 길이가 현재 3D 표시 정밀도를 넘습니다. STEP 원본은 유지됩니다.");
                body.positions.insert(body.positions.end(), {static_cast<float>(displayed[corner].x),
                    static_cast<float>(displayed[corner].y), static_cast<float>(displayed[corner].z)});
                body.normals.insert(body.normals.end(), {static_cast<float>(normal.x / length),
                    static_cast<float>(normal.y / length), static_cast<float>(normal.z / length)});
            }
        }
        result.bodies.push_back(std::move(body));
    }
    return result;
}

/** @brief 같은 렌더링 좌표의 가장 가까운 삼각형을 안정 body 인덱스로 찾는다. */
inline int Pick(const Scene& scene, const Camera& camera, double x, double y,
    const std::set<std::string>& hiddenLayers = {})
{
    double closest = -std::numeric_limits<double>::infinity();
    int selected = -1;
    for (std::size_t bodyIndex = 0; bodyIndex < scene.bodies.size(); ++bodyIndex)
    {
        const auto& body = scene.bodies[bodyIndex];
        if (hiddenLayers.count(body.layer) != 0)
        {
            continue;
        }
        for (std::size_t offset = 0; offset < body.positions.size(); offset += 9)
        {
            std::array<Point, 3> points{};
            for (std::size_t corner = 0; corner < 3; ++corner)
            {
                const std::size_t index = offset + corner * 3;
                points[corner] = camera.Transform({body.positions[index], body.positions[index + 1], body.positions[index + 2]});
            }
            const auto& a = points[0];
            const auto& b = points[1];
            const auto& c = points[2];
            const double denominator = (b.y - c.y) * (a.x - c.x) + (c.x - b.x) * (a.y - c.y);
            if (std::abs(denominator) <= 1e-24)
            {
                continue;
            }
            const double u = ((b.y - c.y) * (x - c.x) + (c.x - b.x) * (y - c.y)) / denominator;
            const double v = ((c.y - a.y) * (x - c.x) + (a.x - c.x) * (y - c.y)) / denominator;
            const double w = 1.0 - u - v;
            const double depth = u * a.z + v * b.z + w * c.z;
            if (u >= -1e-9 && v >= -1e-9 && w >= -1e-9 && depth > closest)
            {
                closest = depth;
                selected = static_cast<int>(bodyIndex);
            }
        }
    }
    return selected;
}

/** @brief 파일과 같은 byte 집합을 Windows SHA256으로 확인한다. */
inline std::string Sha256(const std::string& bytes)
{
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    Require(BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0,
        "SHA256 계산기를 열 수 없습니다.");
    std::array<unsigned char, 32> hash{};
    BCRYPT_HASH_HANDLE state = nullptr;
    NTSTATUS status = BCryptCreateHash(algorithm, &state, nullptr, 0, nullptr, 0, 0);
    if (status >= 0)
    {
        status = BCryptHashData(state, reinterpret_cast<PUCHAR>(const_cast<char*>(bytes.data())), static_cast<ULONG>(bytes.size()), 0);
        if (status >= 0)
        {
            status = BCryptFinishHash(state, hash.data(), static_cast<ULONG>(hash.size()), 0);
        }
        BCryptDestroyHash(state);
    }
    BCryptCloseAlgorithmProvider(algorithm, 0);
    Require(status >= 0, "SHA256 계산에 실패했습니다.");
    static constexpr char Hex[] = "0123456789abcdef";
    std::string result;
    result.reserve(64);
    for (unsigned char value : hash)
    {
        result += Hex[value >> 4];
        result += Hex[value & 15];
    }
    return result;
}

/** @brief 열린 디렉터리를 유지하여 검사 후 경로 교체를 막는다. */
class Handles final
{
public:
    ~Handles()
    {
        for (HANDLE handle : m_handles)
        {
            CloseHandle(handle);
        }
    }

    HANDLE Open(const std::filesystem::path& path, bool directory)
    {
        const HANDLE handle = CreateFileW(path.c_str(), directory ? FILE_READ_ATTRIBUTES : GENERIC_READ,
            directory ? FILE_SHARE_READ | FILE_SHARE_WRITE : FILE_SHARE_READ, nullptr, OPEN_EXISTING,
            FILE_FLAG_OPEN_REPARSE_POINT | (directory ? FILE_FLAG_BACKUP_SEMANTICS : FILE_ATTRIBUTE_NORMAL), nullptr);
        Require(handle != INVALID_HANDLE_VALUE, "게시된 3D 파일 경로를 열 수 없습니다.");
        m_handles.push_back(handle);
        BY_HANDLE_FILE_INFORMATION info{};
        Require(GetFileInformationByHandle(handle, &info) != 0 &&
            (info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) == 0 &&
            (((info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0) == directory),
            "3D 파일 경로에 재분석 지점 또는 잘못된 파일이 있습니다.");
        if (!directory)
        {
            Require(info.nNumberOfLinks == 1 && GetFileType(handle) == FILE_TYPE_DISK,
                "3D 파일은 하나의 일반 파일이어야 합니다.");
        }
        return handle;
    }

private:
    std::vector<HANDLE> m_handles;
};

/** @brief workspace 밖 경로와 바뀐 파일을 차단하고 닫힌 산출물을 읽는다. */
inline Scene Load(const std::filesystem::path& workspace, const Json& artifact, const Json& snapshot,
    const std::string& runId, const std::atomic<bool>* cancelled = nullptr)
{
    Require(artifact.value("role", "") == "display_mesh" && artifact.value("run_id", "") == runId &&
        artifact.value("snapshot_id", "") == snapshot.value("snapshot_id", ""), "3D 파일 참조가 실행과 다릅니다.");
    Require(artifact.at("bytes").is_number_integer(), "3D 파일 크기가 올바르지 않습니다.");
    const auto byteCount = artifact.at("bytes").get<std::int64_t>();
    Require(byteCount > 0 && static_cast<std::uint64_t>(byteCount) <= MaxBytes, "3D 표시 파일은 최대 16 MiB입니다.");
    const std::string uri = artifact.at("uri").get<std::string>();
    Require(!uri.empty() && uri.size() <= 2048 && uri.find_first_of("\\:\0", 0, 3) == std::string::npos && uri.front() != '/',
        "3D 파일 경로는 workspace 기준 상대 경로여야 합니다.");
    const auto relative = std::filesystem::u8path(uri);
    Require(!relative.is_absolute() && !relative.has_root_name() && !relative.has_root_directory(), "잘못된 3D 파일 경로입니다.");
    for (const auto& component : relative)
    {
        const auto name = component.u8string();
        Require(!name.empty() && name != "." && name != ".." && name.back() != '.' && name.back() != ' ',
            "3D 파일 경로에 허용하지 않는 요소가 있습니다.");
    }
    Handles handles;
    auto path = std::filesystem::absolute(workspace).lexically_normal();
    Require(path.is_absolute(), "workspace 절대 경로가 필요합니다.");
    handles.Open(path, true);
    for (const auto& component : relative.parent_path())
    {
        path /= component;
        handles.Open(path, true);
    }
    path /= relative.filename();
    const HANDLE file = handles.Open(path, false);
    LARGE_INTEGER length{};
    Require(GetFileSizeEx(file, &length) != 0 && length.QuadPart == byteCount, "3D 파일 크기가 게시된 값과 다릅니다.");
    std::string bytes(static_cast<std::size_t>(byteCount), '\0');
    std::size_t offset = 0;
    while (offset < bytes.size())
    {
        CheckCancelled(cancelled);
        DWORD received = 0;
        const auto request = static_cast<DWORD>(std::min<std::size_t>(65536, bytes.size() - offset));
        Require(ReadFile(file, bytes.data() + offset, request, &received, nullptr) != 0 && received > 0,
            "3D 파일을 완전히 읽을 수 없습니다.");
        offset += received;
    }
    Require(Sha256(bytes) == artifact.at("sha256").get<std::string>(), "3D 파일 SHA256이 게시된 값과 다릅니다.");
    const Json value = Json::parse(bytes, [cancelled](int depth, Json::parse_event_t, Json&)
    {
        CheckCancelled(cancelled);
        Require(depth <= 32, "3D 파일 중첩 깊이가 너무 큽니다.");
        return true;
    });
    return Parse(value, snapshot, runId, cancelled);
}
}
