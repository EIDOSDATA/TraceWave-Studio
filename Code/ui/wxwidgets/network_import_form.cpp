/** @file @brief 파일 선택, 명시 CSV 열 대응과 원문 조건 채택 입력을 구성한다. */
#include "network_import_dialog.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/checkbox.h>
#include <wx/choice.h>
#include <wx/grid.h>
#include <wx/panel.h>
#include <wx/sizer.h>
#include <wx/spinctrl.h>
#include <wx/statbox.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <wx/tokenzr.h>
#include <cmath>
#include <stdexcept>

namespace
{
/** @brief 화면 선택 순서를 공개 값 목록과 연결하며 값의 의미를 계산하지 않는다. */
wxChoice* Choices(wxWindow* parent, const std::initializer_list<const char*>& labels, const char* name)
{
    auto* choice = new wxChoice(parent, wxID_ANY);
    choice->SetName(name);
    for (const auto* label : labels)
    {
        choice->Append(Display(label));
    }
    choice->SetSelection(0);
    return choice;
}

/** @brief 고정 단위 입력의 문자열을 수치로 읽으며 단위 환산은 수행하지 않는다. */
double Number(wxTextCtrl& input)
{
    double value = 0;
    if (!input.GetValue().ToDouble(&value) || !std::isfinite(value))
    {
        input.SetFocus();
        throw std::runtime_error(
            "명시한 Z0는 유한한 수치로 입력하세요. 비어 있는 값은 임의로 50 ohm으로 채우지 않습니다.");
    }
    return value;
}

/** @brief 열 번호는 0부터 시작하는 유한 정수만 허용한다. */
long Column(const wxString& text)
{
    long value = 0;
    if (!text.ToLong(&value) || value < 0 || value > 63)
    {
        throw std::runtime_error("열 번호는 0부터 63까지의 정수로 입력하세요.");
    }
    return value;
}
}

void NetworkImportDialog::BuildFilePage(wxWindow* page)
{
    const int pad = FromDIP(StudioTheme::PanelPadding);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* form = new wxFlexGridSizer(2, FromDIP(8), FromDIP(12));
    form->AddGrowableCol(1, 1);
    form->Add(new wxStaticText(page, wxID_ANY, Display("자료 이름")), 0, wxALIGN_CENTER_VERTICAL);
    m_name = new wxTextCtrl(page, wxID_ANY);
    m_name->SetName("network.import.name");
    m_name->SetMaxLength(128);
    form->Add(m_name, 1, wxEXPAND);
    form->Add(new wxStaticText(page, wxID_ANY, Display("선택 파일")), 0, wxALIGN_CENTER_VERTICAL);
    auto* file = new wxBoxSizer(wxHORIZONTAL);
    m_path = new wxTextCtrl(page, wxID_ANY, wxEmptyString, wxDefaultPosition, wxDefaultSize, wxTE_READONLY);
    m_path->SetName("network.import.path");
    m_browse = new wxButton(page, wxID_ANY, Display("파일 선택..."));
    m_browse->SetName("network.import.browse");
    StudioTheme::Button(*m_browse);
    file->Add(m_path, 1, wxEXPAND | wxRIGHT, FromDIP(8));
    file->Add(m_browse);
    form->Add(file, 1, wxEXPAND);
    form->Add(new wxStaticText(page, wxID_ANY, Display("파일 형식")), 0, wxALIGN_CENTER_VERTICAL);
    m_format = Choices(page, {"Touchstone S / 1~2 포트", "CSV / 명시 열 대응", "TraceWave 정규 HDF5"},
                       "network.import.format");
    form->Add(m_format, 1, wxEXPAND);
    layout->Add(form, 0, wxEXPAND | wxALL, pad);
    auto* title = new wxStaticText(page, wxID_ANY, Display("원문 미리보기"));
    StudioTheme::Heading(*title);
    layout->Add(title, 0, wxLEFT | wxRIGHT | wxTOP, pad);
    m_raw = new wxTextCtrl(page, wxID_ANY, wxEmptyString, wxDefaultPosition, wxDefaultSize,
                           wxTE_MULTILINE | wxTE_READONLY | wxTE_DONTWRAP);
    m_raw->SetName("network.import.raw");
    layout->Add(m_raw, 1, wxEXPAND | wxALL, pad);
    auto* note = new wxStaticText(
        page, wxID_ANY,
        Display(
            "파싱 성공은 측정 신뢰성이나 안테나 성능의 검증이 아닙니다. 제작 / 측정 조건의 미정 상태를 유지합니다."));
    note->Wrap(FromDIP(820));
    StudioTheme::BindSecondary(*note);
    layout->Add(note, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, pad);
    page->SetSizer(layout);
    m_browse->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       Browse();
                   });
    m_name->Bind(wxEVT_TEXT,
                 [this](wxCommandEvent&)
                 {
                     ChangeInputs();
                 });
    m_format->Bind(wxEVT_CHOICE,
                   [this](wxCommandEvent&)
                   {
                       ChangeInputs(true);
                   });
}

