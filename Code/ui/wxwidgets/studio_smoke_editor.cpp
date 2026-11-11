/** @file @brief 주 창의 smoke_editor 책임을 구현한다. */
#include "studio_internal.h"

/** @brief 실제 입력 폼과 동일한 명령 경로에서 의존 수식과 영속 이력을 검증한다. */
void StudioSmokeDriver::EditorSmokeNext()
{
    const auto parameter = [](const std::string& identity)
    {
        return Json{{"kind", "parameter"}, {"id", identity}};
    };
    if (m_editorStage == 0)
    {
        CheckUxState("saved", false);
        m_uxChecks.push_back("saved_state");
        const wxMenuItem* redo = m_frame.GetMenuBar()->FindItem(IdRedo);
        const std::unique_ptr<wxAcceleratorEntry> primary(redo->GetAccel());
        bool alternate = false;
        for (const auto& shortcut : redo->GetExtraAccels())
        {
            if (shortcut.GetFlags() == (wxACCEL_CTRL | wxACCEL_SHIFT) && shortcut.GetKeyCode() == 'Z' &&
                shortcut.GetCommand() == IdRedo)
            {
                alternate = true;
            }
        }
        if (!primary || primary->GetFlags() != wxACCEL_CTRL || primary->GetKeyCode() != 'Y' || !alternate)
        {
            throw std::runtime_error("Redo shortcuts were not registered together.");
        }
        m_uxChecks.push_back("redo_aliases_registered");
        m_baseParameter = Uuid();
        m_dependentParameter = Uuid();
        m_editorStage = 1;
        m_frame.RefreshEditor(
            Json{{"kind", "new_parameter"}, {"id", m_baseParameter}},
            [this]()
            {
                m_frame.Ready("새 매개변수 입력을 확인합니다.");
                CheckUxState("saved", false);
                m_uxChecks.push_back("blank_parameter_apply_disabled");
                if (m_frame.m_editorPanel->IsFieldVisible("value"))
                {
                    throw std::runtime_error("Missing parameter exposes a numeric input.");
                }
                m_uxChecks.push_back("missing_value_hidden");
                m_frame.m_editorPanel->SetFieldValue("mode", "value");
                m_frame.m_editorPanel->SetFieldValue("value", "40");
                CheckUxState("draft", false);
                m_uxChecks.push_back("unnamed_parameter_apply_disabled");
                m_frame.m_editorPanel->SetFieldValue("name", "기판 폭");
                CheckUxState("draft", true);
                m_uxChecks.push_back("draft_state_and_apply_enabled");
                m_frame.ApplyCurrent(
                    [this]()
                    {
                        CheckUxState("applied", false);
                        m_uxChecks.push_back("applied_state_and_apply_disabled");
                        m_frame.m_editorPanel->SetFieldValue("value", m_frame.m_editorPanel->FieldValue("value"));
                        CheckUxState("applied", false);
                        m_uxChecks.push_back("unchanged_input_apply_disabled");
                        m_frame.m_editorPanel->SetFieldValue("unit", "m");
                        const std::string notice = m_frame.m_editorPanel->InputNotice();
                        if (notice.empty() || notice.find("적용 후 환산") == std::string::npos)
                        {
                            throw std::runtime_error("Unit-only draft does not explain deferred display conversion.");
                        }
                        m_frame.m_editorPanel->SetFieldValue("unit", "mm");
                        if (!m_frame.m_editorPanel->InputNotice().empty())
                        {
                            throw std::runtime_error("Restored display unit retains an obsolete conversion notice.");
                        }
                        CheckUxState("applied", false);
                        m_uxChecks.push_back("unit_change_explained");
                        m_editorChecks.push_back("parameter_created");
                        EditorSmokeNext();
                    });
            });
    }
    else if (m_editorStage == 1)
    {
        m_editorStage = 2;
        m_frame.RefreshEditor(Json{{"kind", "new_parameter"}, {"id", m_dependentParameter}},
                              [this]()
                              {
                                  m_frame.m_editorPanel->SetFieldValue("name", "절반 폭");
                                  m_frame.m_editorPanel->SetFieldValue("mode", "expression");
                                  m_frame.m_editorPanel->SetFieldValue("expression", "width / 2");
                                  m_frame.m_editorPanel->SetFieldValue("bindings", Json{{"width", m_baseParameter}});
                                  if (!m_frame.m_editorPanel->IsFieldVisible("value") ||
                                      !m_frame.m_editorPanel->IsFieldVisible("expression") ||
                                      !m_frame.m_editorPanel->IsFieldVisible("bindings"))
                                  {
                                      throw std::runtime_error("Expression input or calculated value is hidden.");
                                  }
                                  m_uxChecks.push_back("expression_fields_visible");
                                  m_frame.ApplyCurrent(
                                      [this]()
                                      {
                                          CheckEditorValue(20.0);
                                          m_editorChecks.push_back("expression_bound");
                                          EditorSmokeNext();
                                      });
                              });
    }
    else if (m_editorStage == 2)
    {
        m_editorStage = 3;
        m_frame.RefreshEditor(parameter(m_baseParameter),
                              [this]()
                              {
                                  m_frame.m_editorPanel->SetFieldValue("value", "60");
                                  m_frame.ApplyCurrent(
                                      [this]()
                                      {
                                          EditorSmokeNext();
                                      });
                              });
    }
    else if (m_editorStage == 3)
    {
        m_editorStage = 4;
        m_frame.RefreshEditor(
            parameter(m_dependentParameter),
            [this]()
            {
                CheckEditorValue(30.0);
                m_editorChecks.push_back("dependency_recalculated");
                m_failureRevision = m_frame.m_revision;
                m_frame.m_editorPanel->SetFieldValue("expression", "width / 0");
                m_frame.ApplyCurrent(
                    [this]()
                    {
                        FinishSmoke(false, "Invalid expression unexpectedly succeeded.");
                    },
                    [this](const Json& error)
                    {
                        if (error.at("data").at("domain_code") != "E_EXPR_DOMAIN" ||
                            m_frame.m_revision != m_failureRevision ||
                            m_frame.m_editorPanel->FieldValue("expression") != "width / 0")
                        {
                            FinishSmoke(false, "Rejected editor input or revision was not preserved.");
                            return;
                        }
                        if (m_frame.m_editorPanel->DiagnosticField() != "expression")
                        {
                            FinishSmoke(false, "Expression diagnostic did not identify its input field.");
                            return;
                        }
                        m_uxChecks.push_back("expression_error_localized");
                        CheckUxState("draft", true);
                        m_uxChecks.push_back("rejected_draft_stays_editable");
                        m_editorChecks.push_back("invalid_input_preserved");
                        m_frame.m_editorPanel->SetFieldValue("expression", "width / 2");
                        m_editorStage = 5;
                        EditorSmokeNext();
                    });
            });
    }
    else if (m_editorStage == 5)
    {
        m_editorStage = 6;
        m_frame.History("project.undo",
                        [this, parameter]()
                        {
                            m_frame.RefreshEditor(parameter(m_dependentParameter),
                                                  [this]()
                                                  {
                                                      CheckEditorValue(20.0);
                                                      m_editorChecks.push_back("undo_recalculated");
                                                      m_frame.Ready("실행 취소 확인");
                                                      EditorSmokeNext();
                                                  });
                        });
    }
    else if (m_editorStage == 6)
    {
        m_editorStage = 7;
        m_frame.History("project.redo",
                        [this, parameter]()
                        {
                            m_frame.RefreshEditor(parameter(m_dependentParameter),
                                                  [this]()
                                                  {
                                                      CheckEditorValue(30.0);
                                                      m_editorChecks.push_back("redo_recalculated");
                                                      m_frame.Ready("다시 실행 확인");
                                                      EditorSmokeNext();
                                                  });
                        });
    }
    else if (m_editorStage == 7)
    {
        m_editorStage = 8;
        m_frame.SaveProject();
    }
    else if (m_editorStage == 10)
    {
        m_frame.RefreshEditor(parameter(m_dependentParameter),
                              [this]()
                              {
                                  CheckEditorValue(30.0);
                                  if (m_frame.m_editor.at("saved_revision") != m_frame.m_revision ||
                                      m_frame.m_savedRevision != m_frame.m_revision ||
                                      !m_frame.m_editor.at("history").value("can_undo", false) ||
                                      m_serviceSessions != 2)
                                  {
                                      FinishSmoke(false, "Editor state or durable history was lost after restart.");
                                      return;
                                  }
                                  m_editorChecks.push_back("restart_preserved");
                                  m_frame.Ready("저장된 편집 상태를 확인했습니다.");
                                  CheckUxState("saved", false);
                                  m_uxChecks.push_back("saved_after_restart");
                                  m_editorStage = 11;
                                  FinishSmoke(true, "");
                              });
    }
}

