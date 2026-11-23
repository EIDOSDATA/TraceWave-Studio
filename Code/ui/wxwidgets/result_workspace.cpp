/** @file @brief 봉인 source/pin과 프로젝트 수명이 일치한 읽기 응답만 View에 전달한다. */
#include "result_workspace.h"
#include "result_source_browser.h"
#include "result_conditions_view.h"
#include "result_network_view.h"
#include "smith_view.h"
#include "result_metrics_view.h"
#include "result_radiation_view.h"
#include "field_result_view.h"
#include "result_compare_view.h"
#include "measurement_compare_view.h"
#include "result_presentation.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include <wx/sizer.h>
#include <algorithm>
ResultWorkspace::ResultWorkspace(StudioNotebook* views, wxWindow* navigation, wxWindow* conditions,
                                 DialogGateway gateway)
    : m_gateway(std::move(gateway))
{
    m_browser = new ResultSourceBrowser(navigation);
    m_conditions = new ResultConditionsView(conditions);
    navigation->GetSizer()->Add(m_browser, 1, wxEXPAND);
    conditions->GetSizer()->Add(m_conditions, 1, wxEXPAND);
    m_browser->Hide();
    m_conditions->Hide();
    m_network = new ResultNetworkView(views);
    views->AddPage(m_network, Display("네트워크"));
    m_smith = new SmithView(views);
    views->AddPage(m_smith, Display("Smith"));
    m_metrics = new ResultMetricsView(views);
    views->AddPage(m_metrics, Display("전력 / 손실"));
    m_radiation = new RadiationResultView(views);
    views->AddPage(m_radiation, Display("방사 / 편파"));
    m_field = new FieldResultView(views);
    views->AddPage(m_field, Display("필드"));
    m_compare = new ResultCompareView(views);
    views->AddPage(m_compare, Display("결과 / 후보 비교"));
    m_browser->onRefresh = [this]()
    {
        Refresh();
    };
    m_browser->onContextChanged = [this]()
    {
        Refresh();
    };
    m_browser->onPage = [this](int offset)
    {
        LoadCatalog(offset);
    };
    m_browser->onAnchorPage = [this](int offset)
    {
        LoadAnchors(offset);
    };
    m_browser->onSelect = [this](const Json& source)
    {
        Select(source);
    };
    const auto focus = [this]()
    {
        if (onFocusSource)
        {
            onFocusSource();
        }
    };
    m_network->onSelectSource = focus;
    m_smith->onSelectSource = focus;
    m_metrics->onSelectSource = focus;
    const auto validation = [this]()
    {
        if (onOpenValidation)
        {
            onOpenValidation();
        }
    };
    m_conditions->onValidation = validation;
    m_conditions->onSolverEvidence = [this](const std::string& artifact)
    {
        if (onSolverEvidence)
        {
            onSolverEvidence(artifact);
        }
    };
    m_metrics->onValidation = validation;
    m_radiation->onSelectSource = focus;
    m_network->onOpenTools = [this]()
    {
        if (onOpenTools)
        {
            onOpenTools();
        }
    };
    m_network->onExport = [this]()
    {
        Export();
    };
    m_network->onRequest = [this](int row, int column, int offset)
    {
        Network(row, column, offset);
    };
    m_smith->onRequest = [this](int port, const std::string& chart, int offset)
    {
        Smith(port, chart, offset);
    };
    m_radiation->onRequest = [this](const Json& options)
    {
        Radiation(options);
    };
    m_radiation->onInvalidate = [this]()
    {
        ++m_viewGeneration;
        m_pattern.Reset();
    };
    m_field->onFlux = [this](const Json& options)
    {
        auto input = options;
        input.update(Pinned());
        const auto generation = ++m_viewGeneration;
        m_field->SetBusy(true);
        Read("result.field.flux", input, [this, generation]()
        {
            return generation == m_viewGeneration;
        }, [this](const Json& response)
        {
            m_field->SetBusy(false);
            if (!ResultUi::Matches(response, m_description))
            {
                throw std::runtime_error("통과 전력의 원본이 현재 결과와 다릅니다.");
            }
            m_field->SetFlux(response);
        }, [this](const Json& error)
        {
            m_field->SetError("통과 전력 계산 실패: " + DiagnosticMessage(error));
        });
    };
    m_field->onSlice = [this](const Json& options)
    {
        FieldSlice(options);
    };
    m_field->onRefine = [this](const Json& options)
    {
        auto input = options;
        input.update(Pinned());
        if (input.contains("max_rounds") && onFieldStudy)
        {
            Json selection, limits;
            for (const auto* key : {"monitor_id", "component", "frequency_index", "plane", "roi"})
            {
                selection[key] = input.at(key);
            }
            for (const auto* key : {"threshold_fraction", "max_rules", "memory_limit_mib", "max_rounds", "max_s11_complex_delta"})
            {
                limits[key] = input.at(key);
            }
            onFieldStudy({{"source", input.at("source")}, {"pin", input.at("pin")}, {"selection", selection},
                          {"limits", limits}, {"name", "전계 기반 국부 격자 연구"}});
            return;
        }
        const auto generation = ++m_viewGeneration;
        m_field->SetBusy(true);
        Read("result.field.refine", input, [this, generation]()
        {
            return generation == m_viewGeneration;
        }, [this](const Json& response)
        {
            m_field->SetBusy(false);
            if (!ResultUi::Matches(response, m_description))
            {
                throw std::runtime_error("전계 격자 제안의 원본이 현재 결과와 다릅니다.");
            }
            if (response.at("status") == "refined" && onFieldRefinement)
            {
                onFieldRefinement(response);
                return;
            }
            const auto status = response.at("status").get<std::string>();
            m_field->SetError(status == "memory_limit" ? "제안한 격자의 예상 메모리가 상한을 초과합니다." :
                status == "rule_limit" ? "기존 국부 격자 규칙 수가 상한에 도달했습니다." :
                "이 단면과 변화 기준으로 추가 세분화할 구간이 없습니다.");
        }, [this](const Json& error)
        {
            m_field->SetError("전계 격자 검토 실패: " + DiagnosticMessage(error));
        });
    };
    BindComparison(m_compare, 14);
    m_conditions->onConditionPage = [this](int offset)
    {
        Conditions(offset);
    };
}
ResultWorkspace::~ResultWorkspace()
{
    m_lifetime.reset();
    m_queue.clear();
}
wxWindow* ResultWorkspace::NavigationView() const
{
    return m_browser;
}
wxWindow* ResultWorkspace::ConditionsView() const
{
    return m_conditions;
}
void ResultWorkspace::Read(const std::string& method, const Json& input, std::function<bool()> current,
                           Callback success, Callback failure)
{
    m_queue.erase(std::remove_if(m_queue.begin(), m_queue.end(),
                                 [](const ReadRequest& item)
                                 {
                                     return !item.current();
                                 }),
                  m_queue.end());
    if (m_queue.size() >= 32)
    {
        const Json error{{"code", "E_RESOURCE"},
                         {"message", "결과 조회 대기열이 가득 찼습니다. 진행 중인 조회 후 다시 선택하세요."}};
        if (current())
        {
            if (failure)
            {
                failure(error);
            }
            else
            {
                Error(error.at("message").get<std::string>());
            }
        }
        return;
    }
    m_queue.push_back({method, input, std::move(current), std::move(success), std::move(failure)});
    Pump();
}
void ResultWorkspace::Pump()
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
    const auto serial = ++m_serial;
    const std::weak_ptr<int> lifetime = m_lifetime;
    const auto completed = [this, lifetime, serial, request](const Json& result, bool success)
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
                    request.success(result);
                }
                else if (request.failure)
                {
                    request.failure(result);
                }
                else
                {
                    Error(DiagnosticMessage(result));
                }
            }
        }
        catch (const std::exception& error)
        {
            Error(error.what());
        }
        m_inflight = false;
        Pump();
    };
    m_gateway(
        request.method, request.input, false,
        [completed](const Json& result)
        {
            completed(result, true);
        },
        [completed](const Json& error)
        {
            completed(error, false);
        });
}
void ResultWorkspace::Update(const std::string& project, const std::string& epoch, const std::string& revision,
                             bool available, int page)
{
    if (project != m_project || epoch != m_epoch)
    {
        Reset();
        m_project = project;
        m_epoch = epoch;
    }
    if (revision != m_revision)
    {
        m_revision = revision;
        m_refreshNeeded = true;
        m_measurementsRefreshNeeded = true;
    }
    m_available = available;
    m_browser->SetAvailable(available);
    m_compare->SetAvailable(available);
    if (m_measurement != nullptr)
    {
        m_measurement->SetAvailable(available && m_measurementAvailable);
        m_measurement->SetSelectionAvailable(m_description.is_object());
    }
    for (wxWindow* view : std::vector<wxWindow*>{m_network, m_smith, m_metrics, m_radiation, m_field, m_compare})
    {
        view->Enable(available);
    }
    const bool active = (page >= 9 && page <= 14) || page == 16;
    m_browser->Show(active);
    m_conditions->Show(active);
    const bool changed = page != m_page;
    m_page = page;
    if (active && available && m_refreshNeeded)
    {
        m_refreshNeeded = false;
        Refresh();
    }
    if (active && available && m_description.is_object() &&
        m_description.value("current_revision_id", "") != m_revision)
    {
        const auto source = m_description.at("source");
        Select(source);
    }
    if (changed)
    {
        ++m_viewGeneration;
        if (active && available && m_description.is_object())
        {
            LoadActive();
        }
    }
    if (page == 16 && available && m_measurementAvailable && (changed || m_measurementsRefreshNeeded))
    {
        m_measurementsRefreshNeeded = false;
        LoadMeasurements();
    }
    Pump();
}
void ResultWorkspace::Reset()
{
    ++m_serial;
    ++m_catalogGeneration;
    ++m_selectionGeneration;
    ++m_viewGeneration;
    ++m_markerGeneration;
    m_inflight = false;
    m_queue.clear();
    m_description = nullptr;
    m_catalog = nullptr;
    m_pattern.Reset();
    m_catalogHash.clear();
    m_anchorHash.clear();
    m_refreshNeeded = true;
    m_measurementsRefreshNeeded = true;
    m_page = -1;
    m_revision.clear();
    m_browser->Reset();
    m_compare->Clear();
    if (m_measurement != nullptr)
    {
        m_measurement->Clear();
    }
    ClearViews("현재 프로젝트의 보존 원본을 선택하세요.");
    m_conditions->Clear("원본을 선택하면 당시 조건을 표시합니다.");
}
void ResultWorkspace::Refresh()
{
    if (!m_available)
    {
        return;
    }
    ++m_catalogGeneration;
    m_catalogHash.clear();
    m_anchorHash.clear();
    m_browser->ClearCatalog("목록을 다시 읽고 있습니다. 표시 원본의 고정 개정은 유지합니다.");
    if (m_browser->Kind() == "network")
    {
        LoadAnchors(0);
    }
    else if (m_browser->Kind() == "sweep")
    {
        const auto generation = m_catalogGeneration;
        Read(
            "sweep.list", Json::object(),
            [this, generation]()
            {
                return generation == m_catalogGeneration;
            },
            [this](const Json& result)
            {
                m_browser->SetStudies(result);
                LoadCatalog(0);
            });
    }
    else
    {
        LoadCatalog(0);
    }
}
void ResultWorkspace::LoadAnchors(int offset)
{
    const auto generation = ++m_catalogGeneration;
    m_browser->ClearCatalog("보존한 개정 목록을 조회하고 있습니다.");
    Read(
        "result.revisions",
        {{"offset", offset}, {"limit", 25}, {"catalog_hash", offset == 0 ? Json(nullptr) : Json(m_anchorHash)}},
        [this, generation]()
        {
            return generation == m_catalogGeneration;
        },
        [this](const Json& response)
        {
            m_anchorHash = response.at("catalog_hash").get<std::string>();
            m_browser->SetAnchors(response);
            m_catalogHash.clear();
            LoadCatalog(0);
        });
}
void ResultWorkspace::LoadCatalog(int offset)
{
    const auto kind = m_browser->Kind();
    const auto anchor = m_browser->Anchor();
    const auto study = m_browser->StudyId();
    const auto generation = ++m_catalogGeneration;
    if (kind == "sweep" && study.empty())
    {
        m_browser->ClearCatalog("저장된 연구가 없습니다. 해석의 연구 화면에서 먼저 연구를 만드세요.");
        return;
    }
    Json input{{"kind", kind},
               {"revision_id", kind == "network" && anchor.is_object() ? anchor.at("revision_id") : Json(nullptr)},
               {"snapshot_id",
                kind == "network" && anchor.is_object() ? anchor.value("snapshot_id", Json(nullptr)) : Json(nullptr)},
               {"study_id", kind == "sweep" ? Json(study) : Json(nullptr)},
               {"offset", offset},
               {"limit", 25},
               {"catalog_hash", offset == 0 ? Json(nullptr) : Json(m_catalogHash)}};
    m_browser->ClearCatalog("선택 범위의 실제 보존 결과를 읽고 있습니다.");
    Read(
        "result.sources", input,
        [this, generation]()
        {
            return generation == m_catalogGeneration;
        },
        [this](const Json& response)
        {
            m_catalog = response;
            m_catalogHash = response.at("catalog_hash").get<std::string>();
            m_browser->SetCatalog(response, m_description.is_object() ? m_description.at("source") : Json(nullptr));
        });
}
void ResultWorkspace::OpenPinned(const Json& source, const Json& pin)
{
    if (!m_available || !source.is_object() || !pin.is_object())
    {
        return;
    }
    if (source.value("kind", "") != "solver")
    {
        Error("검증 기록의 직접 결과 연결은 보존 해석 실행만 지원합니다.");
        return;
    }
    ++m_catalogGeneration;
    m_catalog = nullptr;
    m_catalogHash.clear();
    m_browser->SetSolverContext();
    Select(source, pin);
}
void ResultWorkspace::SetValidationAvailable(bool available)
{
    m_conditions->SetValidationAvailable(available);
    m_metrics->SetValidationAvailable(available);
}
void ResultWorkspace::Select(const Json& source, const Json& expectedPin)
{
    const auto generation = ++m_selectionGeneration;
    const auto catalogGeneration = m_catalogGeneration;
    ++m_viewGeneration;
    m_description = nullptr;
    m_pattern.Reset();
    ClearViews("선택한 원본의 기록과 조건을 읽고 있습니다.");
    m_conditions->Clear("선택한 원본 조회 중");
    Read(
        "result.describe", {{"source", source}},
        [this, generation]()
        {
            return generation == m_selectionGeneration;
        },
        [this, source, expectedPin, generation, catalogGeneration](const Json& description)
        {
            if (description.at("source") != source || !description.value("pin", Json(nullptr)).is_object())
            {
                throw std::runtime_error("선택한 결과의 원본 또는 고정 해시가 다릅니다.");
            }
            if (expectedPin.is_object() && description.at("pin") != expectedPin)
            {
                throw std::runtime_error("검증 보고서의 봉인 해시와 현재 조회한 원본이 다릅니다.");
            }
            m_description = description;
            m_conditions->SetDescription(description);
            m_network->SetDescription(description);
            m_smith->SetDescription(description);
            m_metrics->SetDescription(description);
            m_radiation->SetDescription(description);
            if (m_catalog.is_object())
            {
                m_browser->SetCatalog(m_catalog, source);
            }
            LoadActive();
            if (expectedPin.is_object() && catalogGeneration == m_catalogGeneration)
            {
                LocatePinnedSource(source, expectedPin, 0, catalogGeneration, generation);
            }
        });
}
Json ResultWorkspace::Pinned() const
{
    return {{"source", m_description.at("source")}, {"pin", m_description.at("pin")}};
}
void ResultWorkspace::LoadActive()
{
    if (!m_description.is_object())
    {
        return;
    }
    m_conditions->SetDescription(m_description);
    if (m_page == 9)
    {
        m_network->SetDescription(m_description);
        Network(0, 0, 0);
    }
    else if (m_page == 10)
    {
        m_smith->SetDescription(m_description);
        Smith(m_smith->Port(), m_smith->Chart(), 0);
    }
    else if (m_page == 11)
    {
        m_metrics->SetDescription(m_description);
        Metrics();
    }
    else if (m_page == 12)
    {
        m_radiation->SetDescription(m_description);
        Radiation(m_radiation->Options());
    }
    else if (m_page == 13)
    {
        FieldDescribe();
    }
    else if (m_page == 14 || m_page == 16)
    {
        ComparisonView()->InspectSelection();
    }
}
void ResultWorkspace::Network(int row, int column, int offset)
{
    if (!m_description.is_object())
    {
        return;
    }
    const auto generation = ++m_viewGeneration;
    auto input = Pinned();
    input.update({{"row", row}, {"column", column}, {"offset", offset}, {"limit", 201}});
    m_network->SetBusy(true);
    Read(
        "result.page", input,
        [this, generation]()
        {
            return generation == m_viewGeneration;
        },
        [this, row, column, offset](const Json& result)
        {
            if (!ResultUi::Matches(result, m_description) ||
                result.at("page").at("channel") != Json{{"row", row}, {"column", column}} ||
                result.at("page").at("offset") != offset)
            {
                throw std::runtime_error("네트워크 응답의 원본, 채널 또는 페이지가 요청과 다릅니다.");
            }
            m_network->SetPage(result);
        },
        [this](const Json& error)
        {
            m_network->Clear("실제 표본 조회 실패: " + DiagnosticMessage(error));
        });
}
void ResultWorkspace::Smith(int port, const std::string& chart, int offset)
{
    if (!m_description.is_object())
    {
        return;
    }
    const auto generation = ++m_viewGeneration;
    auto input = Pinned();
    input.update({{"port", port}, {"chart", chart}, {"offset", offset}, {"limit", 201}});
    m_smith->SetBusy(true);
    Read(
        "result.smith", input,
        [this, generation]()
        {
            return generation == m_viewGeneration;
        },
        [this, port, chart, offset](const Json& result)
        {
            if (!ResultUi::Matches(result, m_description) ||
                result.at("channel") != Json{{"row", port}, {"column", port}} || result.at("offset") != offset ||
                result.at("chart") != chart)
            {
                throw std::runtime_error("Smith 응답의 원본, 채널 또는 페이지가 요청과 다릅니다.");
            }
            m_smith->SetPage(result);
        },
        [this](const Json& error)
        {
            m_smith->Clear("Smith 표시 불가: " + DiagnosticMessage(error));
        });
}
void ResultWorkspace::Metrics()
{
    const auto generation = ++m_viewGeneration;
    Read(
        "result.metrics", Pinned(),
        [this, generation]()
        {
            return generation == m_viewGeneration;
        },
        [this](const Json& result)
        {
            m_metrics->SetMetrics(result);
        },
        [this](const Json& error)
        {
            m_metrics->Clear("전력 기록 조회 실패: " + DiagnosticMessage(error));
        });
}
void ResultWorkspace::Radiation(const Json& options)
{
    if (!m_description.is_object())
    {
        return;
    }
    const auto generation = ++m_viewGeneration;
    m_pattern.Reset();
    m_radiation->SetBusy(true, "기록한 방사 각도 페이지를 읽고 있습니다.");
    RadiationPage(options, generation);
}
void ResultWorkspace::RadiationPage(const Json& options, std::uint64_t generation)
{
    auto input = Pinned();
    input.update(options);
    input["theta_offset"] = m_pattern.Next();
    input["theta_limit"] = 5;
    Read(
        "result.radiation", input,
        [this, generation]()
        {
            return generation == m_viewGeneration;
        },
        [this, options, generation](const Json& response)
        {
            m_pattern.Append(response, m_description, options);
            if (m_pattern.Complete())
            {
                m_radiation->SetPattern(m_pattern.Data());
            }
            else
            {
                m_radiation->SetBusy(true, "기록 각도 " + std::to_string(m_pattern.Next()) + " / " +
                                               std::to_string(response.at("theta_count").get<int>()) + "행 조회됨");
                RadiationPage(options, generation);
            }
        },
        [this](const Json& error)
        {
            m_pattern.Reset();
            m_radiation->SetError("방사 자료를 표시할 수 없습니다: " + DiagnosticMessage(error));
        });
}
void ResultWorkspace::FieldDescribe()
{
    const auto generation = ++m_viewGeneration;
    m_field->SetBusy(true);
    Read(
        "result.field.describe", Pinned(),
        [this, generation]()
        {
            return generation == m_viewGeneration;
        },
        [this](const Json& response)
        {
            if (!ResultUi::Matches(response, m_description))
            {
                throw std::runtime_error("필드 원본이 선택과 다릅니다.");
            }
            m_field->SetDescription(response);
            m_field->SetBusy(false);
        },
        [this](const Json& error)
        {
            m_field->Clear("필드 기록 조회 불가: " + DiagnosticMessage(error));
        });
}
void ResultWorkspace::FieldSlice(const Json& options)
{
    if (!m_description.is_object())
    {
        return;
    }
    const auto generation = ++m_viewGeneration;
    auto input = options;
    input.update(Pinned());
    m_field->SetBusy(true);
    Read(
        "result.field.page", input,
        [this, generation]()
        {
            return generation == m_viewGeneration;
        },
        [this](const Json& response)
        {
            if (!ResultUi::Matches(response, m_description))
            {
                throw std::runtime_error("필드 단면의 원본이 선택과 다릅니다.");
            }
            m_field->SetSlice(response);
            m_field->SetBusy(false);
        },
        [this](const Json& error)
        {
            m_field->SetError("필드 단면 조회 실패: " + DiagnosticMessage(error));
        });
}
void ResultWorkspace::ClearViews(const std::string& reason)
{
    m_network->Clear(reason);
    m_smith->Clear(reason);
    m_metrics->Clear(reason);
    m_radiation->Clear(reason);
    m_field->Clear(reason);
}
void ResultWorkspace::Error(const std::string& message)
{
    m_browser->SetStatus(message);
    ClearViews(message);
    m_conditions->Clear(message);
}
