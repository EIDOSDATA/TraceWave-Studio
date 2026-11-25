#include "prototype_result.h"

#include <algorithm>
#include <chrono>
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

PrototypeResult::PrototypeResult(const char* workspace)
{
    if (workspace)
    {
        const std::string_view path(workspace);
        workspace_ = std::filesystem::path(std::u8string(path.begin(), path.end()));
    }
}

/** @brief 결과 읽기를 중단하고 경로와 중단 신호가 작업보다 먼저 사라지지 않도록 한다. */
PrototypeResult::~PrototypeResult()
{
    cancelled_.store(true);
    if (matrixLoad_.valid())
    {
        matrixLoad_.wait();
    }
}

void PrototypeResult::setStatus(std::string status)
{
    status_ = std::move(status);
}

/** @brief 다음 목록 요청의 순번과 현재 목록의 식별자를 함께 유지한다. */
void PrototypeResult::requestHistory(int direction)
{
    requestedDirection_ = direction;
    if (direction < 0)
    {
        requestedOffset_ = historyOffset_ - historyLimit;
    }
    else if (direction > 0)
    {
        requestedOffset_ = historyOffset_ + history_.size();
    }
    else
    {
        requestedOffset_ = 0;
    }
    setHistoryStatus("완료된 해석 목록을 읽는 중");
}

json PrototypeResult::historyInput() const
{
    return {{"kind", "solver"}, {"revision_id", nullptr}, {"snapshot_id", nullptr}, {"study_id", nullptr},
        {"offset", requestedOffset_}, {"limit", historyLimit},
        {"catalog_hash", requestedDirection_ ? json(historyHash_) : json(nullptr)}};
}

/** @brief 목록이 바뀌거나 행의 출처가 명확하지 않으면 현재 조회 상태를 유지한다. */
void PrototypeResult::acceptHistory(const json& reply, const std::string& project)
{
    const auto& rows = reply.at("items");
    const auto& hash = reply.at("catalog_hash");
    const auto& next = reply.at("next_offset");
    const auto total = reply.at("total").get<std::size_t>();
    if (reply.at("profile") != "rfad.result-source-list/0.1" || reply.at("project_id") != project ||
        !reply.at("resolved_revision_id").is_null() || reply.at("offset") != requestedOffset_ ||
        !hashMatchesFormat(hash) || (requestedDirection_ && (hash != historyHash_ || total != historyTotal_)) ||
        !rows.is_array() || requestedOffset_ > total || rows.size() > historyLimit ||
        rows.size() != std::min(historyLimit, total - requestedOffset_) ||
        (next.is_null() ? requestedOffset_ + rows.size() != total
                        : next != requestedOffset_ + rows.size() || requestedOffset_ + rows.size() >= total))
    {
        throw std::runtime_error("해석 목록의 프로젝트, 식별자 또는 범위가 올바르지 않습니다.");
    }
    std::vector<SavedResult> page;
    page.reserve(rows.size());
    for (const auto& row : rows)
    {
        const auto& source = row.at("source");
        SavedResult item{source.at("artifact_id").get<std::string>(), row.at("label").get<std::string>(),
            row.at("source_revision_id").get<std::string>(), row.at("has_dataset").get<bool>()};
        if (source.at("kind") != "solver" || row.at("result_state") != "completed" ||
            item.artifact.empty() || item.label.empty() || item.revision.empty() ||
            std::ranges::find(page, item.artifact, &SavedResult::artifact) != page.end())
        {
            throw std::runtime_error("완료된 해석 목록의 출처가 올바르지 않습니다.");
        }
        page.push_back(std::move(item));
    }
    history_ = std::move(page);
    historyHash_ = hash.get<std::string>();
    historyOffset_ = requestedOffset_;
    historyTotal_ = total;
    historyIndex_ = requestedDirection_ < 0 && !history_.empty() ? history_.size() - 1 : 0;
    setHistoryStatus(history_.empty() ? "완료된 해석 결과가 없습니다." : "");
}

void PrototypeResult::setHistoryStatus(std::string status)
{
    historyStatus_ = std::move(status);
}

bool PrototypeResult::canBrowseHistory(int direction) const
{
    if (!historyChoice())
    {
        return false;
    }
    const auto current = historyOffset_ + historyIndex_;
    return direction < 0 ? current > 0 : current + 1 < historyTotal_;
}

