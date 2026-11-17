/** @file @brief 같은 Windows 작업공간의 다른 표기로 중복 적용 잠금을 우회하지 못하게 한다. */
#include "reviewed_request_store.h"
#include "studio_support.h"
#include <wx/config.h>
#include <filesystem>
#include <iomanip>
#include <sstream>
#include <stdexcept>

namespace
{
std::string Identity(const std::string& workspace)
{
    auto path = std::filesystem::weakly_canonical(
        std::filesystem::absolute(std::filesystem::path(Display(workspace).ToStdWstring())));
    while (path.filename().empty() && path.has_relative_path())
    {
        path = path.parent_path();
    }
    wxString value(path.native());
    value.Replace("/", "\\");
    value.MakeLower();
    if (value.StartsWith("\\\\?\\unc\\"))
    {
        value = "\\\\" + value.Mid(8);
    }
    else if (value.StartsWith("\\\\?\\"))
    {
        value = value.Mid(4);
    }
    return Utf8(value);
}

wxString Key(const std::string& scope, const std::string& workspace, const std::string& project)
{
    if (scope.empty() || scope.find_first_not_of("abcdefghijklmnopqrstuvwxyz_") != std::string::npos)
    {
        throw std::runtime_error("편집 요청 복구의 기능 구분을 확인할 수 없습니다.");
    }
    std::uint64_t hash = 14695981039346656037ULL;
    for (const unsigned char byte : Identity(workspace))
    {
        hash = (hash ^ byte) * 1099511628211ULL;
    }
    std::ostringstream text;
    text << "/reviewed_request/" << scope << "/" << std::hex << hash << "/" << project;
    return Display(text.str());
}

void Validate(const Json& request, const std::set<std::string>& methods)
{
    if (!request.is_object() || !request.value("request_key", Json(nullptr)).is_string() ||
        request.at("request_key").get<std::string>().empty() ||
        !request.value("request_key_epoch", Json(nullptr)).is_string() ||
        request.at("request_key_epoch").get<std::string>().empty() ||
        !request.value("input", Json(nullptr)).is_object() || methods.count(request.value("method", "")) == 0)
    {
        throw std::runtime_error("보존한 편집 요청을 확인할 수 없습니다. 중복 적용을 잠갔습니다.");
    }
}
}

Json ReviewedRequestStore::Read(const std::string& scope, const std::string& workspace, const std::string& project,
                                const std::set<std::string>& methods)
{
    wxConfig configuration("TraceWaveStudio", "TraceWave");
    const auto key = Key(scope, workspace, project);
    wxString text;
    if (!configuration.Read(key, &text))
    {
        if (configuration.HasEntry(key))
        {
            throw std::runtime_error("편집 요청 복구 항목을 읽지 못했습니다.");
        }
        return nullptr;
    }
    const auto encoded = Utf8(text);
    if (encoded.size() > (scope == "pcb_import" ? 512U : 256U) * 1024U)
    {
        throw std::runtime_error("편집 요청 복구 항목이 상한을 초과했습니다.");
    }
    const auto data = Json::parse(encoded);
    if (data.value("schema", "") != "tracewave.gui-reviewed-request/0.1" || data.at("scope") != scope ||
        data.at("project_id") != project || Identity(data.at("workspace")) != Identity(workspace))
    {
        throw std::runtime_error("편집 요청 복구의 작업공간 또는 프로젝트가 다릅니다.");
    }
    Validate(data.at("request"), methods);
    return data.at("request");
}

void ReviewedRequestStore::Write(const std::string& scope, const std::string& workspace, const std::string& project,
                                 const std::set<std::string>& methods, const Json& request)
{
    Validate(request, methods);
    const Json data{{"schema", "tracewave.gui-reviewed-request/0.1"},
                    {"scope", scope},
                    {"workspace", workspace},
                    {"project_id", project},
                    {"request", request}};
    const auto text = data.dump();
    if (text.size() > (scope == "pcb_import" ? 512U : 256U) * 1024U)
    {
        throw std::runtime_error("편집 복구 요청의 저장 상한을 초과하여 전송하지 않았습니다.");
    }
    wxConfig configuration("TraceWaveStudio", "TraceWave");
    if (!configuration.Write(Key(scope, workspace, project), Display(text)) || !configuration.Flush())
    {
        throw std::runtime_error("편집 요청 키를 보존하지 못하여 적용하지 않았습니다.");
    }
}

void ReviewedRequestStore::Clear(const std::string& scope, const std::string& workspace, const std::string& project)
{
    wxConfig configuration("TraceWaveStudio", "TraceWave");
    const auto key = Key(scope, workspace, project);
    if (configuration.HasEntry(key) && (!configuration.DeleteEntry(key, false) || !configuration.Flush()))
    {
        throw std::runtime_error("확정한 편집 요청의 복구 항목을 회수하지 못했습니다. 같은 영수증을 다시 확인하세요.");
    }
}
