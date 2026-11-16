/** @file @brief 플랫폼 로캘과 무관하게 주파수 접두어/유효 숫자만 표시한다. */
#include "frequency_display.h"
#include <algorithm>
#include <cmath>
#include <iomanip>
#include <limits>
#include <locale>
#include <sstream>
#include <stdexcept>

namespace
{
double Number(const Json& value)
{
    return value.is_number() ? value.get<double>() : std::numeric_limits<double>::quiet_NaN();
}
}

namespace StudioFrequency
{
Scale ForRange(double minHz, double maxHz, const std::string& requested)
{
    if (requested != "auto")
    {
        if (requested == "Hz")
        {
            return {"Hz", 1.0};
        }
        if (requested == "kHz")
        {
            return {"kHz", 1.0e3};
        }
        if (requested == "MHz")
        {
            return {"MHz", 1.0e6};
        }
        if (requested == "GHz")
        {
            return {"GHz", 1.0e9};
        }
        throw std::invalid_argument("지원하지 않는 주파수 표시 단위입니다.");
    }
    const double magnitude =
        std::max(std::isfinite(minHz) ? std::abs(minHz) : 0.0, std::isfinite(maxHz) ? std::abs(maxHz) : 0.0);
    if (magnitude >= 1.0e9)
    {
        return {"GHz", 1.0e9};
    }
    if (magnitude >= 1.0e6)
    {
        return {"MHz", 1.0e6};
    }
    if (magnitude >= 1.0e3)
    {
        return {"kHz", 1.0e3};
    }
    return {"Hz", 1.0};
}

Scale ForSamples(const Json& samples, const std::string& requested)
{
    double maximum = 0.0;
    if (samples.is_array())
    {
        for (const auto& sample : samples)
        {
            if (sample.is_object() && sample.contains("frequency_hz"))
            {
                const double value = Number(sample.at("frequency_hz"));
                if (std::isfinite(value))
                {
                    maximum = std::max(maximum, std::abs(value));
                }
            }
        }
    }
    return ForRange(0.0, maximum, requested);
}

Scale ForPage(const Json& page, const std::string& requested)
{
    return page.is_object() && page.contains("samples") ? ForSamples(page.at("samples"), requested)
                                                        : ForRange(0.0, 0.0, requested);
}

Scale ForDescriptor(const Json& descriptor, const std::string& requested)
{
    if (!descriptor.is_object())
    {
        return ForRange(0.0, 0.0, requested);
    }
    return ForRange(Number(descriptor.value("frequency_min_hz", Json(nullptr))),
                    Number(descriptor.value("frequency_max_hz", Json(nullptr))), requested);
}

std::string Value(const Json& frequencyHz, const Scale& scale, int precision)
{
    if (frequencyHz.is_null())
    {
        return "미정";
    }
    if (!frequencyHz.is_number())
    {
        return "표시 불가";
    }
    const double value = Number(frequencyHz);
    if (!std::isfinite(value))
    {
        return "유한값 없음";
    }
    if (!std::isfinite(scale.divisor) || scale.divisor <= 0.0)
    {
        throw std::invalid_argument("주파수 표시 배율이 올바르지 않습니다.");
    }
    if (value != 0.0 && value / scale.divisor == 0.0)
    {
        return "표시 범위 미만";
    }
    std::ostringstream stream;
    stream.imbue(std::locale::classic());
    stream << std::setprecision(std::clamp(precision, 1, 17))
           << (value == 0.0 ? 0.0L : static_cast<long double>(value) / static_cast<long double>(scale.divisor));
    return stream.str();
}

std::string WithUnit(const Json& frequencyHz, const std::string& requested)
{
    const double value = Number(frequencyHz);
    const auto scale = ForRange(value, value, requested);
    return Value(frequencyHz, scale) + (std::isfinite(value) ? " " + scale.unit : "");
}

std::string Range(const Json& minHz, const Json& maxHz, const std::string& requested)
{
    const auto scale = ForRange(Number(minHz), Number(maxHz), requested);
    return Value(minHz, scale) + " ~ " + Value(maxHz, scale) + " " + scale.unit;
}
}
