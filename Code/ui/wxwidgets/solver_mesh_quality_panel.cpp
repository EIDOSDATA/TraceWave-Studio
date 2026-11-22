/** @file @brief 검토한 격자의 품질 기준, 실제 구간, 수정 위치를 화면에 연결한다. */
#include "solver_mesh_quality_panel.h"
#include "studio_support.h"
#include "studio_theme.h"

#include <wx/listctrl.h>
#include <wx/wx.h>

namespace
{
using Studio::MeshQuality::Finding;
using Studio::MeshQuality::Metric;
using Studio::MeshQuality::Report;
using Studio::MeshQuality::Span;
using Studio::MeshQuality::Zone;
constexpr std::array<const char*, 3> Axes{"X", "Y", "Z"};

wxString MetricName(Metric metric)
{
    switch (metric)
    {
    case Metric::MinimumWidth: return Display("최소 셀 폭");
    case Metric::MaximumWidth: return Display("최대 셀 폭");
    case Metric::Growth: return Display("인접 성장률");
    case Metric::Aspect: return Display("모델 종횡비");
    case Metric::Wavelength: return Display("파장당 셀 수");
    }
    return {};
}

wxString ZoneName(Zone zone)
{
    switch (zone)
    {
    case Zone::Model: return Display("모델");
    case Zone::Air: return Display("공기");
    case Zone::Pml: return "PML";
    case Zone::Interface: return Display("경계");
    }
    return {};
}

wxString Coordinates(const Report& report, const Span& span)
{
    const auto bounds = report.Bounds(span);
    return wxString::Format("%.8g ~ %.8g", bounds[0], bounds[1]);
}

wxString SettingName(const std::string& path)
{
    if (path.rfind("settings.local_mesh[", 0) == 0)
    {
        return Display("해당 국부 격자 조건");
    }
    if (path == "settings.mesh_policy.growth_ratio")
    {
        return Display("공기 격자 성장률");
    }
    if (path == "settings.mesh_policy.air_cell_mm")
    {
        return Display("바깥 공기 격자 간격");
    }
    if (path == "settings.feature_subdivisions")
    {
        return Display("임계 구간 최소 분할");
    }
    return Display("모델 최대 격자 간격");
}

/** @brief 큰 격자도 화면에 보이는 경고 행만 문자열로 변환한다. */
class FindingList final : public wxListCtrl
{
public:
    FindingList(wxWindow* parent, const Report& report)
        : wxListCtrl(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_VIRTUAL | wxLC_SINGLE_SEL),
          m_report(report)
    {
    }

private:
    wxString OnGetItemText(long row, long column) const override
    {
        if (row < 0 || static_cast<std::size_t>(row) >= m_report.findings.size())
        {
            return {};
        }
        const auto& finding = m_report.findings[static_cast<std::size_t>(row)];
        switch (column)
        {
        case 0: return MetricName(finding.metric);
        case 1: return Display(Axes[finding.region.axis]);
        case 2: return ZoneName(finding.zone);
        case 3: return Coordinates(m_report, finding.region);
        case 4: return wxString::Format("%.8g / %.8g", finding.observed, finding.limit);
        case 5: return SettingName(finding.setting);
        }
        return {};
    }

    const Report& m_report;
};
}

SolverMeshQualityPanel::SolverMeshQualityPanel(wxWindow* parent, Locate locate, std::function<void(const std::string&)> edit)
    : wxPanel(parent)
{
    StudioTheme::BindSurface(*this);
    const int gap = FromDIP(StudioTheme::InputGap);
    auto* root = new wxBoxSizer(wxVERTICAL);
    m_intro = new wxStaticText(this, wxID_ANY, wxEmptyString);
    m_intro->SetName("solver.quality.summary");
    StudioTheme::BindSecondary(*m_intro);
    root->Add(m_intro, 0, wxEXPAND | wxALL, gap);
    m_axes = new wxListCtrl(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 144)), wxLC_REPORT | wxLC_SINGLE_SEL);
    m_axes->SetName("solver.quality.axes");
    StudioTheme::Table(*m_axes);
    m_axes->AppendColumn(Display("축"), wxLIST_FORMAT_LEFT, FromDIP(42));
    m_axes->AppendColumn(Display("최소 폭 (mm)"), wxLIST_FORMAT_RIGHT, FromDIP(115));
    m_axes->AppendColumn(Display("최대 폭 (mm)"), wxLIST_FORMAT_RIGHT, FromDIP(115));
    m_axes->AppendColumn(Display("최대 인접 성장률"), wxLIST_FORMAT_RIGHT, FromDIP(145));
    m_axes->AppendColumn(Display("최대 모델 종횡비"), wxLIST_FORMAT_RIGHT, FromDIP(145));
    m_axes->AppendColumn(Display("최소 파장당 셀 수"), wxLIST_FORMAT_RIGHT, FromDIP(152));
    root->Add(m_axes, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, gap);
    m_findings = new FindingList(this, m_report);
    m_findings->SetName("solver.quality.findings");
    StudioTheme::Table(*m_findings);
    m_findings->AppendColumn(Display("검토 지표"), wxLIST_FORMAT_LEFT, FromDIP(116));
    m_findings->AppendColumn(Display("축"), wxLIST_FORMAT_LEFT, FromDIP(36));
    m_findings->AppendColumn(Display("영역"), wxLIST_FORMAT_LEFT, FromDIP(65));
    m_findings->AppendColumn(Display("경고 구간 (mm)"), wxLIST_FORMAT_LEFT, FromDIP(156));
    m_findings->AppendColumn(Display("최악값 / 기준"), wxLIST_FORMAT_RIGHT, FromDIP(140));
    m_findings->AppendColumn(Display("확인할 설정"), wxLIST_FORMAT_LEFT, FromDIP(188));
    root->Add(m_findings, 1, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, gap);
    m_details = new wxTextCtrl(this, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 82)),
                               wxTE_MULTILINE | wxTE_READONLY);
    m_details->SetName("solver.quality.details");
    root->Add(m_details, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, gap);

    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    m_locate = new wxButton(this, wxID_ANY, Display("격자 위치로 이동"));
    m_locate->SetName("solver.quality.locate");
    m_edit = new wxButton(this, wxID_ANY, Display("관련 설정으로 이동"));
    m_edit->SetName("solver.quality.edit");
    for (auto* button : {m_locate, m_edit})
    {
        StudioTheme::Button(*button);
        actions->Add(button, 0, wxRIGHT, gap);
    }
    root->Add(actions, 0, wxLEFT | wxRIGHT | wxBOTTOM, gap);
    SetSizer(root);
    m_findings->Bind(wxEVT_LIST_ITEM_SELECTED, [this](wxListEvent&) { UpdateSelection(); });
    m_findings->Bind(wxEVT_LIST_ITEM_DESELECTED, [this](wxListEvent&) { UpdateSelection(); });
    const auto show = [this, locate]()
    {
        if (const auto* row = Selection())
        {
            locate(m_report, *row, SettingName(row->setting));
        }
    };
    m_findings->Bind(wxEVT_LIST_ITEM_ACTIVATED, [show](wxListEvent&) { show(); });
    m_locate->Bind(wxEVT_BUTTON, [show](wxCommandEvent&) { show(); });
    m_edit->Bind(wxEVT_BUTTON, [this, edit](wxCommandEvent&)
    {
        if (const auto* row = Selection())
        {
            edit(row->setting);
        }
    });
    DisplayMesh(nullptr);
}

