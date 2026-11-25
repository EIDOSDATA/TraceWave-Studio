/** @file @brief Windows의 원본 및 교환 파일과 조건 묶음 저장 경계다. */
#pragma once

#include <filesystem>
#include <nlohmann/json.hpp>
#include <string>

namespace NetworkExportFiles
{
/** @brief 검증한 바이트를 작업 영역 밖의 새 파일로 게시한다. */
void WriteExternal(const std::filesystem::path& path, const std::filesystem::path& workspace, const std::string& bytes);
/** @brief 서비스의 크기와 해시를 검증해 교환 파일과 조건 파일을 함께 게시한다. */
void WriteResult(const nlohmann::json& result, const std::filesystem::path& path, const std::filesystem::path& workspace);
}
