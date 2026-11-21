/** @file @brief Windows 합성 화면에서 시험 창의 프레임 번호와 시각을 읽는다. */
#pragma once

#include <cstdint>
#include <memory>
#include <optional>
#include <windows.h>

namespace WindowsDisplayMarker
{
constexpr int CellWidth = 4;
constexpr int Cells = 24;
constexpr int Width = Cells * CellWidth;
constexpr std::uint32_t Signature = 0xa70000;

/** @brief 합성 화면 갱신의 원시 시각과 운영체제에서 합쳐진 갱신 수이다. */
struct Frame
{
    std::int64_t presented;
    unsigned accumulated;
    std::optional<unsigned> sequence;
    bool protectedContent = false;
};

/** @brief 지정한 시험 창 안의 고정된 한 줄만 GPU에서 복사하고 원본 픽셀을 보존하지 않는다. */
class Reader final
{
public:
    Reader(HWND frame, HWND canvas, POINT marker);
    ~Reader();

    std::optional<Frame> Next();
    unsigned RefreshRate() const;
    SIZE OutputSize() const;

private:
    struct State;
    std::unique_ptr<State> m_state;
};
}
