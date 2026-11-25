#include "prototype_project.h"

#include "../wxwidgets/editor_sync.h"

#include <array>
#include <cstdio>
#include <stdexcept>
#include <utility>

namespace
{
using Json = nlohmann::json;
using Clock = std::chrono::steady_clock;

std::string errorMessage(const Json& error)
{
    const auto data = error.value("data", Json::object());
    const auto code = data.value("domain_code", "");
    const auto message = error.value("message", "서비스 요청을 완료하지 못했습니다.");
    return code.empty() ? message : code + ": " + message;
}
}

PrototypeProject::PrototypeProject(const char* path) : path_(path ? path : "")
{
    if (configured())
    {
        reopen();
    }
}

bool PrototypeProject::busy() const
{
    return step_ != Step::idle && step_ != Step::finished && step_ != Step::failed;
}

void PrototypeProject::reopen()
{
    if (configured() && !busy())
    {
        step_ = Step::open;
        message_ = "프로젝트를 여는 중";
    }
}

void PrototypeProject::save()
{
    if (view_ && writable() && view_->revision != view_->savedRevision)
    {
        step_ = Step::save;
        message_ = "현재 개정을 저장하는 중";
    }
}

/** @brief 표시 전용 또는 이동이 차단된 객체에는 편집 명령을 만들지 않는다. */
bool PrototypeProject::canTranslate() const
{
    if (!view_ || !writable())
    {
        return false;
    }
    const auto* shape = view_->canvas.Find(view_->selection);
    return shape && shape->selectionKind == "geometry" && shape->movable;
}

void PrototypeProject::translate(double dx, double dy)
{
    if (canTranslate())
    {
        movedId_ = view_->selection;
        dx_ = dx;
        dy_ = dy;
        step_ = Step::translate;
        message_ = "도체를 이동하는 중";
    }
}

void PrototypeProject::undo()
{
    if (view_ && writable() && view_->canUndo)
    {
        step_ = Step::undo;
        message_ = "변경을 되돌리는 중";
    }
}

/** @brief 프레임마다 응답과 작업을 진행하며 UI 스레드에서 외부 프로세스를 기다리지 않는다. */
void PrototypeProject::update(PrototypeService& service)
{
    if (!configured())
    {
        return;
    }
    if (service.state() == PrototypeService::State::failed && busy())
    {
        fail(service.status());
        return;
    }
    if (service.state() != PrototypeService::State::connected || !busy())
    {
        return;
    }
    try
    {
        if (awaiting_)
        {
            const auto reply = service.takeReply();
            if (reply.is_null())
            {
                return;
            }
            awaiting_ = false;
            receive(reply);
        }

        switch (step_)
        {
            case Step::open:
                saving_ = false;
                loading_ = {};
                pages_ = nullptr;
                offset_ = 0;
                awaiting_ = service.request("project.open", Json::object(),
                    {{"path", path_}, {"open_mode", "open"}, {"result_mode", "summary"}}, true);
                step_ = Step::accepted;
                break;
            case Step::save:
                saving_ = true;
                awaiting_ = service.request("project.save", {{"project_id", view_->id}},
                    {{"expected_revision", view_->revision}}, true);
                step_ = Step::accepted;
                break;
            case Step::translate:
            case Step::undo:
            {
                const bool move = step_ == Step::translate;
                const auto id = PrototypeService::newCommandId();
                if (id.empty())
                {
                    fail("편집 명령 ID를 만들지 못했습니다.");
                    return;
                }
                Json input{{"expected_revision", view_->revision}, {"command_id", id}};
                if (move)
                {
                    input["operation"] = "translate";
                    input["values"] = {{"id", movedId_}, {"dx_mm", dx_}, {"dy_mm", dy_}};
                }
                awaiting_ = service.request(move ? "canvas.apply" : "project.undo",
                    {{"project_id", view_->id}}, input, true);
                step_ = Step::edited;
                break;
            }
            case Step::job:
                if (Clock::now() >= jobDeadline_)
                {
                    fail("작업 완료를 확인하지 못했습니다. 같은 프로젝트를 다시 열어 저장 상태를 확인하세요.");
                    return;
                }
                if (Clock::now() < nextPoll_)
                {
                    return;
                }
                awaiting_ = service.request("job.status", Json::object(), {{"job_id", job_}});
                break;
            case Step::canvas:
                awaiting_ = service.request("canvas.page", {{"project_id", loading_.id}},
                    {{"expected_revision", loading_.revision}, {"offset", offset_}});
                break;
            case Step::editor:
                awaiting_ = service.request("editor.page", {{"project_id", loading_.id}},
                    {{"expected_revision", loading_.revision}, {"offset", 0}, {"include_items", false},
                     {"selection", {{"kind", "project"}, {"id", loading_.id}}}});
                break;
            default:
                return;
        }
        if (!awaiting_)
        {
            fail("프로젝트 요청을 보내지 못했습니다.");
        }
    }
    catch (const std::exception& error)
    {
        fail(error.what());
    }
}

void PrototypeProject::receive(const Json& reply)
{
    if (reply.contains("error"))
    {
        fail(errorMessage(reply.at("error")));
        return;
    }
    const auto& result = reply.at("result");
    switch (step_)
    {
        case Step::accepted:
            job_ = result.at("job_id").get<std::string>();
            jobDeadline_ = Clock::now() + std::chrono::seconds(30);
            nextPoll_ = Clock::now();
            step_ = Step::job;
            break;
        case Step::job:
            receiveJob(result);
            break;
        case Step::canvas:
            receiveCanvas(result);
            break;
        case Step::editor:
            finishView(result);
            break;
        case Step::edited:
            if (result.at("project_id") != view_->id || result.at("new_revision") == view_->revision)
            {
                throw std::runtime_error("편집 응답의 프로젝트 또는 개정이 올바르지 않습니다.");
            }
            loading_ = {};
            loading_.id = view_->id;
            loading_.revision = result.at("new_revision").get<std::string>();
            offset_ = 0;
            pages_ = nullptr;
            step_ = Step::canvas;
            break;
        default:
            throw std::runtime_error("프로젝트 응답 순서가 올바르지 않습니다.");
    }
}

