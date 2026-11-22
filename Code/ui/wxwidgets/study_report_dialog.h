/** @file @brief 수렴 연구의 설정과 판정 보고서를 읽기 전용으로 표시한다. */
#pragma once

class wxWindow;
class wxString;

/** @brief 사용자가 선택한 보고서의 사례와 판정 내용을 비교한다. */
void ShowStudyReport(wxWindow* parent);

/** @brief 파일 선택에서 얻은 보고서 경로를 같은 검토 창으로 연다. */
void ShowStudyReportFile(wxWindow* parent, const wxString& filename);
