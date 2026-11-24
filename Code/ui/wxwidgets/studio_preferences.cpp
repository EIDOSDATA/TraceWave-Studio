/** @file @brief 실행 환경, 화면 설정과 명령 검색을 현재 Studio 상태에 연결한다. */
#include "studio_internal.h"
#include "studio_shell.h"
#include "studio_theme.h"
#include "system_appearance.h"
#include "workspace_bar.h"
#include <wx/clipbrd.h>
#include <wx/display.h>
#include <wx/srchctrl.h>

namespace
{
/** @brief 현재 모니터에서 사용할 수 있는 영역 안에 대화상자를 배치한다. */
void Place(wxDialog& dialog, const wxWindow& owner, const wxSize& preferred, const wxSize& minimum)
{
    wxDisplay display(&owner);
    const auto available = display.GetClientArea().Deflate(dialog.FromDIP(12));
    auto maximum = [&](const wxSize& size)
    {
        const auto pixels = dialog.FromDIP(size);
        return wxSize(std::min(pixels.x, available.width), std::min(pixels.y, available.height));
    };
    dialog.SetMinSize(maximum(minimum));
    dialog.SetSize(maximum(preferred));
    const auto size = dialog.GetSize();
    dialog.SetPosition(wxPoint(available.x + (available.width - size.x) / 2,
                               available.y + (available.height - size.y) / 2));
}

/** @brief 표준 설정 대화상자의 제목과 설명 계층을 통일한다. */
wxBoxSizer* BuildDialog(wxDialog& dialog, const char* heading, const char* description)
{
    StudioTheme::ApplyTypography(dialog);
    StudioTheme::BindSurface(dialog);
    auto* root = new wxBoxSizer(wxVERTICAL);
    const int pad = dialog.FromDIP(StudioTheme::PanelPadding);
    auto* title = new wxStaticText(&dialog, wxID_ANY, Display(heading));
    StudioTheme::Title(*title);
    root->Add(title, 0, wxEXPAND | wxTOP | wxLEFT | wxRIGHT, pad);
    auto* note = new wxStaticText(&dialog, wxID_ANY, Display(description));
    StudioTheme::BindSecondary(*note);
    note->Wrap(dialog.FromDIP(520));
    root->Add(note, 0, wxEXPAND | wxALL, pad);
    dialog.SetSizer(root);
    return root;
}

/** @brief 페이지 바탕과 폼 여백을 설정하고 해당 탭에 등록한다. */
wxPanel* AddPage(StudioNotebook& pages, const char* label)
{
    auto* page = new wxPanel(&pages);
    StudioTheme::BindSurface(*page);
    page->SetSizer(new wxBoxSizer(wxVERTICAL));
    pages.AddPage(page, Display(label));
    return page;
}

/** @brief 상태 설명을 편집 가능한 입력으로 오인하지 않도록 별도 레이블로 표시한다. */
void AddLine(wxPanel& page, const char* label, const wxString& value)
{
    auto* title = new wxStaticText(&page, wxID_ANY, Display(label));
    StudioTheme::Heading(*title);
    const int pad = page.FromDIP(StudioTheme::PanelPadding);
    page.GetSizer()->Add(title, 0, wxEXPAND | wxTOP | wxLEFT | wxRIGHT, pad);
    auto* body = new wxStaticText(&page, wxID_ANY, value);
    StudioTheme::BindSecondary(*body);
    body->Wrap(page.FromDIP(495));
    page.GetSizer()->Add(body, 0, wxEXPAND | wxLEFT | wxRIGHT | wxTOP, pad);
}

/** @brief 현재 화면의 문자열을 원문 그대로 Windows 클립보드에 복사한다. */
bool CopyEnvironmentText(const wxString& text)
{
    if (!wxTheClipboard->Open())
    {
        return false;
    }
    const bool copied = wxTheClipboard->SetData(new wxTextDataObject(text));
    wxTheClipboard->Close();
    return copied;
}

/** @brief 경로를 읽기 전용으로 표시하고 전체 경로를 한 번에 복사한다. */
void AddPath(wxPanel& page, const char* label, const wxString& value, wxStaticText& status)
{
    const int pad = page.FromDIP(StudioTheme::PanelPadding);
    auto* title = new wxStaticText(&page, wxID_ANY, Display(label));
    StudioTheme::Heading(*title);
    page.GetSizer()->Add(title, 0, wxEXPAND | wxTOP | wxLEFT | wxRIGHT, pad);
    auto* edit = new wxTextCtrl(&page, wxID_ANY, value.empty() ? Display("미연결") : value,
                                wxDefaultPosition, wxDefaultSize, wxTE_READONLY);
    edit->SetName(Display(label));
    edit->SetToolTip(value);
    edit->SetInsertionPointEnd();
    auto* row = new wxBoxSizer(wxHORIZONTAL);
    row->Add(edit, 1, wxALIGN_CENTER_VERTICAL);
    auto* copy = new wxButton(&page, wxID_ANY, Display("경로 복사"));
    copy->SetName(Display(std::string(label) + " 전체 경로 복사"));
    copy->Enable(!value.empty());
    copy->Bind(wxEVT_BUTTON, [value, &status](wxCommandEvent&)
    {
        status.SetLabel(Display(CopyEnvironmentText(value) ? "전체 경로를 복사했습니다." : "클립보드를 열 수 없습니다. 다시 시도하세요."));
    });
    row->Add(copy, 0, wxLEFT | wxALIGN_CENTER_VERTICAL, page.FromDIP(StudioTheme::InputGap));
    page.GetSizer()->Add(row, 0, wxEXPAND | wxLEFT | wxRIGHT | wxTOP, pad);
}

/** @brief 닫기와 명시적 작업 버튼을 정렬하는 하단 행이다. */
wxBoxSizer* Footer(wxDialog& dialog)
{
    auto* row = new wxBoxSizer(wxHORIZONTAL);
    auto* close = new wxButton(&dialog, wxID_CANCEL, Display("닫기"));
    StudioTheme::Button(*close);
    row->AddStretchSpacer();
    row->Add(close, 0, wxALIGN_CENTER_VERTICAL);
    dialog.GetSizer()->Add(row, 0, wxEXPAND | wxALL, dialog.FromDIP(StudioTheme::PanelPadding));
    return row;
}
}

