/** @file @brief 명시 변수/값 선택과 기존 해석 필드를 네 탭의 native 입력으로 배치한다. */
#include "sweep_dialog.h"
#include "sweep_model.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/wx.h>
#include <wx/checklst.h>
#include <wx/grid.h>
#include <wx/listctrl.h>
#include <wx/scrolwin.h>
#include <wx/spinctrl.h>
#include <wx/wrapsizer.h>
#include <algorithm>

namespace
{
void Label(wxWindow* parent, wxSizer* layout, const std::string& text)
{
    auto* label = new wxStaticText(parent, wxID_ANY, Display(text));
    label->Wrap(parent->FromDIP(800));
    layout->Add(label, 0, wxEXPAND | wxALL, parent->FromDIP(4));
}
wxButton* Button(wxWindow* parent, wxSizer* layout, const std::string& name, const std::string& label)
{
    auto* button = new wxButton(parent, wxID_ANY, Display(label));
    button->SetName(Display(name));
    StudioTheme::Button(*button);
    layout->Add(button, 0, wxALL, parent->FromDIP(4));
    return button;
}
}

void SweepDialog::BuildInterface()
{
    auto* root = new wxBoxSizer(wxVERTICAL);
    auto* heading = new wxStaticText(this, wxID_ANY, Display("새 연구 설정"));
    StudioTheme::Title(*heading);
    root->Add(heading, 0, wxALL, FromDIP(12));
    Label(this, root, "기준 원본과 출처는 그대로 보존합니다. 후보 검토 / 연구 저장 / 실제 실행은 별도 동작입니다.");
    m_pages = new StudioNotebook(this);
    for (int index = 0; index < 4; ++index)
    {
        auto* page =
            new wxScrolledWindow(m_pages, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL);
        page->SetScrollRate(0, FromDIP(16));
        StudioTheme::BindSurface(*page);
        auto* layout = new wxBoxSizer(wxVERTICAL);
        page->SetSizer(layout);
        const char* titles[] = {"유형과 변수", "해석과 대상", "실행 예산", "후보 검토"};
        if (index == 0)
        {
            BuildVariables(page, layout);
        }
        else if (index == 1)
        {
            BuildSettings(page, layout);
        }
        else if (index == 2)
        {
            BuildBudget(page, layout);
        }
        else
        {
            BuildReview(page, layout);
        }
        m_pages->AddPage(page, Display(titles[index]));
    }
    root->Add(m_pages, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    m_status = new wxStaticText(this, wxID_ANY,
                                Display("변수와 값 목록을 지정하고 후보를 검토하세요. 물성 미정값은 채우지 않습니다."));
    root->Add(m_status, 0, wxEXPAND | wxALL, FromDIP(12));
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    m_preview = Button(this, actions, "sweep.preview", "후보 검토");
    actions->AddStretchSpacer();
    m_create = Button(this, actions, "sweep.save", "새 연구 저장");
    m_close = new wxButton(this, wxID_CANCEL, Display("닫기"));
    StudioTheme::Button(*m_close);
    actions->Add(m_close, 0, wxALL, FromDIP(4));
    root->Add(actions, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    SetSizer(root);
    m_preview->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        Preview();
                    });
    m_create->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       Create();
                   });
}

