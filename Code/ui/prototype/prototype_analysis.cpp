#include "prototype_analysis.h"

#include <algorithm>
#include <cstdio>
#include <stdexcept>
#include <utility>

namespace
{
using nlohmann::json;
using Phase = Studio::AnalysisWorkflow::Phase;

constexpr std::array frequencyKeys{"start", "stop", "count"};
constexpr std::array settingKeys{"grid_mm", "air_padding_mm", "curve_tolerance_mm", "feature_subdivisions", "max_timesteps", "end_criterion"};

json conditionNumber(const std::string& text, bool integer, const char* key)
{
    auto value = json::parse(text, nullptr, false);
    if (integer ? !value.is_number_integer() : !value.is_number())
    {
        throw std::runtime_error(std::string("숫자 형식을 확인하세요. (") + key + ")");
    }
    return value;
}

std::string diagnostic(const json& error)
{
    const auto data = error.value("data", json::object());
    const auto& issue = data.contains("message_ko") ? data : error;
    const auto code = data.value("domain_code", issue.value("code", ""));
    const auto message = issue.value("message_ko", error.value("message", "서비스 응답을 확인하세요."));
    const auto path = issue.value("details", json::object()).value("field_path", "");
    return (code.empty() ? "" : code + " ") + message + (path.empty() ? "" : " (" + path + ")");
}

const char* phaseLabel(Phase phase)
{
    switch (phase)
    {
        case Phase::Snapshot: return "입력 스냅샷";
        case Phase::Plan: return "해석 계획";
        case Phase::Prepare: return "계산 입력 준비";
        default: return "openEMS 해석";
    }
}
}

PrototypeAnalysis::ConditionDraft::ConditionDraft(std::string selectedRevision, const Condition* source)
    : revision(std::move(selectedRevision)),
      original_(source ? source->settings : json{{"frequency_hz", {{"start", 2.4e9}, {"stop", 2.4835e9}, {"count", 101}}},
          {"grid_mm", 1.0}, {"air_padding_mm", 30.0}, {"curve_tolerance_mm", 0.05}, {"max_timesteps", 30000}, {"end_criterion", 1e-5}})
{
    const auto& band = original_.at("frequency_hz");
    for (std::size_t index = 0; index < frequencyKeys.size(); ++index)
    {
        values[index] = band.at(frequencyKeys[index]).dump();
    }
    for (std::size_t index = 0; index < settingKeys.size(); ++index)
    {
        values[grid + index] = grid + index == subdivisions ? original_.value(settingKeys[index], json(1)).dump() :
            original_.at(settingKeys[index]).dump();
    }
    if (original_.contains("boundary_conditions"))
    {
        const auto& modes = original_.at("boundary_conditions");
        if (!modes.is_array() || modes.size() != boundaries.size())
        {
            throw std::runtime_error("저장된 외벽 조건을 읽을 수 없습니다.");
        }
        for (std::size_t index = 0; index < boundaries.size(); ++index)
        {
            const auto selected = std::ranges::find(boundaryModes, modes.at(index).get_ref<const std::string&>());
            if (selected == boundaryModes.end())
            {
                throw std::runtime_error("저장된 외벽 종류를 읽을 수 없습니다.");
            }
            boundaries[index] = static_cast<int>(selected - boundaryModes.begin());
        }
    }
}

bool PrototypeAnalysis::ConditionDraft::hasDirectPoints() const
{
    return original_.at("frequency_hz").contains("points");
}

