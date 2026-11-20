/** @file @brief 원본과 기존 수령 파일을 보존하는 단일 파일 게시 경계다. */
#pragma once
#include <string>
#include <wx/string.h>

/** @brief 확인한 바이트를 작업 영역 밖의 새 파일로 게시한다. */
void WriteExternalExportFile(const wxString& path, const wxString& workspace, const std::string& bytes);
