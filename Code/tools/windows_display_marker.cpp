/** @file @brief Desktop Duplication 프레임에서 시험 번호를 확인한다. */
#include "windows_display_marker.h"

#include <d3d11.h>
#include <dxgi1_2.h>
#include <wrl/client.h>

#include <cstddef>
#include <cstdio>
#include <stdexcept>
#include <type_traits>

namespace WindowsDisplayMarker
{
namespace
{
using Microsoft::WRL::ComPtr;
using SystemLibrary = std::unique_ptr<std::remove_pointer_t<HMODULE>, decltype(&FreeLibrary)>;

/** @brief 표시 계측을 실행할 때만 Windows 그래픽 진단 DLL을 가져온다. */
SystemLibrary LoadSystemLibrary(const wchar_t* name)
{
    SystemLibrary module(LoadLibraryExW(name, nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32), &FreeLibrary);
    if (!module)
    {
        throw std::runtime_error("Windows 합성 계측 라이브러리를 열지 못했습니다.");
    }
    return module;
}

template <class Function>
Function LoadEntry(const SystemLibrary& library, const char* name)
{
    const auto entry = GetProcAddress(library.get(), name);
    if (entry == nullptr)
    {
        throw std::runtime_error(std::string("Windows 합성 계측 함수가 없습니다: ") + name);
    }
    return reinterpret_cast<Function>(entry);
}

/** @brief 실패 HRESULT를 보고서에 남기도록 읽기 단계와 연결한다. */
void Check(HRESULT status, const char* operation)
{
    if (FAILED(status))
    {
        char code[16]{};
        std::snprintf(code, sizeof(code), "0x%08lx", static_cast<unsigned long>(status));
        throw std::runtime_error(std::string(operation) + " " + code);
    }
}

/** @brief 포인터만 바뀐 경우를 포함해 얻은 프레임은 언제나 반환한다. */
class AcquiredFrame final
{
public:
    explicit AcquiredFrame(IDXGIOutputDuplication& output) : m_output(output) {}
    ~AcquiredFrame()
    {
        m_output.ReleaseFrame();
    }

private:
    IDXGIOutputDuplication& m_output;
};

/** @brief 각 셀의 가운데를 검사하고 시험 표시가 없거나 가려지면 번호를 얻지 않는다. */
std::optional<unsigned> Decode(const std::byte* pixels)
{
    std::uint32_t code = 0;
    for (int cell = 0; cell < Cells; ++cell)
    {
        const auto* pixel = pixels + (cell * CellWidth + CellWidth / 2) * 4;
        const bool dark = pixel[0] < std::byte{32} && pixel[1] < std::byte{32} && pixel[2] < std::byte{32};
        const bool light = pixel[0] > std::byte{223} && pixel[1] > std::byte{223} && pixel[2] > std::byte{223};
        if (!dark && !light)
        {
            return std::nullopt;
        }
        if (light)
        {
            code |= 1u << cell;
        }
    }
    return (code & 0xff0000u) == Signature ? std::optional<unsigned>(code & 0xffffu) : std::nullopt;
}
}

struct Reader::State
{
    SystemLibrary dxgi = LoadSystemLibrary(L"dxgi.dll");
    SystemLibrary d3d = LoadSystemLibrary(L"d3d11.dll");
    HWND frame;
    HWND canvas;
    RECT canvasRect{};
    POINT origin{};
    D3D11_BOX marker{};
    ComPtr<IDXGIOutputDuplication> output;
    ComPtr<ID3D11DeviceContext> context;
    ComPtr<ID3D11Texture2D> strip;
    SIZE size{};
    unsigned refresh = 0;
};

Reader::Reader(HWND frame, HWND canvas, POINT marker) : m_state(std::make_unique<State>())
{
    auto& state = *m_state;
    state.frame = frame;
    state.canvas = canvas;
    if (!GetClientRect(canvas, &state.canvasRect) || !ClientToScreen(canvas, &state.origin) ||
        marker.x < 0 || marker.y < 0 || marker.x + Width > state.canvasRect.right ||
        marker.y >= state.canvasRect.bottom)
    {
        throw std::runtime_error("시험 창 안의 화면 표식 좌표를 확인하지 못했습니다.");
    }
    const RECT target{state.origin.x + marker.x, state.origin.y + marker.y,
                      state.origin.x + marker.x + Width, state.origin.y + marker.y + 1};
    const HMONITOR monitor = MonitorFromRect(&target, MONITOR_DEFAULTTONULL);
    ComPtr<IDXGIFactory1> factory;
    const auto createFactory = LoadEntry<decltype(&CreateDXGIFactory1)>(state.dxgi, "CreateDXGIFactory1");
    const auto createDevice = LoadEntry<decltype(&D3D11CreateDevice)>(state.d3d, "D3D11CreateDevice");
    Check(createFactory(IID_PPV_ARGS(factory.GetAddressOf())), "CreateDXGIFactory1");
    for (UINT adapterIndex = 0;; ++adapterIndex)
    {
        ComPtr<IDXGIAdapter1> adapter;
        const HRESULT adapterStatus = factory->EnumAdapters1(adapterIndex, adapter.GetAddressOf());
        if (adapterStatus == DXGI_ERROR_NOT_FOUND)
        {
            break;
        }
        Check(adapterStatus, "EnumAdapters1");
        for (UINT outputIndex = 0;; ++outputIndex)
        {
            ComPtr<IDXGIOutput> output;
            const HRESULT outputStatus = adapter->EnumOutputs(outputIndex, output.GetAddressOf());
            if (outputStatus == DXGI_ERROR_NOT_FOUND)
            {
                break;
            }
            Check(outputStatus, "EnumOutputs");
            DXGI_OUTPUT_DESC display{};
            Check(output->GetDesc(&display), "IDXGIOutput::GetDesc");
            if (!display.AttachedToDesktop || display.Monitor != monitor)
            {
                continue;
            }
            const RECT desktop = display.DesktopCoordinates;
            if (display.Rotation != DXGI_MODE_ROTATION_IDENTITY || target.left < desktop.left ||
                target.right > desktop.right || target.top < desktop.top || target.bottom > desktop.bottom)
            {
                throw std::runtime_error("시험 표식을 포함한 회전 없는 단일 출력이 필요합니다.");
            }
            ComPtr<ID3D11Device> device;
            Check(createDevice(adapter.Get(), D3D_DRIVER_TYPE_UNKNOWN, nullptr, 0, nullptr, 0,
                               D3D11_SDK_VERSION, device.GetAddressOf(), nullptr, state.context.GetAddressOf()),
                  "D3D11CreateDevice");
            ComPtr<IDXGIOutput1> capture;
            Check(output.As(&capture), "IDXGIOutput1");
            Check(capture->DuplicateOutput(device.Get(), state.output.GetAddressOf()), "DuplicateOutput");
            D3D11_TEXTURE2D_DESC texture{};
            texture.Width = Width;
            texture.Height = 1;
            texture.MipLevels = 1;
            texture.ArraySize = 1;
            texture.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
            texture.SampleDesc.Count = 1;
            texture.Usage = D3D11_USAGE_STAGING;
            texture.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
            Check(device->CreateTexture2D(&texture, nullptr, state.strip.GetAddressOf()), "CreateTexture2D");
            state.marker = {static_cast<UINT>(target.left - desktop.left), static_cast<UINT>(target.top - desktop.top),
                            0, static_cast<UINT>(target.right - desktop.left),
                            static_cast<UINT>(target.bottom - desktop.top), 1};
            state.size = {desktop.right - desktop.left, desktop.bottom - desktop.top};
            DEVMODEW mode{};
            mode.dmSize = sizeof(mode);
            if (EnumDisplaySettingsW(display.DeviceName, ENUM_CURRENT_SETTINGS, &mode))
            {
                state.refresh = mode.dmDisplayFrequency;
            }
            return;
        }
    }
    throw std::runtime_error("시험 창의 활성 Windows 디스플레이를 찾지 못했습니다.");
}

Reader::~Reader() = default;

std::optional<Frame> Reader::Next()
{
    auto& state = *m_state;
    POINT origin{};
    RECT bounds{};
    if (GetForegroundWindow() != state.frame || IsIconic(state.frame) ||
        !ClientToScreen(state.canvas, &origin) || !GetClientRect(state.canvas, &bounds) ||
        origin.x != state.origin.x || origin.y != state.origin.y || !EqualRect(&bounds, &state.canvasRect))
    {
        throw std::runtime_error("시험 창의 전경 상태, 위치 또는 크기가 바뀌었습니다.");
    }
    DXGI_OUTDUPL_FRAME_INFO info{};
    ComPtr<IDXGIResource> image;
    const HRESULT status = state.output->AcquireNextFrame(25, &info, image.GetAddressOf());
    if (status == DXGI_ERROR_WAIT_TIMEOUT)
    {
        return std::nullopt;
    }
    Check(status, "AcquireNextFrame");
    AcquiredFrame acquired(*state.output.Get());
    if (info.LastPresentTime.QuadPart == 0)
    {
        return std::nullopt;
    }
    Frame frame{info.LastPresentTime.QuadPart, info.AccumulatedFrames, std::nullopt};
    if (info.ProtectedContentMaskedOut)
    {
        return frame;
    }
    ComPtr<ID3D11Texture2D> surface;
    Check(image.As(&surface), "ID3D11Texture2D");
    state.context->CopySubresourceRegion(state.strip.Get(), 0, 0, 0, 0, surface.Get(), 0, &state.marker);
    D3D11_MAPPED_SUBRESOURCE mapped{};
    Check(state.context->Map(state.strip.Get(), 0, D3D11_MAP_READ, 0, &mapped), "Map");
    frame.sequence = Decode(static_cast<const std::byte*>(mapped.pData));
    state.context->Unmap(state.strip.Get(), 0);
    return frame;
}

unsigned Reader::RefreshRate() const
{
    return m_state->refresh;
}

SIZE Reader::OutputSize() const
{
    return m_state->size;
}
}
