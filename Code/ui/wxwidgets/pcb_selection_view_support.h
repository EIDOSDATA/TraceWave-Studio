/** @file @brief 선택 화면에서만 사용하는 표시와 명시적 숫자 입력 변환이다. */
#pragma once

#include "studio_support.h"
#include <wx/textctrl.h>
#include <cmath>
#include <stdexcept>

namespace PcbView
{
/** @brief 미정값을 대표 숫자로 바꾸지 않고 빈칸으로 표현한다. */
inline wxString Number(const Json& value)
{
    if (!value.is_number())
    {
        return wxString();
    }
    return wxString::Format("%.17g", value.get<double>());
}

/** @brief 빈칸은 null, 명시적인 유한 숫자만 JSON 수치로 전달한다. */
inline Json Number(const wxString& text, const std::string& label)
{
    wxString trimmed = text;
    trimmed.Trim(true).Trim(false);
    if (trimmed.empty())
    {
        return nullptr;
    }
    double value = 0;
    if (!trimmed.ToDouble(&value) || !std::isfinite(value))
    {
        throw std::runtime_error(label + ": 숫자 또는 미정 빈칸을 입력하세요.");
    }
    return value;
}

/** @brief 표기용 텍스트만 반환하며 원문 JSON 편집기를 만들지 않는다. */
inline std::string Text(const Json& value, const std::string& field, const std::string& missing = "미정")
{
    if (!value.contains(field) || value.at(field).is_null())
    {
        return missing;
    }
    if (value.at(field).is_string())
    {
        return value.at(field).get<std::string>();
    }
    if (value.at(field).is_primitive())
    {
        return value.at(field).dump();
    }
    return missing;
}

/** @brief 이유를 사용자가 쓰지 않은 경우 임의 가정 문구를 만들지 않는다. */
inline std::string Reason(const wxString& value, const std::string& field)
{
    wxString trimmed = value;
    trimmed.Trim(true).Trim(false);
    if (trimmed.empty())
    {
        throw std::runtime_error(field + ": 선택 또는 수정 이유를 입력하세요.");
    }
    return Utf8(value);
}
}
