/** @file @brief 현재 연구의 공정 시료 원문을 선택하는 대화상자다. */
#pragma once
#include <nlohmann/json.hpp>
#include <wx/string.h>

class wxWindow;

/** @brief 변수별 단위를 가진 양식을 저장하고 읽기 전용 비교 입력을 반환한다. */
void SelectSweepSamples(wxWindow* parent, const wxString& workspace, const nlohmann::json& axes,
                        const nlohmann::json& labels, nlohmann::json& options);
