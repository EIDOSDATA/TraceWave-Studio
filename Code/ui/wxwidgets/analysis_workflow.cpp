/** @file @brief 해석 절차는 위젯 없이 명령과 상태만으로 진행한다. */
#include "analysis_workflow.h"
#include <stdexcept>

namespace Studio
{
ServiceCommand AnalysisWorkflow::Begin(const std::string& revision, const Json& settings)
{
    if (Active() || revision.empty())
    {
        throw std::logic_error("Analysis is active or revision is missing.");
    }
    m_settings = settings;
    m_phase = Phase::Snapshot;
    m_cancelRequested = false;
    m_cancelDeliveryPending = false;
    return {"snapshot.create", Json{{"expected_revision", revision}, {"description", "GUI PCB 해석 입력"}}};
}

std::optional<ServiceCommand> AnalysisWorkflow::Complete(const Json& result)
{
    if (!Active() || m_cancelRequested)
    {
        throw std::logic_error("Analysis transition is inactive or cancelled.");
    }
    ServiceCommand next;
    Phase phase;
    switch (m_phase)
    {
    case Phase::Snapshot:
        next = {"solver.plan", Json{{"snapshot", Json{{"snapshot_id", result.at("snapshot_id")},
                                                      {"content_hash", result.at("content_hash")}}},
                                    {"analysis_profile", "rfad.openems.pcb-single-port/0.1"},
                                    {"runtime_profile", "openems-wsl-reference/0.1"},
                                    {"settings", m_settings}}};
        phase = Phase::Plan;
        break;
    case Phase::Plan:
    {
        const auto& plan = result.at("analysis_plan");
        next = {"solver.prepare", Json{{"analysis_plan", Json{{"plan_id", plan.at("plan_id")},
                                                              {"content_hash", plan.at("content_hash")}}},
                                       {"budget", Json{{"timeout_seconds", 300}}}}};
        phase = Phase::Prepare;
        break;
    }
    case Phase::Prepare:
    {
        const auto& prepared = result.at("prepared_plan");
        next = {"job.submit",
                Json{{"task_plan", Json{{"kind", "em_analysis"},
                                        {"prepared_plan", Json{{"prepared_plan_id", prepared.at("prepared_plan_id")},
                                                               {"content_hash", prepared.at("content_hash")}}},
                                        {"execution_mode", "solve_and_postprocess"}}},
                     {"budget", Json{{"timeout_seconds", 300}}}}};
        phase = Phase::Analysis;
        break;
    }
    case Phase::Analysis:
        result.at("artifact_id").get<std::string>();
        m_phase = Phase::Completed;
        return std::nullopt;
    default:
        throw std::logic_error("Unexpected analysis phase.");
    }
    m_phase = phase;
    return next;
}

void AnalysisWorkflow::RequestCancel()
{
    if (Active())
    {
        m_cancelRequested = true;
        m_cancelDeliveryPending = true;
    }
}

void AnalysisWorkflow::AllowCancelRetry()
{
    m_cancelDeliveryPending = false;
}

void AnalysisWorkflow::Stop()
{
    m_phase = Phase::Stopped;
    m_cancelDeliveryPending = false;
}

bool AnalysisWorkflow::Active() const
{
    return m_phase == Phase::Snapshot || m_phase == Phase::Plan || m_phase == Phase::Prepare ||
           m_phase == Phase::Analysis;
}

bool AnalysisWorkflow::CancellationRequested() const
{
    return m_cancelRequested;
}

bool AnalysisWorkflow::CanRequestCancel() const
{
    return Active() && !m_cancelDeliveryPending;
}

AnalysisWorkflow::Phase AnalysisWorkflow::CurrentPhase() const
{
    return m_phase;
}

std::string AnalysisWorkflow::PhaseName() const
{
    switch (m_phase)
    {
    case Phase::Idle:
        return "idle";
    case Phase::Snapshot:
        return "snapshot";
    case Phase::Plan:
        return "plan";
    case Phase::Prepare:
        return "prepare";
    case Phase::Analysis:
        return "analysis";
    case Phase::Completed:
        return "completed";
    case Phase::Stopped:
        return "stopped";
    }
    throw std::logic_error("Unknown analysis phase.");
}
}
