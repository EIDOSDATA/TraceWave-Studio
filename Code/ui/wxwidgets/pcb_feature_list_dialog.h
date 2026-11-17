/** @file @brief 좌표, 핀과 소유 목록을 의미 있는 표와 참조 선택으로 편집한다. */
#pragma once
#include "studio_types.h"
#include <wx/dialog.h>

class wxGrid;
class wxListCtrl;
class wxTextCtrl;
class wxCheckListBox;
class wxChoice;

class PcbFeatureListDialog final : public wxDialog
{
public:
    PcbFeatureListDialog(wxWindow* parent, const Json& field, const Json& value, const Json& context);
    Json Value() const;
    Json DisplayRows() const;
    Json DisplayLoops() const;

private:
    void BuildCoordinates(wxSizer* layout);
    void BuildLoops(wxSizer* layout);
    void RenderLoops();
    void EditLoop(bool append);
    void BuildPins(wxSizer* layout);
    void RenderPins();
    void SelectPin();
    Json m_field, m_original, m_value, m_context;
    std::string m_kind;
    wxGrid* m_grid = nullptr;
    wxListCtrl* m_pins = nullptr;
    wxListCtrl* m_loops = nullptr;
    Json m_displayLoops = Json::array();
    wxTextCtrl* m_number = nullptr;
    wxTextCtrl* m_refs = nullptr;
    wxCheckListBox* m_pads = nullptr;
    wxCheckListBox* m_members = nullptr;
    wxChoice* m_hole = nullptr;
    Json m_padChoices = Json::array(), m_holeChoices = Json::array(), m_memberChoices = Json::array();
};
