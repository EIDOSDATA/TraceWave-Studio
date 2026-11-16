/** @file @brief 저장된 목표 판정과 그 원본 자료를 같은 결과 화면 개정에 연결한다. */
#include "studio_internal.h"
#include "network_assessment_panel.h"
#include "network_panel.h"

void StudioFrame::BuildNetworkAssessmentInterface(wxWindow* navigation)
{
    m_networkAssessmentPanel = new NetworkAssessmentPanel(m_views, navigation, m_properties);
    navigation->GetSizer()->Add(m_networkAssessmentPanel->NavigationView(), 1, wxEXPAND);
    m_properties->GetSizer()->Add(m_networkAssessmentPanel->ConditionsView(), 1, wxEXPAND);
    m_networkAssessmentPanel->NavigationView()->Hide();
    m_networkAssessmentPanel->ConditionsView()->Hide();
    m_views->AddPage(m_networkAssessmentPanel, Display("목표 평가"));
    m_networkAssessmentPanel->onRefresh = [this]()
    {
        RefreshNetwork();
    };
    m_networkAssessmentPanel->onSelect = [this](const std::string& id)
    {
        LoadNetworkAssessment(id);
    };
    m_networkAssessmentPanel->onEvaluate = [this]()
    {
        OpenNetworkAction(NetworkAction::Assessment);
    };
    m_networkAssessmentPanel->onPoints = [this](int criterion, int offset)
    {
        LoadNetworkAssessmentPoints(criterion, offset);
    };
}

void StudioFrame::LoadNetworkAssessment(const std::string& id)
{
    if (!m_connected || !m_networkSupported || m_closing || m_project.empty() || m_busy || m_networkPending ||
        m_setupDialog != nullptr || id.empty())
    {
        return;
    }
    const std::string project = m_project;
    const std::string revision = m_revision;
    const auto generation = ++m_networkGeneration;
    m_networkAssessmentAttemptedId = id;
    m_networkPending = true;
    m_networkAssessmentPanel->ClearSelection("저장된 평가와 당시 자료를 읽고 있습니다.");
    m_networkPanel->ClearSelection("저장 평가의 원본 자료를 읽고 있습니다.");
    UpdateControls();
    const auto failed = [this, project, generation](const Json& error)
    {
        if (m_closing || project != m_project || generation != m_networkGeneration)
        {
            return;
        }
        m_networkPending = false;
        m_networkAssessmentPanel->ClearSelection("평가 조회 실패: " + DiagnosticMessage(error));
        m_networkPanel->ClearSelection("평가 원본 조회를 완료하지 못했습니다.");
        UpdateControls();
    };
    Send(
        "network.assessment", {{"expected_revision", revision}, {"assessment_id", id}}, false, Context(),
        [this, project, revision, generation, id, failed](const Json& assessment)
        {
            if (m_closing || project != m_project || generation != m_networkGeneration)
            {
                return;
            }
            if (revision != m_revision || assessment.at("entry").at("id") != id)
            {
                failed({{"message", "프로젝트 개정이 바뀌어 이전 평가 조회를 폐기했습니다."}});
                return;
            }
            const std::string dataset = assessment.at("entry").at("dataset_id");
            Send(
                "network.get",
                {{"expected_revision", revision},
                 {"dataset_id", dataset},
                 {"offset", 0},
                 {"limit", 201},
                 {"row", 0},
                 {"column", 0}},
                false, Context(),
                [this, project, revision, generation, id, dataset, assessment, failed](const Json& result)
                {
                    if (m_closing || project != m_project || generation != m_networkGeneration)
                    {
                        return;
                    }
                    if (revision != m_revision || result.at("entry").at("id") != dataset ||
                        m_networkAssessmentPanel->AssessmentId() != id)
                    {
                        failed({{"message", "현재 개정 또는 평가 선택이 바뀌어 이전 자료 조회를 폐기했습니다."}});
                        return;
                    }
                    m_networkPending = false;
                    m_networkPanel->SetResult(result);
                    m_networkAssessmentPanel->SetAssessment(assessment);
                    m_networkAssessmentPanel->SetDataset(result);
                    UpdateControls();
                },
                failed);
        },
        failed);
}

void StudioFrame::LoadNetworkAssessmentPoints(int criterion, int offset)
{
    if (!m_connected || m_closing || m_busy || m_networkPending || m_setupDialog != nullptr ||
        !m_networkAssessmentPanel->Selection().is_object() || criterion < 0)
    {
        return;
    }
    const std::string project = m_project;
    const std::string revision = m_revision;
    const std::string id = m_networkAssessmentPanel->AssessmentId();
    const auto generation = ++m_networkGeneration;
    m_networkPending = true;
    m_networkAssessmentPanel->SetStatus("선택한 판정 기준의 실제 표본을 읽고 있습니다.");
    UpdateControls();
    Send(
        "network.assessment.points",
        {{"expected_revision", revision},
         {"assessment_id", id},
         {"criterion", criterion},
         {"offset", offset},
         {"limit", 201}},
        false, Context(),
        [this, project, revision, generation, id, criterion](const Json& result)
        {
            if (m_closing || project != m_project || generation != m_networkGeneration)
            {
                return;
            }
            m_networkPending = false;
            if (revision == m_revision && id == m_networkAssessmentPanel->AssessmentId() &&
                criterion == m_networkAssessmentPanel->CriterionIndex())
            {
                m_networkAssessmentPanel->SetPoints(result);
            }
            else
            {
                m_networkAssessmentPanel->ClearSelection("개정 또는 평가 기준이 바뀌어 이전 표본을 폐기했습니다.");
            }
            UpdateControls();
        },
        [this, project, generation](const Json& error)
        {
            if (m_closing || project != m_project || generation != m_networkGeneration)
            {
                return;
            }
            m_networkPending = false;
            m_networkAssessmentPanel->SetStatus("평가 표본 조회 실패: " + DiagnosticMessage(error));
            UpdateControls();
        });
}
