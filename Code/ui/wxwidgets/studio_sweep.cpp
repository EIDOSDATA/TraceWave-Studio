/** @file @brief 불변 연구의 목록/진행과 실제 제어 응답을 공통 작업 공간에 연결한다. */
#include "studio_internal.h"
#include "sweep_panel.h"
#include "sweep_model.h"
#include "studio_theme.h"
#include "studio_shell.h"
#include "file_delivery.h"
#include <wx/choicdlg.h>
#include <wx/filedlg.h>
#include <wx/msgdlg.h>
#include <wx/scrolwin.h>
#include <wx/tokenzr.h>
#include <cmath>
#include <optional>

namespace
{
/** @brief 저장한 목표의 가중치와 별도 공차 모서리 검토를 설정한다. */
std::optional<Json> RankingOptions(wxWindow* parent, const Json& targets, const Json& axes, const Json& labels)
{
    if (targets.size() < 2 && axes.empty())
    {
        return Json::object();
    }
    wxDialog dialog(parent, wxID_ANY, Display("후보 순위 비교"), wxDefaultPosition, wxDefaultSize,
                    wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    dialog.SetName("sweep.ranking.weights");
    StudioTheme::ApplyTypography(dialog);
    const int gap = dialog.FromDIP(12);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* guide = new wxStaticText(&dialog, wxID_ANY, Display(
        "가중치를 입력하면 합계 점수 순으로 봅니다. 비워 둔 목표는 1을 적용합니다.\n"
        "모든 칸을 비우면 목표별 우열 그룹을 봅니다."));
    layout->Add(guide, 0, wxEXPAND | wxALL, gap);
    auto* scroll = new wxScrolledWindow(&dialog, wxID_ANY);
    scroll->SetScrollRate(0, dialog.FromDIP(14));
    scroll->SetMinSize(dialog.FromDIP(wxSize(450, 185)));
    auto* fields = new wxFlexGridSizer(2, gap, gap);
    fields->AddGrowableCol(0, 1);
    std::vector<std::pair<std::string, wxTextCtrl*>> entries;
    for (const auto& target : targets)
    {
        const auto name = Display(target.at("name").get<std::string>());
        auto* label = new wxStaticText(scroll, wxID_ANY, name.Left(60));
        label->SetToolTip(name);
        fields->Add(label, 0, wxALIGN_CENTER_VERTICAL);
        auto* input = new wxTextCtrl(scroll, wxID_ANY);
        input->SetHint("1");
        input->SetToolTip(name);
        input->SetMaxLength(24);
        fields->Add(input, 0, wxEXPAND);
        entries.emplace_back(target.at("id").get<std::string>(), input);
    }
    scroll->SetSizer(fields);
    layout->Add(scroll, 1, wxEXPAND | wxLEFT | wxRIGHT, gap);
    wxCheckBox* tolerance = nullptr;
    std::vector<wxTextCtrl*> distributions;
    wxTextCtrl* jointWeights = nullptr;
    wxTextCtrl* jointSource = nullptr;
    if (!axes.empty())
    {
        tolerance = new wxCheckBox(&dialog, wxID_ANY, Display("최소·공칭·최대 입력의 공차 모서리 비교"));
        tolerance->SetName("sweep.ranking.tolerance");
        tolerance->SetToolTip(Display("저장한 카테시안 연구에서 공칭점과 각 축 최소/최대의 조합을 비교합니다."));
        layout->Add(tolerance, 0, wxEXPAND | wxALL, gap);
        auto* probabilityLabel = new wxStaticText(
            &dialog, wxID_ANY, Display("이산 분포 가중치 (선택)  /  최소, 공칭, 최대 순서"));
        layout->Add(probabilityLabel, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, gap);
        auto* probabilities = new wxFlexGridSizer(4, gap / 2, gap);
        probabilities->AddGrowableCol(0, 1);
        for (const auto& axis : axes)
        {
            const auto key = axis.at("kind").get<std::string>() + ":" + axis.at("id").get<std::string>();
            const auto name = Display(labels.value(key, std::string("연구 변수")));
            auto* label = new wxStaticText(&dialog, wxID_ANY, name.Left(40));
            label->SetToolTip(name);
            probabilities->Add(label, 0, wxALIGN_CENTER_VERTICAL);
            for (const auto* tip : {"최소", "공칭", "최대"})
            {
                auto* input = new wxTextCtrl(&dialog, wxID_ANY, wxEmptyString, wxDefaultPosition,
                                             dialog.FromDIP(wxSize(66, -1)));
                input->SetHint(Display(tip));
                input->SetToolTip(name + " / " + Display(tip));
                input->SetMaxLength(24);
                probabilities->Add(input, 0, wxEXPAND);
                distributions.push_back(input);
            }
        }
        layout->Add(probabilities, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, gap);
    }
    if (axes.size() >= 2)
    {
        auto* label = new wxStaticText(&dialog, wxID_ANY,
            Display("후보 조합 가중치 (선택) / 축별 가중치와 함께 입력하지 않음"));
        layout->Add(label, 0, wxEXPAND | wxLEFT | wxRIGHT, gap);
        jointWeights = new wxTextCtrl(&dialog, wxID_ANY);
        jointWeights->SetName("sweep.ranking.joint_weights");
        jointWeights->SetHint(Display("후보 번호=가중치, 입력하지 않은 후보는 0"));
        jointWeights->SetToolTip(Display("후보 목록의 번호로 입력합니다. 예시는 1=1, 5=2, 9=1입니다."));
        jointWeights->SetMaxLength(8192);
        layout->Add(jointWeights, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, gap);
        jointSource = new wxTextCtrl(&dialog, wxID_ANY);
        jointSource->SetName("sweep.ranking.joint_source");
        jointSource->SetHint(Display("조합 가중치의 출처 또는 가정"));
        jointSource->SetMaxLength(120);
        layout->Add(jointSource, 0, wxEXPAND | wxLEFT | wxRIGHT, gap);
    }
    auto* status = new wxStaticText(&dialog, wxID_ANY, " ");
    layout->Add(status, 0, wxEXPAND | wxALL, gap);
    layout->Add(dialog.CreateSeparatedButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, gap);
    Json weights = Json::object();
    Json probabilities = Json::array();
    Json joint = nullptr;
    dialog.Bind(wxEVT_BUTTON, [&](wxCommandEvent&)
    {
        weights = Json::object();
        bool hasPositive = false;
        for (const auto& [id, input] : entries)
        {
            auto value = input->GetValue().Trim().Trim(false);
            if (value.empty())
            {
                hasPositive = true;
                continue;
            }
            double weight = 0;
            if (!value.ToDouble(&weight) || !std::isfinite(weight) || weight < 0 || weight > 1e6)
            {
                status->SetLabel(Display("가중치는 0에서 1000000 사이의 숫자를 입력하세요."));
                input->SetFocus();
                return;
            }
            hasPositive = hasPositive || weight > 0;
            weights[id] = weight;
        }
        if (!hasPositive)
        {
            status->SetLabel(Display("가중치가 0보다 큰 목표가 하나 이상 필요합니다."));
            return;
        }
        probabilities = Json::array();
        const bool explicitDistribution = std::any_of(distributions.begin(), distributions.end(), [](wxTextCtrl* input)
        {
            return !input->GetValue().Trim().Trim(false).empty();
        });
        if (explicitDistribution)
        {
            for (std::size_t index = 0; index < distributions.size(); index += 3)
            {
                Json row = Json::array();
                bool positive = false;
                for (std::size_t level = 0; level < 3; ++level)
                {
                    auto* input = distributions[index + level];
                    double weight = 0;
                    if (!input->GetValue().ToDouble(&weight) || !std::isfinite(weight) || weight < 0 || weight > 1e6)
                    {
                        status->SetLabel(Display("모든 축에 0~1000000 사이의 세 가중치를 입력하세요."));
                        input->SetFocus();
                        return;
                    }
                    positive = positive || weight > 0;
                    row.push_back(weight);
                }
                if (!positive)
                {
                    status->SetLabel(Display("각 축에서 하나 이상의 양수 가중치가 필요합니다."));
                    distributions[index]->SetFocus();
                    return;
                }
                probabilities.push_back(std::move(row));
            }
        }
        joint = nullptr;
        if (jointWeights != nullptr)
        {
            const auto supplied = jointWeights->GetValue().Strip(wxString::both);
            const auto source = jointSource->GetValue().Strip(wxString::both);
            if (!supplied.empty() || !source.empty())
            {
                if (supplied.empty() || source.empty() || explicitDistribution)
                {
                    status->SetLabel(Display("조합 가중치와 출처를 함께 입력하고 축별 가중치는 비워 주세요."));
                    jointWeights->SetFocus();
                    return;
                }
                Json rows = Json::array();
                wxStringTokenizer tokens(supplied, ",", wxTOKEN_RET_EMPTY_ALL);
                while (tokens.HasMoreTokens())
                {
                    const auto token = tokens.GetNextToken();
                    long candidate = 0;
                    double weight = 0;
                    if (!token.Contains("=") || !token.BeforeFirst('=').Strip(wxString::both).ToLong(&candidate) ||
                        candidate < 1 || candidate > 128 || !token.AfterFirst('=').Strip(wxString::both).ToDouble(&weight) ||
                        !std::isfinite(weight) || weight < 0 || weight > 1e6 || rows.size() >= 128)
                    {
                        status->SetLabel(Display("후보 번호와 0~1000000 가중치를 번호=가중치로 입력하세요."));
                        jointWeights->SetFocus();
                        return;
                    }
                    rows.push_back({{"ordinal", candidate - 1}, {"weight", weight}});
                }
                joint = {{"source_label", Utf8(source)}, {"weights", std::move(rows)}};
            }
        }
        dialog.EndModal(wxID_OK);
    }, wxID_OK);
    dialog.SetSizerAndFit(layout);
    dialog.CentreOnParent();
    if (dialog.ShowModal() != wxID_OK)
    {
        return std::nullopt;
    }
    Json options = Json::object();
    if (!weights.empty())
    {
        options["weights"] = std::move(weights);
    }
    if (tolerance && (tolerance->GetValue() || !probabilities.empty() || !joint.is_null()))
    {
        options["tolerance"] = true;
    }
    if (!probabilities.empty())
    {
        options["probabilities"] = std::move(probabilities);
    }
    if (!joint.is_null())
    {
        options["joint_probabilities"] = std::move(joint);
    }
    return options;
}
}

void StudioFrame::BuildSweepInterface()
{
    auto* navigation = m_tree->GetParent();
    m_sweepPanel = new SweepPanel(m_views, navigation, m_properties);
    navigation->GetSizer()->Add(m_sweepPanel->NavigationView(), 1, wxEXPAND);
    m_properties->GetSizer()->Add(m_sweepPanel->ConditionsView(), 1, wxEXPAND);
    m_sweepPanel->NavigationView()->Hide();
    m_sweepPanel->ConditionsView()->Hide();
    m_views->AddPage(m_sweepPanel, Display("연구"));
    m_sweepPanel->onRefresh = [this]()
    {
        RefreshSweeps(m_sweepPanel->StudyId());
    };
    m_sweepPanel->onCreate = [this]()
    {
        OpenSweepSetup();
    };
    m_sweepPanel->onSelect = [this](const std::string& id)
    {
        LoadSweep(id);
    };
    m_sweepPanel->onPage = [this](int offset)
    {
        LoadSweep(m_sweepPanel->StudyId(), offset);
    };
    m_sweepPanel->onCommand = [this](const std::string& command)
    {
        SweepCommand(command);
    };
    m_sweepPanel->onResult = [this](int index)
    {
        OpenSweepResult(index);
    };
    m_sweepPanel->onAdopt = [this](int index)
    {
        OpenSweepSelection(index);
    };
    auto* prepare = m_views->GetPage(3);
    auto* button = new wxButton(prepare, wxID_ANY, Display("설계 스윕 / 다축 연구"));
    StudioTheme::Button(*button);
    prepare->GetSizer()->Add(button, 0, wxALL, FromDIP(12));
    button->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     m_views->SetSelection(8);
                 });
}

