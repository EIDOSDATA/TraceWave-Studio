/** @file @brief 읽기 전용 검증 선택과 늦은 응답을 프로젝트 수명에 묶는다. */
#pragma once
#include "dialog_gateway.h"
#include <deque>
#include <memory>
class wxWindow;
class RfValidationView;

class RfValidationController final
{
public:
    RfValidationController(wxWindow* parent, wxWindow* navigation, wxWindow* conditions, DialogGateway gateway);
    wxWindow* View() const;
    ~RfValidationController();
    void Update(const std::string& project, const std::string& epoch, bool connected, bool supported, bool available,
                int page);
    void Reset();
    void Refresh();
    std::function<void(const Json&, const Json&)> onOpenResult;
    std::function<void()> onLegacyReport;

private:
    friend class StudioSmokeDriver;
    struct Request
    {
        std::string method;
        Json input;
        std::function<bool()> current;
        std::function<void(const Json&)> success;
        std::function<void(const Json&)> failure;
    };
    void Read(Request request);
    void Pump();
    void Catalog(int offset);
    void Select(const std::string& validationId, const Json& reportId);
    void Reports(int offset);
    void Record();
    RfValidationView* m_view = nullptr;
    DialogGateway m_gateway;
    std::shared_ptr<int> m_lifetime = std::make_shared<int>(0);
    std::deque<Request> m_queue;
    std::string m_project, m_epoch, m_validationId;
    Json m_reportId = nullptr;
    bool m_available = false, m_connected = false, m_inflight = false, m_refreshNeeded = true;
    std::uint64_t m_serial = 0, m_catalogGeneration = 0, m_selectionGeneration = 0, m_reportsGeneration = 0;
};
