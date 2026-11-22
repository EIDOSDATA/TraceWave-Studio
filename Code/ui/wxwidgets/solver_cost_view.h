/** @file @brief 실행 전 예상과 종료 후 비용 비교를 표시한다. */
#pragma once

#include <nlohmann/json.hpp>
#include <wx/string.h>

class wxWindow;

namespace Studio
{
wxString SolverEstimateText(const nlohmann::json& estimate);
void ShowSolverCost(wxWindow* parent, const nlohmann::json& completed,
                    const nlohmann::json& lastAttempt, bool preferAttempt);
}