void StudioFrame::UpdateSweepViews()
{
    if (!m_sweepPanel)
    {
        return;
    }
    const bool active = m_views->GetSelection() == 8;
    m_sweepPanel->NavigationView()->Show(active);
    m_sweepPanel->ConditionsView()->Show(active);
    m_tree->GetParent()->Layout();
    m_properties->Layout();
    const bool available = m_connected && m_sweepSupported && !m_project.empty() && !m_closing;
    const bool busy = m_busy || m_sweepPending || m_setupDialog != nullptr;
    m_sweepPanel->SetEnabledState(available, busy, m_sweepUncertain);
    m_sweepPanel->SetSelectionSupported(m_sweepSelectionSupported);
    if (active && available && !busy && !m_sweepRefreshQueued && m_sweepAttemptedRevision != m_revision)
    {
        m_sweepRefreshQueued = true;
        CallAfter(
            [this]()
            {
                m_sweepRefreshQueued = false;
                if (!m_closing && m_views->GetSelection() == 8 && m_sweepAttemptedRevision != m_revision)
                {
                    RefreshSweeps(m_sweepPanel->StudyId());
                }
            });
    }
    else if (active && !m_sweepSupported)
    {
        m_sweepPanel->SetStatus("현재 서비스는 설계 스윕을 제공하지 않습니다. 저장/편집 기능은 유지됩니다.");
    }
}

