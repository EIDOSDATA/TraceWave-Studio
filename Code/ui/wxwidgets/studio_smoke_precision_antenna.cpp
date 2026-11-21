/** @file @brief 원호와 IFA의 동일 선택을 실제 2D/3D 입력과 정밀 편집으로 검증한다. */
#include "studio_internal.h"
#include "precision_dialog.h"
#include "setup_smoke_support.h"
#include "studio_notebook.h"
#include <wx/choicdlg.h>
#include <wx/listbox.h>
#include <cmath>

namespace
{
/** @brief 현재 트리에서 사람이 읽는 이름과 분리된 원본 ID를 찾는다. */
wxTreeItemId FindObject(wxTreeCtrl& tree, const wxTreeItemId& root, const std::string& identity)
{
    const auto* data = dynamic_cast<const SelectionData*>(tree.GetItemData(root));
    if (data && data->selection.value("id", "") == identity)
    {
        return root;
    }
    wxTreeItemIdValue cookie;
    for (auto node = tree.GetFirstChild(root, cookie); node.IsOk(); node = tree.GetNextChild(root, cookie))
    {
        const auto found = FindObject(tree, node, identity);
        if (found.IsOk())
        {
            return found;
        }
    }
    return {};
}

/** @brief 병합 도체의 실제 원본 선택 대화상자에서 라벨이 일치하는 행만 선택한다. */
class MeshSourceChoice final : public wxModalDialogHook
{
public:
    explicit MeshSourceChoice(std::string label) : m_label(std::move(label))
    {
        Register();
    }
    ~MeshSourceChoice() override
    {
        Unregister();
    }

    int Enter(wxDialog* dialog) override
    {
        auto* choice = dynamic_cast<wxSingleChoiceDialog*>(dialog);
        if (!choice || dialog->GetTitle() != Display("3D 원본 선택"))
        {
            return wxID_NONE;
        }
        for (auto* child : dialog->GetChildren())
        {
            if (auto* list = dynamic_cast<wxListBox*>(child))
            {
                int index = 0;
                for (const auto& row : list->GetStrings())
                {
                    if (row.Contains(Display(m_label)))
                    {
                        choice->SetSelection(index);
                        selected = true;
                        return wxID_OK;
                    }
                    ++index;
                }
            }
        }
        return wxID_CANCEL;
    }

    bool selected = false;

private:
    std::string m_label;
};
}

