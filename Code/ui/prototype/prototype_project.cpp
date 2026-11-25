#include "prototype_project.h"

#include "../wxwidgets/editor_sync.h"

#include <algorithm>
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

PrototypeProject::PrototypeProject(const char* path, const char* workspace, std::string createName)
    : cad_(workspace), result_(workspace), path_(path ? path : ""), createName_(std::move(createName))
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

bool PrototypeProject::canSwitch() const
{
    return !busy() && !cadJob_.active() && !cad_.loading() && !analysis_.active() && !exchange_.active() &&
        (!view_ || view_->revision == view_->savedRevision);
}

void PrototypeProject::reopen()
{
    if (canReopen())
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

void PrototypeProject::readCad()
{
    if (view_ && writable() && !cad_.loading() && !cadJob_.active())
    {
        step_ = Step::cad;
        cad_.setStatus("게시된 3D 형상을 조회하는 중");
    }
}

bool PrototypeProject::canStartCad() const
{
    return cadReady_ && view_ && writable() && !cad_.loading() && !cadJob_.active();
}

void PrototypeProject::startCad(PrototypeCadJob::Output output)
{
    if (canStartCad())
    {
        cadJob_.start(view_->id, view_->revision, output);
    }
}

/** @brief 현재 개정의 정상 저장본과 영속 편집 상태를 기존 읽기 명령으로 비교한다. */
void PrototypeProject::readRecovery()
{
    if (view_ && writable())
    {
        step_ = Step::recovery;
        recoveryStatus_ = "저장본과 현재 개정을 비교하는 중";
    }
}

void PrototypeProject::clearRecovery()
{
    if (recovery_.is_object())
    {
        recovery_ = nullptr;
        recoveryStatus_ = "개정이 변경됐습니다. 저장본 비교를 다시 읽으세요.";
    }
}

void PrototypeProject::readResult()
{
    if (view_ && writable())
    {
        step_ = Step::solverLatest;
        result_.setStatus("완료된 해석 결과를 조회하는 중");
    }
}

/** @brief 화면에서 확인한 결과의 출처와 pin만 내보내기 요청에 사용한다. */
void PrototypeProject::prepareRfExport(const std::string& format)
{
    const auto& series = result_.series();
    if (view_ && writable() && series &&
        std::ranges::find(series->exportFormats, format) != series->exportFormats.end())
    {
        rfExportInput_ = {{"source", series->source}, {"pin", series->pin}, {"format", format}};
        rfExportRevision_ = series->revision;
        rfExportStatus_ = "선택한 RF 원본과 조건 데이터를 읽는 중";
        step_ = Step::resultExport;
    }
}

nlohmann::json PrototypeProject::takeRfExport()
{
    return std::exchange(rfExportResult_, {});
}

bool PrototypeProject::canReadExchange() const
{
    return exchangeSupported_ && view_ && writable() && !exchange_.active();
}

bool PrototypeProject::canReviewExchange() const
{
    return canReadExchange() || (view_ && writable() && exchange_.choosingFootprint());
}

bool PrototypeProject::canApproveExchange() const
{
    return exchangeReady_ && view_ && writable() && exchange_.canApprove(view_->revision);
}

bool PrototypeProject::canVerifyExchange() const
{
    return exchangeReady_ && canReadExchange() && exchange_.published();
}

void PrototypeProject::reviewExchange()
{
    if (canReviewExchange())
    {
        exchange_.startReview(view_->id, view_->revision);
    }
}

void PrototypeProject::approveExchange()
{
    if (canApproveExchange())
    {
        exchange_.approve(view_->revision);
    }
}

void PrototypeProject::verifyExchange()
{
    if (canVerifyExchange())
    {
        exchange_.startVerify(view_->id);
    }
}

void PrototypeProject::reloadExchange()
{
    if (canReadExchange())
    {
        exchange_.reload(view_->id);
    }
}

void PrototypeProject::moveExchangeFormat(int direction)
{
    if (writable())
    {
        exchange_.moveFormat(direction);
    }
}

void PrototypeProject::moveExchangeFootprint(int direction)
{
    if (writable())
    {
        exchange_.moveFootprint(direction);
    }
}

void PrototypeProject::readResultHistory()
{
    if (view_ && writable())
    {
        result_.requestHistory(0);
        step_ = Step::resultHistory;
    }
}

void PrototypeProject::browseResultHistory(int direction)
{
    if (view_ && writable() && result_.browseHistory(direction))
    {
        step_ = Step::resultHistory;
    }
}

void PrototypeProject::openHistoryResult()
{
    const auto* selected = result_.historyChoice();
    if (view_ && writable() && selected)
    {
        if (selected->available)
        {
            result_.selectArtifact(selected->artifact, selected->revision);
            step_ = Step::resultDescribe;
        }
        else
        {
            result_.selectMatrix(selected->artifact, selected->revision, {}, {}, selected->label);
            step_ = Step::resultArtifact;
        }
        result_.setStatus("선택한 해석의 봉인 표본을 조회하는 중");
    }
}

bool PrototypeProject::canReadSolverConditions() const
{
    return solverReady_ && view_ && writable() && !analysis_.active();
}

bool PrototypeProject::canReviewSolver() const
{
    return canReadSolverConditions() && analysis_.canReview(view_->revision);
}

bool PrototypeProject::canApproveSolver() const
{
    return solverReady_ && view_ && writable() && analysis_.canApprove(view_->revision);
}

void PrototypeProject::readSolverConditions()
{
    if (canReadSolverConditions())
    {
        step_ = Step::solverConditions;
        analysis_.setStatus("저장된 해석 조건을 읽는 중");
    }
}

void PrototypeProject::moveSolverCondition(int direction)
{
    if (writable())
    {
        analysis_.moveChoice(direction);
    }
}

void PrototypeProject::reviewSolver()
{
    if (canReviewSolver())
    {
        analysis_.review(view_->id, view_->revision);
    }
}

void PrototypeProject::approveSolver()
{
    if (canApproveSolver())
    {
        analysis_.approve(view_->revision);
    }
}

bool PrototypeProject::sendBackground(PrototypeService& service)
{
    return analysis_.send(service) || cadJob_.send(service) || exchange_.send(service);
}

/** @brief 프레임마다 응답과 작업을 진행하며 UI 스레드에서 외부 프로세스를 기다리지 않는다. */
void PrototypeProject::update(PrototypeService& service)
{
    cad_.poll();
    if (!configured())
    {
        return;
    }
    cadReady_ = service.cadReady();
    solverReady_ = service.solverReady();
    exchangeSupported_ = service.exchangeSupported();
    exchangeReady_ = service.exchangeReady();
    if (service.state() == PrototypeService::State::failed)
    {
        cadJob_.disconnected();
        analysis_.disconnected();
        exchange_.disconnected();
        if (busy())
        {
            fail(service.status());
        }
        return;
    }
    if (service.state() != PrototypeService::State::connected ||
        !cadJob_.readReply(service, cad_) || !analysis_.readReply(service) || !exchange_.readReply(service))
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

        if (view_)
        {
            analysis_.checkRevision(view_->revision);
            exchange_.checkRevision(view_->revision);
        }
        // @brief 입력 봉인과 사용자 취소를 먼저 보내고 전경 편집은 이전 응답 뒤 이어간다.
        if ((exchange_.urgent() && exchange_.send(service)) ||
            (analysis_.urgent() && analysis_.send(service)) || (cadJob_.urgent() && cadJob_.send(service)))
        {
            return;
        }
        if (!busy())
        {
            const auto publication = analysis_.takeResult();
            if (view_ && publication)
            {
                if (publication->multiport)
                {
                    result_.selectMatrix(publication->artifact, {}, publication->snapshot, publication->reference);
                    step_ = Step::resultArtifact;
                }
                else
                {
                    result_.selectArtifact(publication->artifact);
                    step_ = Step::resultDescribe;
                }
                result_.setStatus("완료한 해석의 봉인 표본을 조회하는 중");
                showingCompletedAnalysis_ = true;
            }
            else
            {
                sendBackground(service);
                return;
            }
        }

        switch (step_)
        {
            case Step::open:
            {
                saving_ = false;
                loading_ = {};
                pages_ = nullptr;
                offset_ = 0;
                Json input{{"path", path_}, {"open_mode", createName_.empty() ? "open" : "create"},
                    {"result_mode", "summary"}};
                if (!createName_.empty())
                {
                    input["name"] = createName_;
                }
                awaiting_ = service.request("project.open", Json::object(), input, true);
                step_ = Step::accepted;
                break;
            }
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
                    sendBackground(service);
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
            case Step::cad:
                awaiting_ = service.request("cad.latest", {{"project_id", view_->id}}, Json::object());
                break;
            case Step::recovery:
                awaiting_ = service.request("project.evidence", {{"project_id", view_->id}},
                    {{"expected_revision", view_->revision}});
                break;
            case Step::solverConditions:
                awaiting_ = service.request("solver.conditions", {{"project_id", view_->id}},
                    {{"expected_revision", view_->revision}});
                break;
            case Step::solverLatest:
                awaiting_ = service.request("solver.latest", {{"project_id", view_->id}}, Json::object());
                break;
            case Step::resultHistory:
                awaiting_ = service.request("result.sources", {{"project_id", view_->id}}, result_.historyInput());
                break;
            case Step::resultDescribe:
                awaiting_ = service.request("result.describe", {{"project_id", view_->id}}, result_.descriptionInput());
                break;
            case Step::resultPage:
                awaiting_ = service.request("result.page", {{"project_id", view_->id}}, result_.pageInput());
                break;
            case Step::resultArtifact:
                awaiting_ = service.request("result.open", {{"project_id", view_->id}}, result_.artifactInput());
                break;
            case Step::resultMatrixLoad:
                if (result_.pollMatrix())
                {
                    finishResult("해석 완료. 봉인된 다중 포트 S 행렬을 읽었습니다.");
                }
                sendBackground(service);
                return;
            case Step::resultExport:
                awaiting_ = service.request("result.export", {{"project_id", view_->id}}, rfExportInput_);
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
        case Step::cad:
            cad_.accept(result, view_->id);
            step_ = Step::finished;
            break;
        case Step::recovery:
        {
            const auto& details = result.at("recovery_details");
            const auto& rows = details.at("rows");
            if (result.at("project_id") != view_->id || result.at("revision_id") != view_->revision ||
                result.at("saved_revision") != view_->savedRevision || !rows.is_array() || rows.size() > 96 ||
                !details.at("has_more").is_boolean() ||
                std::ranges::any_of(rows, [](const Json& row)
                {
                    return !row.is_array() || row.size() != 5 || std::ranges::any_of(row, [](const Json& value)
                    {
                        return !value.is_string();
                    });
                }))
            {
                throw std::runtime_error("저장본 비교의 프로젝트, 개정 또는 변경 목록이 다릅니다.");
            }
            recovery_ = {{"revision_id", result.at("revision_id")}, {"saved_revision", result.at("saved_revision")},
                {"recovery_details", details}};
            recoveryStatus_.clear();
            step_ = Step::finished;
            break;
        }
        case Step::solverConditions:
            analysis_.acceptConditions(result, view_->revision);
            step_ = Step::finished;
            break;
        case Step::solverLatest:
            switch (result_.acceptLatest(result))
            {
                case PrototypeResult::Read::none: step_ = Step::finished; break;
                case PrototypeResult::Read::trace: step_ = Step::resultDescribe; break;
                case PrototypeResult::Read::matrix: step_ = Step::resultArtifact; break;
            }
            break;
        case Step::resultHistory:
            result_.acceptHistory(result, view_->id);
            step_ = Step::finished;
            break;
        case Step::resultDescribe:
            result_.acceptDescription(result, view_->id, view_->revision);
            step_ = Step::resultPage;
            break;
        case Step::resultPage:
            if (result_.acceptPage(result))
            {
                finishResult("해석 완료. 봉인된 S11 결과를 읽었습니다.");
            }
            break;
        case Step::resultArtifact:
            result_.startMatrix(result, view_->id);
            step_ = Step::resultMatrixLoad;
            break;
        case Step::resultExport:
        {
            const auto& conditions = result.at("sidecar");
            if (result.at("source") != rfExportInput_.at("source") || result.at("pin") != rfExportInput_.at("pin") ||
                conditions.at("source") != result.at("source") || conditions.at("pin") != result.at("pin") ||
                conditions.at("source_revision").at("id") != rfExportRevision_ ||
                conditions.at("source_unmodified") != true)
            {
                throw std::runtime_error("내보내기 응답의 출처, 고정 해시 또는 개정이 선택한 결과와 다릅니다.");
            }
            rfExportResult_ = result;
            rfExportStatus_.clear();
            step_ = Step::finished;
            break;
        }
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
        const auto diagnostic = events.empty() ? Json::object() : events.back().value("error", Json::object());
        const auto code = diagnostic.value("code", "");
        const auto message = diagnostic.value("message_ko", state);
        fail("프로젝트 작업 종료: " + (code.empty() ? message : code + " " + message));
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
        clearRecovery();
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
    clearRecovery();
    createName_.clear();
    message_.clear();
    step_ = Step::finished;
}

void PrototypeProject::finishResult(const char* status)
{
    if (showingCompletedAnalysis_)
    {
        analysis_.setStatus(status);
        showingCompletedAnalysis_ = false;
    }
    step_ = Step::finished;
}

void PrototypeProject::fail(std::string message)
{
    if (step_ == Step::cad)
    {
        const auto failure = "3D 형상 조회 실패: " + message;
        std::fprintf(stderr, "%s\n", failure.c_str());
        cad_.setStatus(failure);
        awaiting_ = false;
        step_ = Step::finished;
        return;
    }
    if (step_ == Step::recovery)
    {
        recoveryStatus_ = "저장본 비교 실패. " + message;
        awaiting_ = false;
        step_ = Step::finished;
        return;
    }
    if (step_ == Step::solverConditions)
    {
        analysis_.setStatus("해석 조건 조회 실패. " + message);
        awaiting_ = false;
        step_ = Step::finished;
        return;
    }
    if (step_ == Step::resultExport)
    {
        rfExportStatus_ = "RF 내보내기 요청 실패. " + message;
        awaiting_ = false;
        step_ = Step::finished;
        return;
    }
    if (step_ == Step::resultHistory)
    {
        result_.setHistoryStatus("해석 목록 조회 실패. " + message);
        awaiting_ = false;
        step_ = Step::finished;
        return;
    }
    if (step_ == Step::solverLatest || step_ == Step::resultDescribe || step_ == Step::resultPage ||
        step_ == Step::resultArtifact || step_ == Step::resultMatrixLoad)
    {
        if (showingCompletedAnalysis_)
        {
            analysis_.setStatus("해석을 완료했습니다. 결과 조회 상태를 확인하세요.");
            showingCompletedAnalysis_ = false;
        }
        const auto failure = "해석 결과 조회 실패: " + message;
        std::fprintf(stderr, "%s\n", failure.c_str());
        result_.setStatus(failure);
        awaiting_ = false;
        step_ = Step::finished;
        return;
    }
    message_ = std::move(message);
    std::fprintf(stderr, "%s\n", message_.c_str());
    pages_ = nullptr;
    awaiting_ = false;
    step_ = Step::failed;
}
