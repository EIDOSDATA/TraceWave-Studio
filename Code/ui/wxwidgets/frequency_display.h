/** @file @brief 주파수 SI 원본을 수정하지 않는 공통 화면 표시 형식이다. */
#pragma once
#include "studio_types.h"
#include <string>

namespace StudioFrequency
{
/** @brief 축/표 전체가 공유하는 표시 단위와 십진 접두어 배율이다. */
struct Scale
{
    std::string unit;
    double divisor = 1.0;
};

/** @brief 자동 선택은 유한한 범위의 최대 절댓값을 Hz/kHz/MHz/GHz로 표시한다. */
Scale ForRange(double minHz, double maxHz, const std::string& requested = "auto");
/** @brief frequency_hz를 가진 실제 표본 목록에서 단위를 선택한다. */
Scale ForSamples(const Json& samples, const std::string& requested = "auto");
Scale ForPage(const Json& page, const std::string& requested = "auto");
/** @brief 전체 자료 범위를 사용하여 표본 페이지를 이동해도 단위를 유지한다. */
Scale ForDescriptor(const Json& descriptor, const std::string& requested = "auto");
/** @brief 평가 근거와 선택 자료의 봉인 파일 해시가 같을 때만 보조 범위를 사용한다. */
bool AssessmentMatchesDataset(const Json& assessment, const Json& selection);
/** @brief 저장된 평가 전체 범위를 읽고 입력 표현식은 계산하지 않는다. */
Scale ForAssessment(const Json& assessment, const Json& descriptor = Json(nullptr),
                    const std::string& requested = "auto");
/** @brief Hz, kHz, MHz, GHz의 입력을 계산 계약의 유한한 양수 Hz로 변환한다. 단위 생략 시 Hz다. */
double ReadInput(const std::string& text);
/** @brief 공학 단위로 정확히 왕복할 수 있는 값을 편집 문자열로 표시한다. */
std::string Input(const Json& frequencyHz);
/** @brief 다중 입력의 순서와 모든 주파수 원본을 유지한다. */
std::string InputList(const Json& frequencies);
/** @brief 물리 계산이나 DTO 변경 없이 표시 숫자만 서식화한다. */
std::string Value(const Json& frequencyHz, const Scale& scale, int precision = 15);
std::string WithUnit(const Json& frequencyHz, const std::string& requested = "auto");
std::string Range(const Json& minHz, const Json& maxHz, const std::string& requested = "auto");
}
