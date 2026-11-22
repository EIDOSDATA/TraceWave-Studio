/** @file @brief 원본 고정, 표시 세대와 유한 읽기 요청을 Studio View에서 분리한다. */
#pragma once
#include "dialog_gateway.h"
#include "result_radiation_data.h"
#include <deque>
#include <memory>
class StudioNotebook;
class wxWindow;
class ResultSourceBrowser;
class ResultConditionsView;
class ResultNetworkView;
class SmithView;
class ResultMetricsView;
class RadiationResultView;
class FieldResultView;
class ResultCompareView;
class MeasurementCompareView;
class ResultWorkspace final
{
public:
    ResultWorkspace(StudioNotebook* views, wxWindow* navigation, wxWindow* conditions, DialogGateway gateway);
    ~ResultWorkspace();
    void Update(const std::string& project, const std::string& epoch, const std::string& revision, bool available,
                int page);
    void Reset();
    /** @brief 보고서에 봉인된 원본 해시를 대조한 뒤 기존 결과 화면으로 연다. */
    void OpenPinned(const Json& source, const Json& pin);
    void SetValidationAvailable(bool available);
    void BuildMeasurementPage(StudioNotebook* views);
    void SetMeasurementAvailable(bool available);
    wxWindow* NavigationView() const;
    wxWindow* ConditionsView() const;
    std::function<void()> onFocusSource;
    std::function<void()> onOpenTools;
    std::function<void()> onOpenValidation;
    std::function<void(const std::string&)> onSolverEvidence;
    std::function<void(const Json&)> onExportResult;
    std::function<void(const std::string&, const Json&, const Json&)> onMeasurementTool;

private:
    friend class StudioSmokeDriver;
    using Callback = std::function<void(const Json&)>;
    struct ReadRequest
    {
        std::string method;
        Json input;
        std::function<bool()> current;
        Callback success;
        Callback failure;
    };
    void Read(const std::string& method, const Json& input, std::function<bool()> current, Callback success,
              Callback failure = {});
    void Pump();
    void Refresh();
    void LoadAnchors(int offset);
    void LoadCatalog(int offset);
    void Select(const Json& source, const Json& expectedPin = nullptr);
    void LocatePinnedSource(const Json& source, const Json& pin, int offset, std::uint64_t catalogGeneration,
                            std::uint64_t selectionGeneration);
    void LoadActive();
    void LoadMeasurements();
    void AddMeasurement(const Json& record);
    void Network(int row, int column, int offset);
    void Smith(int port, const std::string& chart, int offset);
    void Metrics();
    void Radiation(const Json& options);
    void RadiationPage(const Json& options, std::uint64_t generation);
    void FieldDescribe();
    void FieldSlice(const Json& options);
    ResultCompareView* ComparisonView() const;
    void BindComparison(ResultCompareView* view, int page);
    void ComparePage(ResultCompareView* view, std::size_t index, int offset);
    void Compare(ResultCompareView* view, std::size_t index, int offset = 0);
    void Conditions(int offset);
    void Markers(ResultCompareView* view, double frequency);
    void Export();
    bool ComparisonCurrent(ResultCompareView* view, std::size_t index, const Json& description, const Json& order,
                           int row, int column) const;
    Json Pinned() const;
    void ClearViews(const std::string& reason);
    void Error(const std::string& message);
    DialogGateway m_gateway;
    std::shared_ptr<int> m_lifetime = std::make_shared<int>(0);
    std::deque<ReadRequest> m_queue;
    bool m_inflight = false;
    std::uint64_t m_serial = 0, m_catalogGeneration = 0, m_selectionGeneration = 0, m_viewGeneration = 0,
                  m_markerGeneration = 0;
    std::string m_project, m_epoch, m_revision;
    std::string m_catalogHash, m_anchorHash;
    bool m_available = false, m_refreshNeeded = true;
    int m_page = -1;
    Json m_description = nullptr;
    Json m_catalog = nullptr;
    ResultRadiationData m_pattern;
    ResultSourceBrowser* m_browser = nullptr;
    ResultConditionsView* m_conditions = nullptr;
    ResultNetworkView* m_network = nullptr;
    SmithView* m_smith = nullptr;
    ResultMetricsView* m_metrics = nullptr;
    RadiationResultView* m_radiation = nullptr;
    FieldResultView* m_field = nullptr;
    ResultCompareView* m_compare = nullptr;
    MeasurementCompareView* m_measurement = nullptr;
    bool m_measurementAvailable = false;
    bool m_measurementsRefreshNeeded = true;
};
