/** @file @brief 다중 대역 목표의 실제 편집 이벤트와 원본 보존을 검사한다. */
#include "studio_internal.h"
#include "target_editor_dialog.h"
#include "setup_smoke_support.h"

namespace
{
/** @brief 시험에서만 쓰는 명시 목표 입력이며 제품의 기본값이 아니다. */
void FillTarget(EditorPanel& fields, const std::string& name, const std::string& start, const std::string& end)
{
    fields.SetFieldValue("name", name);
    fields.SetFieldValue("band.start.mode", "value");
    fields.SetFieldValue("band.start.value", start);
    fields.SetFieldValue("band.end.mode", "value");
    fields.SetFieldValue("band.end.value", end);
    fields.SetFieldValue("sampling.count", "21");
    fields.SetFieldValue("criteria.s11_db.mode", "value");
    fields.SetFieldValue("criteria.s11_db.value", "-12");
    fields.SetFieldValue("criteria.radiation_efficiency.mode", "value");
    fields.SetFieldValue("criteria.radiation_efficiency.value", "0.5");
    fields.SetFieldValue("criteria.total_efficiency.mode", "missing");
    fields.SetFieldValue("criteria.fractional_bandwidth.mode", "value");
    fields.SetFieldValue("criteria.fractional_bandwidth.value", "0.02");
}
}

