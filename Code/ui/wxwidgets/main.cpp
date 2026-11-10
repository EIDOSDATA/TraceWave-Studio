#include <wx/wx.h>
#include <wx/cmdline.h>
#include <wx/splitter.h>
#include <wx/treectrl.h>
#include <wx/filename.h>
#include <wx/accel.h>
#include <wx/aui/aui.h>
#include <wx/listctrl.h>
#include <wx/listbox.h>
#include <wx/checklst.h>
#include <wx/notebook.h>
#include <wx/spinctrl.h>
#include <nlohmann/json.hpp>
#include <objbase.h>

#include <chrono>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <functional>
#include <map>
#include <memory>
#include <stdexcept>
#include <utility>

#include "service_client.h"
#include "editor_panel.h"
#include "design_canvas.h"
#include "model_view.h"
#include "solver_chart.h"
#include "polygon_input.h"

using Json = nlohmann::json;
using Clock = std::chrono::steady_clock;

namespace
{
int ExitCode = 0;

/** @brief JSON과 화면 사이의 문자열을 명시적 UTF-8로 변환한다. */
std::string Utf8(const wxString& text)
{
    const wxScopedCharBuffer buffer = text.utf8_str();
    return std::string(buffer.data(), buffer.length());
}

wxString Display(const std::string& text)
{
    return wxString::FromUTF8(text.data(), text.size());
}

/** @brief 공통 진단 계약의 한국어 본문을 읽고 이전 메시지 형식을 보조한다. */
std::string DiagnosticMessage(const Json& diagnostic)
{
    return diagnostic.value("message_ko", diagnostic.value("message", "입력을 확인하세요."));
}

/** @brief 서버가 요구하는 정규 소문자 UUID를 생성한다. */
std::string Uuid()
{
    GUID identifier{};
    if (FAILED(CoCreateGuid(&identifier)))
    {
        throw std::runtime_error("UUID creation failed");
    }
    char buffer[37]{};
    std::snprintf(buffer, sizeof(buffer), "%08lx-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x",
        static_cast<unsigned long>(identifier.Data1), identifier.Data2, identifier.Data3,
        identifier.Data4[0], identifier.Data4[1], identifier.Data4[2], identifier.Data4[3],
        identifier.Data4[4], identifier.Data4[5], identifier.Data4[6], identifier.Data4[7]);
    return buffer;
}

struct Options
{
    wxString python;
    wxString source;
    wxString workspace;
    wxString cadPython;
    wxString openProject;
    wxString smokeReport;
    bool smoke = false;
    bool editorSmoke = false;
    bool canvasSmoke = false;
    bool primitivesSmoke = false;
    bool coordinatesSmoke = false;
    bool cadSmoke = false;
    bool cadExpectFailure = false;
    bool openEmsWsl = false;
    bool solverSmoke = false;
    bool solverExpectFailure = false;
    wxString solverSettings;
};

enum
{
    IdCreate = wxID_HIGHEST + 1,
    IdOpen,
    IdSave,
    IdSnapshot,
    IdApply,
    IdNewParameter,
    IdUndo,
    IdRedo,
    IdRefresh,
    IdBoard,
    IdCircularBoard,
    IdNewMaterial,
    IdNewNet,
    IdNewPort,
    IdRunSolver,
    IdCancelSolver,
    IdLayer,
    IdDielectric,
    IdExportStep,
    IdBuild3D,
    IdCancelCad,
    IdOutputFolder,
    IdFit3D,
    IdTop3D,
    IdIso3D,
    IdSelect,
    IdLine,
    IdArc,
    IdCoordinates,
    IdPolygon,
    IdCirclePad,
    IdRectanglePad,
    IdVia,
    IdFit,
    IdDeleteShape,
    IdValidate,
    IdResetLayout,
    IdTimer,
    IdShutdown
};

/** @brief 트리 항목을 서비스가 사용하는 안정 객체 ID에 결합한다. */
class SelectionData final : public wxTreeItemData
{
public:
    explicit SelectionData(Json value) : selection(std::move(value))
    {
    }
    Json selection;
};
}

/** @brief 도메인 명령을 복제하지 않고 서비스와 연결하는 최소 편집 창이다. */
class StudioFrame final : public wxFrame
{
public:
    explicit StudioFrame(Options options)
        : wxFrame(nullptr, wxID_ANY, Display("TraceWave Studio"), wxDefaultPosition, wxSize(1360, 860)),
          m_options(std::move(options)), m_timer(this, IdTimer), m_started(Clock::now())
    {
        BuildInterface();
        Bind(wxEVT_TIMER, &StudioFrame::OnTimer, this, IdTimer);
        Bind(wxEVT_CLOSE_WINDOW, &StudioFrame::OnClose, this);
        Bind(wxEVT_THREAD, &StudioFrame::OnShutdown, this, IdShutdown);
        m_timer.Start(50);
        CallAfter([this]()
        {
            Connect();
        });
    }

    ~StudioFrame() override
    {
        m_manager->UnInit();
        delete m_manager;
    }

private:
    struct Pending
    {
        Clock::time_point sent;
        std::function<void(const Json&)> success;
        std::function<void(const Json&)> failure;
        bool foreground = true;
    };