/** @brief 편집한 값만 원본 사본에 반영해 선택 설정과 직접 표본을 보존한다. */
json PrototypeAnalysis::ConditionDraft::settings() const
{
    auto result = original_;
    if (!hasDirectPoints())
    {
        auto& band = result.at("frequency_hz");
        for (std::size_t index = 0; index < frequencyKeys.size(); ++index)
        {
            const auto* key = frequencyKeys[index];
            if (values[index] != band.at(key).dump())
            {
                band[key] = conditionNumber(values[index], index == samples, key);
            }
        }
    }
    for (std::size_t index = 0; index < settingKeys.size(); ++index)
    {
        const auto* key = settingKeys[index];
        const auto field = grid + index;
        const auto existing = field == subdivisions ? result.value(key, json(1)) : result.at(key);
        if (values[field] != existing.dump())
        {
            result[key] = conditionNumber(values[field], field == subdivisions || field == timesteps, key);
        }
    }
    if (result.contains("boundary_conditions") || std::ranges::any_of(boundaries, [](int mode) { return mode != 0; }))
    {
        auto modes = json::array();
        for (const int mode : boundaries)
        {
            modes.push_back(boundaryModes.at(static_cast<std::size_t>(mode)));
        }
        result["boundary_conditions"] = std::move(modes);
    }
    return result;
}

void PrototypeAnalysis::setStatus(std::string status)
{
    status_ = std::move(status);
}

const PrototypeAnalysis::Condition* PrototypeAnalysis::condition() const
{
    return conditions_.empty() ? nullptr : &conditions_[choice_];
}

bool PrototypeAnalysis::canMove(int direction) const
{
    return !active() && condition() &&
        ((direction < 0 && choice_ > 0) || (direction > 0 && choice_ + 1 < conditions_.size()));
}

void PrototypeAnalysis::moveChoice(int direction)
{
    if (canMove(direction))
    {
        choice_ = direction < 0 ? choice_ - 1 : choice_ + 1;
        status_.clear();
    }
}

void PrototypeAnalysis::selectCondition(const std::string& id)
{
    const auto selected = std::ranges::find(conditions_, id, &Condition::id);
    if (selected != conditions_.end())
    {
        choice_ = static_cast<std::size_t>(selected - conditions_.begin());
    }
}

void PrototypeAnalysis::acceptConditions(const json& result, const std::string& revision)
{
    const auto& saved = result.at("saved");
    if (result.at("revision_id") != revision || !saved.is_array() || saved.size() > 32)
    {
        throw std::runtime_error("해석 조건의 개정 또는 목록 범위가 올바르지 않습니다.");
    }
    const auto previous = condition() ? condition()->id : std::string{};
    std::vector<Condition> conditions;
    for (const auto& value : saved)
    {
        Condition row{value.at("id").get<std::string>(), value.at("name").get<std::string>(), value.at("settings")};
        if (row.id.empty() || row.name.empty() || !row.settings.is_object())
        {
            throw std::runtime_error("저장된 해석 조건을 읽을 수 없습니다.");
        }
        conditions.push_back(std::move(row));
    }
    conditions_ = std::move(conditions);
    choice_ = 0;
    selectCondition(previous);
    conditionsRevision_ = revision;
    setStatus(conditions_.empty() ? "저장된 해석 조건이 없습니다. 새 조건을 추가하세요." : "");
}

bool PrototypeAnalysis::sealing() const
{
    return previewing_ || workflow_.CurrentPhase() == Phase::Snapshot;
}

bool PrototypeAnalysis::urgent() const
{
    return sealing() || (active() && workflow_.CancellationRequested() && !cancelSent_) ||
        (command_ && !waitingApproval_);
}

bool PrototypeAnalysis::canCancel() const
{
    return previewing_ ? !cancelledPreview_ : workflow_.CanRequestCancel();
}

bool PrototypeAnalysis::canReview(const std::string& revision) const
{
    return !active() && condition() && revision == conditionsRevision_;
}

bool PrototypeAnalysis::canApprove(const std::string& revision) const
{
    return waitingApproval_ && plan_ && plan_->revision == revision;
}

void PrototypeAnalysis::review(const std::string& project, const std::string& revision)
{
    if (!canReview(revision))
    {
        return;
    }
    project_ = project;
    revision_ = revision;
    settings_ = condition()->settings;
    previewing_ = true;
    setStatus("현재 개정의 해석 조건을 검사하는 중");
}

