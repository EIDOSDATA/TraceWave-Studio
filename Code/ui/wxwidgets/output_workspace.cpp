/** @file @brief 페이지 이동만으로 출력이나 스냅샷을 만들지 않는 작업 공간이다. */
#include "output_workspace.h"
#include "drawing_output_view.h"
#include "handoff_output_view.h"
#include "step_output_view.h"
#include "pcb_cam_output_view.h"
#include "output_conditions_view.h"
#include "output_model.h"
#include "rf_validation_model.h"
#include "output_record_dialog.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/checkbox.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/wrapsizer.h>
#include <algorithm>

namespace
{
wxButton* Button(wxWindow* parent, wxSizer* sizer, const char* label)
{
    auto* button = new wxButton(parent, wxID_ANY, Display(label));
    StudioTheme::Button(*button);
    sizer->Add(button, 0, wxALL, parent->FromDIP(4));
    return button;
}

std::string SnapshotLabel(const Json& snapshot)
{
    const auto description = OutputUi::Text(snapshot.value("description", Json(nullptr)), "고정 입력");
    const auto time = RfValidationUi::Time(snapshot.value("sealed_at", Json(nullptr)));
    return description + " / " + time;
}
}

OutputWorkspace::OutputWorkspace(wxWindow* parent, wxWindow* conditions) : wxPanel(parent)
{
    StudioTheme::BindSurface(*this);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* source = new wxWrapSizer(wxHORIZONTAL);
    m_source = source;
    source->Add(new wxStaticText(this, wxID_ANY, Display("고정 입력 / 적용된 개정")), 0,
                wxALIGN_CENTER_VERTICAL | wxALL, FromDIP(4));
    m_snapshots = new wxChoice(this, wxID_ANY);
    m_snapshots->SetMinSize(FromDIP(wxSize(250, -1)));
    source->Add(m_snapshots, 0, wxALIGN_CENTER_VERTICAL | wxALL, FromDIP(4));
    m_snapshotPrevious = Button(this, source, "이전 입력");
    m_snapshotNext = Button(this, source, "다음 입력");
    m_capture = Button(this, source, "현재 개정 고정");
    m_capture->SetToolTip(
        Display("서비스에 적용된 현재 개정만 고정합니다. 미적용 폼 초안은 자동 적용하거나 폐기하지 않습니다."));
    m_refresh = Button(this, source, "새로고침");
    layout->Add(source, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    m_tabs = new StudioNotebook(this);
    m_drawing = new DrawingOutputView(m_tabs);
    m_step = new StepOutputView(m_tabs);
    m_tabs->AddPage(m_drawing, Display("기술 도면"));
    m_tabs->AddPage(m_step, Display("STEP"));
    m_pcb = new PcbCamOutputView(m_tabs);
    m_tabs->AddPage(m_pcb, Display("PCB / CAM"));
    m_handoff = new HandoffOutputView(m_tabs);
    m_tabs->AddPage(m_handoff, Display("보고서 / 인계"));
    m_handoff->onModeChanged = [this]()
    {
        m_source->ShowItems(Kind() != 3 || !m_handoff->ArchiveMode());
        Layout();
        if (!m_refreshing && onChanged)
        {
            onChanged();
        }
    };
    layout->Add(m_tabs, 1, wxEXPAND);
    auto* history = new wxWrapSizer(wxHORIZONTAL);
    m_history = history;
    history->Add(new wxStaticText(this, wxID_ANY, Display("출력 기록")), 0, wxALIGN_CENTER_VERTICAL | wxALL,
                 FromDIP(4));
    m_records = new wxChoice(this, wxID_ANY);
    m_records->SetMinSize(FromDIP(wxSize(250, -1)));
    history->Add(m_records, 0, wxALIGN_CENTER_VERTICAL | wxALL, FromDIP(4));
    m_catalogPrevious = Button(this, history, "이전 기록");
    m_catalogNext = Button(this, history, "다음 기록");
    m_allFormats = new wxCheckBox(this, wxID_ANY, Display("전체 형식"));
    history->Add(m_allFormats, 0, wxALIGN_CENTER_VERTICAL | wxALL, FromDIP(4));
    m_allFormats->Bind(wxEVT_CHECKBOX, [this](wxCommandEvent&)
    {
        if (onHistoryScope)
        {
            onHistoryScope();
        }
    });
    m_file = Button(this, history, "출력 파일 열기");
    m_file->SetName("output.file.open");
    m_file->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        if (onOpenFile)
        {
            onOpenFile();
        }
    });
    m_details = Button(this, history, "파일 목록 / 검수");
    m_verify = Button(this, history, "다시 검수");
    m_folder = Button(this, history, "출력 폴더");
    layout->Add(history, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    auto* state = new wxWrapSizer(wxHORIZONTAL);
    m_status = new wxStaticText(this, wxID_ANY, Display("프로젝트를 열면 출력할 고정 입력과 보존 기록을 읽습니다."));
    state->Add(m_status, 1, wxALIGN_CENTER_VERTICAL | wxALL, FromDIP(8));
    m_cancel = Button(this, state, "출력 작업 취소");
    m_recover = Button(this, state, "요청 결과 확인");
    layout->Add(state, 0, wxEXPAND);
    SetSizer(layout);
    m_conditions = new OutputConditionsView(conditions);
    conditions->GetSizer()->Add(m_conditions, 1, wxEXPAND);
    m_conditions->Hide();
    m_drawing->onChanged = [this]()
    {
        if (onChanged)
        {
            onChanged();
        }
    };
    m_pcb->onChanged = m_drawing->onChanged;
    m_drawing->onSaveAnnotations = [this](const Json& recipe)
    {
        if (onSaveDrawingAnnotations)
        {
            onSaveDrawingAnnotations(recipe);
        }
    };
    m_pcb->onManufacturing = [this]()
    {
        if (onManufacturing)
        {
            onManufacturing();
        }
    };
    m_pcb->onImport = [this]()
    {
        if (onImport)
        {
            onImport();
        }
    };
    m_tabs->onSelectionChanged = [this](int page)
    {
        m_history->ShowItems(page != 3);
        m_source->ShowItems(page != 3 || !m_handoff->ArchiveMode());
        Layout();
        if (!m_refreshing && onChanged)
        {
            onChanged();
        }
    };
    const auto preview = [this]()
    {
        if (onPreview)
        {
            onPreview();
        }
    };
    const auto build = [this]()
    {
        if (onBuild)
        {
            onBuild();
        }
    };
    m_drawing->onPreview = preview;
    m_step->onPreview = preview;
    m_pcb->onPreview = preview;
    m_drawing->onBuild = build;
    m_step->onBuild = build;
    m_pcb->onBuild = build;
    m_step->onVerify = [this]()
    {
        if (onVerify)
        {
            onVerify();
        }
    };
    m_step->onDetails = [this]()
    {
        ShowRecord(false);
    };
    m_snapshots->Bind(wxEVT_CHOICE,
                      [this](wxCommandEvent&)
                      {
                          const int index = m_snapshots->GetSelection();
                          if (!m_refreshing && index >= 0 && static_cast<std::size_t>(index) < m_snapshotValues.size())
                          {
                              m_selectedSnapshot = m_snapshotValues[index];
                              if (onSelectSnapshot)
                              {
                                  onSelectSnapshot(m_selectedSnapshot);
                              }
                          }
                      });
    m_records->Bind(wxEVT_CHOICE,
                    [this](wxCommandEvent&)
                    {
                        const int index = m_records->GetSelection();
                        if (!m_refreshing && index >= 0 && static_cast<std::size_t>(index) < m_jobIds.size())
                        {
                            m_selectedJob = m_jobIds[index];
                            if (onSelectJob)
                            {
                                onSelectJob(m_selectedJob);
                            }
                        }
                    });
    m_capture->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        if (onSnapshot)
                        {
                            onSnapshot();
                        }
                    });
    m_refresh->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        if (onRefresh)
                        {
                            onRefresh();
                        }
                    });
    m_snapshotPrevious->Bind(wxEVT_BUTTON,
                             [this](wxCommandEvent&)
                             {
                                 if (onSnapshotPage)
                                 {
                                     onSnapshotPage(std::max(0, m_context.value("snapshot_offset", 0) - 25));
                                 }
                             });
    m_snapshotNext->Bind(wxEVT_BUTTON,
                         [this](wxCommandEvent&)
                         {
                             if (onSnapshotPage &&
                                 m_context.value("snapshot_next_offset", Json(nullptr)).is_number_integer())
                             {
                                 onSnapshotPage(m_context.at("snapshot_next_offset"));
                             }
                         });
    m_catalogPrevious->Bind(wxEVT_BUTTON,
                            [this](wxCommandEvent&)
                            {
                                if (onCatalogPage)
                                {
                                    onCatalogPage(std::max(0, m_catalog.value("offset", 0) - 25));
                                }
                            });
    m_catalogNext->Bind(wxEVT_BUTTON,
                        [this](wxCommandEvent&)
                        {
                            if (onCatalogPage && m_catalog.value("next_offset", Json(nullptr)).is_number_integer())
                            {
                                onCatalogPage(m_catalog.at("next_offset"));
                            }
                        });
    m_details->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        ShowRecord(false);
                    });
    m_verify->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       if (onVerify)
                       {
                           onVerify();
                       }
                   });
    m_folder->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       if (onOpenFolder)
                       {
                           onOpenFolder();
                       }
                   });
    m_cancel->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       if (onCancel)
                       {
                           onCancel();
                       }
                   });
    m_recover->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        if (onRecover)
                        {
                            onRecover();
                        }
                    });
    SetAvailable(false, false, false, false, false);
}

