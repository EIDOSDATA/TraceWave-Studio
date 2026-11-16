/** @file @brief Windows 실제 교환 저장의 정확한 한글 파일명과 원문/조건 쌍 보존을 검사한다. */
#include "network_export.h"
#include "display_mesh.h"
#include "studio_support.h"
#include <wx/init.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <set>
#include <stdexcept>
#include <vector>

namespace
{
using Path = std::filesystem::path;

/** @brief Release에서도 경로 또는 바이트가 다르면 시험을 실패시킨다. */
void Check(bool condition, const char* message)
{
    if (!condition)
    {
        throw std::runtime_error(message);
    }
}

/** @brief 자신이 배타적으로 만든 임시 루트만 소유하고 시험 뒤 회수한다. */
class TemporaryRoot final
{
public:
    TemporaryRoot()
    {
        m_parent = std::filesystem::temp_directory_path().lexically_normal();
        if (m_parent.filename().empty() && m_parent != m_parent.root_path())
        {
            m_parent = m_parent.parent_path();
        }
        root = m_parent / (L"TraceWave-export-" + Display(Uuid()).ToStdWstring());
        Check(root.is_absolute() && root.parent_path() == m_parent, "Temporary export root escaped its parent");
        Check(std::filesystem::create_directory(root), "Temporary export root already exists");
        m_created = true;
    }
    ~TemporaryRoot()
    {
        if (m_created && root.is_absolute() && root.parent_path() == m_parent)
        {
            std::error_code ignored;
            std::filesystem::remove_all(root, ignored);
        }
    }
    Path root;

private:
    Path m_parent;
    bool m_created = false;
};

/** @brief 저장한 바이트를 별도 읽기 handle로 다시 읽는다. */
std::string Read(const Path& path)
{
    std::ifstream stream(path, std::ios::binary);
    Check(stream.is_open(), "Published file is missing under its exact requested name");
    return std::string(std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>());
}

/** @brief 기존 파일은 바꾸지 않고 명시 거절해야 한다. */
void Reject(const Json& response, const Path& path, const Path& workspace)
{
    bool rejected = false;
    try
    {
        WriteNetworkExportFiles(response, wxString(path.native()), wxString(workspace.native()));
    }
    catch (const std::exception&)
    {
        rejected = true;
    }
    Check(rejected, "Export unexpectedly replaced a protected existing path");
}
}

int main()
{
    try
    {
        wxInitializer initialized;
        Check(initialized.IsOk(), "wxWidgets initialization failed");
        TemporaryRoot temporary;
        const Path workspace = temporary.root / Display("원본 작업 공간").ToStdWstring();
        const Path destination = temporary.root / Display("한글 출력 폴더와 긴 경로 - 보존").ToStdWstring() /
                                 (L"export-" + std::wstring(24, L'x'));
        std::filesystem::create_directories(workspace);
        std::filesystem::create_directories(destination);
        const std::string raw = "hello\n";
        const Json sidecar = {{"schema", "rfad.network-export/0.1"},
                              {"source_refs", Json::array({"실제 파일명/원문 보존 시험 전용"})},
                              {"manufacturing", nullptr},
                              {"measurement", nullptr}};
        const Json response = {{"profile", "rfad.network-workspace/0.1"},
                               {"bytes", raw.size()},
                               {"content_base64", "aGVsbG8K"},
                               {"sha256", DisplayMesh::Sha256(raw)},
                               {"sidecar", sidecar}};
        std::set<std::wstring> expected;
        for (int index = 0; index < 16; ++index)
        {
            /** @brief 한글/ASCII/이름 길이를 바꿔 연속 게시와 메모리 배치가 달라도 정확한 이름을 요구한다. */
            std::vector<std::vector<wchar_t>> heapNoise;
            for (std::size_t size = 8; size < 256; size += 3)
            {
                heapNoise.emplace_back(size, L'Z');
            }
            heapNoise.clear();
            const std::wstring name = Display("한글 과거 결과 ").ToStdWstring() + std::to_wstring(index) + L"-" +
                                      std::wstring(static_cast<std::size_t>(index * 3), L'a') + L".csv";
            const Path output = destination / name;
            WriteNetworkExportFiles(response, wxString(output.native()), wxString(workspace.native()));
            const std::wstring conditionsName = name + L".conditions.json";
            Check(Read(output) == raw, "Published CSV bytes differ from the exact source");
            Check(Json::parse(Read(destination / conditionsName)) == sidecar,
                  "Published sidecar lost source or unknown conditions");
            expected.insert(name);
            expected.insert(conditionsName);
            std::set<std::wstring> actual;
            for (const auto& entry : std::filesystem::directory_iterator(destination))
            {
                actual.insert(entry.path().filename().native());
            }
            Check(actual == expected, "An export filename contains extra characters or an unfinished temporary file");
            Reject(response, output, workspace);
            Check(Read(output) == raw, "Rejected duplicate export changed existing original bytes");
        }
        const Path protectedOutput = workspace / L"original.csv";
        Reject(response, protectedOutput, workspace);
        Check(!std::filesystem::exists(protectedOutput), "Export published into the original workspace");
        const Path conflicting = destination / Display("조건 파일이 이미 있음.csv").ToStdWstring();
        const Path conflictMetadata = destination / (conflicting.filename().native() + L".conditions.json");
        {
            std::ofstream stream(conflictMetadata, std::ios::binary);
            stream << "preserve-existing-sidecar";
        }
        Reject(response, conflicting, workspace);
        Check(!std::filesystem::exists(conflicting) && Read(conflictMetadata) == "preserve-existing-sidecar",
              "Conflicting sidecar left a partial new export or changed existing bytes");
        std::cout << "network export: 16 exact Unicode pairs, bytes, sidecars and rejection boundaries passed\n";
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << "Network export test failed: " << error.what() << '\n';
        return 1;
    }
}
