/** @file @brief 비교 집합의 원본/채널/포트 대응이 같은 응답만 전달한다. */
#include "result_workspace.h"
#include "result_compare_view.h"
#include "result_conditions_view.h"
#include "result_network_view.h"
#include "result_source_browser.h"
#include "result_presentation.h"
#include "measurement_model.h"
#include "studio_support.h"
#include <wx/choicdlg.h>
void ResultWorkspace::BindComparison(ResultCompareView* view, int page)
{
    view->onAddSelected = [this, view, page]()
    {
        if (m_description.is_object())
        {
            view->Add(m_description);
        }
        else
        {
            m_browser->SetStatus("먼저 원본을 선택하세요.");
            if (onFocusSource)
            {
                onFocusSource();
            }
        }
    };
    view->onChanged = [this, view, page]()
    {
        ++m_markerGeneration;
        if (m_page == page)
        {
            const auto& descriptions = view->Descriptions();
            const int selected = view->Selected();
            if (selected >= 0 && static_cast<std::size_t>(selected) < descriptions.size())
            {
                m_conditions->SetDescription(descriptions[static_cast<std::size_t>(selected)]);
            }
            else
            {
                m_conditions->Clear("비교 목록의 원본을 선택하면 그 기록의 조건을 표시합니다.");
            }
        }
    };
    view->onPage = [this, view, page](std::size_t index, int offset)
    {
        ComparePage(view, index, offset);
    };
    view->onCompare = [this, view, page](std::size_t index)
    {
        Compare(view, index);
    };
    view->onComparePage = [this, view, page](std::size_t index, int offset)
    {
        Compare(view, index, offset);
    };
    view->onMarkers = [this, view, page](double frequency)
    {
        Markers(view, frequency);
    };
    view->onConditions = [this, view, page](const Json& response)
    {
        if (m_page == page)
        {
            const auto& descriptions = view->Descriptions();
            const int selected = view->Selected();
            if (selected > 0 && static_cast<std::size_t>(selected) < descriptions.size())
            {
                m_conditions->SetComparison(
                    response, descriptions.front().value("label", std::string()),
                    descriptions[static_cast<std::size_t>(selected)].value("label", std::string()));
            }
        }
    };
    view->onInspect = [this, view, page](const Json& description)
    {
        if (m_page == page)
        {
            if (description.is_object())
            {
                m_conditions->SetDescription(description);
            }
            else
            {
                m_conditions->Clear("비교 목록의 원본을 선택하세요.");
            }
        }
    };
}

