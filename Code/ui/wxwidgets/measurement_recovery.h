/** @file @brief 측정 기록의 실제 요청 키를 창 밖에서도 보존하는 표시 상태다. */
#pragma once
#include "studio_types.h"
#include <functional>

struct MeasurementRecovery
{
    Json pending = nullptr;
    std::function<void()> resolved;
};
