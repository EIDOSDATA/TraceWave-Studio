#include "accessibility.h"

#include <algorithm>
#include <atomic>
#include <cwchar>
#include <mutex>
#include <new>
#include <utility>

#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <commctrl.h>
#include <uiautomationclient.h>
#include <uiautomationcore.h>
#include <uiautomationcoreapi.h>

#include <imgui_internal.h>

namespace accessibility
{
namespace
{
struct Description
{
    const wchar_t* name;
    const wchar_t* id;
    CONTROLTYPEID role;
    PATTERNID pattern = 0;
    const wchar_t* shortcut = L"";
};

constexpr Description descriptions[] =
{
    {L"", L"", UIA_WindowControlTypeId},
    {L"메뉴 모음", L"menu-bar", UIA_MenuBarControlTypeId},
    {L"창", L"window-menu", UIA_MenuItemControlTypeId, UIA_ExpandCollapsePatternId, L"F10"},
    {L"기판", L"show-board", UIA_MenuItemControlTypeId, UIA_TogglePatternId},
    {L"RF 결과", L"show-result", UIA_MenuItemControlTypeId, UIA_TogglePatternId, L"F7"},
    {L"입력에 초점", L"focus-note", UIA_MenuItemControlTypeId, UIA_InvokePatternId, L"F6"},
    {L"결과를 별도 창으로", L"detach-result", UIA_MenuItemControlTypeId, UIA_InvokePatternId, L"F8"},
    {L"입력을 별도 창으로", L"detach-note", UIA_MenuItemControlTypeId, UIA_InvokePatternId, L"Shift+F8"},
    {L"기본 배치 복원", L"reset-layout", UIA_MenuItemControlTypeId, UIA_InvokePatternId, L"F9"},
    {L"기판", L"board", UIA_PaneControlTypeId},
    {L"보기 초기화", L"reset-board", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"RF 결과", L"result", UIA_PaneControlTypeId},
    {L"입력", L"input", UIA_PaneControlTypeId},
    {L"검수 메모", L"note", UIA_EditControlTypeId, UIA_ValuePatternId, L"F6"},
    {L"메모 지우기", L"clear-note", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"다시 열기", L"reload-project", UIA_ButtonControlTypeId, UIA_InvokePatternId, L"F5"},
    {L"저장", L"save-project", UIA_ButtonControlTypeId, UIA_InvokePatternId, L"Ctrl+S"},
    {L"되돌리기", L"undo-project", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"왼쪽으로 1 mm 이동", L"move-left", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"오른쪽으로 1 mm 이동", L"move-right", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"아래로 1 mm 이동", L"move-down", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"위로 1 mm 이동", L"move-up", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"3D 형상 보기", L"toggle-model", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"3D 형상 다시 읽기", L"reload-model", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"RF 결과 다시 읽기", L"reload-result", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"3D 생성", L"build-model", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"STEP 출력", L"export-step", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"CAD 취소", L"cancel-cad", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"해석 도구", L"show-solver", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"저장된 해석 조건 읽기", L"solver-conditions", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"이전 해석 조건", L"solver-condition-previous", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"다음 해석 조건", L"solver-condition-next", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"해석 계획 검토", L"solver-review", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"검토한 해석 계획 실행", L"solver-run", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"해석 취소", L"solver-cancel", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"", L"solver-selected-condition", UIA_TextControlTypeId},
    {L"", L"solver-status", UIA_TextControlTypeId},
    {L"", L"solver-plan-summary", UIA_TextControlTypeId},
    {L"과거 RF 결과", L"show-rf-history", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"과거 RF 결과 목록 다시 읽기", L"reload-rf-history", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"이전 RF 결과", L"prior-rf-history", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"다음 RF 결과", L"next-rf-history", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"선택한 RF 결과 열기", L"open-rf-history", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"", L"selected-rf-history", UIA_TextControlTypeId},
    {L"", L"rf-history-status", UIA_TextControlTypeId},
    {L"", L"rf-result-read-status", UIA_TextControlTypeId},
    {L"", L"rf-result-summary", UIA_TextControlTypeId},
    {L"도면 및 PCB 출력 도구", L"show-exchange", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"이전 출력 형식", L"exchange-previous", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"다음 출력 형식", L"exchange-next", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"이전 풋프린트", L"exchange-footprint-previous", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"다음 풋프린트", L"exchange-footprint-next", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"선택한 풋프린트 검토", L"exchange-footprint-review", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"출력 검토", L"exchange-review", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"승인한 출력 생성", L"exchange-build", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"게시한 출력 재검수", L"exchange-verify", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"출력 취소", L"exchange-cancel", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"출력 기록 다시 읽기", L"exchange-reload", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"", L"exchange-format", UIA_TextControlTypeId},
    {L"", L"exchange-footprint", UIA_TextControlTypeId},
    {L"", L"exchange-status", UIA_TextControlTypeId},
    {L"", L"exchange-review-summary", UIA_TextControlTypeId},
    {L"", L"exchange-publication", UIA_TextControlTypeId},
    {L"RF 내보내기 도구", L"show-rf-export", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"이전 RF 내보내기 형식", L"rf-export-previous", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"다음 RF 내보내기 형식", L"rf-export-next", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"선택한 RF 결과와 조건 저장", L"rf-export-save", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"", L"rf-export-format", UIA_TextControlTypeId},
    {L"", L"rf-export-status", UIA_TextControlTypeId},
    {L"이전 수신 포트", L"matrix-row-previous", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"다음 수신 포트", L"matrix-row-next", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"이전 입사 포트", L"matrix-column-previous", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"다음 입사 포트", L"matrix-column-next", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"이전 주파수", L"matrix-sample-previous", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"다음 주파수", L"matrix-sample-next", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"행렬 표", L"matrix-table", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"", L"matrix-axes", UIA_TextControlTypeId},
    {L"", L"matrix-sample", UIA_TextControlTypeId},
    {L"제조 교환 형식 변경", L"manufacturing-format", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"제조 교환 후보 ZIP 저장", L"manufacturing-build", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"", L"manufacturing-choice", UIA_TextControlTypeId},
    {L"", L"manufacturing-status", UIA_TextControlTypeId},
    {L"프로젝트 선택", L"project-chooser", UIA_ButtonControlTypeId, UIA_TogglePatternId, L"Ctrl+O"},
    {L"새 프로젝트 모드", L"project-create-mode", UIA_ButtonControlTypeId, UIA_TogglePatternId, L"Ctrl+N"},
    {L"프로젝트 폴더 이름", L"project-name", UIA_EditControlTypeId, UIA_ValuePatternId},
    {L"프로젝트 선택 또는 생성 실행", L"project-submit", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"", L"project-chooser-status", UIA_TextControlTypeId},
    {L"저장본과 현재 개정 비교", L"show-recovery", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"저장본 비교 다시 읽기", L"read-recovery", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"이전 변경 항목", L"recovery-prior", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"다음 변경 항목", L"recovery-next", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"", L"recovery-summary", UIA_TextControlTypeId},
    {L"", L"recovery-field", UIA_TextControlTypeId},
    {L"", L"recovery-before", UIA_TextControlTypeId},
    {L"", L"recovery-after", UIA_TextControlTypeId},
    {L"이전 최근 프로젝트", L"recent-previous", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"다음 최근 프로젝트", L"recent-next", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"선택한 최근 프로젝트 열기", L"recent-open", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"", L"recent-path", UIA_TextControlTypeId},
    {L"보존 묶음 복원 도구", L"archive-toggle", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"복원할 보존 ZIP 선택", L"archive-pick", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"검토한 보존 ZIP 복원 승인", L"archive-apply", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"보존 ZIP 검토 취소", L"archive-cancel", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"복원한 프로젝트 열기", L"archive-open", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"", L"archive-review", UIA_TextControlTypeId},
    {L"", L"archive-status", UIA_TextControlTypeId},
    {L"끝점 편집", L"endpoint-toggle", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"시작점 선택", L"endpoint-start", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"끝점 선택", L"endpoint-end", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"끝점 스냅", L"endpoint-snap", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"캔버스에서 끝점 지정", L"endpoint-pick", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"끝점 X 밀리미터", L"endpoint-x", UIA_EditControlTypeId, UIA_ValuePatternId},
    {L"끝점 Y 밀리미터", L"endpoint-y", UIA_EditControlTypeId, UIA_ValuePatternId},
    {L"선택한 끝점 적용", L"endpoint-apply", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"끝점 초안 좌표 되돌리기", L"endpoint-reset", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"", L"endpoint-snap-status", UIA_TextControlTypeId},
    {L"3D 단면 도구", L"section-toggle", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"3D 단면 축 변경", L"section-axis", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"큰 좌표 쪽 보존", L"section-side", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"단면의 위치 밀리미터", L"section-position", UIA_EditControlTypeId, UIA_ValuePatternId},
    {L"단면 적용", L"section-apply", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"", L"section-axis-value", UIA_TextControlTypeId},
    {L"", L"section-status", UIA_TextControlTypeId},
    {L"이름 바꾸기", L"rename-toggle", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"이름 바꾸기", L"rename-dialog", UIA_WindowControlTypeId},
    {L"", L"rename-target", UIA_TextControlTypeId},
    {L"새 표시 이름", L"rename-name", UIA_EditControlTypeId, UIA_ValuePatternId},
    {L"이름 변경 적용", L"rename-apply", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"이름 변경 취소", L"rename-cancel", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"", L"rename-status", UIA_TextControlTypeId},
    {L"고급 정보", L"rename-details", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"", L"rename-id", UIA_TextControlTypeId},
    {L"고유 ID 복사", L"rename-copy", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"출처와 변경 이력", L"evidence-toggle", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"현재 개정의 출처 읽기", L"evidence-reload", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"채택 이력", L"evidence-records", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"가정과 생략", L"evidence-assumptions", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"변경 이력", L"evidence-history", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"이전 기록", L"evidence-previous", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"다음 기록", L"evidence-next", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"이전 출처 값", L"evidence-previous-value", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"다음 출처 값", L"evidence-next-value", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"", L"evidence-status", UIA_TextControlTypeId},
    {L"", L"evidence-summary", UIA_TextControlTypeId},
    {L"", L"evidence-title", UIA_TextControlTypeId},
    {L"", L"evidence-source", UIA_TextControlTypeId},
    {L"", L"evidence-values", UIA_TextControlTypeId},
    {L"목표 편집", L"target-toggle", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"새 목표", L"target-new", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"대역과 표본", L"target-band", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"성능 기준", L"target-criteria", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"목표 출처와 변경 이력", L"target-sources", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"목표 변경 적용", L"target-apply", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"선택한 목표 삭제 적용", L"target-apply-removal", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"목표 삭제", L"target-remove", UIA_ButtonControlTypeId, UIA_TogglePatternId},
    {L"목표 초안 취소", L"target-discard", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"목표 데이터 다시 읽기", L"target-read", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"이전 목표 변경 기록", L"target-prev-change", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"다음 목표 변경 기록", L"target-next-change", UIA_ButtonControlTypeId, UIA_InvokePatternId},
    {L"목표 이름", L"target-name", UIA_EditControlTypeId, UIA_ValuePatternId},
    {L"대역 시작", L"target-start", UIA_EditControlTypeId, UIA_ValuePatternId},
    {L"대역 끝", L"target-end", UIA_EditControlTypeId, UIA_ValuePatternId},
    {L"등간격 표본 수", L"target-samples", UIA_EditControlTypeId, UIA_ValuePatternId},
    {L"S11 한계", L"target-s11", UIA_EditControlTypeId, UIA_ValuePatternId},
    {L"목표 변경 사유", L"target-reason", UIA_EditControlTypeId, UIA_ValuePatternId},
    {L"", L"target-status", UIA_TextControlTypeId},
    {L"", L"target-summary", UIA_TextControlTypeId},
    {L"", L"target-history", UIA_TextControlTypeId}
};
static_assert(std::size(descriptions) == static_cast<std::size_t>(Control::targetHistory) + 1);

struct Node
{
    Control control;
    Control parent = Control::root;
    UiaRect bounds{};
    bool enabled = true;
    bool focused = false;
    bool checked = false;
    std::string name{};
    std::string value{};
};

struct Snapshot
{
    std::vector<Node> nodes;
    std::string value;

