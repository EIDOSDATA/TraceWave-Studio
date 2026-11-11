/** @file @brief 연구 입력 변환과 상태/전력 표시를 wxWidgets에서 분리한다. */
#pragma once
#include "studio_types.h"
#include <map>
#include <string>
#include <vector>

namespace Studio
{
/** @brief 조건 화면의 문자열 초안이다. 물리 계산이나 원본 설계는 포함하지 않는다. */
using StudyFields = std::map<std::string, std::string>;
/** @brief 고정 수치 조건을 편집 가능한 문자열 초안으로 투영한다. */
StudyFields StudyDraft(const Json& specification);
/** @brief 기존 조건은 보존하고 새 손실 연구에는 화면의 초기 기준을 명시적으로 고정한다. */
Json StudySpecification(const Json& basis, const StudyFields& fields, bool radiation, bool losses,
                        bool newStudy = false);
/** @brief 연구/단계/판정 상태를 계산 완료와 구분하여 표시한다. */
std::string StudyStatus(const std::string& state);
/** @brief 같은 주파수의 전력과 부호 있는 잔차를 원시 단위로 표시한다. */
std::string StudySummary(const Json& view);
/** @brief 연결/고정 출처와 실제 연구 상태로 제어 버튼을 판정한다. */
bool StudyActionAllowed(const Json& view, const std::string& action, bool pending);
}
