/** @file @brief 선택한 해석 결과의 봉인 개정과 계산 입력을 읽기 전용으로 연다. */
#pragma once
#include "dialog_gateway.h"

class wxWindow;

/** @brief 그래프, 공통 결과 탐색과 방사 패턴에서 같은 결과의 봉인 입력을 연다. */
void ShowSolverEvidence(wxWindow* parent, const std::string& artifact, DialogGateway gateway);