void StudioFrame::ResetSweeps()
{
    ++m_sweepGeneration;
    m_sweepPending = false;
    m_sweepUncertain = false;
    m_sweepRefreshQueued = false;
    m_sweepAttemptedRevision.clear();
    m_sweepNextPoll = Clock::time_point{};
    if (m_sweepPanel)
    {
        m_sweepPanel->Clear("현재 프로젝트의 저장 연구를 다시 읽어야 합니다.");
    }
}

void StudioFrame::RefreshSweeps(const std::string& preferred)
{
    if (!m_connected || !m_sweepSupported || m_closing || m_project.empty() || m_busy || m_sweepPending ||
        m_setupDialog)
    {
        return;
    }
    const auto project = m_project;
    const auto generation = ++m_sweepGeneration;
    m_sweepAttemptedRevision = m_revision;
    m_sweepPending = true;
    m_sweepPanel->SetStatus("저장 연구와 권위 상태를 조회하고 있습니다.");
    UpdateControls();
    Send(
        "sweep.list", Json::object(), false, Context(),
        [this, project, generation, preferred](const Json& result)
        {
            if (m_closing || project != m_project || generation != m_sweepGeneration)
            {
                return;
            }
            m_sweepPending = false;
            m_sweepPanel->SetStudies(result, preferred);
            if (m_sweepPanel->StudyId().empty())
            {
                m_sweepUncertain = false;
                m_sweepPanel->ClearSelection("저장된 연구가 없습니다. 새 연구를 검토하여 저장하세요.");
                UpdateControls();
            }
            else
            {
                LoadSweep(m_sweepPanel->StudyId());
            }
        },
        [this, project, generation](const Json& error)
        {
            if (m_closing || project != m_project || generation != m_sweepGeneration)
            {
                return;
            }
            m_sweepPending = false;
            m_sweepPanel->ClearSelection("연구 목록 조회 실패: " + DiagnosticMessage(error));
            UpdateControls();
        });
}