void NetworkImportDialog::BuildMappingPage(wxWindow* page)
{
    const int pad = FromDIP(StudioTheme::PanelPadding);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    m_csv = new wxPanel(page);
    auto* csvLayout = new wxStaticBoxSizer(wxVERTICAL, m_csv, Display("CSV 열 대응 / 열 번호는 0부터 시작"));
    auto* fields = new wxFlexGridSizer(4, FromDIP(8), FromDIP(12));
    fields->AddGrowableCol(1, 1);
    fields->AddGrowableCol(3, 1);
    const auto field = [this, fields](const char* label, wxWindow* input)
    {
        fields->Add(new wxStaticText(m_csv, wxID_ANY, Display(label)), 0, wxALIGN_CENTER_VERTICAL);
        fields->Add(input, 1, wxEXPAND);
    };
    m_delimiter = Choices(m_csv, {"쉼표 (,)", "세미콜론 (;)", "탭"}, "network.import.delimiter");
    field("구분자", m_delimiter);
    m_header = new wxCheckBox(m_csv, wxID_ANY, Display("첫 행은 머리글"));
    m_header->SetName("network.import.header");
    m_header->SetValue(true);
    field("첫 행", m_header);
    m_frequencyColumn = new wxSpinCtrl(m_csv, wxID_ANY);
    m_frequencyColumn->SetName("network.import.frequency_column");
    m_frequencyColumn->SetRange(0, 63);
    field("주파수 열", m_frequencyColumn);
    m_frequencyUnit = Choices(m_csv, {"Hz", "kHz", "MHz", "GHz"}, "network.import.frequency_unit");
    m_frequencyUnit->SetToolTip(Display("CSV 원문의 숫자를 해석하는 단위입니다. 검토 결과의 표시 단위와 구분합니다."));
    field("원문 주파수 단위", m_frequencyUnit);
    m_parameter = Choices(m_csv, {"S (1)", "Z (ohm)", "Y (S)"}, "network.import.parameter");
    field("자료 종류 / 단위", m_parameter);
    m_representation = Choices(m_csv, {"RI / 실수, 허수", "MA / 크기, 각도 (deg)", "DB / dB, 각도 (deg)"},
                               "network.import.representation");
    field("복소수 표현", m_representation);
    m_portCount = Choices(m_csv, {"1", "2", "3", "4"}, "network.import.port_count");
    field("포트 수", m_portCount);
    m_ignored = new wxTextCtrl(m_csv, wxID_ANY);
    m_ignored->SetName("network.import.ignored_columns");
    m_ignored->SetHint(Display("생략할 열 번호: 3, 4"));
    m_ignored->SetMaxLength(256);
    field("명시 생략 열", m_ignored);
    csvLayout->Add(fields, 0, wxEXPAND | wxALL, pad);
    m_pairs = new wxGrid(m_csv, wxID_ANY);
    m_pairs->SetName("network.import.pairs");
    m_pairs->CreateGrid(1, 2);
    m_pairs->SetColLabelValue(0, Display("첫 번째 값의 열"));
    m_pairs->SetColLabelValue(1, Display("두 번째 값의 열"));
    m_pairs->SetColSize(0, FromDIP(210));
    m_pairs->SetColSize(1, FromDIP(210));
    m_pairs->SetRowLabelSize(FromDIP(80));
    m_pairs->DisableDragRowSize();
    csvLayout->Add(m_pairs, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, pad);
    RebuildPairs();
    auto* impedance = new wxBoxSizer(wxHORIZONTAL);
    m_z0Known = new wxCheckBox(m_csv, wxID_ANY, Display("Z0를 명시함 (ohm)"));
    m_z0Known->SetName("network.import.z0_known");
    impedance->Add(m_z0Known, 0, wxALIGN_CENTER_VERTICAL | wxRIGHT, pad);
    for (std::size_t index = 0; index < m_z0.size(); ++index)
    {
        auto* input = new wxTextCtrl(m_csv, wxID_ANY);
        input->SetName(wxString::Format("network.import.z0.%zu", index));
        input->SetHint(wxString::Format("port %zu / ohm", index + 1));
        input->SetMaxLength(128);
        m_z0[index] = input;
        impedance->Add(input, 1, wxRIGHT, pad);
        input->Bind(wxEVT_TEXT,
                    [this](wxCommandEvent&)
                    {
                        ChangeInputs(true);
                    });
    }
    csvLayout->Add(impedance, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, pad);
    m_mappingConfirmed = new wxCheckBox(m_csv, wxID_ANY, Display("전체 열의 단위, 대응 및 생략을 직접 확인했습니다."));
    m_mappingConfirmed->SetName("network.import.mapping_confirmed");
    csvLayout->Add(m_mappingConfirmed, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, pad);
    m_csv->SetSizer(csvLayout);
    layout->Add(m_csv, 0, wxEXPAND | wxALL, pad);

    auto* note = new wxStaticText(
        page, wxID_ANY,
        Display("포트 / 파 / 기준면은 첫 파일 검토 후 편집할 수 있습니다. 바꾸지 않은 조건은 원문 그대로 보존합니다."));
    note->Wrap(FromDIP(820));
    layout->Add(note, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, pad);
    m_conditions = new wxPanel(page);
    auto* conditions =
        new wxStaticBoxSizer(wxVERTICAL, m_conditions, Display("명시 조건 채택 / 원본 조건은 별도 보존"));
    auto* globals = new wxFlexGridSizer(4, FromDIP(8), FromDIP(12));
    globals->AddGrowableCol(1, 1);
    globals->AddGrowableCol(3, 1);
    globals->Add(new wxStaticText(m_conditions, wxID_ANY, Display("파 정의")), 0, wxALIGN_CENTER_VERTICAL);
    m_wave =
        Choices(m_conditions, {"원문 유지", "미정 (unknown)", "power", "pseudo", "traveling"}, "network.import.wave");
    globals->Add(m_wave, 1, wxEXPAND);
    globals->Add(new wxStaticText(m_conditions, wxID_ANY, Display("시간 위상 관례")), 0, wxALIGN_CENTER_VERTICAL);
    m_phasor = Choices(m_conditions, {"원문 유지", "미정 (unknown)", "exp(+j*omega*t)", "exp(-j*omega*t)"},
                       "network.import.phasor");
    globals->Add(m_phasor, 1, wxEXPAND);
    conditions->Add(globals, 0, wxEXPAND | wxALL, pad);
    for (std::size_t index = 0; index < m_ports.size(); ++index)
    {
        auto& port = m_ports[index];
        port.panel = new wxPanel(m_conditions);
        auto* group =
            new wxStaticBoxSizer(wxVERTICAL, port.panel, Display("자료 포트 ") + wxString::Format("%zu", index + 1));
        auto* rows = new wxFlexGridSizer(4, FromDIP(8), FromDIP(12));
        rows->AddGrowableCol(1, 1);
        rows->AddGrowableCol(3, 1);
        rows->Add(new wxStaticText(port.panel, wxID_ANY, Display("프로젝트 포트")), 0, wxALIGN_CENTER_VERTICAL);
        port.project = Choices(port.panel, {"자료 포트 유지"}, "network.import.project_port");
        port.project->SetName(wxString::Format("network.import.project_port.%zu", index));
        for (const auto& entry : m_context.value("ports", Json::array()))
        {
            port.project->Append(Display(entry.value("name", "이름 없는 포트")));
        }
        rows->Add(port.project, 1, wxEXPAND);
        rows->Add(new wxStaticText(port.panel, wxID_ANY, Display("포트 모드")), 0, wxALIGN_CENTER_VERTICAL);
        port.mode =
            Choices(port.panel, {"원문 유지", "미정 (unknown)", "단일 종단 (single_ended)", "직사각 도파관 (TE10)"}, "network.import.mode");
        port.mode->SetName(wxString::Format("network.import.mode.%zu", index));
        rows->Add(port.mode, 1, wxEXPAND);
        rows->Add(new wxStaticText(port.panel, wxID_ANY, Display("전류 방향")), 0, wxALIGN_CENTER_VERTICAL);
        port.orientation =
            Choices(port.panel, {"원문 유지", "미정 (unknown)", "DUT로 유입 (into_dut)"}, "network.import.orientation");
        port.orientation->SetName(wxString::Format("network.import.orientation.%zu", index));
        rows->Add(port.orientation, 1, wxEXPAND);
        port.planeChanged = new wxCheckBox(port.panel, wxID_ANY, Display("기준면 명시"));
        port.planeChanged->SetName(wxString::Format("network.import.plane_changed.%zu", index));
        rows->Add(port.planeChanged, 0, wxALIGN_CENTER_VERTICAL);
        port.plane = new wxTextCtrl(port.panel, wxID_ANY);
        port.plane->SetName(wxString::Format("network.import.plane.%zu", index));
        port.plane->SetMaxLength(512);
        port.plane->SetHint(Display("빈칸은 미정"));
        rows->Add(port.plane, 1, wxEXPAND);
        group->Add(rows, 0, wxEXPAND | wxALL, pad);
        port.panel->SetSizer(group);
        conditions->Add(port.panel, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, pad);
        for (auto* choice : {port.project, port.mode, port.orientation})
        {
            choice->Bind(wxEVT_CHOICE,
                         [this](wxCommandEvent&)
                         {
                             ChangeInputs();
                         });
        }
        port.planeChanged->Bind(wxEVT_CHECKBOX,
                                [this](wxCommandEvent&)
                                {
                                    ChangeInputs();
                                });
        port.plane->Bind(wxEVT_TEXT,
                         [this](wxCommandEvent&)
                         {
                             ChangeInputs();
                         });
    }
    m_conditions->SetSizer(conditions);
    layout->Add(m_conditions, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, pad);
    page->SetSizer(layout);
    for (auto* choice : {m_delimiter, m_frequencyUnit, m_representation})
    {
        choice->Bind(wxEVT_CHOICE,
                     [this](wxCommandEvent&)
                     {
                         ChangeInputs(true);
                     });
    }
    for (auto* choice : {m_portCount, m_parameter})
    {
        choice->Bind(wxEVT_CHOICE,
                     [this](wxCommandEvent&)
                     {
                         RebuildPairs();
                         m_mappingConfirmed->SetValue(false);
                         ChangeInputs(true);
                     });
    }
    for (auto* choice : {m_wave, m_phasor})
    {
        choice->Bind(wxEVT_CHOICE,
                     [this](wxCommandEvent&)
                     {
                         ChangeInputs();
                     });
    }
    for (auto* check : {m_header, m_z0Known, m_mappingConfirmed})
    {
        check->Bind(wxEVT_CHECKBOX,
                    [this](wxCommandEvent&)
                    {
                        ChangeInputs(true);
                    });
    }
    m_frequencyColumn->Bind(wxEVT_SPINCTRL,
                            [this](wxSpinEvent&)
                            {
                                ChangeInputs(true);
                            });
    m_frequencyColumn->Bind(wxEVT_TEXT,
                            [this](wxCommandEvent&)
                            {
                                ChangeInputs(true);
                            });
    m_ignored->Bind(wxEVT_TEXT,
                    [this](wxCommandEvent&)
                    {
                        ChangeInputs(true);
                    });
    m_pairs->Bind(wxEVT_GRID_CELL_CHANGED,
                  [this](wxGridEvent&)
                  {
                      ChangeInputs(true);
                  });
}