wxWindow* OutputWorkspace::ConditionsView() const
{
    return m_conditions;
}
wxStaticText* OutputWorkspace::StatusLabel() const
{
    return m_status;
}
const Json& OutputWorkspace::Record() const
{
    return m_record;
}
const Json& OutputWorkspace::Preview() const
{
    return m_preview;
}
int OutputWorkspace::Kind() const
{
    return m_tabs->GetSelection();
}
void OutputWorkspace::SelectKind(int kind)
{
    m_tabs->SetSelection(kind);
}
std::string OutputWorkspace::SelectedJob() const
{
    return m_selectedJob;
}

void OutputWorkspace::SetContext(const Json& context, bool resetOptions)
{
    m_refreshing = true;
    m_context = context;
    m_snapshots->Clear();
    m_snapshotValues.clear();
    for (const auto& snapshot : context.at("snapshots"))
    {
        m_snapshotValues.push_back(snapshot);
        m_snapshots->Append(Display(SnapshotLabel(snapshot)));
    }
    if (m_snapshotValues.empty())
    {
        m_snapshots->Append(Display("보존된 고정 입력 없음"));
        m_snapshots->SetSelection(0);
    }
    if (m_selectedSnapshot.is_object())
    {
        SelectSnapshot(m_selectedSnapshot);
    }
    if (resetOptions)
    {
        m_drawing->SetContext(context);
        m_pcb->SetContext(context);
    }
    m_refreshing = false;
}

