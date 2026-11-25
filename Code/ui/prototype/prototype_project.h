#pragma once

#include "../wxwidgets/canvas_precision.h"
#include "prototype_analysis.h"
#include "prototype_cad_job.h"
#include "prototype_exchange.h"
#include "prototype_evidence.h"
#include "prototype_target.h"
#include "prototype_template.h"
#include "prototype_setup.h"
#include "prototype_result.h"
#include "prototype_service.h"

#include <chrono>
#include <optional>
#include <string>

/** @brief 열기와 저장의 권위 개정 및 2D 표시 데이터를 함께 관리한다. */
class PrototypeProject
{
public:
    struct View
    {
        std::string id;
        std::string revision;
        std::string savedRevision;
        CanvasScene::Model canvas;
        std::string selection;
        bool canUndo = false;
    };

    explicit PrototypeProject(const char* path, const char* workspace, std::string createName = {});
    void update(PrototypeService& service);
    void reopen();
    void save();
    void translate(double dx, double dy);
    bool canMoveEndpoint(CanvasPrecision::Endpoint endpoint) const;
    void moveEndpoint(CanvasPrecision::Endpoint endpoint, CanvasScene::Point point);
    void undo();
    void readRename();
    void renameObject(const std::string& name);
    bool canRename() const;
    const std::string& renameStatus() const { return renameStatus_; }
    const std::string* renameName() const;
    void readTarget(const std::string& id, const std::string& preset = {});
    void applyTarget(bool remove);
    void readTargetEvidence();
    PrototypeTarget& target() { return target_; }
    const std::string& targetId() const { return targetId_; }
    const std::string& targetPreset() const { return targetPreset_; }
    const std::string& targetStatus() const { return targetStatus_; }
    const std::optional<PrototypeEvidence>& targetEvidence() const { return targetEvidence_; }
    void readTemplate();
    void previewTemplate();
    void applyTemplate();
    PrototypeTemplate& literature() { return literature_; }
    PrototypeSetup& setup() { return setup_; }
    void readSetup();
    void reviewBoardSetup();
    void applySetup(bool remove = false);
    void checkRules(const char* inclusion);
    void readCatalog(PrototypeSetup::Request request);
    void readCad();
    void readRecovery();
    const nlohmann::json& recovery() const { return recovery_; }
    const std::optional<PrototypeEvidence>& evidence() const { return evidence_; }
    const std::string& recoveryStatus() const { return recoveryStatus_; }
    void startCad(PrototypeCadJob::Output output);
    void cancelCad() { cadJob_.cancel(); }
    bool cadReady() const { return cadReady_; }
    bool canStartCad() const;
    const PrototypeCadJob& cadJob() const { return cadJob_; }
    void readResult();
    void prepareRfExport(const std::string& format);
    nlohmann::json takeRfExport();
    const std::string& rfExportStatus() const { return rfExportStatus_; }
    void reviewExchange();
    void approveExchange();
    void verifyExchange();
    void reloadExchange();
    void moveExchangeFormat(int direction);
    void moveExchangeFootprint(int direction);
    void cancelExchange() { exchange_.cancel(); }
    bool canReadExchange() const;
    bool canReviewExchange() const;
    bool canApproveExchange() const;
    bool canVerifyExchange() const;
    bool exchangeReady() const { return exchangeReady_; }
    const PrototypeExchange& exchange() const { return exchange_; }
    void readResultHistory();
    void browseResultHistory(int direction);
    void openHistoryResult();
    void readSolverConditions();
    void moveSolverCondition(int direction);
    void reviewSolver();
    void approveSolver();
    void cancelSolver() { analysis_.cancel(); }
    bool solverReady() const { return solverReady_; }
    bool canReadSolverConditions() const;
    bool canReviewSolver() const;
    bool canApproveSolver() const;
    const PrototypeAnalysis& analysis() const { return analysis_; }
    const PrototypeCad& cad() const { return cad_; }
    const PrototypeResult& result() const { return result_; }

    bool configured() const { return !path_.empty(); }
    bool busy() const;
    bool canSwitch() const;
    bool canTranslate() const;
    bool writable() const { return step_ == Step::finished && !cadJob_.sealing() && !analysis_.sealing() && !exchange_.sealing(); }
    bool canReopen() const { return configured() && !busy() && !cadJob_.sealing() && !analysis_.sealing() && !exchange_.sealing(); }
    const std::string& path() const { return path_; }
    const std::string& message() const { return message_; }
    View* view() { return view_ ? &*view_ : nullptr; }

private:
    enum class Step
    {
        idle, open, save, canvasEdit, undo, readRename, rename, renamed, edited, accepted, job, canvas, editor, cad,
        solverLatest, resultHistory, resultDescribe, resultPage, resultArtifact, resultMatrixLoad, resultExport,
        solverConditions, recovery, targetRead, targetApply, targetEdited, targetEvidence, templateContext, templatePreview, templateApply, templateEdited,
        setupRequest, finished, failed
    };
    bool sendBackground(PrototypeService& service);
    void receive(const nlohmann::json& reply);
    void receiveJob(const nlohmann::json& result);
    void finishEdit(const nlohmann::json& result);
    void requestSetup(PrototypeSetup::Request request, nlohmann::json input);
    void finishResult(const char* status);
    void clearRecovery();
    void receiveCanvas(const nlohmann::json& result);
    void finishView(const nlohmann::json& editor);
    void fail(std::string message);

    PrototypeCad cad_;
    PrototypeCadJob cadJob_;
    PrototypeAnalysis analysis_;
    PrototypeExchange exchange_;
    bool exchangeSupported_ = false;
    bool exchangeReady_ = false;
    bool cadReady_ = false;
    bool solverReady_ = false;
    bool showingCompletedAnalysis_ = false;
    PrototypeResult result_;
    nlohmann::json recovery_;
    std::optional<PrototypeEvidence> evidence_;
    std::string recoveryStatus_;
    nlohmann::json rfExportInput_;
    nlohmann::json rfExportResult_;
    std::string rfExportRevision_;
    std::string rfExportStatus_;
    std::string path_;
    std::string createName_;
    std::string message_;
    Step step_ = Step::idle;
    bool saving_ = false;
    bool awaiting_ = false;
    std::string job_;
    nlohmann::json canvasEdit_;
    nlohmann::json renameSelection_;
    std::string renameRevision_;
    std::optional<std::string> renameName_;
    std::string renameDraft_;
    std::string renameStatus_;
    PrototypeTarget target_;
    std::string targetId_;
    std::string targetPreset_;
    std::string targetStatus_;
    nlohmann::json targetInput_;
    std::optional<PrototypeEvidence> targetEvidence_;
    PrototypeTemplate literature_;
    nlohmann::json templateInput_;
    PrototypeSetup setup_;
    PrototypeSetup::Request setupRequest_ = PrototypeSetup::Request::board;
    nlohmann::json setupInput_;
    bool setupSent_ = false;
    View loading_;
    std::optional<View> view_;
    nlohmann::json pages_;
    std::size_t offset_ = 0;
    std::chrono::steady_clock::time_point nextPoll_;
    std::chrono::steady_clock::time_point jobDeadline_;
};