void SweepDialog::BuildVariables(wxWindow* page, wxSizer* layout)
{
    auto* names = new wxFlexGridSizer(2, FromDIP(8), FromDIP(12));
    names->AddGrowableCol(1);
    Label(page, names, "연구 이름");
    m_name = new wxTextCtrl(page, wxID_ANY);
    m_name->SetName("sweep.name");
    names->Add(m_name, 1, wxEXPAND);
    Label(page, names, "연구 유형");
    m_type = new wxChoice(page, wxID_ANY);
    for (const auto* label : {"설계 변수 스윕", "수치 설정 다축 연구", "회로 소자 스윕"})
    {
        m_type->Append(Display(label));
    }
    m_type->SetName("sweep.type");
    names->Add(m_type, 1, wxEXPAND);
    layout->Add(names, 0, wxEXPAND | wxALL, FromDIP(12));
    auto* catalog = new wxBoxSizer(wxHORIZONTAL);
    m_availableVariables = new wxChoice(page, wxID_ANY);
    m_availableVariables->SetName("sweep.available-variable");
    catalog->Add(m_availableVariables, 1, wxEXPAND | wxALL, FromDIP(4));
    m_addVariable = Button(page, catalog, "sweep.add-variable", "변수 추가");
    m_removeVariable = Button(page, catalog, "sweep.remove-variable", "선택 변수 삭제");
    layout->Add(catalog, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    m_variableList = new wxListCtrl(page, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 130)),
                                    wxLC_REPORT | wxLC_SINGLE_SEL | wxLC_HRULES);
    m_variableList->SetName("sweep.variables");
    StudioTheme::Table(*m_variableList);
    m_variableList->AppendColumn(Display("변수 이름"), wxLIST_FORMAT_LEFT, FromDIP(200));
    m_variableList->AppendColumn(Display("명시 값 / 범위"), wxLIST_FORMAT_LEFT, FromDIP(650));
    layout->Add(m_variableList, 0, wxEXPAND | wxALL, FromDIP(12));
    m_variableNotice =
        new wxStaticText(page, wxID_ANY, Display("변수를 추가한 뒤 명시 값 목록 또는 범위를 입력하세요."));
    layout->Add(m_variableNotice, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    auto* inputMode = new wxBoxSizer(wxHORIZONTAL);
    m_valueMode = new wxChoice(page, wxID_ANY);
    m_valueMode->Append(Display("명시 값 목록"));
    m_valueMode->Append(Display("시작 / 끝 / 개수"));
    m_valueMode->SetSelection(0);
    m_valueMode->SetName("sweep.value-mode");
    inputMode->Add(m_valueMode, 0, wxALL, FromDIP(4));
    m_valueText = new wxTextCtrl(page, wxID_ANY);
    m_valueText->SetName("sweep.new-value");
    m_valueText->SetHint(Display("새 값"));
    inputMode->Add(m_valueText, 1, wxALL | wxEXPAND, FromDIP(4));
    m_valueUnit = new wxChoice(page, wxID_ANY);
    m_valueUnit->SetName("sweep.new-value-unit");
    inputMode->Add(m_valueUnit, 0, wxALL, FromDIP(4));
    m_valueState = new wxChoice(page, wxID_ANY);
    for (const auto* state : {"연결", "개방", "단락", "미실장"})
    {
        m_valueState->Append(Display(state));
    }
    m_valueState->SetSelection(0);
    m_valueState->SetName("sweep.new-state");
    inputMode->Add(m_valueState, 0, wxALL, FromDIP(4));
    m_addValue = Button(page, inputMode, "sweep.add-value", "값 추가");
    m_removeValue = Button(page, inputMode, "sweep.remove-value", "값 삭제");
    layout->Add(inputMode, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    m_values = new wxListBox(page, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 85)), 0, nullptr, wxLB_HSCROLL);
    m_values->SetName("sweep.values");
    layout->Add(m_values, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    auto* range = new wxBoxSizer(wxHORIZONTAL);
    Label(page, range, "시작");
    m_rangeStart = new wxTextCtrl(page, wxID_ANY);
    m_rangeStart->SetName("sweep.range-start");
    range->Add(m_rangeStart, 1, wxALL, FromDIP(4));
    Label(page, range, "끝");
    m_rangeStop = new wxTextCtrl(page, wxID_ANY);
    m_rangeStop->SetName("sweep.range-stop");
    range->Add(m_rangeStop, 1, wxALL, FromDIP(4));
    Label(page, range, "개수");
    m_rangeCount = new wxSpinCtrl(page, wxID_ANY);
    m_rangeCount->SetRange(2, 128);
    m_rangeCount->SetValue(3);
    m_rangeCount->SetName("sweep.range-count");
    range->Add(m_rangeCount, 0, wxALL, FromDIP(4));
    layout->Add(range, 0, wxEXPAND | wxALL, FromDIP(8));
    auto* combination = new wxBoxSizer(wxHORIZONTAL);
    Label(page, combination, "후보 조합");
    m_combination = new wxChoice(page, wxID_ANY);
    for (const auto* label : {"모든 조합", "같은 순번끼리 조합", "행별 값 직접 선택"})
    {
        m_combination->Append(Display(label));
    }
    m_combination->SetName("sweep.combination");
    combination->Add(m_combination, 1, wxALL | wxEXPAND, FromDIP(4));
    m_addRow = Button(page, combination, "sweep.add-row", "후보 행 추가");
    m_removeRow = Button(page, combination, "sweep.remove-row", "후보 행 삭제");
    layout->Add(combination, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    Label(page, layout,
          "같은 순번 조합은 모든 값 목록 길이가 같아야 합니다. 행별 직접 선택에는 명시 값 목록을 사용하세요. 자동 "
          "반복은 없습니다.");
    m_rows = new wxGrid(page, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 140)));
    m_rows->CreateGrid(0, 0);
    m_rows->SetName("sweep.explicit-rows");
    m_rows->SetDefaultRowSize(FromDIP(32));
    m_rows->SetRowLabelSize(FromDIP(55));
    layout->Add(m_rows, 0, wxEXPAND | wxALL, FromDIP(12));
    m_name->Bind(wxEVT_TEXT,
                 [this](wxCommandEvent&)
                 {
                     Changed();
                 });
    m_type->Bind(
        wxEVT_CHOICE,
        [this](wxCommandEvent&)
        {
            if (!m_variables.empty())
            {
                if (wxMessageBox(Display("유형을 바꾸면 현재 변수와 명시 후보 행을 지웁니다. 계속하시겠습니까?"),
                                 Display("연구 유형 변경"), wxYES_NO | wxNO_DEFAULT | wxICON_QUESTION, this) != wxYES)
                {
                    const auto kind = m_variables.front().at("kind");
                    m_type->SetSelection(kind == "parameter" ? 0 : kind == "solver_setting" ? 1 : 2);
                    return;
                }
            }
            m_variables = Json::array();
            m_variableNames.clear();
            m_variableIndex = -1;
            Changed();
            LoadCatalog();
            RenderVariables();
            SelectVariable(-1);
            RenderRows();
            RefreshPorts();
        });
    m_availableVariables->Bind(wxEVT_CHOICE,
                               [this](wxCommandEvent&)
                               {
                                   UpdateActions();
                               });
    m_addVariable->Bind(wxEVT_BUTTON,
                        [this](wxCommandEvent&)
                        {
                            AddVariable();
                        });
    m_removeVariable->Bind(wxEVT_BUTTON,
                           [this](wxCommandEvent&)
                           {
                               if (m_variableIndex < 0)
                               {
                                   return;
                               }
                               m_variables.erase(m_variables.begin() + m_variableIndex);
                               m_variableNames.erase(m_variableNames.begin() + m_variableIndex);
                               m_variableIndex = m_variables.empty() ? -1 : 0;
                               Changed();
                               RenderVariables();
                               SelectVariable(m_variableIndex);
                               RenderRows();
                           });
    m_variableList->Bind(wxEVT_LIST_ITEM_SELECTED,
                         [this](wxListEvent& event)
                         {
                             if (!m_loading)
                             {
                                 SelectVariable(static_cast<int>(event.GetIndex()));
                             }
                         });
    m_addValue->Bind(wxEVT_BUTTON,
                     [this](wxCommandEvent&)
                     {
                         AddValue();
                     });
    m_values->Bind(wxEVT_LISTBOX,
                   [this](wxCommandEvent&)
                   {
                       UpdateActions();
                   });
    m_removeValue->Bind(wxEVT_BUTTON,
                        [this](wxCommandEvent&)
                        {
                            const int row = m_values->GetSelection();
                            if (m_variableIndex < 0 || row < 0)
                            {
                                return;
                            }
                            m_variables.at(m_variableIndex).at("values").erase(row);
                            if (m_rows->GetNumberRows() > 0)
                            {
                                m_rows->ClearGrid();
                            }
                            Changed();
                            RenderVariables();
                            SelectVariable(m_variableIndex);
                            RenderRows();
                        });
    m_valueMode->Bind(
        wxEVT_CHOICE,
        [this](wxCommandEvent&)
        {
            if (m_loading || m_variableIndex < 0)
            {
                return;
            }
            auto& variable = m_variables.at(m_variableIndex);
            const bool previousRange = variable.contains("range");
            if (previousRange || !variable.at("values").empty() || m_rows->GetNumberRows() > 0)
            {
                if (wxMessageBox(
                        Display(
                            "입력 방식을 바꾸면 선택 변수의 값 목록/범위와 명시 후보 행을 지웁니다. 계속하시겠습니까?"),
                        Display("값 입력 방식"), wxYES_NO | wxNO_DEFAULT | wxICON_QUESTION, this) != wxYES)
                {
                    m_valueMode->SetSelection(previousRange ? 1 : 0);
                    return;
                }
            }
            /** @brief 이전 목록의 인덱스를 새 값에 재사용하지 않고 사용자가 후보 행을 다시 선택하게 한다. */
            if (m_rows->GetNumberRows() > 0)
            {
                m_rows->DeleteRows(0, m_rows->GetNumberRows());
            }
            if (m_valueMode->GetSelection() == 1)
            {
                UpdateRange();
            }
            else
            {
                variable.erase("range");
                variable["values"] = Json::array();
                Changed();
                RenderVariables();
                RenderRows();
            }
            SelectVariable(m_variableIndex);
        });
    m_rangeStart->Bind(wxEVT_TEXT,
                       [this](wxCommandEvent&)
                       {
                           UpdateRange();
                       });
    m_rangeStop->Bind(wxEVT_TEXT,
                      [this](wxCommandEvent&)
                      {
                          UpdateRange();
                      });
    m_rangeCount->Bind(wxEVT_SPINCTRL,
                       [this](wxSpinEvent&)
                       {
                           UpdateRange();
                       });
    m_rangeCount->Bind(wxEVT_TEXT,
                       [this](wxCommandEvent&)
                       {
                           UpdateRange();
                       });
    m_valueUnit->Bind(wxEVT_CHOICE,
                      [this](wxCommandEvent&)
                      {
                          UpdateRange();
                      });
    m_combination->Bind(wxEVT_CHOICE,
                        [this](wxCommandEvent&)
                        {
                            Changed();
                            RenderRows();
                            UpdateActions();
                        });
    m_rows->Bind(wxEVT_GRID_CELL_CHANGED,
                 [this](wxGridEvent& event)
                 {
                     Changed();
                     event.Skip();
                 });
    m_addRow->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       if (m_rows->GetNumberCols() == 0)
                       {
                           return;
                       }
                       if (std::any_of(m_variables.begin(), m_variables.end(),
                                       [](const Json& value)
                                       {
                                           return value.contains("range");
                                       }))
                       {
                           SetStatus("행별 직접 선택에서는 각 변수의 명시 값 목록을 먼저 지정하세요.");
                           return;
                       }
                       m_rows->AppendRows();
                       RenderRows();
                       Changed();
                   });
    m_removeRow->Bind(wxEVT_BUTTON,
                      [this](wxCommandEvent&)
                      {
                          if (m_rows->GetNumberRows() > 0)
                          {
                              m_rows->DeleteRows(
                                  std::clamp(m_rows->GetGridCursorRow(), 0, m_rows->GetNumberRows() - 1));
                              Changed();
                          }
                      });
}