void PrototypeAnalysis::approve(const std::string& revision)
{
    if (canApprove(revision))
    {
        waitingApproval_ = false;
        setStatus("검토한 계획의 계산 입력을 준비하는 중");
    }
}

void PrototypeAnalysis::cancel()
{
    if (!canCancel())
    {
        return;
    }
    if (job_.Empty() && pending_ == Request::none)
    {
        finish("해석을 실행하기 전에 취소했습니다.");
        return;
    }
    if (previewing_)
    {
        cancelledPreview_ = true;
    }
    else
    {
        workflow_.RequestCancel();
    }
    setStatus("해석 취소 요청 중");
}

void PrototypeAnalysis::checkRevision(const std::string& revision)
{
    if (waitingApproval_ && revision_ != revision)
    {
        finish("개정이 바뀌었습니다. 조건을 다시 읽고 새 계획을 검토하세요.");
    }
    else if (!active() && !conditionsRevision_.empty() && conditionsRevision_ != revision)
    {
        conditionsRevision_.clear();
        conditions_.clear();
        choice_ = 0;
    }
}

/** @brief 서비스 전송을 다른 프로젝트 작업과 공유하고 미승인 계획은 대기한다. */
bool PrototypeAnalysis::send(PrototypeService& service)
{
    using namespace std::chrono_literals;
    if (!active() || pending_ != Request::none || waitingApproval_)
    {
        return false;
    }
    bool sent = false;
    const json context{{"project_id", project_}};
    if (previewing_)
    {
        sent = service.request("solver.preview", context,
            {{"expected_revision", revision_}, {"settings", settings_}, {"include_all_diagnostics", true}});
        pending_ = Request::preview;
    }
    else if (workflow_.CancellationRequested() && !cancelSent_ && !job_.Empty() && !workflow_.CanRequestCancel())
    {
        sent = service.request("job.cancel", json::object(),
            {{"job_id", job_.Id()}, {"reason", "GUI 해석 작업 취소"}}, true);
        pending_ = Request::cancel;
    }
    else if (command_)
    {
        sent = service.request(command_->method.c_str(), context, command_->input, true);
        command_.reset();
        pending_ = Request::submit;
    }
    else
    {
        if (!job_.BeginPoll(Studio::Clock::now(), cancelSent_ ? 75ms : 150ms))
        {
            return false;
        }
        sent = service.request("job.status", json::object(), {{"job_id", job_.Id()}});
        pending_ = Request::status;
    }
    if (!sent)
    {
        finish("해석 요청을 보내지 못했습니다. 서비스와 작업 상태를 다시 확인하세요.");
    }
    return sent;
}

bool PrototypeAnalysis::readReply(PrototypeService& service)
{
    if (pending_ == Request::none)
    {
        return true;
    }
    const auto reply = service.takeReply();
    if (reply.is_null())
    {
        return false;
    }
    const auto request = std::exchange(pending_, Request::none);
    try
    {
        if (request == Request::preview && cancelledPreview_)
        {
            finish("해석을 실행하기 전에 취소했습니다.");
            return true;
        }
        if (reply.contains("error"))
        {
            throw std::runtime_error(diagnostic(reply.at("error")));
        }
        const auto& result = reply.at("result");
        switch (request)
        {
            case Request::preview:
                acceptPreview(result);
                break;
            case Request::submit:
                job_.Assign(result.at("job_id").get<std::string>());
                std::printf("Solver accepted: phase=%s job=%s revision=%s\n", workflow_.PhaseName().c_str(),
                    job_.Id().c_str(), revision_.c_str());
                if (!workflow_.CancellationRequested())
                {
                    setStatus(std::string(phaseLabel(workflow_.CurrentPhase())) + " 작업 대기 중");
                }
                break;
            case Request::status:
                acceptStatus(result);
                break;
            case Request::cancel:
                if (result.at("job_id") != job_.Id())
                {
                    throw std::runtime_error("해석 취소 영수증의 작업 ID가 다릅니다.");
                }
                cancelSent_ = true;
                setStatus("해석 작업 종료를 확인하는 중");
                std::printf("Solver cancel receipt: job=%s state=%s\n", job_.Id().c_str(),
                    result.at("state").get_ref<const std::string&>().c_str());
                break;
            case Request::none:
                break;
        }
    }
    catch (const std::exception& error)
    {
        const auto message = std::string("해석 요청 실패. ") + error.what();
        if (request == Request::cancel)
        {
            workflow_.AllowCancelRetry();
            setStatus(message);
        }
        else if (request == Request::status && !job_.Empty())
        {
            job_.AbandonPoll();
            setStatus(message);
        }
        else
        {
            finish(message);
        }
    }
    return true;
}

