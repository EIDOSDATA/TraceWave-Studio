/** @file @brief 형상 방식과 편집 동작 전환을 명시 초안으로 구분한다. */
#include "pcb_feature_dialog.h"
#include "pcb_feature_form.h"
#include "studio_support.h"
#include <wx/choice.h>
#include <wx/msgdlg.h>
#include <algorithm>

namespace
{
const std::vector<std::string> Shapes{"circle", "rectangle", "capsule", "polygon"};
}

void PcbFeatureDialog::RefreshSelectors()
{
    const auto record = m_context.at("form").at("record");
    const auto definition = record.value("definition", Json::object());
    const auto mode = definition.value("mode", "explicit_shape");
    m_definition->Show(m_sectionName == "aperture");
    m_definition->SetSelection(mode == "pad_margin" ? 1 : 0);
    m_envelope->Show(m_sectionName == "footprint");
    const auto envelope = record.value("placement_envelope", Json(nullptr));
    const auto envelopeKind = envelope.is_object() ? envelope.value("kind", "") : "";
    const auto envelopeFound = std::find(Shapes.begin(), Shapes.end(), envelopeKind);
    m_envelope->SetSelection(envelopeFound == Shapes.end() ? 0 : static_cast<int>(envelopeFound - Shapes.begin()) + 1);
    m_shape->Show(m_sectionName == "cutout" || m_sectionName == "hole" || m_sectionName == "keepout" ||
                  (m_sectionName == "aperture" && mode == "explicit_shape"));
    m_shapeKinds = m_sectionName == "hole"     ? std::vector<std::string>{"circle", "capsule"}
                   : m_sectionName == "cutout" ? std::vector<std::string>{"circle", "capsule", "polygon"}
                                               : Shapes;
    m_shape->Clear();
    for (const auto& kind : m_shapeKinds)
    {
        m_shape->Append(Display(kind == "circle"      ? "원형"
                                : kind == "rectangle" ? "사각형"
                                : kind == "capsule"   ? "직선 슬롯"
                                                      : "다각형"));
    }
    const auto shape =
        m_sectionName == "aperture" ? definition.value("shape", Json::object()) : record.value("shape", Json::object());
    const auto found = std::find(m_shapeKinds.begin(), m_shapeKinds.end(), shape.value("kind", "circle"));
    m_shape->SetSelection(found == m_shapeKinds.end() ? 0 : static_cast<int>(found - m_shapeKinds.begin()));
}

void PcbFeatureDialog::Transition()
{
    if (m_loading)
    {
        return;
    }
    if (!ConfirmDiscard())
    {
        RefreshSelectors();
        return;
    }
    wxMessageDialog confirm(this,
                            Display("입력 방식을 바꾸면 해당 형상 치수를 미정인 새 초안으로 준비합니다. 원본은 적용 "
                                    "전까지 유지됩니다. 계속하시겠습니까?"),
                            Display("형상 입력 방식"), wxYES_NO | wxNO_DEFAULT | wxICON_QUESTION);
    if (confirm.ShowModal() != wxID_YES)
    {
        RefreshSelectors();
        return;
    }
    Json transition = Json::object();
    if (m_sectionName == "footprint")
    {
        transition["envelope_kind"] =
            m_envelope->GetSelection() == 0 ? Json(nullptr) : Json(Shapes.at(m_envelope->GetSelection() - 1));
    }
    else
    {
        if (m_sectionName == "aperture")
        {
            transition["definition_mode"] = m_definition->GetSelection() == 1 ? "pad_margin" : "explicit_shape";
        }
        if (m_sectionName != "aperture" || m_definition->GetSelection() == 0)
        {
            transition["shape_kind"] = m_shapeKinds.at(m_shape->GetSelection());
        }
    }
    Load(m_sectionName, m_recordId, transition);
}

void PcbFeatureDialog::ChangeOperation()
{
    if (m_loading)
    {
        return;
    }
    const int selected = m_operation->GetSelection();
    if (!ConfirmDiscard())
    {
        m_operation->SetSelection(m_operationIndex);
        return;
    }
    m_form->SetForm(m_context.at("form"), m_context);
    m_operationIndex = selected;
    if (selected >= 0)
    {
        m_form->SetOperation(m_operations.at(selected), m_sectionName);
    }
    Changed();
}
