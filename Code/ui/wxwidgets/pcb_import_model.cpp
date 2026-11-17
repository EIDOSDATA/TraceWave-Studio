/** @file @brief 표시 복구 시 프로젝트와 원문 전송의 정체성을 보존한다. */
#include "pcb_import_model.h"

bool PcbImportUi::MatchesResponse(const Json& request, const Json& response, const std::string& project)
{
    if (!request.is_object() || !response.is_object() || !request.value("input", Json(nullptr)).is_object())
    {
        return false;
    }
    const auto input = request.at("input");
    const auto method = request.value("method", "");
    const auto upload = response.value("upload_id", Json(nullptr));
    if (!upload.is_string() || upload.get<std::string>().empty() ||
        (method != "pcb.import.begin" && upload != input.value("upload_id", Json(nullptr))))
    {
        return false;
    }
    if (method == "pcb.import.begin")
    {
        return response.value("status", Json(nullptr)) == "uploading";
    }
    if (method == "pcb.import.parse")
    {
        const auto job = response.value("job_id", Json(nullptr));
        return job.is_string() && !job.get<std::string>().empty();
    }
    if (method == "pcb.import.chunk")
    {
        const auto offset = input.value("offset", Json(nullptr));
        const auto received = response.value("received", Json(nullptr));
        return response.value("path", Json(nullptr)) == input.value("path", Json(nullptr)) &&
               offset.is_number_integer() && received.is_number_integer() && offset >= 0 &&
               offset <= 16 * 1024 * 1024 && received > offset && received <= 16 * 1024 * 1024 &&
               received.get<std::int64_t>() - offset.get<std::int64_t>() <= 256 * 1024;
    }
    if (method == "pcb.import.apply")
    {
        const auto revision = response.value("new_revision", Json(nullptr));
        return response.value("project_id", Json(nullptr)) == project && revision.is_string() &&
               !revision.get<std::string>().empty() && response.value("review_hash", Json(nullptr)).is_string() &&
               response.at("review_hash") == input.value("review_hash", Json(nullptr));
    }
    return method == "pcb.import.abandon" && response.value("status", Json(nullptr)) == "abandoned";
}
