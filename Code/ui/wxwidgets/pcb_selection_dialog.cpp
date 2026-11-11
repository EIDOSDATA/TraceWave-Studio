/** @file @brief 선택 대화상자의 요청 수명과 미리보기/적용 상태를 연결한다. */
#include "pcb_selection_dialog.h"
#include "pcb_selection_view_support.h"
#include <wx/button.h>
#include <wx/combobox.h>
#include <wx/display.h>
#include <wx/grid.h>
#include <wx/listctrl.h>
#include <wx/notebook.h>
#include <wx/stattext.h>
#include <wx/weakref.h>
#include <stdexcept>
#include <algorithm>

PcbSelectionDialog::PcbSelectionDialog(wxWindow* parent, const Json& context, DialogGateway gateway)
    : wxDialog(parent, wxID_ANY, Display("PCB 재료와 적층 선택"), wxDefaultPosition, parent->FromDIP(wxSize(1140, 800)),
               wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER),
      m_model(context, Uuid()), m_gateway(std::move(gateway)), m_context(context)
{
    SetName("pcb.dialog");
    const int displayIndex = wxDisplay::GetFromWindow(parent);
    const wxRect work =
        wxDisplay(displayIndex == wxNOT_FOUND ? 0U : static_cast<unsigned int>(displayIndex)).GetClientArea();
    const wxSize available(std::max(320, work.width - FromDIP(32)), std::max(300, work.height - FromDIP(48)));
    SetSize(wxSize(std::min(GetSize().x, available.x), std::min(GetSize().y, available.y)));
    SetMinSize(wxSize(std::min(FromDIP(900), available.x), std::min(FromDIP(620), available.y)));
    CentreOnParent();
    BuildInterface();
    PopulateLayers(m_model.LayerRows(), true);
    Bind(wxEVT_CLOSE_WINDOW,
         [this](wxCloseEvent& event)
         {
             if (m_applying)
             {
                 SetStatus("적용 응답을 기다리는 중입니다. 완료 또는 연결 상태 확인 후 닫을 수 있습니다.");
                 event.Veto();
                 return;
             }
             CloseDialog();
         });
    Bind(
        wxEVT_BUTTON,
        [this](wxCommandEvent&)
        {
            CloseDialog();
        },
        wxID_CANCEL);
    wxWeakRef<PcbSelectionDialog> weak(this);
    CallAfter(
        [weak]()
        {
            if (weak && !weak->m_closed)
            {
                weak->Search();
            }
        });
}

const Json& PcbSelectionDialog::GetAppliedResult() const
{
    return m_applied;
}

/** @brief 종료된 뷰의 callback은 모든 경로에서 폐기한다. */
void PcbSelectionDialog::CloseDialog()
{
    if (m_applying || m_closed)
    {
        return;
    }
    m_closed = true;
    ++m_detailRevision;
    EndModal(wxID_CANCEL);
}

void PcbSelectionDialog::ServiceDisconnected(const std::string& message)
{
    if (m_closed)
    {
        return;
    }
    const bool uncertain = m_applying;
    m_applying = false;
    m_disconnected = true;
    m_model.MarkStale();
    SetStatus((uncertain ? "적용 결과를 확인하지 못했습니다. 이 화면에서 다시 적용하지 마세요. 닫은 뒤 프로젝트를 다시 "
                           "조회하세요.\n"
                         : "서비스 연결이 끊겼습니다. 이 화면을 닫고 다시 연결하세요.\n") +
              message);
    UpdateControls();
}

void PcbSelectionDialog::SetStatus(const std::string& message)
{
    m_status->SetLabel(Display(message));
    m_status->Wrap(GetClientSize().GetWidth() - FromDIP(32));
    Layout();
}

/** @brief 확인되지 않은 서버 실패를 정상 미리보기나 적용 완료로 표시하지 않는다. */
void PcbSelectionDialog::ShowFailure(const Json& error)
{
    const std::string headline = DiagnosticMessage(error);
    std::string message = headline;
    std::vector<Json> details;
    if (error.contains("details") && error.at("details").is_object())
    {
        details.push_back(error.at("details"));
    }
    if (error.contains("data") && error.at("data").is_object())
    {
        const auto& data = error.at("data");
        if (data.contains("diagnostics") && data.at("diagnostics").is_array())
        {
            for (const auto& diagnostic : data.at("diagnostics"))
            {
                if (!diagnostic.is_object())
                {
                    continue;
                }
                const std::string text = DiagnosticMessage(diagnostic);
                if (text != headline)
                {
                    message += "\n- " + text;
                }
                if (diagnostic.contains("details") && diagnostic.at("details").is_object())
                {
                    details.push_back(diagnostic.at("details"));
                }
            }
        }
    }
    for (const auto& item : details)
    {
        for (const char* field : {"field_path", "field"})
        {
            if (item.contains(field) && item.at(field).is_string())
            {
                message += "\n입력 위치: " + item.at(field).get<std::string>();
            }
        }
        if (item.contains("review_reasons") && item.at("review_reasons").is_array())
        {
            for (const auto& reason : item.at("review_reasons"))
            {
                if (reason.is_string())
                {
                    message += "\n검토 사유: " + reason.get<std::string>();
                }
            }
        }
        if (item.contains("issues") && item.at("issues").is_array())
        {
            for (const auto& issue : item.at("issues"))
            {
                if (issue.is_object())
                {
                    message += "\n- " + DiagnosticMessage(issue);
                }
            }
        }
    }
    m_sectionLayers = Json::array();
    m_section->Refresh();
    if (message != headline)
    {
        m_review->ChangeValue(Display(message));
        m_notebook->SetSelection(4);
        SetStatus(headline + "\n세부 입력 위치와 검토 사유는 변경 검토 탭에서 확인하세요.");
    }
    else
    {
        SetStatus(headline);
    }
    UpdateControls();
}