void NetworkImportDialog::RebuildPairs()
{
    const int count = m_portCount->GetSelection() + 1;
    const int rows = count * count;
    if (m_pairs->GetNumberRows() > rows)
    {
        m_pairs->DeleteRows(rows, m_pairs->GetNumberRows() - rows);
    }
    else if (m_pairs->GetNumberRows() < rows)
    {
        m_pairs->AppendRows(rows - m_pairs->GetNumberRows());
    }
    const std::array<const char*, 3> kinds = {"S", "Z", "Y"};
    for (int row = 0; row < rows; ++row)
    {
        m_pairs->SetRowLabelValue(row, Display(kinds.at(m_parameter->GetSelection())) +
                                           wxString::Format("%d%d", row / count + 1, row % count + 1));
        m_pairs->SetCellValue(row, 0, wxString::Format("%d", row * 2 + 1));
        m_pairs->SetCellValue(row, 1, wxString::Format("%d", row * 2 + 2));
    }
    m_pairs->SetMinSize(wxSize(-1, FromDIP(46 + rows * 28)));
    m_pairs->GetParent()->Layout();
    m_pairs->GetParent()->GetParent()->Layout();
    m_pairs->GetParent()->GetParent()->FitInside();
}

Json NetworkImportDialog::Mapping() const
{
    if (Format() != "csv")
    {
        return nullptr;
    }
    if (!m_mappingConfirmed->GetValue())
    {
        throw std::runtime_error("CSV 원문과 열 번호를 확인하고 명시 대응 확인란을 선택하세요.");
    }
    const std::array<const char*, 3> delimiters = {",", ";", "\t"};
    const std::array<const char*, 3> representations = {"RI", "MA", "DB"};
    const std::array<const char*, 3> kinds = {"S", "Z", "Y"};
    const std::array<const char*, 3> units = {"1", "ohm", "S"};
    const int count = m_portCount->GetSelection() + 1;
    Json pairs = Json::array();
    for (int row = 0; row < count * count; ++row)
    {
        pairs.push_back({{"row", row / count},
                         {"column", row % count},
                         {"first_column", Column(m_pairs->GetCellValue(row, 0))},
                         {"second_column", Column(m_pairs->GetCellValue(row, 1))}});
    }
    Json ignored = Json::array();
    wxStringTokenizer tokens(m_ignored->GetValue(), ",", wxTOKEN_RET_EMPTY_ALL);
    if (!m_ignored->GetValue().Strip().empty())
    {
        while (tokens.HasMoreTokens())
        {
            ignored.push_back(Column(tokens.GetNextToken().Strip()));
        }
    }
    Json z0 = nullptr;
    if (m_z0Known->GetValue())
    {
        z0 = Json::array();
        for (int index = 0; index < count; ++index)
        {
            z0.push_back(Number(*m_z0.at(index)));
        }
    }
    return {{"delimiter", delimiters.at(m_delimiter->GetSelection())},
            {"header", m_header->GetValue()},
            {"frequency_column", m_frequencyColumn->GetValue()},
            {"frequency_unit", Utf8(m_frequencyUnit->GetStringSelection())},
            {"parameter_kind", kinds.at(m_parameter->GetSelection())},
            {"complex_format", representations.at(m_representation->GetSelection())},
            {"value_unit", units.at(m_parameter->GetSelection())},
            {"port_count", count},
            {"pairs", pairs},
            {"ignored_columns", ignored},
            {"z0_ohm", z0}};
}