    const Node* find(Control control) const
    {
        const auto iter = std::ranges::find(nodes, control, &Node::control);
        return iter == nodes.end() ? nullptr : &*iter;
    }

    Control focus() const
    {
        const auto iter = std::ranges::find_if(nodes.rbegin(), nodes.rend(), [](const Node& node)
        {
            return node.focused;
        });
        return iter == nodes.rend() ? Control::root : iter->control;
    }
};

/** @brief UIA 호출에는 게시된 값만 제공하고 실제 조작은 SDL 스레드로 돌려보낸다. */
struct WindowState
{
    explicit WindowState(HWND handle) : hwnd(handle) {}

    HWND const hwnd;
    std::mutex mutex;
    bool alive = true;
    Snapshot snapshot;
    std::vector<Action> actions;
};

BSTR utf8Value(const std::string& value)
{
    const int length = static_cast<int>(value.size());
    const int wideLength = MultiByteToWideChar(CP_UTF8, 0, value.data(), length, nullptr, 0);
    BSTR result = SysAllocStringLen(nullptr, wideLength);
    if (result && wideLength)
    {
        MultiByteToWideChar(CP_UTF8, 0, value.data(), length, result, wideLength);
    }
    return result;
}

bool contains(const UiaRect& bounds, double x, double y)
{
    return x >= bounds.left && x < bounds.left + bounds.width
        && y >= bounds.top && y < bounds.top + bounds.height;
}

class Provider final : public IRawElementProviderSimple, public IRawElementProviderFragment,
    public IRawElementProviderFragmentRoot, public IInvokeProvider, public IToggleProvider,
    public IExpandCollapseProvider, public IValueProvider
{
public:
    Provider(std::shared_ptr<WindowState> window, Control control)
        : window(std::move(window)), control(control), description(descriptions[static_cast<int>(control)])
    {
    }

    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** output) override
    {
        *output = nullptr;
        if (iid == __uuidof(IUnknown) || iid == __uuidof(IRawElementProviderSimple))
        {
            *output = static_cast<IRawElementProviderSimple*>(this);
        }
        else if (iid == __uuidof(IRawElementProviderFragment))
        {
            *output = static_cast<IRawElementProviderFragment*>(this);
        }
        else if (iid == __uuidof(IRawElementProviderFragmentRoot) && control == Control::root)
        {
            *output = static_cast<IRawElementProviderFragmentRoot*>(this);
        }
        else if (iid == __uuidof(IInvokeProvider) && description.pattern == UIA_InvokePatternId)
        {
            *output = static_cast<IInvokeProvider*>(this);
        }
        else if (iid == __uuidof(IToggleProvider) && description.pattern == UIA_TogglePatternId)
        {
            *output = static_cast<IToggleProvider*>(this);
        }
        else if (iid == __uuidof(IExpandCollapseProvider) && description.pattern == UIA_ExpandCollapsePatternId)
        {
            *output = static_cast<IExpandCollapseProvider*>(this);
        }
        else if (iid == __uuidof(IValueProvider) && description.pattern == UIA_ValuePatternId)
        {
            *output = static_cast<IValueProvider*>(this);
        }
        if (!*output)
        {
            return E_NOINTERFACE;
        }
        AddRef();
        return S_OK;
    }

