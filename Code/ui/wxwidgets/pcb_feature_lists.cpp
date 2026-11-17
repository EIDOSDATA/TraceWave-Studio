/** @file @brief 기계 좌표와 풋프린트 참조 목록의 편집 대화상자를 연결한다. */
#include "pcb_feature_form.h"
#include "pcb_feature_list_dialog.h"
#include "studio_support.h"
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/button.h>

void PcbFeatureForm::BuildList(const std::shared_ptr<Field>& field, wxBoxSizer* row)
{
    field->edit = new wxButton(field->row, wxID_ANY, Display("명시 목록 편집"));
    row->Add(field->edit, 0, wxRIGHT, FromDIP(8));
    row->Add(new wxStaticText(field->row, wxID_ANY, Display("변경 전 원문을 보존하며 항목별로 편집합니다.")), 1,
             wxALIGN_CENTER_VERTICAL);
    field->edit->Bind(wxEVT_BUTTON,
                      [this, field](wxCommandEvent&)
                      {
                          EditList(field);
                      });
}

void PcbFeatureForm::EditList(const std::shared_ptr<Field>& field)
{
    PcbFeatureListDialog dialog(this, field->descriptor, field->value, m_context);
    if (dialog.ShowModal() == wxID_OK)
    {
        if (field->descriptor.value("kind", "") == "coordinates")
        {
            field->descriptor["display_rows"] = dialog.DisplayRows();
        }
        else if (field->descriptor.value("kind", "") == "coordinate_loops")
        {
            field->descriptor["display_loops"] = dialog.DisplayLoops();
        }
        Changed(field, dialog.Value());
    }
}
