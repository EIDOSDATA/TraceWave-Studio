/** @file @brief 실제 Windows 표시 창에서 등록, 10회 단면 위치·주파수 변경, 복소 비교를 검증한다. */
#include "large_result_dialog.h"
#include "field_result_view.h"
#include "studio_support.h"
#include <cmath>
#include <fstream>
#include <stdexcept>
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/listctrl.h>
#include <wx/spinctrl.h>
#include <wx/weakref.h>

namespace
{
std::filesystem::path FileName(const Json& value)
{
    return std::filesystem::path(Display(value.get<std::string>()).ToStdWstring());
}

void Check(bool condition, const char* message)
{
    if (!condition)
    {
        throw std::runtime_error(message);
    }
}

void Mark(const Json& fixture, const char* phase)
{
    std::ofstream output(FileName(fixture.at("phases")), std::ios::app);
    output << phase << '\n';
    Check(output.good(), "대용량 결과의 시간 단계를 기록하지 못했습니다.");
}
}

void LargeResultDialog::StartSmoke(Json fixture)
{
    m_fixture = std::move(fixture);
    m_evidence = Json::object();
    m_smokeStep = 1;
}

void LargeResultDialog::SmokeTick()
{
    if (m_busy || m_copy.valid() || !m_job.empty())
    {
        return;
    }
    try
    {
        if (m_smokeStep == 1)
        {
            Status("동일한 필드 읽기 환경을 준비하고 있습니다.", true);
            m_smokeStep = 2;
            wxWeakRef<LargeResultDialog> weak(this);
            m_gateway("result.large.runtime", Json::object(), false, [weak](const Json& value)
            {
                if (weak)
                {
                    weak->m_evidence["runtime"] = value;
                    Mark(weak->m_fixture, "ready");
                    weak->m_baselineUntil = Clock::now() + std::chrono::milliseconds(1200);
                    weak->Status("대용량 결과 검증 자료를 준비했습니다.");
                }
            }, [weak](const Json& error) { if (weak) { weak->Error(error); } });
            return;
        }
        if (m_smokeStep == 2)
        {
            if (Clock::now() < m_baselineUntil)
            {
                return;
            }
            if (m_fixture.at("mode") == "import" || m_fixture.at("mode") == "receive")
            {
                Check(m_catalog.empty(), "새 시험 프로젝트에 기존 등록 자료가 있습니다.");
                Mark(m_fixture, "import-start");
                StartImport(FileName(m_fixture.at("field")), m_fixture.at("mode") == "receive" ? "package" : "field");
                m_smokeStep = 3;
            }
            else
            {
                m_smokeStep = 4;
            }
            return;
        }
        if (m_smokeStep == 3)
        {
            Check(m_catalog.size() == 1, "단일 필드 등록이 완료되지 않았습니다.");
            StartImport(FileName(m_fixture.at("traces")), m_fixture.at("mode") == "receive" ? "package" : "traces");
            m_smokeStep = 4;
            return;
        }
        if (m_smokeStep == 4)
        {
            Check(m_catalog.size() == 2 && m_records->GetItemCount() == 2,
                  "원문 두 종류를 실제 결과 목록에서 읽지 못했습니다.");
            m_evidence["records"] = m_catalog;
            for (std::size_t i = 0; i < m_catalog.size(); ++i)
            {
                const auto& item = m_catalog.at(i);
                Check(item.at("conditions") == Json({{"manufacturing", nullptr}, {"measurement", nullptr},
                                                       {"physics_validated", false}}),
                      "가져온 자료의 제작·측정 미정값이 다릅니다.");
                if (item.at("kind") == "field")
                {
                    Mark(m_fixture, "field-start");
                    Select(static_cast<int>(i));
                }
            }
            m_smokeStep = 5;
            return;
        }
        if (m_smokeStep == 5)
        {
            if (m_smokeSlices != 0)
            {
                const auto& slice = m_field->m_slice;
                Check(slice.is_object() && slice.at("values_ri").size() == 32 &&
                          slice.at("values_ri").at(0).size() == 32,
                      "실제 캔버스에 요청한 크기의 단면을 표시하지 못했습니다.");
                const auto index = m_smokeSlices - 1;
                const auto value = slice.at("values_ri").at(0).at(0);
                Check(value == Json::array({1000 * (index % 3) + index, 2 + index % 2}) &&
                          slice.at("frequency_hz") == (index % 2 == 0 ? 1e9 : 2e9) &&
                          slice.at("unit") == "미정",
                      "실제 단면의 복소값, 주파수 또는 단위 미정값이 다릅니다.");
                m_evidence["slices"].push_back({{"selection", slice.at("selection")}, {"value", value},
                                                 {"frequency", slice.at("frequency_hz")}});
            }
            if (m_smokeSlices == 10)
            {
                Mark(m_fixture, "curves-start");
                for (std::size_t i = 0; i < m_catalog.size(); ++i)
                {
                    if (m_catalog.at(i).at("kind") == "traces")
                    {
                        Select(static_cast<int>(i));
                    }
                }
                m_smokeStep = 6;
                return;
            }
            Check(m_field->m_frequency->GetCount() == 2, "두 주파수를 필드 View에서 선택할 수 없습니다.");
            const auto index = m_smokeSlices++;
            m_field->m_normal->SetSelection(2);
            m_field->m_component->SetSelection(index % 3);
            m_field->m_frequency->SetSelection(index % 2);
            m_field->RebuildPlane();
            m_field->m_planeIndex->SetValue(index + 1);
            m_field->m_uStart->SetValue(index);
            m_field->m_vStart->SetValue(index * 2);
            wxCommandEvent load(wxEVT_BUTTON, m_field->m_load->GetId());
            m_field->m_load->GetEventHandler()->ProcessEvent(load);
            return;
        }
        if (m_smokeStep == 6)
        {
            Check(m_curvePage.is_object() && m_curvePage.at("mode") == "overview" &&
                      m_curvePage.at("pages").size() == 8 && m_sources->GetItemCount() == 8,
                  "실제 복소 곡선 비교에서 전체 여덟 원본을 표시하지 못했습니다.");
            for (const auto& count : m_curvePage.at("counts"))
            {
                Check(count == 100000, "등록한 곡선의 원본 표본 수가 다릅니다.");
            }
            m_evidence["overview_counts"] = m_curvePage.at("counts");
            m_mode->SetSelection(1);
            m_metric->SetSelection(1);
            m_offset->SetValue(99999);
            ReadCurves();
            m_smokeStep = 7;
            return;
        }
        if (m_smokeStep == 7)
        {
            Check(m_curvePage.at("mode") == "exact" && m_curvePage.at("metric") == "imag",
                  "원본 허수부 조회 결과의 모드가 다릅니다.");
            unsigned number = 0;
            for (const auto& page : m_curvePage.at("pages"))
            {
                const auto& samples = page.at("samples");
                Check(samples.size() == 2 && samples.at(0).at("valid") == false &&
                          samples.at(0).at("imag").is_null() && samples.at(1).at("index") == 99999 &&
                          samples.at(1).at("imag") == -static_cast<double>(++number),
                      "마지막 복소값 또는 원본 결측 상태가 예상 기록과 다릅니다.");
            }
            m_evidence["tail"] = m_curvePage;
            if (m_fixture.contains("export"))
            {
                StartTransfer(FileName(m_fixture.at("export").at("traces")));
                m_smokeStep = 8;
                return;
            }
            SmokeFinish();
        }
        if (m_smokeStep == 8)
        {
            Check(std::filesystem::is_regular_file(FileName(m_fixture.at("export").at("traces"))),
                  "복소 곡선 이관 사본을 저장하지 못했습니다.");
            for (std::size_t index = 0; index < m_catalog.size(); ++index)
            {
                if (m_catalog.at(index).at("kind") == "field")
                {
                    Select(static_cast<int>(index));
                }
            }
            m_smokeStep = 9;
            return;
        }
        if (m_smokeStep == 9)
        {
            Check(m_record.at("kind") == "field", "필드 이관 전에 원본을 선택하지 못했습니다.");
            StartTransfer(FileName(m_fixture.at("export").at("field")));
            m_smokeStep = 10;
            return;
        }
        if (m_smokeStep == 10)
        {
            Check(std::filesystem::is_regular_file(FileName(m_fixture.at("export").at("field"))),
                  "필드 이관 사본을 저장하지 못했습니다.");
            SmokeFinish();
        }
    }
    catch (const std::exception& error)
    {
        SmokeFinish(error.what());
    }
}

void LargeResultDialog::SmokeFinish(const std::string& error)
{
    m_timer.Stop();
    m_evidence["passed"] = error.empty();
    m_evidence["error"] = error;
    Mark(m_fixture, "closed");
    std::ofstream output(FileName(m_fixture.at("evidence")), std::ios::binary);
    output << m_evidence.dump(2) << '\n';
    EndModal(error.empty() ? wxID_OK : wxID_CANCEL);
}
