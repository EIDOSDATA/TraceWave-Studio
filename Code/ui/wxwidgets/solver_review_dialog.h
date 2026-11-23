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
using SolverPropertyAvailable = std::function<bool(const std::string&)>;

struct SolverRepair
{
    std::string fieldPath;
    std::string message;
};

struct SolverReviewDecision
{
    nlohmann::json settings;
    std::string saveName;
    std::optional<SolverRepair> repair;
    bool editInstallation = false;
    bool multiport = false;
    bool checkpoint = false;
};

/** @brief 검토한 설정의 실행/저장 또는 문제 속성 이동 요청을 반환한다. */
std::optional<SolverReviewDecision> ShowSolverReview(wxWindow* parent, const std::string& revision,
    nlohmann::json& draft, const nlohmann::json& catalog, const std::string& resultId, SolverReviewRequest request,
    SolverPropertyAvailable propertyAvailable);
}
