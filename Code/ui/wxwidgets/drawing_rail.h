/** @file @brief 기존 편집 명령 버튼에 DIP 기반 선 도형 아이콘을 표시한다. */
#pragma once
#include <vector>
class wxButton;
/** @brief 선택/선/원호/좌표/맞춤/삭제의 순서로 원본과 무관한 표시를 적용한다. */
void StyleDrawingRail(const std::vector<wxButton*>& buttons);
/** @brief 선택/선/원호의 현재 모드를 색만으로 구분하지 않고 굵기와 설명으로 표시한다. */
void SelectDrawingRail(const std::vector<wxButton*>& buttons, std::size_t selected);