bool ResultWorkspace::ComparisonCurrent(ResultCompareView* view, std::size_t index, const Json& description,
                                        const Json& order, int row, int column) const
{
    const auto& descriptions = view->Descriptions();
    return index < descriptions.size() && ResultUi::Matches(description, descriptions[index]) &&
           description.value("measurement_ref", Json(nullptr)) ==
               descriptions[index].value("measurement_ref", Json(nullptr)) &&
           view->PortOrder(index) == order && view->Row() == row && view->Column() == column;
}
void ResultWorkspace::ComparePage(ResultCompareView* view, std::size_t index, int offset)
{
    const auto descriptions = view->Descriptions();
    if (index >= descriptions.size())
    {
        return;
    }
    const auto description = descriptions[index], order = view->PortOrder(index);
    const int row = view->Row(), column = view->Column();
    const int actualRow = index == 0 ? row : order.is_array() ? order.at(static_cast<std::size_t>(row)).get<int>() : 0;
    const int actualColumn = index == 0         ? column
                             : order.is_array() ? order.at(static_cast<std::size_t>(column)).get<int>()
                                                : 0;
    Json input{{"source", description.at("source")},
               {"pin", description.at("pin")},
               {"row", actualRow},
               {"column", actualColumn},
               {"offset", offset},
               {"limit", 201}};
    Read(
        "result.page", input,
        [this, view, index, description, order, row, column]()
        {
            return ComparisonCurrent(view, index, description, order, row, column);
        },
        [this, view, index, description, actualRow, actualColumn, offset](const Json& response)
        {
            if (!ResultUi::Matches(response, description) ||
                response.at("page").at("channel") != Json{{"row", actualRow}, {"column", actualColumn}} ||
                response.at("page").at("offset") != offset)
            {
                throw std::runtime_error("비교 곡선의 원본, 채널 또는 페이지가 요청과 다릅니다.");
            }
            view->SetPage(index, response);
        },
        [this](const Json& error)
        {
            m_browser->SetStatus("비교 원본의 실제 표본 조회 실패: " + DiagnosticMessage(error));
        });
}
void ResultWorkspace::Compare(ResultCompareView* view, std::size_t index, int offset)
{
    const auto descriptions = view->Descriptions();
    if (index == 0 || index >= descriptions.size())
    {
        return;
    }
    const auto left = descriptions.front(), right = descriptions[index], order = view->PortOrder(index);
    if (!order.is_array())
    {
        return;
    }
    const int row = view->Row(), column = view->Column();
    Json leftPin{{"source", left.at("source")}, {"pin", left.at("pin")}},
        rightPin{{"source", right.at("source")}, {"pin", right.at("pin")}};
    if (view->MeasurementMode())
    {
        leftPin["record"] = left.value("measurement_ref", Json(nullptr));
        rightPin["record"] = right.value("measurement_ref", Json(nullptr));
    }
    Json input{{"left", leftPin},  {"right", rightPin}, {"right_port_order", order},
               {"row", row},       {"column", column},  {"frequency_policy", "exact_only"},
               {"offset", offset}, {"limit", 201}};
    Read(
        view->MeasurementMode() ? "measurement.compare" : "result.compare", input,
        [this, view, index, left, right, order, row, column]()
        {
            return !view->Descriptions().empty() && MeasurementUi::SameRecord(left, view->Descriptions().front()) &&
                   ComparisonCurrent(view, index, right, order, row, column);
        },
        [this, view, index, leftPin, rightPin, row, column, offset](const Json& response)
        {
            if (response.at("left") != leftPin || response.at("right") != rightPin ||
                response.at("channel") != Json{{"row", row}, {"column", column}} ||
                response.value("frequency_policy", "") != "exact_only" || response.value("physics_validated", true) ||
                response.at("offset") != offset)
            {
                throw std::runtime_error("수학 비교 응답의 원본, 채널 또는 검증 상태가 다릅니다.");
            }
            view->SetComparison(index, response);
        },
        [this](const Json& error)
        {
            m_browser->SetStatus("수학 비교를 표시할 수 없습니다: " + DiagnosticMessage(error));
        });
}
void ResultWorkspace::Conditions(int offset)
{
    if (m_page != 14 && m_page != 16)
    {
        return;
    }
    auto* view = ComparisonView();
    const auto descriptions = view->Descriptions();
    const int selected = view->Selected();
    if (selected <= 0 || static_cast<std::size_t>(selected) >= descriptions.size())
    {
        return;
    }
    const auto index = static_cast<std::size_t>(selected);
    const auto left = descriptions.front(), right = descriptions[index], order = view->PortOrder(index);
    const int row = view->Row(), column = view->Column(), total = m_conditions->ConditionTotal();
    if (offset < 0 || offset >= total)
    {
        return;
    }
    const auto generation = m_conditions->ConditionGeneration(), selection = m_selectionGeneration;
    Json leftPin{{"source", left.at("source")}, {"pin", left.at("pin")}},
        rightPin{{"source", right.at("source")}, {"pin", right.at("pin")}};
    if (view->MeasurementMode())
    {
        leftPin["record"] = left.value("measurement_ref", Json(nullptr));
        rightPin["record"] = right.value("measurement_ref", Json(nullptr));
    }
    m_conditions->ConditionsPending(true);
    Read(
        view->MeasurementMode() ? "measurement.conditions" : "result.conditions",
        {{"left", leftPin}, {"right", rightPin}, {"offset", offset}, {"limit", 32}},
        [this, view, index, left, right, order, row, column, generation, selection]()
        {
            return (m_page == 14 || m_page == 16) && ComparisonView() == view && m_selectionGeneration == selection &&
                   m_conditions->ConditionGeneration() == generation && view->Selected() == static_cast<int>(index) &&
                   !view->Descriptions().empty() && MeasurementUi::SameRecord(left, view->Descriptions().front()) &&
                   ComparisonCurrent(view, index, right, order, row, column);
        },
        [this, view, leftPin, rightPin, offset, total](const Json& response)
        {
            const auto& items = response.at("items");
            if (response.at("left") != leftPin || response.at("right") != rightPin || response.at("offset") != offset ||
                response.at("total") != total || !items.is_array() || items.empty() || items.size() > 32 ||
                offset + static_cast<int>(items.size()) > total)
            {
                throw std::runtime_error("조건 응답의 원본, 페이지 또는 항목 수가 요청과 다릅니다.");
            }
            const int end = offset + static_cast<int>(items.size());
            if (response.at("next_offset") != (end < total ? Json(end) : Json(nullptr)))
            {
                throw std::runtime_error("조건 페이지의 다음 위치가 실제 반환 범위와 다릅니다.");
            }
            m_conditions->SetConditionPage(response);
        },
        [this](const Json& error)
        {
            m_conditions->ConditionsPending(false);
            m_browser->SetStatus("조건 페이지를 읽지 못했습니다. 이전 페이지를 유지합니다: " +
                                 DiagnosticMessage(error));
        });
}

