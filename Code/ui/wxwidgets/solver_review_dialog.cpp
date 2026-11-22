/** @file @brief 같은 창에서 해석 입력 수정, 읽기 전용 검토와 실행 승인까지 이어간다. */
#include "solver_review_dialog.h"
#include "solver_mesh_view.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include "studio_theme.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <map>
#include <utility>
#include <wx/display.h>
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
        {"settings.mesh_policy", "mesh_policy"}, {"settings.mesh_policy.air_cell_mm", "air_cell_mm"},
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

class SolverReviewDialog final : public wxDialog
{
public:
    SolverReviewDialog(wxWindow* parent, const std::string& revision, Json& draft, Json& radiationDraft,
                       bool recordRadiation, Studio::SolverPreviewRequest request)
        : wxDialog(parent, wxID_ANY, Display("해석 전 검토"), wxDefaultPosition, wxDefaultSize,
                   wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER),
          m_revision(revision), m_draft(draft), m_radiationDraft(radiationDraft),
          m_recordRadiation(recordRadiation), m_request(std::move(request))
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
        m_output = new wxTextCtrl(Page("종료 / 기록 출력"), wxID_ANY, wxEmptyString, wxDefaultPosition,
                                  wxDefaultSize, wxTE_MULTILINE | wxTE_READONLY);
        m_output->SetName("solver.review.output");
        m_output->GetParent()->GetSizer()->Add(m_output, 1, wxEXPAND | wxALL, pad);

