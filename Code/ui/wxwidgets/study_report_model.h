/** @file @brief 두 수렴 보고서 형식의 읽기 전용 표시 모델이다. */
#pragma once

#include "studio_types.h"
#include <string>
#include <vector>

namespace Studio
{
/** @brief 표와 판정 문구만 가지며 원본 결과의 재판정을 수행하지 않는다. */
struct StudyReportView
{
    std::vector<std::string> columns;
    std::vector<std::vector<std::string>> rows;
    std::string summary;
};

/** @brief 완료된 IFA 또는 방사 연구의 제한된 표/설명을 만든다. */
StudyReportView PresentStudyReport(const Json& report);
}
