/** @file @brief 동일 Windows 경로의 별칭으로 중복 출력 잠금을 우회하지 못하게 한다. */
#include "output_pending_store.h"
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

wxString Key(const std::string& workspace, const std::string& project)
{
    std::uint64_t hash = 14695981039346656037ULL;
    for (const unsigned char byte : Identity(workspace))
    {
        hash = (hash ^ byte) * 1099511628211ULL;
    }
    std::ostringstream text;
    text << "/output_request/" << std::hex << hash << "/" << project;
    return Display(text.str());
}

void Validate(const Json& request)
{
    if (!request.is_object() || !request.value("request_key", Json(nullptr)).is_string() ||
        request.at("request_key").get<std::string>().empty() ||
        !request.value("request_key_epoch", Json(nullptr)).is_string() ||
        request.at("request_key_epoch").get<std::string>().empty() ||
        !request.value("input", Json(nullptr)).is_object())
    {
        throw std::runtime_error("보존한 출력 요청의 정체성을 확인할 수 없습니다. 중복 생성을 잠갔습니다.");
    }
    const auto method = request.value("method", "");
    if (method != "snapshot.create" && method != "export.preview" && method != "export.build" &&
        method != "export.verify" && method != "package.build" && method != "archive.export.build")
    {
        throw std::runtime_error("보존한 출력 요청의 메서드를 지원하지 않습니다. 새 요청을 보내지 않습니다.");
    }
}
}

Json OutputPendingStore::Read(const std::string& workspace, const std::string& project)
{
    wxConfig configuration("TraceWaveStudio", "TraceWave");
    wxString text;
    if (!configuration.Read(Key(workspace, project), &text))
    {
        if (configuration.HasEntry(Key(workspace, project)))
        {
            throw std::runtime_error("출력 요청 복구 항목을 읽지 못했습니다.");
        }
        return nullptr;
    }
    const auto encoded = Utf8(text);
    if (encoded.size() > 256 * 1024)
    {
        throw std::runtime_error("출력 요청 복구 항목이 상한을 초과했습니다.");
    }
    const auto data = Json::parse(encoded);
    if (data.value("schema", "") != "tracewave.gui-output-request/0.1" || data.at("project_id") != project ||
        Identity(data.at("workspace")) != Identity(workspace))
    {
        throw std::runtime_error("출력 요청 복구의 작업 영역 또는 프로젝트가 다릅니다.");
    }
    Validate(data.at("request"));
    return data.at("request");
}

void OutputPendingStore::Write(const std::string& workspace, const std::string& project, const Json& request)
{
    Validate(request);
    const Json data{{"schema", "tracewave.gui-output-request/0.1"},
                    {"workspace", workspace},
                    {"project_id", project},
                    {"request", request}};
    const auto text = data.dump();
    if (text.size() > 256 * 1024)
    {
        throw std::runtime_error("출력 복구 요청의 저장 상한을 초과하여 전송하지 않았습니다.");
    }
    wxConfig configuration("TraceWaveStudio", "TraceWave");
    if (!configuration.Write(Key(workspace, project), Display(text)) || !configuration.Flush())
    {
        throw std::runtime_error("출력 요청 키를 보존하지 못하여 새 작업을 접수하지 않았습니다.");
    }
}

void OutputPendingStore::Clear(const std::string& workspace, const std::string& project)
{
    wxConfig configuration("TraceWaveStudio", "TraceWave");
    if (configuration.HasEntry(Key(workspace, project)) &&
        (!configuration.DeleteEntry(Key(workspace, project), false) || !configuration.Flush()))
    {
        throw std::runtime_error("확정된 출력 요청의 복구 항목을 회수하지 못했습니다. 같은 영수증을 다시 확인하세요.");
    }
}