void StudioFrame::LoadSweep(const std::string& id, int offset)
{
    if (!m_connected || !m_sweepSupported || m_closing || m_project.empty() || m_busy || m_sweepPending ||
        m_setupDialog || id.empty())
    {
        return;
    }
    const auto project = m_project;
    const auto generation = ++m_sweepGeneration;
    m_sweepPending = true;
    m_sweepPanel->BeginRead(id);
    UpdateControls();
    const auto failed = [this, project, generation](const Json& error)
    {
        if (m_closing || project != m_project || generation != m_sweepGeneration)
        {
            return;
        }
        m_sweepPending = false;
        m_sweepNextPoll = Clock::now() + std::chrono::seconds(3);
        m_sweepPanel->ClearSelection("연구 조회 실패: " + DiagnosticMessage(error));
        UpdateControls();
    };
    Send(
        "sweep.get", {{"study_id", id}}, false, Context(),
        [this, project, generation, id, offset, failed](const Json& result)
        {
            if (m_closing || project != m_project || generation != m_sweepGeneration)
            {
                return;
            }
            if (result.at("study_id") != id)
            {
                failed({{"message", "다른 연구의 조회 응답을 폐기했습니다."}});
                return;
            }
            m_sweepPanel->SetStudy(result);
            ShowWorkspaceJob(2, result.at("state"),
                             result.at("name").get<std::string>() + " / " + result.value("message", ""));
            Send(
                "sweep.page", {{"study_id", id}, {"offset", offset}, {"limit", 25}}, false, Context(),
                [this, project, generation, id](const Json& page)
                {
                    if (m_closing || project != m_project || generation != m_sweepGeneration)
                    {
                        return;
                    }
                    m_sweepPending = false;
                    m_sweepNextPoll = Clock::now() + std::chrono::seconds(2);
                    if (page.at("study_id") == id && m_sweepPanel->StudyId() == id)
                    {
                        m_sweepPanel->SetPage(page);
                        m_sweepUncertain = false;
                    }
                    else
                    {
                        m_sweepPanel->ClearSelection("현재 연구와 다른 후보 페이지를 폐기했습니다.");
                    }
                    UpdateControls();
                },
                failed);
        },
        failed);
}

