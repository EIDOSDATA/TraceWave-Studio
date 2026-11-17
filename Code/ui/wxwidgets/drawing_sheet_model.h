/** @file @brief 서비스가 배치한 종이 좌표 벡터만 검증하여 표시한다. */
#pragma once
#include "studio_types.h"
#include <string>

namespace DrawingSheet
{
/** @brief 출력 단위나 치수를 다시 계산하지 않고 유한한 표시 DTO만 수용한다. */
void ValidatePages(const Json& pages);
/** @brief 명시한 종이와 표시 공간의 비율을 유지하는 화면 배치이다. */
struct Placement
{
    double x = 0.0;
    double y = 0.0;
    double scale = 0.0;
    double width = 0.0;
    double height = 0.0;
};
Placement Fit(double paperWidth, double paperHeight, double width, double height, double margin);
}