void SweepDialog::BuildSettings(wxWindow* page, wxSizer* layout)
{
    Label(page, layout,
          "회로 스윕은 원본 복소 자료와 저장 정합망을 선택합니다. 형상/수치 연구는 같은 기준 원본의 해석 설정을 "
          "사용합니다.");
    auto* network = new wxFlexGridSizer(2, FromDIP(8), FromDIP(12));
    network->AddGrowableCol(1);
    Label(page, network, "기준 복소 자료");
    m_datasets = new wxChoice(page, wxID_ANY);
    m_datasets->SetName("sweep.dataset");
    for (const auto& row : m_context.at("datasets"))
    {
        m_datasets->Append(Display(row.at("name")));
    }
    network->Add(m_datasets, 1, wxEXPAND);
    Label(page, network, "저장 정합망");
    m_circuits = new wxChoice(page, wxID_ANY);
    m_circuits->SetName("sweep.circuit");
    for (const auto& row : m_context.at("circuits"))
    {
        m_circuits->Append(Display(row.at("name")));
    }
    network->Add(m_circuits, 1, wxEXPAND);
    layout->Add(network, 0, wxEXPAND | wxALL, FromDIP(12));
    m_sourceNotice = new wxStaticText(
        page, wxID_ANY,
        Display("원본의 제작/측정 조건과 기준면은 미정일 수 있습니다. 선택으로 조건을 확정하지 않습니다."));
    layout->Add(m_sourceNotice, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(12));
    Label(page, layout, "해석 수치 설정 / 변경한 필드만 반영");
    m_recordRadiation = new wxCheckBox(page, wxID_ANY, Display("NF2FF 방사 기록 사용 / 초기 수치 제안, 수렴 미검증"));
    m_recordRadiation->SetName("sweep.record-radiation");
    m_featureSubdivisions = new wxCheckBox(page, wxID_ANY, Display("임계 구간 분할 사용 / 초기 제안 1"));
    m_featureSubdivisions->SetName("sweep.feature-subdivisions");
    m_recordLosses =
        new wxCheckBox(page, wxID_ANY, Display("독립 손실과 전력 수지 기록 / 방사 기록 필요, 잔차 기준 0.03"));
    m_recordLosses->SetName("sweep.record-losses");
    for (auto* option : {m_recordRadiation, m_featureSubdivisions, m_recordLosses})
    {
        layout->Add(option, 0, wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(12));
        option->Bind(wxEVT_CHECKBOX,
                     [this](wxCommandEvent&)
                     {
                         RefreshOptionalInputs();
                         Changed();
                     });
    }
    auto* fields = new wxFlexGridSizer(3, FromDIP(8), FromDIP(12));
    fields->AddGrowableCol(1);
    for (const auto& field : m_context.at("numerical_fields"))
    {
        const auto id = field.at("id").get<std::string>();
        Label(page, fields, field.at("label"));
        SettingInput input;
        input.text = new wxTextCtrl(page, wxID_ANY, Display(field.value("text", "")));
        input.text->SetName(Display("sweep.setting." + id));
        input.quantity = field.value("quantity", Json(nullptr));
        input.eligible = field.value("eligible", true);
        input.displayUnit = field.value(
            "display_unit", input.quantity.is_object() ? input.quantity.value("display_unit", field.value("unit", "1"))
                                                       : field.value("unit", "1"));
        input.unit = new wxChoice(page, wxID_ANY);
        input.unit->SetName(Display("sweep.setting-unit." + id));
        for (const auto& unit : field.at("units"))
        {
            input.unit->Append(Display(unit));
        }
        input.unit->SetStringSelection(Display(input.displayUnit));
        fields->Add(input.text, 1, wxEXPAND);
        fields->Add(input.unit, 0, wxEXPAND);
        if (!field.value("eligible", true))
        {
            input.text->SetToolTip(Display(field.value("reason", "기준 설정에 없는 항목")));
            input.text->Disable();
            input.unit->Disable();
        }
        m_settings.emplace(id, input);
        input.text->Bind(wxEVT_TEXT,
                         [this, id](wxCommandEvent&)
                         {
                             if (!m_loading)
                             {
                                 m_settings.at(id).dirty = true;
                                 m_settings.at(id).quantityCurrent = false;
                                 Changed();
                             }
                         });
        input.unit->Bind(wxEVT_CHOICE,
                         [this, id](wxCommandEvent&)
                         {
                             ChangeSettingUnit(id);
                         });
    }
    layout->Add(fields, 0, wxEXPAND | wxALL, FromDIP(12));
    auto* radiation = new wxFlexGridSizer(3, FromDIP(8), FromDIP(12));
    radiation->AddGrowableCol(1);
    Label(page, radiation, "직접 방사 주파수 수");
    m_radiationCount = new wxSpinCtrl(page, wxID_ANY);
    m_radiationCount->SetRange(1, 3);
    m_radiationCount->SetValue(3);
    m_radiationCount->SetName("sweep.radiation-count");
    radiation->Add(m_radiationCount);
    Label(page, radiation, "개 / 1~3");
    for (const auto& frequency : m_context.at("optional_radiation_frequencies"))
    {
        const auto index = m_radiationFields.size();
        Label(page, radiation, "방사 주파수 " + std::to_string(index + 1));
        SettingInput input;
        input.quantity = frequency.at("quantity");
        input.displayUnit = frequency.at("unit");
        input.text = new wxTextCtrl(page, wxID_ANY, Display(frequency.at("text")));
        input.text->SetName(Display("sweep.radiation-frequency." + std::to_string(index)));
        input.unit = new wxChoice(page, wxID_ANY);
        for (const auto* unit : {"Hz", "kHz", "MHz", "GHz"})
        {
            input.unit->Append(unit);
        }
        input.unit->SetStringSelection(Display(input.displayUnit));
        radiation->Add(input.text, 1, wxEXPAND);
        radiation->Add(input.unit);
        m_radiationFields.push_back(input);
        input.text->Bind(wxEVT_TEXT,
                         [this, index](wxCommandEvent&)
                         {
                             if (!m_loading)
                             {
                                 m_radiationFields.at(index).dirty = true;
                                 m_radiationDirty = true;
                                 Changed();
                             }
                         });
        input.unit->Bind(wxEVT_CHOICE,
                         [this, index](wxCommandEvent&)
                         {
                             ChangeRadiationUnit(index);
                         });
    }
    m_radiationCount->Bind(wxEVT_SPINCTRL,
                           [this](wxSpinEvent&)
                           {
                               m_radiationDirty = true;
                               Changed();
                           });
    m_radiationCount->Bind(wxEVT_TEXT,
                           [this](wxCommandEvent&)
                           {
                               if (!m_loading)
                               {
                                   m_radiationDirty = true;
                                   Changed();
                               }
                           });
    layout->Add(radiation, 0, wxEXPAND | wxALL, FromDIP(12));
    Label(page, layout, "목표 선택 / 저장 당시 목표 개정과 원문을 보존");
    m_targets = new wxCheckListBox(page, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 110)));
    m_targets->SetName("sweep.targets");
    for (const auto& target : m_context.at("targets"))
    {
        m_targets->Append(Display(target.at("name")));
    }
    layout->Add(m_targets, 0, wxEXPAND | wxALL, FromDIP(12));
    m_explicitContext =
        new wxCheckBox(page, wxID_ANY, Display("선택 목표에 사용할 자료 포트와 기준면을 아래 입력으로 명시"));
    m_explicitContext->SetName("sweep.explicit-target-context");
    layout->Add(m_explicitContext, 0, wxALL, FromDIP(12));
    auto* mapping = new wxFlexGridSizer(2, FromDIP(8), FromDIP(12));
    mapping->AddGrowableCol(1);
    Label(page, mapping, "평가할 자료 포트");
    m_port = new wxChoice(page, wxID_ANY);
    m_port->SetName("sweep.target-port");
    mapping->Add(m_port, 1, wxEXPAND);
    Label(page, mapping, "명시 기준면 / 비우면 미정");
    m_referencePlane = new wxTextCtrl(page, wxID_ANY);
    m_referencePlane->SetName("sweep.target-plane");
    mapping->Add(m_referencePlane, 1, wxEXPAND);
    layout->Add(mapping, 0, wxEXPAND | wxALL, FromDIP(12));
    Label(page, layout,
          "정확히 같은 주파수 표본만 평가합니다. 대응을 명시하지 않은 조건은 평가 시 미확립으로 남습니다.");
    m_datasets->Bind(wxEVT_CHOICE,
                     [this](wxCommandEvent&)
                     {
                         RefreshPorts();
                         Changed();
                     });
    m_circuits->Bind(
        wxEVT_CHOICE,
        [this](wxCommandEvent&)
        {
            if (!m_variables.empty() && m_type->GetSelection() == 2)
            {
                if (wxMessageBox(Display("정합망을 바꾸면 현재 소자 변수와 명시 후보 행을 지웁니다. 계속하시겠습니까?"),
                                 Display("기준 정합망 변경"), wxYES_NO | wxNO_DEFAULT | wxICON_QUESTION, this) != wxYES)
                {
                    m_circuits->SetSelection(m_circuitIndex);
                    return;
                }
                m_variables = Json::array();
                m_variableNames.clear();
                m_variableIndex = -1;
                RenderVariables();
                SelectVariable(-1);
                RenderRows();
            }
            m_circuitIndex = m_circuits->GetSelection();
            LoadCatalog();
            Changed();
        });
    m_targets->Bind(wxEVT_CHECKLISTBOX,
                    [this](wxCommandEvent&)
                    {
                        Changed();
                    });
    m_explicitContext->Bind(wxEVT_CHECKBOX,
                            [this](wxCommandEvent&)
                            {
                                Changed();
                            });
    m_port->Bind(wxEVT_CHOICE,
                 [this](wxCommandEvent&)
                 {
                     Changed();
                 });
    m_referencePlane->Bind(wxEVT_TEXT,
                           [this](wxCommandEvent&)
                           {
                               Changed();
                           });
}

