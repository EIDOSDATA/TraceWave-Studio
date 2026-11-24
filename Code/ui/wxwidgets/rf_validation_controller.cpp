/** @file @brief 불변 판정 ID와 선택 세대를 확인한 뒤에만 검증 표를 교체한다. */
#include "rf_validation_controller.h"
#include "rf_validation_view.h"
#include "studio_support.h"
#include <algorithm>
#include <stdexcept>

namespace
{
void Page(const Json& response, int offset)
{
    const auto& items = response.at("items");
    const int total = response.at("total").get<int>();
    if (response.value("profile", "") != "rfad.rf-validation/0.1" || response.at("offset") != offset || total < 0 ||
        !items.is_array() || items.size() > 25 || offset + static_cast<int>(items.size()) > total)
    {
        throw std::runtime_error("검증 목록의 프로필 또는 페이지 경계가 다릅니다.");
    }
    const int next = offset + static_cast<int>(items.size());
    if (response.at("next_offset") != (next < total ? Json(next) : Json(nullptr)))
    {
        throw std::runtime_error("검증 목록의 다음 페이지가 실제 반환 범위와 다릅니다.");
    }
}
}

RfValidationController::RfValidationController(wxWindow* parent, wxWindow* navigation, wxWindow* conditions,
                                               DialogGateway gateway)
    : m_gateway(std::move(gateway))
{
    m_view = new RfValidationView(parent, navigation, conditions);
    m_view->onRefresh = [this]()
    {
        Refresh();
    };
    m_view->onCatalogPage = [this](int offset)
    {
        Catalog(offset);
    };
    m_view->onSelect = [this](const std::string& id, const Json& report)
    {
        Select(id, report);
    };
    m_view->onReport = [this](const Json& report)
    {
        if (!m_validationId.empty())
        {
            Select(m_validationId, report);
        }
    };
    m_view->onReportPage = [this](int offset)
    {
        Reports(offset);
    };
    m_view->onOpenResult = [this](const Json& source, const Json& pin)
    {
        if (m_available && onOpenResult)
        {
            onOpenResult(source, pin);
        }
    };
    m_view->onLegacyReport = [this]()
    {
        if (onLegacyReport)
        {
            onLegacyReport();
        }
    };
}

wxWindow* RfValidationController::View() const
{
    return m_view;
}

RfValidationController::~RfValidationController()
{
    m_lifetime.reset();
}

void RfValidationController::Reset()
{
    ++m_serial;
    ++m_catalogGeneration;
    ++m_selectionGeneration;
    ++m_reportsGeneration;
    m_queue.clear();
    m_inflight = false;
    m_validationId.clear();
    m_reportId = nullptr;
    m_refreshNeeded = true;
    m_view->Clear("현재 프로젝트의 보존 검증 기록을 선택하세요.");
}

void RfValidationController::Update(const std::string& project, const std::string& epoch, bool connected,
                                    bool supported, bool available, int page)
{
    if (project != m_project || epoch != m_epoch || (m_connected && !connected))
    {
        Reset();
        m_project = project;
        m_epoch = epoch;
    }
    m_connected = connected;
    m_available = available && connected && supported && !project.empty();
    const bool active = page == 15;
    m_view->NavigationView()->Show(active);
    m_view->ConditionsView()->Show(active);
    m_view->SetAvailable(m_available);
    if (active && (!connected || !supported || project.empty()))
    {
        m_view->SetStatus(
            !connected   ? "서비스 연결이 필요합니다. 보존 판정이나 성공 결과를 생성하지 않습니다."
            : !supported ? "현재 서비스에는 독립 RF 검증 기록 조회 기능이 없습니다. 기존 수렴 보고서는 열 수 있습니다."
                         : "프로젝트를 열면 그 프로젝트의 보존 검증 기록을 조회할 수 있습니다.");
    }
    if (active && m_available && m_refreshNeeded)
    {
        m_refreshNeeded = false;
        Refresh();
    }
    Pump();
}

void RfValidationController::Read(Request request)
{
    /** @brief 같은 종류의 아직 보내지 않은 조회는 마지막 요청만 유지해 빠른 선택의 자원 사용을 제한한다. */
    m_queue.erase(std::remove_if(m_queue.begin(), m_queue.end(),
                                 [&request](const Request& queued)
                                 {
                                     return queued.method == request.method;
                                 }),
                  m_queue.end());
    if (m_queue.size() >= 4)
    {
        if (request.current())
        {
            request.failure({{"code", "E_RESOURCE"}, {"message", "검증 조회 대기 상한입니다. 다시 선택하세요."}});
        }
        return;
    }
    m_queue.push_back(std::move(request));
    Pump();
}

