cmake_minimum_required(VERSION 3.24)
project(TraceWaveShellPrototype LANGUAGES C CXX)

if(NOT CMAKE_SYSTEM_NAME MATCHES "^(Windows|Linux|Darwin)$")
    message(FATAL_ERROR "The shell prototype requires Windows, Linux or macOS.")
endif()

include(FetchContent)

function(prototype_source name repo revision sha256)
    FetchContent_Declare(${name}
        URL "https://codeload.github.com/${repo}/tar.gz/${revision}"
        URL_HASH "SHA256=${sha256}"
        DOWNLOAD_EXTRACT_TIMESTAMP FALSE
    )
endfunction()

prototype_source(SDL3 libsdl-org/SDL 147a8ee32dbf9ac02f3794964490687b6bbda1bc
    29d9362282d347b8ae25c7f572a535e72de0749e60528abb1523daaf43d072fd)
prototype_source(imgui ocornut/imgui 4806a1924ff6181180bf5e4b8b79ab4394118875
    cc35a88df717dff3c488e43b4b148dcfe968bd3ff6798f60751b106eb9bcee48)
prototype_source(implot epezent/implot 18c72431f8265e2b0b5378a3a73d8a883b2175ff
    4787c77e6050f3bdc19f39eecf87d5b321bd3096321142b63f8169e1aa8f9b34)
prototype_source(bgfx_wrapper bkaradzic/bgfx.cmake c07b70ddc18d84538a460d6b022b6bb22d0e0950
    146f66340a5014a1c2ee8396c59ea3853ddcd6169e61d1c506be52ffbeadfd0a)
prototype_source(bx bkaradzic/bx 150eb9fa89d4fdb13154f763517726bd560b67fa
    bb49f9d99dec753b83eced500da1843879644746032338aa6e3970f54f85b880)
prototype_source(bimg bkaradzic/bimg 38ceda5c7778228f976f75900623fb5923b49107
    319180cb8ae9c6d2ba31396edc6c4aebd925c1eb64ce91ba57b6e115648d7a43)
prototype_source(bgfx bkaradzic/bgfx 9714e329d7b9eda40254964634d57010d1e80659
    06b745336d9424e98ba56a324788675aae47e2769850e28baad03a6acbb3435b)

set(SDL_SHARED OFF)
set(SDL_STATIC ON)
set(SDL_TEST_LIBRARY OFF)
set(SDL_TESTS OFF)
set(SDL_EXAMPLES OFF)
set(SDL_INSTALL OFF)
set(BGFX_BUILD_TOOLS OFF)
set(BGFX_BUILD_EXAMPLES OFF)
set(BGFX_BUILD_TESTS OFF)
set(BGFX_INSTALL OFF)
set(BGFX_CONFIG_VIDEO OFF)
set(BGFX_CONFIG_MULTITHREADED OFF)

FetchContent_MakeAvailable(SDL3 imgui implot bgfx_wrapper)
FetchContent_GetProperties(bgfx SOURCE_DIR prototype_bgfx_source)

add_library(prototype_widgets STATIC
    "${imgui_SOURCE_DIR}/imgui.cpp"
    "${imgui_SOURCE_DIR}/imgui_draw.cpp"
    "${imgui_SOURCE_DIR}/imgui_tables.cpp"
    "${imgui_SOURCE_DIR}/imgui_widgets.cpp"
    "${imgui_SOURCE_DIR}/backends/imgui_impl_sdl3.cpp"
    "${implot_SOURCE_DIR}/implot.cpp"
    "${implot_SOURCE_DIR}/implot_items.cpp"
)
target_include_directories(prototype_widgets SYSTEM PUBLIC
    "${imgui_SOURCE_DIR}" "${imgui_SOURCE_DIR}/backends" "${implot_SOURCE_DIR}"
)
target_link_libraries(prototype_widgets PUBLIC SDL3::SDL3)

add_executable(tracewave_shell_prototype main.cpp renderer.cpp)
target_compile_features(tracewave_shell_prototype PRIVATE cxx_std_20)
set_target_properties(tracewave_shell_prototype PROPERTIES CXX_EXTENSIONS OFF)
target_include_directories(tracewave_shell_prototype SYSTEM PRIVATE
    "${prototype_bgfx_source}"
)
target_link_libraries(tracewave_shell_prototype PRIVATE prototype_widgets bgfx bx)

if(MSVC)
    target_compile_options(tracewave_shell_prototype PRIVATE /utf-8 /W4)
elseif(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(tracewave_shell_prototype PRIVATE -Wall -Wextra -Wpedantic)
endif()
if(MINGW)
    target_link_options(tracewave_shell_prototype PRIVATE -static)
endif()

include(CTest)
if(BUILD_TESTING)
    add_test(NAME prototype_window_smoke COMMAND tracewave_shell_prototype --smoke)
    set_tests_properties(prototype_window_smoke PROPERTIES TIMEOUT 40)
endif()