void SweepDialog::BuildBudget(wxWindow* page, wxSizer* layout)
{
    Label(page, layout,
          "후보 수, 실제 해석 횟수, 전체 시간과 자원 예산을 고정합니다. 예상과 실측 사용량은 분리합니다.");
    auto* fields = new wxFlexGridSizer(3, FromDIP(10), FromDIP(12));
    fields->AddGrowableCol(1);
    const auto& budget = m_basis.at("budget");
    Label(page, fields, "최대 후보 수");
    m_candidateBudget = new wxSpinCtrl(page, wxID_ANY);
    m_candidateBudget->SetRange(1, 128);
    m_candidateBudget->SetValue(budget.at("max_candidates").get<int>());
    m_candidateBudget->SetName("sweep.max-candidates");
    fields->Add(m_candidateBudget, 1, wxEXPAND);
    Label(page, fields, "개 / 최대 128");
    Label(page, fields, "실제 EM 해석 횟수 상한");
    m_nativeBudget = new wxSpinCtrl(page, wxID_ANY);
    m_nativeBudget->SetRange(0, 128);
    m_nativeBudget->SetValue(budget.at("max_native_solves").get<int>());
    m_nativeBudget->SetName("sweep.max-native-solves");
    fields->Add(m_nativeBudget, 1, wxEXPAND);
    Label(page, fields, "회");
    for (const auto& item : std::vector<std::pair<std::string, std::string>>{
             {"wall_seconds", "전체 실행 시간"}, {"ram_bytes", "RAM 예산"}, {"disk_bytes", "디스크 예산"}})
    {
        const auto display = m_context.at("budget_display").at(item.first);
        Label(page, fields, item.second);
        auto* input = new wxTextCtrl(page, wxID_ANY, Display(display.at("text")));
        input->SetName(Display("sweep.budget." + item.first));
        m_budgetText[item.first] = input;
        m_budgetUnits[item.first] = display.at("unit");
        m_budgetDirty[item.first] = false;
        fields->Add(input, 1, wxEXPAND);
        Label(page, fields, display.at("unit"));
        input->Bind(wxEVT_TEXT,
                    [this, key = item.first](wxCommandEvent&)
                    {
                        if (!m_loading)
                        {
                            m_budgetDirty.at(key) = true;
                            Changed();
                        }
                    });
    }
    Label(page, fields, "동시 실행");
    Label(page, fields, "1개 / 현재 지원 범위");
    Label(page, fields, "native 작업 슬롯 공유");
    layout->Add(fields, 0, wxEXPAND | wxALL, FromDIP(16));
    Label(page, layout,
          "예산을 모두 쓰면 새 후보 실행을 중지합니다. 취소 후 실제 작업 종료를 확인하며, 재개는 완료 후보와 과거 "
          "시도를 유지합니다.");
    Label(page, layout, "기록할 출처 / 가정 (한 줄에 하나, 선택 입력)");
    m_sources =
        new wxTextCtrl(page, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 130)), wxTE_MULTILINE);
    m_sources->SetName("sweep.sources");
    std::string sources;
    for (const auto& source : m_basis.value("source_refs", Json::array()))
    {
        sources += source.get<std::string>() + "\n";
    }
    m_sources->ChangeValue(Display(sources));
    layout->Add(m_sources, 0, wxEXPAND | wxALL, FromDIP(12));
    m_candidateBudget->Bind(wxEVT_SPINCTRL,
                            [this](wxSpinEvent&)
                            {
                                Changed();
                            });
    m_nativeBudget->Bind(wxEVT_SPINCTRL,
                         [this](wxSpinEvent&)
                         {
                             Changed();
                         });
    m_candidateBudget->Bind(wxEVT_TEXT,
                            [this](wxCommandEvent&)
                            {
                                Changed();
                            });
    m_nativeBudget->Bind(wxEVT_TEXT,
                         [this](wxCommandEvent&)
                         {
                             Changed();
                         });
    m_sources->Bind(wxEVT_TEXT,
                    [this](wxCommandEvent&)
                    {
                        Changed();
                    });
}