void OutputWorkspace::SetStoredDrawingAnnotation(const Json& settings)
{
    m_drawing->SetStoredAnnotation(settings);
}

void OutputWorkspace::SelectSnapshot(const Json& snapshot)
{
    if (m_snapshotValues.empty())
    {
        m_snapshots->Clear();
    }
    m_selectedSnapshot = snapshot;
    m_snapshots->SetSelection(wxNOT_FOUND);
    if (!snapshot.is_object())
    {
        return;
    }
    auto found = std::find_if(m_snapshotValues.begin(), m_snapshotValues.end(),
                              [&snapshot](const Json& value)
                              {
                                  return value.at("snapshot_id") == snapshot.at("snapshot_id") &&
                                         value.at("content_hash") == snapshot.at("content_hash");
                              });
    if (found == m_snapshotValues.end())
    {
        m_snapshotValues.push_back(snapshot);
        m_snapshots->Append(Display(SnapshotLabel(snapshot)));
        m_snapshots->SetSelection(static_cast<int>(m_snapshotValues.size() - 1));
    }
    else
    {
        m_snapshots->SetSelection(static_cast<int>(std::distance(m_snapshotValues.begin(), found)));
    }
    m_snapshots->SetToolTip(Display(SnapshotLabel(snapshot)));
}

Json OutputWorkspace::Snapshot() const
{
    if (!m_selectedSnapshot.is_object())
    {
        return nullptr;
    }
    return {{"snapshot_id", m_selectedSnapshot.at("snapshot_id")},
            {"content_hash", m_selectedSnapshot.at("content_hash")}};
}

HandoffOutputView* OutputWorkspace::Handoff() const
{
    return m_handoff;
}

void OutputWorkspace::SetHandoffAvailable(bool available)
{
    m_handoff->SetAvailable(available && Kind() == 3, Snapshot().is_object());
}

