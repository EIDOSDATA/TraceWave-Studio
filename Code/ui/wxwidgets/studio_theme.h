/** @file @brief native 입력을 유지하는 주 작업 공간의 공통 표시 토큰이다. */
#pragma once

#include <wx/colour.h>
#include <wx/window.h>

class wxAuiManager;
class wxStaticText;

/** @brief 물리 장면의 색과 분리된 라이트 작업 공간 스타일이다. */
namespace StudioTheme
{
constexpr int Space = 4;
constexpr int InputGap = 8;
constexpr int PanelPadding = 12;
constexpr int GroupGap = 16;
constexpr int ToolHeight = 30;

/** @brief 입력 값의 의미를 바꾸지 않는 패널 역할이다. */
enum class Surface
{
    Workspace,
    Panel
};

/** @brief 고대비에서는 OS의 표면/글자 색을 함께 사용한다. */
struct Palette
{
    wxColour workspace;
    wxColour panel;
    wxColour border;
    wxColour text;
    wxColour secondary;
};

/** @brief Windows 고대비 설정을 반영하여 현재 팔레트를 반환한다. */
Palette Colours();
/** @brief 패널 생성 시 표면을 적용하고 OS 색 변경도 반영한다. */
void BindSurface(wxWindow& window, Surface surface = Surface::Panel);
/** @brief OS 기본 글꼴을 유지하며 그룹 제목의 굵기를 구분한다. */
void Heading(wxStaticText& label);
/** @brief 동적 안내 문구의 대비를 유지하고 고대비 전환을 반영한다. */
void BindSecondary(wxStaticText& label);
/** @brief 도킹 캡션과 경계의 색/크기를 OS 글꼴과 DIP 기준으로 설정한다. */
void ConfigureDocking(wxAuiManager& manager, wxWindow& window);
}