void SweepDialog::BuildReview(wxWindow* page, wxSizer* layout)
{
    m_reviewSummary = new wxStaticText(
        page, wxID_ANY, Display("후보 검토를 실행하면 서비스가 만든 처음 25개 후보와 전체 개수를 표시합니다."));
    layout->Add(m_reviewSummary, 0, wxEXPAND | wxALL, FromDIP(12));
    m_previewRows = new wxListCtrl(page, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 245)),
                                   wxLC_REPORT | wxLC_SINGLE_SEL | wxLC_HRULES);
    m_previewRows->SetName("sweep.preview-candidates");
    StudioTheme::Table(*m_previewRows);
    for (const auto& column : std::vector<std::pair<std::string, int>>{
             {"후보", 60}, {"명시 변수 값", 400}, {"검토 상태", 130}, {"이유", 350}})
    {
        m_previewRows->AppendColumn(Display(column.first), wxLIST_FORMAT_LEFT, FromDIP(column.second));
    }
    layout->Add(m_previewRows, 0, wxEXPAND | wxALL, FromDIP(12));
    Label(page, layout, "검토 성공은 실행 완료나 성능 합격이 아닙니다. 저장된 연구는 실행 전 목록에 추가됩니다.");
    m_diagnostics = new wxTextCtrl(page, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 150)),
                                   wxTE_MULTILINE | wxTE_READONLY);
    m_diagnostics->SetName("sweep.review-diagnostics");
    layout->Add(m_diagnostics, 0, wxEXPAND | wxALL, FromDIP(12));
}

