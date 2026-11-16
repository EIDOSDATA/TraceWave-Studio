/** @file @brief 공통 결과 View와 서비스 조회/모달 도구를 현재 프로젝트 개정에 연결한다. */
#include "studio_internal.h"
#include "studio_shell.h"
#include "network_panel.h"
#include "network_assessment_panel.h"
#include "network_import_dialog.h"
#include "network_circuit_dialog.h"
#include "network_assessment_dialog.h"
#include "network_transform_dialog.h"
#include "network_source_dialog.h"
#include "network_export.h"
#include <wx/choicdlg.h>
#include <wx/srchctrl.h>

void StudioFrame::BuildNetworkInterface()
{
    auto* navigation = m_tree->GetParent();
    m_networkPanel = new NetworkPanel(m_views, navigation, m_properties);
    navigation->GetSizer()->Add(m_networkPanel->NavigationView(), 1, wxEXPAND);
    m_properties->GetSizer()->Add(m_networkPanel->ConditionsView(), 1, wxEXPAND);
    m_networkPanel->NavigationView()->Hide();
    m_networkPanel->ConditionsView()->Hide();
    m_views->AddPage(m_networkPanel, Display("네트워크"));
    BuildNetworkAssessmentInterface(navigation);
    m_views->SetGroups({0, 0, 2, 1, 3, 4, 2, 2});
    m_views->SetDisplayOrder({0, 1, 6, 7, 2, 3, 4, 5});
    m_networkPanel->onRefresh = [this]()
    {
        RefreshNetwork();
    };
    m_networkPanel->onSelect = [this](const std::string& id, int row, int column, int offset)
    {
        LoadNetworkResult(id, row, column, offset);
    };
    m_networkPanel->onAction = [this](NetworkAction action)
    {
        OpenNetworkAction(action);
    };
}

void StudioFrame::UpdateNetworkViews()
{
    if (m_networkPanel == nullptr || m_networkAssessmentPanel == nullptr)
    {
        return;
    }
    const bool assessmentActive = m_views->GetSelection() == 7;
    const bool networkActive = m_views->GetSelection() == 6;
    const bool active = networkActive || assessmentActive || m_views->GetSelection() == 8;
    m_networkPanel->NavigationView()->Show(networkActive);
    m_networkPanel->ConditionsView()->Show(networkActive);
    m_networkAssessmentPanel->NavigationView()->Show(assessmentActive);
    m_networkAssessmentPanel->ConditionsView()->Show(assessmentActive);
    m_tree->Show(!active);
    m_objectSearch->Show(!active);
    m_objectFilter->Show(!active);
    m_selectionLabel->Show(!active);
    const bool metadata = m_selection.value("kind", "project") == "project";
    m_metadataPanel->Show(!active && metadata);
    m_editorPanel->Show(!active && !metadata);
    m_apply->Show(!active);
    m_revisionLabel->Show(!active);
    if (m_shell)
    {
        m_shell->SetResultContext(active, m_views->GetSelection() == 8);
    }
    m_tree->GetParent()->Layout();
    m_properties->Layout();
    const bool available = m_connected && m_networkSupported && !m_project.empty() && !m_closing;
    const bool blocked = m_busy || m_networkPending || m_setupDialog != nullptr;
    m_networkPanel->SetEnabledState(available, blocked);
    m_networkAssessmentPanel->SetEnabledState(available, blocked);
    if (active && available && !blocked && !m_networkRefreshQueued && m_networkAttemptedRevision != m_revision &&
        m_networkPanel->Library().value("revision_id", "") != m_revision)
    {
        m_networkRefreshQueued = true;
        CallAfter(
            [this]()
            {
                m_networkRefreshQueued = false;
                if (!m_closing && !m_busy && (m_views->GetSelection() == 6 || m_views->GetSelection() == 7) &&
                    m_networkAttemptedRevision != m_revision &&
                    m_networkPanel->Library().value("revision_id", "") != m_revision)
                {
                    RefreshNetwork(m_networkPreferredId);
                }
            });
    }
    else if (assessmentActive && available && !blocked && !m_networkRefreshQueued &&
             m_networkAssessmentPanel->Library().value("revision_id", "") == m_revision &&
             m_networkAssessmentPanel->Selection().is_null() && !m_networkAssessmentPanel->AssessmentId().empty() &&
             m_networkAssessmentAttemptedId != m_networkAssessmentPanel->AssessmentId())
    {
        m_networkRefreshQueued = true;
        CallAfter(
            [this]()
            {
                m_networkRefreshQueued = false;
                if (!m_closing && !m_busy && m_views->GetSelection() == 7 &&
                    m_networkAssessmentPanel->Selection().is_null() &&
                    m_networkAssessmentAttemptedId != m_networkAssessmentPanel->AssessmentId())
                {
                    LoadNetworkAssessment(m_networkAssessmentPanel->AssessmentId());
                }
            });
    }
    if (active && !m_networkSupported)
    {
        m_networkPanel->SetStatus("현재 서비스는 공통 복소 자료 기능을 제공하지 않습니다.");
        m_networkAssessmentPanel->SetStatus("현재 서비스는 공통 복소 자료 기능을 제공하지 않습니다.");
    }
}

