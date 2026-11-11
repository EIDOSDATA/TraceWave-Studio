/** @file @brief 주 창의 validation 책임을 구현한다. */
#include "studio_internal.h"

/** @brief 명시적 해석 입력 검사를 실행하며 완료와 설계 합격을 구분한다. */
void StudioFrame::ValidateInput(std::function<void()> completed)
{
    if (m_busy || m_project.empty())
    {
        return;
    }
    ApplyCurrent(
        [this, completed]()
        {
            m_busy = true;
            UpdateControls();
            Send("design.validate",
                 Json{{"expected_revision", m_revision}, {"profile", "rfad.design/0.1"}, {"purpose", "em"}}, true,
                 Context(),
                 [this, completed](const Json& task)
                 {
                     WaitJob(task,
                             [this, completed](const Json& result)
                             {
                                 m_problemRevision = result.at("revision_id");
                                 m_diagnostics = result.at("diagnostics");
                                 m_diagnosticCount = result.at("diagnostic_count").get<std::size_t>();
                                 m_diagnosticsTruncated = result.at("diagnostics_truncated").get<bool>();
                                 ShowProblems();
                                 m_bottom->SetSelection(0);
                                 Ready("입력 검사를 완료했습니다. 해석 실행/정확도 검증 결과와 구분합니다.");
                                 if (completed)
                                 {
                                     completed();
                                 }
                             });
                 });
        });
}

void StudioFrame::ShowProblems()
{
    m_problems->DeleteAllItems();
    for (const auto& diagnostic : m_diagnostics)
    {
        const long row = m_problems->InsertItem(m_problems->GetItemCount(), Display("확인 필요"));
        m_problems->SetItem(row, 1, Display(DiagnosticMessage(diagnostic)));
    }
    const bool stale = !m_problemRevision.empty() && m_problemRevision != m_revision;
    const std::string count = std::to_string(m_diagnosticCount) + "개" +
                              (m_diagnosticsTruncated ? " 중 " + std::to_string(m_diagnostics.size()) + "개 표시" : "");
    m_problemSummary->SetLabel(
        Display(m_problemRevision.empty()
                    ? "입력 검사를 실행하지 않았습니다."
                    : (stale ? "이전 설계의 검사 결과입니다. 다시 검사하세요."
                             : "해석 입력 문제 " + count + " / 해석 메뉴에서 준비와 실행을 별도로 요청하세요.")));
    m_bottom->SetPageText(0, Display("문제 " + std::to_string(m_diagnosticCount)));
}

void StudioFrame::OpenProblem(long index)
{
    if (m_busy || index < 0 || static_cast<std::size_t>(index) >= m_diagnostics.size() || !ConfirmDiscard())
    {
        return;
    }
    if (m_problemRevision != m_revision)
    {
        Log("이전 설계의 검사입니다. 다시 검사한 뒤 위치로 이동하세요.");
        return;
    }
    const Json diagnostic = m_diagnostics.at(index);
    const auto paths = diagnostic.value("field_paths", Json::array());
    const std::string path = paths.empty() ? "" : paths.at(0).get<std::string>();
    const std::map<std::string, std::string> collections{{"geometry", "geometry"},
                                                         {"materials", "material"},
                                                         {"stackup", "layer"},
                                                         {"ports", "port"},
                                                         {"parameters", "parameter"}};
    for (const auto& item : m_editor.at("items"))
    {
        const std::string kind = item.at("kind");
        const std::string id = item.at("id");
        bool matches = kind == "board" && (path == "board" || path.compare(0, 6, "board.") == 0);
        for (const auto& mapping : collections)
        {
            const std::string prefix = mapping.first + "." + id;
            matches = matches || (kind == mapping.second &&
                                  (path == prefix || path.compare(0, prefix.size() + 1, prefix + ".") == 0));
        }
        if (matches)
        {
            RefreshEditor(Json{{"kind", kind}, {"id", id}},
                          [this, path, diagnostic]()
                          {
                              Ready("문제 위치로 이동했습니다.");
                              m_editorPanel->ShowDiagnostic(path, DiagnosticMessage(diagnostic));
                          });
            return;
        }
    }
    Log(DiagnosticMessage(diagnostic));
}
