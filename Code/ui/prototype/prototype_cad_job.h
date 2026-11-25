/** @file @brief 기존 Windows CAD 작업자의 입력 봉인, 실행 및 취소를 연결한다. */
#pragma once

#include "../wxwidgets/async_state.h"
#include "prototype_cad.h"
#include "prototype_service.h"

#include <optional>

class PrototypeCadJob
{
public:
    enum class Output { geometry, step };
    struct PublishedStep
    {
        std::string revision;
        std::string uri;
        std::string sha256;
    };

    void start(const std::string& project, const std::string& revision, Output output);
    void cancel();
    bool send(PrototypeService& service);
    bool readReply(PrototypeService& service, PrototypeCad& cad);
    void disconnected();

    bool active() const { return phase_ != Phase::idle; }
    bool sealing() const { return phase_ == Phase::seal || phase_ == Phase::sealStatus; }
    bool canCancel() const { return active() && !cancelRequested_; }
    bool urgent() const { return sealing() || phase_ == Phase::submit || (cancelRequested_ && !cancelSent_); }
    const std::string& status() const { return status_; }
    const std::optional<PublishedStep>& step() const { return step_; }

private:
    enum class Phase { idle, seal, sealStatus, submit, monitor };
    enum class Request { none, seal, status, submit, cancel };
    void receive(const nlohmann::json& reply, Request request, PrototypeCad& cad);
    void receiveStatus(const nlohmann::json& result, PrototypeCad& cad);
    void completed(const nlohmann::json& result, PrototypeCad& cad);
    void finish(std::string status);

    Phase phase_ = Phase::idle;
    Request pending_ = Request::none;
    Output output_ = Output::geometry;
    Studio::JobTracker job_;
    nlohmann::json snapshot_;
    std::string project_;
    std::string revision_;
    std::string status_;
    std::string observedState_;
    bool observedWorker_ = false;
    bool cancelRequested_ = false;
    bool cancelSent_ = false;
    std::optional<PublishedStep> step_;
};
