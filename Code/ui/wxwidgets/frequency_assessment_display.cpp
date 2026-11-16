/** @file @brief 평가 당시 전체 표본 범위만 사용하여 페이지 사이의 주파수 단위를 유지한다. */
#include "frequency_display.h"
#include <cmath>

namespace
{
/** @brief 명시된 유한 범위만 표시 배율로 읽으며 원문 표현식을 해석하지 않는다. */
bool KnownRange(const Json& minimum, const Json& maximum, const std::string& requested, StudioFrequency::Scale& scale)
{
    if (!minimum.is_number() || !maximum.is_number())
    {
        return false;
    }
    const double low = minimum.get<double>();
    const double high = maximum.get<double>();
    if (!std::isfinite(low) || !std::isfinite(high) || low < 0.0 || high < low)
    {
        return false;
    }
    scale = StudioFrequency::ForRange(low, high, requested);
    return true;
}
}

namespace StudioFrequency
{
bool AssessmentMatchesDataset(const Json& assessment, const Json& selection)
{
    const auto artifactHash = [](const Json& value, const char* parent) -> std::string
    {
        if (!value.is_object() || !value.contains(parent) || !value.at(parent).is_object())
        {
            return "";
        }
        const auto& container = value.at(parent);
        if (!container.contains("dataset") || !container.at("dataset").is_object())
        {
            return "";
        }
        const auto& dataset = container.at("dataset");
        return dataset.contains("sha256") && dataset.at("sha256").is_string() ? dataset.at("sha256").get<std::string>()
                                                                              : "";
    };
    const auto expected = artifactHash(assessment, "evidence");
    return !expected.empty() && expected == artifactHash(selection, "entry");
}

Scale ForAssessment(const Json& assessment, const Json& descriptor, const std::string& requested)
{
    Scale scale;
    if (assessment.is_object())
    {
        if (KnownRange(assessment.value("frequency_min_hz", Json(nullptr)),
                       assessment.value("frequency_max_hz", Json(nullptr)), requested, scale))
        {
            return scale;
        }
        const auto evidence = assessment.find("evidence");
        if (evidence != assessment.end() && evidence->is_object())
        {
            const auto target = evidence->find("target_original");
            if (target != evidence->end() && target->is_object())
            {
                const auto band = target->find("band");
                if (band != target->end() && band->is_object())
                {
                    const auto start = band->find("start");
                    const auto end = band->find("end");
                    if (start != band->end() && end != band->end() && start->is_object() && end->is_object() &&
                        KnownRange(start->value("value_si", Json(nullptr)), end->value("value_si", Json(nullptr)),
                                   requested, scale))
                    {
                        return scale;
                    }
                }
            }
        }
    }
    return ForDescriptor(descriptor, requested);
}
}
