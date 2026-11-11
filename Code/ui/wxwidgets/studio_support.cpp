/** @file @brief 주 창의 플랫폼/문자열 경계 구현이다. */
#include "studio_support.h"
#include <objbase.h>
#include <cstdio>
#include <stdexcept>

int ExitCode = 0;

/** @brief JSON과 화면 사이의 문자열을 명시적 UTF-8로 변환한다. */
std::string Utf8(const wxString& text)
{
    const wxScopedCharBuffer buffer = text.utf8_str();
    return std::string(buffer.data(), buffer.length());
}

/** @brief UTF-8 문자열을 손실 없이 wxString으로 변환한다. */
wxString Display(const std::string& text)
{
    return wxString::FromUTF8(text.data(), text.size());
}

/** @brief 공통 진단 계약의 한국어 본문을 읽고 이전 메시지 형식을 보조한다. */
std::string DiagnosticMessage(const Json& diagnostic)
{
    return diagnostic.value("message_ko", diagnostic.value("message", "입력을 확인하세요."));
}

/** @brief 서버가 요구하는 정규 소문자 UUID를 생성한다. */
std::string Uuid()
{
    GUID identifier{};
    if (FAILED(CoCreateGuid(&identifier)))
    {
        throw std::runtime_error("UUID creation failed");
    }
    char buffer[37]{};
    std::snprintf(buffer, sizeof(buffer), "%08lx-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x",
                  static_cast<unsigned long>(identifier.Data1), identifier.Data2, identifier.Data3, identifier.Data4[0],
                  identifier.Data4[1], identifier.Data4[2], identifier.Data4[3], identifier.Data4[4],
                  identifier.Data4[5], identifier.Data4[6], identifier.Data4[7]);
    return buffer;
}
