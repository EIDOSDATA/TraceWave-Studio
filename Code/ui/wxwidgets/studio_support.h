/** @file @brief 주 창의 문자열 및 플랫폼 식별자 변환 경계다. */
#pragma once
#include "studio_types.h"
#include <wx/string.h>
#include <string>

extern int ExitCode;
/** @brief 화면 문자열을 UTF-8로 변환한다. */
std::string Utf8(const wxString& text);
/** @brief UTF-8 문자열을 화면 문자열로 변환한다. */
wxString Display(const std::string& text);
/** @brief 공통 진단의 표시 문구를 구한다. */
std::string DiagnosticMessage(const Json& diagnostic);
/** @brief 변경 요청의 고유 식별자를 만든다. */
std::string Uuid();