void StudioSmokeDriver::SetupTargetSmoke(TargetEditorDialog& dialog)
{
    if (m_setupStage == 200 || dialog.m_pending)
    {
        return;
    }
    if (m_setupStage == 2)
    {
        CanvasAssert(dialog.m_targetId.is_null() && dialog.m_fields->FieldValue("name") == "" &&
                         dialog.m_fields->FieldValue("band.start.mode") == "missing" &&
                         dialog.m_fields->FieldValue("reference_impedance.mode") == "missing" &&
                         dialog.m_fields->FieldValue("port_id") == "" && !dialog.m_apply->IsEnabled(),
                     "신규 목표의 빈 입력 또는 미정 조건이 보존되지 않았습니다.");
        m_setupSeedTarget = dialog.m_context.at("items").at(0).at("id");
        m_setupStage = 200;
        SetupSafetyChecks(dialog.m_context);
        FillTarget(*dialog.m_fields, "GUI 고대역", "5.8", "5.9");
        dialog.m_reason->SetValue(Display("GUI 시험용 목표 추가"));
        m_setupChecks.push_back("new_target_has_no_physical_defaults");
        m_setupStage = 3;
        SetupSmoke::Click(dialog.m_apply);
        m_frame.Close();
        CanvasAssert(m_frame.m_setupDialog == &dialog && !m_frame.m_closeAfterSetup && dialog.m_mutating,
                     "적용 중 부모 닫기 요청이 보류되지 않았습니다.");
        m_setupChecks.push_back("parent_close_veto_during_target_apply");
    }
    else if (m_setupStage == 3)
    {
        CanvasAssert(!dialog.m_targetId.is_null() && dialog.m_context.at("items").size() == 2,
                     "새 대역을 기존 목표와 함께 저장하지 못했습니다.");
        m_setupAddedTarget = dialog.m_targetId;
        dialog.m_fields->SetFieldValue("band.start.unit", "Hz");
        dialog.m_reason->SetValue(Display("표시 단위만 변경"));
        m_setupStage = 4;
        SetupSmoke::Click(dialog.m_apply);
    }
    else if (m_setupStage == 4)
    {
        double value = 0;
        CanvasAssert(Display(dialog.m_fields->FieldValue("band.start.value").get<std::string>()).ToDouble(&value) &&
                         value == 5.8e9 && dialog.m_fields->FieldValue("reference_impedance.mode") == "missing" &&
                         dialog.m_fields->FieldValue("band.reference.mode") == "missing" &&
                         dialog.m_fields->FieldValue("port_id") == "",
                     "단위 변경 또는 미정 조건이 변질되었습니다.");
        m_setupChecks.push_back("unit_only_change_preserves_si_and_missing_conditions");
        m_setupExpectedRevision = dialog.m_revision;
        dialog.m_fields->SetFieldValue("band.start.value", "9000000000");
        dialog.m_reason->SetValue(Display("범위 오류 차단 시험"));
        m_setupStage = 5;
        SetupSmoke::Click(dialog.m_apply);
    }
    else if (m_setupStage == 5)
    {
        CanvasAssert(!dialog.m_error.is_null() && dialog.m_revision == m_setupExpectedRevision &&
                         dialog.m_fields->FieldValue("band.start.value") == "9000000000" && !dialog.m_disconnected,
                     "확정 입력 오류가 기존 개정 또는 미적용 폼을 훼손했습니다.");
        m_setupChecks.push_back("invalid_target_preserves_draft_and_revision");
        dialog.m_fields->SetFieldValue("band.start.value", "5800000000");
        dialog.m_fields->SetFieldValue("name", "GUI 수정 고대역");
        dialog.m_reason->SetValue(Display("오류 수정과 이름 변경"));
        m_setupStage = 6;
        SetupSmoke::Click(dialog.m_apply);
    }
    else if (m_setupStage == 6)
    {
        m_setupStage = 7;
        SetupSmoke::Click(dialog.m_add);
    }
    else if (m_setupStage == 7)
    {
        CanvasAssert(dialog.m_targetId.is_null(), "새 목표 폼으로 전환하지 못했습니다.");
        FillTarget(*dialog.m_fields, "삭제할 GUI 목표", "6.0", "6.1");
        dialog.m_reason->SetValue(Display("삭제와 이력 확인용 추가"));
        m_setupStage = 8;
        SetupSmoke::Click(dialog.m_apply);
    }
    else if (m_setupStage == 8)
    {
        CanvasAssert(dialog.m_context.at("items").size() == 3, "세 번째 목표를 추가하지 못했습니다.");
        dialog.m_reason->SetValue(Display("시험 목표 명시적 삭제"));
        m_setupStage = 9;
        SetupSmoke::Click(dialog.m_remove);
    }
    else if (m_setupStage == 9)
    {
        CanvasAssert(dialog.m_targetId.is_null() && dialog.m_context.at("items").size() == 2,
                     "선택 목표만 삭제되지 않았습니다.");
        m_setupChecks.push_back("target_add_edit_select_remove");
        int index = 0;
        for (const auto& item : dialog.m_context.at("items"))
        {
            if (item.at("id") == m_setupSeedTarget)
            {
                break;
            }
            ++index;
        }
        m_setupStage = 10;
        SetupSmoke::Select(dialog.m_targets, index);
    }
    else if (m_setupStage == 10)
    {
        CanvasAssert(dialog.m_targetId == m_setupSeedTarget &&
                         dialog.m_fields->FieldValue("sampling.kind") == "explicit",
                     "명시 표본이 있는 원래 목표를 선택하지 못했습니다.");
        m_setupSamples = dialog.m_fields->FieldValue("sampling.explicit");
        CanvasAssert(m_setupSamples.size() == 1001 && !dialog.m_fields->IsFieldVisible("sampling.count") &&
                         dialog.m_fields->IsFieldVisible("sampling.explicit") &&
                         !dialog.m_fields->IsFieldVisible("sampling.provenance") &&
                         dialog.m_context.at("input_status").at("has_estimated_inputs") == true,
                     "명시 표본/기본 상세 분리/근사 상태를 보존하지 못했습니다.");
        dialog.m_fields->SetFieldValue("name", "GUI 원본 출처 유지");
        dialog.m_reason->SetValue(Display("이름만 변경하고 원본 표본 보존"));
        m_setupStage = 11;
        SetupSmoke::Click(dialog.m_apply);
    }
    else if (m_setupStage == 11)
    {
        CanvasAssert(dialog.m_fields->FieldValue("sampling.explicit") == m_setupSamples &&
                         dialog.m_context.at("input_status").at("has_estimated_inputs") == true,
                     "이름 변경이 원래 명시 표본 또는 근사 상태를 바꿨습니다.");
        m_setupChecks.push_back("explicit_1001_samples_and_origins_preserved");
        m_setupExpectedRevision = dialog.m_revision;
        const Json applied = dialog.GetAppliedResult();
        dialog.ServiceDisconnected("완료된 변경 보존과 재조회 경계 시험");
        CanvasAssert(dialog.GetAppliedResult() == applied && dialog.NeedsReload(),
                     "연결 상태 변경으로 이미 확인한 적용 결과가 사라졌습니다.");
        m_setupChecks.push_back("completed_changes_reloaded_after_dialog_disconnect");
        m_setupStage = 12;
        SetupSmoke::Click(dialog.m_cancel);
    }
}
