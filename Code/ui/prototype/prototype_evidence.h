#pragma once

#include <nlohmann/json.hpp>

#include <array>
#include <cstddef>
#include <string>
#include <vector>

/** @brief 저장소의 권위 개정에서 조회한 출처와 변경 이력의 화면 데이터다. */
struct PrototypeEvidence
{
    struct Record
    {
        std::string label;
        std::string source;
        std::string assumptions;
        std::vector<std::array<std::string, 4>> values;
    };

    struct Change
    {
        std::string before;
        std::string after;
        std::string command;
        std::string target;
        std::string targetId;
        std::string time;
        std::string reason;
    };

    static PrototypeEvidence read(const nlohmann::json& reply);
    std::vector<Record> records;
    std::vector<Change> changes;
    std::size_t changeCount = 0;
    std::size_t redoCount = 0;
};
