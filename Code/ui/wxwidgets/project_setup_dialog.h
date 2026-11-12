/** @file @brief 프로젝트 설정 화면의 요청 세대와 적용/닫기 수명을 관리한다. */
#pragma once

#include "dialog_gateway.h"
#include <wx/dialog.h>
#include <cstdint>

class wxStaticText;
class StudioSmokeDriver;

/** @brief 늦은 조회와 미확정 변경을 구분하는 설정 화면의 공통 경계이다. */
class ProjectSetupDialog : public wxDialog
{
public:
    ProjectSetupDialog(wxWindow* parent, const std::string& title, const Json& context, DialogGateway gateway);
    const Json& GetAppliedResult() const;
    /** @brief 미확정 변경 또는 개정 충돌 후 원본 재조회 필요 여부이다. */
    bool NeedsReload() const;
    void ServiceDisconnected(const std::string& message);

protected:
    friend class StudioSmokeDriver;

    /** @brief 새로운 요청은 이전 조회 응답을 무효화하며 자동 재전송하지 않는다. */
    void Request(const std::string& method, const Json& input, bool mutation,
                 std::function<void(const Json&)> completed);
    /** @brief 폼 변경/닫기로 이전 읽기 응답의 적용을 막는다. */
    void InvalidateRead();
    /** @brief 권위 응답의 개정을 보관하며 변경 이력은 서비스가 소유한다. */
    void AcceptMutation(const Json& result);
    void SetStatus(const std::string& message);
    void CloseDialog(bool force = false);
    /** @brief 미적용 초안이 있을 때 닫기/선택 변경 전에 확인한다. */
    bool ConfirmDiscard();
    virtual bool HasDraft() const = 0;
    bool Editable() const;
    virtual void UpdateActions() = 0;
    /** @brief 입력 거절의 위치를 기능별 폼에 연결한다. */
    virtual void ShowRequestFailure(const Json& error);

    std::string m_projectId;
    std::string m_revision;
    Json m_applied = nullptr;
    Json m_error = nullptr;
    wxStaticText* m_status = nullptr;
    bool m_pending = false;
    bool m_mutating = false;
    bool m_disconnected = false;
    bool m_closed = false;
    bool m_needsReload = false;

private:
    DialogGateway m_gateway;
    std::uint64_t m_generation = 0;
};