void StudioFrame::SweepCommand(const std::string& action)
{
    if (!m_connected || m_closing || m_busy || m_sweepPending || m_sweepUncertain || m_setupDialog || !m_sweepPanel)
    {
        return;
    }
    const auto& selected = m_sweepPanel->Selection();
    if (!selected.is_object() || !selected.value("allowed_actions", Json::object()).value(action, false))
    {
        return;
    }
    const auto id = m_sweepPanel->StudyId();
    const auto project = m_project;
    Json rankRequest = {{"study_id", id}};
    if (action == "rank")
    {
        const auto options = RankingOptions(this, selected.value("ranking_targets", Json::array()),
                                            selected.value("ranking_tolerance_axes", Json::array()),
                                            selected.value("variable_labels", Json::object()));
        if (!options || m_closing || m_project != project || m_sweepPanel->StudyId() != id || m_sweepPending)
        {
            return;
        }
        rankRequest.update(*options);
        rankRequest["suggest_next"] = true;
    }
    const auto generation = ++m_sweepGeneration;
    m_sweepPending = true;
    if (action == "rank")
    {
        m_sweepPanel->SetStatus("봉인된 목표 표본으로 후보 순위를 비교하고 있습니다.");
        UpdateControls();
        Send("sweep.rank", rankRequest, false, Context(),
             [this, project, generation, id](const Json& result)
             {
                 if (m_closing || project != m_project || generation != m_sweepGeneration)
                 {
                     return;
                 }
                 m_sweepPending = false;
                 UpdateControls();
                 if (result.at("study_id") != id)
                 {
                     m_sweepPanel->SetStatus("순위 응답이 선택한 연구와 다릅니다.");
                     return;
                 }
                 const auto ranked = result.at("ranked").get<int>();
                 const auto total = result.at("total").get<int>();
                 const auto counts = result.at("excluded");
                 const auto summary = wxString::Format(Display("순위 %d / %d개. 미완료 %d, 목표 없음 %d, 평가 없음 %d, 표본 미확인 %d."),
                     ranked, total, counts.value("not_completed", 0), counts.value("no_targets", 0),
                     counts.value("unavailable_assessment", 0), counts.value("incomplete_targets", 0));
                 m_sweepPanel->SetStatus(summary.ToStdString(wxConvUTF8));
                 if (ranked == 0)
                 {
                     return;
                 }
                 CallAfter([this, project, generation, id, result, summary]()
                 {
                     if (m_closing || project != m_project || generation != m_sweepGeneration || m_sweepPanel->StudyId() != id)
                     {
                         return;
                     }
                     wxArrayString labels;
                     const auto& targets = result.at("targets");
                     const auto& rows = result.at("items");
                     const auto tolerance = result.value("tolerance_analysis", Json::object());
                     const auto corners = tolerance.value("corner_ordinals", Json::array());
                     const auto next = result.value("next_candidate", Json::object());
                     const bool canSuggest = next.value("status", std::string()) == "proposed";
                     if (canSuggest)
                     {
                         labels.Add(wxString::Format(Display("다음 후보 검토 / %s %s / 후보 %d와 %d 사이"),
                             Display(next.at("text")), Display(next.at("unit")),
                             next.at("basis_ordinal").get<int>() + 1, next.at("neighbor_ordinal").get<int>() + 1));
                     }
                     for (const auto& row : rows)
                     {
                         auto label = wxString::Format(Display("%d그룹 / 후보 %d"),
                             row.at("front").get<int>(), row.at("ordinal").get<int>() + 1);
                         if (!tolerance.empty())
                         {
                             const auto ordinal = row.at("ordinal").get<int>();
                             if (ordinal == tolerance.at("nominal_ordinal"))
                             {
                                 label += Display(" / 공칭");
                             }
                             else if (std::find(corners.begin(), corners.end(), ordinal) != corners.end())
                             {
                                 label += Display(" / 모서리");
                             }
                         }
                         if (row.contains("weighted_score"))
                         {
                             label += wxString::Format(Display(" / 가중 점수 %.2f%%"),
                                 row.at("weighted_score").get<double>() * 100);
                         }
                         const auto& scores = row.at("target_scores");
                         const std::size_t limit = std::min<std::size_t>(3, scores.size());
                         for (std::size_t index = 0; index < limit; ++index)
                         {
                             label += "  |  " + Display(targets.at(index).at("name").get<std::string>()).Left(28) +
                                      wxString::Format(" %.1f%%", scores.at(index).get<double>() * 100);
                         }
                         if (scores.size() > limit)
                         {
                             label += wxString::Format(Display("  |  외 %zu개"), scores.size() - limit);
                         }
                         labels.Add(label);
                     }
                     auto explanation = summary + Display("\n각 목표에서 기준별 통과율의 최솟값을 비교합니다.");
                     if (result.contains("weights"))
                     {
                         explanation += Display("\n가중치 비율");
                         const auto& weights = result.at("weights");
                         const auto visible = std::min<std::size_t>(4, weights.size());
                         for (std::size_t index = 0; index < visible; ++index)
                         {
                             explanation += " | " + Display(targets.at(index).at("name").get<std::string>()).Left(28) +
                                 wxString::Format(" %.2f%%", weights.at(index).at("normalized_weight").get<double>() * 100);
                         }
                         if (weights.size() > visible)
                         {
                             explanation += wxString::Format(Display(" | 외 %zu개"), weights.size() - visible);
                         }
                     }
                     if (!tolerance.empty())
                     {
                         const auto missing = tolerance.at("missing_corner_ordinals").size();
                         explanation += wxString::Format(Display("\n공칭 후보 %d | 모서리 평가 %zu/%zu"),
                             tolerance.at("nominal_ordinal").get<int>() + 1, corners.size() - missing, corners.size());
                         if (missing)
                         {
                             explanation += Display(" | 누락으로 최악값 미확정");
                         }
                         if (tolerance.contains("discrete_probability"))
                         {
                             const auto& probability = tolerance.at("discrete_probability");
                             const auto& limits = probability.at("pass_probability_bounds");
                             const auto source = probability.value("source_label", std::string());
                             if (!source.empty())
                             {
                                 explanation += Display("\n후보 조합 가중치 / ") + Display(source).Left(72);
                             }
                             explanation += wxString::Format(Display("\n가정한 이산 분포의 전체 목표 통과 %.2f~%.2f%% | 미확인 %.2f%%"),
                                 limits.at(0).get<double>() * 100, limits.at(1).get<double>() * 100,
                                 probability.at("unresolved_mass").get<double>() * 100);
                         }
                         const auto& objective = tolerance.at("targets");
                         const auto axisLabels = m_sweepPanel->Selection().value("variable_labels", Json::object());
                         for (std::size_t i = 0; i < std::min<std::size_t>(4, objective.size()); ++i)
                         {
                             const auto& minimum = objective.at(i).at("complete_corner_score");
                             const auto& nominal = objective.at(i).at("nominal_score");
                             const auto percent = [](const Json& score)
                             {
                                 return score.is_null() ? Display("미정") : wxString::Format("%.1f%%", score.get<double>() * 100);
                             };
                             explanation += "\n" + Display(targets.at(i).at("name").get<std::string>()).Left(28) +
                                 Display(" | 공칭 ") + percent(nominal) + Display(" | 모서리 최저 ") + percent(minimum);
                             const auto response = objective.at(i).value("s11_response", Json());
                             if (response.is_null() || response.at("axes").empty())
                             {
                                 continue;
                             }
                             const auto& first = response.at("axes").front();
                             if (first.at("maximum_abs_delta_db").is_null())
                             {
                                 explanation += Display(" | S11 변화 미정");
                             }
                             else
                             {
                                 const auto key = first.at("kind").get<std::string>() + ":" + first.at("id").get<std::string>();
                                 explanation += wxString::Format(Display("\n%.8g Hz S11 변화 최대 / %s %.3g dB"),
                                     response.at("frequency_hz").get<double>(),
                                     Display(axisLabels.value(key, std::string("연구 변수"))).Left(28),
                                     first.at("maximum_abs_delta_db").get<double>());
                             }
                             const auto pairs = response.value("pair_interactions", Json::array());
                             if (!pairs.empty())
                             {
                                 const auto& interaction = pairs.front();
                                 if (interaction.at("complete").get<bool>())
                                 {
                                     const auto label = [&axisLabels](const Json& axis)
                                     {
                                         const auto key = axis.at("kind").get<std::string>() + ":" +
                                             axis.at("id").get<std::string>();
                                         return Display(axisLabels.value(key, std::string("연구 변수"))).Left(21);
                                     };
                                     const auto& axes = interaction.at("axes");
                                     explanation += wxString::Format(Display("\n두 변수 교호 효과 / %s + %s / %.3g dB"),
                                         label(axes.at(0)), label(axes.at(1)), interaction.at("maximum_abs_db").get<double>());
                                 }
                                 const auto incomplete = std::count_if(pairs.begin(), pairs.end(), [](const Json& pair)
                                 {
                                     return !pair.at("complete").get<bool>();
                                 });
                                 if (incomplete)
                                 {
                                     explanation += wxString::Format(Display("\n직접 표본이 부족한 변수 쌍 %zu개"),
                                         static_cast<std::size_t>(incomplete));
                                 }
                             }
                         }
                     }
                     if (!canSuggest)
                     {
                         explanation += Display("\n평가를 마친 한 축 이웃 사이에 새 후보를 만들 수 있는 구간이 없습니다.");
                     }
                     explanation += Display("\n후보의 평가를 열거나 다음 후보를 새 연구로 검토할 수 있습니다.");
                     wxSingleChoiceDialog dialog(this, explanation, Display("목표별 후보 순위"), labels);
                     dialog.SetName("sweep.rank.dialog");
                     if (dialog.ShowModal() == wxID_OK && m_sweepPanel->StudyId() == id)
                     {
                         const int selection = dialog.GetSelection();
                         if (canSuggest && selection == 0)
                         {
                             ReviewNextSweepCandidate(next);
                         }
                         else if (selection >= 0)
                         {
                             OpenSweepResult(rows.at(selection - static_cast<int>(canSuggest)).at("ordinal").get<int>());
                         }
                     }
                 });
             },
             [this, project, generation](const Json& error)
             {
                 if (!m_closing && project == m_project && generation == m_sweepGeneration)
                 {
                     m_sweepPending = false;
                     m_sweepPanel->SetStatus("후보 순위 조회 실패. " + DiagnosticMessage(error));
                     UpdateControls();
                 }
             });
        return;
    }
    if (action == "replay")
    {
        m_sweepPanel->SetStatus("보존한 설계 개정에서 연구 후보를 다시 검토하고 있습니다.");
        UpdateControls();
        Send("sweep.replay_preview", {{"study_id", id}}, false, Context(),
             [this, project, generation, id](const Json& result)
             {
                 if (m_closing || project != m_project || generation != m_sweepGeneration)
                 {
                     return;
                 }
                 m_sweepPending = false;
                 UpdateControls();
                 if (result.at("study_id") != id)
                 {
                     m_sweepPanel->SetStatus("재검토 응답이 선택한 연구와 다릅니다.");
                     return;
                 }
                 static constexpr std::array<std::pair<const char*, const char*>, 6> checks{{
                     {"normalized_specification", "정규 입력"}, {"network_sources", "회로 자료"},
                     {"candidate_count", "후보 수"}, {"solver_runtime", "솔버 환경"},
                     {"calculation_engine", "계산 엔진"}, {"review_hash", "검토 해시"}}};
                 std::string text = result.at("matches").get<bool>() ? "보존 연구와 입력 검토 일치" : "보존 연구와 입력 검토에 차이가 있습니다.";
                 text += " / 후보 " + result.at("counts").at("total").dump() + "개";
                 for (const auto& [key, label] : checks)
                 {
                     if (!result.at("checks").at(key).get<bool>())
                     {
                         text += " / " + std::string(label) + " 다름";
                     }
                 }
                 text += "\n보존 개정 " + result.at("revision_id").get<std::string>();
                 m_sweepPanel->SetStatus(text);
             },
             [this, project, generation](const Json& error)
             {
                 if (!m_closing && project == m_project && generation == m_sweepGeneration)
                 {
                     m_sweepPending = false;
                     m_sweepPanel->SetStatus("보존 입력 재검토 실패. " + DiagnosticMessage(error));
                     UpdateControls();
                 }
             });
        return;
    }
    if (action == "export" || action == "recipe")
    {
        const bool recipe = action == "recipe";
        const std::string label = recipe ? "계산 명세" : "후보 CSV";
        m_sweepPanel->SetStatus("봉인된 " + label + " 자료를 읽고 있습니다.");
        UpdateControls();
        Send(recipe ? "sweep.recipe" : "sweep.export", {{"study_id", id}}, false, Context(),
             [this, project, generation, id, recipe, label](const Json& result)
             {
                 if (m_closing || project != m_project || generation != m_sweepGeneration)
                 {
                     return;
                 }
                 m_sweepPending = false;
                 UpdateControls();
                 if (result.at("study_id") != id)
                 {
                     m_sweepPanel->SetStatus("내보내기 응답이 선택한 연구와 다릅니다.");
                     return;
                 }
                 const auto contents = recipe ? result.dump(2) + "\n" : result.at("csv").get<std::string>();
                 CallAfter([this, project, generation, id, recipe, label, contents]()
                 {
                     if (m_closing || project != m_project || generation != m_sweepGeneration)
                     {
                         return;
                     }
                     wxFileDialog dialog(this, Display(label + " 저장"), wxEmptyString,
                                         Display("sweep-" + id.substr(0, 8) + (recipe ? "-recipe.json" : ".csv")),
                                         Display(recipe ? "JSON (*.json)|*.json" : "CSV (*.csv)|*.csv"), wxFD_SAVE);
                     if (dialog.ShowModal() != wxID_OK)
                     {
                         m_sweepPanel->SetStatus(label + " 저장을 취소했습니다.");
                         return;
                     }
                     try
                     {
                         WriteExternalExportFile(dialog.GetPath(), m_options.workspace, contents);
                         m_sweepPanel->SetStatus(label + " 파일을 저장했습니다.");
                     }
                     catch (const std::exception& error)
                     {
                         m_sweepPanel->SetStatus(label + " 저장 실패. " + std::string(error.what()));
                     }
                 });
             },
             [this, project, generation, label](const Json& error)
             {
                 if (!m_closing && project == m_project && generation == m_sweepGeneration)
                 {
                     m_sweepPending = false;
                     m_sweepPanel->SetStatus(label + " 조회 실패. " + DiagnosticMessage(error));
                     UpdateControls();
                 }
             });
        return;
    }
    m_sweepPanel->SetStatus(action == "cancel"
                                ? "취소를 요청합니다. 실제 종료를 확인하기 전에는 취소 완료로 표시하지 않습니다."
                                : "연구 제어 응답을 기다리고 있습니다.");
    UpdateControls();
    Send(
        "sweep." + action, {{"study_id", id}}, true, Context(),
        [this, project, generation, id](const Json& result)
        {
            if (m_closing || project != m_project || generation != m_sweepGeneration)
            {
                return;
            }
            m_sweepPending = false;
            if (result.at("study_id") != id)
            {
                m_sweepUncertain = true;
                m_sweepPanel->SetStatus("제어 응답이 선택 연구와 다릅니다. 다시 실행하지 말고 상태를 조회하세요.");
                UpdateControls();
                return;
            }
            LoadSweep(id, m_sweepPanel->Offset());
        },
        [this, project, generation](const Json& error)
        {
            if (m_closing || project != m_project || generation != m_sweepGeneration)
            {
                return;
            }
            m_sweepPending = false;
            const auto code =
                error.value("data", Json::object())
                    .value("domain_code",
                           error.value("code", Json(nullptr)).is_string() ? error.at("code").get<std::string>() : "");
            m_sweepUncertain = code != "E_SCHEMA" && code != "E_CONFLICT" && code != "E_RESOURCE" &&
                               code != "E_VERSION" && code != "E_UNSUPPORTED";
            m_sweepPanel->SetStatus(
                (m_sweepUncertain ? "적용 결과가 미확정입니다. 다시 실행하지 말고 목록 / 현재 상태를 새로 읽으세요.\n"
                                  : "") +
                DiagnosticMessage(error));
            UpdateControls();
        });
}

void StudioFrame::PollSweep(Clock::time_point now)
{
    if (!m_sweepPanel || m_views->GetSelection() != 8 || m_sweepUncertain || now < m_sweepNextPoll ||
        m_sweepPanel->Selection().is_null())
    {
        return;
    }
    const auto state = m_sweepPanel->Selection().value("state", "");
    if (state == "running" || state == "resuming" || state == "cancel_requested")
    {
        LoadSweep(m_sweepPanel->StudyId(), m_sweepPanel->Offset());
    }
}
