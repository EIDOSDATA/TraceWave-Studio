/** @file @brief 위젯 없이 취소/지연 응답/재진입과 해석 입력 고정을 검증한다. */
#include "../ui/wxwidgets/async_state.h"
#include "../ui/wxwidgets/analysis_workflow.h"
#include <cstdlib>
#include <iostream>
#include <vector>

/** @brief Release 빌드에서도 실패를 종료 코드로 보고한다. */
void Check(bool condition)
{
    if (!condition)
    {
        std::cerr << "GUI state contract failed.\n";
        std::exit(1);
    }
}

/** @brief 거부된 동작은 예외 없이 정상 성공으로 처리되지 않아야 한다. */
template <class Action> void Reject(Action action)
{
    try
    {
        action();
    }
    catch (const std::exception&)
    {
        return;
    }
    Check(false);
}

/** @brief 서비스 없이 순서 역전과 중단 경계의 불변 조건을 검사한다. */
int main()
{
    using namespace Studio;
    const auto now = Clock::time_point(std::chrono::seconds(100));
    JobTracker jobs;
    jobs.Assign("old");
    Check(jobs.BeginPoll(now, std::chrono::milliseconds(100)));
    Check(!jobs.BeginPoll(now + std::chrono::seconds(1), std::chrono::milliseconds(100)));
    jobs.Assign("new");
    Check(jobs.BeginPoll(now, std::chrono::milliseconds(100)));
    Check(!jobs.EndPoll("old"));
    Check(!jobs.BeginPoll(now + std::chrono::seconds(1), std::chrono::milliseconds(100)));
    Check(jobs.EndPoll("new"));
    Check(!jobs.BeginPoll(now + std::chrono::milliseconds(50), std::chrono::milliseconds(100)));
    jobs.AbandonPoll();
    Check(jobs.Id() == "new");
    jobs.Reset();
    Check(!jobs.BeginPoll(now, std::chrono::milliseconds(100)));
    Reject(
        [&jobs]()
        {
            jobs.Assign("");
        });

    RequestDispatcher requests;
    int sequence = 0;
    int called = 0;
    std::vector<Json> sent;
    auto identifiers = [&sequence]()
    {
        return std::to_string(++sequence);
    };
    auto transport = [&sent](const std::string& frame)
    {
        sent.push_back(Json::parse(frame));
        return true;
    };
    auto callback = [&called](const Json&)
    {
        ++called;
    };
    for (int index = 0; index < 16; ++index)
    {
        Check(requests.Submit("project.save", Json::object(), true, Json::object(), "epoch", true, callback, {},
                              identifiers, transport, now) == RequestDispatcher::SubmitResult::Queued);
    }
    Check(sent[0].at("params").at("request_key_epoch") == "epoch");
    Check(sent[0].at("id") != sent[0].at("params").at("request_key"));
    Check(requests.Submit("read", Json::object(), false, Json::object(), "", false, callback, {}, identifiers,
                          transport, now) == RequestDispatcher::SubmitResult::Full);
    Check(sent.size() == 16);
    auto response = Json{{"jsonrpc", "2.0"}, {"id", sent[5].at("id")}, {"result", Json::object()}};
    auto delivery = requests.Take(response);
    Check(delivery.has_value() && called == 0 && requests.Size() == 15);
    delivery->success(response.at("result"));
    Check(called == 1 && !requests.Take(response));
    Reject(
        [&requests]()
        {
            requests.Take(Json{{"jsonrpc", "2.0"}, {"id", "1"}, {"result", 0}, {"error", 0}});
        });
    Check(requests.Size() == 15);
    Check(!requests.Expired(now + std::chrono::seconds(30)));
    Check(requests.Expired(now + std::chrono::seconds(31)));
    requests.Clear();
    Check(!requests.Take(Json{{"jsonrpc", "2.0"}, {"id", sent[0].at("id")}, {"result", 0}}));
    Check(requests.Submit(
              "read", Json::object(), false, Json::object(), "", false, callback, {}, identifiers,
              [](const std::string&)
              {
                  return false;
              },
              now) == RequestDispatcher::SubmitResult::TransportClosed);
    Check(requests.Size() == 0);

    AnalysisWorkflow flow;
    Json settings{{"grid_mm", 0.4}};
    Check(flow.Begin("revision-A", settings).method == "snapshot.create");
    settings["grid_mm"] = 99;
    Reject(
        [&flow]()
        {
            flow.Begin("revision-B", Json::object());
        });
    Reject(
        [&flow]()
        {
            flow.Complete(Json::object());
        });
    Check(flow.CurrentPhase() == AnalysisWorkflow::Phase::Snapshot);
    auto command = flow.Complete(Json{{"snapshot_id", "snapshot-A"}, {"content_hash", "hash-A"}});
    Check(command->input.at("settings").at("grid_mm") == 0.4);
    Check(command->input.at("snapshot").at("snapshot_id") == "snapshot-A");
    flow.RequestCancel();
    Check(flow.Active() && flow.CancellationRequested() && !flow.CanRequestCancel());
    flow.AllowCancelRetry();
    Check(flow.CancellationRequested() && flow.CanRequestCancel());
    Reject(
        [&flow]()
        {
            flow.Complete(Json{{"analysis_plan", {{"plan_id", "p"}, {"content_hash", "h"}}}});
        });
    Check(flow.CurrentPhase() == AnalysisWorkflow::Phase::Plan);
    flow.RequestCancel();
    Check(flow.CancellationRequested() && !flow.CanRequestCancel());
    Reject(
        [&flow]()
        {
            flow.Complete(Json{{"analysis_plan", {{"plan_id", "p"}, {"content_hash", "h"}}}});
        });
    Check(flow.CurrentPhase() == AnalysisWorkflow::Phase::Plan);
    flow.Stop();
    Reject(
        [&flow]()
        {
            flow.Complete(Json::object());
        });
    flow.Begin("revision-B", settings);
    Check(!flow.CancellationRequested() && flow.CanRequestCancel());
    flow.Complete(Json{{"snapshot_id", "s"}, {"content_hash", "h"}});
    Check(flow.Complete(Json{{"analysis_plan", {{"plan_id", "p"}, {"content_hash", "h"}}}})->method ==
          "solver.prepare");
    Check(flow.Complete(Json{{"prepared_plan", {{"prepared_plan_id", "q"}, {"content_hash", "h"}}}})->method ==
          "job.submit");
    Check(!flow.Complete(Json{{"artifact_id", "result"}}));
    Check(!flow.Active() && flow.CurrentPhase() == AnalysisWorkflow::Phase::Completed);
    Reject(
        [&flow]()
        {
            flow.Complete(Json{{"artifact_id", "result"}});
        });
    return 0;
}
