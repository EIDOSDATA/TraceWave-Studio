/** @file @brief 작업 영역별로 실제 열린 프로젝트만 기록한다. */
#pragma once

#include <filesystem>
#include <string>
#include <vector>

class PrototypeRecent
{
public:
    void load(const std::string& layout, const char* workspace);
    void remember(const std::string& path);
    const std::vector<std::string>& paths() const { return paths_; }

private:
    std::filesystem::path file_;
    std::vector<std::string> paths_;
};