void StudioSmokeDriver::PrecisionAntennaSmokeTick()
{
    const std::string identity = m_precisionAntenna.at("id");
    const std::string other = m_precisionAntenna.at("other_id");
    const std::string dimension = m_precisionAntenna.at("dimension");
    const auto point = m_precisionAntenna.at("point_mm");
    auto* modal = dynamic_cast<PrecisionDialog*>(m_frame.m_setupDialog);
    if (modal != nullptr)
    {
        if (modal->m_pending)
        {
            return;
        }
        if (m_setupStage == 6)
        {
            SetupSmoke::Choose(modal->m_operation, SetupSmoke::FindRow(modal->m_context.at("operations"), "id", "dimension_set"));
            SetupSmoke::Choose(modal->m_dimension, SetupSmoke::FindRow(modal->m_context.at("dimensions"), "key", dimension));
            modal->m_numbers.at("value")->SetValue("0");
            m_setupStage = 7;
            SetupSmoke::Click(modal->m_preview);
        }
        else if (m_setupStage == 7)
        {
            CanvasAssert(!modal->m_review.at("can_apply").get<bool>() && !modal->m_apply->IsEnabled() &&
                             CanvasShape(identity) == m_precisionBeforeShapes,
                         "잘못된 치수 후보가 원호/IFA 원본을 변경했습니다.");
            modal->m_numbers.at("value")->SetValue(Display(m_precisionAntenna.at("value").get<std::string>()));
            m_setupStage = 8;
            SetupSmoke::Click(modal->m_preview);
        }
        else if (m_setupStage == 8)
        {
            CanvasAssert(modal->m_review.at("can_apply").get<bool>(), "유효한 원호/IFA 치수 편집이 차단됐습니다.");
            m_setupStage = 9;
            SetupSmoke::Click(modal->m_apply);
        }
        return;
    }
    if (m_frame.m_busy || m_frame.m_cadRestoring || m_frame.m_modelView->IsLoading())
    {
        return;
    }
    const auto selectTree = [this](const std::string& id)
    {
        const auto node = FindObject(*m_frame.m_tree, m_frame.m_tree->GetRootItem(), id);
        CanvasAssert(node.IsOk(), "트리에서 편집할 원본을 찾지 못했습니다.");
        m_frame.m_tree->SelectItem(node);
    };
    const auto check = [this, &identity](const std::string& id)
    {
        const auto node = m_frame.m_tree->GetSelection();
        const auto* data = node.IsOk() ? dynamic_cast<const SelectionData*>(m_frame.m_tree->GetItemData(node)) : nullptr;
        CanvasAssert(data && data->selection.value("id", "") == id && m_frame.m_selection.value("id", "") == id &&
                         m_frame.m_canvas->Selection() == id && m_frame.m_modelView->Selection() == id &&
                         m_frame.m_editor.at("selection").at("id") == id,
                     "2D, 3D, 트리와 속성이 서로 다른 원본을 가리킵니다.");
        if (id == identity)
        {
            const std::string label = m_precisionAntenna.at("label");
            CanvasAssert(m_frame.m_selectionLabel->GetLabel() == Display(label) &&
                             m_frame.m_editorPanel->FieldValue("name") == label,
                         "원호/IFA가 선택됐지만 속성 제목 또는 이름 입력이 다른 객체를 표시합니다.");
        }
    };
    if (m_setupStage == 1)
    {
        CanvasAssert(m_frame.m_cadConfigured, "원호/IFA 시험에 OCCT 실행 환경이 필요합니다.");
        m_setupStage = 2;
        selectTree(other);
    }
    else if (m_setupStage == 2)
    {
        check(other);
        m_setupStage = 3;
        SetupSmoke::Click(m_frame.m_tools.at(IdBuild3D));
    }
    else if (m_setupStage == 3 && m_frame.m_modelView->HasMesh() && !m_frame.m_displayResult.empty())
    {
        CanvasAssert(m_frame.m_displayResult.at("snapshot").at("revision_id") == m_frame.m_revision,
                     "현재 개정의 OCCT 메시가 표시되지 않았습니다.");
        m_setupStage = 5;
        m_frame.m_views->SetSelection(0);
        m_frame.m_canvas->FitView();
        CanvasClick(point[0].get<double>(), point[1].get<double>());
    }
    else if (m_setupStage == 5)
    {
        check(identity);
        m_precisionBeforeShapes = CanvasShape(identity);
        m_precisionUndoBefore = m_frame.m_editor.at("history").at("undo_count");
        m_setupStage = 6;
        SetupSmoke::Click(m_frame.m_tools.at(IdPrecision));
    }
    else if (m_setupStage == 9)
    {
        check(identity);
        m_precisionAppliedShapes = CanvasShape(identity);
        CanvasAssert(m_precisionBeforeShapes != m_precisionAppliedShapes &&
                         m_frame.m_editor.at("history").at("undo_count") == m_precisionUndoBefore + 1,
                     "치수가 한 이력 명령으로 적용되지 않았습니다.");
        m_setupStage = 10;
        m_frame.History("project.undo");
    }
    else if (m_setupStage == 10)
    {
        check(identity);
        CanvasAssert(CanvasShape(identity) == m_precisionBeforeShapes, "실행 취소가 원래 도체를 복원하지 못했습니다.");
        m_setupStage = 11;
        m_frame.History("project.redo");
    }
    else if (m_setupStage == 11)
    {
        check(identity);
        CanvasAssert(CanvasShape(identity) == m_precisionAppliedShapes, "다시 실행에서 편집 치수가 유실됐습니다.");
        m_setupChecks.push_back("antenna_dimension_reject_apply_undo_redo");
        m_setupStage = 12;
        selectTree(other);
    }
    else if (m_setupStage == 12)
    {
        m_frame.m_views->SetSelection(1);
        m_frame.m_modelView->SetView("top");
        m_frame.m_modelView->FitView();
        CanvasAssert(m_frame.m_modelView->ClickTopPointForSmoke(point[0].get<double>(), point[1].get<double>()),
                     "이전 메시의 원호/IFA에 실제 마우스 입력을 전달하지 못했습니다.");
        check(other);
        CanvasAssert(m_frame.m_modelHint->GetLabel().Contains(Display("3D를 갱신")),
                     "이전 메시를 클릭한 뒤 개정 안내가 유지되지 않았습니다.");
        m_setupStage = 13;
        SetupSmoke::Click(m_frame.m_tools.at(IdBuild3D));
    }
    else if (m_setupStage == 13 && !m_frame.m_displayResult.empty() &&
             m_frame.m_displayResult.at("snapshot").at("revision_id") == m_frame.m_revision)
    {
        m_frame.m_modelView->SetView("top");
        m_frame.m_modelView->FitView();
        MeshSourceChoice choice(m_precisionAntenna.at("label").get<std::string>());
        m_setupStage = 14;
        CanvasAssert(m_frame.m_modelView->ClickTopPointForSmoke(point[0].get<double>(), point[1].get<double>()),
                     "갱신한 메시의 원호/IFA에 실제 마우스 입력을 전달하지 못했습니다.");
        if (m_precisionAntenna.value("merged", false))
        {
            CanvasAssert(choice.selected, "병합 바디의 원본 라벨을 선택할 수 없었습니다.");
        }
    }
    else if (m_setupStage == 14)
    {
        check(identity);
        m_setupChecks.push_back("antenna_current_and_stale_mesh_selection");
        m_setupStage = 15;
        m_frame.SaveProject();
    }
    else if (m_setupStage == 15 && m_frame.m_savedRevision == m_frame.m_revision)
    {
        m_setupStage = 16;
        m_frame.OpenProject("open", m_frame.m_path);
    }
    else if (m_setupStage == 16)
    {
        m_setupStage = 17;
        selectTree(identity);
    }
    else if (m_setupStage == 17)
    {
        check(identity);
        CanvasAssert(CanvasShape(identity) == m_precisionAppliedShapes && m_frame.m_revision == m_frame.m_savedRevision,
                     "재열기에서 원호/IFA 치수나 원본 ID가 유실됐습니다.");
        m_setupChecks.push_back("antenna_saved_reopen_selection_and_geometry");
        FinishSmoke(true, "");
    }
    if (m_frame.m_cadState == "failed" || !m_frame.m_modelView->Error().empty())
    {
        throw std::runtime_error("원호/IFA 3D 작업 실패: " + Utf8(m_frame.m_cadDetails->GetValue()));
    }
}
