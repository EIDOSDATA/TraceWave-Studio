/** @file @brief 같은 창에서 해석 입력 수정, 읽기 전용 검토와 실행 승인까지 이어간다. */
#include "solver_review_dialog.h"
#include "solver_mesh_view.h"
#include "solver_local_mesh_panel.h"
#include "solver_mesh_quality_panel.h"
#include "solver_cost_view.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include "studio_theme.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <ctime>
#include <map>
#include <utility>
#include <wx/display.h>
#include <wx/datetime.h>
#include <wx/tokenzr.h>
#include <set>
#include <wx/listctrl.h>
#include <wx/scrolwin.h>
#include <wx/weakref.h>
#include <wx/wx.h>

namespace
{
constexpr std::array<const char*, 3> Axes{"x", "y", "z"};

/** @brief 운영체제 숫자 서식과 무관하게 격자 수를 세 자리 단위로 읽을 수 있게 한다. */
wxString GridCount(unsigned long long value)
{
    auto digits = std::to_string(value);
    for (auto position = digits.size(); position > 3;)
    {
        position -= 3;
        digits.insert(position, 1, ',');
    }
    return Display(digits);
}

/** @brief 격자선은 화면에서 합쳐 보일 수 있어도 수치 표에서는 전부 읽을 수 있다. */
class GridCoordinates final : public wxListCtrl
{
public:
    explicit GridCoordinates(wxWindow* parent)
        : wxListCtrl(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_VIRTUAL | wxLC_SINGLE_SEL)
    {
        SetName("solver.review.coordinates");
        StudioTheme::Table(*this);
        AppendColumn(Display("순서"), wxLIST_FORMAT_RIGHT, FromDIP(48));
        AppendColumn(Display("위치 (mm)"), wxLIST_FORMAT_RIGHT, FromDIP(130));
        AppendColumn(Display("간격 (mm)"), wxLIST_FORMAT_RIGHT, FromDIP(92));
    }

    void DisplayAxis(const Json* values)
    {
        m_values = values;
        SetItemCount(values ? static_cast<long>(values->size()) : 0);
        Refresh();
    }

    /** @brief 선택 구간 첫 셀의 끝 선을 실제 좌표 표에서 보이게 한다. */
    void LocateCell(long firstLine)
    {
        SetItemState(firstLine + 1, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
        EnsureVisible(firstLine + 1);
        SetFocus();
    }

private:
    wxString OnGetItemText(long item, long column) const override
    {
        if (!m_values || item < 0 || static_cast<std::size_t>(item) >= m_values->size())
        {
            return {};
        }
        const auto index = static_cast<std::size_t>(item);
        if (column == 0)
        {
            return wxString::Format("%ld", item + 1);
        }
        if (column == 1)
        {
            return Display(m_values->at(index).dump());
        }
        if (index == 0)
        {
            return {};
        }
        return wxString::Format("%.9g", m_values->at(index).get<double>() - m_values->at(index - 1).get<double>());
    }

    const Json* m_values = nullptr;
};

/** @brief 공통 재료와 형상 구분을 사용자가 보는 역할 이름으로 바꾼다. */
std::string RoleLabel(const Json& row)
{
    static const std::map<std::string, std::string> names{
        {"dielectric", "기판 유전체"}, {"environment", "설치 부품"}, {"surface", "표면층"},
        {"void", "기계 절삭 / 공기"}, {"conductor", "시트 도체"}, {"via", "도금 비아"}, {"port", "급전"}};
    const auto role = row.at("role").get<std::string>();
    const auto found = names.find(role);
    return found == names.end() ? role : found->second;
}

/** @brief 서비스가 알려 준 설정 경로를 편집 필드의 안정 이름으로 바꾼다. */
std::string FieldFor(const std::string& path)
{
    static const std::map<std::string, std::string> aliases{
        {"settings.frequency_hz", "stop_hz"}, {"settings.frequency_hz.start", "start_hz"},
        {"settings.frequency_hz.stop", "stop_hz"}, {"settings.frequency_hz.count", "count"},
        {"settings.frequency_hz.points", "sample_points_hz"}, {"settings.field_probe", "field_probe"},
        {"settings.boundary_conditions", "boundary_conditions"}, {"settings.mesh_policy", "mesh_policy"}, {"settings.mesh_policy.air_cell_mm", "air_cell_mm"},
        {"settings.mesh_policy.growth_ratio", "growth_ratio"}, {"settings.radiation", "frequency_hz"},
        {"settings.radiation.frequency_hz", "frequency_hz"}, {"mesh", "grid_mm"}, {"settings", "grid_mm"}};
    const auto item = aliases.find(path);
    if (item != aliases.end())
    {
        return item->second;
    }
    const auto field = path.rfind('.');
    return path.rfind("settings.", 0) == 0 ? path.substr(field + 1) : std::string();
}

/** @brief 두 입력에서 실제로 달라진 설정만 표시한다. */
void CompareValues(wxListCtrl& table, const Json& current, const Json& source, const std::string& path = {})
{
    static const std::map<std::string, std::string> labels{
        {"frequency_hz.start", "시작 주파수 (Hz)"}, {"frequency_hz.stop", "끝 주파수 (Hz)"},
        {"frequency_hz.count", "주파수 표본 수"}, {"frequency_hz.points", "직접 주파수 표본"}, {"grid_mm", "모델 최대 격자 간격 (mm)"},
        {"boundary_conditions", "면별 경계 조건"}, {"air_padding_mm", "외부 공기 여유 (mm)"}, {"curve_tolerance_mm", "곡선 근사 허용오차 (mm)"},
        {"feature_subdivisions", "임계 구간 최소 분할"}, {"mesh_policy.kind", "외부 공기 격자 방식"},
        {"mesh_policy.air_cell_mm", "바깥 공기 격자 간격 (mm)"}, {"mesh_policy.growth_ratio", "공기 격자 성장률"},
        {"max_timesteps", "최대 시간 단계"}, {"end_criterion", "종료 에너지 비율"},
        {"field_probe.frequency_hz", "전기장 단면 주파수 (Hz)"}, {"field_probe.x_mm", "전기장 단면 X 범위 (mm)"},
        {"field_probe.y_mm", "전기장 단면 Y 범위 (mm)"}, {"field_probe.z_mm", "전기장 단면 Z (mm)"},
        {"radiation.frequency_hz", "NF2FF 기록 주파수 (Hz)"}, {"radiation.theta_step_deg", "NF2FF theta 간격 (deg)"},
        {"radiation.phi_step_deg", "NF2FF phi 간격 (deg)"},
        {"compute_profile.kind", "계산 예산 프로필"}, {"compute_profile.num_threads", "계산 스레드"},
        {"power_balance.kind", "독립 손실 기록 방식"}, {"local_mesh", "객체별 국부 격자"}};
    if (current == source)
    {
        return;
    }
    if (current.is_object() || source.is_object())
    {
        std::set<std::string> keys;
        for (const auto* value : {&current, &source})
        {
            if (value->is_object())
            {
                for (auto item = value->begin(); item != value->end(); ++item)
                {
                    keys.insert(item.key());
                }
            }
        }
        for (const auto& key : keys)
        {
            CompareValues(table, current.contains(key) ? current.at(key) : Json(), source.contains(key) ? source.at(key) : Json(),
                          path.empty() ? key : path + "." + key);
        }
        return;
    }
    const auto value = [](const Json& item)
    {
        return Display(item.is_null() ? "사용 안 함" : item.is_string() ? item.get<std::string>() : item.dump());
    };
    const auto label = labels.find(path);
    const long row = table.InsertItem(table.GetItemCount(), Display(label == labels.end() ? path : label->second));
    table.SetItem(row, 1, value(current));
    table.SetItem(row, 2, value(source));
}

/** @brief 변경하지 않은 수치는 과거 계획의 JSON 표현까지 그대로 보존한다. */
void PreserveUnchangedValues(const Json& original, Json& edited)
{
    if (original == edited)
    {
        edited = original;
    }
    else if (original.is_object() && edited.is_object())
    {
        for (auto value = edited.begin(); value != edited.end(); ++value)
        {
            if (original.contains(value.key()))
            {
                PreserveUnchangedValues(original.at(value.key()), value.value());
            }
        }
    }
    else if (original.is_array() && edited.is_array() && original.size() == edited.size())
    {
        for (std::size_t index = 0; index < edited.size(); ++index)
        {
            PreserveUnchangedValues(original.at(index), edited.at(index));
        }
    }
}

class SolverReviewDialog final : public wxDialog
{
public:
    SolverReviewDialog(wxWindow* parent, const std::string& revision, Json& draft, const Json& catalog,
                       const std::string& resultId, Studio::SolverReviewRequest request,
                       Studio::SolverPropertyAvailable propertyAvailable)
        : wxDialog(parent, wxID_ANY, Display("해석 전 검토"), wxDefaultPosition, wxDefaultSize,
                   wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER),
          m_revision(revision), m_draft(draft), m_catalog(catalog), m_request(std::move(request)),
          m_propertyAvailable(std::move(propertyAvailable))
    {
        SetName("solver.preview.dialog");
        StudioTheme::ApplyTypography(*this);
        StudioTheme::BindSurface(*this);
        const int pad = FromDIP(StudioTheme::PanelPadding);
        auto* root = new wxBoxSizer(wxVERTICAL);
        auto* heading = new wxStaticText(this, wxID_ANY, Display("해석 조건, 격자와 포함 형상"));
        StudioTheme::Title(*heading);
        root->Add(heading, 0, wxLEFT | wxTOP, pad);
        m_status = new wxStaticText(this, wxID_ANY, wxEmptyString);
        m_status->SetName("solver.review.status");
        root->Add(m_status, 0, wxEXPAND | wxALL, pad);
        m_book = new StudioNotebook(this);
        root->Add(m_book, 1, wxEXPAND | wxLEFT | wxRIGHT, pad);
        BuildInputs();
        BuildMeshPage();
        BuildModelPage();
        BuildConditions();
        m_output = new wxTextCtrl(Page("종료 / 기록 출력"), wxID_ANY, wxEmptyString, wxDefaultPosition,
                                  wxDefaultSize, wxTE_MULTILINE | wxTE_READONLY);
        m_output->SetName("solver.review.output");
        m_output->GetParent()->GetSizer()->Add(m_output, 1, wxEXPAND | wxALL, pad);
        m_localPage = m_book->GetPageCount();
        auto* local = Page("국부 격자");
        m_local = new SolverLocalMeshPanel(local, m_catalog.value("local_mesh_targets", Json::array()),
            [this]() { Invalidate(); },
            [this](int axis, const std::array<double, 2>& bounds, long firstLine, bool applied)
            {
                SetGridRepair({});
                LocateBand(axis, bounds, firstLine, applied);
                const auto status = wxString::Format(Display("국부 격자 %s축 %.8g ~ %.8g mm / %s"),
                    Display(std::string(1, "XYZ"[axis])), bounds[0], bounds[1],
                    Display(applied ? "적용 경계" : "상위 규칙이 적용된 경계"));
                SetStatus(Utf8(status));
            });
        local->GetSizer()->Add(m_local, 1, wxEXPAND);
        auto* quality = Page("격자 품질");
        m_quality = new SolverMeshQualityPanel(quality,
            [this](const Studio::MeshQuality::Report& report, const Studio::MeshQuality::Finding& row,
                   const wxString& setting)
            {
                const auto bounds = report.Bounds(row.worst);
                std::optional<SolverMeshBand> comparison;
                if (row.cross)
                {
                    comparison = SolverMeshBand{row.cross->axis, report.Bounds(*row.cross)};
                }
                if (row.zone != Studio::MeshQuality::Zone::Model)
                {
                    m_full->SetValue(true);
                }
                SetGridRepair(row.setting);
                LocateBand(row.worst.axis, bounds, static_cast<long>(row.worst.first), false, comparison);
                SetStatus(Utf8(wxString::Format(Display("격자 품질 %s축 %.8g ~ %.8g mm | 확인할 설정 %s"),
                    Display(std::string(1, "XYZ"[row.worst.axis])), bounds[0], bounds[1], setting)));
            },
            [this](const std::string& path) { FocusReviewSetting(path); });
        quality->GetSizer()->Add(m_quality, 1, wxEXPAND);
        LoadFields(m_draft);

        m_issueList = new wxChoice(this, wxID_ANY);
        m_issueList->SetName("solver.review.issues");
        m_issueList->Hide();
        m_issueList->Bind(wxEVT_CHOICE, [this](wxCommandEvent&) { SelectIssue(); });
        root->Add(m_issueList, 0, wxEXPAND | wxLEFT | wxRIGHT, pad);
        auto* actions = new wxBoxSizer(wxHORIZONTAL);
        auto* back = new wxButton(this, wxID_ANY, Display("조건 입력으로"));
        back->SetName("solver.review.back");
        StudioTheme::Button(*back);
        back->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { FocusInput("grid_mm"); });
        actions->Add(back, 0);
        m_jump = new wxButton(this, wxID_ANY, Display("문제 속성으로 이동"));
        m_jump->SetName("solver.review.issue");
        StudioTheme::Button(*m_jump);
        m_jump->Hide();
        m_jump->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
        {
            if (m_repair && !m_pending)
            {
                EndModal(wxID_FORWARD);
            }
        });
        actions->Add(m_jump, 0, wxLEFT, pad);
        actions->AddStretchSpacer();
        auto* close = new wxButton(this, wxID_CANCEL, Display("닫기"));
        StudioTheme::Button(*close);
        actions->Add(close, 0);
        m_check = new wxButton(this, wxID_ANY, Display("조건 검토"));
        m_check->SetName("solver.review.request");
        StudioTheme::Button(*m_check);
        m_check->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { Review(); });
        actions->Add(m_check, 0, wxLEFT, pad);
        m_run = new wxButton(this, wxID_ANY, Display("검토한 조건으로 실행"));
        m_run->SetName("solver.review.run");
        StudioTheme::Button(*m_run, true);
        m_run->Enable(false);
        m_run->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
        {
            if (!m_result.empty() && !m_pending)
            {
                EndModal(wxID_OK);
            }
        });
        actions->Add(m_run, 0, wxLEFT, pad);
        root->Add(actions, 0, wxEXPAND | wxALL, pad);
        SetSizer(root);
        const auto area = wxDisplay(parent).GetClientArea().Deflate(FromDIP(12));
        const auto ideal = FromDIP(wxSize(1120, 770));
        SetSize(std::min(ideal.x, area.width), std::min(ideal.y, area.height));
        SetMinSize(wxSize(std::min(FromDIP(800), area.width), std::min(FromDIP(540), area.height)));
        CentreOnParent();
        SetStatus("해석 조건을 입력한 후 검토하세요.");
        for (std::size_t index = 0; !resultId.empty() && index < m_sources.size(); ++index)
        {
            if (m_sources.at(index).at("id") == resultId)
            {
                m_book->SetSelection(3);
                m_source->SetSelection(static_cast<int>(index + 1));
                SelectSource();
                break;
            }
        }
    }

    Studio::SolverReviewDecision Decision(int outcome) const
    {
        if (outcome == wxID_FORWARD)
        {
            return {Json(), "", m_repair};
        }
        if (outcome == wxID_APPLY)
        {
            return {Json(), "", std::nullopt, true};
        }
        return {m_result.at("settings"), m_saveName, std::nullopt};
    }

