/** @file @brief 출력 원본 선택과 고정 요청/작업/영수증 수명을 관리한다. */
#pragma once
#include "dialog_gateway.h"
#include "async_state.h"
#include <memory>
class OutputWorkspace;
class wxWindow;

using OutputGateway = std::function<void(const std::string&, const Json&, bool, std::function<void(const Json&)>,
                                         std::function<void(const Json&)>, const std::string&, const std::string&)>;

class OutputController final
{
public:
    OutputController(wxWindow* parent, wxWindow* conditions, const std::string& workspace, OutputGateway gateway);
    ~OutputController();
    OutputWorkspace* View() const;
    void Update(const std::string& project, const std::string& revision, const std::string& epoch, bool connected,
                bool supported, bool available, bool active, bool handoffSupported = false,
                bool archiveSupported = false);
    void Poll(Clock::time_point now);
    bool Active() const;
    bool OwnsJob(const std::string& job) const;
    void OpenStep();
    std::function<void(const std::string&, const std::string&)> onStatus;
    std::function<void()> onStateChanged;
    std::function<void(const Json&)> onCadResult;
    std::function<void(const std::string&, const Json&)> onJobStatus;
    std::function<void(const std::string&, const char*, const Json&)> onCancellation;

private:
    friend class StudioSmokeDriver;
    void Reset();
    void Actions();
    void Status(const std::string& state, const std::string& message);
    void Read(const std::string& method, const Json& input, std::function<void(const Json&)> completed,
              std::function<void(const Json&)> failed = {});
    void Context(int offset = 0, bool resetOptions = false);
    void Catalog(int offset = 0, const std::string& preferred = "");
    void Record(const std::string& job);
    void Capture();
    void Preview();
    void Build();
    void Verify();
    void Changed();
    void Start(const std::string& method, const Json& input);
    void AcceptTask(const Json& task);
    void Complete(const Json& result);
    void Recover();
    void Cancel();
    void OpenFolder();
    void OpenFile();
    void HandoffSync();
    Json ArchiveOutputInput() const;
    void HandoffEvidence(int offset);
    void HandoffCatalog(const std::string& preferred = "");
    void HandoffPreview();
    void HandoffBuild();
    void CompleteHandoff(const Json& package);
    void HandoffSave();
    void HandoffChunk();
    void EndHandoffSave();
    OutputWorkspace* m_view = nullptr;
    OutputGateway m_gateway;
    std::shared_ptr<int> m_lifetime = std::make_shared<int>(0);
    std::string m_workspace, m_project, m_revision, m_epoch, m_catalogFormat;
    bool m_connected = false, m_available = false, m_supported = false, m_active = false;
    bool m_refreshNeeded = true, m_uncertain = false, m_mutating = false, m_cancelRequested = false;
    bool m_handoffSupported = false;
    int m_reads = 0;
    std::uint64_t m_handoffGeneration = 0, m_handoffCatalogGeneration = 0;
    Json m_handoffSnapshot = nullptr, m_handoffDownload = nullptr, m_handoffInput = nullptr;
    std::string m_handoffPath, m_handoffBytes;
    std::uint64_t m_serial = 0, m_contextGeneration = 0, m_catalogGeneration = 0, m_recordGeneration = 0;
    Json m_pending = nullptr, m_previewInput = nullptr;
    Studio::JobTracker m_task;
};
