/** @file @brief 원본 프로젝트와 분리된 GUI 요청 영수증 복구 항목을 보존한다. */
#pragma once
#include "sweep_selection_dialog.h"

namespace SweepSelectionStore
{
/** @brief 다른 작업공간의 같은 프로젝트 식별자가 섞이지 않도록 원문 경로도 대조한다. */
std::shared_ptr<SweepSelectionRecovery> Read(const std::string& workspace, const std::string& project);
/** @brief 요청을 보내기 전에 기존 ledger 키를 저장하며 저장 실패 시 예외로 막는다. */
void Write(const std::string& workspace, const std::string& project, const SweepSelectionRecovery& recovery);
/** @brief 권위 응답을 확인한 항목만 회수한다. */
void Clear(const std::string& workspace, const std::string& project);
}
