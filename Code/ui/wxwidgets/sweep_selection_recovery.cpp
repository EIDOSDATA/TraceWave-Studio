/** @file @brief GUI 복구 메타데이터만 사용자 설정에 저장하고 프로젝트 원본에는 쓰지 않는다. */
#include "sweep_selection_recovery.h"
#include "studio_support.h"
#include <wx/config.h>
#include <filesystem>
#include <iomanip>
#include <sstream>
#include <stdexcept>

namespace
{
/** @brief 같은 Windows 작업공간의 대소문자/구분자/점 경로 표기를 같은 복구 정체성으로 묶는다. */
std::string Identity(const std::string& workspace)
{
    auto canonical = std::filesystem::weakly_canonical(
        std::filesystem::absolute(std::filesystem::path(Display(workspace).ToStdWstring())));
    while (canonical.filename().empty() && canonical.has_relative_path())
    {
        canonical = canonical.parent_path();
    }
    wxString path(canonical.native());
    path.Replace("/", "\\");
    path.MakeLower();
    if (path.StartsWith("\\\\?\\unc\\"))
    {
        path = "\\\\" + path.Mid(8);
    }
    else if (path.StartsWith("\\\\?\\"))
    {
        path = path.Mid(4);
    }
    return Utf8(path);
}

/** @brief 고정 해시는 설정 키 길이만 줄이며 저장된 작업공간 원문을 별도로 대조한다. */
wxString Key(const std::string& workspace, const std::string& project)
{
    std::uint64_t hash = 14695981039346656037ULL;
    for (const unsigned char value : Identity(workspace))
    {
        hash ^= value;
        hash *= 1099511628211ULL;
    }
    std::ostringstream text;
    text << "/sweep_selection/" << std::hex << hash << "/" << project;
    return Display(text.str());
}
}

namespace SweepSelectionStore
{
std::shared_ptr<SweepSelectionRecovery> Read(const std::string& workspace, const std::string& project)
{
    wxConfig configuration("TraceWaveStudio", "TraceWave");
    wxString saved;
    auto result = std::shared_ptr<SweepSelectionRecovery>(new SweepSelectionRecovery());
    if (!configuration.Read(Key(workspace, project), &saved))
    {
        if (configuration.HasEntry(Key(workspace, project)))
        {
            throw std::runtime_error(
                "보존된 생성 요청의 GUI 복구 항목을 읽을 수 없습니다. 중복 생성 잠금을 유지합니다.");
        }
        return result;
    }
    const auto encoded = Utf8(saved);
    if (encoded.size() > 256 * 1024)
    {
        throw std::runtime_error("보존된 GUI 복구 항목이 허용 크기를 초과합니다. 중복 생성 잠금을 유지합니다.");
    }
    const Json data = Json::parse(encoded);
    if (data.at("schema") != "tracewave.gui-sweep-selection-recovery/0.1" || !data.at("workspace").is_string() ||
        Identity(data.at("workspace").get<std::string>()) != Identity(workspace) || data.at("project_id") != project ||
        !data.at("context").is_object() || !data.at("input").is_object() ||
        data.at("context").at("project_id") != project || !data.at("request_key").is_string() ||
        data.at("request_key").get<std::string>().empty() || !data.at("request_key_epoch").is_string() ||
        data.at("request_key_epoch").get<std::string>().empty())
    {
        throw std::runtime_error(
            "보존한 후보 채택 요청의 식별을 확인할 수 없습니다. 중복 생성을 막기 위해 잠금을 유지합니다.");
    }
    result->context = data.at("context");
    result->input = data.at("input");
    result->requestKey = data.at("request_key");
    result->epoch = data.at("request_key_epoch");
    result->uncertain = true;
    return result;
}

void Write(const std::string& workspace, const std::string& project, const SweepSelectionRecovery& recovery)
{
    const Json data{{"schema", "tracewave.gui-sweep-selection-recovery/0.1"},
                    {"workspace", workspace},
                    {"project_id", project},
                    {"context", recovery.context},
                    {"input", recovery.input},
                    {"request_key", recovery.requestKey},
                    {"request_key_epoch", recovery.epoch}};
    std::ostringstream encoded;
    encoded << data;
    const auto text = encoded.str();
    if (text.size() > 256 * 1024)
    {
        throw std::runtime_error("복구용 요청 정보가 상한을 넘었습니다. 생성 요청을 보내지 않았습니다.");
    }
    wxConfig configuration("TraceWaveStudio", "TraceWave");
    if (!configuration.Write(Key(workspace, project), Display(text)) || !configuration.Flush())
    {
        throw std::runtime_error("복구용 요청 키를 저장하지 못했습니다. 생성 요청을 보내지 않았습니다.");
    }
}

void Clear(const std::string& workspace, const std::string& project)
{
    wxConfig configuration("TraceWaveStudio", "TraceWave");
    if (configuration.HasEntry(Key(workspace, project)) &&
        (!configuration.DeleteEntry(Key(workspace, project), false) || !configuration.Flush()))
    {
        throw std::runtime_error(
            "확정된 요청의 GUI 복구 항목을 회수하지 못했습니다. 다음 진입 때 같은 영수증을 다시 확인합니다.");
    }
}
}
