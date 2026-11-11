/** @file @brief GUI와 분리한 단일 포트 해석의 명시적 단계 상태 머신이다. */
#pragma once
#include "async_state.h"

namespace Studio
{
/** @brief presenter가 서비스에 전달할 한 단계의 변경 명령이다. */
struct ServiceCommand
{
    std::string method;
    Json input;
};

/** @brief 스냅샷/계획/준비/해석 순서와 취소 이후 진행 금지를 소유한다. */
class AnalysisWorkflow final
{
public:
    enum class Phase
    {
        Idle,
        Snapshot,
        Plan,
        Prepare,
        Analysis,
        Completed,
        Stopped
    };
    /** @brief 시작 당시의 해석 설정을 복사해 이후 화면 입력 변경과 분리한다. */
    ServiceCommand Begin(const std::string& revision, const Json& settings);
    /** @brief 현재 단계의 완료 자료만 다음 명령으로 변환한다. */
    std::optional<ServiceCommand> Complete(const Json& result);
    /** @brief 실제 작업 종료와 별개로 다음 단계 전이를 막는다. */
    void RequestCancel();
    /** @brief 중단 의도를 유지한 채 취소 요청 전달 실패 후 재시도만 허용한다. */
    void AllowCancelRetry();
    /** @brief 실패/취소 시 진행을 멈추되 기존 결과 표시는 건드리지 않는다. */
    void Stop();
    bool Active() const;
    bool CancellationRequested() const;
    /** @brief 요청 전달 중복을 막으며 이전 전달 실패 후에도 재시도를 허용한다. */
    bool CanRequestCancel() const;
    Phase CurrentPhase() const;
    std::string PhaseName() const;

private:
    Phase m_phase = Phase::Idle;
    bool m_cancelRequested = false;
    bool m_cancelDeliveryPending = false;
    Json m_settings = Json::object();
};
}
