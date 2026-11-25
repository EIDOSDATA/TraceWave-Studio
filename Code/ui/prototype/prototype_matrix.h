/** @file @brief 봉인된 다중 포트 S 행렬을 원래 축과 표본 상태로 표시한다. */
#pragma once

#include <nlohmann/json.hpp>

#include <atomic>
#include <filesystem>
#include <optional>
#include <string>
#include <vector>

namespace PrototypeMatrix
{
inline constexpr char profile[] = "rfad.openems.pcb-multiport/0.1";

enum class State { valid, missing, singular, illConditioned, unsupported, outsideValidity, nonfinite };
struct Complex
{
    double real = 0.0;
    double imag = 0.0;
};
struct Sample
{
    Complex value;
    State state;
};
struct Port
{
    std::string id;
    std::string name;
    std::string referencePlane;
};
struct Channel
{
    std::vector<Sample> samples;
    std::vector<double> db;
};
struct Matrix
{
    std::string artifact;
    std::string label;
    std::string revision;
    std::string sha256;
    std::string wave;
    std::string phasor;
    std::vector<Port> ports;
    std::vector<double> hertz;
    std::vector<double> ghz;
    std::vector<std::optional<Complex>> impedances;
    std::vector<Channel> channels;

    const Channel& channel(std::size_t row, std::size_t column) const { return channels[row * ports.size() + column]; }
};

const char* StateLabel(State state);
std::string ChannelName(std::size_t row, std::size_t column);

/** @brief 서비스가 가리키는 원문 파일에서 축, 스냅샷 및 복소 표본을 확인한다. */
Matrix Load(const std::filesystem::path& workspace, const nlohmann::json& result, const std::string& project,
    std::string label, const std::string& revision, const nlohmann::json& expectedSnapshot,
    const std::atomic<bool>& cancelled);
}
