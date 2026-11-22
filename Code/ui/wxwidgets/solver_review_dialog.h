/** @file @brief 해석 입력 편집과 실제 격자 검토의 공개 대화상자 진입점이다. */
#pragma once

#include <functional>
#include <optional>
#include <string>
#include <nlohmann/json.hpp>

class wxWindow;

namespace Studio
{
using PreviewCallback = std::function<void(const nlohmann::json&)>;
using SolverReviewRequest = std::function<void(const char*, const nlohmann::json&, PreviewCallback, PreviewCallback)>;

struct SolverReviewDecision
{
    nlohmann::json settings;
    std::string saveName;
};

/** @brief 사용자가 같은 입력의 검토 결과를 확인하고 실행을 누르면 그 입력을 반환한다. */
std::optional<SolverReviewDecision> ShowSolverReview(wxWindow* parent, const std::string& revision,
    nlohmann::json& draft, const nlohmann::json& catalog, const std::string& resultId, SolverReviewRequest request);
}
