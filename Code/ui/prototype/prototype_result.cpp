#include "prototype_result.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <limits>
#include <stdexcept>
#include <utility>

using nlohmann::json;

namespace
{
bool hashMatchesFormat(const json& value)
{
    if (!value.is_string())
    {
        return false;
    }
    const auto& string = value.get_ref<const std::string&>();
    return string.size() == 64 && string.find_first_not_of("0123456789abcdef") == std::string::npos;
}
}

void PrototypeResult::setStatus(std::string status)
{
    status_ = std::move(status);
}

/** @brief 완료된 해석의 아티팩트만 사용한다. */
bool PrototypeResult::acceptLatest(const json& reply)
{
    if (reply.at("profile") != "rfad.solver-view/0.1")
    {
        throw std::runtime_error("지원하지 않는 완료 해석 응답입니다.");
    }
    pending_ = {};
    const auto& latest = reply.at("result");
    if (latest.is_null())
    {
        series_.reset();
        setStatus("완료된 해석 결과가 없습니다.");
        return false;
    }
    pending_.source = {{"kind", "solver"}, {"artifact_id", latest.at("artifact_id").get<std::string>()}};
    return true;
}

json PrototypeResult::descriptionInput() const
{
    return {{"source", pending_.source}};
}

/** @brief 결과, 입력 스냅샷, 현재 개정 및 pin이 맞을 때만 표본 조회를 시작한다. */
void PrototypeResult::acceptDescription(const json& reply, const std::string& project, const std::string& revision)
{
    const auto& descriptor = reply.at("descriptor");
    const auto& snapshot = descriptor.at("source_snapshot");
    const auto& pin = reply.at("pin");
    const auto source = reply.at("source_revision").at("id").get<std::string>();
    const auto count = descriptor.at("sample_count").get<std::size_t>();
    const auto& references = reply.at("source_refs");
    const bool validReferences = references.is_array() && std::all_of(references.begin(), references.end(),
        [](const json& item)
        {
            return item.is_string();
        });
    constexpr std::size_t maxSamples = 1001;
    if (reply.at("profile") != "rfad.result-view/0.1" || reply.at("source") != pending_.source ||
        reply.at("current_revision_id") != revision || descriptor.at("parameter_kind") != "S" ||
        snapshot.at("project_id") != project || snapshot.at("revision_id") != source ||
        !hashMatchesFormat(pin.at("identity_hash")) || !hashMatchesFormat(pin.at("dataset_sha256")) ||
        count == 0 || count > maxSamples || !validReferences)
    {
        throw std::runtime_error("해석 결과의 출처, 개정 또는 표본 범위가 올바르지 않습니다.");
    }
    pending_.label = reply.at("label").get<std::string>();
    pending_.revision = source;
    pending_.pin = pin;
    pending_.references = references;
    pending_.total = count;
    pending_.frequenciesGhz.reserve(count);
    pending_.magnitudeDb.reserve(count);
}

json PrototypeResult::pageInput() const
{
    return {{"source", pending_.source}, {"pin", pending_.pin}, {"row", 0}, {"column", 0},
        {"offset", pending_.frequenciesGhz.size()}, {"limit", pageLimit}};
}

/** @brief 누락 또는 무한 dB 표본의 구간을 끊고 모든 페이지가 맞을 때 장면을 교체한다. */
bool PrototypeResult::acceptPage(const json& reply)
{
    const auto& page = reply.at("page");
    const auto& samples = page.at("samples");
    const auto offset = pending_.frequenciesGhz.size();
    const auto& next = page.at("next_offset");
    if (reply.at("profile") != "rfad.page-view/0.1" || reply.at("source") != pending_.source ||
        reply.at("pin") != pending_.pin || page.at("parameter_kind") != "S" ||
        page.at("channel").at("row") != 0 || page.at("channel").at("column") != 0 ||
        page.at("offset") != offset || page.at("total") != pending_.total ||
        !samples.is_array() || samples.empty() || samples.size() > pageLimit || offset > pending_.total ||
        samples.size() > pending_.total - offset ||
        (next.is_null() ? offset + samples.size() != pending_.total
                        : next != offset + samples.size() || offset + samples.size() >= pending_.total))
    {
        throw std::runtime_error("해석 결과 페이지의 pin 또는 표본 범위가 올바르지 않습니다.");
    }
    for (const auto& sample : samples)
    {
        const double frequency = sample.at("frequency_hz").get<double>() / 1e9;
        if (sample.at("index") != pending_.frequenciesGhz.size() || !std::isfinite(frequency) || frequency <= 0.0 ||
            (!pending_.frequenciesGhz.empty() && frequency <= pending_.frequenciesGhz.back()))
        {
            throw std::runtime_error("해석 결과의 주파수 순서가 올바르지 않습니다.");
        }
        double value = std::numeric_limits<double>::quiet_NaN();
        if (sample.at("valid").get<bool>() && sample.at("magnitude_db_state") == "finite")
        {
            value = sample.at("magnitude_db").get<double>();
            if (!std::isfinite(value))
            {
                throw std::runtime_error("해석 결과의 유한 dB 표본을 읽을 수 없습니다.");
            }
        }
        pending_.frequenciesGhz.push_back(frequency);
        pending_.magnitudeDb.push_back(value);
    }
    if (!next.is_null())
    {
        return false;
    }
    std::printf("S11 display: artifact=%s revision=%s samples=%zu\n",
        pending_.source.at("artifact_id").get_ref<const std::string&>().c_str(),
        pending_.revision.c_str(), pending_.frequenciesGhz.size());
    series_ = std::move(pending_);
    status_.clear();
    return true;
}