    ULONG STDMETHODCALLTYPE AddRef() override { return ++references; }
    ULONG STDMETHODCALLTYPE Release() override
    {
        const ULONG remaining = --references;
        if (!remaining)
        {
            delete this;
        }
        return remaining;
    }

    HRESULT STDMETHODCALLTYPE get_ProviderOptions(ProviderOptions* output) override
    {
        *output = static_cast<ProviderOptions>(ProviderOptions_ServerSideProvider | ProviderOptions_ProviderOwnsSetFocus);
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE get_HostRawElementProvider(IRawElementProviderSimple** output) override
    {
        *output = nullptr;
        if (control == Control::root)
        {
            return UiaHostProviderFromHwnd(window->hwnd, output);
        }
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE GetPatternProvider(PATTERNID pattern, IUnknown** output) override
    {
        *output = nullptr;
        if (pattern != description.pattern)
        {
            return S_OK;
        }
        switch (pattern)
        {
            case UIA_InvokePatternId: *output = static_cast<IInvokeProvider*>(this); break;
            case UIA_TogglePatternId: *output = static_cast<IToggleProvider*>(this); break;
            case UIA_ExpandCollapsePatternId: *output = static_cast<IExpandCollapseProvider*>(this); break;
            case UIA_ValuePatternId: *output = static_cast<IValueProvider*>(this); break;
            default: return S_OK;
        }
        AddRef();
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE GetPropertyValue(PROPERTYID property, VARIANT* output) override
    {
        VariantInit(output);
        std::lock_guard lock(window->mutex);
        const Node* node = current();
        if (!node)
        {
            return UIA_E_ELEMENTNOTAVAILABLE;
        }
        if (control == Control::root)
        {
            if (property == UIA_HasKeyboardFocusPropertyId)
            {
                setBool(output, window->snapshot.focus() == Control::root && GetForegroundWindow() == window->hwnd);
            }
            return S_OK;
        }
        switch (property)
        {
            case UIA_NamePropertyId:
                if (node->name.empty())
                {
                    return setString(output, description.name);
                }
                output->vt = VT_BSTR;
                output->bstrVal = utf8Value(node->name);
                return output->bstrVal ? S_OK : E_OUTOFMEMORY;
            case UIA_AutomationIdPropertyId: return setString(output, description.id);
            case UIA_AcceleratorKeyPropertyId: return setString(output, description.shortcut);
            case UIA_ControlTypePropertyId:
                output->vt = VT_I4;
                output->lVal = description.role;
                break;
            case UIA_IsControlElementPropertyId:
            case UIA_IsContentElementPropertyId: setBool(output, true); break;
            case UIA_IsEnabledPropertyId: setBool(output, node->enabled); break;
            case UIA_IsKeyboardFocusablePropertyId: setBool(output, canFocus(*node)); break;
            case UIA_HasKeyboardFocusPropertyId:
                setBool(output, node->focused && GetForegroundWindow() == window->hwnd);
                break;
            case UIA_IsOffscreenPropertyId:
                setBool(output, IsIconic(window->hwnd) || node->bounds.width <= 0 || node->bounds.height <= 0);
                break;
            default: break;
        }
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE Navigate(NavigateDirection direction, IRawElementProviderFragment** output) override
    {
        *output = nullptr;
        std::lock_guard lock(window->mutex);
        const Node* node = current();
        if (!node)
        {
            return UIA_E_ELEMENTNOTAVAILABLE;
        }
        const auto& nodes = window->snapshot.nodes;
        if (direction == NavigateDirection_Parent && control != Control::root)
        {
            return fragment(node->parent, output);
        }
        if (direction == NavigateDirection_FirstChild || direction == NavigateDirection_LastChild)
        {
            const Node* child = nullptr;
            for (const Node& candidate : nodes)
            {
                if (candidate.control != Control::root && candidate.parent == control)
                {
                    child = &candidate;
                    if (direction == NavigateDirection_FirstChild)
                    {
                        break;
                    }
                }
            }
            return child ? fragment(child->control, output) : S_OK;
        }
        if (control != Control::root)
        {
            const bool next = direction == NavigateDirection_NextSibling;
            const auto position = node - nodes.data();
            const auto step = next ? 1 : -1;
            for (auto index = position + step; index > 0 && index < std::ssize(nodes); index += step)
            {
                if (nodes[index].parent == node->parent)
                {
                    return fragment(nodes[index].control, output);
                }
            }
        }
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE GetRuntimeId(SAFEARRAY** output) override
    {
        *output = nullptr;
        if (control == Control::root)
        {
            return S_OK;
        }
        SAFEARRAY* id = SafeArrayCreateVector(VT_I4, 0, 2);
        if (!id)
        {
            return E_OUTOFMEMORY;
        }
        LONG index = 0;
        LONG append = UiaAppendRuntimeId;
        SafeArrayPutElement(id, &index, &append);
        ++index;
        LONG element = static_cast<LONG>(control);
        SafeArrayPutElement(id, &index, &element);
        *output = id;
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE get_BoundingRectangle(UiaRect* output) override
    {
        std::lock_guard lock(window->mutex);
        const Node* node = current();
        *output = node ? node->bounds : UiaRect{};
        return node ? S_OK : UIA_E_ELEMENTNOTAVAILABLE;
    }

    HRESULT STDMETHODCALLTYPE GetEmbeddedFragmentRoots(SAFEARRAY** output) override
    {
        *output = nullptr;
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE SetFocus() override { return enqueue(Operation::focus); }

    HRESULT STDMETHODCALLTYPE get_FragmentRoot(IRawElementProviderFragmentRoot** output) override
    {
        *output = new (std::nothrow) Provider(window, Control::root);
        return *output ? S_OK : E_OUTOFMEMORY;
    }

    HRESULT STDMETHODCALLTYPE ElementProviderFromPoint(double x, double y,
        IRawElementProviderFragment** output) override
    {
        *output = nullptr;
        std::lock_guard lock(window->mutex);
        if (!current())
        {
            return UIA_E_ELEMENTNOTAVAILABLE;
        }
        const auto& nodes = window->snapshot.nodes;
        for (auto node = nodes.rbegin(); node != nodes.rend(); ++node)
        {
            if (contains(node->bounds, x, y))
            {
                return fragment(node->control, output);
            }
        }
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE GetFocus(IRawElementProviderFragment** output) override
    {
        *output = nullptr;
        std::lock_guard lock(window->mutex);
        if (!current())
        {
            return UIA_E_ELEMENTNOTAVAILABLE;
        }
        if (GetForegroundWindow() == window->hwnd)
        {
            return fragment(window->snapshot.focus(), output);
        }
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE Invoke() override { return enqueue(Operation::invoke); }
    HRESULT STDMETHODCALLTYPE Toggle() override { return enqueue(Operation::toggle); }
    HRESULT STDMETHODCALLTYPE Expand() override { return enqueue(Operation::expand); }
    HRESULT STDMETHODCALLTYPE Collapse() override { return enqueue(Operation::collapse); }

    HRESULT STDMETHODCALLTYPE get_ToggleState(ToggleState* output) override
    {
        std::lock_guard lock(window->mutex);
        const Node* node = current();
        *output = node && node->checked ? ToggleState_On : ToggleState_Off;
        return node ? S_OK : UIA_E_ELEMENTNOTAVAILABLE;
    }

    HRESULT STDMETHODCALLTYPE get_ExpandCollapseState(ExpandCollapseState* output) override
    {
        std::lock_guard lock(window->mutex);
        const Node* node = current();
        *output = node && node->checked ? ExpandCollapseState_Expanded : ExpandCollapseState_Collapsed;
        return node ? S_OK : UIA_E_ELEMENTNOTAVAILABLE;
    }

    HRESULT STDMETHODCALLTYPE SetValue(LPCWSTR value) override
    {
        if (!value || std::wcspbrk(value, L"\r\n"))
        {
            return E_INVALIDARG;
        }
        const int size = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value, -1, nullptr, 0, nullptr, nullptr);
        const auto capacity = control == Control::note ? noteCapacity : projectNameCapacity;
        if (size <= 0 || size > static_cast<int>(capacity))
        {
            return E_INVALIDARG;
        }
        std::string utf8(static_cast<std::size_t>(size), '\0');
        WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value, -1, utf8.data(), size, nullptr, nullptr);
        utf8.pop_back();
        return enqueue(Operation::setValue, std::move(utf8));
    }

    HRESULT STDMETHODCALLTYPE get_Value(BSTR* output) override
    {
        *output = nullptr;
        std::lock_guard lock(window->mutex);
        const auto* node = current();
        if (!node)
        {
            return UIA_E_ELEMENTNOTAVAILABLE;
        }
        *output = utf8Value(control == Control::note ? window->snapshot.value : node->value);
        return *output ? S_OK : E_OUTOFMEMORY;
    }

    HRESULT STDMETHODCALLTYPE get_IsReadOnly(BOOL* output) override
    {
        std::lock_guard lock(window->mutex);
        const auto* node = current();
        *output = node && node->enabled ? FALSE : TRUE;
        return node ? S_OK : UIA_E_ELEMENTNOTAVAILABLE;
    }

private:
    const Node* current() const { return window->alive ? window->snapshot.find(control) : nullptr; }

    bool canFocus(const Node& node) const
    {
        return node.enabled && control != Control::menuBar &&
            descriptions[static_cast<int>(control)].role != UIA_TextControlTypeId;
    }

    HRESULT fragment(Control target, IRawElementProviderFragment** output) const
    {
        *output = new (std::nothrow) Provider(window, target);
        return *output ? S_OK : E_OUTOFMEMORY;
    }

    HRESULT enqueue(Operation operation, std::string value = {})
    {
        std::lock_guard lock(window->mutex);
        const Node* node = current();
        if (!node)
        {
            return UIA_E_ELEMENTNOTAVAILABLE;
        }
        if (!node->enabled)
        {
            return UIA_E_ELEMENTNOTENABLED;
        }
        if (operation == Operation::focus && !canFocus(*node))
        {
            return UIA_E_INVALIDOPERATION;
        }
        window->actions.push_back({control, operation, std::move(value)});
        return S_OK;
    }

    static HRESULT setString(VARIANT* output, const wchar_t* value)
    {
        output->vt = VT_BSTR;
        output->bstrVal = SysAllocString(value);
        return output->bstrVal ? S_OK : E_OUTOFMEMORY;
    }

    static void setBool(VARIANT* output, bool value)
    {
        output->vt = VT_BOOL;
        output->boolVal = value ? VARIANT_TRUE : VARIANT_FALSE;
    }

    std::atomic<ULONG> references{1};
    std::shared_ptr<WindowState> window;
    Control control;
    const Description& description;
};

struct Host
{
    explicit Host(HWND hwnd);
    ~Host();

    void update(Snapshot next, bool foreground);

    std::shared_ptr<WindowState> window;
    Provider* root;
    bool attached = false;
    bool focused = false;
};

LRESULT CALLBACK uiAutomationSubclass(HWND hwnd, UINT message, WPARAM wParam, LPARAM lParam, UINT_PTR id,
    DWORD_PTR data)
{
    auto& host = *reinterpret_cast<Host*>(data);
    if (message == WM_GETOBJECT && static_cast<LONG>(lParam) == UiaRootObjectId)
    {
        return UiaReturnRawElementProvider(hwnd, wParam, lParam, host.root);
    }
    if (message == WM_NCDESTROY)
    {
        {
            std::lock_guard lock(host.window->mutex);
            host.window->alive = false;
        }
        RemoveWindowSubclass(hwnd, uiAutomationSubclass, id);
        host.attached = false;
        UiaReturnRawElementProvider(hwnd, 0, 0, nullptr);
    }
    return DefSubclassProc(hwnd, message, wParam, lParam);
}

Host::Host(HWND hwnd) : window(std::make_shared<WindowState>(hwnd)), root(new Provider(window, Control::root))
{
    attached = SetWindowSubclass(hwnd, uiAutomationSubclass, 1, reinterpret_cast<DWORD_PTR>(this));
}

Host::~Host()
{
    {
        std::lock_guard lock(window->mutex);
        window->alive = false;
    }
    if (attached)
    {
        RemoveWindowSubclass(window->hwnd, uiAutomationSubclass, 1);
        UiaReturnRawElementProvider(window->hwnd, 0, 0, nullptr);
    }
    root->Release();
}

/** @brief 게시가 끝난 후 UIA에 초점, 값, 메뉴 상태 및 요소의 변경을 알린다. */
void Host::update(Snapshot next, bool foreground)
{
    Snapshot previous;
    {
        std::lock_guard lock(window->mutex);
        previous = std::exchange(window->snapshot, next);
    }
    const bool becameFocused = !focused && foreground;
    focused = foreground;
    if (!UiaClientsAreListening())
    {
        return;
    }
    if (!std::ranges::equal(previous.nodes, next.nodes, {}, &Node::control, &Node::control)
        || !std::ranges::equal(previous.nodes, next.nodes, {}, &Node::parent, &Node::parent))
    {
        UiaRaiseStructureChangedEvent(root, StructureChangeType_ChildrenInvalidated, nullptr, 0);
    }
    const Control target = next.focus();
    if (foreground && (becameFocused || target != previous.focus()))
    {
        auto* provider = new Provider(window, target);
        UiaRaiseAutomationEvent(provider, UIA_AutomationFocusChangedEventId);
        provider->Release();
    }
    for (const Node& node : next.nodes)
    {
        const Node* prior = previous.find(node.control);
        if (!prior)
        {
            continue;
        }
        if (prior->enabled != node.enabled)
        {
            VARIANT oldEnabled{};
            VARIANT newEnabled{};
            oldEnabled.vt = newEnabled.vt = VT_BOOL;
            oldEnabled.boolVal = prior->enabled ? VARIANT_TRUE : VARIANT_FALSE;
            newEnabled.boolVal = node.enabled ? VARIANT_TRUE : VARIANT_FALSE;
            auto* provider = new Provider(window, node.control);
            UiaRaiseAutomationPropertyChangedEvent(provider, UIA_IsEnabledPropertyId, oldEnabled, newEnabled);
            provider->Release();
        }
        const PATTERNID pattern = descriptions[static_cast<int>(node.control)].pattern;
        const auto& previousValue = node.control == Control::note ? previous.value : prior->value;
        const auto& nextValue = node.control == Control::note ? next.value : node.value;
        VARIANT before{};
        VARIANT after{};
        PROPERTYID property = 0;
        if (prior->name != node.name)
        {
            property = UIA_NamePropertyId;
            before.vt = after.vt = VT_BSTR;
            before.bstrVal = utf8Value(prior->name);
            after.bstrVal = utf8Value(node.name);
        }
        else if (pattern == UIA_ValuePatternId && previousValue != nextValue)
        {
            property = UIA_ValueValuePropertyId;
            before.vt = after.vt = VT_BSTR;
            before.bstrVal = utf8Value(previousValue);
            after.bstrVal = utf8Value(nextValue);
        }
        else if (prior->checked != node.checked && (pattern == UIA_TogglePatternId || pattern == UIA_ExpandCollapsePatternId))
        {
            before.vt = after.vt = VT_I4;
            if (pattern == UIA_TogglePatternId)
            {
                property = UIA_ToggleToggleStatePropertyId;
                before.lVal = prior->checked ? ToggleState_On : ToggleState_Off;
                after.lVal = node.checked ? ToggleState_On : ToggleState_Off;
            }
            else
            {
                property = UIA_ExpandCollapseExpandCollapseStatePropertyId;
                before.lVal = prior->checked ? ExpandCollapseState_Expanded : ExpandCollapseState_Collapsed;
                after.lVal = node.checked ? ExpandCollapseState_Expanded : ExpandCollapseState_Collapsed;
            }
        }
        if (property)
        {
            auto* provider = new Provider(window, node.control);
            UiaRaiseAutomationPropertyChangedEvent(provider, property, before, after);
            provider->Release();
            VariantClear(&before);
            VariantClear(&after);
        }
    }
}

struct FrameNode
{
    ImGuiID viewport;
    ImRect area;
    Node node;
};

UiaRect boundsInWindow(ImRect area, const ImGuiViewport& viewport, POINT origin, RECT client)
{
    const float left = std::clamp(area.Min.x - viewport.Pos.x, 0.0f, static_cast<float>(client.right));
    const float top = std::clamp(area.Min.y - viewport.Pos.y, 0.0f, static_cast<float>(client.bottom));
    const float right = std::clamp(area.Max.x - viewport.Pos.x, left, static_cast<float>(client.right));
    const float bottom = std::clamp(area.Max.y - viewport.Pos.y, top, static_cast<float>(client.bottom));
    return {origin.x + static_cast<double>(left), origin.y + static_cast<double>(top), right - left, bottom - top};
}
}

struct Bridge::State
{
    std::vector<FrameNode> frame;
    std::vector<std::unique_ptr<Host>> hosts;
    bool coInitialized = SUCCEEDED(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED));

    ~State()
    {
        hosts.clear();
        if (coInitialized)
        {
            CoUninitialize();
        }
    }
};

Bridge::Bridge() : state(std::make_unique<State>()) {}
Bridge::~Bridge() = default;

void Bridge::item(Control control, Control parent, bool enabled, bool checked, const ImGuiViewport* viewport,
    std::string_view value)
{
    ImGuiWindow* window = ImGui::GetCurrentWindowRead();
    const ImRect area(ImGui::GetItemRectMin(), ImGui::GetItemRectMax());
    state->frame.push_back({viewport ? viewport->ID : window->Viewport->ID, area,
        {control, parent, {}, enabled, ImGui::IsItemFocused() ||
            (descriptions[static_cast<int>(control)].pattern == UIA_ValuePatternId && ImGui::IsItemActive()),
            checked, {}, std::string(value)}});
}

void Bridge::text(Control control, Control parent, std::string_view name)
{
    const ImRect area(ImGui::GetItemRectMin(), ImGui::GetItemRectMax());
    state->frame.push_back({ImGui::GetWindowViewport()->ID, area,
        {control, parent, {}, true, false, false, std::string(name)}});
}

void Bridge::panel(Control control)
{
    ImGuiWindow* window = ImGui::GetCurrentWindowRead();
    state->frame.push_back({window->Viewport->ID, window->Rect(),
        {control, Control::root, {}, true, control != Control::menuBar && ImGui::IsWindowFocused()}});
}

void Bridge::publish(const char* value)
{
    ImGuiPlatformIO& platform = ImGui::GetPlatformIO();
    const HWND foreground = GetForegroundWindow();
    std::erase_if(state->hosts, [](const auto& host) { return !host->attached; });
    for (const ImGuiViewport* viewport : platform.Viewports)
    {
        HWND hwnd = static_cast<HWND>(viewport->PlatformHandleRaw);
        RECT client{};
        POINT origin{};
        if (!hwnd || !GetClientRect(hwnd, &client) || !ClientToScreen(hwnd, &origin))
        {
            continue;
        }

        auto it = std::ranges::find_if(state->hosts, [hwnd](const auto& host) { return host->window->hwnd == hwnd; });
        if (it == state->hosts.end())
        {
            state->hosts.push_back(std::make_unique<Host>(hwnd));
            it = std::prev(state->hosts.end());
        }
        Snapshot snapshot;
        RECT outer{};
        GetWindowRect(hwnd, &outer);
        snapshot.nodes.push_back({Control::root, Control::root, {static_cast<double>(outer.left),
            static_cast<double>(outer.top), static_cast<double>(outer.right - outer.left),
            static_cast<double>(outer.bottom - outer.top)}});
        for (const FrameNode& entry : state->frame)
        {
            if (entry.viewport == viewport->ID)
            {
                Node node = entry.node;
                node.bounds = boundsInWindow(entry.area, *viewport, origin, client);
                snapshot.nodes.push_back(node);
            }
        }
        if (snapshot.find(Control::renameDialog))
        {
            std::erase_if(snapshot.nodes, [](const Node& node)
            {
                return node.control != Control::root && node.control != Control::renameDialog &&
                    node.parent != Control::renameDialog;
            });
        }
        for (Node& node : snapshot.nodes)
        {
            if (!snapshot.find(node.parent))
            {
                node.parent = Control::root;
            }
            if (node.focused && (descriptions[static_cast<int>(node.control)].role == UIA_PaneControlTypeId ||
                node.control == Control::renameDialog)
                && std::ranges::any_of(snapshot.nodes, [&node](const Node& child)
                {
                    return child.parent == node.control && child.focused;
                }))
            {
                node.focused = false;
            }
        }
        if (snapshot.find(Control::note))
        {
            snapshot.value = value;
        }
        (*it)->update(std::move(snapshot), hwnd == foreground);
    }
    state->frame.clear();
}

std::vector<Action> Bridge::takeActions()
{
    std::vector<Action> result;
    for (const auto& host : state->hosts)
    {
        std::vector<Action> actions;
        {
            std::lock_guard lock(host->window->mutex);
            actions.swap(host->window->actions);
        }
        for (Action& action : actions)
        {
            if (action.operation == Operation::focus)
            {
                SetForegroundWindow(host->window->hwnd);
            }
            result.push_back(std::move(action));
        }
    }
    return result;
}
}
