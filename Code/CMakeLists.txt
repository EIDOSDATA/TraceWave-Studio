cmake_minimum_required(VERSION 3.24)
project(TraceWaveStudio LANGUAGES CXX C)

if(NOT WIN32)
    message(FATAL_ERROR "This initial wxMSW GUI profile requires Windows; Linux GUI is a later profile.")
endif()
enable_language(RC)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(RFAD_WX_SOURCE_DIR "" CACHE PATH "Verified wxWidgets source directory")
set(RFAD_JSON_INCLUDE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/.local/deps/json-3.12.0" CACHE PATH "Directory containing nlohmann/json.hpp")

if(NOT EXISTS "${RFAD_JSON_INCLUDE_DIR}/nlohmann/json.hpp")
    message(FATAL_ERROR "Set RFAD_JSON_INCLUDE_DIR to the verified nlohmann single-header include directory")
endif()

if(RFAD_WX_SOURCE_DIR)
    set(wxBUILD_SHARED OFF CACHE BOOL "" FORCE)
    set(wxBUILD_SAMPLES OFF CACHE BOOL "" FORCE)
    set(wxBUILD_DEMOS OFF CACHE BOOL "" FORCE)
    set(wxBUILD_TESTS OFF CACHE BOOL "" FORCE)
    set(wxBUILD_PRECOMP OFF CACHE BOOL "" FORCE)
    set(wxUSE_WEBVIEW OFF CACHE BOOL "" FORCE)
    set(wxUSE_MEDIACTRL OFF CACHE BOOL "" FORCE)
    set(wxUSE_OPENGL ON CACHE BOOL "" FORCE)
    set(wxUSE_STC OFF CACHE BOOL "" FORCE)
    set(wxUSE_RIBBON OFF CACHE BOOL "" FORCE)
    add_subdirectory("${RFAD_WX_SOURCE_DIR}" "${CMAKE_CURRENT_BINARY_DIR}/wxwidgets" EXCLUDE_FROM_ALL)
    set(RFAD_WX_LIBRARIES wx::aui wx::gl wx::core wx::base)
else()
    find_package(wxWidgets 3.2 REQUIRED COMPONENTS aui gl core base)
    include(${wxWidgets_USE_FILE})
    set(RFAD_WX_LIBRARIES ${wxWidgets_LIBRARIES})
endif()

if(MINGW)
    find_path(RFAD_WX_RESOURCE_INCLUDE wx/msw/wx.rc
        HINTS "${RFAD_WX_SOURCE_DIR}/include" ${wxWidgets_INCLUDE_DIRS} REQUIRED NO_CACHE)
    set(RFAD_RESOURCE "${CMAKE_CURRENT_BINARY_DIR}/app-resource.obj")
    # @brief windres의 공백 include 경로 재해석을 피하도록 원본 include 폴더에서 실행한다.
    add_custom_command(OUTPUT "${RFAD_RESOURCE}"
        COMMAND "${CMAKE_RC_COMPILER}" -O coff -I .
            "${CMAKE_CURRENT_SOURCE_DIR}/ui/wxwidgets/app.rc" "${RFAD_RESOURCE}"
        WORKING_DIRECTORY "${RFAD_WX_RESOURCE_INCLUDE}"
        DEPENDS ui/wxwidgets/app.rc
            "${RFAD_WX_RESOURCE_INCLUDE}/wx/msw/wx.rc"
            "${RFAD_WX_RESOURCE_INCLUDE}/wx/msw/wx_dpi_aware_pmv2.manifest"
        VERBATIM)
    set_source_files_properties("${RFAD_RESOURCE}" PROPERTIES EXTERNAL_OBJECT TRUE GENERATED TRUE)
else()
    set(RFAD_RESOURCE ui/wxwidgets/app.rc)
endif()

add_executable(tracewave_gui WIN32
    ui/wxwidgets/main.cpp
    ui/wxwidgets/canvas_scene.cpp
    ui/wxwidgets/canvas_viewport.cpp
    ui/wxwidgets/canvas_renderer.cpp
    ui/wxwidgets/editor_presentation.cpp
    ui/wxwidgets/coordinate_editor_dialog.cpp
    ui/wxwidgets/studio_smoke_events.cpp
    ui/wxwidgets/studio_frame.cpp
    ui/wxwidgets/studio_layout.cpp
    ui/wxwidgets/studio_geometry_dialogs.cpp
    ui/wxwidgets/studio_drawing.cpp
    ui/wxwidgets/studio_validation.cpp
    ui/wxwidgets/studio_cad.cpp
    ui/wxwidgets/studio_solver.cpp
    ui/wxwidgets/studio_controls.cpp
    ui/wxwidgets/studio_session.cpp
    ui/wxwidgets/studio_project.cpp
    ui/wxwidgets/studio_editing.cpp
    ui/wxwidgets/studio_lifecycle.cpp
    ui/wxwidgets/studio_smoke_editor.cpp
    ui/wxwidgets/studio_smoke_canvas.cpp
    ui/wxwidgets/studio_smoke_primitives.cpp
    ui/wxwidgets/studio_smoke_workers.cpp
    ui/wxwidgets/studio_smoke_report.cpp
    ui/wxwidgets/studio_support.cpp
    ui/wxwidgets/async_state.cpp
    ui/wxwidgets/analysis_workflow.cpp
    ui/wxwidgets/editor_panel.cpp
    ui/wxwidgets/design_canvas.cpp
    ui/wxwidgets/model_view.cpp
    ui/wxwidgets/service_client.cpp
    ${RFAD_RESOURCE}
)
target_include_directories(tracewave_gui PRIVATE "${RFAD_JSON_INCLUDE_DIR}")
target_compile_definitions(tracewave_gui PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(tracewave_gui PRIVATE ${RFAD_WX_LIBRARIES} ole32 opengl32 bcrypt)
if(MSVC)
    target_compile_options(tracewave_gui PRIVATE "$<$<COMPILE_LANGUAGE:CXX>:/W4;/utf-8>")
else()
    target_compile_options(tracewave_gui PRIVATE "$<$<COMPILE_LANGUAGE:CXX>:-Wall;-Wextra;-Wpedantic;-finput-charset=UTF-8;-fexec-charset=UTF-8>")
endif()
set_target_properties(tracewave_gui PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/bin")

include(CTest)
if(BUILD_TESTING)
    add_executable(tracewave_gui_presentation_tests tests/gui_presentation_test.cpp
        ui/wxwidgets/canvas_scene.cpp ui/wxwidgets/canvas_viewport.cpp ui/wxwidgets/editor_presentation.cpp)
    target_include_directories(tracewave_gui_presentation_tests PRIVATE ui/wxwidgets "${RFAD_JSON_INCLUDE_DIR}")
    set_target_properties(tracewave_gui_presentation_tests PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/bin")
    add_test(NAME gui_presentation COMMAND tracewave_gui_presentation_tests)
    add_executable(tracewave_gui_state_tests tests/gui_state_test.cpp
        ui/wxwidgets/async_state.cpp ui/wxwidgets/analysis_workflow.cpp)
    target_include_directories(tracewave_gui_state_tests PRIVATE "${RFAD_JSON_INCLUDE_DIR}")
    set_target_properties(tracewave_gui_state_tests PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/bin")
    add_test(NAME gui_state COMMAND tracewave_gui_state_tests)
    add_executable(tracewave_canvas_geometry_tests tests/canvas_geometry_test.cpp)
    target_include_directories(tracewave_canvas_geometry_tests PRIVATE ui/wxwidgets "${RFAD_JSON_INCLUDE_DIR}")
    set_target_properties(tracewave_canvas_geometry_tests PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/bin")
    add_test(NAME canvas_geometry COMMAND tracewave_canvas_geometry_tests)
    add_executable(tracewave_display_mesh_tests tests/display_mesh_test.cpp)
    target_include_directories(tracewave_display_mesh_tests PRIVATE ui/wxwidgets "${RFAD_JSON_INCLUDE_DIR}")
    target_compile_definitions(tracewave_display_mesh_tests PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
    target_link_libraries(tracewave_display_mesh_tests PRIVATE bcrypt)
    if(MSVC)
        target_compile_options(tracewave_display_mesh_tests PRIVATE /W4 /utf-8)
    else()
        target_compile_options(tracewave_display_mesh_tests PRIVATE -Wall -Wextra -Wpedantic -finput-charset=UTF-8 -fexec-charset=UTF-8)
    endif()
    set_target_properties(tracewave_display_mesh_tests PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/bin")
    add_test(NAME display_mesh COMMAND tracewave_display_mesh_tests)
endif()
