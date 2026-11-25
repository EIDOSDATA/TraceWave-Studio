#pragma once

#include "../wxwidgets/canvas_scene.h"
#include "prototype_cad_job.h"
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

    explicit PrototypeProject(const char* path, const char* workspace);
    void update(PrototypeService& service);
    void reopen();
    void save();
    void translate(double dx, double dy);
    void undo();
    void readCad();
    void startCad(PrototypeCadJob::Output output);
    void cancelCad() { cadJob_.cancel(); }
    bool cadReady() const { return cadReady_; }
    bool canStartCad() const;
    const PrototypeCadJob& cadJob() const { return cadJob_; }
    void readResult();
    const PrototypeCad& cad() const { return cad_; }
    const PrototypeResult& result() const { return result_; }

    bool configured() const { return !path_.empty(); }
    bool busy() const;
    bool canTranslate() const;
    bool writable() const { return step_ == Step::finished && !cadJob_.sealing(); }
    bool canReopen() const { return configured() && !busy() && !cadJob_.sealing(); }
    const std::string& path() const { return path_; }
    const std::string& message() const { return message_; }
    View* view() { return view_ ? &*view_ : nullptr; }

private:
    enum class Step
    {
        idle, open, save, translate, undo, edited, accepted, job, canvas, editor, cad,
        solverLatest, resultDescribe, resultPage, finished, failed
    };
    void receive(const nlohmann::json& reply);
    void receiveJob(const nlohmann::json& result);
    void receiveCanvas(const nlohmann::json& result);
    void finishView(const nlohmann::json& editor);
    void fail(std::string message);

    PrototypeCad cad_;
    PrototypeCadJob cadJob_;
    bool cadReady_ = false;
    PrototypeResult result_;
    std::string path_;
    std::string message_;
    Step step_ = Step::idle;
    bool saving_ = false;
    bool awaiting_ = false;
    std::string job_;
    std::string movedId_;
    double dx_ = 0;
    double dy_ = 0;
    View loading_;
    std::optional<View> view_;
    nlohmann::json pages_;
    std::size_t offset_ = 0;
    std::chrono::steady_clock::time_point nextPoll_;
    std::chrono::steady_clock::time_point jobDeadline_;
};