void PrototypeProject::receiveJob(const Json& result)
{
    if (result.at("job_id") != job_)
    {
        throw std::runtime_error("프로젝트 작업 ID가 일치하지 않습니다.");
    }
    const auto state = result.at("state").get<std::string>();
    const auto& events = result.at("events");
    if (!events.is_array())
    {
        throw std::runtime_error("프로젝트 작업 이벤트를 읽을 수 없습니다.");
    }
    if (state == "failed" || state == "cancelled" || state == "interrupted" || state == "timeout")
    {
        const auto errors = events.empty() ? Json::array() : events.back().value("diagnostics", Json::array());
        const auto message = errors.empty() ? state : errors.front().value("message_ko", state);
        fail("프로젝트 작업 종료: " + message);
        return;
    }
    if (state != "completed")
    {
        nextPoll_ = Clock::now() + std::chrono::milliseconds(50);
        return;
    }
    if (events.empty())
    {
        throw std::runtime_error("완료된 프로젝트 작업에 결과가 없습니다.");
    }
    const auto& complete = events.back().at("operation_result");
    if (saving_)
    {
        if (complete.at("saved_revision") != view_->revision)
        {
            throw std::runtime_error("저장한 개정이 요청 개정과 다릅니다.");
        }
        view_->savedRevision = view_->revision;
        message_ = "저장 완료";
        std::printf("project saved: %s\n", view_->savedRevision.c_str());
        step_ = Step::finished;
        return;
    }
    loading_.id = complete.at("project_id").get<std::string>();
    loading_.revision = complete.at("revision_id").get<std::string>();
    loading_.savedRevision = complete.at("saved_revision").get<std::string>();
    step_ = Step::canvas;
}

/** @brief 기존 편집 표시의 페이지 제약과 개정 소유권을 확인하고 전체 장면을 한 번에 교체한다. */
void PrototypeProject::receiveCanvas(const Json& result)
{
    constexpr std::size_t maxRows = 64000;
    constexpr std::size_t maxPage = 512;
    constexpr std::array rows{"shapes", "omissions", "pcb_features"};
    const auto& page = result.at("page");
    const auto total = page.at("total").get<std::size_t>();
    if (!Studio::MatchesCanvas(result, loading_.id, loading_.revision) ||
        page.at("profile") != Studio::EditViewPagesProfile || page.at("offset") != offset_ ||
        offset_ > total || total > maxRows || (offset_ && pages_.at("page").at("total") != total))
    {
        throw std::runtime_error("기판 표시 페이지의 개정 또는 범위가 올바르지 않습니다.");
    }
    if (!offset_)
    {
        pages_ = result;
    }
    std::size_t count = 0;
    for (const auto* name : rows)
    {
        if (!result.contains(name) && !pages_.contains(name) && std::string_view(name) == "pcb_features")
        {
            continue;
        }
        const auto& entries = result.at(name);
        if (!entries.is_array())
        {
            throw std::runtime_error("기판 표시 목록을 읽을 수 없습니다.");
        }
        count += entries.size();
        if (offset_)
        {
            auto& destination = pages_.at(name);
            destination.insert(destination.end(), entries.begin(), entries.end());
        }
    }
    const auto& next = page.at("next");
    if (count > maxPage || count > total - offset_ ||
        (next.is_null() ? offset_ + count != total : !count || next != offset_ + count || offset_ + count >= total))
    {
        throw std::runtime_error("기판 표시 페이지의 다음 위치가 올바르지 않습니다.");
    }
    if (!next.is_null())
    {
        offset_ += count;
        return;
    }

    loading_.canvas = CanvasScene::Model::Parse(pages_);
    if (view_ && view_->id == loading_.id && loading_.canvas.Find(view_->selection))
    {
        loading_.selection = view_->selection;
    }
    pages_ = nullptr;
    step_ = Step::editor;
}

void PrototypeProject::finishView(const Json& editor)
{
    if (!Studio::MatchesEditor(editor, loading_.id, loading_.revision))
    {
        throw std::runtime_error("저장 개정 또는 편집 이력이 현재 프로젝트와 다릅니다.");
    }
    const auto saved = editor.at("saved_revision").get<std::string>();
    if (!loading_.savedRevision.empty() && saved != loading_.savedRevision)
    {
        throw std::runtime_error("열기 결과와 편집 화면의 저장 개정이 다릅니다.");
    }
    loading_.savedRevision = saved;
    loading_.canUndo = editor.at("history").at("can_undo").get<bool>();
    std::printf("project opened: %s current=%s saved=%s shapes=%zu\n", loading_.id.c_str(),
        loading_.revision.c_str(), loading_.savedRevision.c_str(), loading_.canvas.shapes.size());
    view_ = std::move(loading_);
    message_.clear();
    step_ = Step::finished;
}

void PrototypeProject::fail(std::string message)
{
    message_ = std::move(message);
    std::fprintf(stderr, "%s\n", message_.c_str());
    pages_ = nullptr;
    awaiting_ = false;
    step_ = Step::failed;
}