void SolverMeshQualityPanel::DisplayMesh(const Json* mesh, const Json* settings)
{
    const long selected = m_findings->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
    if (selected >= 0)
    {
        m_findings->SetItemState(selected, 0, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
    }
    m_axes->DeleteAllItems();
    m_report = mesh ? Studio::MeshQuality::Inspect(*mesh, *settings) : Report{};
    if (mesh)
    {
        m_intro->SetLabel(wxString::Format(
            Display("검토 경고 %zu개 | 성장률 %.6g 이하 | 모델 종횡비 %.6g 이하 | 파장당 %.6g셀 이상\n"
                    "여기 상한 %.8g Hz | 모델 파장 %.8g mm | 진공 파장 %.8g mm"),
            m_report.findings.size(), m_report.growthLimit, m_report.aspectLimit, m_report.wavelengthLimit,
            m_report.frequencyHz, m_report.modelWavelength, m_report.vacuumWavelength));
        for (int axis = 0; axis < 3; ++axis)
        {
            const auto& row = m_report.axes[axis];
            const long index = m_axes->InsertItem(axis, Display(Axes[axis]));
            const std::array<double, 5> values{row.minWidth, row.maxWidth, row.maxGrowth,
                                               row.maxAspect, row.minCellsPerWavelength};
            for (int column = 0; column < 5; ++column)
            {
                m_axes->SetItem(index, column + 1, wxString::Format("%.8g", values[column]));
            }
        }
    }
    else
    {
        m_intro->SetLabel(Display("조건을 검토하면 실제 격자의 품질과 경고 위치를 표시합니다."));
    }
    m_findings->SetItemCount(static_cast<long>(m_report.findings.size()));
    m_findings->Refresh();
    UpdateSelection();
    Layout();
}

const Finding* SolverMeshQualityPanel::Selection() const
{
    const long row = m_findings->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
    return row >= 0 && static_cast<std::size_t>(row) < m_report.findings.size()
        ? &m_report.findings[static_cast<std::size_t>(row)] : nullptr;
}

void SolverMeshQualityPanel::UpdateSelection()
{
    const auto* row = Selection();
    m_locate->Enable(row != nullptr);
    m_edit->Enable(row != nullptr);
    if (!row)
    {
        m_details->ChangeValue(Display(m_report.findings.empty() ? "" : "경고를 선택하면 최악 구간과 관련 설정을 표시합니다."));
        return;
    }
    wxString detail = wxString::Format(Display("%s축 최악 구간 %s mm. 확인할 설정은 %s입니다."),
        Display(Axes[row->worst.axis]), Coordinates(m_report, row->worst), SettingName(row->setting));
    if (row->cross)
    {
        detail += wxString::Format(Display("\n비교한 넓은 셀은 %s축 %s mm입니다. 필요하면 넓은 축의 간격을 줄여 다시 검토하세요."),
            Display(Axes[row->cross->axis]), Coordinates(m_report, *row->cross));
    }
    else if (row->metric == Metric::Growth)
    {
        const auto& lines = m_report.lines[row->worst.axis];
        const auto first = row->worst.first;
        detail += wxString::Format(Display("\n인접 폭 %.8g mm / %.8g mm. 얇은 층과 형상에 고정된 격자선도 확인하세요."),
            lines[first + 1] - lines[first], lines[first + 2] - lines[first + 1]);
    }
    else if (row->metric == Metric::Wavelength || row->metric == Metric::MaximumWidth)
    {
        detail += Display("\n해당 축의 넓은 셀 폭을 줄이고 다시 검토하세요.");
    }
    m_details->ChangeValue(detail);
}
