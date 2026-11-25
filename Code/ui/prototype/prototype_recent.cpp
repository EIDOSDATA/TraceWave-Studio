#include "prototype_recent.h"

#include "../wxwidgets/display_mesh.h"
#include "prototype_service.h"

#include <algorithm>
#include <fstream>
#include <string_view>

namespace
{
constexpr std::size_t limit = 8;
constexpr std::size_t fileLimit = 12 * 1024;

std::filesystem::path Utf8(std::string_view text)
{
    return std::filesystem::path(std::u8string(text.begin(), text.end()));
}

bool Valid(std::string_view path)
{
    constexpr std::string_view root = "projects/";
    if (!path.starts_with(root) || path.size() > 1024)
    {
        return false;
    }
    const auto name = path.substr(root.size());
    return !name.empty() && name != "." && name != ".." &&
        name.find_first_of("/\\:\r\n") == std::string_view::npos && name.find('\0') == std::string_view::npos;
}
}

/** @brief 현재 작업 영역의 최근 목록만 읽고 불완전한 설정은 빈 목록으로 처리한다. */
void PrototypeRecent::load(const std::string& layout, const char* workspace)
{
    if (layout.empty() || !workspace)
    {
        return;
    }
    try
    {
        const auto key = std::filesystem::weakly_canonical(Utf8(workspace)).generic_u8string();
        const std::string keyBytes(key.begin(), key.end());
        file_ = Utf8(layout).parent_path() / ("recent-" + DisplayMesh::Sha256(keyBytes) + ".json");
        std::ifstream input(file_, std::ios::binary);
        std::string raw(fileLimit + 1, '\0');
        input.read(raw.data(), static_cast<std::streamsize>(raw.size()));
        if (!input.eof() || input.gcount() == 0 || input.gcount() > static_cast<std::streamsize>(fileLimit))
        {
            return;
        }
        raw.resize(static_cast<std::size_t>(input.gcount()));
        const auto records = nlohmann::json::parse(raw);
        if (!records.is_array() || records.size() > limit)
        {
            return;
        }
        for (const auto& entry : records)
        {
            if (entry.is_string())
            {
                const auto& path = entry.get_ref<const std::string&>();
                if (Valid(path) && std::ranges::find(paths_, path) == paths_.end())
                {
                    paths_.push_back(path);
                }
            }
        }
    }
    catch (const std::exception&)
    {
        paths_.clear();
    }
}

/** @brief 열린 경로를 앞에 두고 같은 폴더의 임시 파일을 완성한 뒤 교체한다. */
void PrototypeRecent::remember(const std::string& path)
{
    if (!Valid(path) || (!paths_.empty() && paths_.front() == path))
    {
        return;
    }
    std::erase(paths_, path);
    paths_.insert(paths_.begin(), path);
    if (paths_.size() > limit)
    {
        paths_.resize(limit);
    }
    if (file_.empty())
    {
        return;
    }
    const auto operation = PrototypeService::newCommandId();
    if (operation.empty())
    {
        return;
    }
    auto temp = file_;
    temp += "." + operation + ".tmp";
    try
    {
        std::ofstream out(temp, std::ios::binary);
        out << nlohmann::json(paths_).dump();
        out.close();
        if (out && MoveFileExW(temp.c_str(), file_.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
        {
            return;
        }
    }
    catch (const std::exception&)
    {
    }
    std::error_code ec;
    std::filesystem::remove(temp, ec);
}
