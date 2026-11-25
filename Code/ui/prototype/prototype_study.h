/** @file @brief 프로젝트 연구의 편집과 봉인된 진행 조회를 관리한다. */
#pragma once

#include "../wxwidgets/project_study_model.h"

#include <chrono>
#include <string>

class PrototypeStudy
{
public:
    enum class Request { context, list, detail, create, start, cancel, resume };

    static const char* method(Request request);
    static bool mutation(Request request);
    bool request(Request request, const std::string& project, const std::string& revision,
        const std::string& identity = {});
    void accept(const nlohmann::json& result);
    void failed(std::string message);
    bool shouldPoll() const;
    bool canCreate(const std::string& revision) const;
    bool canControl(Request request) const;

    Request pending = Request::context;
    nlohmann::json input;
    nlohmann::json context;
    nlohmann::json rows;
    nlohmann::json detail;
    Studio::StudyFields fields;
    std::string chosen;
    std::string status;
    std::string summary;
    bool radiation = false;
    bool losses = false;

private:
    std::string project_;
    std::string revision_;
    std::chrono::steady_clock::time_point nextPoll_{};
};
