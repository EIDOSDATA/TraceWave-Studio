/** @file @brief Windows Studio 검증용 GPU 메모리 계측이다. */
#include "studio_smoke_gpu.h"
#include <windows.h>
#include <dxgi1_4.h>
#include <wrl/client.h>
#include <cstring>
#include <memory>
#include <type_traits>

/** @brief GPU 계측을 활성화한 실행에서만 Studio 프로세스의 DXGI node 0 사용량을 읽는다. */
Json StudioSmoke::GpuMemorySamples()
{
    using Microsoft::WRL::ComPtr;
    const std::unique_ptr<std::remove_pointer_t<HMODULE>, decltype(&FreeLibrary)> module(
        LoadLibraryExW(L"dxgi.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32), &FreeLibrary);
    if (!module)
    {
        return Json::array();
    }
    const auto entry = GetProcAddress(module.get(), "CreateDXGIFactory1");
    decltype(&CreateDXGIFactory1) create = nullptr;
    static_assert(sizeof(create) == sizeof(entry));
    std::memcpy(&create, &entry, sizeof(create));
    ComPtr<IDXGIFactory1> factory;
    if (create == nullptr || FAILED(create(IID_PPV_ARGS(factory.GetAddressOf()))))
    {
        return Json::array();
    }
    auto rows = Json::array();
    for (UINT ordinal = 0;; ++ordinal)
    {
        ComPtr<IDXGIAdapter1> adapter;
        if (FAILED(factory->EnumAdapters1(ordinal, adapter.GetAddressOf())))
        {
            break;
        }
        DXGI_ADAPTER_DESC1 description{};
        ComPtr<IDXGIAdapter3> memory;
        if (FAILED(adapter->GetDesc1(&description)) ||
            (description.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) != 0 || FAILED(adapter.As(&memory)))
        {
            continue;
        }
        const auto usage = [&](DXGI_MEMORY_SEGMENT_GROUP group) -> Json
        {
            DXGI_QUERY_VIDEO_MEMORY_INFO info{};
            if (FAILED(memory->QueryVideoMemoryInfo(0, group, &info)))
            {
                return nullptr;
            }
            return info.CurrentUsage;
        };
        rows.push_back({{"ordinal", ordinal}, {"node", 0},
                        {"local_bytes", usage(DXGI_MEMORY_SEGMENT_GROUP_LOCAL)},
                        {"nonlocal_bytes", usage(DXGI_MEMORY_SEGMENT_GROUP_NON_LOCAL)}});
    }
    return rows;
}