/** @brief smoke에서 서비스가 환산한 표시값만 읽고 기대 결과와 비교한다. */
void StudioSmokeDriver::CheckEditorValue(double expected) const
{
    const std::string text = m_frame.m_editorPanel->FieldValue("value").get<std::string>();
    if (std::abs(std::stod(text) - expected) > 1e-9)
    {
        throw std::runtime_error("Editor computed value mismatch: " + text);
    }
}

/** @brief 실제 입력 이벤트 뒤의 상태 표시와 적용 가능 여부를 smoke에서 확인한다. */
void StudioSmokeDriver::CheckUxState(const std::string& expected, bool applyEnabled) const
{
    const std::string label =
        expected == "draft" ? "미적용 입력" : (expected == "applied" ? "적용됨 (저장 필요)" : "저장됨");
    const std::string name = m_frame.m_editor.at("metadata").at("name").get<std::string>();
    if (m_frame.m_editState != expected || m_frame.m_apply->IsEnabled() != applyEnabled ||
        Utf8(m_frame.m_revisionLabel->GetLabel()) != label || Utf8(m_frame.GetStatusBar()->GetStatusText(1)) != label ||
        !m_frame.GetTitle().StartsWith(Display(name + " - ")) ||
        m_frame.GetTitle().Contains(Display(m_frame.m_revision)) ||
        !m_frame.m_revisionLabel->GetToolTipText().Contains(Display(m_frame.m_revision)))
    {
        throw std::runtime_error("Editor state, title or apply availability does not match " + expected);
    }
}