void StudioFrame::ResetNetwork()
{
    ResetSweeps();
    ++m_networkGeneration;
    m_networkPending = false;
    m_networkRefreshQueued = false;
    m_networkAttemptedRevision.clear();
    m_networkPreferredId.clear();
    m_networkAssessmentPreferredId.clear();
    m_networkAssessmentAttemptedId.clear();
    if (m_networkPanel != nullptr)
    {
        m_networkPanel->Clear("현재 프로젝트의 결과 목록을 다시 읽어야 합니다.");
    }
    if (m_networkAssessmentPanel != nullptr)
    {
        m_networkAssessmentPanel->Clear("현재 프로젝트의 저장 평가를 다시 읽어야 합니다.");
    }
}

void StudioFrame::RefreshNetwork(const std::string& preferredId)
{
    if (!m_connected || !m_networkSupported || m_closing || m_project.empty() || m_busy || m_networkPending ||
        m_setupDialog != nullptr)
    {
        return;
    }
    const std::string project = m_project;
    const std::string revision = m_revision;
    const auto generation = ++m_networkGeneration;
    m_networkAttemptedRevision = revision;
    m_networkPending = true;
    m_networkPanel->ClearSelection("자료 목록을 읽고 있습니다.");
    m_networkAssessmentPanel->ClearSelection("저장 평가 목록을 읽고 있습니다.");
    UpdateControls();
    Send(
        "network.library", {{"expected_revision", revision}}, false, Context(),
        [this, project, revision, generation, preferredId](const Json& context)
        {
            if (m_closing || generation != m_networkGeneration || project != m_project)
            {
                return;
            }
            m_networkPending = false;
            if (revision != m_revision || context.at("project_id") != project || context.at("revision_id") != revision)
            {
                m_networkPanel->ClearSelection("개정이 바뀌어 이전 조회를 폐기했습니다. 목록을 다시 읽으세요.");
                UpdateControls();
                return;
            }
            m_networkPanel->SetLibrary(context, preferredId);
            m_networkAssessmentPanel->SetLibrary(context, m_networkAssessmentPreferredId);
            m_networkAssessmentAttemptedId.clear();
            m_networkAssessmentPreferredId.clear();
            m_networkPreferredId.clear();
            UpdateControls();
            if (m_views->GetSelection() == 7 && !m_networkAssessmentPanel->AssessmentId().empty())
            {
                LoadNetworkAssessment(m_networkAssessmentPanel->AssessmentId());
            }
            else if (!m_networkPanel->DatasetId().empty())
            {
                LoadNetworkResult(m_networkPanel->DatasetId());
            }
        },
        [this, project, generation](const Json& error)
        {
            if (m_closing || generation != m_networkGeneration || project != m_project)
            {
                return;
            }
            m_networkPending = false;
            m_networkPanel->ClearSelection("목록 조회 실패: " + DiagnosticMessage(error));
            m_networkAssessmentPanel->ClearSelection("목록 조회 실패: " + DiagnosticMessage(error));
            UpdateControls();
        });
}

void StudioFrame::LoadNetworkResult(const std::string& id, int row, int column, int offset)
{
    if (!m_connected || !m_networkSupported || m_closing || m_project.empty() || m_busy || m_networkPending ||
        m_setupDialog != nullptr)
    {
        return;
    }
    const std::string project = m_project;
    const std::string revision = m_revision;
    const auto generation = ++m_networkGeneration;
    m_networkPending = true;
    m_networkPanel->ClearSelection("현재 자료의 실제 표본을 읽고 있습니다.");
    UpdateControls();
    Send(
        "network.get",
        {{"expected_revision", revision},
         {"dataset_id", id},
         {"offset", offset},
         {"limit", 201},
         {"row", row},
         {"column", column}},
        false, Context(),
        [this, project, revision, generation, id](const Json& result)
        {
            if (m_closing || generation != m_networkGeneration || project != m_project)
            {
                return;
            }
            m_networkPending = false;
            if (revision != m_revision || result.at("entry").at("id") != id)
            {
                m_networkPanel->ClearSelection("개정 또는 선택이 바뀌어 이전 결과 조회를 폐기했습니다.");
            }
            else
            {
                m_networkPanel->SetResult(result);
            }
            UpdateControls();
        },
        [this, project, generation](const Json& error)
        {
            if (m_closing || generation != m_networkGeneration || project != m_project)
            {
                return;
            }
            m_networkPending = false;
            m_networkPanel->ClearSelection("표본 조회 실패: " + DiagnosticMessage(error));
            UpdateControls();
        });
}

