/** @file @brief 연구 조건과 결과 화면의 위젯 배치를 담당한다. */
#include "project_study_dialog.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/checkbox.h>
#include <wx/choice.h>
#include <wx/display.h>
#include <algorithm>
#include <initializer_list>
#include <wx/listctrl.h>
#include <wx/notebook.h>
#include <wx/panel.h>
#include <wx/scrolwin.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>

void ProjectStudyDialog::AddField(wxWindow* parent, wxFlexGridSizer* grid, const std::string& key,
                                  const std::string& label)
{
    grid->Add(new wxStaticText(parent, wxID_ANY, Display(label)), 0, wxALIGN_CENTER_VERTICAL);
    auto* input = new wxTextCtrl(parent, wxID_ANY);
    input->SetName(Display("study_" + key));
    m_fields[key] = input;
    grid->Add(input, 1, wxEXPAND);
    input->Bind(wxEVT_TEXT,
                [this](wxCommandEvent&)
                {
                    UpdateControls();
                });
}

void ProjectStudyDialog::Build()
{
    auto* root = new wxBoxSizer(wxVERTICAL);
    root->Add(
        new wxStaticText(this, wxID_ANY,
                         Display("설계의 수식과 출처를 스냅샷에 보존합니다. 물성, 제작 및 측정의 미정값은 채우지 않습니다.")),
        0, wxALL, 10);
    auto* selection = new wxBoxSizer(wxHORIZONTAL);
    m_choice = new wxChoice(this, wxID_ANY);
    selection->Add(m_choice, 1, wxEXPAND | wxRIGHT, 8);
    m_refresh = new wxButton(this, wxID_ANY, Display("연구와 현재 개정 다시 읽기"));
    selection->Add(m_refresh);
    root->Add(selection, 0, wxEXPAND | wxLEFT | wxRIGHT, 10);
    m_pages = new wxNotebook(this, wxID_ANY);
    for (const auto* title : {"격자와 해석 조건", "방사 및 독립 손실", "초기 판정 기준"})
    {
        auto* page = new wxScrolledWindow(m_pages);
        StudioTheme::BindSurface(*page);
        page->SetScrollRate(0, FromDIP(12));
        auto* outer = new wxBoxSizer(wxVERTICAL);
        auto* fields = new wxFlexGridSizer(2, FromDIP(7), FromDIP(12));
        fields->AddGrowableCol(1);
        const std::string name = title;
        if (name == "격자와 해석 조건")
        {
            m_analysisBand = new wxStaticText(page, wxID_ANY, wxEmptyString);
            outer->Add(m_analysisBand, 0, wxLEFT | wxTOP | wxRIGHT, FromDIP(10));
            for (const auto& field : std::vector<std::pair<std::string, std::string>>{
                     {"name", "새 연구 이름"},
                     {"grids", "격자 수준 (mm, 큰 값부터 쉼표로 구분, 최대 6개)"},
                     {"adaptive_memory_limit_mib", "적응 격자 메모리 상한 (MiB, 비우면 모든 수준 실행)"},
                     {"start", "시작 주파수 (예: 2.4 GHz)"},
                     {"stop", "끝 주파수 (예: 2483.5 MHz)"},
                     {"count", "포트 주파수 표본 수"},
                     {"air_padding_mm", "외부 공기 여백 (mm)"},
                     {"air_cell_mm", "외부 공기 격자 (mm)"},
                     {"growth_ratio", "공기 격자 성장률"},
                     {"curve_tolerance_mm", "곡선 근사 허용오차 (mm)"},
                     {"feature_subdivisions", "임계 구간 최소 분할 (1~8, 얇은 특징 국부 검사)"},
                     {"max_timesteps", "최대 시간 단계"},
                     {"end_criterion", "종료 에너지 비율"}})
            {
                AddField(page, fields, field.first, field.second);
            }
        }
        else if (name == "방사 및 독립 손실")
        {
            m_radiation = new wxCheckBox(page, wxID_ANY, Display("원거리 방사 패턴 계산 (NF2FF)"));
            m_losses = new wxCheckBox(page, wxID_ANY, Display("유전체·도체 손실과 전력 수지 계산"));
            m_radiationBand = new wxStaticText(page, wxID_ANY, wxEmptyString);
            outer->Add(m_radiationBand, 0, wxLEFT | wxTOP | wxRIGHT, FromDIP(10));
            outer->Add(m_radiation, 0, wxLEFT | wxRIGHT | wxTOP, FromDIP(10));
            outer->Add(m_losses, 0, wxLEFT | wxRIGHT | wxTOP, FromDIP(10));
            for (const auto& field : std::vector<std::pair<std::string, std::string>>{
                     {"frequencies", "방사 주파수 (1~3개, 낮은 값부터)"},
                     {"theta_step_deg", "극각 간격 (theta, 5/10/15/30도)"},
                     {"phi_step_deg", "방위각 간격 (phi, 5/10/15/30도)"},
                     {"box_clearance_mm", "기록 상자의 최소 기판 거리 (mm)"},
                     {"max_relative_residual", "전력 수지 상대 잔차 한계 (0.03 = 3%)"}})
            {
                AddField(page, fields, field.first, field.second);
            }
            auto* help = new wxStaticText(page, wxID_ANY,
                Display("주파수는 쉼표로 구분하세요. 예: 2.4 GHz, 2483.5 MHz (단위 생략 시 Hz).\n"
                        "전력 수지를 계산할 때는 포트가 실제로 계산하는 주파수를 사용하세요.\n"
                        "도금 관통홀(PTH) 손실은 별도로 표시합니다. 얇은 도금의 표피 깊이 정확도는 별도 검증이 필요합니다."));
            help->Wrap(FromDIP(680));
            outer->Add(help, 0, wxLEFT | wxRIGHT | wxTOP, FromDIP(10));
        }
        else
        {
            const auto section = [this, page, fields](
                                     const char* label, std::initializer_list<std::pair<const char*, const char*>> inputs)
            {
                auto* heading = new wxStaticText(page, wxID_ANY, Display(label));
                StudioTheme::Heading(*heading);
                fields->Add(heading, 0, wxTOP, FromDIP(8));
                fields->AddSpacer(0);
                for (const auto& [key, caption] : inputs)
                {
                    AddField(page, fields, key, caption);
                }
            };
            section("포트 응답과 공진",
                    {{"port_max_s11_complex_delta", "포트 복소 S11 최대 변화"},
                     {"port_max_resonance_relative_shift", "표본 공진 상대 이동 한계"}});
            section("방사 결과 변화",
                    {{"max_pattern_delta", "정규화 패턴 최대 변화"},
                     {"max_radiated_relative_delta", "방사 전력 상대 변화"},
                     {"max_directivity_delta_db", "최대 지향성 변화 (dB)"},
                     {"max_gain_delta_db", "이득 및 실현 이득 변화 (dB)"},
                     {"max_efficiency_delta", "효율 변화 (0.02 = 2%p)"},
                     {"max_s11_complex_delta", "방사 비교의 복소 S11 최대 변화"}});
            section("수치 검증과 손실",
                    {{"max_sphere_relative_error", "원방 구면 적분 상대 오차"},
                     {"max_passivity_excess", "수동성 초과 수치 예산"},
                     {"max_port_balance_relative_error", "포트 파동 항등식 상대 잔차"},
                     {"loss_max_relative_delta", "개별 손실 상대 변화 (0.02 = 2%, 최소 3수준)"},
                     {"loss_absolute_fraction_floor", "개별 손실 절대 바닥 (수용 전력 비율, 0.00001 = 0.001%p)"}});
        }
        outer->Add(fields, 0, wxEXPAND | wxALL, 10);
        page->SetSizer(outer);
        m_pages->AddPage(page, Display(title));
    }
    UpdateBandLabels();
    auto* results = new wxPanel(m_pages);
    auto* resultLayout = new wxBoxSizer(wxVERTICAL);
    m_cases =
        new wxListCtrl(results, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 140)), wxLC_REPORT | wxLC_SINGLE_SEL);
    StudioTheme::Table(*m_cases);
    int column = 0;
    for (const auto* title : {"사례", "기준 격자 (mm)", "단계", "시도 수", "완료 결과", "실제 격자점"})
    {
        m_cases->InsertColumn(column++, Display(title), wxLIST_FORMAT_LEFT, FromDIP(130));
    }
    resultLayout->Add(m_cases, 0, wxEXPAND | wxBOTTOM, 8);
    m_samples = new wxButton(results, wxID_ANY, Display("두 격자의 주파수별 포트 변화"));
    m_samples->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        ShowPortSamples();
    });
    resultLayout->Add(m_samples, 0, wxBOTTOM, FromDIP(6));
    m_details = new wxTextCtrl(results, wxID_ANY, wxEmptyString, wxDefaultPosition, wxDefaultSize,
                               wxTE_MULTILINE | wxTE_READONLY);
    m_details->SetHint(Display("저장된 연구를 선택하면 사례별 진행 상태와 전력 수지를 표시합니다."));
    resultLayout->Add(m_details, 1, wxEXPAND);
    results->SetSizer(resultLayout);
    m_pages->AddPage(results, Display("진행 및 전력 수지"));
    root->Add(m_pages, 1, wxEXPAND | wxALL, 10);
    m_status = new wxStaticText(this, wxID_ANY, Display("연구가 선택되지 않았습니다. 조건을 확인하고 새 연구를 저장하세요."));
    root->Add(m_status, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 10);
    root->Add(new wxStaticText(this, wxID_ANY,
                               Display("수정한 조건은 새 연구로 저장합니다. 기존 연구의 조건은 고정되며 창을 닫아도 "
                                       "서비스 실행은 계속됩니다.")),
              0, wxLEFT | wxRIGHT | wxBOTTOM, 10);
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    m_create = new wxButton(this, wxID_ANY, Display("새 연구 저장"));
    m_start = new wxButton(this, wxID_ANY, Display("선택 연구 실행"));
    m_resume = new wxButton(this, wxID_ANY, Display("선택 연구 재개"));
    m_cancel = new wxButton(this, wxID_ANY, Display("연구 취소"));
    for (auto* button : {m_create, m_start, m_resume, m_cancel})
    {
        actions->Add(button, 0, wxRIGHT, 8);
    }
    actions->AddStretchSpacer();
    auto* close = new wxButton(this, wxID_CLOSE, Display("닫기"));
    actions->Add(close);
    root->Add(actions, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 10);
    SetSizer(root);
    const auto available = wxDisplay(GetParent()).GetClientArea().Deflate(FromDIP(16));
    const auto minimum = FromDIP(wxSize(820, 580));
    const auto preferred = FromDIP(wxSize(1020, 740));
    SetMinSize(wxSize(std::min(minimum.x, available.width), std::min(minimum.y, available.height)));
    SetSize(wxSize(std::min(preferred.x, available.width), std::min(preferred.y, available.height)));
    CentreOnParent();
    m_create->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       CreateStudy();
                   });
    m_start->Bind(wxEVT_BUTTON,
                  [this](wxCommandEvent&)
                  {
                      Command("start");
                  });
    m_resume->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       Command("resume");
                   });
    m_cancel->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       Command("cancel");
                   });
    m_refresh->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        ReloadStudies();
                    });
    close->Bind(wxEVT_BUTTON,
                [this](wxCommandEvent&)
                {
                    Close();
                });
    m_choice->Bind(wxEVT_CHOICE,
                   [this](wxCommandEvent& event)
                   {
                       if (event.GetSelection() >= 0)
                       {
                           m_selected = m_studies.at(event.GetSelection()).at("study_id");
                           ReadSelected(true);
                       }
                   });
    m_radiation->Bind(wxEVT_CHECKBOX,
                      [this](wxCommandEvent&)
                      {
                          if (!m_radiation->GetValue())
                          {
                              m_losses->SetValue(false);
                          }
                          UpdateControls();
                      });
    m_losses->Bind(wxEVT_CHECKBOX,
                   [this](wxCommandEvent&)
                   {
                       if (m_losses->GetValue())
                       {
                           m_radiation->SetValue(true);
                       }
                       UpdateControls();
                   });
}
