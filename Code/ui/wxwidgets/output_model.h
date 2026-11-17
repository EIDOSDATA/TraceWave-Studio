/** @file @brief 출력 화면의 상태와 원본 소유권을 서비스 계산과 분리한다. */
#pragma once
#include "studio_types.h"
#include <string>

namespace OutputUi
{
/** @brief 이전 표시 파일 읽기가 끝날 때까지 최신 선택 한 개만 보존한다. */
class DeferredDisplay final
{
public:
    void Replace(const Json& request)
    {
        m_request = request;
    }
    void Clear()
    {
        m_request = nullptr;
    }
    bool Empty() const
    {
        return m_request.is_null();
    }
    Json TakeWhenIdle(bool loading)
    {
        if (loading)
        {
            return nullptr;
        }
        auto request = m_request;
        m_request = nullptr;
        return request;
    }

private:
    Json m_request = nullptr;
};
/** @brief 복합 reader 기록을 내부 JSON 없이 실제 도구 이름으로 나열한다. */
std::string Reader(const Json& value);
/** @brief 재검수 작업 이름과 원래 출력 profile을 구분해 실제 용도를 표시한다. */
std::string Purpose(const Json& record);
std::string Text(const Json& value, const std::string& missing = "미정");
std::string State(const std::string& state);
std::string Issues(const Json& issues);
/** @brief 보존된 결과와 조회 시 이름을 보완한 표시 자료를 원본 변경 없이 결합한다. */
Json RecordForDisplay(const Json& record);
/** @brief 다른 스냅샷이나 검토 옵션의 응답을 생성 권한으로 사용하지 않는다. */
bool MatchesPreview(const Json& result, const Json& input);
/** @brief 원문 미정과 파일 형식의 검수 상태를 서로 독립적으로 요약한다. */
std::string Conditions(const Json& record);
}