void SweepDialog::RenderReview(const Json& result)
{
    m_previewRows->DeleteAllItems();
    for (const auto& candidate : result.value("candidates", Json::array()))
    {
        const long row = m_previewRows->InsertItem(
            m_previewRows->GetItemCount(),
            Display(std::to_string(candidate.value("ordinal", static_cast<int>(m_previewRows->GetItemCount())) + 1)));
        m_previewRows->SetItem(row, 1, Display(SweepUi::CandidateValues(candidate)));
        m_previewRows->SetItem(
            row, 2,
            Display(SweepUi::Status(candidate.value("validation_status", candidate.value("state", "unknown")))));
        m_previewRows->SetItem(row, 3, Display(SweepUi::Diagnostics(candidate.value("diagnostics", Json::array()))));
    }
    m_reviewSummary->SetLabel(
        Display("전체 후보 " + std::to_string(result.value("candidate_count", 0)) + "개 / 처음 " +
                std::to_string(m_previewRows->GetItemCount()) + "개 표시\n" + "유효 " +
                std::to_string(result.value("counts", Json::object()).value("valid", 0)) + " / 입력 불가 " +
                std::to_string(result.value("counts", Json::object()).value("invalid", 0)) + " / 미지원 " +
                std::to_string(result.value("counts", Json::object()).value("unsupported", 0)) + " / 중복 " +
                std::to_string(result.value("counts", Json::object()).value("duplicates", 0)) + "\n" +
                (result.value("can_create", false) ? "저장 가능 / 실행은 별도" : "저장 차단 / 입력과 예산 진단 확인")));
    std::string diagnostics = SweepUi::Diagnostics(result.value("diagnostics", Json::array()));
    const auto budget = result.value("budget_estimate", Json::object());
    diagnostics +=
        "\n\n예산 예상 / 실제 관측값 아님\n실제 EM 해석 대상: " +
        SweepUi::Text(budget.value("native_solves", Json(nullptr))) +
        "\n메시/RAM/디스크는 실제 준비 시 다시 검사합니다. 물성이나 기준면 미정값을 자동으로 채우지 않습니다.";
    m_diagnostics->ChangeValue(Display(diagnostics));
    SetStatus(result.value("can_create", false) ? "검토한 원문 입력과 hash로 새 연구를 저장할 수 있습니다."
                                                : "후보를 저장할 수 없습니다. 진단을 확인하세요.");
    UpdateActions();
}
