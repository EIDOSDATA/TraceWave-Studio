/** @file @brief 화면 경계의 JSON 및 단조 시각 별칭이다. */
#pragma once
#include <chrono>
#include <nlohmann/json.hpp>

using Json = nlohmann::json;
using Clock = std::chrono::steady_clock;