        auto* actions = new wxBoxSizer(wxHORIZONTAL);
        auto* back = new wxButton(this, wxID_ANY, Display("조건 입력으로"));
        back->SetName("solver.review.back");
        StudioTheme::Button(*back);
        back->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { FocusInput("grid_mm"); });
        actions->Add(back, 0);
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
    }

    const Json& ReviewedSettings() const
    {
        return m_result.at("settings");
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
        Field(*frequency, "start_hz", "시작 주파수 (Hz)", m_draft, 2.4e9);
        Field(*frequency, "stop_hz", "끝 주파수 (Hz)", m_draft, 2.4835e9);
        Field(*frequency, "count", "주파수 표본 수 (3~201)", m_draft, 101);
        Field(*frequency, "max_timesteps", "최대 시간 단계", m_draft, 30000);
        Field(*frequency, "end_criterion", "종료 에너지 비율", m_draft, 1e-5);
        if (m_recordRadiation)
        {
            Field(*frequency, "frequency_hz", "방사 기록 주파수 (Hz)", m_radiationDraft,
                  (m_draft.value("start_hz", 2.4e9) + m_draft.value("stop_hz", 2.4835e9)) / 2);
            Field(*frequency, "theta_step_deg", "theta 간격 (5/10/15/30 deg)", m_radiationDraft, 15);
            Field(*frequency, "phi_step_deg", "phi 간격 (5/10/15/30 deg)", m_radiationDraft, 15);
        }
        auto* grid = group("해석 격자");
        Field(*grid, "grid_mm", "모델 최대 격자 간격 (mm)", m_draft, 1.0);
        Field(*grid, "air_padding_mm", "외부 공기 여유 (mm)", m_draft, 30.0);
        Field(*grid, "curve_tolerance_mm", "곡선 근사 허용오차 (mm)", m_draft, 0.05);
        Field(*grid, "feature_subdivisions", "임계 구간 최소 분할 (1~8)", m_draft, 1);
        auto* box = grid->GetStaticBox();
        m_graded = new wxCheckBox(box, wxID_ANY, Display("외부 공기 영역에 가변 격자 사용"));
        m_graded->SetName("solver.mesh_policy");
        m_graded->SetValue(m_draft.value("graded_air", false));
        grid->Add(m_graded, 0, wxEXPAND | wxALL, FromDIP(8));
        Field(*grid, "air_cell_mm", "바깥 공기 격자 간격 (mm)", m_draft, 6.0);
        Field(*grid, "growth_ratio", "공기 격자 성장률 (1.05~1.5)", m_draft, 1.5);
        auto* note = new wxStaticText(box, wxID_ANY, Display("가변 격자에서 공기 여유는 바깥 격자 간격의 정수배이며 최소 12배입니다."));
        StudioTheme::BindSecondary(*note);
        note->Wrap(FromDIP(300));
        grid->Add(note, 0, wxEXPAND | wxALL, FromDIP(8));
        m_graded->Bind(wxEVT_CHECKBOX, [this](wxCommandEvent&)
        {
            SetGradedControls();
            Invalidate();
        });
        SetGradedControls();
        m_input->SetSizer(columns);
        page->GetSizer()->Add(m_input, 1, wxEXPAND);
    }

    void Field(wxStaticBoxSizer& group, const char* key, const char* label, const Json& draft, double initial)
    {
        auto* parent = group.GetStaticBox();
        auto* caption = new wxStaticText(parent, wxID_ANY, Display(label));
        group.Add(caption, 0, wxLEFT | wxTOP, FromDIP(8));
        auto* input = new wxTextCtrl(parent, wxID_ANY, wxString::Format("%.12g", draft.value(key, initial)));
        input->SetName(Display(std::string("solver.") + key));
        input->SetToolTip(Display(label));
        m_fields.emplace(key, input);
        group.Add(input, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
        input->Bind(wxEVT_TEXT, [this](wxCommandEvent&) { Invalidate(); });
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
        controls->AddStretchSpacer();
        controls->Add(new wxStaticText(page, wxID_ANY, Display("수치 표의 축")), 0, wxALIGN_CENTER_VERTICAL | wxRIGHT, gap);
        m_axis = new wxChoice(page, wxID_ANY);
        m_axis->SetName("solver.review.axis");
        m_axis->Append("X");
        m_axis->Append("Y");
        m_axis->Append("Z");
        m_axis->SetSelection(0);
        controls->Add(m_axis);
        page->GetSizer()->Add(controls, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, gap);

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

    void SetGradedControls()
    {
        for (const auto* field : {"air_cell_mm", "growth_ratio"})
        {
            m_fields.at(field)->Enable(m_graded->GetValue());
        }
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
        else if (key == "mesh_policy")
        {
            m_graded->SetFocus();
        }
    }

    void ClearResult()
    {
        m_plot->DisplayPlan(nullptr);
        m_coordinates->DisplayAxis(nullptr);
        m_result = Json::object();
        m_model->DeleteAllItems();
        m_modelDetails->Clear();
        m_axisSummary->SetLabel(wxEmptyString);
        m_meshSummary->SetLabel(wxEmptyString);
        m_meshSettings->SetLabel(wxEmptyString);
        m_meshSummary->GetParent()->Layout();
        m_modelSummary->SetLabel(wxEmptyString);
        m_output->Clear();
        m_run->Enable(false);
    }

    void Invalidate()
    {
        if (!m_result.empty())
        {
            ClearResult();
            SetStatus("입력값이 바뀌었습니다. 현재 조건을 다시 검토하세요.");
        }
    }

    /** @brief 입력된 수를 원본 단위로 읽고 정수 조건은 변환 전에 검사한다. */
    bool ReadFields(Json& ordinary, Json& radiation)
    {
        static const std::map<std::string, std::array<double, 2>> integers{
            {"count", {3, 201}}, {"max_timesteps", {1000, 200000}}, {"feature_subdivisions", {1, 8}},
            {"theta_step_deg", {5, 30}}, {"phi_step_deg", {5, 30}}};
        ordinary = m_draft;
        ordinary["graded_air"] = m_graded->GetValue();
        radiation = m_radiationDraft;
        for (const auto& [key, input] : m_fields)
        {
            if (!m_graded->GetValue() && (key == "air_cell_mm" || key == "growth_ratio"))
            {
                continue;
            }
            double value = 0;
            const auto range = integers.find(key);
            const bool integral = range != integers.end();
            if (!input->GetValue().ToDouble(&value) || !std::isfinite(value) ||
                (integral && (value != std::floor(value) || value < range->second[0] || value > range->second[1])))
            {
                const auto message = integral ? "정수 범위에 맞는 값을 입력하세요." : "유한한 수를 입력하세요.";
                SetStatus(Utf8(input->GetToolTipText()) + " / " + message);
                FocusInput(key);
                return false;
            }
            auto& target = key == "frequency_hz" || key == "theta_step_deg" || key == "phi_step_deg" ? radiation : ordinary;
            target[key] = integral ? Json(static_cast<int>(value)) : Json(value);
        }
        return true;
    }

    /** @brief 입력한 값만 기존 solver 설정 계약으로 보낸다. */
    void Review()
    {
        if (m_pending)
        {
            return;
        }
        Json values, radiation;
        if (!ReadFields(values, radiation))
        {
            return;
        }
        m_draft = values;
        m_radiationDraft = radiation;
        Json settings{{"frequency_hz", {{"start", values.at("start_hz")}, {"stop", values.at("stop_hz")},
                                        {"count", values.at("count")}}},
                      {"grid_mm", values.at("grid_mm")}, {"air_padding_mm", values.at("air_padding_mm")},
                      {"curve_tolerance_mm", values.at("curve_tolerance_mm")}, {"max_timesteps", values.at("max_timesteps")},
                      {"end_criterion", values.at("end_criterion")},
                      {"feature_subdivisions", values.at("feature_subdivisions")}};
        if (m_graded->GetValue())
        {
            settings["mesh_policy"] = {{"kind", "graded_air"}, {"air_cell_mm", values.at("air_cell_mm")},
                                       {"growth_ratio", values.at("growth_ratio")}};
        }
        if (m_recordRadiation)
        {
            settings["radiation"] = {{"frequency_hz", Json::array({radiation.at("frequency_hz")})},
                                     {"theta_step_deg", radiation.at("theta_step_deg")},
                                     {"phi_step_deg", radiation.at("phi_step_deg")}};
        }
        ClearResult();
        m_pending = true;
        m_input->Enable(false);
        m_check->Enable(false);
        SetStatus("해석 계획과 실제 입력 격자선을 확인하고 있습니다.");
        const wxWeakRef<SolverReviewDialog> weak(this);
        m_request(settings,
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
        m_check->Enable(true);
        SetGradedControls();
    }

    void Reject(const Json& error)
    {
        EnableInputs();
        const auto data = error.value("data", Json::object());
        Json details = Json::object();
        for (const auto& diagnostic : data.value("diagnostics", Json::array()))
        {
            const auto candidate = diagnostic.value("details", Json::object());
            if (candidate.contains("field_path"))
            {
                details = candidate;
                break;
            }
        }
        auto problem = DiagnosticMessage(error);
        if (details.contains("grid_point_limit"))
        {
            problem += " 확인된 격자점은 최소 " + details.at("grid_points_lower_bound").dump() +
                       "개입니다. 격자 간격, 공기 여유와 임계 구간 분할을 확인하세요.";
        }
        const auto field = details.value("field_path", std::string());
        if (field.empty())
        {
            problem += " 조건을 확인한 뒤 필요하면 다시 검토하세요.";
        }
        SetStatus(problem);
        FocusInput(FieldFor(field));
    }

    void Accept(const Json& result)
    {
        EnableInputs();
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
        UpdateAxis();
        FillModel();
        const std::string radiation = settings.contains("radiation") ? "NF2FF 기록 사용" : "NF2FF 기록 끔";
        const std::string loss = settings.contains("power_balance") ? "독립 손실 기록 사용" : "독립 손실 기록 요청 없음";
        m_output->ChangeValue(wxString::Format(
            Display("최대 %d 시간 단계 / 종료 에너지 비율 %.8g\n\n복소 표본, 사용한 개정과 해석 조건을 보존합니다.\n"),
            settings.at("max_timesteps").get<int>(), settings.at("end_criterion").get<double>()) +
            Display(radiation + "\n" + loss + "\n기본 PCB 실행의 내부 전계 / 자계는 자동으로 기록하지 않습니다.\n\n격자 SHA-256 " +
                    mesh.at("lines_sha256").get<std::string>() + "\n해석 입력 SHA-256 " +
                    mesh.at("case_sha256").get<std::string>() + "\n검토한 프로젝트 개정 " + m_revision));
        m_book->SetSelection(1);
        m_meshSummary->GetParent()->Layout();
        SetStatus("격자와 포함 형상 확인을 완료했습니다. 해석 실행 대기 중입니다.");
        m_run->Enable(true);
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
    Json& m_radiationDraft;
    const bool m_recordRadiation;
    Studio::SolverPreviewRequest m_request;
    std::map<std::string, wxTextCtrl*> m_fields;
    Json m_result = Json::object();
    bool m_pending = false;
    wxScrolledWindow* m_input = nullptr;
    StudioNotebook* m_book = nullptr;
    wxCheckBox* m_graded = nullptr;
    wxStaticText* m_status = nullptr;
    wxButton* m_check = nullptr;
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
};
}

std::optional<Json> Studio::ShowSolverReview(wxWindow* parent, const std::string& revision, Json& draft,
    Json& radiationDraft, bool recordRadiation, SolverPreviewRequest request)
{
    SolverReviewDialog dialog(parent, revision, draft, radiationDraft, recordRadiation, std::move(request));
    if (dialog.ShowModal() == wxID_OK)
    {
        return dialog.ReviewedSettings();
    }
    return std::nullopt;
}
