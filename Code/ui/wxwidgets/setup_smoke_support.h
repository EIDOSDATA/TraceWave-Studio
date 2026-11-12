/** @file @brief 설정 화면 시험이 제품과 동일한 wx 이벤트를 사용하게 한다. */
#pragma once

#include <wx/button.h>
#include <wx/choice.h>
#include <wx/listbox.h>
#include <wx/modalhook.h>
#include <wx/dialog.h>
#include <stdexcept>

namespace SetupSmoke
{
/** @brief 실제 확인 대화상자의 응답만 고정하고 제품의 초안 분기를 검사한다. */
class DiscardHook final : public wxModalDialogHook
{
public:
    explicit DiscardHook(int response) : m_response(response)
    {
        Register();
    }
    ~DiscardHook() override
    {
        Unregister();
    }
    int Enter(wxDialog* dialog) override
    {
        if (dialog->GetName() == "setup.discard")
        {
            ++count;
            return m_response;
        }
        return wxID_NONE;
    }
    int count = 0;

private:
    int m_response;
};

/** @brief 비활성 버튼을 우회하지 않고 클릭 이벤트를 보낸다. */
inline void Click(wxButton* button)
{
    if (button == nullptr || !button->IsEnabled())
    {
        throw std::runtime_error("설정 시험 버튼이 비활성입니다.");
    }
    wxCommandEvent event(wxEVT_BUTTON, button->GetId());
    event.SetEventObject(button);
    button->GetEventHandler()->ProcessEvent(event);
}

/** @brief 선택 컨트롤의 실제 변경 알림을 전달한다. */
inline void Choose(wxChoice* choice, int index)
{
    choice->SetSelection(index);
    wxCommandEvent event(wxEVT_CHOICE, choice->GetId());
    event.SetInt(index);
    event.SetEventObject(choice);
    choice->GetEventHandler()->ProcessEvent(event);
}

/** @brief 목록의 실제 선택 경로를 사용한다. */
inline void Select(wxListBox* list, int index)
{
    list->SetSelection(index);
    wxCommandEvent event(wxEVT_LISTBOX, list->GetId());
    event.SetInt(index);
    event.SetEventObject(list);
    list->GetEventHandler()->ProcessEvent(event);
}
}