void OutputWorkspace::SetHandoffConditions(const Json& input, const Json& review)
{
    if (Kind() == 3)
    {
        m_conditions->SetHandoff(input, review, m_handoff->ArchiveMode());
    }
}

Json OutputWorkspace::Input() const
{
    if (Kind() == 3)
    {
        return nullptr;
    }
    if (Kind() == 2)
    {
        auto input = m_pcb->Input();
        input["snapshot"] = Snapshot();
        return input;
    }
    Json value{{"snapshot", Snapshot()},
               {"profile", Kind() == 1 ? "rfad.step.mechanical/0.1" : "rfad.exchange.drawing/0.1"},
               {"format", Kind() == 1 ? "step" : m_drawing->Format()}};
    if (Kind() == 0)
    {
        value["options"] = m_drawing->Options();
    }
    return value;
}

Json OutputWorkspace::PreviewInput() const
{
    auto input = Input();
    if (Kind() == 2)
    {
        const auto selection = m_pcb->DisplaySelection();
        for (const auto& [key, value] : selection.items())
        {
            input[key] = value;
        }
    }
    return input;
}

std::string OutputWorkspace::HistoryFormat() const
{
    if (m_allFormats->GetValue() || Kind() == 3)
    {
        return {};
    }
    return Input().value("format", "");
}

void OutputWorkspace::SetCatalog(const Json& catalog, const std::string& preferredJob)
{
    m_refreshing = true;
    m_catalog = catalog;
    m_records->Clear();
    m_jobIds.clear();
    if (!preferredJob.empty())
    {
        m_selectedJob = preferredJob;
    }
    for (const auto& item : catalog.at("items"))
    {
        m_jobIds.push_back(item.at("job_id"));
        const auto snapshot = item.value("snapshot", Json(nullptr));
        const auto revision = snapshot.is_object() ? snapshot.value("revision_id", "") : "";
        m_records->Append(Display(item.value("label", "출력") + " / " + OutputUi::State(item.value("state", "")) +
                                  (revision.empty() ? "" : " / 개정 " + revision.substr(0, 8)) +
                                  " / " + RfValidationUi::Time(item.value("created_at", Json(nullptr)))));
        if (m_jobIds.back() == m_selectedJob)
        {
            m_records->SetSelection(static_cast<int>(m_jobIds.size() - 1));
        }
    }
    if (m_jobIds.empty())
    {
        m_records->Append(Display("보존된 출력 기록 없음"));
        m_records->SetSelection(0);
    }
    m_records->SetToolTip(Display(
        "완료된 출력과 별도 검수 기록을 선택하세요. 목록 조회만으로 출력하거나 최신 기록을 선택하지 않습니다."));
    m_refreshing = false;
}

void OutputWorkspace::SetPreview(const Json& review)
{
    m_preview = review;
    if (Kind() == 0)
    {
        if (review.value("pages", Json::array()).empty())
        {
            m_drawing->ClearPreview(OutputUi::Issues(review.value("issues", Json::array())));
        }
        else
        {
            m_drawing->SetPreview(review);
        }
    }
    else if (Kind() == 1)
    {
        m_step->SetPreview(review);
    }
    else if (Kind() == 2)
    {
        m_pcb->SetPreview(review);
    }
    m_conditions->SetRecord(review, m_context.value("source_name", m_context.value("project_name", "고정 입력")));
}

void OutputWorkspace::SetRecord(const Json& record, const wxString& workspace)
{
    m_record = record;
    m_selectedJob = record.value("job_id", "");
    const auto result = record.value("result", Json(nullptr));
    if (result.is_object())
    {
        const auto combined = OutputUi::RecordForDisplay(record);
        m_conditions->SetRecord(combined, "선택한 보존 출력 / 현재 편집과 별개");
        if (result.value("profile", "") == "rfad.step.mechanical/0.1")
        {
            m_refreshing = true;
            m_tabs->SetSelection(1);
            m_refreshing = false;
            m_step->SetResult(result, workspace);
        }
        else if (result.value("profile", "") == "rfad.exchange.drawing/0.1")
        {
            m_refreshing = true;
            m_tabs->SetSelection(0);
            m_refreshing = false;
        }
        else if (result.value("profile", "").rfind("rfad.exchange.", 0) == 0)
        {
            m_refreshing = true;
            m_tabs->SetSelection(2);
            m_pcb->SetRecord(combined);
            m_refreshing = false;
        }
    }
    const auto found = std::find(m_jobIds.begin(), m_jobIds.end(), m_selectedJob);
    m_records->SetSelection(found == m_jobIds.end() ? wxNOT_FOUND
                                                    : static_cast<int>(std::distance(m_jobIds.begin(), found)));
}

