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
    return !busy() && !solverDraft_ && !cadJob_.active() && !cad_.loading() && !analysis_.active() && !exchange_.active() &&
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
        canvasEdit_ = {{"operation", "translate"}, {"values", {{"id", view_->selection}, {"dx_mm", dx}, {"dy_mm", dy}}}};
        step_ = Step::canvasEdit;
        message_ = "도체를 이동하는 중";
    }
}

/** @brief 서비스가 편집을 허용한 같은 개정의 선이나 원호 끝점만 대상으로 삼는다. */
bool PrototypeProject::canMoveEndpoint(CanvasPrecision::Endpoint endpoint) const
{
    if (!view_ || !writable())
    {
        return false;
    }
    const auto* shape = view_->canvas.Find(view_->selection);
    return shape && shape->selectionKind == "geometry" && CanvasPrecision::HasEndpoints(*shape) &&
        CanvasPrecision::Editable(*shape, endpoint);
}

void PrototypeProject::moveEndpoint(CanvasPrecision::Endpoint endpoint, CanvasScene::Point point)
{
    if (canMoveEndpoint(endpoint) && CanvasGeometry::Valid(point))
    {
        const auto* shape = view_->canvas.Find(view_->selection);
        auto preview = *shape;
        if (CanvasPrecision::EndpointUnchanged(*shape, endpoint, point) ||
            !CanvasPrecision::Preview(preview, endpoint, point))
        {
            return;
        }
        canvasEdit_ = {{"operation", "move_endpoint"}, {"values", {{"id", shape->id},
            {"endpoint", endpoint == CanvasPrecision::Endpoint::Start ? "start" : "end"}, {"point", {point.x, point.y}}}}};
        step_ = Step::canvasEdit;
        message_ = "선택한 끝점을 적용하는 중";
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

/** @brief 캔버스 도체 또는 선택이 없는 프로젝트의 이름 편집 정보를 조회한다. */
bool PrototypeProject::canRename() const
{
    if (!view_ || !writable())
    {
        return false;
    }
    const auto* shape = view_->canvas.Find(view_->selection);
    return view_->selection.empty() || (shape && shape->selectionKind == "geometry");
}

void PrototypeProject::readRename()
{
    if (!canRename())
    {
        return;
    }
    const bool project = view_->selection.empty();
    renameSelection_ = {{"kind", project ? "project" : "geometry"},
        {"id", project ? view_->id : view_->selection}};
    renameRevision_ = view_->revision;
    renameName_.reset();
    renameStatus_.clear();
    step_ = Step::readRename;
}

/** @brief 이름은 조회한 개정 및 안정 ID에만 적용한다. */
const std::string* PrototypeProject::renameName() const
{
    if (!view_ || !renameName_ || view_->revision != renameRevision_)
    {
        return nullptr;
    }
    const auto& id = view_->selection.empty() ? view_->id : view_->selection;
    return renameSelection_.at("id") == id ? &*renameName_ : nullptr;
}

void PrototypeProject::renameObject(const std::string& name)
{
    const auto* original = renameName();
    if (canRename() && original && !name.empty() && name != *original)
    {
        renameDraft_ = name;
        renameStatus_.clear();
        message_ = "이름 변경을 적용하는 중";
        step_ = Step::rename;
    }
}

/** @brief 조회와 초안 전환은 같은 프로젝트의 현재 개정에서만 수행한다. */
void PrototypeProject::readTarget(const std::string& id, const std::string& preset)
{
    if (view_ && writable() && !target_.dirty())
    {
        targetInput_ = {{"expected_revision", view_->revision}, {"target_id", id.empty() ? Json(nullptr) : Json(id)}};
        if (!preset.empty())
        {
            targetInput_["preset_id"] = preset;
        }
        targetStatus_ = "목표 입력을 읽는 중";
        step_ = Step::targetRead;
    }
}

/** @brief 활성 필드의 변경값과 명시한 이유만 기존 목표 명령으로 보낸다. */
void PrototypeProject::applyTarget(bool remove)
{
    if (!view_ || !writable() || !target_.loaded || target_.reason.empty() || (remove && targetId_.empty()))
    {
        return;
    }
    auto values = remove ? Json::object() : target_.changes();
    if (!remove && values.empty() && targetPreset_.empty())
    {
        return;
    }
    const auto id = PrototypeService::newCommandId();
    if (id.empty())
    {
        targetStatus_ = "목표 편집 명령 ID를 만들지 못했습니다.";
        return;
    }
    targetInput_ = {{"expected_revision", view_->revision}, {"command_id", id},
        {"operation", remove ? "remove" : "set"}, {"target_id", targetId_.empty() ? Json(nullptr) : Json(targetId_)},
        {"values", std::move(values)}, {"reason", target_.reason}};
    if (!targetPreset_.empty())
    {
        targetInput_["preset_id"] = targetPreset_;
    }
    targetStatus_ = "목표 변경을 적용하는 중";
    step_ = Step::targetApply;
}

void PrototypeProject::readTargetEvidence()
{
    if (view_ && writable() && !targetId_.empty())
    {
        targetStatus_ = "목표의 출처와 이력을 읽는 중";
        step_ = Step::targetEvidence;
    }
}

void PrototypeProject::readTemplate()
{
    if (view_ && writable())
    {
        literature_.status = "현재 개정의 문헌 카드와 적용 대상을 읽는 중";
        step_ = Step::templateContext;
    }
}

/** @brief 미리보기 요청에만 초안을 전달하고 편집 개정은 그대로 둔다. */
void PrototypeProject::previewTemplate()
{
    if (!view_ || !writable() || !literature_.ready())
    {
        return;
    }
    literature_.clearReview();
    try
    {
        templateInput_ = literature_.specification();
        literature_.status = "후보 형상을 검토하는 중";
        step_ = Step::templatePreview;
    }
    catch (const std::exception& error)
    {
        literature_.status = error.what();
    }
}

/** @brief 검토한 입력과 해시로만 한 개의 문헌 적용 명령을 만든다. */
void PrototypeProject::applyTemplate()
{
    if (!view_ || !writable() || !literature_.canApply())
    {
        return;
    }
    try
    {
        templateInput_ = literature_.application(PrototypeService::newCommandId());
        literature_.status = "검토한 형상을 적용하는 중";
        step_ = Step::templateApply;
    }
    catch (const std::exception& error)
    {
        literature_.clearReview();
        literature_.status = error.what();
    }
}

void PrototypeProject::requestSetup(PrototypeSetup::Request request, Json input)
{
    using Request = PrototypeSetup::Request;
    if (request != Request::board && !PrototypeSetup::catalogRequest(request))
    {
        input["expected_revision"] = view_->revision;
    }
    setupRequest_ = request;
    setupInput_ = std::move(input);
    setupSent_ = false;
    setup_.status = PrototypeSetup::mutation(request) ? "검토한 설정을 적용하는 중" : "현재 개정의 설정을 확인하는 중";
    step_ = Step::setupRequest;
}

void PrototypeProject::readSetup()
{
    using Page = PrototypeSetup::Page;
    using Request = PrototypeSetup::Request;
    if (view_ && writable() && !setup_.dirty())
    {
        const auto request = setup_.page == Page::board ? Request::board :
            setup_.page == Page::physical ? Request::physical : Request::rules;
        requestSetup(request, setup_.readInput());
    }
}

void PrototypeProject::reviewBoardSetup()
{
    if (view_ && writable() && setup_.board && setup_.dirty())
    {
        try
        {
            requestSetup(PrototypeSetup::Request::boardPreview, setup_.boardPreview());
        }
        catch (const std::exception& error)
        {
            setup_.status = error.what();
        }
    }
}

void PrototypeProject::applySetup(bool remove)
{
    using Page = PrototypeSetup::Page;
    using Request = PrototypeSetup::Request;
    if (!view_ || !writable())
    {
        return;
    }
    try
    {
        const auto command = PrototypeService::newCommandId();
        if (setup_.page == Page::board && setup_.board && setup_.board->CanApply() && !remove)
        {
            requestSetup(Request::boardApply, setup_.boardApply(command));
        }
        if (setup_.page == Page::physical || setup_.page == Page::rules)
        {
            requestSetup(setup_.page == Page::physical ? Request::physicalApply : Request::rulesApply,
                setup_.formInput(command, remove));
        }
    }
    catch (const std::exception& error)
    {
        setup_.status = error.what();
    }
}

void PrototypeProject::checkRules(const char* inclusion)
{
    if (view_ && writable() && setup_.page == PrototypeSetup::Page::rules && !setup_.dirty())
    {
        setup_.report = nullptr;
        requestSetup(PrototypeSetup::Request::check, setup_.checkInput(inclusion));
    }
}

/** @brief 제조업체 자료는 프로젝트와 독립된 읽기 전용 서비스에서 조회한다. */
void PrototypeProject::readCatalog(PrototypeSetup::Request request)
{
    if (view_ && writable() && setup_.page == PrototypeSetup::Page::board && PrototypeSetup::catalogRequest(request))
    {
        requestSetup(request, setup_.catalogInput(request));
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
        recoveryStatus_ = "출처와 저장본을 조회하는 중";
    }
}

void PrototypeProject::clearRecovery()
{
    if (recovery_.is_object())
    {
        recovery_ = nullptr;
        evidence_.reset();
        recoveryStatus_ = "개정이 변경됐습니다. 출처 또는 저장본 비교를 다시 읽으세요.";
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
    return view_ && writable() && !analysis_.active() && !solverDraft_;
}

bool PrototypeProject::canReviewSolver() const
{
    return solverReady_ && canReadSolverConditions() && analysis_.canReview(view_->revision);
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

bool PrototypeProject::canEditSolverCondition() const
{
    return solverDraft_ && view_ && writable() && !analysis_.active() && solverDraft_->revision == view_->revision;
}

void PrototypeProject::beginSolverCondition()
{
    if (!canReadSolverConditions())
    {
        return;
    }
    try
    {
        const auto* source = analysis_.canReview(view_->revision) ? analysis_.condition() : nullptr;
        solverDraft_.emplace(view_->revision, source);
        solverConditionInput_ = nullptr;
        analysis_.setStatus("");
    }
    catch (const std::exception& error)
    {
        analysis_.setStatus(std::string("조건 초안을 열지 못했습니다. ") + error.what());
    }
}

void PrototypeProject::discardSolverCondition()
{
    if (solverDraft_ && !busy())
    {
        solverDraft_.reset();
        solverConditionInput_ = nullptr;
        analysis_.setStatus("");
    }
}

/** @brief 새로운 이름의 해석 조건을 공개 변경 계약으로 보내며 해석은 실행하지 않는다. */
void PrototypeProject::saveSolverCondition()
{
    if (!canEditSolverCondition() || solverDraft_->name.empty())
    {
        return;
    }
    try
    {
        const auto settings = solverDraft_->settings();
        if (!solverConditionInput_.is_object() || solverConditionInput_.at("name") != solverDraft_->name ||
            solverConditionInput_.at("settings") != settings)
        {
            solverConditionInput_ = {{"expected_revision", view_->revision}, {"command_id", PrototypeService::newCommandId()},
                {"name", solverDraft_->name}, {"settings", settings}};
        }
        step_ = Step::solverConditionSave;
        analysis_.setStatus("현재 개정에 해석 조건을 추가하는 중");
    }
    catch (const std::exception& error)
    {
        analysis_.setStatus(error.what());
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
            case Step::readRename:
                awaiting_ = service.request("editor.page", {{"project_id", view_->id}},
                    {{"expected_revision", renameRevision_}, {"offset", 0}, {"include_items", false},
                     {"selection", renameSelection_}});
                break;
            case Step::canvasEdit:
            case Step::rename:
            case Step::undo:
            {
                const bool canvas = step_ == Step::canvasEdit;
                const bool rename = step_ == Step::rename;
                const auto id = PrototypeService::newCommandId();
                if (id.empty())
                {
                    fail("편집 명령 ID를 만들지 못했습니다.");
                    return;
                }
                Json input{{"expected_revision", view_->revision}, {"command_id", id}};
                const char* method = "project.undo";
                if (canvas)
                {
                    input.update(canvasEdit_);
                    method = "canvas.apply";
                }
                if (rename)
                {
                    input["selection"] = renameSelection_;
                    input["values"] = {{"name", renameDraft_}};
                    method = "editor.apply";
                }
                awaiting_ = service.request(method, {{"project_id", view_->id}}, input, true);
                if (awaiting_)
                {
                    step_ = rename ? Step::renamed : Step::edited;
                }
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
            case Step::setupRequest:
            {
                const auto context = PrototypeSetup::catalogRequest(setupRequest_) ?
                    Json::object() : Json{{"project_id", view_->id}};
                awaiting_ = service.request(PrototypeSetup::method(setupRequest_), context,
                    setupInput_, PrototypeSetup::mutation(setupRequest_));
                setupSent_ = awaiting_;
                break;
            }
            case Step::templateContext:
                awaiting_ = service.request("template.context", {{"project_id", view_->id}},
                    {{"expected_revision", view_->revision}});
                break;
            case Step::templatePreview:
                awaiting_ = service.request("template.synthesize", {{"project_id", view_->id}}, templateInput_);
                break;
            case Step::templateApply:
                awaiting_ = service.request("template.apply", {{"project_id", view_->id}}, templateInput_, true);
                if (awaiting_)
                {
                    step_ = Step::templateEdited;
                }
                break;
            case Step::targetRead:
                awaiting_ = service.request("target.editor.get", {{"project_id", view_->id}}, targetInput_);
                break;
            case Step::targetApply:
                awaiting_ = service.request("target.editor.apply", {{"project_id", view_->id}}, targetInput_, true);
                if (awaiting_)
                {
                    step_ = Step::targetEdited;
                }
                break;
            case Step::targetEvidence:
                awaiting_ = service.request("project.evidence", {{"project_id", view_->id}},
                    {{"expected_revision", view_->revision}, {"target_id", targetId_}});
                break;
            case Step::solverConditions:
                awaiting_ = service.request("solver.conditions", {{"project_id", view_->id}},
                    {{"expected_revision", view_->revision}});
                break;
            case Step::solverConditionSave:
                awaiting_ = service.request("solver.conditions.save", {{"project_id", view_->id}}, solverConditionInput_, true);
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
        const auto& error = reply.at("error");
        const auto data = error.value("data", Json::object());
        const auto code = data.value("domain_code", "");
        if (step_ == Step::renamed && (code == "E_SCHEMA" || code == "E_CONFLICT"))
        {
            renameStatus_ = errorMessage(error);
            message_.clear();
            step_ = Step::finished;
            return;
        }
        if (step_ == Step::setupRequest && (code == "E_SCHEMA" || code == "E_CONFLICT" ||
            code == "E_UNIT" || code == "E_RESOURCE" || code == "E_UNSUPPORTED" || code == "E_DESIGN_CONSTRAINT"))
        {
            setupSent_ = false;
        }
        if (step_ == Step::templateEdited && (code == "E_SCHEMA" || code == "E_CONFLICT" || code == "E_RESOURCE"))
        {
            literature_.clearReview();
            literature_.status = errorMessage(error);
            step_ = Step::finished;
            return;
        }
        if (step_ == Step::targetEdited && (code == "E_SCHEMA" || code == "E_CONFLICT" ||
            code == "E_UNIT" || code == "E_RESOURCE" || code == "E_UNSUPPORTED"))
        {
            targetStatus_ = errorMessage(error);
            if (const auto diagnostics = data.value("diagnostics", Json::array()); !diagnostics.empty())
            {
                const auto field = diagnostics.front().value("details", Json::object()).value("field_path", "");
                if (!field.empty())
                {
                    targetStatus_ += " (" + field + ")";
                }
            }
            step_ = Step::finished;
            return;
        }
        fail(errorMessage(error));
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
            auto evidence = PrototypeEvidence::read(result);
            recovery_ = {{"revision_id", result.at("revision_id")}, {"saved_revision", result.at("saved_revision")},
                {"recovery_details", details}};
            evidence_ = std::move(evidence);
            recoveryStatus_.clear();
            step_ = Step::finished;
            break;
        }
        case Step::setupRequest:
            setup_.accept(setupRequest_, result, setupInput_, view_->id, view_->revision,
                setupRequest_ == PrototypeSetup::Request::board ? PrototypeService::newCommandId() : "");
            if (!PrototypeSetup::mutation(setupRequest_))
            {
                step_ = Step::finished;
                break;
            }
            finishEdit(result);
            break;
        case Step::templateContext:
            literature_.acceptContext(result, view_->id, view_->revision);
            step_ = Step::finished;
            break;
        case Step::templatePreview:
            literature_.acceptPreview(result, view_->id, templateInput_);
            step_ = Step::finished;
            break;
        case Step::targetRead:
        {
            const auto& selection = targetInput_.at("target_id");
            const auto id = selection.is_null() ? std::string{} : selection.get<std::string>();
            const auto preset = targetInput_.value("preset_id", "");
            target_.accept(result, view_->id, view_->revision, view_->savedRevision, id, preset);
            targetId_ = id;
            targetPreset_ = preset;
            targetEvidence_.reset();
            targetStatus_.clear();
            step_ = Step::finished;
            break;
        }
        case Step::targetEvidence:
            if (result.at("project_id") != view_->id || result.at("revision_id") != view_->revision ||
                result.at("saved_revision") != view_->savedRevision)
            {
                throw std::runtime_error("목표 출처 응답의 프로젝트 또는 개정이 다릅니다.");
            }
            targetEvidence_ = PrototypeEvidence::read(result);
            targetStatus_.clear();
            step_ = Step::finished;
            break;
        case Step::solverConditions:
            analysis_.acceptConditions(result, view_->revision);
            if (!newSolverCondition_.empty())
            {
                analysis_.selectCondition(newSolverCondition_);
                newSolverCondition_.clear();
                analysis_.setStatus("해석 조건을 추가했습니다. 프로젝트를 저장하세요.");
            }
            step_ = Step::finished;
            break;
        case Step::solverConditionSave:
            finishEdit(result);
            newSolverCondition_ = solverConditionInput_.at("command_id").get<std::string>();
            solverConditionInput_ = nullptr;
            solverDraft_.reset();
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
        case Step::readRename:
        {
            const auto& selection = result.at("selection");
            if (!Studio::MatchesEditor(result, view_->id, renameRevision_) ||
                selection.at("id") != renameSelection_.at("id") || selection.at("kind") != renameSelection_.at("kind"))
            {
                throw std::runtime_error("이름 조회 응답의 개정 또는 객체가 다릅니다.");
            }
            const auto& fields = selection.at("fields");
            const auto field = std::ranges::find_if(fields, [](const Json& entry)
            {
                return entry.at("key") == "name" && !entry.at("readonly").get<bool>();
            });
            if (field == fields.end())
            {
                throw std::runtime_error("이름을 변경할 수 없는 객체입니다.");
            }
            renameName_ = field->at("value").get<std::string>();
            step_ = Step::finished;
            break;
        }
        case Step::targetEdited:
        {
            const auto id = result.at("target_id").get<std::string>();
            if (id.empty() || (!targetId_.empty() && id != targetId_) ||
                result.at("project_id") != view_->id || result.at("new_revision") == view_->revision)
            {
                throw std::runtime_error("목표 편집 응답의 프로젝트, 개정 또는 목표가 다릅니다.");
            }
            targetId_ = targetInput_.at("operation") == "remove" ? "" : id;
            targetPreset_.clear();
            target_.discard();
            target_.loaded = false;
            targetStatus_.clear();
        }
        [[fallthrough]];
        case Step::templateEdited:
            literature_.acceptApply(result, view_->id, templateInput_);
            [[fallthrough]];
        case Step::renamed:
        case Step::edited:
            finishEdit(result);
            break;
        default:
            throw std::runtime_error("프로젝트 응답 순서가 올바르지 않습니다.");
    }
}

/** @brief 확인된 새 개정으로 장면과 저장 상태를 함께 다시 읽는다. */
void PrototypeProject::finishEdit(const Json& result)
{
    if (result.at("project_id") != view_->id || result.at("new_revision") == view_->revision)
    {
        throw std::runtime_error("편집 응답의 프로젝트 또는 개정이 올바르지 않습니다.");
    }
    loading_ = {};
    loading_.id = view_->id;
    loading_.revision = result.at("new_revision").get<std::string>();
    loading_.selection = view_->selection;
    offset_ = 0;
    pages_ = nullptr;
    step_ = Step::canvas;
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
    if (!loading_.canvas.Find(loading_.selection))
    {
        loading_.selection.clear();
    }
    std::printf("project opened: %s current=%s saved=%s shapes=%zu\n", loading_.id.c_str(),
        loading_.revision.c_str(), loading_.savedRevision.c_str(), loading_.canvas.shapes.size());
    view_ = std::move(loading_);
    clearRecovery();
    target_.loaded = false;
    targetEvidence_.reset();
    literature_.invalidate(view_->revision);
    setup_.invalidate(view_->revision);
    createName_.clear();
    message_.clear();
    step_ = Step::finished;
    if (!newSolverCondition_.empty())
    {
        readSolverConditions();
    }
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
    if (step_ == Step::setupRequest && (!PrototypeSetup::mutation(setupRequest_) || !setupSent_))
    {
        setup_.failed(setupRequest_, "설정 요청 실패. " + message);
        awaiting_ = false;
        step_ = Step::finished;
        return;
    }
    if (step_ == Step::templateContext || step_ == Step::templatePreview || step_ == Step::templateApply)
    {
        literature_.clearReview();
        literature_.status = "문헌 요청 실패. " + message;
        awaiting_ = false;
        step_ = Step::finished;
        return;
    }
    if (step_ == Step::targetRead || step_ == Step::targetApply || step_ == Step::targetEvidence)
    {
        targetStatus_ = "목표 요청 실패. " + message;
        awaiting_ = false;
        step_ = Step::finished;
        return;
    }
    if (step_ == Step::readRename || step_ == Step::rename)
    {
        renameStatus_ = "이름 편집 요청 실패. " + message;
        message_.clear();
        awaiting_ = false;
        step_ = Step::finished;
        return;
    }
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
        recoveryStatus_ = "출처와 저장본 조회 실패. " + message;
        awaiting_ = false;
        step_ = Step::finished;
        return;
    }
    if (step_ == Step::solverConditionSave || step_ == Step::solverConditions)
    {
        const char* prefix = step_ == Step::solverConditionSave ? "해석 조건 추가 실패. " : "해석 조건 조회 실패. ";
        analysis_.setStatus(prefix + message);
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