void PrototypeAnalysis::acceptPreview(const json& result)
{
    if (result.at("revision_id") != revision_)
    {
        throw std::runtime_error("해석 미리보기 개정이 다릅니다.");
    }
    if (result.contains("blocking_diagnostics"))
    {
        const auto& issues = result.at("blocking_diagnostics");
        if (!issues.is_array() || issues.empty())
        {
            throw std::runtime_error("해석 입력의 오류 목록을 읽을 수 없습니다.");
        }
        const auto count = result.at("blocking_total").get<std::size_t>();
        finish("해석 입력 오류 " + std::to_string(count) + "건. " + diagnostic(issues.front()));
        return;
    }
    estimate_ = result.at("estimated");
    settings_ = result.at("settings");
    multiport_ = result.contains("multiport");
    previewing_ = false;
    command_ = workflow_.Begin(revision_, settings_, multiport_);
    setStatus("해석 입력 개정을 봉인하는 중");
}

void PrototypeAnalysis::acceptStatus(const json& result)
{
    if (!job_.EndPoll(result.at("job_id").get<std::string>()))
    {
        throw std::runtime_error("해석 상태 응답의 작업 ID가 다릅니다.");
    }
    const auto state = result.at("state").get<std::string>();
    const auto& events = result.at("events");
    if (!events.is_array() || events.empty() || events.back().at("state") != state)
    {
        throw std::runtime_error("해석 작업의 상태 이력이 올바르지 않습니다.");
    }
    const bool worker = result.value("guest_worker_attached", false);
    if (observedState_ != state || observedWorker_ != worker)
    {
        std::printf("Solver job: phase=%s job=%s state=%s worker=%d\n", workflow_.PhaseName().c_str(),
            job_.Id().c_str(), state.c_str(), worker ? 1 : 0);
        observedState_ = state;
        observedWorker_ = worker;
    }
    const auto& last = events.back();
    if (state == "completed")
    {
        job_.Reset();
        if (workflow_.CancellationRequested())
        {
            finish(workflow_.CurrentPhase() == Phase::Analysis
                ? "해석 완료가 취소보다 먼저 확정됐습니다. 결과를 다시 읽어 확인하세요."
                : "취소 요청 뒤 해석의 후속 단계를 중단했습니다.");
        }
        else
        {
            complete(last.at("operation_result"));
        }
    }
    else if (state == "cancelled")
    {
        const bool confirmed = last.value("termination_confirmed", false) && !last.value("outcome_unknown", false);
        std::printf("Solver cancellation: job=%s termination_confirmed=%d\n", job_.Id().c_str(), confirmed ? 1 : 0);
        finish(confirmed ? "해석 취소 완료. 작업 종료를 확인했습니다." : "해석이 취소됐습니다. 작업 종료를 확인할 수 없습니다.");
    }
    else if (state == "failed" || state == "interrupted" || state == "timeout")
    {
        finish(last.value("outcome_unknown", false) ? "해석이 중단됐습니다. 작업 종료 확인이 필요합니다."
            : "해석 실패. " + diagnostic(last.value("error", json::object())));
    }
    else if (workflow_.CancellationRequested() || state == "cancel_requested")
    {
        if (cancelSent_ || state == "cancel_requested")
        {
            setStatus("해석 작업 종료를 확인하는 중");
        }
    }
    else if (state == "postprocessing")
    {
        setStatus("해석 결과를 정리하는 중");
    }
    else if (workflow_.CurrentPhase() == Phase::Analysis && state == "running" && worker)
    {
        setStatus("openEMS 해석 실행 중");
    }
    else
    {
        setStatus(std::string(phaseLabel(workflow_.CurrentPhase())) +
            (state == "queued" ? " 작업 대기 중" : " 작업 진행 중"));
    }
}

