/** @file @brief 고정된 출력 검토/파일/검수 기록을 읽는 native 대화상자이다. */
#pragma once
#include "studio_types.h"
#include <wx/dialog.h>

class OutputRecordDialog final : public wxDialog
{
public:
    /** @brief review=true이면 검토 범위만 확인하며 파일 생성은 호출자의 명시 동작이다. */
    OutputRecordDialog(wxWindow* parent, const Json& record, bool review);
};
