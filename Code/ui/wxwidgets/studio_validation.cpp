/** @file @brief 주 창의 validation 책임을 구현한다. */
#include "studio_internal.h"
#include "studio_shell.h"

namespace
{
/** @brief 전체 경로 또는 그 하위 필드가 정확히 같은 원본을 가리키는지 확인한다. */
bool AtPath(const std::string& path, const std::string& prefix)
{
    return path.compare(0, prefix.size(), prefix) == 0 &&
           (path.size() == prefix.size() || path[prefix.size()] == '.' || path[prefix.size()] == '[');
}
}

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
        const auto severity = diagnostic.value("severity", "");
        const auto state = severity == "blocking" ? "차단" :
                           severity == "warning" ? "주의" : severity == "info" ? "안내" : "확인 필요";
        const long row = m_problems->InsertItem(m_problems->GetItemCount(), Display(state));
        m_problems->SetItem(row, 1, Display(DiagnosticMessage(diagnostic)));
    }
    const bool stale = !m_problemRevision.empty() && m_problemRevision != m_revision;
    const std::string count = std::to_string(m_diagnosticCount) + "개" +
                              (m_diagnosticsTruncated ? " 중 " + std::to_string(m_diagnostics.size()) + "개 표시" : "");
    m_problemSummary->SetLabel(
        Display(m_problemRevision.empty()
                    ? "입력 검사를 실행하지 않았습니다."
                    : (stale ? "이전 개정의 검사입니다. 다시 검사하세요." : "해석 입력 문제 " + count)));
    m_bottom->SetPageText(0, Display("문제 " + std::to_string(m_diagnosticCount)));
}

long StudioFrame::FindPortProblem(const Json& port) const
{
    if (m_problemRevision != m_revision)
    {
        return -1;
    }
    const std::string prefix = "ports." + port.at("id").get<std::string>();
    long terminal = -1;
    for (std::size_t i = 0; i < m_diagnostics.size(); ++i)
    {
        for (const auto& field : m_diagnostics.at(i).value("field_paths", Json::array()))
        {
            const auto path = field.get<std::string>();
            if (AtPath(path, prefix))
            {
                return static_cast<long>(i);
            }
            for (const auto& id : port.at("terminal_ids"))
            {
                if (terminal < 0 && AtPath(path, "geometry." + id.get<std::string>()))
                {
                    terminal = static_cast<long>(i);
                }
            }
        }
    }
    return terminal;
}

void StudioFrame::OpenProblem(long index)
{
    if (m_busy || index < 0 || static_cast<std::size_t>(index) >= m_diagnostics.size())
    {
        return;
    }
    if (m_problemRevision != m_revision)
    {
        Log("이전 설계의 검사입니다. 다시 검사한 뒤 위치로 이동하세요.");
        return;
    }
    if (!ConfirmDiscard())
    {
        m_problems->SetFocus();
        return;
    }
    const Json diagnostic = m_diagnostics.at(index);
    const auto message = DiagnosticMessage(diagnostic);
    for (const auto& field : diagnostic.value("field_paths", Json::array()))
    {
        const std::string path = field.get<std::string>();
        const auto target = DiagnosticSelection(path);
        if (!target.is_null())
        {
            RefreshEditor(target, [this, path, message]()
            {
                Ready("문제 위치로 이동했습니다.");
                ShowDiagnosticField(path, message);
                if (m_portProblem->IsShownOnScreen() && m_portProblem->IsEnabled())
                {
                    m_portProblem->SetFocus();
                }
            });
            return;
        }
    }
    Log(message);
}

Json StudioFrame::DiagnosticSelection(const std::string& path) const
{
    if (!m_editor.contains("items"))
    {
        return nullptr;
    }
    static const std::map<std::string, std::string> collections{{"geometry", "geometry"}, {"material", "materials"},
        {"layer", "stackup"}, {"port", "ports"}, {"parameter", "parameters"}};
    for (const auto& item : m_editor.at("items"))
    {
        const std::string kind = item.at("kind");
        const std::string id = item.at("id");
        const auto collection = collections.find(kind);
        if ((kind == "board" && AtPath(path, "board")) ||
            (collection != collections.end() && AtPath(path, collection->second + "." + id)))
        {
            return Json{{"kind", kind}, {"id", id}};
        }
    }
    return nullptr;
}

void StudioFrame::ShowDiagnosticField(const std::string& path, const std::string& message)
{
    m_shell->ShowProperties(false);
    m_editorPanel->ShowDiagnostic(path, message);
}
