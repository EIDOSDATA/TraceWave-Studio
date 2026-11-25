/** @file @brief 봉인된 PCB 해석 입력의 검토, 승인과 작업 상태를 관리한다. */
#pragma once

#include "../wxwidgets/analysis_workflow.h"
#include "prototype_service.h"

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

class PrototypeAnalysis
{
public:
    struct Condition
    {
        std::string id;
        std::string name;
        nlohmann::json settings;
    };

    struct Review
    {
        std::string plan;
        std::string revision;
        std::string condition;
        std::uint64_t cells = 0;
        std::uint64_t bytes = 0;
        int timeout = 0;
        double startGhz = 0.0;
        double stopGhz = 0.0;
        std::size_t samples = 0;
        std::string settings;
        std::string model;
    };

    void acceptConditions(const nlohmann::json& result, const std::string& revision);
    void moveChoice(int direction);
    void review(const std::string& project, const std::string& revision);
    void approve(const std::string& revision);
    void cancel();
    void checkRevision(const std::string& revision);
    void disconnected();
    bool send(PrototypeService& service);
    bool readReply(PrototypeService& service);
    std::string takeResult();

    bool active() const { return previewing_ || workflow_.Active(); }
    bool sealing() const;
    bool urgent() const;
    bool canCancel() const;
    bool canReview(const std::string& revision) const;
    bool canApprove(const std::string& revision) const;
    bool canMove(int direction) const;
    const Condition* condition() const;
    const std::optional<Review>& plan() const { return plan_; }
    const std::string& status() const { return status_; }
    void setStatus(std::string status);

private:
    enum class Request { none, preview, submit, status, cancel };
    void acceptPreview(const nlohmann::json& result);
    void acceptStatus(const nlohmann::json& result);
    void complete(const nlohmann::json& result);
    void finish(std::string status);

    Studio::AnalysisWorkflow workflow_;
    Studio::JobTracker job_;
    Request pending_ = Request::none;
    std::optional<Studio::ServiceCommand> command_;
    std::optional<Review> plan_;
    bool previewing_ = false;
    bool cancelledPreview_ = false;
    bool waitingApproval_ = false;
    bool cancelSent_ = false;
    bool multiport_ = false;
    bool observedWorker_ = false;
    std::string observedState_;
    std::string status_;
    std::string conditionsRevision_;
    std::string project_;
    std::string revision_;
    std::string snapshot_;
    std::string completedResult_;
    nlohmann::json settings_;
    nlohmann::json estimate_;
    std::vector<Condition> conditions_;
    std::size_t choice_ = 0;
};
