/** @file @brief 도면 및 PCB 출력의 입력 동결, 승인과 게시 상태를 관리한다. */
#pragma once

#include "../wxwidgets/async_state.h"
#include "prototype_service.h"

#include <array>
#include <optional>

class PrototypeExchange
{
public:
    struct Published
    {
        std::string job;
        std::string revision;
        std::string uri;
        std::string sha256;
        std::string manifest;
        nlohmann::json snapshot;
    };

    void moveFormat(int direction);
    void startReview(const std::string& project, const std::string& revision);
    void approve(const std::string& revision);
    void startVerify(const std::string& project);
    void reload(const std::string& project);
    void cancel();
    void checkRevision(const std::string& revision);
    void disconnected();
    bool send(PrototypeService& service);
    bool readReply(PrototypeService& service);

    bool active() const { return phase_ != Phase::idle; }
    bool sealing() const { return phase_ == Phase::seal || phase_ == Phase::context; }
    bool urgent() const { return sealing() || (cancelRequested_ && !cancelSent_); }
    bool canMove(int direction) const;
    bool canApprove(const std::string& revision) const;
    bool canCancel() const;
    const char* name() const;
    const std::string& status() const { return status_; }
    const nlohmann::json& review() const { return review_; }
    const std::optional<Published>& published() const { return published_[format_]; }

private:
    enum class Phase { idle, seal, context, preview, approval, build, verify, list, record };
    enum class Request { none, acceptJob, poll, context, cancel, list, record };

    nlohmann::json snapshotInput() const;
    void acceptContext(const nlohmann::json& result);
    void acceptStatus(const nlohmann::json& result);
    void complete(const nlohmann::json& result);
    void acceptList(const nlohmann::json& result);
    void acceptPublished(const nlohmann::json& result, const std::string& job, const nlohmann::json& manifestHash = nullptr);
    void finish(std::string status);

    Phase phase_ = Phase::idle;
    Request pending_ = Request::none;
    Studio::JobTracker job_;
    std::size_t format_ = 0;
    std::array<std::optional<Published>, 3> published_;
    std::string project_;
    std::string revision_;
    std::string status_;
    nlohmann::json snapshot_;
    nlohmann::json input_;
    nlohmann::json review_;
    bool cancelRequested_ = false;
    bool cancelSent_ = false;
    std::string observedState_;
    bool observedWorker_ = false;
    std::size_t listOffset_ = 0;
    double latestTime_ = 0;
    std::string latestId_;
};