Json NetworkImportDialog::Declarations() const
{
    Json result = Json::object();
    if (m_sourceDescriptor.is_null())
    {
        return result;
    }
    const std::array<const char*, 5> waves = {"", "unknown", "power", "pseudo", "traveling"};
    const std::array<const char*, 4> phasors = {"", "unknown", "exp(+j*omega*t)", "exp(-j*omega*t)"};
    if (m_wave->GetSelection() > 0)
    {
        result["wave_definition"] = waves.at(m_wave->GetSelection());
    }
    if (m_phasor->GetSelection() > 0)
    {
        result["phasor_convention"] = phasors.at(m_phasor->GetSelection());
    }
    Json ports = Json::array();
    const std::array<const char*, 4> modeNames = {"", "unknown", "single_ended", "rectangular_te10"};
    Json modes = m_sourceDescriptor.at("port_modes");
    Json orientations = m_sourceDescriptor.at("current_orientation");
    Json planes = m_sourceDescriptor.at("reference_planes");
    bool changedPorts = false, changedModes = false, changedOrientations = false, changedPlanes = false;
    for (std::size_t index = 0; index < m_sourceDescriptor.at("port_ids").size(); ++index)
    {
        const auto& port = m_ports.at(index);
        const int project = port.project->GetSelection();
        ports.push_back(project > 0 ? m_context.at("ports").at(project - 1).at("id") : Json(nullptr));
        changedPorts = changedPorts || project > 0;
        if (port.mode->GetSelection() > 0)
        {
            modes[index] = modeNames.at(port.mode->GetSelection());
            changedModes = true;
        }
        if (port.orientation->GetSelection() > 0)
        {
            orientations[index] = port.orientation->GetSelection() == 1 ? "unknown" : "into_dut";
            changedOrientations = true;
        }
        if (port.planeChanged->GetValue())
        {
            planes[index] = port.plane->IsEmpty() ? Json(nullptr) : Json(Utf8(port.plane->GetValue()));
            changedPlanes = true;
        }
    }
    if (changedPorts)
    {
        result["port_ids"] = ports;
    }
    if (changedModes)
    {
        result["port_modes"] = modes;
    }
    if (changedOrientations)
    {
        result["current_orientation"] = orientations;
    }
    if (changedPlanes)
    {
        result["reference_planes"] = planes;
    }
    return result;
}