void ResultWorkspace::Markers(ResultCompareView* view, double frequency)
{
    const auto descriptions = view->Descriptions();
    const auto generation = ++m_markerGeneration;
    const int row = view->Row(), column = view->Column();
    for (std::size_t index = 0; index < descriptions.size(); ++index)
    {
        const auto description = descriptions[index], order = view->PortOrder(index);
        const int actualRow = index == 0         ? row
                              : order.is_array() ? order.at(static_cast<std::size_t>(row)).get<int>()
                                                 : 0;
        const int actualColumn = index == 0         ? column
                                 : order.is_array() ? order.at(static_cast<std::size_t>(column)).get<int>()
                                                    : 0;
        Json input{{"source", description.at("source")},
                   {"pin", description.at("pin")},
                   {"frequency_hz", frequency},
                   {"row", actualRow},
                   {"column", actualColumn}};
        Read(
            "result.marker", input,
            [this, view, index, description, order, row, column, generation]()
            {
                return generation == m_markerGeneration &&
                       ComparisonCurrent(view, index, description, order, row, column);
            },
            [this, view, index, description, frequency](const Json& response)
            {
                if (!ResultUi::Matches(response, description) ||
                    (response.value("found", false) && response.at("point").at("frequency_hz") != frequency))
                {
                    throw std::runtime_error("마커가 같은 원본의 정확한 주파수 표본이 아닙니다.");
                }
                view->SetMarker(index, response);
            },
            [this, view, index, description](const Json& error)
            {
                Json missing{{"source", description.at("source")},
                             {"pin", description.at("pin")},
                             {"found", false},
                             {"point", nullptr},
                             {"reason", DiagnosticMessage(error)}};
                view->SetMarker(index, missing);
            });
    }
}
void ResultWorkspace::Export()
{
    if (!m_description.is_object() || !m_available)
    {
        return;
    }
    const auto formats = m_description.value("available_exports", Json::array());
    wxArrayString labels;
    std::vector<std::string> keys;
    if (formats.is_array())
    {
        for (const auto& format : formats)
        {
            if (!format.is_string())
            {
                continue;
            }
            const auto key = format.get<std::string>();
            keys.push_back(key);
            labels.Add(Display(key == "touchstone" ? "Touchstone"
                               : key == "csv"      ? "CSV"
                               : key == "hdf5"     ? "HDF5"
                               : key == "source"   ? "보존 원문 바이트"
                                                   : key));
        }
    }
    if (keys.empty())
    {
        m_browser->SetStatus("선택한 원본은 사용 가능한 내보내기 형식을 제공하지 않습니다.");
        return;
    }
    const auto selection = m_selectionGeneration;
    const auto description = m_description;
    const std::weak_ptr<int> lifetime = m_lifetime;
    wxSingleChoiceDialog dialog(
        m_network, Display("원본 자료와 조건과 출처 파일을 함께 저장합니다. 과거 자료를 현재 설계에 등록하지 않습니다."),
        Display("보존 결과 내보내기"), labels);
    if (dialog.ShowModal() != wxID_OK || lifetime.expired())
    {
        return;
    }
    if (!m_available || selection != m_selectionGeneration || !ResultUi::Matches(description, m_description))
    {
        return;
    }
    auto input = Pinned();
    input["format"] = keys.at(static_cast<std::size_t>(dialog.GetSelection()));
    Read(
        "result.export", input,
        [this, selection]()
        {
            return selection == m_selectionGeneration;
        },
        [this](const Json& response)
        {
            if (!ResultUi::Matches(response, m_description))
            {
                throw std::runtime_error("내보내기 응답의 원본 또는 고정 해시가 선택과 다릅니다.");
            }
            if (onExportResult)
            {
                onExportResult(response);
            }
        });
}
