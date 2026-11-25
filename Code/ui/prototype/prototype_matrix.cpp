#include "prototype_matrix.h"

#include "../wxwidgets/display_mesh.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <string_view>
#include <utility>

namespace PrototypeMatrix
{
namespace
{
using nlohmann::json;
using DisplayMesh::Require;
constexpr std::array<std::string_view, 7> states =
{
    "valid", "missing", "singular", "ill_conditioned", "unsupported", "outside_validity", "nonfinite"
};

State ParseState(const json& value)
{
    const auto found = std::ranges::find(states, value.get_ref<const std::string&>());
    Require(found != states.end(), "지원하지 않는 다중 포트 표본 상태입니다.");
    return static_cast<State>(found - states.begin());
}

double Number(const json& value)
{
    Require(value.is_number(), "다중 포트 표본에 숫자가 필요합니다.");
    const auto number = value.get<double>();
    Require(std::isfinite(number), "유한한 다중 포트 표본이 필요합니다.");
    return number;
}

Complex ReadComplex(const json& pair)
{
    Require(pair.is_array() && pair.size() == 2, "복소 표본의 실수부와 허수부가 필요합니다.");
    return {Number(pair[0]), Number(pair[1])};
}

bool SizeIs(const json& values, std::size_t count)
{
    return values.is_array() && values.size() == count;
}

bool Uuid(std::string_view value)
{
    if (value.size() != 36)
    {
        return false;
    }
    for (std::size_t index = 0; index < value.size(); ++index)
    {
        if (index == 8 || index == 13 || index == 18 || index == 23)
        {
            if (value[index] != '-')
            {
                return false;
            }
        }
        else if (std::string_view("0123456789abcdef").find(value[index]) == std::string_view::npos)
        {
            return false;
        }
    }
    return true;
}

std::string TextOrEmpty(const json& value)
{
    return value.is_null() ? std::string{} : value.get<std::string>();
}

double DisplayDb(const Sample& sample)
{
    if (sample.state == State::valid)
    {
        const auto modulus = std::hypot(sample.value.real, sample.value.imag);
        if (std::isfinite(modulus) && modulus > 0.0)
        {
            return 20.0 * std::log10(modulus);
        }
    }
    return std::numeric_limits<double>::quiet_NaN();
}
}

const char* StateLabel(State state)
{
    switch (state)
    {
        case State::valid: return "유효";
        case State::missing: return "미기록";
        case State::singular: return "특이";
        case State::illConditioned: return "조건 불량";
        case State::unsupported: return "지원 범위 밖";
        case State::outsideValidity: return "유효 범위 밖";
        case State::nonfinite: return "비유한";
    }
    return "미정";
}

std::string ChannelName(std::size_t row, std::size_t column)
{
    const auto out = std::to_string(row + 1);
    const auto in = std::to_string(column + 1);
    return row < 9 && column < 9 ? "S" + out + in : "S(" + out + "," + in + ")";
}

Matrix Load(const std::filesystem::path& workspace, const json& result, const std::string& project,
    std::string label, const std::string& revision, const json& expectedSnapshot, const std::atomic<bool>& cancelled)
{
    const auto& files = result.at("files");
    Require(SizeIs(files, 1), "정규화한 다중 포트 원문이 하나 있어야 합니다.");
    const auto& artifact = files.front();
    const auto& uri = artifact.at("uri").get_ref<const std::string&>();
    constexpr std::string_view prefix("solver-artifacts/");
    constexpr std::string_view suffix("/normalized.json");
    const std::string_view relative(uri);
    Require(artifact.at("role") == "normalized_result" && artifact.at("media_type") == "application/json" &&
        relative.size() == prefix.size() + 36 + suffix.size() && relative.starts_with(prefix) &&
        relative.ends_with(suffix) && Uuid(relative.substr(prefix.size(), 36)),
        "다중 포트 정규 원문의 참조 경로가 올바르지 않습니다.");

    const auto record = json::parse(DisplayMesh::ReadVerifiedArtifact(workspace, artifact, &cancelled));
    const auto& snapshot = record.at("snapshot");
    const auto& data = record.at("network");
    const auto& provenance = data.at("provenance");
    const auto& metadata = result.at("metadata");
    const auto& revisionId = snapshot.at("revision_id").get_ref<const std::string&>();
    Require(record.at("schema") == profile && metadata.at("profile") == profile &&
        record.at("prepared_plan_id") == result.at("prepared_plan_id") &&
        snapshot.at("project_id") == project && Uuid(revisionId) &&
        (revision.empty() || revisionId == revision) && (expectedSnapshot.is_null() || snapshot == expectedSnapshot) &&
        data.at("schema") == "rfad.network-data/0.1" && data.at("parameter_kind") == "S" && data.at("unit") == "1" &&
        provenance.at("snapshot") == snapshot && provenance.at("source_sha256") == snapshot.at("content_hash"),
        "다중 포트 결과의 스냅샷 또는 자료 형식이 다릅니다.");

    const auto& portIds = data.at("port_ids");
    const auto& names = data.at("port_names");
    const auto& planes = data.at("reference_planes");
    const auto& axis = data.at("frequency_hz");
    const auto ports = portIds.size();
    const auto count = axis.size();
    Require(portIds.is_array() && ports >= 2 && ports <= 12 && metadata.at("port_count") == ports &&
        axis.is_array() && count >= 1 && count <= 1001 && metadata.at("sample_count") == count &&
        SizeIs(names, ports) && SizeIs(planes, ports), "다중 포트 결과의 축 크기가 게시 기록과 다릅니다.");

    Matrix matrix;
    matrix.artifact = result.at("artifact_id").get<std::string>();
    matrix.label = label.empty() ? "완료된 다중 포트 해석" : std::move(label);
    matrix.revision = revisionId;
    matrix.sha256 = artifact.at("sha256").get<std::string>();
    matrix.wave = data.at("wave_definition").get<std::string>();
    matrix.phasor = data.at("phasor_convention").get<std::string>();
    for (std::size_t index = 0; index < ports; ++index)
    {
        const auto id = portIds[index].get<std::string>();
        Require(Uuid(id) && std::ranges::find(matrix.ports, id, &Port::id) == matrix.ports.end(),
            "다중 포트 식별자가 올바르지 않거나 중복되었습니다.");
        matrix.ports.push_back({id, TextOrEmpty(names[index]), TextOrEmpty(planes[index])});
    }

    const auto& values = data.at("values_ri");
    const auto& mask = data.at("valid_mask");
    const auto& status = data.at("sample_status");
    const auto& impedances = data.at("z0_ohm");
    Require(SizeIs(values, count) && SizeIs(mask, count) && SizeIs(status, count) &&
        (impedances.is_null() || SizeIs(impedances, count)), "다중 포트 원문의 주파수 축 길이가 다릅니다.");
    matrix.channels.resize(ports * ports);
    matrix.hertz.reserve(count);
    matrix.ghz.reserve(count);
    matrix.impedances.reserve(count * ports);
    for (auto& channel : matrix.channels)
    {
        channel.samples.reserve(count);
        channel.db.reserve(count);
    }

    double previous = -1.0;
    for (std::size_t index = 0; index < count; ++index)
    {
        DisplayMesh::CheckCancelled(&cancelled);
        const auto hz = Number(axis[index]);
        Require(hz >= 0.0 && hz > previous, "다중 포트 주파수는 중복 없이 증가해야 합니다.");
        previous = hz;
        matrix.hertz.push_back(hz);
        matrix.ghz.push_back(hz / 1e9);
        Require(SizeIs(values[index], ports) && SizeIs(mask[index], ports) && SizeIs(status[index], ports) &&
            (impedances.is_null() || SizeIs(impedances[index], ports)), "다중 포트 원문의 수신 축 길이가 다릅니다.");
        for (std::size_t row = 0; row < ports; ++row)
        {
            const auto& z = impedances.is_null() ? impedances : impedances[index][row];
            matrix.impedances.push_back(z.is_null() ? std::nullopt : std::optional<Complex>(ReadComplex(z)));
            Require(SizeIs(values[index][row], ports) && SizeIs(mask[index][row], ports) &&
                SizeIs(status[index][row], ports), "다중 포트 원문의 입사 축 길이가 다릅니다.");
            for (std::size_t column = 0; column < ports; ++column)
            {
                const auto pointState = ParseState(status[index][row][column]);
                const auto& valid = mask[index][row][column];
                const auto& pair = values[index][row][column];
                Require(valid.is_boolean() && valid == (pointState == State::valid) &&
                    (pointState != State::valid || !pair.is_null()), "복소 표본과 유효 상태가 다릅니다.");
                const Sample sample{pair.is_null() ? Complex{} : ReadComplex(pair), pointState};
                auto& channel = matrix.channels[row * ports + column];
                channel.samples.push_back(sample);
                channel.db.push_back(DisplayDb(sample));
            }
        }
    }
    return matrix;
}
}