private:
    /** @brief 공통 작업 탭과 동일한 표면에 독립된 검토 페이지를 생성한다. */
    wxPanel* Page(const char* title)
    {
        auto* page = new wxPanel(m_book);
        StudioTheme::BindSurface(*page);
        page->SetSizer(new wxBoxSizer(wxVERTICAL));
        m_book->AddPage(page, Display(title));
        return page;
    }

    void BuildInputs()
    {
        auto* page = Page("조건 입력");
        const int pad = FromDIP(StudioTheme::PanelPadding);
        m_input = new wxScrolledWindow(page, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL);
        m_input->SetScrollRate(0, FromDIP(12));
        StudioTheme::BindSurface(*m_input);
        auto* columns = new wxBoxSizer(wxHORIZONTAL);
        const auto group = [&](const char* title)
        {
            auto* box = new wxStaticBoxSizer(wxVERTICAL, m_input, Display(title));
            columns->Add(box, 1, wxEXPAND | wxALL, pad);
            return box;
        };
        auto* frequency = group("주파수와 종료");
        Field(*frequency, "start_hz", "시작 주파수 (Hz)");
        Field(*frequency, "stop_hz", "끝 주파수 (Hz)");
        Field(*frequency, "count", "주파수 표본 수 (3~201)");
        Field(*frequency, "sample_points_hz", "직접 주파수 표본 (Hz, 쉼표, 선택)");
        m_fields.at("sample_points_hz")->SetHint(Display("비우면 시작/끝/표본 수 사용"));
        Field(*frequency, "max_timesteps", "최대 시간 단계");
        Field(*frequency, "end_criterion", "종료 에너지 비율");
        m_nf = new wxCheckBox(frequency->GetStaticBox(), wxID_ANY, Display("NF2FF 기록"));
        m_nf->SetName("solver.radiation.enabled");
        frequency->Add(m_nf, 0, wxEXPAND | wxALL, FromDIP(8));
        Field(*frequency, "frequency_hz", "방사 기록 주파수 (Hz, 쉼표로 구분)");
        Field(*frequency, "theta_step_deg", "theta 간격 (5/10/15/30 deg)");
        Field(*frequency, "phi_step_deg", "phi 간격 (5/10/15/30 deg)");
        Field(*frequency, "field_probe", "전기장 XY 단면 (선택)");
        auto* probeOrder = new wxStaticText(frequency->GetStaticBox(), wxID_ANY,
            Display("쉼표로 구분해 주파수 (Hz), X 최소/최대, Y 최소/최대, Z (mm) 입력"));
        StudioTheme::BindSecondary(*probeOrder);
        frequency->Add(probeOrder, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
        m_fields.at("field_probe")->SetHint(Display("2450000000, 2, 5, 2, 5, 2"));
        m_advanced = new wxStaticText(frequency->GetStaticBox(), wxID_ANY, wxEmptyString);
        StudioTheme::BindSecondary(*m_advanced);
        frequency->Add(m_advanced, 0, wxEXPAND | wxALL, FromDIP(8));
        m_nf->Bind(wxEVT_CHECKBOX, [this](wxCommandEvent&)
        {
            SetOptionalControls();
            Invalidate();
        });
        auto* grid = group("해석 격자");
        Field(*grid, "grid_mm", "모델 최대 격자 간격 (mm)");
        Field(*grid, "air_padding_mm", "외부 공기 여유 (mm)");
        Field(*grid, "curve_tolerance_mm", "곡선 근사 허용오차 (mm)");
        Field(*grid, "feature_subdivisions", "임계 구간 최소 분할 (1~8)");
        auto* box = grid->GetStaticBox();
        m_graded = new wxCheckBox(box, wxID_ANY, Display("외부 공기 영역에 가변 격자 사용"));
        m_graded->SetName("solver.mesh_policy");
        grid->Add(m_graded, 0, wxEXPAND | wxALL, FromDIP(8));
        Field(*grid, "air_cell_mm", "바깥 공기 격자 간격 (mm)");
        Field(*grid, "growth_ratio", "공기 격자 성장률 (1.05~1.5)");
        auto* note = new wxStaticText(box, wxID_ANY, Display("가변 격자에서 공기 여유는 바깥 격자 간격의 정수배이며 최소 12배입니다."));
        StudioTheme::BindSecondary(*note);
        note->Wrap(FromDIP(300));
        grid->Add(note, 0, wxEXPAND | wxALL, FromDIP(8));
        m_graded->Bind(wxEVT_CHECKBOX, [this](wxCommandEvent&)
        {
            SetOptionalControls();
            Invalidate();
        });
        auto* boundaries = group("해석 영역의 외벽");
        const std::array<const char*, 6> faces{"X 최소", "X 최대", "Y 최소", "Y 최대", "Z 최소", "Z 최대"};
        auto* rows = new wxFlexGridSizer(2, FromDIP(6), FromDIP(12));
        rows->AddGrowableCol(1);
        for (std::size_t i = 0; i < faces.size(); ++i)
        {
            auto* label = new wxStaticText(boundaries->GetStaticBox(), wxID_ANY, Display(faces[i]));
            rows->Add(label, 0, wxALIGN_CENTER_VERTICAL);
            auto* choice = new wxChoice(boundaries->GetStaticBox(), wxID_ANY);
            choice->SetName(Display(std::string(faces[i]) + " 경계"));
            for (const auto* mode : {"PML_8", "MUR", "PEC", "PMC"})
            {
                choice->Append(Display(mode));
            }
            choice->SetSelection(0);
            choice->Bind(wxEVT_CHOICE, [this](wxCommandEvent&)
            {
                Invalidate();
            });
            m_boundary[i] = choice;
            rows->Add(choice, 1, wxEXPAND);
        }
        boundaries->Add(rows, 0, wxEXPAND | wxALL, FromDIP(8));
        m_input->SetSizer(columns);
        page->GetSizer()->Add(m_input, 1, wxEXPAND);
    }

    /** @brief 과거 조건 비교와 새 이름 저장을 같은 검토 창에서 수행한다. */
    void BuildConditions()
    {
        auto* page = Page("조건 저장 / 재사용");
        const int gap = FromDIP(StudioTheme::InputGap);
        auto* layout = page->GetSizer();
        m_source = new wxChoice(page, wxID_ANY);
        m_source->SetName("solver.conditions.source");
        m_source->Append(Display("비교할 저장 조건 또는 과거 결과 선택"));
        for (const auto& row : m_catalog.at("saved"))
        {
            m_sources.push_back(row);
            m_source->Append(Display("저장 조건 / " + row.at("name").get<std::string>()));
        }
        for (const auto& row : m_catalog.at("results"))
        {
            m_sources.push_back(row);
            const wxDateTime time(static_cast<time_t>(row.at("snapshot_time").get<double>()));
            const auto label = "과거 결과 / " + row.at("name").get<std::string>() + " / " +
                Utf8(time.Format("%Y-%m-%d %H:%M:%S")) + " / " + row.at("id").get<std::string>().substr(0, 8);
            m_source->Append(Display(label));
        }
        m_source->SetSelection(0);
        layout->Add(m_source, 0, wxEXPAND | wxALL, gap);
        m_summary = new wxStaticText(page, wxID_ANY, Display("저장 조건이나 과거 결과를 선택하면 현재 입력과 비교합니다."));
        m_summary->SetName("solver.conditions.summary");
        StudioTheme::BindSecondary(*m_summary);
        layout->Add(m_summary, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, gap);
        m_comparison = new wxListCtrl(page, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_SINGLE_SEL);
        m_comparison->SetName("solver.conditions.diff");
        StudioTheme::Table(*m_comparison);
        m_comparison->AppendColumn(Display("변경 항목"), wxLIST_FORMAT_LEFT, FromDIP(225));
        m_comparison->AppendColumn(Display("현재 입력"), wxLIST_FORMAT_LEFT, FromDIP(225));
        m_comparison->AppendColumn(Display("선택한 조건"), wxLIST_FORMAT_LEFT, FromDIP(240));
        layout->Add(m_comparison, 1, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, gap);

        m_load = new wxButton(page, wxID_ANY, Display("선택 조건 불러오기"));
        m_load->SetName("solver.conditions.apply");
        StudioTheme::Button(*m_load);
        m_load->Disable();
        auto* sourceActions = new wxBoxSizer(wxHORIZONTAL);
        sourceActions->Add(m_load, 0, wxRIGHT, gap);
        m_previousConfig = new wxButton(page, wxID_ANY, Display("이전 비교"));
        m_nextConfig = new wxButton(page, wxID_ANY, Display("다음 비교"));
        m_previousConfig->Disable();
        m_nextConfig->Disable();
        sourceActions->Add(m_previousConfig, 0, wxRIGHT, gap);
        sourceActions->Add(m_nextConfig, 0, wxRIGHT, gap);
        auto* editPort = new wxButton(page, wxID_ANY, Display("급전 속성"));
        auto* editInstallation = new wxButton(page, wxID_ANY, Display("설치 구성 편집"));
        sourceActions->Add(editPort, 0, wxRIGHT, gap);
        sourceActions->Add(editInstallation, 0);
        layout->Add(sourceActions, 0, wxLEFT | wxRIGHT | wxBOTTOM, gap);
        const auto targets = m_catalog.value("local_mesh_targets", Json::array());
        const auto found = std::find_if(targets.begin(), targets.end(), [](const Json& item)
        {
            return item.value("kind", "") == "port";
        });
        const std::string path = found == targets.end() ? "" : "ports." + found->at("id").get<std::string>() + ".resistance";
        editPort->Enable(!path.empty() && m_propertyAvailable(path));
        editPort->Bind(wxEVT_BUTTON, [this, path](wxCommandEvent&)
        {
            Json draft;
            if (!m_pending && ReadSettings(draft, true))
            {
                m_draft = draft;
                m_repair = Studio::SolverRepair{path, "해석 구성의 급전 속성을 편집하세요."};
                EndModal(wxID_FORWARD);
            }
        });
        editInstallation->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
        {
            Json draft;
            if (!m_pending && ReadSettings(draft, true))
            {
                m_draft = draft;
                EndModal(wxID_APPLY);
            }
        });
        m_previousConfig->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { SelectSource(m_configurationOffset - 120); });
        m_nextConfig->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { SelectSource(m_configurationOffset + 120); });

        auto* save = new wxBoxSizer(wxHORIZONTAL);
        auto* caption = new wxStaticText(page, wxID_ANY, Display("조건 이름"));
        save->Add(caption, 0, wxALIGN_CENTER_VERTICAL | wxRIGHT, gap);
        auto* name = new wxTextCtrl(page, wxID_ANY);
        name->SetName("solver.conditions.name");
        name->SetMaxLength(96);
        save->Add(name, 1, wxALIGN_CENTER_VERTICAL | wxRIGHT, gap);
        m_save = new wxButton(page, wxID_ANY, Display("검토한 조건 저장"));
        m_save->SetName("solver.conditions.save");
        StudioTheme::Button(*m_save);
        m_save->Disable();
        save->Add(m_save, 0);
        layout->Add(save, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, gap);
        layout->Add(new wxStaticText(page, wxID_ANY, Display("조건 검토를 마치면 이름으로 저장할 수 있습니다.")),
                    0, wxLEFT | wxRIGHT | wxBOTTOM, gap);

        m_source->Bind(wxEVT_CHOICE, [this](wxCommandEvent&) { SelectSource(); });
        m_load->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
        {
            if (m_pending || m_selected.empty())
            {
                return;
            }
            ClearResult();
            LoadFields(m_selected.at("settings"));
            RefreshComparison();
            SetStatus("선택한 설정을 입력란에 불러왔습니다. 현재 설계에서 조건을 다시 검토하세요.");
            FocusInput("grid_mm");
        });
        m_save->Bind(wxEVT_BUTTON, [this, name](wxCommandEvent&)
        {
            if (m_result.empty() || m_pending)
            {
                return;
            }
            const auto value = Utf8(name->GetValue().Strip(wxString::both));
            if (value.empty())
            {
                SetStatus("저장할 해석 조건의 이름을 입력하세요.");
                name->SetFocus();
                return;
            }
            m_saveName = value;
            EndModal(wxID_SAVE);
        });
    }

    void SelectSource(int offset = 0)
    {
        m_configurationOffset = offset;
        m_previousConfig->Disable();
        m_nextConfig->Disable();
        const int selection = m_source->GetSelection() - 1;
        const auto generation = ++m_sourceGeneration;
        m_selected = Json::object();
        m_comparison->DeleteAllItems();
        m_load->Disable();
        if (selection < 0)
        {
            m_summary->SetLabel(Display("저장 조건이나 과거 결과를 선택하면 현재 입력과 비교합니다."));
            m_summary->GetParent()->Layout();
            return;
        }
        const auto& row = m_sources.at(static_cast<std::size_t>(selection));
        m_summary->SetLabel(Display("선택한 당시 개정의 구성과 해석 조건을 읽고 있습니다."));
        const wxWeakRef<SolverReviewDialog> weak(this);
        const Json query{{row.contains("settings") ? "condition_id" : "artifact_id", row.at("id")},
                         {"configuration_offset", offset}};
        m_request("solver.conditions", query,
            [weak, generation](const Json& selected)
            {
                if (weak && weak->m_sourceGeneration == generation)
                {
                    weak->m_selected = selected;
                    weak->RefreshComparison();
                }
            },
            [weak, generation](const Json& error)
            {
                if (weak && weak->m_sourceGeneration == generation)
                {
                    weak->m_summary->SetLabel(Display(DiagnosticMessage(error)));
                    weak->m_summary->GetParent()->Layout();
                }
            });
    }

    /** @brief 현재 설계의 급전/설치와 선택 결과의 출처를 수치 설정 비교와 함께 표시한다. */
    void RefreshComparison()
    {
        if (m_selected.empty())
        {
            return;
        }
        Json current;
        const bool valid = ReadSettings(current, false);
        m_comparison->Freeze();
        m_comparison->DeleteAllItems();
        if (valid)
        {
            auto source = m_selected.at("settings");
            current["feature_subdivisions"] = current.value("feature_subdivisions", 1);
            source["feature_subdivisions"] = source.value("feature_subdivisions", 1);
            CompareValues(*m_comparison, current, source);
        }
        const auto numeric = m_comparison->GetItemCount();
        const auto configuration = m_selected.value("configuration", Json::object());
        const auto valueText = [](const Json& value, bool exists)
        {
            return Display(!exists ? "항목 없음" : value.is_null() ? "미정" :
                           value.is_string() ? value.get<std::string>() : value.dump());
        };
        for (const auto& item : configuration.value("items", Json::array()))
        {
            const auto label = item.at("name").get<std::string>() + " / " + item.at("label").get<std::string>();
            const auto row = m_comparison->InsertItem(m_comparison->GetItemCount(), Display(label));
            m_comparison->SetItem(row, 1, valueText(item.at("current"), item.at("current_exists")));
            m_comparison->SetItem(row, 2, valueText(item.at("source"), item.at("source_exists")));
        }
        m_previousConfig->Enable(m_configurationOffset > 0);
        m_nextConfig->Enable(configuration.value("next_offset", Json(nullptr)).is_number_integer());
        m_comparison->Thaw();
        std::string note = valid ? "달라진 설정 " + std::to_string(numeric) + "개"
                                 : "현재 입력을 읽을 수 없습니다. 선택한 조건은 불러올 수 있습니다.";
        note += " / 급전·설치·정합 차이 " + std::to_string(configuration.value("total", 0)) + "개";
        if (configuration.contains("unavailable"))
        {
            note += "\n" + configuration.at("unavailable").get<std::string>();
        }
        const auto& own = m_catalog.at("design");
        const auto& prior = m_selected.at("design");
        const auto revision = m_selected.at("revision_id").get<std::string>();
        note += revision == m_revision ? " / 같은 설계 개정" : " / 다른 설계 개정 " + revision.substr(0, 8);
        for (const auto* kind : {"ports", "installation"})
        {
            const std::string path = kind;
            const auto key = path + "_label";
            const auto hash = path + "_sha256";
            note += "\n" + std::string(path == "ports" ? "급전  " : "설치  ") + own.at(key).get<std::string>();
            if (own.at(hash) != prior.at(hash))
            {
                note += " / 선택 조건 " + prior.at(key).get<std::string>() + " (입력 다름)";
            }
        }
        m_summary->SetLabel(Display(note));
        auto* page = m_summary->GetParent();
        m_summary->Wrap(std::max(FromDIP(480), page->GetClientSize().x - FromDIP(20)));
        page->Layout();
        m_load->Enable(!m_pending);
    }

    void Field(wxStaticBoxSizer& group, const char* key, const char* label)
    {
        auto* parent = group.GetStaticBox();
        auto* caption = new wxStaticText(parent, wxID_ANY, Display(label));
        group.Add(caption, 0, wxLEFT | wxTOP, FromDIP(8));
        auto* input = new wxTextCtrl(parent, wxID_ANY);
        input->SetName(Display(std::string("solver.") + key));
        input->SetToolTip(Display(label));
        m_fields.emplace(key, input);
        group.Add(input, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
        input->Bind(wxEVT_TEXT, [this, field = std::string(key)](wxCommandEvent&)
        {
            if (field == "sample_points_hz")
            {
                UpdateFrequencyControls();
            }
            Invalidate();
        });
    }

    void BuildMeshPage()
    {
        auto* page = Page("해석 격자");
        const int gap = FromDIP(StudioTheme::InputGap);
        m_meshSummary = new wxStaticText(page, wxID_ANY, wxEmptyString);
        m_meshSummary->SetName("solver.review.mesh_summary");
        page->GetSizer()->Add(m_meshSummary, 0, wxEXPAND | wxLEFT | wxTOP | wxRIGHT, gap);
        m_meshSettings = new wxStaticText(page, wxID_ANY, wxEmptyString);
        m_meshSettings->SetName("solver.review.mesh_settings");
        StudioTheme::BindSecondary(*m_meshSettings);
        page->GetSizer()->Add(m_meshSettings, 0, wxEXPAND | wxALL, gap);

        auto* controls = new wxBoxSizer(wxHORIZONTAL);
        m_plane = new wxChoice(page, wxID_ANY);
        m_plane->SetName("solver.review.plane");
        for (const auto* label : {"XY 형상 투영", "XZ 높이 범위", "YZ 높이 범위"})
        {
            m_plane->Append(Display(label));
        }
        m_plane->SetSelection(0);
        controls->Add(m_plane, 0, wxRIGHT, gap);
        m_full = new wxCheckBox(page, wxID_ANY, Display("전체 영역과 PML 경계"));
        m_full->SetName("solver.review.full");
        controls->Add(m_full, 0, wxALIGN_CENTER_VERTICAL);
        m_pickRegion = new wxButton(page, wxID_ANY, Display("XY 영역에서 국부 격자 추가"));
        m_pickRegion->SetName("solver.local.pick_region");
        m_pickRegion->Disable();
        controls->Add(m_pickRegion, 0, wxLEFT, gap);
        m_pickRegion->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
        {
            if (!m_result.empty() && m_local->Rules().size() < 16)
            {
                m_plane->SetSelection(0);
                m_plot->SetView(0, m_full->GetValue());
                m_plot->StartRegionPick([this](const Json& bounds) { m_local->AddFromBounds(bounds); });
                SetStatus("XY 격자에서 영역의 두 모서리를 선택하세요. Z는 모델 높이 범위를 사용합니다.");
            }
        });
        controls->AddStretchSpacer();
        m_gridRepair = new wxButton(page, wxID_ANY, Display("관련 설정으로 이동"));
        m_gridRepair->SetName("solver.review.quality_edit");
        StudioTheme::Button(*m_gridRepair);
        m_gridRepair->Hide();
        controls->Add(m_gridRepair, 0, wxRIGHT, gap);
        m_gridRepair->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { FocusReviewSetting(m_gridRepairPath); });
        controls->Add(new wxStaticText(page, wxID_ANY, Display("수치 표의 축")), 0, wxALIGN_CENTER_VERTICAL | wxRIGHT, gap);
        m_axis = new wxChoice(page, wxID_ANY);
        m_axis->SetName("solver.review.axis");
        m_axis->Append("X");
        m_axis->Append("Y");
        m_axis->Append("Z");
        m_axis->SetSelection(0);
        controls->Add(m_axis);
        page->GetSizer()->Add(controls, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, gap);

        m_intervals = new wxChoice(page, wxID_ANY);
        m_intervals->SetName("solver.review.intervals");
        m_intervals->Hide();
        page->GetSizer()->Add(m_intervals, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, gap);
        m_intervals->Bind(wxEVT_CHOICE, [this](wxCommandEvent&)
        {
            const auto selection = m_intervals->GetSelection();
            if (selection <= 0)
            {
                m_plot->Highlight({});
                SetGridRepair({});
                return;
            }
            const auto& mesh = m_result.at("mesh");
            const auto& intervals = mesh.at("interval_report").at("intervals");
            const auto index = static_cast<std::size_t>(selection - 1);
            if (index >= intervals.size())
            {
                LocateClearance(mesh.at("planar_clearances").at("clearances").at(index - intervals.size()));
                return;
            }
            const auto& row = intervals.at(index);
            const int axis = row.at("axis").get<std::string>().at(0) - 'x';
            LocateBand(axis, row.at("bounds_mm").get<std::array<double, 2>>(),
                       row.at("first_line").get<long>(), true);
            SetGridRepair(row.at("setting_path").get<std::string>());
        });

        auto* drawing = new wxBoxSizer(wxHORIZONTAL);
        m_plot = new SolverMeshView(page);
        drawing->Add(m_plot, 1, wxEXPAND | wxRIGHT, gap);
        m_coordinates = new GridCoordinates(page);
        m_coordinates->SetMinSize(FromDIP(wxSize(290, 150)));
        drawing->Add(m_coordinates, 0, wxEXPAND);
        page->GetSizer()->Add(drawing, 1, wxEXPAND | wxLEFT | wxRIGHT, gap);
        m_axisSummary = new wxStaticText(page, wxID_ANY, wxEmptyString);
        page->GetSizer()->Add(m_axisSummary, 0, wxEXPAND | wxALL, gap);
        auto* note = new wxStaticText(page, wxID_ANY,
            Display("그림은 격자와 포함 경계의 투영입니다. 측면은 높이 범위를 표시합니다. PML 안쪽은 점선입니다."));
        StudioTheme::BindSecondary(*note);
        page->GetSizer()->Add(note, 0, wxLEFT | wxRIGHT | wxBOTTOM, gap);

        m_plane->Bind(wxEVT_CHOICE, [this](wxCommandEvent&) { UpdatePlot(); });
        m_full->Bind(wxEVT_CHECKBOX, [this](wxCommandEvent&) { UpdatePlot(); });
        m_axis->Bind(wxEVT_CHOICE, [this](wxCommandEvent&) { UpdateAxis(); });
    }

    void BuildModelPage()
    {
        auto* page = Page("포함 형상");
        const int gap = FromDIP(StudioTheme::InputGap);
        m_modelSummary = new wxStaticText(page, wxID_ANY, wxEmptyString);
        m_modelSummary->SetName("solver.review.model_summary");
        page->GetSizer()->Add(m_modelSummary, 0, wxEXPAND | wxALL, gap);
        m_model = new wxListCtrl(page, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_SINGLE_SEL);
        m_model->SetName("solver.review.model");
        StudioTheme::Table(*m_model);
        m_model->AppendColumn(Display("개체"), wxLIST_FORMAT_LEFT, FromDIP(245));
        m_model->AppendColumn(Display("상태"), wxLIST_FORMAT_LEFT, FromDIP(100));
        m_model->AppendColumn(Display("해석 역할 / 제외 사유"), wxLIST_FORMAT_LEFT, FromDIP(230));
        m_model->AppendColumn(Display("계산 형상 수"), wxLIST_FORMAT_RIGHT, FromDIP(125));
        page->GetSizer()->Add(m_model, 1, wxEXPAND | wxLEFT | wxRIGHT, gap);
        m_modelDetails = new wxTextCtrl(page, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 80)),
                                       wxTE_MULTILINE | wxTE_READONLY);
        m_modelDetails->SetName("solver.review.model_details");
        page->GetSizer()->Add(m_modelDetails, 0, wxEXPAND | wxALL, gap);
        auto* locate = new wxButton(page, wxID_ANY, Display("선택한 형상을 격자에서 보기"));
        locate->SetName("solver.review.locate");
        StudioTheme::Button(*locate);
        locate->Enable(false);
        page->GetSizer()->Add(locate, 0, wxLEFT | wxBOTTOM, gap);
        locate->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { m_book->SetSelection(1); });
        m_model->Bind(wxEVT_LIST_ITEM_SELECTED, [this, locate](wxListEvent& event)
        {
            if (m_result.empty())
            {
                return;
            }
            const auto& model = m_result.at("model");
            const auto& included = model.at("included");
            const auto index = static_cast<std::size_t>(event.GetIndex());
            const bool available = index < included.size();
            locate->Enable(available);
            const auto& row = available ? included.at(index) : model.at("excluded").at(index - included.size());
            SetGridRepair({});
            m_plot->Highlight(available ? row.at("id").get<std::string>() : "");
            m_modelDetails->ChangeValue(Display(row.at("name").get<std::string>() + "\nID " +
                row.at("id").get<std::string>() + "\n" +
                (available ? "native 속성 " + row.at("native_property").get<std::string>()
                           : "해석 제외 / " + Exclusion(row))));
        });
        m_model->Bind(wxEVT_LIST_ITEM_DESELECTED, [this, locate](wxListEvent&)
        {
            locate->Enable(false);
            m_plot->Highlight("");
            m_modelDetails->Clear();
        });
    }

    static std::string Exclusion(const Json& row)
    {
        const auto reason = row.at("reason").get<std::string>();
        return reason == "unsupported_in_profile" ? "현재 해석 범위 밖" : "해석 포함 설정이 꺼져 있음";
    }

    void UpdatePlot()
    {
        m_plot->SetView(m_plane->GetSelection(), m_full->GetValue());
    }

    /** @brief 국부 규칙과 품질 경고가 모두 같은 격자와 수치 표를 이용한다. */
    void LocateBand(int axis, const std::array<double, 2>& bounds, long firstLine, bool applied,
                    std::optional<SolverMeshBand> cross = std::nullopt)
    {
        const int plane = cross ? axis + cross->axis - 1 : axis == 2 ? 1 : 0;
        m_book->SetSelection(1);
        m_plane->SetSelection(plane);
        m_axis->SetSelection(axis);
        UpdatePlot();
        UpdateAxis();
        m_plot->HighlightBand(axis, bounds, applied, cross);
        m_coordinates->LocateCell(firstLine);
    }

    /** @brief 간극이 동일 높이인지 층간인지에 따라 실제 격자 투영을 선택한다. */
    void LocateClearance(const Json& row)
    {
        const bool layered = row.contains("other_z_mm");
        const auto points = row.at("points_mm").get<std::array<std::array<double, 2>, 2>>();
        SolverMeshClearance clearance{0, points, {}};
        int axis = 0;
        if (layered)
        {
            const auto& [a, b] = points;
            const int horizontal = std::abs(a[0] - b[0]) >= std::abs(a[1] - b[1]) ? 0 : 1;
            clearance.plane = horizontal + 1;
            clearance.points = {{{a[horizontal], row.at("z_mm").get<double>()},
                                 {b[horizontal], row.at("other_z_mm").get<double>()}}};
            for (const auto& index : row.at("cells_xyz"))
            {
                const auto cell = index.get<std::array<std::size_t, 3>>();
                const std::array<std::size_t, 2> projected{cell[horizontal], cell[2]};
                if (clearance.cells.empty() || clearance.cells.back() != projected)
                {
                    clearance.cells.push_back(projected);
                }
            }
            axis = 2;
        }
        else
        {
            clearance.cells = row.at("cells_xy").get<std::vector<std::array<std::size_t, 2>>>();
        }
        m_book->SetSelection(1);
        m_plane->SetSelection(clearance.plane);
        m_full->SetValue(false);
        m_axis->SetSelection(axis);
        UpdatePlot();
        UpdateAxis();
        if (!clearance.cells.empty())
        {
            m_coordinates->LocateCell(static_cast<long>(clearance.cells.front()[layered ? 1 : 0]));
        }
        m_plot->HighlightClearance(std::move(clearance));
        const auto names = row.at("object_names").get<std::array<std::string, 2>>();
        const auto distance = row.at("distance_mm").get<double>();
        const auto height = row.at("z_mm").get<double>();
        const auto details = layered
            ? wxString::Format(Display("Z %.6g ~ %.6g mm | 층간 간극 %.6g mm, XYZ %llu셀"), height,
                               row.at("other_z_mm").get<double>(), distance,
                               static_cast<unsigned long long>(row.at("cells_xyz").size()))
            : wxString::Format(Display("Z %.6g mm | 간극 %.6g mm, XY %llu셀"), height, distance,
                               static_cast<unsigned long long>(row.at("cells_xy").size()));
        SetStatus(Utf8(Display(names[0] + " / " + names[1] + " | ") + details));
        SetGridRepair("settings.local_mesh");
    }

    void SetGridRepair(const std::string& path)
    {
        m_gridRepairPath = path;
        m_gridRepair->Show(!path.empty());
        m_gridRepair->GetParent()->Layout();
    }

    /** @brief 품질 경고나 검토 오류를 다시 조정할 수 있는 입력으로 연결한다. */
    void FocusReviewSetting(const std::string& path)
    {
        if (path.rfind("settings.local_mesh", 0) == 0)
        {
            m_book->SetSelection(m_localPage);
            m_local->FocusRule(path);
        }
        else
        {
            FocusInput(FieldFor(path));
        }
    }

    void UpdateAxis()
    {
        if (m_result.empty())
        {
            m_coordinates->DisplayAxis(nullptr);
            m_axisSummary->SetLabel(wxEmptyString);
            return;
        }
        const auto* axis = Axes.at(static_cast<std::size_t>(m_axis->GetSelection()));
        const auto& mesh = m_result.at("mesh");
        m_coordinates->DisplayAxis(&mesh.at("lines_mm").at(axis));
        const auto& values = mesh.at("axes").at(axis);
        const auto pml = values.at("pml_inner_mm").get<std::array<double, 2>>();
        const auto air = values.at("air_before_pml_mm").get<std::array<double, 2>>();
        const auto modes = values.value("boundary_modes", std::array<std::string, 2>{"PML_8", "PML_8"});
        if (modes[0] != "PML_8" || modes[1] != "PML_8")
        {
            m_axisSummary->SetLabel(wxString::Format(
                Display("셀 간격 %.8g~%.8g mm | %s %.8g / %s %.8g mm | 모델과 경계 사이 %.8g / %.8g mm"),
                values.at("min_cell_mm").get<double>(), values.at("max_cell_mm").get<double>(),
                Display(modes[0]), pml[0], Display(modes[1]), pml[1], air[0], air[1]));
            return;
        }
        m_axisSummary->SetLabel(wxString::Format(
            Display("셀 간격 %.8g~%.8g mm | PML 안쪽 %.8g / %.8g mm | 모델과 PML 사이 %.8g / %.8g mm"),
            values.at("min_cell_mm").get<double>(), values.at("max_cell_mm").get<double>(),
            pml[0], pml[1], air[0], air[1]));
    }

    void SetStatus(const std::string& message)
    {
        m_status->SetLabel(Display(message));
        m_status->Wrap(std::max(FromDIP(350), GetClientSize().x - FromDIP(26)));
        Layout();
    }

    /** @brief 직접 주파수 목록을 입력하는 동안 범위 및 균등 표본 수 입력을 잠근다. */
    void UpdateFrequencyControls()
    {
        const bool uniform = m_fields.at("sample_points_hz")->GetValue().Strip(wxString::both).empty();
        for (const auto* field : {"start_hz", "stop_hz", "count"})
        {
            m_fields.at(field)->Enable(uniform);
        }
    }

    void SetOptionalControls()
    {
        UpdateFrequencyControls();
        for (const auto* field : {"air_cell_mm", "growth_ratio"})
        {
            m_fields.at(field)->Enable(m_graded->GetValue());
        }
        for (const auto* field : {"frequency_hz", "theta_step_deg", "phi_step_deg"})
        {
            m_fields.at(field)->Enable(m_nf->GetValue());
        }
    }

    /** @brief 저장 또는 실행한 설정에서 입력을 채우고 편집 범위 밖의 옵션도 유지한다. */
    void LoadFields(const Json& settings)
    {
        const auto band = settings.value("frequency_hz", Json{{"start", 2.4e9}, {"stop", 2.4835e9}, {"count", 101}});
        wxArrayString pointLabels;
        for (const auto& point : band.value("points", Json::array()))
        {
            pointLabels.Add(wxString::Format("%.17g", point.get<double>()));
        }
        m_fields.at("sample_points_hz")->ChangeValue(wxJoin(pointLabels, ','));
        const auto mesh = settings.value("mesh_policy", Json::object());
        const auto radiation = settings.value("radiation", Json::object());
        const Json values{{"start_hz", band.at("start")}, {"stop_hz", band.at("stop")}, {"count", band.at("count")},
                          {"grid_mm", settings.value("grid_mm", 1.0)}, {"air_padding_mm", settings.value("air_padding_mm", 30.0)},
                          {"curve_tolerance_mm", settings.value("curve_tolerance_mm", .05)},
                          {"feature_subdivisions", settings.value("feature_subdivisions", 1)},
                          {"max_timesteps", settings.value("max_timesteps", 30000)}, {"end_criterion", settings.value("end_criterion", 1e-5)},
                          {"air_cell_mm", mesh.value("air_cell_mm", 6.0)}, {"growth_ratio", mesh.value("growth_ratio", 1.5)},
                          {"theta_step_deg", radiation.value("theta_step_deg", 15)}, {"phi_step_deg", radiation.value("phi_step_deg", 15)}};
        for (auto value = values.begin(); value != values.end(); ++value)
        {
            m_fields.at(value.key())->ChangeValue(Display(value.value().dump()));
        }
        wxArrayString frequencies;
        for (const auto& value : radiation.value("frequency_hz", Json::array({
                (band.at("start").get<double>() + band.at("stop").get<double>()) / 2})))
        {
            frequencies.Add(Display(value.dump()));
        }
        m_fields.at("frequency_hz")->ChangeValue(wxJoin(frequencies, ','));
        wxArrayString probeValues;
        if (settings.contains("field_probe"))
        {
            const auto& probe = settings.at("field_probe");
            for (const auto& item : {probe.at("frequency_hz"), probe.at("x_mm").at(0), probe.at("x_mm").at(1),
                                     probe.at("y_mm").at(0), probe.at("y_mm").at(1), probe.at("z_mm")})
            {
                probeValues.Add(Display(item.dump()));
            }
        }
        m_fields.at("field_probe")->ChangeValue(wxJoin(probeValues, ','));
        const auto modes = settings.value("boundary_conditions", Json::array());
        for (std::size_t i = 0; i < m_boundary.size(); ++i)
        {
            m_boundary[i]->SetStringSelection(i < modes.size() ? Display(modes[i].get<std::string>()) : "PML_8");
        }
        m_graded->SetValue(!mesh.empty());
        m_nf->SetValue(!radiation.empty());
        m_local->LoadRules(settings.value("local_mesh", Json::array()));
        m_draft = settings;
        SetOptionalControls();
        const bool useBudget = settings.contains("compute_profile");
        const bool useLoss = settings.contains("power_balance");
        m_advanced->SetLabel(Display(useBudget && useLoss ? "불러온 계산 예산 / 독립 손실 기록 사용"
            : useBudget ? "불러온 계산 예산 사용" : useLoss ? "불러온 독립 손실 기록 사용" : ""));
        m_advanced->Show(useBudget || useLoss);
        m_input->Layout();
    }

    void FocusInput(const std::string& key)
    {
        m_book->SetSelection(0);
        const auto found = m_fields.find(key);
        if (found != m_fields.end() && found->second->IsEnabled())
        {
            found->second->SetFocus();
            found->second->SelectAll();
        }
        else if (key == "boundary_conditions")
        {
            m_boundary.front()->SetFocus();
        }
        else if (key == "mesh_policy")
        {
            m_graded->SetFocus();
        }
    }

    void ClearResult()
    {
        m_plot->DisplayPlan(nullptr);
        m_pickRegion->Disable();
        m_intervals->Clear();
        m_intervals->Hide();
        m_coordinates->DisplayAxis(nullptr);
        m_result = Json::object();
        m_model->DeleteAllItems();
        m_modelDetails->Clear();
        m_local->DisplayReport(Json::object());
        m_quality->DisplayMesh(nullptr);
        SetGridRepair({});
        m_axisSummary->SetLabel(wxEmptyString);
        m_meshSummary->SetLabel(wxEmptyString);
        m_meshSettings->SetLabel(wxEmptyString);
        m_meshSummary->GetParent()->Layout();
        m_modelSummary->SetLabel(wxEmptyString);
        m_output->Clear();
        m_run->Enable(false);
        m_save->Enable(false);
        m_repair.reset();
        m_jump->Hide();
        m_issues = Json::array();
        m_issueList->Clear();
        m_issueList->Hide();
    }

    void Invalidate()
    {
        RefreshComparison();
        if (!m_result.empty() || m_repair || !m_issues.empty())
        {
            ClearResult();
            SetStatus("입력값이 바뀌었습니다. 현재 조건을 다시 검토하세요.");
        }
    }

    /** @brief 편집값을 정확히 읽고 불러온 고급 설정을 보존한다. */
    bool ReadSettings(Json& settings, bool report)
    {
        static const std::map<std::string, std::array<double, 2>> integers{
            {"count", {3, 201}}, {"max_timesteps", {1000, 200000}}, {"feature_subdivisions", {1, 8}},
            {"theta_step_deg", {5, 30}}, {"phi_step_deg", {5, 30}}};
        const auto fail = [this, report](const std::string& key, const std::string& message)
        {
            if (report)
            {
                SetStatus(Utf8(m_fields.at(key)->GetToolTipText()) + " / " + message);
                FocusInput(key);
            }
            return false;
        };
        Json values = Json::object();
        for (const auto& [key, input] : m_fields)
        {
            if (!input->IsThisEnabled() || key == "frequency_hz" || key == "sample_points_hz" || key == "field_probe")
            {
                continue;
            }
            double number = 0;
            const auto range = integers.find(key);
            const bool whole = range != integers.end();
            if (!input->GetValue().ToDouble(&number) || !std::isfinite(number) ||
                (whole && (number != std::floor(number) || number < range->second[0] || number > range->second[1])))
            {
                return fail(key, whole ? "정수 범위에 맞는 값을 입력하세요." : "유한한 수를 입력하세요.");
            }
            values[key] = whole ? Json(static_cast<int>(number)) : Json(number);
        }
        Json band;
        const auto direct = m_fields.at("sample_points_hz")->GetValue().Strip(wxString::both);
        if (direct.empty())
        {
            band = {{"start", values.at("start_hz")}, {"stop", values.at("stop_hz")}, {"count", values.at("count")}};
        }
        else
        {
            Json points = Json::array();
            wxStringTokenizer tokens(direct, ",", wxTOKEN_RET_EMPTY_ALL);
            while (tokens.HasMoreTokens())
            {
                double number = 0;
                if (!tokens.GetNextToken().Strip(wxString::both).ToDouble(&number) || !std::isfinite(number) ||
                    (!points.empty() && number <= points.back().get<double>()) || points.size() >= 201)
                {
                    return fail("sample_points_hz", "서로 다른 유한 주파수를 오름차순으로 최대 201개 입력하세요.");
                }
                points.push_back(number);
            }
            if (points.size() < 3)
            {
                return fail("sample_points_hz", "직접 주파수는 3개 이상 입력하세요.");
            }
            band = {{"start", points.front()}, {"stop", points.back()}, {"count", points.size()}, {"points", points}};
        }
        settings = m_draft;
        settings.update(Json{{"frequency_hz", band},
                             {"grid_mm", values.at("grid_mm")}, {"air_padding_mm", values.at("air_padding_mm")},
                             {"curve_tolerance_mm", values.at("curve_tolerance_mm")}, {"max_timesteps", values.at("max_timesteps")},
                             {"end_criterion", values.at("end_criterion")}});
        if (m_draft.contains("feature_subdivisions") || values.at("feature_subdivisions") != 1)
        {
            settings["feature_subdivisions"] = values.at("feature_subdivisions");
        }
        if (m_graded->GetValue())
        {
            settings["mesh_policy"] = {{"kind", "graded_air"}, {"air_cell_mm", values.at("air_cell_mm")},
                                       {"growth_ratio", values.at("growth_ratio")}};
        }
        else
        {
            settings.erase("mesh_policy");
        }
        if (m_local->Rules().empty())
        {
            settings.erase("local_mesh");
        }
        else
        {
            settings["local_mesh"] = m_local->Rules();
        }
        if (m_nf->GetValue())
        {
            Json frequencies = Json::array();
            wxStringTokenizer tokens(m_fields.at("frequency_hz")->GetValue(), ",", wxTOKEN_RET_EMPTY_ALL);
            while (tokens.HasMoreTokens())
            {
                double number = 0;
                if (!tokens.GetNextToken().Strip(wxString::both).ToDouble(&number) || !std::isfinite(number))
                {
                    return fail("frequency_hz", "주파수는 유한한 수를 쉼표로 구분해 입력하세요.");
                }
                frequencies.push_back(number);
            }
            if (frequencies.empty() || frequencies.size() > 3)
            {
                return fail("frequency_hz", "1~3개의 주파수를 입력하세요.");
            }
            Json radiation = settings.value("radiation", Json::object());
            radiation.update(Json{{"frequency_hz", frequencies}, {"theta_step_deg", values.at("theta_step_deg")},
                                  {"phi_step_deg", values.at("phi_step_deg")}});
            settings["radiation"] = radiation;
        }
        else
        {
            settings.erase("radiation");
        }
        const auto probe = m_fields.at("field_probe")->GetValue().Strip(wxString::both);
        if (probe.empty())
        {
            settings.erase("field_probe");
        }
        else
        {
            std::array<double, 6> coordinates{};
            wxStringTokenizer tokens(probe, ",", wxTOKEN_RET_EMPTY_ALL);
            for (auto& value : coordinates)
            {
                if (!tokens.HasMoreTokens() || !tokens.GetNextToken().Strip(wxString::both).ToDouble(&value) ||
                    !std::isfinite(value))
                {
                    return fail("field_probe", "주파수와 좌표 6개를 쉼표로 구분해 입력하세요.");
                }
            }
            if (tokens.HasMoreTokens())
            {
                return fail("field_probe", "주파수와 좌표 6개를 쉼표로 구분해 입력하세요.");
            }
            settings["field_probe"] = {{"frequency_hz", coordinates[0]}, {"x_mm", {coordinates[1], coordinates[2]}},
                                       {"y_mm", {coordinates[3], coordinates[4]}}, {"z_mm", coordinates[5]}};
        }
        Json modes = Json::array();
        for (const auto* choice : m_boundary)
        {
            modes.push_back(Utf8(choice->GetStringSelection()));
        }
        if (m_draft.contains("boundary_conditions") ||
            std::any_of(modes.begin(), modes.end(), [](const Json& mode) { return mode != "PML_8"; }))
        {
            settings["boundary_conditions"] = std::move(modes);
        }
        PreserveUnchangedValues(m_draft, settings);
        return true;
    }

    /** @brief 저장하거나 실행하기 전에 현재 입력으로 계획을 다시 검토한다. */
    void Review()
    {
        Json settings;
        if (m_pending || !ReadSettings(settings, true))
        {
            return;
        }
        m_draft = settings;
        ClearResult();
        m_pending = true;
        m_input->Enable(false);
        m_local->Enable(false);
        m_load->Enable(false);
        m_check->Enable(false);
        SetStatus("해석 계획과 실제 입력 격자선을 확인하고 있습니다.");
        const wxWeakRef<SolverReviewDialog> weak(this);
        m_request("solver.preview", Json{{"settings", settings}, {"include_all_diagnostics", true}},
            [weak](const Json& result)
            {
                if (weak)
                {
                    weak->Accept(result);
                }
            },
            [weak](const Json& error)
            {
                if (weak)
                {
                    weak->Reject(error);
                }
            });
    }

    void EnableInputs()
    {
        m_pending = false;
        m_input->Enable(true);
        m_local->Enable(true);
        m_check->Enable(true);
        m_load->Enable(!m_selected.empty());
        SetOptionalControls();
    }

    void Reject(const Json& error)
    {
        EnableInputs();
        const auto data = error.value("data", Json::object());
        const auto diagnostics = data.value("diagnostics", Json::array());
        if (!diagnostics.empty())
        {
            ShowIssues(diagnostics, diagnostics.size());
            return;
        }
        SetStatus(DiagnosticMessage(error));
    }

    /** @brief 목록에서 고른 진단이 다음 속성 이동의 유일한 대상이 된다. */
    void ShowIssues(const Json& diagnostics, std::size_t total)
    {
        m_issues = diagnostics;
        m_issueTotal = total;
        m_issueList->Clear();
        std::size_t index = 0;
        for (const auto& row : m_issues)
        {
            const auto path = row.value("details", Json::object()).value("field_path", std::string());
            const auto label = row.value("message_ko", std::string());
            m_issueList->Append(Display(std::to_string(++index) + " / " + label +
                                        (path.empty() ? "" : " / " + path)));
        }
        m_issueList->SetSelection(0);
        m_issueList->Show();
        SelectIssue();
    }

    void SelectIssue()
    {
        const auto index = m_issueList->GetSelection();
        if (index == wxNOT_FOUND || static_cast<std::size_t>(index) >= m_issues.size())
        {
            return;
        }
        const auto& diagnostic = m_issues.at(static_cast<std::size_t>(index));
        const auto details = diagnostic.value("details", Json::object());
        auto problem = "차단 문제 " + std::to_string(index + 1) + " / " + std::to_string(m_issueTotal) +
                       "\n" + diagnostic.value("message_ko", std::string("해석 입력을 확인하세요."));
        if (m_issues.size() < m_issueTotal)
        {
            problem += "\n앞 " + std::to_string(m_issues.size()) + "개를 표시합니다. 수정 후 다시 검토하세요.";
        }
        m_repair.reset();
        m_jump->Hide();
        const auto field = details.value("field_path", std::string());
        const bool local = field.rfind("settings.local_mesh", 0) == 0;
        if (details.contains("grid_point_limit"))
        {
            problem += " 확인된 격자점은 최소 " + details.at("grid_points_lower_bound").dump() +
                       (local ? "개입니다. 국부 목표 폭과 범위 또는 전체 격자 조건을 확인하세요."
                              : "개입니다. 격자 간격, 공기 여유와 임계 구간 분할을 확인하세요.");
        }
        if (local)
        {
            SetStatus(problem);
            FocusReviewSetting(field);
            return;
        }
        if (field.empty())
        {
            problem += " 조건을 확인한 뒤 필요하면 다시 검토하세요.";
        }
        FocusInput(FieldFor(field));
        const auto repairField = details.value("repair_field", field);
        if (m_propertyAvailable(repairField))
        {
            m_repair = Studio::SolverRepair{repairField, problem};
            m_jump->Show();
            SetStatus(problem + " 속성에서 수정한 뒤 같은 조건으로 다시 검토할 수 있습니다.");
            m_jump->SetFocus();
        }
        else
        {
            SetStatus(problem);
        }
    }

    void Accept(const Json& result)
    {
        EnableInputs();
        if (result.value("revision_id", std::string()) == m_revision && result.contains("blocking_diagnostics"))
        {
            ShowIssues(result.at("blocking_diagnostics"), result.at("blocking_total").get<std::size_t>());
            return;
        }
        if (result.value("revision_id", std::string()) != m_revision ||
            !result.contains("mesh") || !result.contains("model"))
        {
            SetStatus("현재 개정의 격자와 해석 형상을 받지 못했습니다. 프로젝트와 서비스 연결을 확인하세요.");
            FocusInput("grid_mm");
            return;
        }
        m_result = result;
        const auto& mesh = m_result.at("mesh");
        const auto& lines = mesh.at("lines_mm");
        const auto& estimate = m_result.at("estimated");
        const auto x = static_cast<unsigned long long>(lines.at("x").size());
        const auto y = static_cast<unsigned long long>(lines.at("y").size());
        const auto z = static_cast<unsigned long long>(lines.at("z").size());
        const double memory = estimate.at("estimated_memory_bytes").get<double>() / (1024.0 * 1024.0);
        const auto& settings = m_result.at("settings");
        const auto policy = settings.value("mesh_policy", Json::object());
        const auto grid = policy.empty() ? Display("외부 공기 가변 격자 끔")
            : wxString::Format(Display("가변 공기 격자 %.8g mm / 성장률 %.8g"),
                               policy.at("air_cell_mm").get<double>(), policy.at("growth_ratio").get<double>());
        m_meshSummary->SetLabel(wxString::Format(
            Display("격자선 X %llu / Y %llu / Z %llu  |  격자점 %s  |  Yee 셀 %s  |  예상 메모리 %.1f MiB"),
            x, y, z, GridCount(x * y * z),
            GridCount((x - 1) * (y - 1) * (z - 1)), memory));
        m_meshSettings->SetLabel(wxString::Format(
            Display("모델 최대 간격 %.8g mm  |  임계 구간 최소 분할 %d  |  %s"),
            settings.at("grid_mm").get<double>(), settings.value("feature_subdivisions", 1), grid));
        m_plot->DisplayPlan(&m_result);
        m_pickRegion->Enable(m_local->Rules().size() < 16);
        m_intervals->Clear();
        if (mesh.contains("interval_report"))
        {
            const auto& report = mesh.at("interval_report");
            const auto& intervals = report.at("intervals");
            m_intervals->Append(wxString::Format(Display("간극과 최소 셀 위치 %llu/%llu | 자유공간 CFL 참고 %.4g ps"),
                static_cast<unsigned long long>(intervals.size()), report.at("interval_total").get<unsigned long long>(),
                report.at("vacuum_cartesian_cfl_seconds").get<double>() * 1e12));
            for (const auto& row : intervals)
            {
                const auto kind = row.at("kind").get<std::string>();
                const char* label = kind == "minimum_cell" ? "최소 셀" : kind == "feed_gap" ? "급전 간극" :
                    kind == "surface_opening" ? "표면 개구" : kind == "via_bore" ? "비아 내경" : "국부 간극";
                m_intervals->Append(wxString::Format(Display("%s %s / %.6g mm / 교차 %d셀, 완전 %d셀"),
                    Display(label), Display(row.at("axis").get<std::string>()), row.at("width_mm").get<double>(),
                    row.at("cells").get<int>(), row.at("full_cells").get<int>()));
            }
            if (mesh.contains("planar_clearances"))
            {
                const auto& gaps = mesh.at("planar_clearances");
                const auto& rows = gaps.at("clearances");
                const auto total = gaps.at("pair_total").get<unsigned long long>();
                const auto evaluated = gaps.at("pair_evaluated").get<unsigned long long>();
                m_intervals->SetToolTip(wxString::Format(
                    Display("해석 형상 간극 %.6g mm 이내 | 검사 %llu/%llu쌍 | 표시 %llu/%llu건 | 미지원 체적 %llu개"),
                    gaps.at("search_radius_mm").get<double>(), evaluated, total,
                    static_cast<unsigned long long>(rows.size()), gaps.at("clearance_total").get<unsigned long long>(),
                    gaps.value("volume_omitted_count", 0ULL)));
                for (const auto& row : rows)
                {
                    const auto roles = row.value("object_roles", std::vector<std::string>{});
                    const auto hasRole = [&roles](const char* role)
                    {
                        return std::find(roles.begin(), roles.end(), role) != roles.end();
                    };
                    const char* label = "도체 간극";
                    if (hasRole("surface"))
                    {
                        label = "표면층 간극";
                    }
                    else if (hasRole("dielectric"))
                    {
                        label = "유전체 체적 간극";
                    }
                    else if (hasRole("via"))
                    {
                        label = "PTH 배럴 간극";
                    }
                    else if (hasRole("environment"))
                    {
                        label = "설치물 간극";
                    }
                    if (row.contains("other_z_mm"))
                    {
                        m_intervals->Append(wxString::Format(Display("%s %.6g mm / XYZ %llu셀"),
                            Display(label), row.at("distance_mm").get<double>(),
                            static_cast<unsigned long long>(row.at("cells_xyz").size())));
                    }
                    else
                    {
                        m_intervals->Append(wxString::Format(Display("%s %.6g mm / Z %.6g mm / XY %llu셀"),
                            Display(label), row.at("distance_mm").get<double>(), row.at("z_mm").get<double>(),
                            static_cast<unsigned long long>(row.at("cells_xy").size())));
                    }
                }
            }
            m_intervals->SetSelection(0);
            m_intervals->Show();
        }
        m_local->DisplayReport(mesh.value("local_mesh_report", Json::object()));
        const bool hasQuality = mesh.contains("quality_reference");
        m_quality->DisplayMesh(hasQuality ? &mesh : nullptr, &settings);
        UpdateAxis();
        FillModel();
        const std::string radiation = settings.contains("radiation") ? "NF2FF 기록 사용" : "NF2FF 기록 끔";
        const std::string loss = settings.contains("power_balance") ? "독립 손실 기록 사용" : "독립 손실 기록 요청 없음";
        wxString fieldSummary = Display("전기장 XY 단면 기록 요청 없음");
        if (m_result.contains("field_recording"))
        {
            const auto& field = m_result.at("field_recording");
            const auto& start = field.at("start_mm");
            const auto& stop = field.at("stop_mm");
            fieldSummary = wxString::Format(Display("전기장 XY 단면 %.10g Hz / X %.6g~%.6g / Y %.6g~%.6g / Z %.6g mm / %d점"),
                field.at("frequency_hz").at(0).get<double>(), start.at(0).get<double>(), stop.at(0).get<double>(),
                start.at(1).get<double>(), stop.at(1).get<double>(), start.at(2).get<double>(),
                field.at("point_count").get<int>());
        }
        const auto cost = Studio::SolverEstimateText(m_result.value("execution_estimate", Json::object()));
        m_output->ChangeValue(wxString::Format(
            Display("최대 %d 시간 단계 / 종료 에너지 비율 %.8g\n\n복소 표본, 사용한 개정과 해석 조건을 보존합니다.\n"),
            settings.at("max_timesteps").get<int>(), settings.at("end_criterion").get<double>()) +
            cost + "\n\n" + Display(radiation + "\n" + loss + "\n") + fieldSummary + Display("\n\n격자 SHA-256 " +
                    mesh.at("lines_sha256").get<std::string>() + "\n해석 입력 SHA-256 " +
                    mesh.at("case_sha256").get<std::string>() + "\n검토한 프로젝트 개정 " + m_revision));
        m_book->SetSelection(1);
        m_meshSummary->GetParent()->Layout();
        SetStatus("격자와 포함 형상 확인을 완료했습니다. 종료 / 기록 출력에서 예상 실행 비용을 확인할 수 있습니다.");
        m_run->Enable(true);
        m_save->Enable(true);
    }

    void FillModel()
    {
        const auto& model = m_result.at("model");
        const auto& included = model.at("included");
        const auto& excluded = model.at("excluded");
        m_modelSummary->SetLabel(Display("해석 포함 " + std::to_string(included.size()) +
                                        "개 / 제외 " + std::to_string(excluded.size()) + "개"));
        m_model->Freeze();
        for (const auto& row : included)
        {
            const long index = m_model->InsertItem(m_model->GetItemCount(), Display(row.at("name").get<std::string>()));
            m_model->SetItem(index, 1, Display("포함"));
            m_model->SetItem(index, 2, Display(RoleLabel(row)));
            m_model->SetItem(index, 3, Display(std::to_string(row.at("primitives").size())));
        }
        for (const auto& row : excluded)
        {
            const long index = m_model->InsertItem(m_model->GetItemCount(), Display(row.at("name").get<std::string>()));
            m_model->SetItem(index, 1, Display("제외"));
            m_model->SetItem(index, 2, Display(Exclusion(row)));
        }
        m_model->Thaw();
    }

    const std::string m_revision;
    Json& m_draft;
    const Json& m_catalog;
    Studio::SolverReviewRequest m_request;
    Studio::SolverPropertyAvailable m_propertyAvailable;
    Json m_sources = Json::array();
    Json m_selected = Json::object();
    std::size_t m_sourceGeneration = 0;
    int m_configurationOffset = 0;
    wxButton* m_previousConfig = nullptr;
    wxButton* m_nextConfig = nullptr;
    std::string m_saveName;
    std::optional<Studio::SolverRepair> m_repair;
    wxChoice* m_issueList = nullptr;
    Json m_issues = Json::array();
    std::size_t m_issueTotal = 0;
    wxChoice* m_source = nullptr;
    wxListCtrl* m_comparison = nullptr;
    wxStaticText* m_summary = nullptr;
    wxStaticText* m_advanced = nullptr;
    wxButton* m_load = nullptr;
    wxButton* m_save = nullptr;
    wxCheckBox* m_nf = nullptr;
    std::map<std::string, wxTextCtrl*> m_fields;
    Json m_result = Json::object();
    bool m_pending = false;
    wxScrolledWindow* m_input = nullptr;
    StudioNotebook* m_book = nullptr;
    std::array<wxChoice*, 6> m_boundary{};
    wxCheckBox* m_graded = nullptr;
    wxStaticText* m_status = nullptr;
    wxButton* m_check = nullptr;
    wxButton* m_jump = nullptr;
    wxButton* m_run = nullptr;
    wxTextCtrl* m_output = nullptr;
    SolverMeshView* m_plot = nullptr;
    wxChoice* m_plane = nullptr;
    wxCheckBox* m_full = nullptr;
    wxChoice* m_axis = nullptr;
    GridCoordinates* m_coordinates = nullptr;
    wxStaticText* m_meshSummary = nullptr;
    wxStaticText* m_meshSettings = nullptr;
    wxStaticText* m_axisSummary = nullptr;
    wxListCtrl* m_model = nullptr;
    wxStaticText* m_modelSummary = nullptr;
    wxTextCtrl* m_modelDetails = nullptr;
    SolverLocalMeshPanel* m_local = nullptr;
    std::size_t m_localPage = 0;
    SolverMeshQualityPanel* m_quality = nullptr;
    wxButton* m_gridRepair = nullptr;
    wxButton* m_pickRegion = nullptr;
    wxChoice* m_intervals = nullptr;
    std::string m_gridRepairPath;
};
}

std::optional<Studio::SolverReviewDecision> Studio::ShowSolverReview(wxWindow* parent, const std::string& revision,
    Json& draft, const Json& catalog, const std::string& resultId, Studio::SolverReviewRequest request,
    Studio::SolverPropertyAvailable propertyAvailable)
{
    SolverReviewDialog dialog(parent, revision, draft, catalog, resultId, std::move(request), std::move(propertyAvailable));
    const int outcome = dialog.ShowModal();
    if (outcome == wxID_OK || outcome == wxID_SAVE || outcome == wxID_FORWARD || outcome == wxID_APPLY)
    {
        return dialog.Decision(outcome);
    }
    return std::nullopt;
}