    /** @brief 프로젝트 메타데이터와 선택 객체의 서비스 기반 입력 폼을 구성한다. */
    void BuildInterface()
    {
        auto* menu = new wxMenu;
        menu->Append(IdCreate, Display("새 프로젝트(&N)\tCtrl+N"));
        menu->Append(IdOpen, Display("프로젝트 열기(&O)\tCtrl+O"));
        menu->AppendSeparator();
        menu->Append(IdSave, Display("저장(&S)\tCtrl+S"));
        menu->Append(IdSnapshot, Display("스냅샷 만들기"));
        menu->Append(IdExportStep, Display("STEP 출력 / 3D 갱신"));
        menu->Append(IdRefresh, Display("저장된 상태 다시 읽기\tF5"));
        menu->AppendSeparator();
        menu->Append(wxID_EXIT, Display("종료"));
        auto* edit = new wxMenu;
        edit->Append(IdUndo, Display("실행 취소\tCtrl+Z"));
        auto* redo = edit->Append(IdRedo, Display("다시 실행\tCtrl+Y"), Display("Ctrl+Y 또는 Ctrl+Shift+Z"));
        redo->AddExtraAccel(wxAcceleratorEntry(wxACCEL_CTRL | wxACCEL_SHIFT, 'Z', IdRedo));
        edit->AppendSeparator();
        edit->Append(IdNewParameter, Display("매개변수 추가"));
        auto* bar = new wxMenuBar;
        bar->Append(menu, Display("프로젝트"));
        bar->Append(edit, Display("편집"));
        auto* design = new wxMenu;
        design->Append(IdBoard, Display("직사각 기판 만들기"));
        design->Append(IdCircularBoard, Display("원형 기판 만들기"));
        design->Append(IdNewMaterial, Display("재료 추가"));
        design->Append(IdNewNet, Display("네트 추가"));
        design->Append(IdNewPort, Display("급전 포트 추가"));
        design->Append(IdLayer, Display("도체층 추가"));
        design->Append(IdDielectric, Display("유전체층 추가"));
        design->AppendSeparator();
        design->Append(IdCoordinates, Display("좌표로 선 / 원호 추가"));
        design->Append(IdPolygon, Display("다각형 도체 면 추가"));
        design->Append(IdCirclePad, Display("원형 패드 추가"));
        design->Append(IdRectanglePad, Display("직사각 패드 추가"));
        design->Append(IdVia, Display("도금 비아 추가"));
        design->Append(IdDeleteShape, Display("선택 형상 삭제"));
        design->Append(IdValidate, Display("해석 입력 검사"));
        bar->Append(design, Display("설계"));
        auto* analysis = new wxMenu;
        analysis->Append(IdRunSolver, Display("설정 및 해석 실행"));
        analysis->Append(IdCancelSolver, Display("해석 작업 취소"));
        bar->Append(analysis, Display("해석"));
        auto* view = new wxMenu;
        view->Append(IdResetLayout, Display("기본 패널 배치 복원"));
        view->Append(IdFit, Display("전체 형상 맞춤"));
        view->Append(IdBuild3D, Display("현재 설계로 3D 갱신"));
        view->Append(IdOutputFolder, Display("STEP 출력 폴더 열기"));
        view->Append(IdCancelCad, Display("CAD 작업 취소"));
        bar->Append(view, Display("보기"));
        SetMenuBar(bar);
        CreateStatusBar(2);
        SetStatusText(Display("서비스 연결 중"), 0);
        SetStatusText(Display("Windows wxWidgets / 개발용"), 1);
        SetMinSize(FromDIP(wxSize(980, 680)));
        const wxRect workArea = wxGetClientDisplayRect();
        const wxSize preferred = FromDIP(wxSize(1360, 860));
        SetSize(wxSize(std::min(preferred.GetWidth(), workArea.GetWidth() - FromDIP(24)),
            std::min(preferred.GetHeight(), workArea.GetHeight() - FromDIP(24))));
        Centre();
        m_manager = new wxAuiManager(this);
        auto* workspace = new wxPanel(this);
        auto* top = new wxBoxSizer(wxHORIZONTAL);
        auto* title = new wxStaticText(workspace, wxID_ANY, Display("TraceWave Studio / 설계"));
        title->SetFont(title->GetFont().Bold());
        top->Add(title, 1, wxALIGN_CENTER_VERTICAL | wxALL, 10);
        AddTool(workspace, top, IdCreate, "새 프로젝트");
        AddTool(workspace, top, IdOpen, "열기");
        AddTool(workspace, top, IdSave, "저장");
        AddTool(workspace, top, IdSnapshot, "스냅샷");
        AddTool(workspace, top, IdUndo, "실행 취소");
        AddTool(workspace, top, IdRedo, "다시 실행");
        AddTool(workspace, top, IdExportStep, "STEP 출력");
        workspace->SetSizer(top);
        m_manager->AddPane(workspace, wxAuiPaneInfo().Name("workspace").Top().CaptionVisible(false).CloseButton(false).Resizable(false).PaneBorder(false)
            .BestSize(wxSize(-1, FromDIP(44))).MinSize(wxSize(-1, FromDIP(38))));

        auto* navigation = new wxPanel(this);
        auto* navigationSizer = new wxBoxSizer(wxVERTICAL);
        navigationSizer->Add(new wxStaticText(navigation, wxID_ANY, Display("설계 단계")), 0, wxALL, 8);
        m_steps = new wxListBox(navigation, wxID_ANY);
        for (const auto& label : {"1  기판", "2  패턴", "3  재료", "4  급전", "5  입력 검사"})
        {
            m_steps->Append(Display(label));
        }
        navigationSizer->Add(m_steps, 0, wxEXPAND | wxLEFT | wxRIGHT, 6);
        navigationSizer->Add(new wxStaticText(navigation, wxID_ANY, Display("객체 / 레이어")), 0, wxALL, 8);
        m_tree = new wxTreeCtrl(navigation, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxTR_HAS_BUTTONS | wxTR_LINES_AT_ROOT);
        m_tree->AddRoot(Display("프로젝트 없음"));
        navigationSizer->Add(m_tree, 1, wxEXPAND);
        navigation->SetSizer(navigationSizer);
        m_manager->AddPane(navigation, wxAuiPaneInfo().Name("navigation").Caption(Display("프로젝트 탐색")).Left().BestSize(FromDIP(wxSize(235, 600))).MinSize(FromDIP(wxSize(180, 240))).CloseButton(false));

        m_views = new wxNotebook(this, wxID_ANY);
        auto* center = new wxPanel(m_views);
        auto* centerSizer = new wxBoxSizer(wxVERTICAL);
        auto* drawingTools = new wxBoxSizer(wxHORIZONTAL);
        AddTool(center, drawingTools, IdSelect, "선택");
        AddTool(center, drawingTools, IdLine, "선");
        AddTool(center, drawingTools, IdArc, "원호");
        AddTool(center, drawingTools, IdCoordinates, "좌표 입력");
        AddTool(center, drawingTools, IdFit, "전체 보기");
        AddTool(center, drawingTools, IdDeleteShape, "삭제");
        centerSizer->Add(drawingTools, 0, wxEXPAND | wxALL, 4);
        auto* context = new wxBoxSizer(wxHORIZONTAL);
        AddTool(center, context, IdBoard, "사각 기판");
        AddTool(center, context, IdCircularBoard, "원형 기판");
        AddTool(center, context, IdLayer, "도체층");
        AddTool(center, context, IdDielectric, "유전체층");
        context->Add(new wxStaticText(center, wxID_ANY, Display("활성 층")), 0, wxALIGN_CENTER_VERTICAL | wxLEFT, 6);
        m_layerChoice = new wxChoice(center, wxID_ANY);
        context->Add(m_layerChoice, 1, wxALIGN_CENTER_VERTICAL | wxLEFT, 4);
        context->Add(new wxStaticText(center, wxID_ANY, Display("선폭")), 0, wxALIGN_CENTER_VERTICAL | wxLEFT, 6);
        m_width = new wxSpinCtrlDouble(center, wxID_ANY, "0.80", wxDefaultPosition, FromDIP(wxSize(90, -1)), wxSP_ARROW_KEYS, 0.001, 1000.0, 0.8, 0.05);
        m_width->SetDigits(3);
        context->Add(m_width, 0, wxALIGN_CENTER_VERTICAL | wxLEFT, 4);
        context->Add(new wxStaticText(center, wxID_ANY, "mm"), 0, wxALIGN_CENTER_VERTICAL | wxLEFT | wxRIGHT, 4);
        centerSizer->Add(context, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 4);
        m_canvas = new DesignCanvas(center);
        m_canvas->SetStrokeWidth(m_width->GetValue());
        centerSizer->Add(m_canvas, 1, wxEXPAND);
        m_canvasHint = new wxStaticText(center, wxID_ANY, Display("프로젝트를 열고 기판과 도체층을 만들어 시작하세요."));
        centerSizer->Add(m_canvasHint, 0, wxEXPAND | wxALL, 6);
        center->SetSizer(centerSizer);
        m_views->AddPage(center, Display("2D 편집"));
        auto* modelPanel = new wxPanel(m_views);
        auto* modelSizer = new wxBoxSizer(wxVERTICAL);
        auto* modelTools = new wxBoxSizer(wxHORIZONTAL);
        AddTool(modelPanel, modelTools, IdBuild3D, "3D 갱신");
        AddTool(modelPanel, modelTools, IdFit3D, "전체 보기");
        AddTool(modelPanel, modelTools, IdTop3D, "위에서");
        AddTool(modelPanel, modelTools, IdIso3D, "입체 보기");
        modelSizer->Add(modelTools, 0, wxEXPAND | wxALL, 4);
        m_modelState = new wxStaticText(modelPanel, wxID_ANY, Display("아직 생성한 3D 형상이 없습니다. 층 위치와 두께를 입력한 뒤 갱신하세요."));
        modelSizer->Add(m_modelState, 0, wxEXPAND | wxALL, 6);
        m_modelView = new ModelView(modelPanel);
        modelSizer->Add(m_modelView, 1, wxEXPAND);
        m_modelHint = new wxStaticText(modelPanel, wxID_ANY, Display("표시용 형상 / 실제 두께 / 제조 및 RF 검증 전"));
        modelSizer->Add(m_modelHint, 0, wxEXPAND | wxALL, 6);
        modelPanel->SetSizer(modelSizer);
        m_views->AddPage(modelPanel, Display("3D 형상"));
        BuildSolverInterface();
        m_manager->AddPane(m_views, wxAuiPaneInfo().Name("canvas").Caption(Display("설계 / mm")).CenterPane().PaneBorder(false));

        m_properties = new wxPanel(this);
        auto* form = new wxBoxSizer(wxVERTICAL);
        m_selectionLabel = new wxStaticText(m_properties, wxID_ANY, Display("프로젝트 속성"));
        m_selectionLabel->SetFont(m_selectionLabel->GetFont().Bold());
        form->Add(m_selectionLabel, 0, wxALL, 10);
        m_metadataPanel = new wxPanel(m_properties);
        auto* fields = new wxFlexGridSizer(2, 8, 8);
        fields->AddGrowableCol(1);
        fields->Add(new wxStaticText(m_metadataPanel, wxID_ANY, Display("이름")), 0, wxALIGN_CENTER_VERTICAL);
        m_name = new wxTextCtrl(m_metadataPanel, wxID_ANY);
        fields->Add(m_name, 1, wxEXPAND);
        fields->Add(new wxStaticText(m_metadataPanel, wxID_ANY, Display("설명")), 0, wxALIGN_TOP);
        m_description = new wxTextCtrl(m_metadataPanel, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 100)), wxTE_MULTILINE);
        fields->Add(m_description, 1, wxEXPAND);
        m_metadataPanel->SetSizer(fields);
        form->Add(m_metadataPanel, 0, wxEXPAND | wxALL, 10);
        m_editorPanel = new EditorPanel(m_properties);
        form->Add(m_editorPanel, 1, wxEXPAND | wxLEFT | wxRIGHT, 4);
        m_editorPanel->Hide();
        m_apply = new wxButton(m_properties, IdApply, Display("변경 적용"));
        form->Add(m_apply, 0, wxALL | wxALIGN_RIGHT, 10);
        m_revisionLabel = new wxStaticText(m_properties, wxID_ANY, Display("프로젝트를 만들거나 열어 시작하세요."));
        form->Add(m_revisionLabel, 0, wxEXPAND | wxALL, 10);
        m_properties->SetSizer(form);
        m_manager->AddPane(m_properties, wxAuiPaneInfo().Name("properties").Caption(Display("선택 속성")).Right().BestSize(FromDIP(wxSize(380, 600))).MinSize(FromDIP(wxSize(320, 220))).CloseButton(false));

        m_bottom = new wxNotebook(this, wxID_ANY);
        auto* problemPanel = new wxPanel(m_bottom);
        auto* problemSizer = new wxBoxSizer(wxVERTICAL);
        auto* problemHeader = new wxBoxSizer(wxHORIZONTAL);
        m_problemSummary = new wxStaticText(problemPanel, wxID_ANY, Display("입력 검사를 실행하지 않았습니다."));
        problemHeader->Add(m_problemSummary, 1, wxALL | wxALIGN_CENTER_VERTICAL, 6);
        AddTool(problemPanel, problemHeader, IdValidate, "해석 입력 검사");
        problemSizer->Add(problemHeader, 0, wxEXPAND);
        m_problems = new wxListCtrl(problemPanel, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_SINGLE_SEL);
        m_problems->AppendColumn(Display("상태"), wxLIST_FORMAT_LEFT, FromDIP(110));
        m_problems->AppendColumn(Display("내용 / 두 번 눌러 위치로 이동"), wxLIST_FORMAT_LEFT, FromDIP(650));
        problemSizer->Add(m_problems, 1, wxEXPAND);
        problemPanel->SetSizer(problemSizer);
        m_bottom->AddPage(problemPanel, Display("문제"));
        m_log = new wxTextCtrl(m_bottom, wxID_ANY, wxEmptyString, wxDefaultPosition, wxDefaultSize, wxTE_MULTILINE | wxTE_READONLY);
        m_bottom->AddPage(m_log, Display("로그"));
        auto* cadPanel = new wxPanel(m_bottom);
        auto* cadSizer = new wxBoxSizer(wxVERTICAL);
        auto* cadTools = new wxBoxSizer(wxHORIZONTAL);
        m_cadStatus = new wxStaticText(cadPanel, wxID_ANY, Display("CAD 환경 연결을 확인하고 있습니다."));
        cadTools->Add(m_cadStatus, 1, wxALL | wxALIGN_CENTER_VERTICAL, 6);
        AddTool(cadPanel, cadTools, IdCancelCad, "작업 취소");
        AddTool(cadPanel, cadTools, IdOutputFolder, "출력 폴더 열기");
        cadSizer->Add(cadTools, 0, wxEXPAND);
        m_cadDetails = new wxTextCtrl(cadPanel, wxID_ANY, wxEmptyString, wxDefaultPosition, wxDefaultSize, wxTE_MULTILINE | wxTE_READONLY);
        cadSizer->Add(m_cadDetails, 1, wxEXPAND);
        cadPanel->SetSizer(cadSizer);
        m_bottom->AddPage(cadPanel, Display("CAD 출력"));
        m_manager->AddPane(m_bottom, wxAuiPaneInfo().Name("problems").Caption(Display("문제 / 작업 기록")).Bottom().BestSize(FromDIP(wxSize(900, 180))).MinSize(FromDIP(wxSize(300, 110))).CloseButton(false));
        m_manager->Update();
        m_defaultLayout = m_manager->SavePerspective();
        BindCanvas();
        BindCad();
        BindSolver();
        m_name->Bind(wxEVT_TEXT, [this](wxCommandEvent&)
        {
            UpdateDraftState();
        });
        m_description->Bind(wxEVT_TEXT, [this](wxCommandEvent&)
        {
            UpdateDraftState();
        });
        m_editorPanel->Bind(wxEVT_RFAD_EDITOR_CHANGED, [this](wxCommandEvent&)
        {
            UpdateDraftState();
        });
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            if (!ConfirmDiscard())
            {
                return;
            }
            const wxString name = wxGetTextFromUser(Display("새 프로젝트 이름"), Display("프로젝트 만들기"), Display("새 안테나"), this);
            if (!name.empty())
            {
                OpenProject("create", "projects/" + Utf8(name), Utf8(name));
            }
        }, IdCreate);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            if (!ConfirmDiscard())
            {
                return;
            }
            const wxString path = wxGetTextFromUser(Display("작업 영역에 등록된 경로 (projects/이름)"), Display("프로젝트 열기"), Display(m_path.empty() ? "projects/새 안테나" : m_path), this);
            if (!path.empty())
            {
                OpenProject("open", Utf8(path));
            }
        }, IdOpen);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            SaveProject();
        }, IdSave);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            Snapshot();
        }, IdSnapshot);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            Close();
        }, wxID_EXIT);
        Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
        {
            ApplyProperties();
        }, IdApply);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            History("project.undo");
        }, IdUndo);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            History("project.redo");
        }, IdRedo);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            if (ConfirmDiscard())
            {
                SelectObject(Json{{"kind", "new_parameter"}, {"id", Uuid()}});
            }
        }, IdNewParameter);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            if (ConfirmDiscard())
            {
                OpenProject("open", m_path);
            }
        }, IdRefresh);
        m_tree->Bind(wxEVT_TREE_SEL_CHANGING, [this](wxTreeEvent& event)
        {
            if (!m_refreshing && (m_busy || !ConfirmDiscard()))
            {
                event.Veto();
            }
        });
        m_tree->Bind(wxEVT_TREE_SEL_CHANGED, [this](wxTreeEvent& event)
        {
            if (m_refreshing)
            {
                return;
            }
            auto* data = dynamic_cast<SelectionData*>(m_tree->GetItemData(event.GetItem()));
            if (data != nullptr)
            {
                SelectObject(data->selection, true);
            }
        });
        UpdateControls();
    }

    /** @brief 메뉴와 도구 버튼이 같은 명령 처리기를 사용하도록 연결한다. */
    void AddTool(wxWindow* parent, wxSizer* sizer, int id, const std::string& label)
    {
        auto* button = new wxButton(parent, id, Display(label), wxDefaultPosition, wxDefaultSize, wxBU_EXACTFIT);
        sizer->Add(button, 0, wxALL | wxALIGN_CENTER_VERTICAL, 3);
        m_tools[id] = button;
        button->Bind(wxEVT_BUTTON, [this, id](wxCommandEvent&)
        {
            wxCommandEvent command(wxEVT_MENU, id);
            GetEventHandler()->ProcessEvent(command);
        });
    }

    struct NumericField
    {
        std::string key;
        std::string label;
        double initial;
    };

    /** @brief 키보드만으로 좌표를 지정하며 유한 수치의 판정 후 서비스에 전달한다. */
    bool AskNumbers(const std::string& title, const std::vector<NumericField>& fields, Json& values)
    {
        wxDialog dialog(this, wxID_ANY, Display(title), wxDefaultPosition, wxDefaultSize, wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
        auto* outer = new wxBoxSizer(wxVERTICAL);
        auto* form = new wxFlexGridSizer(2, 8, 8);
        form->AddGrowableCol(1);
        std::map<std::string, wxTextCtrl*> controls;
        for (const auto& field : fields)
        {
            form->Add(new wxStaticText(&dialog, wxID_ANY, Display(field.label)), 0, wxALIGN_CENTER_VERTICAL);
            auto* input = new wxTextCtrl(&dialog, wxID_ANY, wxString::Format("%.12g", values.value(field.key, field.initial)));
            controls[field.key] = input;
            form->Add(input, 1, wxEXPAND);
        }
        outer->Add(form, 1, wxEXPAND | wxALL, 14);
        outer->Add(dialog.CreateSeparatedButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, 10);
        dialog.SetSizerAndFit(outer);
        while (dialog.ShowModal() == wxID_OK)
        {
            bool valid = true;
            for (const auto& item : controls)
            {
                double number = 0;
                if (!item.second->GetValue().ToDouble(&number) || !std::isfinite(number))
                {
                    wxMessageBox(Display("유한한 숫자를 입력하세요."), Display(title), wxOK | wxICON_WARNING, &dialog);
                    item.second->SetFocus();
                    valid = false;
                    break;
                }
                values[item.first] = number;
            }
            if (valid)
            {
                return true;
            }
        }
        return false;
    }

    /** @brief 빈 줄로 구멍을 구분하는 정확한 수치 입력을 단일 생성 명령으로 보낸다. */
    void AddPolygon()
    {
        if (m_busy || m_activeLayer.empty() || !ConfirmDiscard())
        {
            return;
        }
        wxDialog dialog(this, wxID_ANY, Display("다각형 도체 면 / mm"), wxDefaultPosition, FromDIP(wxSize(500, 440)), wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
        auto* layout = new wxBoxSizer(wxVERTICAL);
        auto* help = new wxStaticText(&dialog, wxID_ANY, Display("한 줄에 x, y를 입력하세요. 첫 묶음은 외곽, 빈 줄 다음은 구멍입니다.\n마지막 점을 반복하지 않습니다. 총 64점 / 구멍 최대 8개.\n접지 역할, 네트와 재료는 생성 후 속성에서 지정합니다."));
        layout->Add(help, 0, wxEXPAND | wxALL, 12);
        auto* input = new wxTextCtrl(&dialog, wxID_ANY, Display(m_polygonDraft), wxDefaultPosition, wxDefaultSize, wxTE_MULTILINE);
        layout->Add(input, 1, wxEXPAND | wxLEFT | wxRIGHT, 12);
        layout->Add(dialog.CreateSeparatedButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, 10);
        dialog.SetSizer(layout);
        while (dialog.ShowModal() == wxID_OK)
        {
            try
            {
                const std::string text = Utf8(input->GetValue());
                Json values = ParsePolygonInput(text);
                values["id"] = Uuid();
                values["layer_id"] = m_activeLayer;
                m_polygonDraft = text;
                CanvasCommand("create_polygon", values);
                return;
            }
            catch (const std::exception& error)
            {
                wxMessageBox(Display(error.what()), Display("다각형 좌표"), wxOK | wxICON_WARNING, &dialog);
                input->SetFocus();
            }
        }
    }

    /** @brief 원형/회전 사각 패드의 실제 치수를 명시하고 물성을 추정하지 않는다. */
    void AddPad(bool circle)
    {
        if (m_busy || m_activeLayer.empty() || !ConfirmDiscard())
        {
            return;
        }
        Json values = Json::object();
        std::vector<NumericField> fields{{"x", "중심 X (mm)", 0}, {"y", "중심 Y (mm)", 0},
            {"width", circle ? "지름 (mm)" : "폭 (mm)", 2}};
        if (!circle)
        {
            fields.push_back({"height", "높이 (mm)", 2});
            fields.push_back({"rotation", "반시계 회전 (deg)", 0});
        }
        if (AskNumbers(circle ? "원형 패드 치수" : "직사각 패드 치수", fields, values))
        {
            CanvasCommand("create_pad", Json{{"id", Uuid()}, {"layer_id", m_activeLayer}, {"pad_shape", circle ? "circle" : "rectangle"},
                {"center", Json::array({values.at("x"), values.at("y")})}, {"width_mm", values.at("width")},
                {"height_mm", circle ? values.at("width") : values.at("height")}, {"rotation_deg", circle ? Json(0.0) : values.at("rotation")}});
        }
    }

    /** @brief 비아의 층 범위와 제작 치수를 입력하며 비운 치수는 미정으로 보존한다. */
    void AddVia()
    {
        if (m_busy || m_activeLayer.empty() || !ConfirmDiscard())
        {
            return;
        }
        wxDialog dialog(this, wxID_ANY, Display("도금 비아 / mm"), wxDefaultPosition, wxDefaultSize, wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
        auto* layout = new wxBoxSizer(wxVERTICAL);
        layout->Add(new wxStaticText(&dialog, wxID_ANY, Display("시작은 활성 도체층입니다. 적층 순서상 뒤에 있는 끝 도체층을 선택하세요.\n완성 구멍/도금/공구 구멍은 서로 다른 값입니다. 빈칸은 미정입니다.\n패드와 도금 물성은 자동으로 생성하지 않습니다.")), 0, wxEXPAND | wxALL, 12);
        auto* form = new wxFlexGridSizer(2, 8, 8);
        form->AddGrowableCol(1);
        form->Add(new wxStaticText(&dialog, wxID_ANY, Display("끝 도체층")), 0, wxALIGN_CENTER_VERTICAL);
        auto* endLayer = new wxChoice(&dialog, wxID_ANY);
        std::vector<std::string> layerIds;
        bool afterStart = false;
        for (const auto& layer : m_scene.at("layers"))
        {
            if (layer.at("id") == m_activeLayer)
            {
                afterStart = true;
            }
            else if (afterStart && layer.at("role") == "conductor")
            {
                layerIds.push_back(layer.at("id"));
                endLayer->Append(Display(layer.at("label")));
            }
        }
        form->Add(endLayer, 1, wxEXPAND);
        const std::vector<std::pair<std::string, std::string>> names{{"x", "중심 X (mm)"}, {"y", "중심 Y (mm)"},
            {"finished_hole_diameter_mm", "완성 구멍 지름 (mm)"}, {"plating_thickness_mm", "도금 두께 (mm)"},
            {"tool_hole_diameter_mm", "공구 구멍 지름 (mm)"}};
        std::map<std::string, wxTextCtrl*> fields;
        for (const auto& name : names)
        {
            form->Add(new wxStaticText(&dialog, wxID_ANY, Display(name.second)), 0, wxALIGN_CENTER_VERTICAL);
            auto* input = new wxTextCtrl(&dialog, wxID_ANY, name.first == "x" || name.first == "y" ? "0" : "");
            fields[name.first] = input;
            form->Add(input, 1, wxEXPAND);
        }
        layout->Add(form, 0, wxEXPAND | wxLEFT | wxRIGHT, 12);
        layout->Add(new wxStaticText(&dialog, wxID_ANY, Display("연결 패드 (미선택 초안 허용, 물리 검증 전 명시 필요)")), 0, wxEXPAND | wxALL, 12);
        auto* pads = new wxCheckListBox(&dialog, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(400, 100)));
        std::vector<std::string> padIds;
        for (const auto& shape : m_scene.at("shapes"))
        {
            if (shape.at("kind") == "pad")
            {
                padIds.push_back(shape.at("id"));
                pads->Append(Display(shape.at("label")));
            }
        }
        layout->Add(pads, 1, wxEXPAND | wxLEFT | wxRIGHT, 12);
        layout->Add(dialog.CreateSeparatedButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, 10);
        dialog.SetSizerAndFit(layout);
        while (dialog.ShowModal() == wxID_OK)
        {
            if (endLayer->GetSelection() == wxNOT_FOUND)
            {
                wxMessageBox(Display("끝 도체층을 선택하세요. 목록이 비어 있으면 적층 순서가 앞선 층을 활성화하거나 도체층을 추가하세요."), Display("비아 층 범위"), wxOK | wxICON_WARNING, &dialog);
                endLayer->SetFocus();
                continue;
            }
            Json values{{"id", Uuid()}, {"layer_id", m_activeLayer}, {"end_layer_id", layerIds.at(endLayer->GetSelection())}, {"pad_ids", Json::array()}};
            bool valid = true;
            for (const auto& field : fields)
            {
                wxString text = field.second->GetValue();
                text.Trim(true).Trim(false);
                if (text.empty() && field.first != "x" && field.first != "y")
                {
                    values[field.first] = nullptr;
                    continue;
                }
                double number = 0;
                if (!text.ToDouble(&number) || !std::isfinite(number))
                {
                    wxMessageBox(Display("좌표에는 유한한 숫자를 입력하세요. 제작 치수의 빈칸은 미정으로 유지합니다."), Display("비아 입력"), wxOK | wxICON_WARNING, &dialog);
                    field.second->SetFocus();
                    valid = false;
                    break;
                }
                values[field.first] = number;
            }
            if (!valid)
            {
                continue;
            }
            values["center"] = Json::array({values.at("x"), values.at("y")});
            values.erase("x");
            values.erase("y");
            for (std::size_t index = 0; index < padIds.size(); ++index)
            {
                if (pads->IsChecked(static_cast<unsigned int>(index)))
                {
                    values["pad_ids"].push_back(padIds[index]);
                }
            }
            CanvasCommand("create_via", values);
            return;
        }
    }

    void BindCanvas()
    {
        m_canvas->onStatus = [this](const std::string& message)
        {
            m_canvasHint->SetLabel(Display(message));
        };
        m_canvas->onSelection = [this](const std::string& identity)
        {
            if (m_busy || !ConfirmDiscard())
            {
                m_canvas->SetSelection(m_selection.value("kind", "") == "geometry" ? m_selection.value("id", "") : "");
                return;
            }
            SelectObject(identity.empty() ? Json{{"kind", "project"}, {"id", m_project}} : Json{{"kind", "geometry"}, {"id", identity}});
        };
        m_canvas->onAction = [this](const Json& action)
        {
            if (m_busy || !ConfirmDiscard())
            {
                RestoreCanvas();
                return;
            }
            const std::string type = action.at("type");
            Json values = action;
            values.erase("type");
            if (type == "create_line" || type == "create_arc")
            {
                values["id"] = Uuid();
                values["width_mm"] = values.at("width");
                values.erase("width");
                if (type == "create_arc")
                {
                    values["radius_mm"] = values.at("radius");
                    values["start_angle_deg"] = values.at("start_angle");
                    values["sweep_angle_deg"] = values.at("sweep_angle");
                    values.erase("radius");
                    values.erase("start_angle");
                    values.erase("sweep_angle");
                }
            }
            else if (type == "translate")
            {
                values["dx_mm"] = values.at("delta").at(0);
                values["dy_mm"] = values.at("delta").at(1);
                values.erase("delta");
            }
            CanvasCommand(type, values);
        };
        m_layerChoice->Bind(wxEVT_CHOICE, [this](wxCommandEvent&)
        {
            const int index = m_layerChoice->GetSelection();
            if (index >= 0 && static_cast<std::size_t>(index) < m_layerIds.size())
            {
                m_activeLayer = m_layerIds[index];
                m_canvas->SetDrawingLayer(m_activeLayer);
            }
        });
        m_width->Bind(wxEVT_SPINCTRLDOUBLE, [this](wxSpinDoubleEvent&)
        {
            UpdateStrokeWidth();
        });
        m_width->Bind(wxEVT_TEXT, [this](wxCommandEvent&)
        {
            UpdateStrokeWidth();
        });
        for (const auto& tool : std::vector<std::pair<int, std::string>>{{IdSelect, "select"}, {IdLine, "line"}, {IdArc, "arc"}})
        {
            Bind(wxEVT_MENU, [this, name = tool.second](wxCommandEvent&)
            {
                if (ConfirmDiscard())
                {
                    auto activate = [this, name]()
                    {
                        m_drawTool = name;
                        m_canvas->SetTool(name);
                        m_canvas->SetFocus();
                    };
                    if (HasDraft())
                    {
                        RefreshEditor(m_selection, [this, activate]()
                        {
                            Ready("미적용 입력을 버리고 도구를 선택했습니다.");
                            activate();
                        });
                    }
                    else
                    {
                        activate();
                    }
                }
            }, tool.first);
        }
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            m_canvas->FitView();
        }, IdFit);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            m_manager->LoadPerspective(m_defaultLayout);
        }, IdResetLayout);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            if (!m_busy && ConfirmDiscard())
            {
                Json values{{"width_mm", 40.0}, {"height_mm", 60.0}};
                if (AskNumbers("기판 외형 / mm", {{"width_mm", "폭 (mm)", 40}, {"height_mm", "길이 (mm)", 60}}, values))
                {
                    values["id"] = Uuid();
                    CanvasCommand("create_board", values);
                }
            }
        }, IdBoard);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            if (!m_busy && ConfirmDiscard())
            {
                Json values{{"center_x_mm", 0.0}, {"center_y_mm", 0.0}, {"radius_mm", 30.0}};
                if (AskNumbers("원형 기판 외형 / mm", {{"center_x_mm", "중심 X (mm)", 0}, {"center_y_mm", "중심 Y (mm)", 0}, {"radius_mm", "반지름 (mm)", 30}}, values))
                {
                    values["id"] = Uuid();
                    CanvasCommand("create_circular_board", values);
                }
            }
        }, IdCircularBoard);
        for (const auto& object : std::vector<std::pair<int, std::string>>{{IdNewMaterial, "new_material"}, {IdNewNet, "new_net"}, {IdNewPort, "new_port"}})
        {
            Bind(wxEVT_MENU, [this, kind = object.second](wxCommandEvent&)
            {
                if (!m_busy && ConfirmDiscard())
                {
                    SelectObject(Json{{"kind", kind}, {"id", Uuid()}});
                }
            }, object.first);
        }
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            if (!m_busy && ConfirmDiscard())
            {
                const wxString name = wxGetTextFromUser(Display("도체층 이름. 위치/두께/재료는 미정으로 생성합니다."), Display("도체층 추가"), "Top Copper", this);
                if (!name.empty())
                {
                    CanvasCommand("create_layer", Json{{"id", Uuid()}, {"name", Utf8(name)}});
                }
            }
        }, IdLayer);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            if (!m_busy && ConfirmDiscard())
            {
                const wxString name = wxGetTextFromUser(Display("유전체층 이름. 위치/두께/물성은 직접 입력합니다."), Display("유전체층 추가"), Display("기판 유전체"), this);
                if (!name.empty())
                {
                    CanvasCommand("create_dielectric_layer", Json{{"id", Uuid()}, {"name", Utf8(name)}});
                }
            }
        }, IdDielectric);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            AddCoordinates();
        }, IdCoordinates);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            AddPolygon();
        }, IdPolygon);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            AddPad(true);
        }, IdCirclePad);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            AddPad(false);
        }, IdRectanglePad);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            AddVia();
        }, IdVia);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            if (!m_busy && m_selection.value("kind", "") == "geometry" && ConfirmDiscard())
            {
                CanvasCommand("remove", Json{{"id", m_selection.at("id")}});
            }
        }, IdDeleteShape);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            ValidateInput();
        }, IdValidate);
        m_steps->Bind(wxEVT_LISTBOX, [this](wxCommandEvent& event)
        {
            if (m_busy || !ConfirmDiscard())
            {
                return;
            }
            const int step = event.GetSelection();
            if (step == 1)
            {
                m_canvas->SetFocus();
                return;
            }
            if (step == 4)
            {
                ValidateInput();
                return;
            }
            const std::string kind = step == 0 ? "board" : (step == 2 ? "material" : "port");
            for (const auto& item : m_editor.at("items"))
            {
                if (item.at("kind") == kind)
                {
                    SelectObject(Json{{"kind", kind}, {"id", item.at("id")}});
                    return;
                }
            }
            Log("해당 객체가 없습니다. 설계 메뉴에서 기판, 재료 또는 급전 포트를 추가하세요.");
        });
        m_problems->Bind(wxEVT_LIST_ITEM_ACTIVATED, [this](wxListEvent& event)
        {
            OpenProblem(event.GetIndex());
        });
    }

    /** @brief 화면 초안을 도메인 명령 하나로 적용하고 권위 scene을 다시 읽는다. */
    void CanvasCommand(const std::string& operation, const Json& values, std::function<void()> completed = {})
    {
        m_busy = true;
        UpdateControls();
        Send("canvas.apply", Json{{"expected_revision", m_revision}, {"command_id", Uuid()}, {"operation", operation}, {"values", values}}, true, Context(),
            [this, operation, values, completed](const Json& result)
        {
            m_revision = result.at("new_revision");
            const std::string kind = (operation == "create_board" || operation == "create_circular_board") ? "board" :
                ((operation == "create_layer" || operation == "create_dielectric_layer") ? "layer" : "geometry");
            const Json selection = operation == "remove" ? Json{{"kind", "project"}, {"id", m_project}} : Json{{"kind", kind}, {"id", values.at("id")}};
            RefreshEditor(selection, [this, completed]()
            {
                Ready("2D 편집을 적용했습니다.");
                if (completed)
                {
                    completed();
                }
                else if (m_options.canvasSmoke)
                {
                    CanvasSmokeNext();
                }
            });
        }, [this](const Json& error)
        {
            RestoreCanvas();
            Failure(error.value("message", std::string("2D 편집을 적용하지 못했습니다.")));
        });
    }

    /** @brief 거절된 드래그의 강조를 속성 패널의 권위 선택으로 되돌린다. */
    void RestoreCanvas()
    {
        m_canvas->SetScene(m_scene);
        m_canvas->SetSelection(m_selection.value("kind", "") == "geometry" ? m_selection.value("id", "") : "");
    }

    void AddCoordinates()
    {
        if (m_busy || m_activeLayer.empty() || !ConfirmDiscard())
        {
            return;
        }
        const bool arc = m_drawTool == "arc";
        Json& draft = arc ? m_arcDraft : m_lineDraft;
        std::vector<NumericField> fields;
        if (arc)
        {
            fields = {{"cx", "중심 X (mm)", 20}, {"cy", "중심 Y (mm)", 30}, {"radius_mm", "반지름 (mm)", 10},
                {"start_angle_deg", "시작 각도 (deg)", 0}, {"sweep_angle_deg", "회전 각도 (deg, +반시계)", 90}, {"width_mm", "선폭 (mm)", m_width->GetValue()}};
        }
        else
        {
            fields = {{"x1", "시작 X (mm)", 5}, {"y1", "시작 Y (mm)", 5}, {"x2", "끝 X (mm)", 25},
                {"y2", "끝 Y (mm)", 5}, {"width_mm", "선폭 (mm)", m_width->GetValue()}};
        }
        if (!AskNumbers(arc ? "원호 좌표 입력" : "선 좌표 입력", fields, draft))
        {
            return;
        }
        Json values{{"id", Uuid()}, {"layer_id", m_activeLayer}, {"width_mm", draft.at("width_mm")}};
        if (arc)
        {
            values["center"] = Json::array({draft.at("cx"), draft.at("cy")});
            for (const auto& key : {"radius_mm", "start_angle_deg", "sweep_angle_deg"})
            {
                values[key] = draft.at(key);
            }
        }
        else
        {
            values["start"] = Json::array({draft.at("x1"), draft.at("y1")});
            values["end"] = Json::array({draft.at("x2"), draft.at("y2")});
        }
        CanvasCommand(arc ? "create_arc" : "create_line", values);
    }

    /** @brief 잘못된 선폭 입력에는 마지막 유효 표시값을 유지한다. */
    void UpdateStrokeWidth()
    {
        const double width = m_width->GetValue();
        if (std::isfinite(width) && width > 0.0 && width <= 1000.0)
        {
            m_canvas->SetStrokeWidth(width);
        }
        else
        {
            m_canvasHint->SetLabel(Display("선폭은 0보다 큰 유한 숫자여야 합니다. 마지막 유효 선폭을 유지합니다."));
        }
    }

    /** @brief 명시적 해석 입력 검사를 실행하며 완료와 설계 합격을 구분한다. */
    void ValidateInput(std::function<void()> completed = {})
    {
        if (m_busy || m_project.empty())
        {
            return;
        }
        ApplyCurrent([this, completed]()
        {
            m_busy = true;
            UpdateControls();
            Send("design.validate", Json{{"expected_revision", m_revision}, {"profile", "rfad.design/0.1"}, {"purpose", "em"}}, true, Context(), [this, completed](const Json& task)
            {
                WaitJob(task, [this, completed](const Json& result)
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

    void ShowProblems()
    {
        m_problems->DeleteAllItems();
        for (const auto& diagnostic : m_diagnostics)
        {
            const long row = m_problems->InsertItem(m_problems->GetItemCount(), Display("확인 필요"));
            m_problems->SetItem(row, 1, Display(DiagnosticMessage(diagnostic)));
        }
        const bool stale = !m_problemRevision.empty() && m_problemRevision != m_revision;
        const std::string count = std::to_string(m_diagnosticCount) + "개" +
            (m_diagnosticsTruncated ? " 중 " + std::to_string(m_diagnostics.size()) + "개 표시" : "");
        m_problemSummary->SetLabel(Display(m_problemRevision.empty() ? "입력 검사를 실행하지 않았습니다." :
            (stale ? "이전 설계의 검사 결과입니다. 다시 검사하세요." : "해석 입력 문제 " + count + " / 해석 메뉴에서 준비와 실행을 별도로 요청하세요.")));
        m_bottom->SetPageText(0, Display("문제 " + std::to_string(m_diagnosticCount)));
    }

    void OpenProblem(long index)
    {
        if (m_busy || index < 0 || static_cast<std::size_t>(index) >= m_diagnostics.size() || !ConfirmDiscard())
        {
            return;
        }
        if (m_problemRevision != m_revision)
        {
            Log("이전 설계의 검사입니다. 다시 검사한 뒤 위치로 이동하세요.");
            return;
        }
        const Json diagnostic = m_diagnostics.at(index);
        const auto paths = diagnostic.value("field_paths", Json::array());
        const std::string path = paths.empty() ? "" : paths.at(0).get<std::string>();
        const std::map<std::string, std::string> collections{{"geometry", "geometry"}, {"materials", "material"}, {"stackup", "layer"}, {"ports", "port"}, {"parameters", "parameter"}};
        for (const auto& item : m_editor.at("items"))
        {
            const std::string kind = item.at("kind");
            const std::string id = item.at("id");
            bool matches = kind == "board" && (path == "board" || path.compare(0, 6, "board.") == 0);
            for (const auto& mapping : collections)
            {
                const std::string prefix = mapping.first + "." + id;
                matches = matches || (kind == mapping.second && (path == prefix || path.compare(0, prefix.size() + 1, prefix + ".") == 0));
            }
            if (matches)
            {
                RefreshEditor(Json{{"kind", kind}, {"id", id}}, [this, path, diagnostic]()
                {
                    Ready("문제 위치로 이동했습니다.");
                    m_editorPanel->ShowDiagnostic(path, DiagnosticMessage(diagnostic));
                });
                return;
            }
        }
        Log(DiagnosticMessage(diagnostic));
    }

    void Log(const std::string& text)
    {
        wxWindow* focused = wxWindow::FindFocus();
        m_log->AppendText(Display(text) + "\n");
        if (m_log->GetLastPosition() > 20000)
        {
            m_log->Remove(0, m_log->GetLastPosition() - 16000);
        }
        if (focused != nullptr && focused != m_log && focused->IsEnabled() && focused->IsShownOnScreen())
        {
            focused->SetFocus();
        }
    }

    /** @brief CAD는 별도 작업으로 추적하여 편집/저장 작업의 callback을 보존한다. */
    void BindCad()
    {
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            StartCad(true);
        }, IdExportStep);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            StartCad(false);
        }, IdBuild3D);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            CancelCad();
        }, IdCancelCad);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            m_modelView->FitView();
        }, IdFit3D);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            m_modelView->SetView("top");
        }, IdTop3D);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            m_modelView->SetView("isometric");
        }, IdIso3D);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            if (m_cadResult.empty())
            {
                return;
            }
            for (const auto& artifact : m_cadResult.at("artifacts"))
            {
                if (artifact.value("role", "") == "step")
                {
                    const auto relative = std::filesystem::u8path(artifact.at("uri").get<std::string>());
                    if (relative.is_absolute() || relative.has_root_name())
                    {
                        throw std::runtime_error("Invalid STEP artifact path.");
                    }
                    for (const auto& part : relative)
                    {
                        if (part == "..")
                        {
                            throw std::runtime_error("Invalid STEP artifact path.");
                        }
                    }
                    const auto directory = std::filesystem::path(m_options.workspace.ToStdWstring()) / relative.parent_path();
                    if (!wxLaunchDefaultApplication(wxString(directory.wstring())))
                    {
                        CadStatus(m_cadState, "출력 폴더를 열 수 없습니다. CAD 출력 기록의 경로를 확인하세요.");
                    }
                    return;
                }
            }
        }, IdOutputFolder);
        m_modelView->onStatus = [this](const std::string& message)
        {
            m_modelHint->SetLabel(Display(message));
        };
        m_modelView->onSelection = [this](const std::string& identity)
        {
            if (m_busy)
            {
                m_modelView->SetSelection(m_selection.value("id", ""));
                return;
            }
            if (m_displayResult.empty() || m_displayResult.at("snapshot").at("revision_id") != m_revision)
            {
                m_modelHint->SetLabel(Display("이전 결과의 선택은 현재 설계에 적용하지 않습니다. 3D를 갱신하세요."));
                return;
            }
            if (!ConfirmDiscard())
            {
                m_modelView->SetSelection(m_selection.value("id", ""));
                return;
            }
            if (identity.empty())
            {
                SelectObject(Json{{"kind", "project"}, {"id", m_project}});
                return;
            }
            for (const auto& item : m_editor.value("items", Json::array()))
            {
                if (item.value("id", "") == identity)
                {
                    SelectObject(Json{{"kind", item.at("kind")}, {"id", identity}});
                    return;
                }
            }
        };
    }

    /** @brief 완료 상태와 입력 개정, 출력 위치를 사용자가 확인할 수 있게 유지한다. */
    void CadStatus(const std::string& state, const std::string& message)
    {
        m_cadState = state;
        m_cadStatus->SetLabel(Display(message));
        m_cadStatus->SetToolTip(Display(message));
        m_cadStatus->Wrap(std::max(FromDIP(220), m_bottom->GetClientSize().GetWidth() - FromDIP(260)));
        m_cadDetails->ChangeValue(Display(message));
        m_cadStatus->GetParent()->Layout();
        Log(message);
    }

    /** @brief 파일에 기록된 입력과 현재 편집 개정을 구분하며 이전 형상을 숨기지 않는다. */
    void UpdateModelState()
    {
        if (!m_cadResult.empty() && m_modelView->LoadedSnapshotId() == m_cadResult.at("snapshot").value("snapshot_id", "") &&
            (m_displayResult.empty() || m_displayResult.at("snapshot").at("snapshot_id") != m_cadResult.at("snapshot").at("snapshot_id")))
        {
            m_displayResult = m_cadResult;
        }
        std::string text = "아직 생성한 3D 형상이 없습니다. 층 위치와 두께를 입력한 뒤 갱신하세요.";
        if (!m_displayResult.empty())
        {
            const auto& snapshot = m_displayResult.at("snapshot");
            const std::string revision = snapshot.at("revision_id");
            const bool stale = revision != m_revision;
            text = std::string(stale ? "이전 설계의 형상 - 3D 갱신 필요" : "현재 적용된 설계의 형상") +
                " / " + std::to_string(m_modelView->TriangleCount()) + "개 삼각형 / 실제 두께";
            m_modelState->SetToolTip(Display("입력 설계 버전: " + revision + "\n스냅샷: " + snapshot.at("snapshot_id").get<std::string>()));
        }
        if (m_modelView->IsLoading())
        {
            text = "새 3D 파일 확인 중 / " + text;
        }
        if (HasDraft())
        {
            text += " / 미적용 입력은 아직 포함되지 않음";
        }
        if (m_modelState->GetLabel() != Display(text))
        {
            m_modelState->SetLabel(Display(text));
        }
    }

    /** @brief 적용 후 불변 스냅샷을 접수하고 native 작업 중에는 편집 잠금을 해제한다. */
    void StartCad(bool step)
    {
        if (m_busy || m_project.empty() || !m_cadConfigured || m_cadPreparing || m_cadRestoring || !m_cadJob.empty() || m_modelView->IsLoading())
        {
            return;
        }
        if (HasDraft())
        {
            ApplyCurrent([this, step]()
            {
                StartCad(step);
            });
            return;
        }
        m_canvas->CancelGesture();
        m_cadPreparing = true;
        m_cadCancelRequested = false;
        m_busy = true;
        m_bottom->SetSelection(2);
        CadStatus("preparing", "출력 입력을 스냅샷으로 고정하고 있습니다.");
        UpdateControls();
        Send("snapshot.create", Json{{"expected_revision", m_revision}, {"description", "GUI CAD 출력 입력"}}, true, Context(), [this, step](const Json& task)
        {
            WaitJob(task, [this, step](const Json& snapshot)
            {
                m_snapshot = snapshot.at("snapshot_id");
                m_cadSnapshot = snapshot;
                if (m_cadCancelRequested)
                {
                    m_cadPreparing = false;
                    CadStatus("cancelled", "CAD 실행 전 취소했습니다. 기존 출력은 보존했습니다.");
                    Ready("출력 준비를 취소했습니다.");
                    return;
                }
                Json input{{"snapshot", Json{{"snapshot_id", snapshot.at("snapshot_id")}, {"content_hash", snapshot.at("content_hash")}}},
                    {"profile", "rfad.step.mechanical/0.1"}};
                input[step ? "format" : "projection_kind"] = step ? "step" : "brep";
                Send(step ? "export.build" : "geometry.build", input, true, Context(), [this](const Json& accepted)
                {
                    m_cadJob = accepted.at("job_id");
                    m_cadPreparing = false;
                    m_cadPolling = false;
                    m_cadLastPoll = Clock::time_point{};
                    CadStatus("queued", "CAD 작업 대기 중. 편집과 저장을 계속할 수 있습니다.");
                    Ready("고정된 스냅샷으로 CAD 작업을 접수했습니다.");
                    if (m_cadCancelRequested)
                    {
                        m_cadCancelRequested = false;
                        CancelCad();
                    }
                }, [this](const Json& error)
                {
                    CadRejected(error);
                });
            });
        }, [this](const Json& error)
        {
            CadRejected(error);
        });
    }

    /** @brief 접수 실패를 기존 정상 출력과 분리하여 사용자에게 알린다. */
    void CadRejected(const Json& error)
    {
        m_cadPreparing = false;
        m_cadJob.clear();
        m_cadPolling = false;
        m_busy = false;
        CadStatus("failed", "CAD 출력 실패: " + error.value("message", std::string("입력을 확인하세요.")));
        m_bottom->SetSelection(2);
        UpdateControls();
    }

    /** @brief 취소 요청과 실제 프로세스 종료를 구분하여 완료 상태를 기다린다. */
    void CancelCad()
    {
        if (m_cadCancelRequested || (!m_cadPreparing && m_cadJob.empty()))
        {
            return;
        }
        m_cadCancelRequested = true;
        CadStatus("cancel_requested", "취소 요청 중. worker 종료 확인을 기다립니다.");
        UpdateControls();
        if (!m_cadJob.empty())
        {
            Send("job.cancel", Json{{"job_id", m_cadJob}, {"reason", "GUI 사용자 취소"}}, true, Json::object(),
                [](const Json&)
                {
                }, [this](const Json& error)
            {
                m_cadCancelRequested = false;
                CadStatus(m_cadState, "취소 요청 오류: " + error.value("message", ""));
                UpdateControls();
            });
        }
    }

    /** @brief 재열기 때 게시 완료된 동일 프로젝트의 마지막 결과만 복원한다. */
    void RestoreCad()
    {
        m_cadRestoring = true;
        const std::string project = m_project;
        Send("cad.latest", Json::object(), false, Context(), [this, project](const Json& response)
        {
            m_cadRestoring = false;
            if (m_project == project && response.contains("result") && !response.at("result").is_null() && m_cadJob.empty() && !m_cadPreparing)
            {
                AcceptCad(response.at("result"), false);
            }
            UpdateControls();
        }, [this](const Json& error)
        {
            m_cadRestoring = false;
            Log("이전 CAD 결과 조회 실패: " + error.value("message", ""));
            UpdateControls();
        });
    }

    /** @brief 작은 참조만 GUI로 받아 파일 읽기와 hash 검사를 3D loader에 맡긴다. */
    void AcceptCad(const Json& result, bool show)
    {
        if (result.at("snapshot").at("project_id") != m_project || result.value("status", "") != "generated_unverified")
        {
            throw std::runtime_error("CAD output is not bound to this project.");
        }
        m_cadResult = result;
        std::string listing = "STEP 생성 완료 / 제조 및 RF 검증 전\n입력 설계: " + result.at("snapshot").at("revision_id").get<std::string>();
        for (const auto& artifact : result.at("artifacts"))
        {
            listing += "\n" + artifact.at("uri").get<std::string>();
            if (artifact.value("role", "") == "display_mesh")
            {
                if (m_modelView->LoadArtifact(m_options.workspace, artifact, result.at("snapshot"), artifact.at("run_id").get<std::string>()))
                {
                    m_modelWasLoading = true;
                }
                else
                {
                    m_modelHint->SetLabel(Display("3D 파일 읽기를 시작하지 못했습니다. STEP 출력 파일은 보존되어 있습니다."));
                }
            }
        }
        CadStatus("completed", "STEP 패키지를 생성했습니다. 출력 폴더에서 파일을 확인하세요.");
        m_cadDetails->ChangeValue(Display(listing));
        if (show || m_modelView->IsLoading())
        {
            m_views->SetSelection(1);
        }
        UpdateControls();
    }

    /** @brief 실제 GUI 명령과 서비스, CAD 프로세스 및 renderer의 연결을 검증한다. */
    void CadSmokeTick()
    {
        if (!m_options.cadSmoke || !m_connected || m_cadRestoring || m_busy || m_finishing)
        {
            return;
        }
        if (m_cadSmokeStage == 1 && !m_modelView->IsLoading())
        {
            if (!m_cadConfigured)
            {
                FinishSmoke(false, "CAD smoke requires a configured native runtime.");
                return;
            }
            m_cadSmokeStage = 2;
            m_description->SetValue(Display("GUI CAD 출력 전 적용할 입력"));
            StartCad(true);
        }
        else if (m_cadSmokeStage == 2)
        {
            if (m_options.cadExpectFailure && m_cadState == "failed")
            {
                CanvasAssert(m_cadResult.empty() && !m_modelView->HasMesh() && !m_tools.at(IdOutputFolder)->IsEnabled(), "Failed CAD output was exposed.");
                m_cadChecks.push_back("invalid_input_not_published");
                m_cadSmokeStage = 7;
                FinishSmoke(true, "");
            }
            else if (!m_cadJob.empty())
            {
                CanvasAssert(m_cadSnapshot.at("revision_id") == m_revision && !HasDraft(), "CAD snapshot did not include applied draft.");
                CanvasAssert(GetMenuBar()->IsEnabled(IdSave) && m_canvas->IsEnabled(), "CAD blocked project editing.");
                m_cadChecks.push_back("draft_applied_before_snapshot");
                m_cadChecks.push_back("editing_enabled_during_cad");
                m_cadSmokeStage = 3;
                m_name->SetValue(wxEmptyString);
                ApplyCurrent([this]()
                {
                    FinishSmoke(false, "Invalid edit was accepted during CAD.");
                }, [this](const Json&)
                {
                    CanvasAssert(HasDraft() && m_revision == m_cadSnapshot.at("revision_id"), "Rejected edit changed the snapshot revision.");
                    m_name->SetValue(Display("CAD 출력 중 편집한 이름"));
                    ApplyCurrent([this]()
                    {
                        Ready("CAD 실행 중 편집 검증");
                        SaveProject();
                    });
                });
                Send("capabilities.get", Json::object(), false, Json::object(), [this](const Json&)
                {
                    m_cadErrorProbeSeen = true;
                });
            }
        }
        else if (m_cadSmokeStage == 3 && !m_cadResult.empty() && m_cadJob.empty() &&
            !m_modelView->IsLoading() && m_modelView->HasMesh() && m_modelView->RenderedFrameCount() > 0)
        {
            CanvasAssert(m_cadResult.at("snapshot").at("revision_id") != m_revision &&
                m_editor.at("saved_revision") == m_revision, "Output snapshot changed or concurrent save failed.");
            CanvasAssert(m_cadResult.at("artifacts").size() == 6 && m_modelView->TriangleCount() > 0 &&
                m_modelView->BodyCount() > 0 && m_tools.at(IdOutputFolder)->IsEnabled(), "CAD mesh or package was not connected.");
            CanvasAssert(Utf8(m_modelState->GetLabel()).find("이전 설계") != std::string::npos, "Stale CAD view was not labelled.");
            CanvasAssert(m_cadErrorProbeSeen && m_tools.at(IdBuild3D)->IsEnabled() && m_tools.at(IdFit3D)->IsEnabled(), "Responses or controls did not recover after CAD loading.");
            m_cadChecks.push_back("edit_error_does_not_drop_responses");
            m_cadChecks.push_back("snapshot_fixed_and_stale_label");
            m_cadChecks.push_back("save_during_cad");
            m_cadChecks.push_back("verified_mesh_rendered");
            m_cadChecks.push_back("step_package_accessible");
            m_cadFirstSnapshot = m_modelView->LoadedSnapshotId();
            m_modelView->SetView("top");
            m_modelView->FitView();
            m_modelView->SetView("isometric");
            m_cadChecks.push_back("camera_controls");
            m_cadSmokeStage = 4;
            StartCad(false);
        }
        else if (m_cadSmokeStage == 4 && !m_cadJob.empty())
        {
            m_cadSmokeStage = 5;
            CancelCad();
        }
        else if (m_cadSmokeStage == 5 && m_cadJob.empty() && m_cadState == "cancelled")
        {
            CanvasAssert(m_modelView->LoadedSnapshotId() == m_cadFirstSnapshot && !m_cadResult.empty(), "Cancellation removed the previous result.");
            m_cadChecks.push_back("cancel_preserves_previous_result");
            m_cadSmokeStage = 6;
            m_connected = false;
            m_transportFailed = false;
            m_restarting = true;
            BeginShutdown();
        }
        else if (m_cadSmokeStage == 6 && !m_modelView->IsLoading() && m_modelView->HasMesh())
        {
            CanvasAssert(m_serviceSessions == 2 && m_modelView->LoadedSnapshotId() == m_cadFirstSnapshot, "Published CAD result did not survive restart.");
            m_cadChecks.push_back("restart_restores_published_mesh");
            m_cadSmokeStage = 7;
            FinishSmoke(true, "");
        }
        if (!m_modelView->IsLoading() && !m_modelView->Error().empty() && !m_options.cadExpectFailure)
        {
            FinishSmoke(false, m_modelView->Error());
        }
    }

    /** @brief CAD 상태는 제한된 주기로 읽고 일반 편집 응답과 별도로 처리한다. */
    void PollCad(Clock::time_point now)
    {
        const bool loading = m_modelView->IsLoading();
        if (m_modelWasLoading != loading)
        {
            m_modelWasLoading = loading;
            UpdateControls();
        }
        UpdateModelState();
        if (m_cadJob.empty() || m_cadPolling || !m_connected || now - m_cadLastPoll < std::chrono::milliseconds(200))
        {
            return;
        }
        m_cadPolling = true;
        m_cadLastPoll = now;
        const std::string job = m_cadJob;
        Send("job.status", Json{{"job_id", job}}, false, Json::object(), [this, job](const Json& status)
        {
            m_cadPolling = false;
            if (m_cadJob != job)
            {
                return;
            }
            const std::string state = status.at("state");
            if (state == "completed")
            {
                m_cadJob.clear();
                AcceptCad(status.at("events").back().at("operation_result"), true);
            }
            else if (state == "failed" || state == "cancelled" || state == "interrupted")
            {
                m_cadJob.clear();
                const Json terminal = status.at("events").back();
                const std::string error = terminal.value("error", Json::object()).value("message", "");
                CadStatus(state, state == "cancelled" ? "CAD 작업이 취소되었습니다. 기존 출력은 보존했습니다." :
                    "CAD 작업 중단: " + error + (terminal.value("outcome_unknown", false) ? " / 이전 실행 확인 필요" : ""));
                UpdateControls();
            }
            else if (state != m_cadState)
            {
                CadStatus(state, state == "cancel_requested" ? "취소 요청을 처리하고 있습니다." : "CAD 형상 및 STEP 생성 중. 편집과 저장이 가능합니다.");
            }
        }, [this](const Json& error)
        {
            m_cadPolling = false;
            CadStatus("query_error", "CAD 상태 조회 실패: " + error.value("message", ""));
        });
    }

    /** @brief 해석 작업 상태와 결과 그래프를 기존 설계 탭과 분리하여 구성한다. */
    void BuildSolverInterface()
    {
        auto* panel = new wxPanel(m_views);
        auto* layout = new wxBoxSizer(wxVERTICAL);
        auto* tools = new wxBoxSizer(wxHORIZONTAL);
        AddTool(panel, tools, IdRunSolver, "설정 및 해석 실행");
        AddTool(panel, tools, IdCancelSolver, "해석 취소");
        m_solverMetric = new wxChoice(panel, wxID_ANY);
        for (const auto* name : {"S11 (dB)", "VSWR", "Z (ohm): Re / Im"})
        {
            m_solverMetric->Append(name);
        }
        m_solverMetric->SetSelection(0);
        tools->Add(m_solverMetric, 0, wxALL | wxALIGN_CENTER_VERTICAL, 4);
        layout->Add(tools, 0, wxEXPAND | wxALL, 4);
        m_solverStatus = new wxStaticText(panel, wxID_ANY, Display("해석 환경 연결을 확인하고 있습니다."));
        layout->Add(m_solverStatus, 0, wxEXPAND | wxALL, 6);
        m_solverViewState = new wxStaticText(panel, wxID_ANY, Display("결과 없음 / 단일 포트 PCB 계산 / IFA 및 방사 정확도 검증 전"));
        layout->Add(m_solverViewState, 0, wxEXPAND | wxLEFT | wxRIGHT, 6);
        m_solverChart = new SolverChart(panel);
        layout->Add(m_solverChart, 1, wxEXPAND | wxALL, 4);
        m_solverDetails = new wxTextCtrl(panel, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 110)), wxTE_MULTILINE | wxTE_READONLY);
        layout->Add(m_solverDetails, 0, wxEXPAND | wxALL, 6);
        panel->SetSizer(layout);
        m_views->AddPage(panel, Display("해석 결과"));
    }

    void BindSolver()
    {
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            ConfigureSolver();
        }, IdRunSolver);
        Bind(wxEVT_MENU, [this](wxCommandEvent&)
        {
            CancelSolver();
        }, IdCancelSolver);
        m_solverMetric->Bind(wxEVT_CHOICE, [this](wxCommandEvent& event)
        {
            m_solverChart->SetMetric(event.GetSelection());
        });
    }

    /** @brief 해석 조건은 사용자가 확인한 입력이며 보드 물성을 대신 생성하지 않는다. */
    void ConfigureSolver()
    {
        if (m_busy || !m_solverConfigured || m_project.empty() || m_solverActive || m_solverRestoring)
        {
            return;
        }
        Json values = m_solverDraft;
        if (!AskNumbers("PCB 해석 조건 / 재료와 급전은 선택 속성에서 입력", {
            {"start_hz", "시작 주파수 (Hz)", 2.4e9}, {"stop_hz", "끝 주파수 (Hz)", 2.4835e9},
            {"count", "주파수 표본 수 (정수)", 101}, {"grid_mm", "최대 격자 간격 (mm)", 1.0},
            {"air_padding_mm", "외부 공기 여유 (mm)", 30.0}, {"curve_tolerance_mm", "곡선 근사 허용오차 (mm)", 0.05},
            {"max_timesteps", "최대 시간 단계 (정수)", 30000}, {"end_criterion", "종료 에너지 비율", 1e-5}}, values))
        {
            return;
        }
        for (const auto* key : {"count", "max_timesteps"})
        {
            const double value = values.at(key);
            if (value != std::floor(value) || value < 1 || value > 10000000)
            {
                wxMessageBox(Display("표본 수와 최대 시간 단계에는 양의 정수를 입력하세요."), Display("해석 조건"), wxOK | wxICON_WARNING, this);
                return;
            }
        }
        m_solverDraft = values;
        m_solverSettings = Json{{"frequency_hz", Json{{"start", values.at("start_hz")}, {"stop", values.at("stop_hz")}, {"count", static_cast<int>(values.at("count").get<double>())}}},
            {"grid_mm", values.at("grid_mm")}, {"air_padding_mm", values.at("air_padding_mm")}, {"curve_tolerance_mm", values.at("curve_tolerance_mm")},
            {"max_timesteps", static_cast<int>(values.at("max_timesteps").get<double>())}, {"end_criterion", values.at("end_criterion")}};
        StartSolver();
    }

    void SolverStatus(const std::string& state, const std::string& message)
    {
        m_solverState = state;
        m_solverStatus->SetLabel(Display(message));
        m_solverStatus->GetParent()->Layout();
        m_solverDetails->AppendText(Display(state + ": " + message + "\n"));
        if (m_solverDetails->GetLastPosition() > 24000)
        {
            m_solverDetails->Remove(0, m_solverDetails->GetLastPosition() - 16000);
        }
    }

    /** @brief 스냅샷부터 해석까지 별도 작업으로 추적하여 편집과 저장을 계속 허용한다. */
    void StartSolver()
    {
        if (m_busy || m_project.empty() || !m_solverConfigured || m_solverActive || m_solverRestoring)
        {
            return;
        }
        if (HasDraft())
        {
            ApplyCurrent([this]()
            {
                StartSolver();
            });
            return;
        }
        m_canvas->CancelGesture();
        m_solverActive = true;
        m_solverCancelRequested = false;
        m_views->SetSelection(2);
        SubmitSolverPhase("snapshot", "snapshot.create", Json{{"expected_revision", m_revision}, {"description", "GUI PCB 해석 입력"}});
    }

    void SubmitSolverPhase(const std::string& phase, const std::string& method, const Json& input)
    {
        m_solverPhase = phase;
        SolverStatus("accepting", phase + " 작업을 접수하고 있습니다. 입력은 스냅샷으로 고정됩니다.");
        UpdateControls();
        Send(method, input, true, Context(), [this](const Json& accepted)
        {
            m_solverJob = accepted.at("job_id");
            m_solverPolling = false;
            m_solverLastPoll = Clock::time_point{};
            SolverStatus("queued", m_solverPhase + " 대기 중. 편집과 저장을 계속할 수 있습니다.");
            UpdateControls();
            if (m_solverCancelRequested)
            {
                m_solverCancelRequested = false;
                CancelSolver();
            }
        }, [this](const Json& error)
        {
            SolverRejected(error);
        });
    }

    void SolverRejected(const Json& error)
    {
        m_solverActive = false;
        m_solverJob.clear();
        m_solverPolling = false;
        SolverStatus("failed", "해석 실패: " + DiagnosticMessage(error));
        m_views->SetSelection(2);
        UpdateControls();
    }

    /** @brief 취소 요청 뒤에는 다음 단계로 자동 진행하지 않는다. */
    void CancelSolver()
    {
        if (!m_solverActive || m_solverCancelRequested)
        {
            return;
        }
        m_solverCancelRequested = true;
        SolverStatus("cancel_requested", "취소 요청 중. 실제 WSL worker 종료 확인을 기다립니다.");
        UpdateControls();
        if (!m_solverJob.empty())
        {
            Send("job.cancel", Json{{"job_id", m_solverJob}, {"reason", "GUI 해석 작업 취소"}}, true, Json::object(), [](const Json&)
            {
            }, [this](const Json& error)
            {
                m_solverCancelRequested = false;
                SolverStatus("cancel_error", "취소 요청을 확인하지 못했습니다: " + DiagnosticMessage(error));
                UpdateControls();
            });
        }
    }

    void PollSolver(Clock::time_point now)
    {
        UpdateSolverView();
        if (m_solverJob.empty() || m_solverPolling || !m_connected || now - m_solverLastPoll < std::chrono::milliseconds(250))
        {
            return;
        }
        m_solverPolling = true;
        m_solverLastPoll = now;
        const std::string job = m_solverJob;
        Send("job.status", Json{{"job_id", job}}, false, Json::object(), [this, job](const Json& status)
        {
            m_solverPolling = false;
            if (m_solverJob != job)
            {
                return;
            }
            const std::string state = status.at("state");
            if (state == "completed")
            {
                m_solverJob.clear();
                if (m_solverCancelRequested)
                {
                    m_solverActive = false;
                    SolverStatus("cancelled", "취소 요청 이후 단계 실행을 멈췄습니다. 기존 결과는 보존했습니다.");
                    UpdateControls();
                    return;
                }
                SolverPhaseComplete(status.at("events").back().at("operation_result"));
            }
            else if (state == "failed" || state == "cancelled" || state == "interrupted")
            {
                m_solverJob.clear();
                m_solverActive = false;
                const auto terminal = status.at("events").back();
                const std::string reason = DiagnosticMessage(terminal.value("error", Json::object()));
                SolverStatus(state, state == "cancelled" ? "해석이 취소되었습니다. 기존 결과는 보존했습니다." :
                    "해석 중단: " + reason + (terminal.value("outcome_unknown", false) ? " / guest 종료 확인 필요, 자동 재실행하지 않음" : ""));
                UpdateControls();
            }
            else if (state != m_solverState)
            {
                SolverStatus(state, m_solverPhase + " / " + state + " / 편집 및 저장 가능");
            }
        }, [this](const Json& error)
        {
            m_solverPolling = false;
            SolverStatus("query_error", "해석 상태 조회 실패: " + DiagnosticMessage(error));
        });
    }

    void SolverPhaseComplete(const Json& result)
    {
        if (m_solverPhase == "snapshot")
        {
            m_solverSnapshot = result;
            SubmitSolverPhase("plan", "solver.plan", Json{{"snapshot", Json{{"snapshot_id", result.at("snapshot_id")}, {"content_hash", result.at("content_hash")}}},
                {"analysis_profile", "rfad.openems.pcb-single-port/0.1"}, {"runtime_profile", "openems-wsl-reference/0.1"}, {"settings", m_solverSettings}});
        }
        else if (m_solverPhase == "plan")
        {
            const auto& plan = result.at("analysis_plan");
            m_solverPlan = plan;
            m_solverDetails->AppendText(Display("계획: " + plan.at("plan_id").get<std::string>() + "\n"));
            SubmitSolverPhase("prepare", "solver.prepare", Json{{"analysis_plan", Json{{"plan_id", plan.at("plan_id")}, {"content_hash", plan.at("content_hash")}}},
                {"budget", Json{{"timeout_seconds", 300}}}});
        }
        else if (m_solverPhase == "prepare")
        {
            const auto& prepared = result.at("prepared_plan");
            m_solverPrepared = prepared;
            SubmitSolverPhase("analysis", "job.submit", Json{{"task_plan", Json{{"kind", "em_analysis"}, {"prepared_plan", Json{{"prepared_plan_id", prepared.at("prepared_plan_id")}, {"content_hash", prepared.at("content_hash")}}},
                {"execution_mode", "solve_and_postprocess"}}}, {"budget", Json{{"timeout_seconds", 300}}}});
        }
        else
        {
            m_solverActive = false;
            AcceptSolver(result, true);
        }
    }

    void AcceptSolver(const Json& result, bool show)
    {
        const std::string project = m_project;
        const std::string artifact = result.at("artifact_id");
        m_solverRestoring = true;
        UpdateControls();
        Send("result.open", Json{{"artifact_id", artifact}}, false, Context(), [this, project, artifact, result, show](const Json& view)
        {
            if (project != m_project)
            {
                m_solverRestoring = false;
                return;
            }
            Send("solver.samples", Json{{"artifact_id", artifact}}, false, Context(), [this, project, result, view, show](const Json& samples)
            {
                m_solverRestoring = false;
                if (project != m_project || samples.at("snapshot").at("project_id") != m_project)
                {
                    throw std::runtime_error("해석 표시 결과가 선택 프로젝트와 다릅니다.");
                }
                m_solverChart->SetResult(samples);
                m_solverSamples = samples;
                m_solverResult = result;
                SolverStatus("completed", "계산 결과를 열었습니다. 사용자 안테나의 물리 정확도 검증과 구분합니다.");
                for (const auto& file : view.at("files"))
                {
                    m_solverDetails->AppendText(Display(file.at("uri").get<std::string>() + "\n"));
                }
                if (show)
                {
                    m_views->SetSelection(2);
                }
                UpdateSolverView();
                UpdateControls();
            }, [this](const Json& error)
            {
                m_solverRestoring = false;
                SolverRejected(error);
            });
        }, [this](const Json& error)
        {
            m_solverRestoring = false;
            SolverRejected(error);
        });
    }

    void RestoreSolver()
    {
        m_solverRestoring = true;
        Send("solver.latest", Json::object(), false, Context(), [this](const Json& response)
        {
            m_solverRestoring = false;
            if (response.contains("result") && !response.at("result").is_null())
            {
                AcceptSolver(response.at("result"), false);
            }
            UpdateControls();
        }, [this](const Json& error)
        {
            m_solverRestoring = false;
            Log("이전 해석 결과 조회 실패: " + DiagnosticMessage(error));
            UpdateControls();
        });
    }

    void UpdateSolverView()
    {
        if (m_solverSamples.empty())
        {
            return;
        }
        const bool stale = m_solverSamples.at("snapshot").at("revision_id") != m_revision;
        const std::string label = (stale ? "이전 설계의 결과 / " : "현재 적용 설계의 결과 / ") +
            std::to_string(m_solverChart->SampleCount()) + "개 주파수 / IFA 및 NF2FF 정확도 검증 전";
        if (m_solverViewState->GetLabel() != Display(label))
        {
            m_solverViewState->SetLabel(Display(label));
        }
    }

    /** @brief 실제 GUI 작업 사슬과 결과 유지/재열기를 정해진 입력으로 검증한다. */
    void SolverSmokeTick()
    {
        if (!m_options.solverSmoke || m_busy || m_solverRestoring || m_cadRestoring || !m_connected || m_finishing)
        {
            return;
        }
        if (m_solverSmokeStage == 1)
        {
            if (m_scene.at("board").is_null())
            {
                m_solverSmokeStage = 8;
                CanvasCommand("create_circular_board", Json{{"id", Uuid()}, {"center_x_mm", -5.0}, {"center_y_mm", 7.0}, {"radius_mm", 20.0}}, [this]()
                {
                    CanvasAssert(m_scene.at("board").at("kind") == "circle" && m_scene.at("board").at("center") == Json::array({-5.0, 7.0}) &&
                        m_scene.at("board").at("radius") == 20.0, "Circular board DTO differs from the submitted geometry.");
                    m_solverChecks.push_back("circular_board_created");
                    m_solverSmokeStage = 1;
                });
                return;
            }
            if (!m_options.solverSettings.empty())
            {
                std::ifstream stream(std::filesystem::path(m_options.solverSettings.ToStdWstring()), std::ios::binary);
                m_solverSettings = Json::parse(stream);
            }
            else
            {
                m_solverSettings = Json{{"frequency_hz", Json{{"start", 2.4e9}, {"stop", 2.4835e9}, {"count", 31}}}, {"grid_mm", 1.0},
                    {"air_padding_mm", 30.0}, {"curve_tolerance_mm", 0.05}, {"max_timesteps", 30000}, {"end_criterion", 1e-5}};
            }
            if (m_scene.at("board").value("kind", "rectangle") == "circle")
            {
                m_canvas->FitView();
                m_solverChecks.push_back("circular_board_display");
            }
            m_solverSmokeStage = 2;
            StartSolver();
        }
        else if (m_solverSmokeStage == 2 && m_options.solverExpectFailure && !m_solverActive && m_solverState == "failed")
        {
            CanvasAssert(m_solverResult.empty() && m_solverChart->SampleCount() == 0, "Invalid physics input produced a result.");
            m_solverChecks.push_back("invalid_physics_not_published");
            m_solverSmokeStage = 7;
            FinishSmoke(true, "");
        }
        else if (m_solverSmokeStage == 2 && !m_options.solverExpectFailure && m_solverActive && m_solverPhase == "analysis")
        {
            CanvasAssert(m_tools.at(IdSave)->IsEnabled() && m_tools.at(IdCancelSolver)->IsEnabled(), "Solver blocked save or cancel.");
            m_solverChecks.push_back("editing_enabled_during_solver");
            m_solverSmokeStage = 3;
            m_description->SetValue(Display("해석 실행 중 편집/저장 검증"));
            ApplyCurrent([this]()
            {
                SaveProject();
            });
        }
        else if (m_solverSmokeStage == 3 && !m_solverActive && m_solverState == "completed" && m_solverChart->RenderedFrames() > 0)
        {
            CanvasAssert(m_solverSamples.at("snapshot").at("revision_id") != m_revision && m_editor.at("saved_revision") == m_revision,
                "Solver snapshot changed or concurrent save failed.");
            CanvasAssert(m_solverChart->SampleCount() >= 3, "No solver samples displayed.");
            m_solverChecks.push_back("snapshot_fixed_and_stale_label");
            m_solverChecks.push_back("bounded_results_rendered");
            m_solverChecks.push_back("save_during_solver");
            m_solverFirstResult = m_solverResult.at("artifact_id");
            m_solverMetric->SetSelection(2);
            m_solverChart->SetMetric(2);
            m_solverSmokeStage = 4;
            StartSolver();
        }
        else if (m_solverSmokeStage == 4 && !m_solverJob.empty())
        {
            m_solverSmokeStage = 5;
            CancelSolver();
        }
        else if (m_solverSmokeStage == 5 && !m_solverActive && m_solverState == "cancelled")
        {
            CanvasAssert(m_solverResult.at("artifact_id") == m_solverFirstResult, "Cancel removed prior solver result.");
            m_solverChecks.push_back("cancel_preserves_previous_result");
            m_solverSmokeStage = 6;
            m_connected = false;
            m_transportFailed = false;
            m_restarting = true;
            BeginShutdown();
        }
        else if (m_solverSmokeStage == 6 && !m_solverSamples.empty())
        {
            CanvasAssert(m_serviceSessions == 2 && m_solverResult.at("artifact_id") == m_solverFirstResult, "Solver result was not restored.");
            m_solverChecks.push_back("restart_restores_result");
            m_solverSmokeStage = 7;
            FinishSmoke(true, "");
        }
        if (!m_options.solverExpectFailure && !m_solverActive && m_solverState == "failed")
        {
            FinishSmoke(false, Utf8(m_solverStatus->GetLabel()));
        }
    }

    void UpdateControls()
    {
        const bool ready = m_connected && !m_busy;
        const bool opened = ready && !m_project.empty();
        const bool cadRunning = m_cadPreparing || !m_cadJob.empty();
        const bool canSwitch = ready && !cadRunning && !m_solverActive && !m_solverRestoring && !m_cadRestoring && !m_modelView->IsLoading();
        GetMenuBar()->Enable(IdCreate, canSwitch);
        GetMenuBar()->Enable(IdOpen, canSwitch);
        GetMenuBar()->Enable(IdSave, opened);
        GetMenuBar()->Enable(IdSnapshot, opened);
        GetMenuBar()->Enable(IdRefresh, opened && canSwitch);
        GetMenuBar()->Enable(IdNewParameter, opened);
        for (const int id : {IdNewMaterial, IdNewNet, IdNewPort})
        {
            GetMenuBar()->Enable(id, opened);
        }
        const Json history = m_editor.value("history", Json::object());
        GetMenuBar()->Enable(IdUndo, opened && history.value("can_undo", false));
        GetMenuBar()->Enable(IdRedo, opened && history.value("can_redo", false));
        m_tree->Enable(opened);
        m_name->Enable(opened);
        m_description->Enable(opened);
        m_editorPanel->Enable(opened);
        const bool board = m_scene.contains("board") && !m_scene.at("board").is_null();
        const bool synchronized = m_scene.value("revision_id", "") == m_revision;
        const bool drawing = opened && synchronized && board && !m_activeLayer.empty();
        for (const int id : {IdPolygon, IdCirclePad, IdRectanglePad, IdVia})
        {
            GetMenuBar()->Enable(id, drawing);
        }
        for (const auto& item : m_tools)
        {
            bool enabled = opened;
            if (item.first == IdCreate || item.first == IdOpen)
            {
                enabled = canSwitch;
            }
            else if (item.first == IdUndo || item.first == IdRedo)
            {
                enabled = opened && history.value(item.first == IdUndo ? "can_undo" : "can_redo", false);
            }
            else if (item.first == IdBoard || item.first == IdCircularBoard)
            {
                enabled = opened && !board;
            }
            else if (item.first == IdLayer || item.first == IdDielectric)
            {
                enabled = opened && board;
            }
            else if (item.first == IdLine || item.first == IdArc || item.first == IdCoordinates)
            {
                enabled = drawing;
            }
            else if (item.first == IdDeleteShape)
            {
                enabled = opened && m_selection.value("kind", "") == "geometry";
            }
            else if (item.first == IdExportStep || item.first == IdBuild3D)
            {
                enabled = opened && m_cadConfigured && !cadRunning && !m_cadRestoring && !m_modelView->IsLoading();
            }
            else if (item.first == IdCancelCad)
            {
                enabled = m_connected && cadRunning && !m_cadCancelRequested;
            }
            else if (item.first == IdOutputFolder)
            {
                enabled = !m_cadResult.empty();
            }
            else if (item.first == IdRunSolver)
            {
                enabled = opened && m_solverConfigured && !m_solverActive && !m_solverRestoring;
            }
            else if (item.first == IdCancelSolver)
            {
                enabled = m_connected && m_solverActive && !m_solverCancelRequested;
            }
            else if (item.first == IdFit3D || item.first == IdTop3D || item.first == IdIso3D)
            {
                enabled = m_modelView->HasMesh();
            }
            item.second->Enable(enabled);
        }
        for (const int id : {IdBoard, IdCircularBoard, IdLayer, IdDielectric, IdCoordinates, IdDeleteShape, IdValidate,
            IdExportStep, IdBuild3D, IdCancelCad, IdOutputFolder, IdRunSolver, IdCancelSolver})
        {
            GetMenuBar()->Enable(id, m_tools.at(id)->IsEnabled());
        }
        m_steps->Enable(opened);
        m_layerChoice->Enable(drawing);
        m_width->Enable(drawing);
        m_canvas->SetEditingEnabled(opened && synchronized);
        if (opened && !synchronized)
        {
            m_canvasHint->SetLabel(Display("이전 설계의 표시입니다. F5로 최신 상태를 다시 읽으세요."));
        }
        UpdateDraftState();
        UpdateModelState();
    }

    /** @brief 미적용 입력과 적용 후 저장 필요 상태를 서비스 개정 정보로 구분한다. */
    void UpdateDraftState()
    {
        if (m_refreshing || m_updatingDraft)
        {
            return;
        }
        m_updatingDraft = true;
        try
        {
            const bool opened = !m_project.empty() && !m_editor.empty();
            const bool draft = opened && HasDraft();
            bool canApply = draft;
            if (opened && m_selection.value("kind", "project") == "new_parameter")
            {
                wxString name = Display(m_editorPanel->FieldValue("name").get<std::string>());
                name.Trim(true).Trim(false);
                canApply = canApply && !name.empty();
            }
            m_apply->Enable(m_connected && !m_busy && canApply);
            if (!opened)
            {
                m_editState = "empty";
                SetTitle(Display("TraceWave Studio"));
                m_revisionLabel->SetLabel(Display("프로젝트를 만들거나 열어 시작하세요."));
                m_revisionLabel->UnsetToolTip();
                SetStatusText(Display("프로젝트 없음"), 1);
            }
            else
            {
                const bool saved = m_editor.at("saved_revision") == m_revision;
                m_editState = draft ? "draft" : (saved ? "saved" : "applied");
                const std::string status = draft ? "미적용 입력" : (saved ? "저장됨" : "적용됨 (저장 필요)");
                const std::string name = m_editor.at("metadata").at("name").get<std::string>();
                SetTitle(Display(name + " - " + status + " - TraceWave Studio"));
                m_revisionLabel->SetLabel(Display(status));
                m_revisionLabel->SetToolTip(Display("프로젝트 식별자: " + m_project + "\n설계 버전: " + m_revision +
                    "\n저장 버전: " + m_editor.at("saved_revision").get<std::string>()));
                SetStatusText(Display(status), 1);
            }
        }
        catch (const std::exception&)
        {
            m_apply->Disable();
        }
        m_updatingDraft = false;
    }

    /** @brief 적용 전 입력이 선택 변경이나 종료로 조용히 사라지지 않도록 한다. */
    bool HasDraft() const
    {
        if (m_editor.empty())
        {
            return false;
        }
        if (m_selection.value("kind", "project") == "project")
        {
            return Utf8(m_name->GetValue()) != m_editor.at("metadata").at("name") ||
                Utf8(m_description->GetValue()) != m_editor.at("metadata").at("description");
        }
        return m_editorPanel->IsDirty();
    }

    bool ConfirmDiscard()
    {
        if (!HasDraft())
        {
            return true;
        }
        return wxMessageBox(Display("아직 적용하지 않은 입력을 버리고 계속하시겠습니까?"),
            Display("입력 변경 확인"), wxYES_NO | wxNO_DEFAULT | wxICON_QUESTION, this) == wxYES;
    }

    void Failure(const std::string& message, bool disconnected = false)
    {
        Log(message);
        m_busy = false;
        m_activeJob.clear();
        m_jobPending = false;
        if (disconnected)
        {
            m_pending.clear();
            m_connected = false;
            m_cadPreparing = false;
            m_cadPolling = false;
            if (!m_cadJob.empty())
            {
                CadStatus("disconnected", "CAD 서비스 연결이 끊겼습니다. 완료 여부를 추정하지 않습니다. 재열기 후 보존된 결과를 확인하세요.");
            }
            m_solverPolling = false;
            if (m_solverActive)
            {
                SolverStatus("disconnected", "해석 서비스 연결이 끊겼습니다. guest 종료와 완료 여부를 추정하지 않으며 자동 재실행하지 않습니다.");
            }
        }
        SetStatusText(Display(disconnected ? "서비스 연결 끊김" : "작업 실패"), 0);
        if (m_cadPreparing)
        {
            m_cadPreparing = false;
            CadStatus("failed", message);
        }
        UpdateControls();
        if (m_options.smoke)
        {
            FinishSmoke(false, message);
        }
    }

    void Connect()
    {
        if (m_closing || m_finishing)
        {
            return;
        }
        m_busy = true;
        UpdateControls();
        std::string error;
        if (!m_client.Start(m_options.python.ToStdWstring(), m_options.source.ToStdWstring(), m_options.workspace.ToStdWstring(), error, m_options.cadPython.ToStdWstring(), m_options.openEmsWsl))
        {
            Failure(error, true);
            return;
        }
        Send("capabilities.get", Json::object(), false, Json::object(), [this](const Json& result)
        {
            if (!result.at("idempotency_policy").value("mutations_enabled", false))
            {
                Failure("Service does not enable project mutations.", true);
                return;
            }
            m_epoch = result.at("idempotency_policy").at("request_key_epoch").get<std::string>();
            ++m_serviceSessions;
            m_connected = true;
            m_cadConfigured = result.value("cad_profile", Json::object()).value("runtime_configured", false);
            m_solverConfigured = result.value("solver_profile", Json::object()).value("runtime_configured", false);
            SolverStatus("idle", m_solverConfigured ? "WSL openEMS 준비됨. 물성 및 급전 위치를 명시한 설계를 사용합니다." : "해석 환경 미연결. launch_gui.ps1 -OpenEmsWsl로 실행하세요.");
            CadStatus("idle", m_cadConfigured ? "준비됨. STEP 출력은 현재 적용된 설계의 스냅샷을 사용합니다." :
                "CAD 환경이 연결되지 않았습니다. launch_gui.ps1 -CadPython으로 CAD Python 경로를 지정하세요.");
            m_busy = false;
            SetStatusText(Display("준비됨"), 0);
            Log("프로젝트 서비스에 연결했습니다.");
            UpdateControls();
            if (m_options.cadSmoke || !m_options.openProject.empty())
            {
                OpenProject("open", Utf8(m_options.openProject));
            }
            else if (m_options.primitivesSmoke)
            {
                if (m_primitivesStage == 21 || m_primitivesStage == 106)
                {
                    OpenProject("open", m_smokePath);
                }
                else
                {
                    m_smokePath = "projects/primitives-" + Uuid();
                    OpenProject("create", m_smokePath, "GUI 면 패드 비아 검증");
                }
            }
            else if (m_options.canvasSmoke)
            {
                if (m_canvasStage == 14)
                {
                    OpenProject("open", m_smokePath);
                }
                else
                {
                    m_smokePath = "projects/canvas-" + Uuid();
                    OpenProject("create", m_smokePath, "GUI 2D 선 원호 검증");
                }
            }
            else if (m_options.editorSmoke)
            {
                if (m_editorStage == 10)
                {
                    OpenProject("open", m_smokePath);
                }
                else
                {
                    m_smokePath = "projects/editor-" + Uuid();
                    OpenProject("create", m_smokePath, "GUI 설계 편집 검증");
                }
            }
            else if (m_options.smoke)
            {
                if (m_smokeStage == 4)
                {
                    OpenProject("open", m_smokePath);
                }
                else
                {
                    m_smokePath = "projects/gui-" + Uuid();
                    OpenProject("create", m_smokePath, "GUI 초기 프로젝트");
                }
            }
        });
    }

    void Send(const std::string& method, const Json& input, bool mutation, const Json& context, std::function<void(const Json&)> success, std::function<void(const Json&)> failure = {})
    {
        if (m_pending.size() >= 16)
        {
            Failure("GUI request queue is full.");
            return;
        }
        const std::string id = Uuid();
        Json params{{"contract_version", "rfad.api/2.0"}, {"context", context}, {"input", input}};
        if (mutation)
        {
            params["request_key"] = Uuid();
            params["request_key_epoch"] = m_epoch;
        }
        Json request{{"jsonrpc", "2.0"}, {"id", id}, {"method", method}, {"params", params}};
        const bool foreground = method != "cad.latest" && method != "solver.latest" && method != "solver.samples" && method != "result.open" && method != "job.cancel" &&
            method != "solver.plan" && method != "solver.prepare" && method != "job.submit" &&
            !(method == "snapshot.create" && input.value("description", "") == "GUI PCB 해석 입력") &&
            !(method == "job.status" && (input.value("job_id", "") == m_cadJob || input.value("job_id", "") == m_solverJob));
        m_pending.emplace(id, Pending{Clock::now(), std::move(success), std::move(failure), foreground});
        if (!m_client.Send(request.dump()))
        {
            m_pending.erase(id);
            Failure("Cannot queue service request. No automatic retry is performed.", true);
        }
    }

    Json Context() const
    {
        return Json{{"project_id", m_project}};
    }

    void WaitJob(const Json& task, std::function<void(const Json&)> completed)
    {
        m_activeJob = task.at("job_id").get<std::string>();
        m_jobComplete = std::move(completed);
        m_jobPending = false;
        m_lastPoll = Clock::time_point{};
        SetStatusText(Display("작업 처리 중"), 0);
    }

    void OpenProject(const std::string& mode, const std::string& path, const std::string& name = "")
    {
        if (m_cadPreparing || !m_cadJob.empty() || m_modelView->IsLoading() || m_cadRestoring || m_solverActive || m_solverRestoring)
        {
            Log("CAD/해석 작업 또는 결과 읽기가 끝난 뒤 프로젝트를 전환하세요.");
            return;
        }
        m_canvas->CancelGesture();
        m_busy = true;
        UpdateControls();
        Json input{{"open_mode", mode}, {"path", path}};
        if (mode == "create")
        {
            input["name"] = name;
        }
        Send("project.open", input, true, Json::object(), [this, path](const Json& task)
        {
            WaitJob(task, [this, path](const Json& result)
            {
                m_project = result.at("project_id").get<std::string>();
                m_revision = result.at("revision_id").get<std::string>();
                m_path = path;
                m_scene = Json::object();
                m_modelView->Clear();
                m_cadResult = Json::object();
                m_displayResult = Json::object();
                m_solverChart->Clear();
                m_solverResult = Json::object();
                m_solverSamples = Json::object();
                m_solverViewState->SetLabel(Display("결과 없음 / 단일 포트 PCB 계산 / IFA 및 방사 정확도 검증 전"));
                SolverStatus("idle", "선택한 프로젝트의 완료 결과를 조회합니다.");
                m_problemRevision.clear();
                m_diagnostics = Json::array();
                m_diagnosticCount = 0;
                m_diagnosticsTruncated = false;
                RefreshEditor(Json{{"kind", "project"}, {"id", m_project}}, [this]()
                {
                    Ready("프로젝트를 열었습니다.");
                    RestoreCad();
                    RestoreSolver();
                    if (m_options.solverSmoke)
                    {
                        if (m_solverSmokeStage == 0)
                        {
                            m_solverSmokeStage = 1;
                        }
                    }
                    else if (m_options.cadSmoke)
                    {
                        if (m_cadSmokeStage == 0)
                        {
                            m_cadSmokeStage = 1;
                        }
                    }
                    else if (m_options.primitivesSmoke)
                    {
                        if (m_primitivesStage == 0)
                        {
                            m_primitivesStage = 1;
                        }
                    }
                    else if (m_options.canvasSmoke)
                    {
                        CanvasSmokeNext();
                    }
                    else if (m_options.editorSmoke)
                    {
                        EditorSmokeNext();
                    }
                    else if (m_options.smoke && m_smokeStage == 0)
                    {
                        m_smokeStage = 1;
                        m_name->SetValue(Display("GUI 변경된 프로젝트"));
                        m_description->SetValue(Display("한글 설명 및 공백 경로 검증"));
                        ApplyProperties();
                    }
                    else if (m_options.smoke && m_smokeStage == 4)
                    {
                        if (m_editor.at("metadata").at("name") != "GUI 변경된 프로젝트" ||
                            m_editor.at("metadata").at("description") != "한글 설명 및 공백 경로 검증" ||
                            m_editor.at("saved_revision") != m_revision || m_savedRevision != m_revision)
                        {
                            FinishSmoke(false, "Reopened values do not match saved revision.");
                            return;
                        }
                        m_smokeStage = 5;
                        FinishSmoke(true, "");
                    }
                });
            });
        });
    }

    /** @brief 전체 원본 대신 목록과 선택 객체의 작은 편집 DTO만 조회한다. */
    void RefreshEditor(const Json& selection, std::function<void()> completed)
    {
        m_busy = true;
        UpdateControls();
        Send("editor.get", Json{{"expected_revision", m_revision}, {"selection", selection}}, false, Context(),
            [this, completed](const Json& result)
        {
            if (result.at("profile") != "rfad.editor/0.1" || result.at("revision_id") != m_revision)
            {
                throw std::runtime_error("Unexpected editor profile or revision.");
            }
            m_editor = result;
            m_selection = result.at("selection");
            m_selection.erase("fields");
            m_modelView->SetSelection(m_selection.value("id", ""));
            RefreshProject();
            RefreshScene(completed);
        });
    }

    /** @brief 같은 revision의 표시 DTO는 재사용하고 변경된 표시 데이터만 다시 읽는다. */
    void RefreshScene(std::function<void()> completed)
    {
        if (m_scene.value("revision_id", "") == m_revision)
        {
            m_canvas->SetSelection(m_selection.value("kind", "") == "geometry" ? m_selection.value("id", "") : "");
            completed();
            return;
        }
        Send("canvas.get", Json{{"expected_revision", m_revision}}, false, Context(), [this, completed](const Json& result)
        {
            if (result.at("profile") != "rfad.canvas/0.1" || result.at("revision_id") != m_revision || result.at("unit") != "mm" || result.at("angle_unit") != "deg")
            {
                throw std::runtime_error("Unexpected canvas profile, unit or revision.");
            }
            const bool first = m_scene.empty();
            m_canvas->SetScene(result);
            m_scene = result;
            m_layerChoice->Clear();
            m_layerIds.clear();
            for (const auto& layer : result.at("layers"))
            {
                if (layer.at("role") == "conductor")
                {
                    m_layerIds.push_back(layer.at("id"));
                    m_layerChoice->Append(Display(layer.at("label").get<std::string>()));
                }
            }
            auto active = std::find(m_layerIds.begin(), m_layerIds.end(), m_activeLayer);
            if (active == m_layerIds.end())
            {
                m_activeLayer = m_layerIds.empty() ? "" : m_layerIds.front();
                active = m_layerIds.begin();
            }
            if (!m_layerIds.empty())
            {
                m_layerChoice->SetSelection(static_cast<int>(active - m_layerIds.begin()));
            }
            m_canvas->SetDrawingLayer(m_activeLayer);
            m_canvas->SetSelection(m_selection.value("kind", "") == "geometry" ? m_selection.value("id", "") : "");
            if (first)
            {
                m_canvas->FitView();
                m_canvasHint->SetLabel(Display(m_activeLayer.empty() ?
                    "도체층을 추가한 뒤 선 또는 원호 도구를 선택하세요." :
                    "선 또는 원호 도구를 선택하세요. 휠: 확대/축소, 가운데 버튼: 이동, Esc: 취소"));
            }
            for (const auto& omission : result.at("omissions"))
            {
                Log("표시 생략: " + omission.at("message").get<std::string>());
            }
            ShowProblems();
            completed();
        });
    }

    /** @brief 비동기 조회 중 비활성화한 트리의 키보드 초점을 완료 후 복원한다. */
    void SelectObject(const Json& selection, bool restoreTreeFocus = false)
    {
        RefreshEditor(selection, [this, restoreTreeFocus]()
        {
            Ready("선택한 객체의 속성을 읽었습니다.");
            if (restoreTreeFocus)
            {
                m_tree->SetFocus();
            }
            if (m_canvasAwaitSelection)
            {
                m_canvasAwaitSelection = false;
                CanvasSmokeNext();
            }
        });
    }

    void RefreshProject()
    {
        m_refreshing = true;
        m_name->ChangeValue(Display(m_editor.at("metadata").at("name").get<std::string>()));
        m_description->ChangeValue(Display(m_editor.at("metadata").at("description").get<std::string>()));
        m_tree->Freeze();
        m_tree->DeleteAllItems();
        const wxTreeItemId root = m_tree->AddRoot(m_name->GetValue(), -1, -1,
            new SelectionData(Json{{"kind", "project"}, {"id", m_project}}));
        std::map<std::string, wxTreeItemId> categories;
        const std::pair<const char*, const char*> names[] = {
            {"parameter", "매개변수"}, {"board", "기판"}, {"material", "재료"}, {"layer", "적층"},
            {"net", "네트"}, {"geometry", "형상"}, {"port", "포트"}
        };
        for (const auto& name : names)
        {
            categories.emplace(name.first, m_tree->AppendItem(root, Display(name.second)));
        }
        wxTreeItemId selected = root;
        std::string selectedLabel = "프로젝트 속성";
        for (const auto& item : m_editor.at("items"))
        {
            const std::string kind = item.at("kind").get<std::string>();
            if (kind == "project")
            {
                continue;
            }
            const Json selection{{"kind", kind}, {"id", item.at("id")}};
            const auto parent = categories.find(kind);
            const wxTreeItemId node = m_tree->AppendItem(parent == categories.end() ? root : parent->second,
                Display(item.at("label").get<std::string>()), -1, -1, new SelectionData(selection));
            if (selection == m_selection)
            {
                selected = node;
                selectedLabel = item.at("label").get<std::string>();
            }
        }
        if (m_selection.at("kind").get<std::string>().rfind("new_", 0) == 0)
        {
            const std::string kind = m_selection.at("kind").get<std::string>().substr(4);
            selectedLabel = kind == "parameter" ? "새 매개변수" : (kind == "material" ? "새 재료" : (kind == "net" ? "새 네트" : "새 급전 포트"));
            selected = m_tree->AppendItem(categories.at(kind), Display(selectedLabel), -1, -1, new SelectionData(m_selection));
        }
        m_tree->Expand(root);
        if (m_tree->GetItemParent(selected).IsOk())
        {
            m_tree->Expand(m_tree->GetItemParent(selected));
        }
        m_tree->SelectItem(selected);
        m_tree->Thaw();
        m_selectionLabel->SetLabel(Display(selectedLabel));
        const bool metadata = m_selection.at("kind") == "project";
        m_metadataPanel->Show(metadata);
        m_editorPanel->Show(!metadata);
        m_editorPanel->SetFields(m_editor.at("selection").at("fields"), m_editor.at("selection"), m_editor.value("coordinate_choices", Json::array()));
        m_properties->Layout();
        m_refreshing = false;
        UpdateDraftState();
    }

    /** @brief 폼 변경분을 한 서비스 명령으로 적용하고 권위 DTO로 다시 표시한다. */
    void ApplyCurrent(std::function<void()> completed, std::function<void(const Json&)> rejected = {})
    {
        Json values = Json::object();
        try
        {
            if (m_selection.at("kind") == "project")
            {
                const std::string name = Utf8(m_name->GetValue());
                const std::string description = Utf8(m_description->GetValue());
                if (m_editor.at("metadata").at("name") != name)
                {
                    values["name"] = name;
                }
                if (m_editor.at("metadata").at("description") != description)
                {
                    values["description"] = description;
                }
            }
            else
            {
                values = m_editorPanel->Changes();
            }
        }
        catch (const std::exception& error)
        {
            m_editorPanel->ShowDiagnostic("", error.what());
            Failure(error.what());
            return;
        }
        if (values.empty() && m_selection.at("kind").get<std::string>().rfind("new_", 0) != 0)
        {
            completed();
            return;
        }
        m_busy = true;
        UpdateControls();
        Json target = m_selection;
        if (target.at("kind").get<std::string>().rfind("new_", 0) == 0)
        {
            target["kind"] = target.at("kind").get<std::string>().substr(4);
        }
        Send("editor.apply", Json{{"expected_revision", m_revision}, {"command_id", Uuid()},
            {"selection", m_selection}, {"values", values}}, true, Context(),
            [this, completed, target](const Json& result)
        {
            m_revision = result.at("new_revision").get<std::string>();
            RefreshEditor(target, [this, completed]()
            {
                Ready("변경을 적용했습니다.");
                completed();
            });
        }, std::move(rejected));
    }

    void ApplyProperties()
    {
        if (m_project.empty())
        {
            return;
        }
        ApplyCurrent([this]()
        {
            if (m_options.smoke && !m_options.editorSmoke && m_smokeStage == 1)
            {
                m_smokeStage = 2;
                SaveProject();
            }
        });
    }

    /** @brief undo/redo의 원본과 이력은 서비스가 소유하며 GUI에는 결과 개정만 반영한다. */
    void History(const std::string& method, std::function<void()> completed = {})
    {
        if (!ConfirmDiscard())
        {
            return;
        }
        m_busy = true;
        UpdateControls();
        Send(method, Json{{"expected_revision", m_revision}, {"command_id", Uuid()}}, true, Context(),
            [this, completed](const Json& result)
        {
            m_revision = result.at("new_revision").get<std::string>();
            RefreshEditor(Json{{"kind", "project"}, {"id", m_project}}, [this, completed]()
            {
                Ready("편집 이력을 적용했습니다.");
                if (completed)
                {
                    completed();
                }
            });
        });
    }

    /** @brief 실제 입력 폼과 동일한 명령 경로에서 의존 수식과 영속 이력을 검증한다. */
    void EditorSmokeNext()
    {
        const auto parameter = [](const std::string& identity)
        {
            return Json{{"kind", "parameter"}, {"id", identity}};
        };
        if (m_editorStage == 0)
        {
            CheckUxState("saved", false);
            m_uxChecks.push_back("saved_state");
            const wxMenuItem* redo = GetMenuBar()->FindItem(IdRedo);
            const std::unique_ptr<wxAcceleratorEntry> primary(redo->GetAccel());
            bool alternate = false;
            for (const auto& shortcut : redo->GetExtraAccels())
            {
                if (shortcut.GetFlags() == (wxACCEL_CTRL | wxACCEL_SHIFT) &&
                    shortcut.GetKeyCode() == 'Z' && shortcut.GetCommand() == IdRedo)
                {
                    alternate = true;
                }
            }
            if (!primary || primary->GetFlags() != wxACCEL_CTRL || primary->GetKeyCode() != 'Y' || !alternate)
            {
                throw std::runtime_error("Redo shortcuts were not registered together.");
            }
            m_uxChecks.push_back("redo_aliases_registered");
            m_baseParameter = Uuid();
            m_dependentParameter = Uuid();
            m_editorStage = 1;
            RefreshEditor(Json{{"kind", "new_parameter"}, {"id", m_baseParameter}}, [this]()
            {
                Ready("새 매개변수 입력을 확인합니다.");
                CheckUxState("saved", false);
                m_uxChecks.push_back("blank_parameter_apply_disabled");
                if (m_editorPanel->IsFieldVisible("value"))
                {
                    throw std::runtime_error("Missing parameter exposes a numeric input.");
                }
                m_uxChecks.push_back("missing_value_hidden");
                m_editorPanel->SetFieldValue("mode", "value");
                m_editorPanel->SetFieldValue("value", "40");
                CheckUxState("draft", false);
                m_uxChecks.push_back("unnamed_parameter_apply_disabled");
                m_editorPanel->SetFieldValue("name", "기판 폭");
                CheckUxState("draft", true);
                m_uxChecks.push_back("draft_state_and_apply_enabled");
                ApplyCurrent([this]()
                {
                    CheckUxState("applied", false);
                    m_uxChecks.push_back("applied_state_and_apply_disabled");
                    m_editorPanel->SetFieldValue("value", m_editorPanel->FieldValue("value"));
                    CheckUxState("applied", false);
                    m_uxChecks.push_back("unchanged_input_apply_disabled");
                    m_editorPanel->SetFieldValue("unit", "m");
                    const std::string notice = m_editorPanel->InputNotice();
                    if (notice.empty() || notice.find("적용 후 환산") == std::string::npos)
                    {
                        throw std::runtime_error("Unit-only draft does not explain deferred display conversion.");
                    }
                    m_editorPanel->SetFieldValue("unit", "mm");
                    if (!m_editorPanel->InputNotice().empty())
                    {
                        throw std::runtime_error("Restored display unit retains an obsolete conversion notice.");
                    }
                    CheckUxState("applied", false);
                    m_uxChecks.push_back("unit_change_explained");
                    m_editorChecks.push_back("parameter_created");
                    EditorSmokeNext();
                });
            });
        }
        else if (m_editorStage == 1)
        {
            m_editorStage = 2;
            RefreshEditor(Json{{"kind", "new_parameter"}, {"id", m_dependentParameter}}, [this]()
            {
                m_editorPanel->SetFieldValue("name", "절반 폭");
                m_editorPanel->SetFieldValue("mode", "expression");
                m_editorPanel->SetFieldValue("expression", "width / 2");
                m_editorPanel->SetFieldValue("bindings", Json{{"width", m_baseParameter}});
                if (!m_editorPanel->IsFieldVisible("value") || !m_editorPanel->IsFieldVisible("expression") ||
                    !m_editorPanel->IsFieldVisible("bindings"))
                {
                    throw std::runtime_error("Expression input or calculated value is hidden.");
                }
                m_uxChecks.push_back("expression_fields_visible");
                ApplyCurrent([this]()
                {
                    CheckEditorValue(20.0);
                    m_editorChecks.push_back("expression_bound");
                    EditorSmokeNext();
                });
            });
        }
        else if (m_editorStage == 2)
        {
            m_editorStage = 3;
            RefreshEditor(parameter(m_baseParameter), [this]()
            {
                m_editorPanel->SetFieldValue("value", "60");
                ApplyCurrent([this]()
                {
                    EditorSmokeNext();
                });
            });
        }
        else if (m_editorStage == 3)
        {
            m_editorStage = 4;
            RefreshEditor(parameter(m_dependentParameter), [this]()
            {
                CheckEditorValue(30.0);
                m_editorChecks.push_back("dependency_recalculated");
                m_failureRevision = m_revision;
                m_editorPanel->SetFieldValue("expression", "width / 0");
                ApplyCurrent([this]()
                {
                    FinishSmoke(false, "Invalid expression unexpectedly succeeded.");
                }, [this](const Json& error)
                {
                    if (error.at("data").at("domain_code") != "E_EXPR_DOMAIN" ||
                        m_revision != m_failureRevision || m_editorPanel->FieldValue("expression") != "width / 0")
                    {
                        FinishSmoke(false, "Rejected editor input or revision was not preserved.");
                        return;
                    }
                    if (m_editorPanel->DiagnosticField() != "expression")
                    {
                        FinishSmoke(false, "Expression diagnostic did not identify its input field.");
                        return;
                    }
                    m_uxChecks.push_back("expression_error_localized");
                    CheckUxState("draft", true);
                    m_uxChecks.push_back("rejected_draft_stays_editable");
                    m_editorChecks.push_back("invalid_input_preserved");
                    m_editorPanel->SetFieldValue("expression", "width / 2");
                    m_editorStage = 5;
                    EditorSmokeNext();
                });
            });
        }
        else if (m_editorStage == 5)
        {
            m_editorStage = 6;
            History("project.undo", [this, parameter]()
            {
                RefreshEditor(parameter(m_dependentParameter), [this]()
                {
                    CheckEditorValue(20.0);
                    m_editorChecks.push_back("undo_recalculated");
                    Ready("실행 취소 확인");
                    EditorSmokeNext();
                });
            });
        }
        else if (m_editorStage == 6)
        {
            m_editorStage = 7;
            History("project.redo", [this, parameter]()
            {
                RefreshEditor(parameter(m_dependentParameter), [this]()
                {
                    CheckEditorValue(30.0);
                    m_editorChecks.push_back("redo_recalculated");
                    Ready("다시 실행 확인");
                    EditorSmokeNext();
                });
            });
        }
        else if (m_editorStage == 7)
        {
            m_editorStage = 8;
            SaveProject();
        }
        else if (m_editorStage == 10)
        {
            RefreshEditor(parameter(m_dependentParameter), [this]()
            {
                CheckEditorValue(30.0);
                if (m_editor.at("saved_revision") != m_revision || m_savedRevision != m_revision ||
                    !m_editor.at("history").value("can_undo", false) || m_serviceSessions != 2)
                {
                    FinishSmoke(false, "Editor state or durable history was lost after restart.");
                    return;
                }
                m_editorChecks.push_back("restart_preserved");
                Ready("저장된 편집 상태를 확인했습니다.");
                CheckUxState("saved", false);
                m_uxChecks.push_back("saved_after_restart");
                m_editorStage = 11;
                FinishSmoke(true, "");
            });
        }
    }

    /** @brief smoke에서 서비스가 환산한 표시값만 읽고 기대 결과와 비교한다. */
    void CheckEditorValue(double expected) const
    {
        const std::string text = m_editorPanel->FieldValue("value").get<std::string>();
        if (std::abs(std::stod(text) - expected) > 1e-9)
        {
            throw std::runtime_error("Editor computed value mismatch: " + text);
        }
    }

    /** @brief 실제 입력 이벤트 뒤의 상태 표시와 적용 가능 여부를 smoke에서 확인한다. */
    void CheckUxState(const std::string& expected, bool applyEnabled) const
    {
        const std::string label = expected == "draft" ? "미적용 입력" :
            (expected == "applied" ? "적용됨 (저장 필요)" : "저장됨");
        const std::string name = m_editor.at("metadata").at("name").get<std::string>();
        if (m_editState != expected || m_apply->IsEnabled() != applyEnabled ||
            Utf8(m_revisionLabel->GetLabel()) != label || Utf8(GetStatusBar()->GetStatusText(1)) != label ||
            !GetTitle().StartsWith(Display(name + " - ")) || GetTitle().Contains(Display(m_revision)) ||
            !m_revisionLabel->GetToolTipText().Contains(Display(m_revision)))
        {
            throw std::runtime_error("Editor state, title or apply availability does not match " + expected);
        }
    }

    /** @brief 실제 캔버스 이벤트 처리기로 좌표 입력을 보내 서비스 저장까지 확인한다. */
    void CanvasMouse(wxEventType type, double x, double y, bool left = false, bool middle = false)
    {
        wxMouseEvent event(type);
        event.SetPosition(m_canvas->WorldToScreen(wxPoint2DDouble(x, y)));
        event.SetLeftDown(left);
        event.SetMiddleDown(middle);
        event.SetEventObject(m_canvas);
        m_canvas->GetEventHandler()->ProcessEvent(event);
    }

    void CanvasClick(double x, double y)
    {
        CanvasMouse(wxEVT_LEFT_DOWN, x, y, true);
        CanvasMouse(wxEVT_LEFT_UP, x, y);
    }

    Json CanvasShape(const std::string& id) const
    {
        for (const auto& shape : m_scene.at("shapes"))
        {
            if (shape.at("id") == id)
            {
                return shape;
            }
        }
        throw std::runtime_error("Canvas smoke shape missing.");
    }

    void CanvasAssert(bool condition, const std::string& message) const
    {
        if (!condition)
        {
            throw std::runtime_error(message);
        }
    }

    /** @brief 새로운 면/패드/비아를 실제 선택과 드래그 및 속성 명령으로 검증한다. */
    void PrimitivesSmokeTick()
    {
        if (!m_options.primitivesSmoke || m_busy || m_cadRestoring || m_solverRestoring || !m_connected || m_finishing || m_primitivesStage == 0)
        {
            return;
        }
        auto create = [this](int next, const std::string& operation, const Json& values)
        {
            m_primitivesStage = next;
            CanvasCommand(operation, values);
        };
        if (m_primitivesStage == 1)
        {
            create(2, "create_circular_board", Json{{"id", Uuid()}, {"center_x_mm", 0}, {"center_y_mm", 0}, {"radius_mm", 35}});
        }
        else if (m_primitivesStage == 2)
        {
            m_primitivesLayerA = Uuid();
            create(3, "create_layer", Json{{"id", m_primitivesLayerA}, {"name", "Top"}});
        }
        else if (m_primitivesStage == 3 && m_options.coordinatesSmoke)
        {
            Json outer = Json::array();
            for (int index = 0; index < 64; ++index)
            {
                const double angle = index * 2.0 * 3.14159265358979323846 / 64;
                outer.push_back(Json::array({10.0 * std::cos(angle), 10.0 * std::sin(angle)}));
            }
            m_primitivesPolygon = Uuid();
            create(101, "create_polygon", Json{{"id", m_primitivesPolygon}, {"layer_id", m_primitivesLayerA}, {"outer", outer}, {"holes", Json::array()}});
        }
        else if (m_primitivesStage == 3)
        {
            m_primitivesLayerB = Uuid();
            create(4, "create_layer", Json{{"id", m_primitivesLayerB}, {"name", "Bottom"}});
        }
        else if (m_primitivesStage == 4)
        {
            Json values = ParsePolygonInput("-20,-20\n20,-20\n20,20\n-20,20\n\n-4,-4\n4,-4\n4,4\n-4,4\n");
            m_primitivesPolygon = Uuid();
            values["id"] = m_primitivesPolygon;
            values["layer_id"] = m_primitivesLayerA;
            create(5, "create_polygon", values);
        }
        else if (m_primitivesStage == 5 || m_primitivesStage == 6 || m_primitivesStage == 7)
        {
            const bool rectangle = m_primitivesStage == 6;
            const std::string id = Uuid();
            if (rectangle)
            {
                m_primitivesRectangle = id;
            }
            else
            {
                m_primitivesPads.push_back(id);
            }
            create(m_primitivesStage + 1, "create_pad", Json{{"id", id}, {"layer_id", m_primitivesStage == 7 ? m_primitivesLayerB : m_primitivesLayerA},
                {"pad_shape", rectangle ? "rectangle" : "circle"}, {"center", Json::array({rectangle ? -10.0 : 10.0, 0.0})},
                {"width_mm", 4.0}, {"height_mm", rectangle ? 2.0 : 4.0}, {"rotation_deg", rectangle ? 45.0 : 0.0}});
        }
        else if (m_primitivesStage == 8 || m_primitivesStage == 9)
        {
            const bool missing = m_primitivesStage == 8;
            const std::string id = Uuid();
            if (missing)
            {
                m_primitivesMissingVia = id;
            }
            else
            {
                m_primitivesVia = id;
            }
            create(m_primitivesStage + 1, "create_via", Json{{"id", id}, {"layer_id", m_primitivesLayerA}, {"end_layer_id", m_primitivesLayerB},
                {"center", Json::array({missing ? -10.0 : 10.0, missing ? 10.0 : 0.0})},
                {"finished_hole_diameter_mm", missing ? Json(nullptr) : Json(0.8)}, {"plating_thickness_mm", missing ? Json(nullptr) : Json(0.1)},
                {"tool_hole_diameter_mm", missing ? Json(nullptr) : Json(1.0)}, {"pad_ids", missing ? Json::array() : m_primitivesPads}});
        }
        else if (m_primitivesStage == 10)
        {
            CanvasAssert(m_scene.at("shapes").size() == 6, "Primitive creation omitted display objects.");
            m_canvas->FitView();
            m_canvas->SetTool("select");
            CanvasAssert(m_canvas->HitTest(m_canvas->WorldToScreen(wxPoint2DDouble(0, 0))).empty(), "Polygon hole was filled or selectable.");
            CanvasAssert(m_canvas->HitTest(m_canvas->WorldToScreen(wxPoint2DDouble(0, 15))) == m_primitivesPolygon, "Polygon interior is not selectable.");
            CanvasAssert(CanvasShape(m_primitivesVia).at("span_layer_ids").size() == 2, "Via layer span is incomplete.");
            CanvasAssert(CanvasShape(m_primitivesMissingVia).at("finished_hole_diameter").is_null(), "Missing via diameter was fabricated.");
            m_primitivesChecks.push_back("polygon_holes_and_pad_via_display");
            CanvasAssert(m_editorPanel->FieldValue("pad_ids").size() == 2 && !HasDraft(), "Via pad references were not read without changing order.");
            m_editorPanel->SetFieldValue("pad_ids", Json::array({m_primitivesPads.at(0)}));
            m_primitivesStage = 23;
            ApplyCurrent([]()
            {
            });
        }
        else if (m_primitivesStage == 23)
        {
            CanvasAssert(m_editorPanel->FieldValue("pad_ids").size() == 1, "Via pad multichoice edit did not persist.");
            m_primitivesStage = 24;
            History("project.undo", [this]()
            {
                SelectObject(Json{{"kind", "geometry"}, {"id", m_primitivesVia}});
            });
        }
        else if (m_primitivesStage == 24)
        {
            CanvasAssert(m_editorPanel->FieldValue("pad_ids").size() == 2, "Via pad reference undo failed.");
            m_primitivesChecks.push_back("via_pad_multichoice_and_undo");
            m_primitivesStage = 11;
            CanvasClick(-10, 0);
        }
        else if (m_primitivesStage == 11)
        {
            CanvasAssert(m_selection.at("id") == m_primitivesRectangle && m_canvas->Selection() == m_primitivesRectangle, "Rotated pad selection did not reach properties.");
            m_editorPanel->SetFieldValue("center.0.value", "-9");
            m_primitivesStage = 12;
            ApplyCurrent([]()
            {
            });
        }
        else if (m_primitivesStage == 12)
        {
            CanvasAssert(CanvasShape(m_primitivesRectangle).at("center").at(0) == -9.0, "Pad property edit did not reach canvas.");
            m_primitivesChecks.push_back("rotated_pad_selection_and_properties");
            m_primitivesOriginalPolygon = CanvasShape(m_primitivesPolygon);
            m_canvasUndoBefore = m_editor.at("history").at("undo_count");
            m_primitivesStage = 13;
            CanvasMouse(wxEVT_LEFT_DOWN, 0, 15, true);
            CanvasMouse(wxEVT_MOTION, 2, 16, true);
            CanvasMouse(wxEVT_LEFT_UP, 2, 16);
        }
        else if (m_primitivesStage == 13)
        {
            const Json polygon = CanvasShape(m_primitivesPolygon);
            const double dx = polygon.at("outer").at(0).at(0).get<double>() + 20.0;
            CanvasAssert(std::abs(dx - 2) < 0.25 && std::abs(polygon.at("holes").at(0).at(0).at(0).get<double>() + 4.0 - dx) < 1e-8,
                "Polygon drag failed to move its hole with its outline.");
            CanvasAssert(m_editor.at("history").at("undo_count").get<int>() == m_canvasUndoBefore + 1, "Polygon drag produced several history commands.");
            m_primitivesMovedPolygon = polygon;
            m_primitivesStage = 14;
            History("project.undo");
        }
        else if (m_primitivesStage == 14)
        {
            CanvasAssert(CanvasShape(m_primitivesPolygon) == m_primitivesOriginalPolygon, "Polygon undo lost its hole.");
            m_primitivesStage = 15;
            History("project.redo");
        }
        else if (m_primitivesStage == 15)
        {
            CanvasAssert(CanvasShape(m_primitivesPolygon) == m_primitivesMovedPolygon, "Polygon redo failed.");
            m_primitivesChecks.push_back("polygon_drag_single_command_and_history");
            m_canvas->SetLayerVisible(m_primitivesLayerA, false);
            CanvasAssert(m_canvas->HitTest(m_canvas->WorldToScreen(wxPoint2DDouble(10, 0))) == m_primitivesVia, "Via disappeared on its visible end layer.");
            m_canvas->SetLayerVisible(m_primitivesLayerB, false);
            CanvasAssert(m_canvas->HitTest(m_canvas->WorldToScreen(wxPoint2DDouble(10, 0))).empty(), "Fully hidden via remained selectable.");
            m_canvas->SetLayerVisible(m_primitivesLayerA, true);
            m_canvas->SetLayerVisible(m_primitivesLayerB, true);
            m_primitivesChecks.push_back("via_visibility_uses_full_layer_span");
            m_primitivesStage = 16;
            SelectObject(Json{{"kind", "geometry"}, {"id", m_primitivesMissingVia}});
        }
        else if (m_primitivesStage == 16)
        {
            CanvasAssert(m_editorPanel->FieldValue("finished_hole_diameter.mode") == "missing", "Via missing input mode was lost.");
            m_editorPanel->SetFieldValue("plating_thickness.mode", "value");
            m_editorPanel->SetFieldValue("plating_thickness.unit", "mm");
            m_editorPanel->SetFieldValue("plating_thickness.value", "0.1");
            m_primitivesStage = 17;
            ApplyCurrent([]()
            {
            });
        }
        else if (m_primitivesStage == 17)
        {
            const Json via = CanvasShape(m_primitivesMissingVia);
            CanvasAssert(via.at("finished_hole_diameter").is_null() && via.at("tool_hole_diameter").is_null() && via.at("plating_thickness") == 0.1,
                "Via editing fabricated missing manufacturing inputs.");
            m_primitivesStage = 18;
            History("project.undo");
        }
        else if (m_primitivesStage == 18)
        {
            CanvasAssert(CanvasShape(m_primitivesMissingVia).at("plating_thickness").is_null(), "Via undo did not restore missing input.");
            m_primitivesChecks.push_back("via_missing_inputs_edit_and_undo");
            m_primitivesSavedShapes = m_scene.at("shapes");
            m_primitivesStage = 19;
            SaveProject();
        }
        else if (m_primitivesStage == 19)
        {
            CanvasAssert(m_savedRevision == m_revision, "Primitive save did not settle.");
            m_primitivesStage = 20;
            Snapshot();
        }
        else if (m_primitivesStage == 20)
        {
            CanvasAssert(!m_snapshot.empty(), "Primitive snapshot was not created.");
            m_primitivesStage = 21;
            m_connected = false;
            m_transportFailed = false;
            m_restarting = true;
            BeginShutdown();
        }
        else if (m_primitivesStage == 101)
        {
            Json coordinates = m_editorPanel->FieldValue("outer");
            CanvasAssert(coordinates.size() == 64 && !HasDraft(), "A 64-point coordinate table changed source or exceeded the DTO.");
            m_primitivesStage = 102;
            m_busy = true;
            m_editorPanel->EditCoordinateCellForSmoke("outer", 0, 0, "11");
            m_busy = false;
            ApplyCurrent([]()
            {
            });
        }
        else if (m_primitivesStage == 102)
        {
            CanvasAssert(CanvasShape(m_primitivesPolygon).at("outer").at(0).at(0) == 11.0 && m_editorPanel->FieldValue("outer").size() == 64,
                "Coordinate table edit did not preserve all vertices.");
            m_primitivesChecks.push_back("64_point_coordinate_table_edit");
            m_primitivesStage = 103;
            History("project.undo");
        }
        else if (m_primitivesStage == 103)
        {
            CanvasAssert(CanvasShape(m_primitivesPolygon).at("outer").at(0).at(0) == 10.0, "Coordinate table undo failed.");
            m_primitivesChecks.push_back("coordinate_table_undo");
            m_primitivesSavedShapes = m_scene.at("shapes");
            m_primitivesStage = 104;
            SaveProject();
        }
        else if (m_primitivesStage == 104)
        {
            CanvasAssert(m_savedRevision == m_revision, "Coordinate table save failed.");
            m_primitivesStage = 105;
            Snapshot();
        }
        else if (m_primitivesStage == 105)
        {
            m_primitivesStage = 106;
            m_connected = false;
            m_transportFailed = false;
            m_restarting = true;
            BeginShutdown();
        }
        else if (m_primitivesStage == 21 || m_primitivesStage == 106)
        {
            CanvasAssert(m_serviceSessions == 2 && m_scene.at("shapes") == m_primitivesSavedShapes && m_editor.at("saved_revision") == m_revision,
                "Primitive source or missing inputs changed after reopening.");
            m_primitivesChecks.push_back("save_snapshot_restart_preserves_primitives");
            m_primitivesStage = 22;
            FinishSmoke(true, "");
        }
    }

    /** @brief 도킹 창과 선/원호의 입력, 선택, 이동, 이력 및 재시작을 통합 검사한다. */
    void CanvasSmokeNext()
    {
        if (m_canvasStage == 0)
        {
            CanvasAssert(m_manager->GetPane("canvas").IsOk() && m_manager->GetPane("properties").IsOk() && m_manager->GetPane("problems").IsOk(), "Docking shell missing.");
            for (const int id : {IdCreate, IdOpen, IdSave, IdSnapshot, IdUndo, IdRedo})
            {
                const wxButton* button = m_tools.at(id);
                const wxSize area = button->GetParent()->GetClientSize();
                CanvasAssert(button->GetRect().GetBottom() <= area.GetHeight() && button->GetRect().GetRight() <= area.GetWidth() && button->GetSize().GetHeight() > 0,
                    "Workspace toolbar is clipped.");
            }
            m_canvasChecks.push_back("docking_shell");
            m_canvasStage = 1;
            CanvasCommand("create_board", Json{{"id", Uuid()}, {"width_mm", 40.0}, {"height_mm", 60.0}});
        }
        else if (m_canvasStage == 1)
        {
            m_canvasStage = 2;
            CanvasCommand("create_layer", Json{{"id", Uuid()}, {"name", "검증 도체층"}});
        }
        else if (m_canvasStage == 2)
        {
            CanvasAssert(!m_activeLayer.empty() && m_scene.at("board").at("width") == 40.0, "Drawing prerequisites not available.");
            m_canvas->FitView();
            m_canvas->SetTool("line");
            CanvasClick(5, 5);
            wxKeyEvent escape(wxEVT_KEY_DOWN);
            escape.m_keyCode = WXK_ESCAPE;
            m_canvas->GetEventHandler()->ProcessEvent(escape);
            CanvasAssert(!m_canvas->HasGesture() && m_scene.at("shapes").empty(), "Escape committed a drawing.");
            m_canvasChecks.push_back("escape_cancels_preview");
            m_canvas->SetTool("line");
            m_canvasStage = 3;
            CanvasClick(5, 5);
            CanvasClick(25, 5);
        }
        else if (m_canvasStage == 3)
        {
            CanvasAssert(m_scene.at("shapes").size() == 1 && m_scene.at("shapes").at(0).at("kind") == "line_path", "Two-click line failed.");
            m_canvasLine = m_scene.at("shapes").at(0).at("id");
            m_canvasOriginalLine = CanvasShape(m_canvasLine);
            m_canvasChecks.push_back("two_click_line");
            m_canvas->SetTool("arc");
            m_canvasStage = 4;
            CanvasClick(20, 30);
            CanvasClick(30, 30);
            CanvasClick(20, 40);
        }
        else if (m_canvasStage == 4)
        {
            CanvasAssert(m_scene.at("shapes").size() == 2, "Three-click arc failed.");
            for (const auto& shape : m_scene.at("shapes"))
            {
                if (shape.at("kind") == "arc_path")
                {
                    m_canvasArc = shape.at("id");
                    CanvasAssert(std::abs(shape.at("sweep_angle").get<double>() - 90.0) < 2.0, "Arc direction is not CCW.");
                }
            }
            CanvasAssert(!m_canvasArc.empty() && m_canvas->HitTest(m_canvas->WorldToScreen(wxPoint2DDouble(20, 20))) != m_canvasArc, "Arc hit testing includes the unused circle.");
            m_canvasChecks.push_back("three_click_arc_and_hit_test");
            m_canvas->SetTool("select");
            m_canvasStage = 5;
            m_canvasAwaitSelection = true;
            CanvasClick(15, 5);
        }
        else if (m_canvasStage == 5)
        {
            CanvasAssert(m_selection.at("id") == m_canvasLine && m_canvas->Selection() == m_canvasLine, "Canvas selection does not match properties.");
            m_canvasChecks.push_back("selection_sync");
            m_canvasUndoBefore = m_editor.at("history").at("undo_count");
            const std::string before = m_revision;
            m_canvasStage = 6;
            CanvasMouse(wxEVT_LEFT_DOWN, 15, 5, true);
            CanvasMouse(wxEVT_MOTION, 18, 7, true);
            CanvasAssert(m_revision == before, "Drag preview mutated the project.");
            CanvasMouse(wxEVT_LEFT_UP, 18, 7);
        }
        else if (m_canvasStage == 6)
        {
            const Json moved = CanvasShape(m_canvasLine);
            CanvasAssert(std::abs(moved.at("start").at(0).get<double>() - m_canvasOriginalLine.at("start").at(0).get<double>() - 3.0) < 0.25, "Drag X translation failed.");
            CanvasAssert(m_editor.at("history").at("undo_count").get<int>() == m_canvasUndoBefore + 1, "Drag is not one history entry.");
            m_canvasChecks.push_back("drag_one_command");
            m_canvasMovedLine = moved;
            m_canvasStage = 7;
            History("project.undo", [this]()
            {
                CanvasSmokeNext();
            });
        }
        else if (m_canvasStage == 7)
        {
            CanvasAssert(CanvasShape(m_canvasLine) == m_canvasOriginalLine, "Undo did not restore line.");
            m_canvasStage = 8;
            History("project.redo", [this]()
            {
                CanvasSmokeNext();
            });
        }
        else if (m_canvasStage == 8)
        {
            CanvasAssert(CanvasShape(m_canvasLine) == m_canvasMovedLine, "Redo did not restore moved line.");
            m_canvasChecks.push_back("drag_undo_redo");
            RefreshEditor(Json{{"kind", "geometry"}, {"id", m_canvasLine}}, [this]()
            {
                m_editorPanel->SetFieldValue("end.0.value", "32");
                m_canvasStage = 9;
                ApplyCurrent([this]()
            {
                CanvasSmokeNext();
            });
            });
        }
        else if (m_canvasStage == 9)
        {
            CanvasAssert(CanvasShape(m_canvasLine).at("end").at(0) == 32.0, "Property change did not refresh canvas.");
            m_canvasChecks.push_back("property_to_canvas");
            m_canvas->SetSelection(m_canvasArc);
            const std::string before = m_revision;
            m_busy = true;
            m_canvas->onAction(Json{{"type", "translate"}, {"id", m_canvasArc}, {"delta", Json::array({1.0, 0.0})}});
            CanvasAssert(m_canvas->Selection() == m_canvasLine && m_selection.at("id") == m_canvasLine && m_revision == before, "Rejected gesture did not restore authoritative selection.");
            m_busy = false;
            UpdateControls();
            m_canvasChecks.push_back("rejected_gesture_restores_selection");
            m_canvasStage = 10;
            CanvasCommand("remove", Json{{"id", m_canvasLine}});
        }
        else if (m_canvasStage == 10)
        {
            CanvasAssert(m_scene.at("shapes").size() == 1, "Delete failed.");
            m_canvasStage = 11;
            History("project.undo", [this]()
            {
                CanvasSmokeNext();
            });
        }
        else if (m_canvasStage == 11)
        {
            CanvasAssert(m_scene.at("shapes").size() == 2 && CanvasShape(m_canvasLine).at("end").at(0) == 32.0, "Delete undo failed.");
            m_canvasChecks.push_back("delete_undo");
            const Json line = CanvasShape(m_canvasLine);
            const wxPoint2DDouble midpoint((line.at("start").at(0).get<double>() + line.at("end").at(0).get<double>()) / 2.0,
                (line.at("start").at(1).get<double>() + line.at("end").at(1).get<double>()) / 2.0);
            Json boundary = m_scene;
            boundary["board"]["width"] = nullptr;
            Json huge = line;
            huge["id"] = Uuid();
            huge["start"] = Json::array({1e10, 1e10});
            huge["end"] = Json::array({1e10 + 10, 1e10});
            boundary["shapes"].push_back(huge);
            m_canvas->SetScene(boundary);
            CanvasAssert(m_canvas->DisplayOmissionCount() >= 1 && m_canvas->HitTest(m_canvas->WorldToScreen(midpoint)) == m_canvasLine, "An unrenderable object hid valid geometry.");
            m_canvas->SetScene(m_scene);
            m_canvasChecks.push_back("display_limits_preserve_valid_shapes");
            const std::string revision = m_revision;
            const wxPoint anchor = m_canvas->WorldToScreen(midpoint);
            const auto before = m_canvas->ScreenToWorld(anchor);
            wxMouseEvent wheel(wxEVT_MOUSEWHEEL);
            wheel.SetPosition(anchor);
            wheel.m_wheelRotation = 120;
            wheel.m_wheelDelta = 120;
            m_canvas->GetEventHandler()->ProcessEvent(wheel);
            const auto after = m_canvas->ScreenToWorld(anchor);
            CanvasAssert(std::hypot(before.m_x - after.m_x, before.m_y - after.m_y) < 1e-7, "Zoom moved its world anchor.");
            m_canvas->SetLayerVisible(m_activeLayer, false);
            CanvasAssert(m_canvas->HitTest(anchor).empty(), "Hidden layer remains selectable.");
            m_canvas->SetLayerVisible(m_activeLayer, true);
            wxMouseEvent panStart(wxEVT_MIDDLE_DOWN);
            panStart.SetPosition(anchor);
            panStart.SetMiddleDown(true);
            m_canvas->GetEventHandler()->ProcessEvent(panStart);
            wxMouseEvent panMove(wxEVT_MOTION);
            panMove.SetPosition(anchor + wxPoint(20, 10));
            panMove.SetMiddleDown(true);
            m_canvas->GetEventHandler()->ProcessEvent(panMove);
            wxMouseEvent panEnd(wxEVT_MIDDLE_UP);
            panEnd.SetPosition(anchor + wxPoint(20, 10));
            m_canvas->GetEventHandler()->ProcessEvent(panEnd);
            CanvasAssert(m_canvas->WorldToScreen(midpoint) == anchor + wxPoint(20, 10) && m_revision == revision, "View-only pan mutated geometry or failed.");
            m_canvas->FitView();
            m_canvasChecks.push_back("view_controls_do_not_edit");
            m_canvasSavedShapes = m_scene.at("shapes");
            m_canvasStage = 12;
            ValidateInput([this]()
            {
                CanvasAssert(!m_diagnostics.empty() && m_problemRevision == m_revision, "Missing EM inputs were not shown.");
                for (std::size_t index = 0; index < m_diagnostics.size(); ++index)
                {
                    CanvasAssert(Utf8(m_problems->GetItemText(static_cast<long>(index), 1)) ==
                        m_diagnostics.at(index).at("message_ko").get<std::string>(),
                        "The problem list lost the service's Korean diagnostic message.");
                }
                m_canvasChecks.push_back("input_check_not_simulation");
                SaveProject();
            });
        }
        else if (m_canvasStage == 14)
        {
            CanvasAssert(m_scene.at("shapes") == m_canvasSavedShapes && m_savedRevision == m_revision && m_editor.at("saved_revision") == m_revision, "Canvas persistence failed.");
            m_canvasChecks.push_back("save_snapshot_restart");
            m_canvasStage = 15;
            FinishSmoke(true, "");
        }
    }

    void SaveProject()
    {
        if (HasDraft())
        {
            ApplyCurrent([this]()
            {
                SaveProject();
            });
            return;
        }
        m_busy = true;
        UpdateControls();
        Send("project.save", Json{{"expected_revision", m_revision}}, true, Context(), [this](const Json& task)
        {
            WaitJob(task, [this](const Json& result)
            {
                m_savedRevision = result.at("saved_revision").get<std::string>();
                m_editor["saved_revision"] = m_savedRevision;
                Ready("현재 설계 버전을 저장했습니다.");
                if (m_options.canvasSmoke && m_canvasStage == 12)
                {
                    m_canvasStage = 13;
                    Snapshot();
                }
                else if (m_options.editorSmoke && m_editorStage == 8)
                {
                    CheckUxState("saved", false);
                    m_uxChecks.push_back("saved_after_apply");
                    m_editorStage = 9;
                    Snapshot();
                }
                else if (m_options.smoke && m_smokeStage == 2)
                {
                    m_smokeStage = 3;
                    Snapshot();
                }
            });
        });
    }

    void Snapshot()
    {
        if (HasDraft())
        {
            ApplyCurrent([this]()
            {
                Snapshot();
            });
            return;
        }
        m_busy = true;
        UpdateControls();
        Send("snapshot.create", Json{{"expected_revision", m_revision}, {"description", "GUI에서 생성한 스냅샷"}}, true, Context(), [this](const Json& task)
        {
            WaitJob(task, [this](const Json& result)
            {
                m_snapshot = result.at("snapshot_id").get<std::string>();
                Ready("스냅샷을 만들었습니다: " + m_snapshot);
                if (m_options.canvasSmoke && m_canvasStage == 13)
                {
                    m_canvasStage = 14;
                    m_connected = false;
                    m_transportFailed = false;
                    m_restarting = true;
                    BeginShutdown();
                }
                else if (m_options.editorSmoke && m_editorStage == 9)
                {
                    m_editorStage = 10;
                    m_connected = false;
                    m_transportFailed = false;
                    m_restarting = true;
                    BeginShutdown();
                }
                else if (m_options.smoke && m_smokeStage == 3)
                {
                    m_smokeStage = 4;
                    m_connected = false;
                    m_transportFailed = false;
                    m_restarting = true;
                    BeginShutdown();
                }
            });
        });
    }

    void Ready(const std::string& message)
    {
        m_busy = false;
        SetStatusText(Display("준비됨"), 0);
        Log(message);
        UpdateControls();
    }

    void OnTimer(wxTimerEvent&)
    {
        if ((m_finishing && !m_waitingClose) || m_restarting || m_closing)
        {
            return;
        }
        try
        {
            for (auto& incoming : m_client.Drain())
            {
                if (!incoming.protocol)
                {
                    Log(incoming.text);
                    continue;
                }
                const Json response = Json::parse(incoming.text);
                if (!response.is_object() || !response.contains("id") || !response["id"].is_string())
                {
                    Failure("Unexpected service protocol response.", true);
                    return;
                }
                const std::string id = response["id"].get<std::string>();
                auto found = m_pending.find(id);
                if (found == m_pending.end())
                {
                    continue;
                }
                auto callback = std::move(found->second.success);
                auto rejected = std::move(found->second.failure);
                const bool foreground = found->second.foreground;
                m_pending.erase(found);
                if (response.contains("error"))
                {
                    const Json& error = response.at("error");
                    std::string field;
                    const Json data = error.value("data", Json::object());
                    for (const auto& diagnostic : data.value("diagnostics", Json::array()))
                    {
                        const Json details = diagnostic.value("details", Json::object());
                        field = details.value("field_path", std::string());
                        if (!field.empty())
                        {
                            break;
                        }
                    }
                    const std::string message = error.value("message", std::string("Service error"));
                    if (foreground)
                    {
                        m_busy = false;
                        UpdateControls();
                    }
                    const std::string readable = foreground ? m_editorPanel->ShowDiagnostic(field, message) : message;
                    if (rejected)
                    {
                        rejected(error);
                    }
                    else
                    {
                        Failure(readable);
                    }
                    if (m_finishing || m_restarting || m_closing || !m_connected)
                    {
                        return;
                    }
                    continue;
                }
                callback(response.at("result"));
                if (m_finishing || m_restarting || m_closing)
                {
                    return;
                }
            }
            const std::string transportError = m_client.Error();
            if (!transportError.empty() && !m_transportFailed)
            {
                m_transportFailed = true;
                Failure(transportError, true);
                return;
            }
            const auto now = Clock::now();
            PollCad(now);
            PollSolver(now);
            CadSmokeTick();
            SolverSmokeTick();
            PrimitivesSmokeTick();
            if (m_waitingClose && ((!m_solverActive && m_cadJob.empty() && !m_cadPreparing) || now >= m_closeDeadline))
            {
                Close();
                return;
            }
            if (m_restarting || m_finishing)
            {
                return;
            }
            for (const auto& pending : m_pending)
            {
                if (now - pending.second.sent > std::chrono::seconds(30))
                {
                    Failure("Service response timeout. Reopen and inspect durable state before resubmitting.", true);
                    return;
                }
            }
            if (!m_activeJob.empty() && !m_jobPending && now - m_lastPoll >= std::chrono::milliseconds(100))
            {
                m_jobPending = true;
                m_lastPoll = now;
                Send("job.status", Json{{"job_id", m_activeJob}}, false, Json::object(), [this](const Json& result)
                {
                    m_jobPending = false;
                    const std::string state = result.at("state").get<std::string>();
                    if (state == "completed")
                    {
                        const Json finalResult = result.at("events").back().at("operation_result");
                        auto callback = std::move(m_jobComplete);
                        m_activeJob.clear();
                        callback(finalResult);
                    }
                    else if (state == "failed" || state == "interrupted" || state == "cancelled")
                    {
                        Failure("작업이 완료되지 않았습니다: " + state + " / " + result.at("events").back().dump());
                    }
                });
            }
            if (m_options.smoke && now - m_started > std::chrono::seconds(m_options.solverSmoke ? 600 : (m_options.cadSmoke ? 180 : 60)))
            {
                FinishSmoke(false, "GUI smoke timeout");
            }
        }
        catch (const std::exception& error)
        {
            Failure(std::string("Protocol/UI error: ") + error.what(), true);
        }
    }

    void FinishSmoke(bool passed, const std::string& error)
    {
        if (m_finishing)
        {
            return;
        }
        m_finishing = true;
        ExitCode = passed ? 0 : 2;
        Json report{{"schema_version", "rfad.gui-smoke/0.1"}, {"passed", passed}, {"stage", m_smokeStage},
            {"project_id", m_project}, {"revision_id", m_revision}, {"saved_revision", m_savedRevision},
            {"snapshot_id", m_snapshot}, {"service_sessions", m_serviceSessions},
            {"editor_stage", m_editorStage}, {"editor_checks", m_editorChecks},
            {"canvas_stage", m_canvasStage}, {"canvas_checks", m_canvasChecks},
            {"primitives_stage", m_primitivesStage}, {"primitives_checks", m_primitivesChecks},
            {"cad_stage", m_cadSmokeStage}, {"cad_checks", m_cadChecks}, {"cad_result", m_cadResult},
            {"solver_stage", m_solverSmokeStage}, {"solver_checks", m_solverChecks}, {"solver_result", m_solverResult},
            {"solver_sample_count", m_solverChart->SampleCount()}, {"solver_frames", m_solverChart->RenderedFrames()},
            {"mesh_triangles", m_modelView->TriangleCount()}, {"mesh_bodies", m_modelView->BodyCount()},
            {"rendered_frames", m_modelView->RenderedFrameCount()}, {"renderer", m_modelView->RendererDescription()},
            {"ux_checks", m_uxChecks}, {"editor_ui_state", m_editState}, {"apply_enabled", m_apply->IsEnabled()},
            {"error", error}, {"physics_tested", false}, {"frame_budget_tested", false}};
        if (!m_options.smokeReport.empty())
        {
            const std::filesystem::path path(m_options.smokeReport.ToStdWstring());
            std::error_code filesystemError;
            if (!path.parent_path().empty())
            {
                std::filesystem::create_directories(path.parent_path(), filesystemError);
            }
            std::ofstream output(path, std::ios::binary);
            output << report.dump(2) << '\n';
            if (!output)
            {
                ExitCode = 3;
            }
        }
        CallAfter([this]()
        {
            Close();
        });
    }

    void OnClose(wxCloseEvent& event)
    {
        if (m_closing)
        {
            return;
        }
        if (!m_waitingClose && !m_finishing && !m_options.smoke && !ConfirmDiscard())
        {
            if (event.CanVeto())
            {
                event.Veto();
            }
            return;
        }
        if (!m_waitingClose && m_connected && (m_solverActive || m_cadPreparing || !m_cadJob.empty()) && event.CanVeto())
        {
            m_waitingClose = true;
            m_closeDeadline = Clock::now() + std::chrono::seconds(30);
            CancelSolver();
            CancelCad();
            SetStatusText(Display("작업 취소와 실제 종료를 확인한 뒤 창을 닫습니다."), 0);
            Disable();
            event.Veto();
            return;
        }
        m_closing = true;
        m_timer.Stop();
        Disable();
        Hide();
        if (!m_restarting)
        {
            BeginShutdown();
        }
    }

    /** @brief 화면 수명을 유지한 채 서비스 종료와 pipe join을 UI 밖에서 수행한다. */
    void BeginShutdown()
    {
        try
        {
            m_shutdown = std::thread([this]()
            {
                m_client.Stop();
                wxQueueEvent(this, new wxThreadEvent(wxEVT_THREAD, IdShutdown));
            });
        }
        catch (const std::exception& error)
        {
            m_client.Stop();
            if (m_closing)
            {
                Destroy();
            }
            else
            {
                m_restarting = false;
                Failure(std::string("Cannot start shutdown thread: ") + error.what(), true);
            }
        }
    }

    /** @brief 종료 thread가 pipe를 모두 회수한 뒤 창을 파괴하거나 smoke 연결을 재개한다. */
    void OnShutdown(wxThreadEvent&)
    {
        m_shutdown.join();
        if (m_closing)
        {
            Destroy();
        }
        else
        {
            m_restarting = false;
            Connect();
        }
    }

    Options m_options;
    SolverChart* m_solverChart = nullptr;
    wxChoice* m_solverMetric = nullptr;
    wxStaticText* m_solverStatus = nullptr;
    wxStaticText* m_solverViewState = nullptr;
    wxTextCtrl* m_solverDetails = nullptr;
    bool m_solverConfigured = false;
    bool m_solverActive = false;
    bool m_solverCancelRequested = false;
    bool m_solverPolling = false;
    bool m_solverRestoring = false;
    std::string m_solverJob;
    std::string m_solverPhase;
    std::string m_solverState = "idle";
    std::string m_solverFirstResult;
    Clock::time_point m_solverLastPoll{};
    Json m_solverDraft = Json::object();
    Json m_solverSettings = Json::object();
    Json m_solverSnapshot = Json::object();
    Json m_solverPlan = Json::object();
    Json m_solverPrepared = Json::object();
    Json m_solverResult = Json::object();
    Json m_solverSamples = Json::object();
    Json m_solverChecks = Json::array();
    int m_solverSmokeStage = 0;
    wxAuiManager* m_manager = nullptr;
    wxString m_defaultLayout;
    std::map<int, wxButton*> m_tools;
    DesignCanvas* m_canvas = nullptr;
    wxNotebook* m_views = nullptr;
    ModelView* m_modelView = nullptr;
    wxStaticText* m_modelState = nullptr;
    wxStaticText* m_modelHint = nullptr;
    wxStaticText* m_cadStatus = nullptr;
    wxTextCtrl* m_cadDetails = nullptr;
    bool m_cadConfigured = false;
    bool m_cadPreparing = false;
    bool m_cadPolling = false;
    bool m_cadRestoring = false;
    bool m_cadCancelRequested = false;
    bool m_modelWasLoading = false;
    bool m_cadErrorProbeSeen = false;
    std::string m_cadJob;
    std::string m_cadState = "idle";
    Clock::time_point m_cadLastPoll{};
    Json m_cadSnapshot = Json::object();
    Json m_cadResult = Json::object();
    Json m_displayResult = Json::object();
    int m_cadSmokeStage = 0;
    std::string m_cadFirstSnapshot;
    Json m_cadChecks = Json::array();
    wxListBox* m_steps = nullptr;
    wxChoice* m_layerChoice = nullptr;
    wxSpinCtrlDouble* m_width = nullptr;
    wxStaticText* m_canvasHint = nullptr;
    wxStaticText* m_problemSummary = nullptr;
    wxNotebook* m_bottom = nullptr;
    wxListCtrl* m_problems = nullptr;
    std::vector<std::string> m_layerIds;
    std::string m_activeLayer;
    std::string m_drawTool = "select";
    std::string m_problemRevision;
    Json m_scene = Json::object();
    Json m_diagnostics = Json::array();
    std::size_t m_diagnosticCount = 0;
    bool m_diagnosticsTruncated = false;
    Json m_lineDraft = Json::object();
    Json m_arcDraft = Json::object();
    std::string m_polygonDraft;
    int m_primitivesStage = 0;
    std::string m_primitivesLayerA;
    std::string m_primitivesLayerB;
    std::string m_primitivesPolygon;
    std::string m_primitivesRectangle;
    std::string m_primitivesVia;
    std::string m_primitivesMissingVia;
    Json m_primitivesPads = Json::array();
    Json m_primitivesOriginalPolygon;
    Json m_primitivesMovedPolygon;
    Json m_primitivesSavedShapes;
    Json m_primitivesChecks = Json::array();
    int m_canvasStage = 0;
    int m_canvasUndoBefore = 0;
    bool m_canvasAwaitSelection = false;
    std::string m_canvasLine;
    std::string m_canvasArc;
    Json m_canvasOriginalLine;
    Json m_canvasMovedLine;
    Json m_canvasSavedShapes;
    Json m_canvasChecks = Json::array();
    ServiceClient m_client;
    std::thread m_shutdown;
    wxTimer m_timer;
    wxTreeCtrl* m_tree = nullptr;
    wxPanel* m_properties = nullptr;
    wxPanel* m_metadataPanel = nullptr;
    EditorPanel* m_editorPanel = nullptr;
    wxStaticText* m_selectionLabel = nullptr;
    wxTextCtrl* m_name = nullptr;
    wxTextCtrl* m_description = nullptr;
    wxTextCtrl* m_log = nullptr;
    wxButton* m_apply = nullptr;
    wxStaticText* m_revisionLabel = nullptr;
    bool m_connected = false;
    bool m_busy = true;
    bool m_jobPending = false;
    bool m_transportFailed = false;
    bool m_finishing = false;
    bool m_restarting = false;
    bool m_closing = false;
    bool m_waitingClose = false;
    Clock::time_point m_closeDeadline{};
    bool m_refreshing = false;
    bool m_updatingDraft = false;
    int m_smokeStage = 0;
    int m_editorStage = 0;
    int m_serviceSessions = 0;
    Clock::time_point m_started;
    Clock::time_point m_lastPoll{};
    std::map<std::string, Pending> m_pending;
    std::function<void(const Json&)> m_jobComplete;
    Json m_editor = Json::object();
    Json m_selection = Json::object();
    Json m_editorChecks = Json::array();
    Json m_uxChecks = Json::array();
    std::string m_editState = "empty";
    std::string m_baseParameter;
    std::string m_dependentParameter;
    std::string m_failureRevision;
    std::string m_epoch;
    std::string m_project;
    std::string m_revision;
    std::string m_path;
    std::string m_activeJob;
    std::string m_savedRevision;
    std::string m_snapshot;
    std::string m_smokePath;
};

