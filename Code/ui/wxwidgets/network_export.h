/** @file @brief 복소 교환 파일과 조건 sidecar를 함께 게시하는 native 저장 경계다. */
#pragma once
#include "studio_types.h"
#include <wx/string.h>

class wxWindow;

/** @brief 원문 바이트를 확인하고 workspace 밖의 새 파일 두 개를 함께 게시한다. */
void WriteNetworkExportFiles(const Json& result, const wxString& path, const wxString& workspace);
/** @brief 사용자가 선택한 새 경로에 저장하며 실패 또는 취소는 성공으로 표시하지 않는다. */
bool SaveNetworkExport(wxWindow* parent, const Json& result, const wxString& workspace);
