/** @file @brief 실제 Windows GPU 표본의 공통 읽기 경계다. */
#pragma once
#include "studio_types.h"

namespace StudioSmoke
{
/** @brief 현재 GUI 프로세스의 어댑터별 DXGI 메모리 사용량을 읽는다. */
Json GpuMemorySamples();
}
