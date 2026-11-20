/** @file @brief 재현용 표시 파일의 유한 참조를 두 Windows 계측 도구에서 읽는다. */
#pragma once

#include <filesystem>
#include <fstream>
#include <nlohmann/json.hpp>
#include <stdexcept>
#include <string>

/** @brief 표시 본문과 스냅샷/실행 결합의 검증은 제품 로더가 수행한다. */
inline nlohmann::json ReadLargeDisplayFixture(const std::filesystem::path& directory)
{
    std::ifstream metadata(directory / "fixture.json", std::ios::binary);
    std::string bytes(65537, '\0');
    metadata.read(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    if (!metadata.eof() || metadata.gcount() <= 0 || metadata.gcount() > 65536)
    {
        throw std::runtime_error("대형 표시 시험의 fixture.json을 읽을 수 없습니다.");
    }
    bytes.resize(static_cast<std::size_t>(metadata.gcount()));
    return nlohmann::json::parse(bytes);
}