void StudioFrame::ShowDisplayPreferences()
{
    wxDialog dialog(this, wxID_ANY, Display("화면과 키보드 환경설정"), wxDefaultPosition,
                    wxDefaultSize, wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    dialog.SetName("studio.preferences");
    auto* root = BuildDialog(dialog, "환경설정", "Studio의 패널 표시, 단축키와 Windows 표시 상태를 확인합니다.");
    auto* pages = new StudioNotebook(&dialog);
    root->Add(pages, 1, wxEXPAND | wxLEFT | wxRIGHT, dialog.FromDIP(StudioTheme::PanelPadding));

    auto& layout = *AddPage(*pages, "화면 배치");
    AddLine(layout, "패널 표시", Display("이 창과 보기 메뉴에서 선택한 패널 표시를 사용자 설정에 저장합니다."));
    const std::array<const char*, 4> panelLabels = {
        m_shell->IsCompact() ? "프로젝트 탐색과 선택 속성" : "프로젝트 탐색", "선택 속성",
        "레이어 표시", "문제, 작업 및 로그"
    };
    const auto visibility = m_shell->PanelVisibility();
    std::array<wxCheckBox*, 4> panels{};
    for (std::size_t index = 0; index < visibility.size(); ++index)
    {
        if (m_shell->IsCompact() && index == 1)
        {
            continue;
        }
        auto* check = new wxCheckBox(&layout, wxID_ANY, Display(panelLabels[index]));
        check->SetValue(visibility[index]);
        panels[index] = check;
        layout.GetSizer()->Add(check, 0, wxEXPAND | wxTOP | wxLEFT | wxRIGHT, dialog.FromDIP(StudioTheme::PanelPadding));
    }
    auto* reset = new wxButton(&layout, wxID_ANY, Display("기본 패널 배치 복원"));
    StudioTheme::Button(*reset);
    layout.GetSizer()->Add(reset, 0, wxALL, dialog.FromDIP(StudioTheme::PanelPadding));
    reset->Bind(wxEVT_BUTTON, [&](wxCommandEvent&)
    {
        if (wxMessageBox(Display("숨긴 패널을 다시 표시하고 기본 위치로 돌립니다."), Display("기본 패널 배치 복원"),
                         wxYES_NO | wxNO_DEFAULT | wxICON_QUESTION, &dialog) == wxYES)
        {
            m_shell->RestoreLayout();
            dialog.EndModal(wxID_OK);
        }
    });

    auto& keyboard = *AddPage(*pages, "키보드");
    auto* table = new wxListCtrl(&keyboard, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_SINGLE_SEL);
    table->SetName("preferences.shortcuts");
    StudioTheme::Table(*table);
    table->InsertColumn(0, Display("작업"), wxLIST_FORMAT_LEFT, dialog.FromDIP(205));
    table->InsertColumn(1, Display("단축키"), wxLIST_FORMAT_LEFT, dialog.FromDIP(125));
    table->InsertColumn(2, Display("사용 위치"), wxLIST_FORMAT_LEFT, dialog.FromDIP(205));
    const char* shortcuts[][3] = {
        {"명령 찾기", "Ctrl+Shift+P", "작업 창"}, {"프로젝트 객체 찾기", "Ctrl+F", "열린 프로젝트"},
        {"다음 또는 이전 패널", "F6, Shift+F6", "작업 창"}, {"객체 이름 바꾸기", "F2", "탐색과 선택 객체"},
        {"정밀 편집", "D", "2D 작업 화면"}, {"현재 도구 취소", "Esc", "2D 작업 화면"},
        {"프로젝트 저장", "Ctrl+S", "열린 프로젝트"}
    };
    for (const auto& shortcut : shortcuts)
    {
        const long row = table->InsertItem(table->GetItemCount(), Display(shortcut[0]));
        table->SetItem(row, 1, Display(shortcut[1]));
        table->SetItem(row, 2, Display(shortcut[2]));
    }
    keyboard.GetSizer()->Add(table, 1, wxEXPAND | wxALL, dialog.FromDIP(StudioTheme::PanelPadding));

    auto& colours = *AddPage(*pages, "색상과 접근성");
    AddLine(colours, "현재 색상", Display(StudioAppearance::HighContrast() ? "Windows 고대비" : "Studio 라이트"));
    AddLine(colours, "Windows 배율",
            wxString::Format(Display("%d%%. 배율과 고대비는 Windows 설정에서 변경합니다."),
                             wxRound(GetDPIScaleFactor() * 100)));
    AddLine(colours, "상태 표시", Display("작업과 판정은 색상과 함께 상태 이름으로 표시됩니다."));
    auto* footer = Footer(dialog);
    auto* apply = new wxButton(&dialog, wxID_ANY, Display("패널 표시 적용"));
    StudioTheme::Button(*apply, true);
    footer->Add(apply, 0, wxALIGN_CENTER_VERTICAL | wxLEFT, dialog.FromDIP(StudioTheme::PanelPadding));
    apply->Bind(wxEVT_BUTTON, [&](wxCommandEvent&)
    {
        auto settings = visibility;
        for (std::size_t index = 0; index < panels.size(); ++index)
        {
            if (panels[index])
            {
                settings[index] = panels[index]->GetValue();
            }
        }
        m_shell->SetPanelVisibility(settings);
        dialog.EndModal(wxID_OK);
    });
    pages->onSelectionChanged = [&](int index)
    {
        apply->Show(index == 0);
        dialog.Layout();
    };
    Place(dialog, *this, wxSize(710, 490), wxSize(600, 420));
    dialog.ShowModal();
}

void StudioFrame::ShowEnvironment()
{
    wxDialog dialog(this, wxID_ANY, Display("실행 환경 및 진단"), wxDefaultPosition, wxDefaultSize,
                    wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    dialog.SetName("studio.environment");
    auto* root = BuildDialog(dialog, "실행 환경 및 진단", "현재 세션의 편집 서비스와 선택한 실행 환경을 확인합니다.");
    auto* pages = new StudioNotebook(&dialog);
    root->Add(pages, 1, wxEXPAND | wxLEFT | wxRIGHT, dialog.FromDIP(StudioTheme::PanelPadding));
    auto& components = *AddPage(*pages, "구성 요소");
    AddLine(components, "프로젝트 서비스", Display(m_connected ? "연결됨" : "연결 확인 필요"));
    AddLine(components, "CAD 및 STEP", Display(m_cadConfigured ? "실행 환경 연결됨" : "내보내려면 CAD 실행 환경 연결 필요"));
    AddLine(components, "openEMS 해석", Display(m_solverConfigured
        ? (m_options.openEmsWsl ? "WSL2 openEMS 연결됨" : "Windows 기본 openEMS 연결됨")
        : "새 해석을 실행하려면 openEMS 연결이 필요합니다."));
    AddLine(components, "다음 조치", Display(!m_connected
        ? "Studio를 다시 시작하고 프로젝트 서비스 연결을 확인하세요. 계속 연결되지 않으면 진단 기록을 복사하세요."
        : !m_solverConfigured || !m_cadConfigured
            ? "필요한 기능의 연결이 끊겨 있습니다. 설치본은 Windows 설치 프로그램으로 필요한 환경을 복구한 뒤 Studio를 다시 여세요."
            : "현재 연결 상태로 프로젝트를 편집하고 해석할 수 있습니다. 문제를 재현한 뒤 진단 기록에서 시간과 내용을 확인하세요."));

    auto& paths = *AddPage(*pages, "경로와 연결");
    const int pad = dialog.FromDIP(StudioTheme::PanelPadding);
    auto* pathStatus = new wxStaticText(&paths, wxID_ANY, Display("필요한 전체 경로를 복사할 수 있습니다."));
    StudioTheme::BindSecondary(*pathStatus);
    AddPath(paths, "프로젝트 작업 영역", m_options.workspace, *pathStatus);
    AddPath(paths, "서비스 Python", m_options.python, *pathStatus);
    AddPath(paths, "CAD Python", m_options.cadPython, *pathStatus);
    AddPath(paths, "도면 교환용 Python", m_options.exchangePython, *pathStatus);
    paths.GetSizer()->Add(pathStatus, 0, wxEXPAND | wxALL, pad);

    auto& diagnostics = *AddPage(*pages, "진단 기록");
    auto* mode = new wxChoice(&diagnostics, wxID_ANY);
    mode->SetName(Display("진단 기록 표시 방식"));
    mode->Append(Display("요약"));
    mode->Append(Display("전체 기술 기록"));
    mode->SetSelection(0);
    auto* toolbar = new wxBoxSizer(wxHORIZONTAL);
    toolbar->Add(mode, 0, wxALIGN_CENTER_VERTICAL | wxRIGHT, pad);
    auto* refresh = new wxButton(&diagnostics, wxID_ANY, Display("새로 읽기"));
    toolbar->Add(refresh, 0, wxALIGN_CENTER_VERTICAL | wxRIGHT, pad);
    auto* copy = new wxButton(&diagnostics, wxID_ANY, Display("표시 기록 복사"));
    toolbar->Add(copy, 0, wxALIGN_CENTER_VERTICAL);
    diagnostics.GetSizer()->Add(toolbar, 0, wxALL, pad);
    auto* log = new wxTextCtrl(&diagnostics, wxID_ANY, wxEmptyString, wxDefaultPosition, wxDefaultSize,
                               wxTE_MULTILINE | wxTE_READONLY);
    log->SetName(Display("현재 세션 진단 기록"));
    diagnostics.GetSizer()->Add(log, 1, wxEXPAND | wxLEFT | wxRIGHT, pad);
    auto* logStatus = new wxStaticText(&diagnostics, wxID_ANY, wxEmptyString);
    StudioTheme::BindSecondary(*logStatus);
    diagnostics.GetSizer()->Add(logStatus, 0, wxEXPAND | wxALL, pad);
    const auto updateLog = [this, mode, log, logStatus, copy]()
    {
        const bool technical = mode->GetSelection() == 1;
        const auto text = technical ? m_log->GetValue() : m_logSummary->GetValue();
        log->ChangeValue(text);
        log->ShowPosition(log->GetLastPosition());
        copy->Enable(!text.empty());
        logStatus->SetLabel(Display(text.empty() ? "현재 세션에 기록이 없습니다."
            : technical ? "전체 경로와 기술 세부 사항이 표시됩니다."
                        : "최신 기록을 아래에 표시합니다. 자세한 원인은 전체 기술 기록에서 확인하세요."));
    };
    mode->Bind(wxEVT_CHOICE, [updateLog](wxCommandEvent&) { updateLog(); });
    refresh->Bind(wxEVT_BUTTON, [updateLog](wxCommandEvent&) { updateLog(); });
    copy->Bind(wxEVT_BUTTON, [log, logStatus](wxCommandEvent&)
    {
        logStatus->SetLabel(Display(CopyEnvironmentText(log->GetValue()) ? "표시한 기록을 복사했습니다."
            : "클립보드를 열 수 없습니다. 다시 시도하세요."));
    });
    updateLog();

    Footer(dialog);
    Place(dialog, *this, wxSize(780, 610), wxSize(600, 510));
    dialog.ShowModal();
}

void StudioFrame::ShowCommandSearch()
{
    struct Command
    {
        int id;
        wxString label;
        wxString group;
        wxString key;
        wxMenuItem* item = nullptr;
        wxButton* tool = nullptr;
        bool IsEnabled() const
        {
            // @brief 명령 창이 주 창을 잠그는 동안에도 도구 자체의 사용 가능 상태를 읽는다.
            return item ? item->IsEnabled() : tool->IsThisEnabled();
        }
    };

    std::vector<Command> commands;
    wxMenuBar* bar = GetMenuBar();
    for (std::size_t group = 0; group < bar->GetMenuCount(); ++group)
    {
        for (auto* item : bar->GetMenu(group)->GetMenuItems())
        {
            if (!item->IsSeparator() && item->GetId() != IdFindCommand)
            {
                commands.push_back({item->GetId(), item->GetItemLabelText(), bar->GetMenuLabelText(group),
                                    item->GetItemLabel().AfterFirst('\t'), item});
            }
        }
    }
    for (const auto& [id, label] : std::array<std::pair<int, const char*>, 4>{
             {{IdRoute, "대화식 배선"}, {IdLine, "선 그리기"}, {IdArc, "원호 그리기"}, {IdPrecision, "정밀 편집"}}})
    {
        commands.push_back({id, Display(label), Display("설계"), id == IdPrecision ? wxString("D") : wxString(),
                            nullptr, m_tools.at(id)});
    }

    wxDialog dialog(this, wxID_ANY, Display("명령 찾기"), wxDefaultPosition, wxDefaultSize,
                    wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    dialog.SetName("studio.commands");
    auto* root = BuildDialog(dialog, "명령 찾기", "명령 이름, 메뉴 또는 단축키를 검색하세요.");
    const int pad = dialog.FromDIP(StudioTheme::PanelPadding);
    auto* search = new wxSearchCtrl(&dialog, wxID_ANY);
    search->SetDescriptiveText(Display("예: 원호, 저장, Ctrl+F"));
    search->SetName("commands.search");
    search->SetMinSize(dialog.FromDIP(wxSize(-1, 34)));
    root->Add(search, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, pad);
    auto* list = new wxListCtrl(&dialog, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_SINGLE_SEL);
    list->SetName("commands.results");
    StudioTheme::Table(*list);
    list->InsertColumn(0, Display("명령"), wxLIST_FORMAT_LEFT, dialog.FromDIP(274));
    list->InsertColumn(1, Display("메뉴"), wxLIST_FORMAT_LEFT, dialog.FromDIP(80));
    list->InsertColumn(2, Display("단축키"), wxLIST_FORMAT_LEFT, dialog.FromDIP(126));
    list->InsertColumn(3, Display("상태"), wxLIST_FORMAT_LEFT, dialog.FromDIP(110));
    root->Add(list, 1, wxEXPAND | wxLEFT | wxRIGHT, pad);
    auto* status = new wxStaticText(&dialog, wxID_ANY, wxEmptyString);
    StudioTheme::BindSecondary(*status);
    root->Add(status, 0, wxEXPAND | wxLEFT | wxRIGHT | wxTOP, pad);
    auto* footer = Footer(dialog);
    auto* run = new wxButton(&dialog, wxID_ANY, Display("선택 명령 실행"));
    StudioTheme::Button(*run, true);
    footer->Add(run, 0, wxALIGN_CENTER_VERTICAL | wxLEFT, pad);

    const Command* selected = nullptr;
    const auto selectedCommand = [&]() -> const Command*
    {
        const auto row = list->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
        return row < 0 ? nullptr : &commands[list->GetItemData(row)];
    };
    const auto refreshState = [&]()
    {
        const auto* command = selectedCommand();
        run->Enable(command && command->IsEnabled());
        status->SetLabel(list->GetItemCount() == 0 ? Display("일치하는 명령 없음")
            : command && !command->IsEnabled() ? Display("현재 프로젝트, 선택 또는 작업 상태에서 실행할 수 없습니다.")
            : Display("Tab으로 목록 이동, 방향키로 선택, Enter로 실행, Esc로 닫기"));
    };
    const auto populate = [&]()
    {
        wxString query = search->GetValue();
        query.Trim().Trim(false);
        query.MakeLower();
        search->ShowCancelButton(!search->GetValue().empty());
        list->Freeze();
        list->DeleteAllItems();
        for (std::size_t index = 0; index < commands.size(); ++index)
        {
            const auto& command = commands[index];
            if (query.empty() || (command.label + " " + command.group + " " + command.key).Lower().Contains(query))
            {
                const long row = list->InsertItem(list->GetItemCount(), command.label);
                list->SetItem(row, 1, command.group);
                list->SetItem(row, 2, command.key);
                list->SetItem(row, 3, Display(command.IsEnabled() ? "실행 가능" : "실행 불가"));
                list->SetItemData(row, index);
            }
        }
        if (list->GetItemCount() > 0)
        {
            list->SetItemState(0, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED,
                              wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
        }
        list->Thaw();
        refreshState();
    };
    const auto execute = [&]()
    {
        const auto* command = selectedCommand();
        if (command && command->IsEnabled())
        {
            selected = command;
            dialog.EndModal(wxID_OK);
        }
    };
    list->Bind(wxEVT_LIST_ITEM_SELECTED, [&](wxListEvent&) { refreshState(); });
    list->Bind(wxEVT_LIST_ITEM_DESELECTED, [&](wxListEvent&) { refreshState(); });
    list->Bind(wxEVT_LIST_ITEM_ACTIVATED, [&](wxListEvent&) { execute(); });
    search->Bind(wxEVT_TEXT, [&](wxCommandEvent&) { populate(); });
    search->Bind(wxEVT_SEARCH_CANCEL, [search](wxCommandEvent&) { search->Clear(); });
    run->Bind(wxEVT_BUTTON, [&](wxCommandEvent&) { execute(); });
    populate();
    Place(dialog, *this, wxSize(720, 550), wxSize(640, 420));
    search->SetFocus();
    if (dialog.ShowModal() == wxID_OK && selected && selected->IsEnabled())
    {
        if (selected->tool)
        {
            NavigateWorkspace(WorkspaceArea::Design);
            wxCommandEvent event(wxEVT_BUTTON, selected->id);
            event.SetEventObject(selected->tool);
            selected->tool->ProcessWindowEvent(event);
        }
        else
        {
            wxCommandEvent event(wxEVT_MENU, selected->id);
            if (selected->item->IsCheckable())
            {
                const bool checked = !selected->item->IsChecked();
                selected->item->Check(checked);
                event.SetInt(checked ? 1 : 0);
            }
            ProcessWindowEvent(event);
        }
    }
}