/** @brief 숫자 파싱 전의 타이핑도 기존 미리보기의 적용 자격을 제거한다. */
void PcbSelectionDialog::Changed()
{
    if (m_loading || m_applying || m_disconnected || m_closed ||
        m_model.CurrentStage() == Studio::PcbSelectionModel::Stage::Stale)
    {
        return;
    }
    m_model.Invalidate();
    m_sectionLayers = Json::array();
    m_section->Refresh();
    SetStatus("입력이 바뀌었습니다. 변경 미리보기를 다시 확인하세요.");
    UpdateControls();
}

void PcbSelectionDialog::UpdateControls()
{
    const bool editable = !m_applying && !m_disconnected && !m_closed &&
                          m_model.CurrentStage() != Studio::PcbSelectionModel::Stage::Stale;
    m_notebook->Enable(editable);
    m_search->Enable(editable);
    m_previous->Enable(editable && m_pageOffsets.size() > 1);
    m_next->Enable(editable && m_searchResult.value("has_more", false));
    m_useSource->Enable(editable && !m_selected.is_null());
    const bool loadingDraft = m_model.CurrentStage() == Studio::PcbSelectionModel::Stage::LoadingDraft;
    m_useSuggestion->Enable(
        editable && !loadingDraft && !m_suggestionLoading && m_suggestionIndex >= 0 && !m_suggestionData.is_null() &&
        !m_suggestionData.at("layers").at(static_cast<std::size_t>(m_suggestionIndex)).at("material_spec").is_null());
    const bool pageReady = editable && !loadingDraft && !m_suggestionLoading && !m_suggestionData.is_null();
    m_suggestionPrevious->Enable(pageReady && m_suggestionOffsets.size() > 1);
    m_suggestionNext->Enable(pageReady && !m_suggestionData.at("next_offset").is_null());
    m_addLayer->Enable(editable && m_manual && m_layers->GetNumberRows() < 32);
    m_removeLayer->Enable(editable && m_manual && m_layers->GetNumberRows() > 1);
    m_previewButton->Enable(editable);
    m_applyButton->Enable(editable && m_model.CanApply());
    m_cancelButton->Enable(!m_applying);
}

/** @brief 서비스가 계산한 후보를 읽고 사용자가 검토할 때만 Apply를 활성화한다. */
void PcbSelectionDialog::Preview()
{
    try
    {
        if (m_materialDirty && !SaveMaterial())
        {
            return;
        }
        m_layers->SaveEditControlValue();
        m_ports->SaveEditControlValue();
        m_model.SetSpecification(CollectSpecification());
        const auto token = m_model.BeginRequest("preview");
        const Json input = m_model.PreviewInput();
        SetStatus("후보 적층, 기존 참조와 출처 보존 용량을 확인하고 있습니다.");
        UpdateControls();
        wxWeakRef<PcbSelectionDialog> weak(this);
        m_gateway(
            "pcb.selection.preview", input, false,
            [weak, token](const Json& result)
            {
                if (weak && !weak->m_closed && !weak->m_disconnected && weak->m_model.AcceptPreview(token, result))
                {
                    weak->RenderPreview(result);
                    weak->UpdateControls();
                }
            },
            [weak, token](const Json& error)
            {
                if (weak && !weak->m_closed && !weak->m_disconnected && weak->m_model.Fail(token, error))
                {
                    weak->ShowFailure(error);
                }
            });
    }
    catch (const std::exception& error)
    {
        SetStatus(error.what());
        UpdateControls();
    }
}

/** @brief 승인된 동일 입력을 한 번만 전송하고 결과를 주 창으로 돌려준다. */
void PcbSelectionDialog::Apply()
{
    try
    {
        m_layers->SaveEditControlValue();
        m_ports->SaveEditControlValue();
        if (m_materialDirty || CollectSpecification() != m_model.Specification())
        {
            Changed();
            SetStatus("아직 검토하지 않은 입력이 있습니다. 변경 미리보기를 다시 실행하세요.");
            return;
        }
        const Json input = m_model.ApplyInput(Uuid());
        const auto token = m_model.BeginRequest("apply");
        m_applying = true;
        SetStatus("검토한 재료, 층, 포트 좌표와 출처를 함께 적용하고 있습니다.");
        UpdateControls();
        wxWeakRef<PcbSelectionDialog> weak(this);
        m_gateway(
            "pcb.selection.apply", input, true,
            [weak, token](const Json& result)
            {
                if (weak && !weak->m_closed && !weak->m_disconnected && weak->m_model.AcceptApply(token, result))
                {
                    weak->m_applied = result;
                    weak->m_applying = false;
                    weak->m_closed = true;
                    weak->EndModal(wxID_OK);
                }
            },
            [weak, token](const Json& error)
            {
                if (weak && !weak->m_closed && !weak->m_disconnected && weak->m_model.Fail(token, error))
                {
                    weak->m_applying = false;
                    weak->ShowFailure(error);
                    weak->SetStatus("적용에 실패했거나 결과를 확정하지 못했습니다. 다시 적용하지 말고 화면을 닫은 뒤 "
                                    "프로젝트를 다시 조회하세요.\n" +
                                    DiagnosticMessage(error));
                }
            });
    }
    catch (const std::exception& error)
    {
        m_applying = false;
        SetStatus(error.what());
        UpdateControls();
    }
}
