#pragma once

#include <imgui.h>

#include <cstddef>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace accessibility
{
constexpr std::size_t noteCapacity = 256;
constexpr std::size_t projectNameCapacity = 1025;

enum class Control
{
    root, menuBar, windowMenu, showBoard, showResult, focusNote, detachResult, detachNote, resetLayout,
    board, resetBoard, result, input, note, clearNote, reloadProject, saveProject, undoProject, moveLeft, moveRight, moveDown, moveUp, toggleModel, reloadModel, reloadResult,
    buildModel, exportStep, cancelCad,
    showSolver, readSolverConditions, priorSolverCondition, nextSolverCondition, reviewSolver, approveSolver, cancelSolver,
    solverCondition, solverStatus, solverPlan,
    showResultHistory, reloadResultHistory, priorResult, nextResult, openHistoryResult,
    historyChoice, historyStatus, resultReadStatus, resultSummary,
    showExchange, priorExchange, nextExchange, priorFootprint, nextFootprint, reviewFootprint, reviewExchange, buildExchange, verifyExchange, cancelExchange, reloadExchange,
    exchangeFormat, exchangeFootprint, exchangeStatus, exchangeReview, exchangePublication,
    showRfExport, previousRfExport, nextRfExport, saveRfExport, rfExportFormat, rfExportStatus,
    matrixPriorRow, matrixNextRow, matrixPriorColumn, matrixNextColumn, matrixPriorSample, matrixNextSample,
    matrixTable, matrixAxes, matrixSample, manufacturingFormat, buildManufacturing, manufacturingChoice, manufacturingStatus,
    showProjectChooser, createProjectMode, projectName, submitProject, projectChooserStatus,
    showRecovery, readRecovery, priorRecoveryField, nextRecoveryField, recoverySummary, recoveryField,
    recoveryBefore, recoveryAfter, recentPrevious, recentNext, recentOpen, recentPath,
    archiveToggle, archivePick, archiveApply, archiveCancel, archiveOpen, archiveReview, archiveStatus,
    endpointToggle, endpointStart, endpointEnd, endpointSnap, endpointPick, endpointX, endpointY,
    endpointApply, endpointReset, endpointSnapStatus, sectionToggle, sectionAxis, sectionSide, sectionPosition,
    sectionApply, sectionAxisValue, sectionStatus,
    renameToggle, renameDialog, renameTarget, renameName, renameApply, renameCancel, renameStatus,
    renameDetails, renameId, renameCopy,
    evidenceToggle, evidenceReload, evidenceRecords, evidenceAssumptions, evidenceHistory,
    evidencePrevious, evidenceNext, evidencePreviousValue, evidenceNextValue,
    evidenceStatus, evidenceSummary, evidenceTitle, evidenceSource, evidenceValues,
    targetToggle, targetNew, targetBand, targetCriteria, targetSources, targetApply, targetApplyRemoval, targetRemove, targetDiscard,
    targetRead, targetPrevChange, targetNextChange, targetName, targetStart, targetEnd, targetSamples,
    targetS11, targetReason, targetStatus, targetSummary, targetHistory
};

enum class Operation { focus, invoke, toggle, expand, collapse, setValue };

struct Action
{
    Control control;
    Operation operation;
    std::string value;
};

#if defined(_WIN32)
/** @brief SDL 창마다 ImGui 요소의 Windows UI Automation 트리를 게시한다. */
class Bridge
{
public:
    Bridge();
    ~Bridge();
    Bridge(const Bridge&) = delete;
    Bridge& operator=(const Bridge&) = delete;

    void item(Control control, Control parent, bool enabled = true, bool checked = false,
        const ImGuiViewport* viewport = nullptr, std::string_view value = {});
    void panel(Control control);
    void text(Control control, Control parent, std::string_view name);
    void publish(const char* value);
    std::vector<Action> takeActions();

private:
    struct State;
    std::unique_ptr<State> state;
};
#else
class Bridge
{
public:
    void item(Control, Control, bool = true, bool = false, const ImGuiViewport* = nullptr, std::string_view = {}) {}
    void panel(Control) {}
    void text(Control, Control, std::string_view) {}
    void publish(const char*) {}
    std::vector<Action> takeActions() { return {}; }
};
#endif
}
