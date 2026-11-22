/** @file @brief 탐색에서 선택한 개정, 기록과 고정 해석 결과를 읽는다. */
#pragma once
#include "dialog_gateway.h"

class wxWindow;

/** @brief 선택한 해석 결과의 source와 pin을 반환하며, 닫기만 하면 null을 반환한다. */
Json ShowProjectActivity(wxWindow* parent, const std::string& revision, const std::string& object,
                         DialogGateway gateway);
