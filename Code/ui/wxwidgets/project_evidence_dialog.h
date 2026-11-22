/** @file @brief 실제 개정의 기록을 보여 주는 공통 읽기 화면이다. */
#pragma once
#include "studio_types.h"
class wxWindow;
/** @brief 열 때 선택할 탭과 복구 관련 선택 결과를 전달한다. */
int ShowProjectEvidence(wxWindow* parent, const Json& evidence, std::size_t page = 0);