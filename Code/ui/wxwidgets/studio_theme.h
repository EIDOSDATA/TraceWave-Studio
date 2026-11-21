/** @file @brief native 입력을 유지하는 주 작업 공간의 공통 표시 토큰이다. */
#pragma once

#include <cstddef>

#include <wx/colour.h>
#include <wx/window.h>
#include <wx/bitmap.h>
#include <string>

class wxAuiManager;
class wxStaticText;
class wxButton;
class wxListCtrl;

/** @brief 물리 장면의 색과 분리된 라이트 작업 공간 스타일이다. */
namespace StudioTheme
{
constexpr int Space = 4;
constexpr int InputGap = 8;
constexpr int PanelPadding = 12;
constexpr int GroupGap = 16;
constexpr int ToolHeight = 36;
constexpr int TabHeight = 40;

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
    wxColour content;
    wxColour accent;
    wxColour selection;
};

/** @brief Windows 고대비 설정을 반영하여 현재 팔레트를 반환한다. */
Palette Colours();
/** @brief 시스템 글꼴 종류와 큰 글자를 유지하며 본문을 최소 11pt로 표시한다. */
void ApplyTypography(wxWindow& window);
/** @brief 화면 제목과 선택 객체 이름에 본문보다 큰 계층을 부여한다. */
void Title(wxStaticText& label);
/** @brief 기본 버튼의 높이와 여백을 통일하며 실제 입력 동작은 native 위젯이 맡는다. */
void Button(wxButton& button, bool primary = false);
/** @brief native 표에 읽기 쉬운 행 높이와 공통 바탕을 적용한다. */
void Table(wxListCtrl& list);
/** @brief 프로젝트 탐색과 도구막대에서 재사용할 의미 아이콘을 그린다. */
wxBitmap Icon(wxWindow& window, const std::string& kind, int size = 20, int rowHeight = 20);
/** @brief 패널 생성 시 표면을 적용하고 OS 색 변경도 반영한다. */
void BindSurface(wxWindow& window, Surface surface = Surface::Panel);
/** @brief 늦게 만든 패널의 native 컨트롤에도 시스템 색 변경을 연결한다. */
void BindNativeControls(wxWindow& parent, std::size_t firstChild = 0);
/** @brief OS 기본 글꼴을 유지하며 그룹 제목의 굵기를 구분한다. */
void Heading(wxStaticText& label);
/** @brief 동적 안내 문구의 대비를 유지하고 고대비 전환을 반영한다. */
void BindSecondary(wxStaticText& label);
/** @brief 도킹 캡션과 경계의 색/크기를 OS 글꼴과 DIP 기준으로 설정한다. */
void ConfigureDocking(wxAuiManager& manager, wxWindow& window);
}
