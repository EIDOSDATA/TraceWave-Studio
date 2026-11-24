/** @file @brief 표시 문자열과 입력 교체는 SI 환산이나 기하 계산을 수행하지 않는다. */
#include "pcb_feature_model.h"
#include "output_model.h"
#include <map>
#include <stdexcept>

namespace
{
Json::json_pointer Pointer(const Json& path)
{
    if (!path.is_array() || path.empty() || path.size() > 16)
    {
        throw std::runtime_error("PCB 입력 필드 경로를 확인할 수 없습니다.");
    }
    std::string result;
    for (const auto& part : path)
    {
        std::string token;
        if (part.is_string())
        {
            token = part.get<std::string>();
        }
        else if (part.is_number_integer() && part >= 0 && part < 256)
        {
            token = part.dump();
        }
        else
        {
            throw std::runtime_error("PCB 입력 필드 위치가 유효하지 않습니다.");
        }
        if (token.empty() || token.find_first_of("~/") != std::string::npos)
        {
            throw std::runtime_error("PCB 입력 필드 이름이 유효하지 않습니다.");
        }
        result += "/" + token;
    }
    return Json::json_pointer(result);
}
}

std::string PcbFeatureUi::SectionLabel(const std::string& section)
{
    static const std::map<std::string, std::string> labels{{"overview", "PCB 형상과 제조 입력"},
                                                           {"cutout", "기판 내부 절삭"},
                                                           {"hole", "관통 홀과 슬롯"},
                                                           {"footprint", "풋프린트"},
                                                           {"artwork_layer", "제조 이미지 층"},
                                                           {"aperture", "마스크 및 페이스트 개구"},
                                                           {"keepout", "금지 영역"}};
    const auto found = labels.find(section);
    return found == labels.end() ? "PCB 객체" : found->second;
}

std::string PcbFeatureUi::Text(const Json& value, const std::string& missing)
{
    return OutputUi::Text(value, missing);
}

std::string PcbFeatureUi::Issues(const Json& issues)
{
    return OutputUi::Issues(issues);
}

std::string PcbFeatureUi::Conditions(const Json& context)
{
    const auto form = context.value("form", Json::object());
    const auto record = form.value("record", Json::object());
    std::string text = "선택 객체: " + Text(record.value("name", Json(nullptr))) + "\n";
    text += "종류: " + SectionLabel(form.value("section", "")) + "\n";
    text += record.value("origin", Json(nullptr)).is_null() ? "직접 입력한 기록입니다. 가져온 원본은 연결되지 않았습니다.\n"
                                                            : "가져온 원본의 참조가 있습니다. 고급 설정에서 원문을 확인하세요.\n";
    for (const auto& row : context.value("rows", Json::array()))
    {
        if (row.value("id", Json(nullptr)) == form.value("record_id", Json(nullptr)))
        {
            const auto owner = row.value("owner_footprint_id", Json(nullptr));
            for (const auto& candidate : context.value("rows", Json::array()))
            {
                if (!owner.is_null() && candidate.value("id", Json(nullptr)) == owner)
                {
                    text += "소유 풋프린트: " + Text(candidate.value("label", Json(nullptr))) + "\n";
                }
            }
        }
    }
    text += "\n미정 입력\n";
    bool missing = false;
    for (const auto& field : form.value("fields", Json::array()))
    {
        const auto value = Field(record, field.at("path"));
        if (value.is_null() || value == "unknown" ||
            (value.is_object() && value.contains("value_si") && value.at("value_si").is_null()))
        {
            text += "- " + field.value("label", "입력") + ": 미정\n";
            missing = true;
        }
    }
    if (!missing)
    {
        text += "표시된 단일 입력에는 미정값이 없습니다. 좌표와 참조 목록과 원문 조건은 별도 확인합니다.\n";
    }
    text += "\n출처\n";
    for (const auto& reference : record.value("source_refs", Json::array()))
    {
        text += "- " + Text(reference) + "\n";
    }
    if (record.value("source_refs", Json::array()).empty())
    {
        text += "추가 출처 식별자 미기록\n";
    }
    text += "\n제작과 측정 검증은 미확립 상태입니다.\n기계 제거, 제조 이미지와 물리 표면은 별도입니다. 마스크와 페이스트 "
            "개구로 물리 두께나 재료를 자동 확정하지 않습니다.\n새 PCB 기계 형상의 해석 적용은 별도 지원 범위 확인이 "
            "필요합니다.";
    return text;
}

void PcbFeatureUi::ReplaceField(Json& record, const Json& path, const Json& value)
{
    const auto pointer = Pointer(path);
    if (!record.contains(pointer))
    {
        throw std::runtime_error("현재 PCB 원문에 없는 입력 필드입니다. 화면을 다시 읽어 주세요.");
    }
    record[pointer] = value;
}

Json PcbFeatureUi::Field(const Json& record, const Json& path)
{
    return record.at(Pointer(path));
}

bool PcbFeatureUi::MatchesReview(const Json& review, const Json& input, const std::string& project)
{
    return review.is_object() && input.is_object() && review.value("project_id", "") == project &&
           review.value("source_revision_id", review.value("revision_id", "")) ==
               input.value("expected_revision", "") &&
           review.value("can_apply", false) && review.value("review_hash", Json(nullptr)).is_string() &&
           !review.at("review_hash").get<std::string>().empty();
}

bool PcbFeatureUi::MatchesApplied(const Json& response, const std::string& project)
{
    return response.is_object() && response.value("project_id", "") == project &&
           response.value("new_revision", Json(nullptr)).is_string() &&
           !response.at("new_revision").get<std::string>().empty();
}