void StudioFrame::OpenNetworkAction(NetworkAction action)
{
    if (!m_connected || !m_networkSupported || m_closing || m_project.empty() || m_busy || m_networkPending ||
        m_setupDialog != nullptr)
    {
        return;
    }
    if (HasDraft())
    {
        ApplyCurrent(
            [this, action]()
            {
                OpenNetworkAction(action);
            });
        return;
    }
    const std::string project = m_project;
    const std::string revision = m_revision;
    const std::string dataset = m_networkPanel->DatasetId();
    m_busy = true;
    UpdateControls();
    const auto failed = [this](const Json& error)
    {
        m_busy = false;
        m_networkPanel->SetStatus(DiagnosticMessage(error));
        UpdateControls();
    };
    Send(
        "network.library", {{"expected_revision", revision}}, false, Context(),
        [this, action, project, revision, dataset, failed](const Json& context)
        {
            if (m_closing || project != m_project || revision != m_revision || context.at("revision_id") != revision)
            {
                failed({{"message", "현재 프로젝트 개정이 바뀌었습니다. 다시 읽으세요."}});
                return;
            }
            const auto show = [this, action, context, project, revision](const Json& selection)
            {
                CallAfter(
                    [this, action, context, selection, project, revision]()
                    {
                        if (!m_closing && m_connected && project == m_project && revision == m_revision)
                        {
                            ShowNetworkTool(action, context, selection);
                        }
                        else if (!m_closing)
                        {
                            m_busy = false;
                            UpdateControls();
                        }
                    });
            };
            if (action == NetworkAction::Import || action == NetworkAction::Solver ||
                (action == NetworkAction::Circuit && dataset.empty()))
            {
                show(nullptr);
            }
            else if (dataset.empty())
            {
                failed({{"message", "먼저 결과 자료를 선택하세요."}});
            }
            else
            {
                Send("network.get",
                     {{"expected_revision", revision},
                      {"dataset_id", dataset},
                      {"offset", 0},
                      {"limit", 201},
                      {"row", 0},
                      {"column", 0}},
                     false, Context(), show, failed);
            }
        },
        failed);
}

void StudioFrame::ShowNetworkTool(NetworkAction action, const Json& context, const Json& selection)
{
    if (action == NetworkAction::Export)
    {
        wxArrayString formats;
        std::vector<std::string> keys{"touchstone", "csv", "hdf5"};
        formats.Add("Touchstone");
        formats.Add("CSV");
        formats.Add("HDF5");
        if (!selection.at("entry").at("raw").is_null())
        {
            formats.Add(Display("가져온 원문 바이트"));
            keys.push_back("source");
        }
        wxSingleChoiceDialog format(this, Display("자료와 조건/출처 파일을 함께 내보냅니다."), Display("결과 내보내기"),
                                    formats);
        if (format.ShowModal() != wxID_OK)
        {
            m_busy = false;
            UpdateControls();
            return;
        }
        const std::string project = m_project;
        Send(
            "network.export",
            {{"expected_revision", m_revision},
             {"dataset_id", selection.at("entry").at("id")},
             {"format", keys.at(static_cast<std::size_t>(format.GetSelection()))}},
            false, Context(),
            [this, project](const Json& result)
            {
                CallAfter(
                    [this, project, result]()
                    {
                        if (!m_closing && project == m_project)
                        {
                            SaveNetworkExport(this, result, m_options.workspace);
                            m_busy = false;
                            UpdateControls();
                        }
                    });
            },
            [this](const Json& error)
            {
                m_busy = false;
                m_networkPanel->SetStatus("내보내기 실패: " + DiagnosticMessage(error));
                UpdateControls();
            });
        return;
    }
    try
    {
        std::unique_ptr<ProjectSetupDialog> dialog;
        if (action == NetworkAction::Import)
        {
            dialog = std::make_unique<NetworkImportDialog>(this, context, ObjectToolGateway());
        }
        else if (action == NetworkAction::Circuit)
        {
            dialog = std::make_unique<NetworkCircuitDialog>(this, context, selection, ObjectToolGateway());
        }
        else if (action == NetworkAction::Assessment)
        {
            dialog = std::make_unique<NetworkAssessmentDialog>(this, context, selection, ObjectToolGateway());
        }
        else if (action == NetworkAction::Transform)
        {
            dialog = std::make_unique<NetworkTransformDialog>(this, context, selection, ObjectToolGateway());
        }
        else if (action == NetworkAction::Solver)
        {
            dialog = std::make_unique<NetworkSolverDialog>(this, context, ObjectToolGateway());
        }
        else if (action == NetworkAction::Diagnostics)
        {
            dialog = std::make_unique<NetworkDiagnosticsDialog>(this, context, selection, ObjectToolGateway());
        }
        ShowObjectTool(std::move(dialog), m_selection);
    }
    catch (const std::exception& error)
    {
        Failure(error.what());
    }
}