void OutputWorkspace::SetStatus(const std::string& message)
{
    m_status->SetLabel(Display(message));
    m_status->SetToolTip(Display(message));
    m_status->Wrap(std::max(FromDIP(300), GetClientSize().x - FromDIP(310)));
    Layout();
}

void OutputWorkspace::ClearPreview(const std::string& message)
{
    m_preview = nullptr;
    m_drawing->ClearPreview(message);
    m_step->Clear(message);
    m_pcb->Clear(message);
    m_conditions->Clear(message);
    SetStatus(message);
}

void OutputWorkspace::ClearRecord(const std::string& message)
{
    m_record = nullptr;
    ClearPreview(message);
}

void OutputWorkspace::Clear(const std::string& message)
{
    m_context = nullptr;
    m_catalog = nullptr;
    m_allFormats->SetValue(false);
    m_record = nullptr;
    m_selectedSnapshot = nullptr;
    m_selectedJob.clear();
    m_snapshots->Clear();
    m_records->Clear();
    m_snapshotValues.clear();
    m_jobIds.clear();
    m_step->Clear(message);
    ClearPreview(message);
}

void OutputWorkspace::ShowRecord(bool review)
{
    Json value = review ? m_preview : m_record;
    if (!value.is_object())
    {
        return;
    }
    if (!review && value.value("result", Json(nullptr)).is_object())
    {
        value = OutputUi::RecordForDisplay(value);
    }
    OutputRecordDialog dialog(this, value, review);
    dialog.ShowModal();
}

void OutputWorkspace::SetImportAvailable(bool available)
{
    m_pcb->SetImportAvailable(available);
}

bool OutputWorkspace::LockCancelButton()
{
    m_cancel->Disable();
    return !m_cancel->IsEnabled();
}

void OutputWorkspace::SetAvailable(bool available, bool busy, bool reviewed, bool canCancel, bool uncertain)
{
    const bool ready = available && !busy && !uncertain;
    const bool context = m_context.is_object();
    const bool snapshot = m_selectedSnapshot.is_object();
    const bool canVerify = m_record.is_object() && m_record.value("can_verify", false);
    m_tabs->Enable(ready);
    m_history->ShowItems(Kind() != 3);
    m_capture->Enable(ready);
    m_refresh->Enable(available && !busy);
    m_snapshots->Enable(ready && context && !m_snapshotValues.empty());
    m_records->Enable(ready && !m_jobIds.empty());
    m_snapshotPrevious->Enable(ready && context && m_context.value("snapshot_offset", 0) > 0);
    m_snapshotNext->Enable(ready && context && !m_context.value("snapshot_next_offset", Json(nullptr)).is_null());
    m_catalogPrevious->Enable(ready && m_catalog.is_object() && m_catalog.value("offset", 0) > 0);
    m_catalogNext->Enable(ready && m_catalog.is_object() && !m_catalog.value("next_offset", Json(nullptr)).is_null());
    m_details->Enable(!busy && m_record.is_object());
    m_verify->Enable(ready && canVerify);
    m_folder->Enable(ready && !OutputUi::ManifestPath(m_record).empty());
    m_allFormats->Enable(ready);
    m_file->Enable(ready && !OutputUi::PrimaryPath(m_record).empty());
    m_cancel->Enable(available && canCancel);
    m_recover->Enable(available && !busy && uncertain);
    m_cancel->Show(canCancel);
    m_recover->Show(uncertain);
    m_drawing->SetAvailable(ready && context, false, reviewed && Kind() == 0, snapshot);
    m_step->SetAvailable(ready && context && snapshot, false,
                         reviewed && Kind() == 1 && m_context.value("cad_runtime_configured", false), canVerify);
    m_pcb->SetAvailable(ready && context, reviewed && Kind() == 2, snapshot);
    const auto result = m_record.is_object() ? m_record.value("result", Json(nullptr)) : Json(nullptr);
    m_pcb->SetManufacturingAvailable(ready && result.is_object() && m_record.value("state", "") == "completed" &&
        m_record.value("format", "") == "kicad_pcb" && result.value("profile", "") == "rfad.exchange.kicad-board/0.1" && !OutputUi::ManifestPath(m_record).empty());
}