/** @brief 인접 항목이 현재 페이지에 없으면 동일한 해시로 다음 페이지를 요청한다. */
bool PrototypeResult::browseHistory(int direction)
{
    if (!canBrowseHistory(direction))
    {
        return false;
    }
    if ((direction < 0 && historyIndex_ == 0) ||
        (direction > 0 && historyIndex_ + 1 == history_.size()))
    {
        requestHistory(direction);
        return true;
    }
    historyIndex_ = direction < 0 ? historyIndex_ - 1 : historyIndex_ + 1;
    return false;
}

const PrototypeResult::SavedResult* PrototypeResult::historyChoice() const
{
    return history_.empty() ? nullptr : &history_[historyIndex_];
}

/** @brief 완료된 해석의 아티팩트만 사용한다. */
PrototypeResult::Read PrototypeResult::acceptLatest(const json& reply)
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
        matrix_.reset();
        setStatus("완료된 해석 결과가 없습니다.");
        return Read::none;
    }
    const auto artifact = latest.at("artifact_id").get<std::string>();
    if (latest.value("profile", "") == PrototypeMatrix::profile)
    {
        selectMatrix(artifact, {}, latest.at("snapshot"), latest.at("normalized_result"));
        return Read::matrix;
    }
    selectArtifact(artifact);
    return Read::trace;
}

void PrototypeResult::selectMatrix(const std::string& artifact, const std::string& revision,
    const json& snapshot, const json& reference, const std::string& label)
{
    selectArtifact(artifact, revision);
    pending_.label = label;
    expectedSnapshot_ = snapshot;
    expectedReference_ = reference;
}

json PrototypeResult::artifactInput() const
{
    return {{"artifact_id", pending_.source.at("artifact_id")}, {"selection", "normalized"}};
}

/** @brief 완료 기록과 파일 참조를 대조하고 플랫폼 이벤트 처리와 분리해 읽는다. */
void PrototypeResult::startMatrix(const json& reply, const std::string& project)
{
    if (reply.at("artifact_id") != pending_.source.at("artifact_id") ||
        reply.at("metadata").at("profile") != PrototypeMatrix::profile)
    {
        throw std::runtime_error("이 해석의 결과 형식은 현재 화면에 표시할 수 없습니다.");
    }
    if (!expectedReference_.is_null())
    {
        const auto& file = reply.at("files").at(0);
        if (file.at("uri") != expectedReference_.at("uri") || file.at("sha256") != expectedReference_.at("sha256") ||
            file.at("bytes") != expectedReference_.at("bytes"))
        {
            throw std::runtime_error("완료 기록과 다중 포트 원문 참조가 다릅니다.");
        }
    }
    setStatus("봉인된 다중 포트 S 행렬을 읽는 중");
    matrixLoad_ = std::async(std::launch::async, [this, reply, project, label = pending_.label,
        revision = pending_.revision, snapshot = expectedSnapshot_]()
    {
        return PrototypeMatrix::Load(workspace_, reply, project, label, revision, snapshot, cancelled_);
    });
}

bool PrototypeResult::pollMatrix()
{
    if (matrixLoad_.wait_for(std::chrono::seconds(0)) != std::future_status::ready)
    {
        return false;
    }
    auto matrix = matrixLoad_.get();
    std::printf("S matrix display: artifact=%s revision=%s ports=%zu samples=%zu\n",
        matrix.artifact.c_str(), matrix.revision.c_str(), matrix.ports.size(), matrix.hertz.size());
    matrix_ = std::move(matrix);
    series_.reset();
    status_.clear();
    return true;
}

void PrototypeResult::selectArtifact(const std::string& artifact, const std::string& revision)
{
    pending_ = {};
    pending_.source = {{"kind", "solver"}, {"artifact_id", artifact}};
    pending_.revision = revision;
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
        (!pending_.revision.empty() && pending_.revision != source) ||
        !hashMatchesFormat(pin.at("identity_hash")) || !hashMatchesFormat(pin.at("dataset_sha256")) ||
        count == 0 || count > maxSamples || !validReferences)
    {
        throw std::runtime_error("해석 결과의 출처, 개정 또는 표본 범위가 올바르지 않습니다.");
    }
    pending_.label = reply.at("label").get<std::string>();
    pending_.revision = source;
    pending_.pin = pin;
    pending_.references = references;
    for (const auto& format : reply.value("available_exports", json::array()))
    {
        if (format == "csv" || format == "touchstone" || format == "hdf5" || format == "source")
        {
            pending_.exportFormats.push_back(format.get<std::string>());
        }
    }
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
    matrix_.reset();
    status_.clear();
    return true;
}
