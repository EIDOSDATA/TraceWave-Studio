/** @file @brief 출처 서비스 응답 전체를 검증한 뒤 읽기 전용 모델로 올린다. */
#include "prototype_evidence.h"

#include <stdexcept>
#include <utility>

PrototypeEvidence PrototypeEvidence::read(const nlohmann::json& reply)
{
    PrototypeEvidence model;
    const auto& records = reply.at("records");
    const auto& history = reply.at("history");
    const auto& context = reply.at("history_context");
    if (!records.is_array() || !history.is_array() || !context.is_array() || history.size() != context.size() ||
        !reply.at("history_total").is_number_unsigned() || !reply.at("redo_count").is_number_unsigned())
    {
        throw std::runtime_error("출처 또는 변경 이력 목록의 형식이 올바르지 않습니다.");
    }
    model.changeCount = reply.at("history_total").get<std::size_t>();
    model.redoCount = reply.at("redo_count").get<std::size_t>();
    if (model.changeCount < history.size())
    {
        throw std::runtime_error("변경 이력의 전체 항목 수가 올바르지 않습니다.");
    }
    for (const auto& entry : records)
    {
        Record record{entry.at("label").get<std::string>(), entry.at("source").get<std::string>(),
            entry.at("assumptions").get<std::string>(), {}};
        const auto& values = entry.at("values");
        if (!values.is_array())
        {
            throw std::runtime_error("출처 값의 목록 형식이 올바르지 않습니다.");
        }
        for (const auto& row : values)
        {
            if (!row.is_array() || row.size() != 4)
            {
                throw std::runtime_error("출처 값에 네 개의 열이 필요합니다.");
            }
            record.values.push_back(row.get<std::array<std::string, 4>>());
        }
        model.records.push_back(std::move(record));
    }
    for (std::size_t index = 0; index < history.size(); ++index)
    {
        const auto& row = history.at(index);
        if (!row.is_array() || row.size() != 4)
        {
            throw std::runtime_error("변경 이력에 이전 개정, 적용 개정, 명령과 대상이 필요합니다.");
        }
        const auto& item = context.at(index);
        auto target = item.value("name", std::string{});
        if (target.empty())
        {
            target = row.at(3).get<std::string>();
        }
        model.changes.push_back({row.at(0).get<std::string>(), row.at(1).get<std::string>(), row.at(2).get<std::string>(),
            std::move(target), item.at("target_id").get<std::string>(), item.at("timestamp").get<std::string>(),
            item.at("reason").get<std::string>()});
    }
    return model;
}
