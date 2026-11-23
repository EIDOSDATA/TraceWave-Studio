/** @file @brief 측정 기록과 기존 봉인 결과를 별도 정체성으로 선택한다. */
#include "result_workspace.h"
#include "measurement_compare_view.h"
#include "result_compare_view.h"
#include "result_presentation.h"
#include "studio_notebook.h"
#include "studio_support.h"

wxWindow* ResultWorkspace::BuildMeasurementPage(wxWindow* parent)
{
    m_measurement = new MeasurementCompareView(parent);
    BindComparison(m_measurement->Comparison(), 16);
    m_measurement->onRefresh = [this]()
    {
        LoadMeasurements();
    };
    m_measurement->onAddRecord = [this](const Json& record)
    {
        AddMeasurement(record);
    };
    m_measurement->onEditRecord = [this](const Json& record)
    {
        if (onMeasurementTool)
        {
            onMeasurementTool("record", record, m_description);
        }
    };
    m_measurement->onNewRecord = [this]()
    {
        if (onMeasurementTool && m_description.is_object())
        {
            onMeasurementTool("record", nullptr, m_description);
        }
    };
    m_measurement->onImport = [this]()
    {
        if (onMeasurementTool)
        {
            onMeasurementTool("import_record", nullptr, nullptr);
        }
    };
    m_measurement->onAlign = [this]()
    {
        if (onMeasurementTool)
        {
            onMeasurementTool("align", m_measurement->RecordRef(), m_description);
        }
    };
    m_measurement->onSaveComparison = [this]()
    {
        if (onMeasurementTool)
        {
            auto* view = m_measurement->Comparison();
            const auto& sources = view->Descriptions();
            const int index = view->Selected();
            if (index <= 0 || static_cast<std::size_t>(index) >= sources.size() || !view->PortOrder(index).is_array())
            {
                m_measurement->SetStatus("비교할 원본 행과 포트 대응을 먼저 명시하세요.");
                return;
            }
            const auto pinned = [](const Json& source)
            {
                return Json{{"source", source.at("source")},
                            {"pin", source.at("pin")},
                            {"record", source.value("measurement_ref", Json(nullptr))}};
            };
            const Json comparison{{"left", pinned(sources.front())},
                                  {"right", pinned(sources.at(index))},
                                  {"right_port_order", view->PortOrder(index)},
                                  {"row", view->Row()},
                                  {"column", view->Column()},
                                  {"frequency_policy", "exact_only"}};
            onMeasurementTool("compare_record", nullptr, {{"comparison", comparison}});
        }
    };
    m_measurement->onRecover = [this]()
    {
        if (onMeasurementTool)
        {
            onMeasurementTool("recover", nullptr, nullptr);
        }
    };
    m_measurement->onHistory = [this](const Json& entry)
    {
        if (onMeasurementTool)
        {
            onMeasurementTool("history", nullptr, entry);
        }
    };
    m_measurement->SetAvailable(false);
    return m_measurement;
}

ResultCompareView* ResultWorkspace::ComparisonView() const
{
    return m_page == 16 && m_measurement != nullptr ? m_measurement->Comparison() : m_compare;
}

void ResultWorkspace::SetMeasurementAvailable(bool available)
{
    m_measurementAvailable = available;
    if (m_measurement != nullptr)
    {
        m_measurement->SetAvailable(m_available && available);
    }
}

/** @brief 편집 직후 저장된 시료를 정확한 ID, 해시, 개정으로 한 번 선택한다. */
void ResultWorkspace::PreferMeasurement(const Json& reference)
{
    m_preferredMeasurement = reference;
    LoadMeasurements();
}

void ResultWorkspace::LoadMeasurements()
{
    if (!m_measurement || !m_available || !m_measurementAvailable)
    {
        return;
    }
    const auto project = m_project, revision = m_revision;
    const auto request = ++m_measurementRequest;
    m_measurement->SetStatus("현재 개정의 시료 / 교정 기록을 읽고 있습니다.");
    Read(
        "measurement.context", {{"revision_id", nullptr}, {"offset", 0}, {"limit", 32}},
        [this, project, revision, request]()
        {
            return m_project == project && m_revision == revision && m_measurementRequest == request;
        },
        [this, project, revision](const Json& response)
        {
            if (response.value("project_id", "") != project || response.value("revision_id", "") != revision)
            {
                throw std::runtime_error("측정 기록 목록의 프로젝트 또는 개정이 다릅니다.");
            }
            m_measurement->SetRecords(response, m_preferredMeasurement);
            m_preferredMeasurement = nullptr;
        },
        [this](const Json& error)
        {
            m_measurement->SetStatus("측정 기록 조회 실패: " + DiagnosticMessage(error));
        });
}

void ResultWorkspace::AddMeasurement(const Json& record)
{
    if (!m_measurement || !m_available || !m_measurementAvailable || !record.is_object())
    {
        return;
    }
    const auto reference = record.value("record_ref", Json(nullptr));
    if (!reference.is_object())
    {
        return;
    }
    const auto serial = m_catalogGeneration;
    const auto project = m_project;
    Read(
        "measurement.get", {{"record", reference}},
        [this, project, serial]()
        {
            return project == m_project && serial == m_catalogGeneration;
        },
        [this, reference](const Json& response)
        {
            if (response.value("record_ref", Json(nullptr)) != reference ||
                !response.value("pin", Json(nullptr)).is_object())
            {
                throw std::runtime_error("조회한 측정 기록의 고정 개정 또는 원본 해시가 다릅니다.");
            }
            Json description = response;
            description["measurement_ref"] = reference;
            description["measurement_record"] = response.at("record");
            description["measurement_label"] = response.at("record").at("name");
            description["label"] = response.at("record").at("name");
            description["current_revision_id"] = m_revision;
            m_measurement->Comparison()->Add(description);
        },
        [this](const Json& error)
        {
            m_measurement->SetStatus("측정 기록 선택 실패: " + DiagnosticMessage(error));
        });
}