void RfValidationController::Pump()
{
    if (m_inflight || !m_available)
    {
        return;
    }
    while (!m_queue.empty() && !m_queue.front().current())
    {
        m_queue.pop_front();
    }
    if (m_queue.empty())
    {
        return;
    }
    auto request = std::move(m_queue.front());
    m_queue.pop_front();
    m_inflight = true;
    const auto serial = m_serial;
    const std::weak_ptr<int> lifetime = m_lifetime;
    const auto finish = [this, lifetime, serial, request](const Json& response, bool success)
    {
        if (lifetime.expired() || serial != m_serial)
        {
            return;
        }
        try
        {
            if (request.current())
            {
                if (success)
                {
                    request.success(response);
                }
                else
                {
                    request.failure(response);
                }
            }
        }
        catch (const std::exception& error)
        {
            m_view->ClearRecord(std::string("검증 기록 읽기 실패: ") + error.what());
        }
        m_inflight = false;
        Pump();
    };
    m_gateway(
        request.method, request.input, false,
        [finish](const Json& result)
        {
            finish(result, true);
        },
        [finish](const Json& error)
        {
            finish(error, false);
        });
}

void RfValidationController::Refresh()
{
    if (!m_available)
    {
        return;
    }
    Catalog(0);
    if (!m_validationId.empty())
    {
        Reports(0);
        Record();
    }
}

void RfValidationController::Catalog(int offset)
{
    const auto generation = ++m_catalogGeneration;
    Read({"rf.validation.list",
          {{"offset", offset}, {"limit", 25}},
          [this, generation]()
          {
              return generation == m_catalogGeneration;
          },
          [this, offset](const Json& response)
          {
              Page(response, offset);
              if (response.at("total") == 0)
              {
                  ++m_selectionGeneration;
                  ++m_reportsGeneration;
                  m_validationId.clear();
                  m_reportId = nullptr;
                  m_view->Clear("보존한 검증 기록이 없습니다. 원본 자료를 임의 참조 사례로 만들지 않습니다.");
              }
              m_view->SetCatalog(response, m_validationId);
          },
          [this](const Json& error)
          {
              m_view->SetStatus("목록 조회에 실패해 마지막 기록을 표시합니다. 사유: " + DiagnosticMessage(error));
          }});
}

void RfValidationController::Select(const std::string& id, const Json& report)
{
    const bool changed = id != m_validationId;
    ++m_selectionGeneration;
    m_validationId = id;
    m_reportId = report;
    m_view->ClearRecord("선택한 계획 또는 보존 판정을 조회하고 있습니다.");
    if (changed)
    {
        m_view->SetReports({{"offset", 0}, {"total", 0}, {"next_offset", nullptr}, {"items", Json::array()}}, report);
        Reports(0);
    }
    Record();
}

void RfValidationController::Reports(int offset)
{
    if (m_validationId.empty())
    {
        return;
    }
    const auto id = m_validationId;
    const auto generation = ++m_reportsGeneration;
    Read({"rf.validation.reports",
          {{"validation_id", id}, {"offset", offset}, {"limit", 25}},
          [this, id, generation]()
          {
              return id == m_validationId && generation == m_reportsGeneration;
          },
          [this, offset](const Json& response)
          {
              Page(response, offset);
              m_view->SetReports(response, m_reportId);
          },
          [this](const Json& error)
          {
              m_view->SetStatus("보존 판정 목록 조회 실패: " + DiagnosticMessage(error));
          }});
}

void RfValidationController::Record()
{
    if (m_validationId.empty())
    {
        return;
    }
    const auto id = m_validationId;
    const auto report = m_reportId;
    const auto generation = ++m_selectionGeneration;
    m_view->SetPending(true, "선택한 검증 기록을 읽고 있습니다. 원본과 기존 판정은 보존됩니다.");
    Read({"rf.validation.get",
          {{"validation_id", id}, {"report_id", report}},
          [this, id, report, generation]()
          {
              return id == m_validationId && report == m_reportId && generation == m_selectionGeneration;
          },
          [this, id, report](const Json& response)
          {
              if (response.value("profile", "") != "rfad.rf-validation/0.1" || response.at("validation_id") != id ||
                  response.at("report_id") != report || !response.at("cases").is_array() ||
                  response.at("cases").size() > 9 || !response.at("rows").is_array() ||
                  response.at("rows").size() > 128 || (report.is_null() != response.at("assessment_hash").is_null()))
              {
                  throw std::runtime_error("검증 판정의 선택, 고정 해시 또는 행 범위가 요청과 다릅니다.");
              }
              m_view->SetRecord(response);
          },
          [this](const Json& error)
          {
              m_view->ClearRecord("선택한 기록 조회 실패: " + DiagnosticMessage(error));
          }});
}