/** @brief 명시한 실행 경로로 wxWidgets GUI를 초기화한다. */
class StudioApp final : public wxApp
{
public:
    bool OnInit() override
    {
        wxCmdLineParser parser(argc, argv);
        parser.AddOption("", "python", "Python executable path");
        parser.AddOption("", "source", "rfad source directory");
        parser.AddOption("", "workspace", "Project workspace directory");
        parser.AddOption("", "cad-python", "Isolated CAD Python executable path");
        parser.AddSwitch("", "openems-wsl", "Enable fixed WSL openEMS runtime");
        parser.AddSwitch("", "solver-smoke-test", "Run PCB solver GUI workflow and exit");
        parser.AddSwitch("", "solver-expect-failure", "Verify missing PCB physics inputs are rejected");
        parser.AddOption("", "solver-settings", "Explicit solver smoke settings JSON path");
        parser.AddOption("", "open-project", "Registered project path relative to workspace");
        parser.AddSwitch("", "smoke-test", "Run GUI/service smoke test and exit");
        parser.AddSwitch("", "editor-smoke-test", "Run editor/undo/restart smoke test and exit");
        parser.AddSwitch("", "canvas-smoke-test", "Run 2D mouse/command/history/restart smoke test and exit");
        parser.AddSwitch("", "primitives-smoke-test", "Run polygon/pad/via input/display/history/restart smoke test and exit");
        parser.AddSwitch("", "coordinate-table-smoke-test", "Run 64-point coordinate table edit/history/restart smoke test and exit");
        parser.AddSwitch("", "cad-smoke-test", "Run CAD export/view/cancel/restart smoke test and exit");
        parser.AddSwitch("", "cad-expect-failure", "Verify invalid CAD input without publishing output");
        parser.AddOption("", "smoke-report", "Smoke JSON output path");
        parser.AddSwitch("h", "help", "Show help", wxCMD_LINE_OPTION_HELP);
        if (parser.Parse() != 0)
        {
            return false;
        }
        Options options;
        parser.Found("python", &options.python);
        parser.Found("source", &options.source);
        parser.Found("workspace", &options.workspace);
        parser.Found("cad-python", &options.cadPython);
        parser.Found("open-project", &options.openProject);
        parser.Found("smoke-report", &options.smokeReport);
        options.editorSmoke = parser.Found("editor-smoke-test");
        options.canvasSmoke = parser.Found("canvas-smoke-test");
        options.coordinatesSmoke = parser.Found("coordinate-table-smoke-test");
        options.primitivesSmoke = parser.Found("primitives-smoke-test") || options.coordinatesSmoke;
        options.cadSmoke = parser.Found("cad-smoke-test");
        options.cadExpectFailure = parser.Found("cad-expect-failure");
        options.openEmsWsl = parser.Found("openems-wsl");
        options.solverSmoke = parser.Found("solver-smoke-test");
        options.solverExpectFailure = parser.Found("solver-expect-failure");
        parser.Found("solver-settings", &options.solverSettings);
        options.smoke = parser.Found("smoke-test") || options.editorSmoke || options.canvasSmoke || options.primitivesSmoke || options.cadSmoke || options.solverSmoke;
        if (options.python.empty() || options.source.empty() || options.workspace.empty())
        {
            wxMessageBox(Display("--python, --source, --workspace 경로를 지정하십시오."), Display("실행 설정"), wxOK | wxICON_ERROR);
            ExitCode = 2;
            return false;
        }
        if (!wxFileName(options.python).IsAbsolute() || !wxFileName(options.source).IsAbsolute() || !wxFileName(options.workspace).IsAbsolute() ||
            (!options.cadPython.empty() && !wxFileName(options.cadPython).IsAbsolute()))
        {
            wxMessageBox(Display("실행 경로는 절대 경로로 지정하십시오."), Display("실행 설정"), wxOK | wxICON_ERROR);
            ExitCode = 2;
            return false;
        }
        auto* frame = new StudioFrame(std::move(options));
        SetTopWindow(frame);
        frame->Show();
        return true;
    }

    int OnRun() override
    {
        wxApp::OnRun();
        return ExitCode;
    }
};

wxIMPLEMENT_APP(StudioApp);