/** @brief 검토와 실제 계획의 자원값을 대조하고 승인 전에는 준비 작업을 보내지 않는다. */
void PrototypeAnalysis::complete(const json& result)
{
    const auto phase = workflow_.CurrentPhase();
    if (phase == Phase::Snapshot)
    {
        if (result.at("project_id") != project_ || result.at("revision_id") != revision_)
        {
            throw std::runtime_error("봉인된 해석 입력의 프로젝트 또는 개정이 다릅니다.");
        }
        snapshot_ = result.at("snapshot_id").get<std::string>();
    }
    else if (phase == Phase::Plan)
    {
        const auto& budget = result.at("resource_estimate");
        const auto* expected = multiport_ ? "rfad.openems.pcb-multiport/0.1" : "rfad.openems.pcb-single-port/0.1";
        if (result.at("profile") != expected || budget != estimate_)
        {
            throw std::runtime_error("검토한 해석 범위 또는 자원 예상값과 봉인된 계획이 다릅니다.");
        }
        const auto& band = settings_.at("frequency_hz");
        plan_ = Review{result.at("analysis_plan").at("plan_id").get<std::string>(), revision_, condition()->name,
            budget.at("estimated_grid_points").get<std::uint64_t>(), budget.at("estimated_memory_bytes").get<std::uint64_t>(),
            budget.at("max_wall_time_seconds").get<int>(), band.at("start").get<double>() / 1e9,
            band.at("stop").get<double>() / 1e9, band.at("count").get<std::size_t>(), settings_.dump(2),
            result.at("model_report").dump(2)};
    }
    else if (phase == Phase::Analysis)
    {
        const auto& snapshot = result.at("snapshot");
        if (snapshot.at("snapshot_id") != snapshot_ || snapshot.at("project_id") != project_ ||
            snapshot.at("revision_id") != revision_)
        {
            throw std::runtime_error("완료 결과의 입력 스냅샷이 검토한 계획과 다릅니다.");
        }
    }
    command_ = workflow_.Complete(result);
    if (phase == Phase::Plan)
    {
        waitingApproval_ = true;
        setStatus("계획 검토 완료. 검토한 입력으로 해석 실행을 선택하세요.");
    }
    else if (phase == Phase::Analysis)
    {
        completedResult_ = PublishedResult{result.at("artifact_id").get<std::string>(), multiport_,
            result.at("snapshot"), result.at("normalized_result")};
        finish("해석 완료. 봉인된 결과를 읽는 중");
    }
}

void PrototypeAnalysis::disconnected()
{
    if (active())
    {
        finish("서비스 연결이 끊겼습니다. 해석 작업의 최종 상태는 다시 열어 확인하세요.");
    }
}

std::optional<PrototypeAnalysis::PublishedResult> PrototypeAnalysis::takeResult()
{
    return std::exchange(completedResult_, std::nullopt);
}

void PrototypeAnalysis::finish(std::string status)
{
    workflow_.Stop();
    job_.Reset();
    pending_ = Request::none;
    command_.reset();
    plan_.reset();
    previewing_ = false;
    cancelledPreview_ = false;
    waitingApproval_ = false;
    cancelSent_ = false;
    observedState_.clear();
    observedWorker_ = false;
    setStatus(std::move(status));
}
