/** @file @brief 연구 후보의 실제 복소 표본을 원본 라이브러리로 복사하지 않고 조회한다. */
#pragma once
#include "project_setup_dialog.h"
#include <wx/collpane.h>
class NetworkChart;
class StudioNotebook;
class wxChoice;
class wxListCtrl;
class wxTextCtrl;
class wxButton;

/** @brief 읽기 전용 후보 결과의 채널/페이지와 조건을 같은 ID로 유지한다. */
class SweepResultDialog final : public ProjectSetupDialog
{
public:
    SweepResultDialog(wxWindow* parent, const Json& context, const std::string& studyId, int index,
                      DialogGateway gateway);

private:
    friend class StudioSmokeDriver;
    void Load(int offset);
    void Render(const Json& result);
    void ChangeMetric();
    bool HasDraft() const override
    {
        return false;
    }
    void UpdateActions() override;
    void ShowRequestFailure(const Json& error) override;
    std::string m_studyId;
    int m_index = 0;
    int m_offset = 0;
    int m_nextOffset = -1;
    Json m_result = nullptr;
    NetworkChart* m_chart = nullptr;
    wxListCtrl* m_samples = nullptr;
    wxTextCtrl* m_conditions = nullptr;
    wxTextCtrl* m_source = nullptr;
    wxCollapsiblePane* m_advanced = nullptr;
    StudioNotebook* m_tabs = nullptr;
    wxChoice* m_row = nullptr;
    wxChoice* m_column = nullptr;
    wxChoice* m_metric = nullptr;
    wxButton* m_previous = nullptr;
    wxButton* m_next = nullptr;
};
