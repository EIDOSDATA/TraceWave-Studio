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
    ui/wxwidgets/canvas_pcb_features.cpp
    ui/wxwidgets/canvas_viewport.cpp
    ui/wxwidgets/canvas_renderer.cpp
    ui/wxwidgets/editor_presentation.cpp
    ui/wxwidgets/coordinate_editor_dialog.cpp
    ui/wxwidgets/pcb_selection_model.cpp
    ui/wxwidgets/pcb_selection_model_data.cpp
    ui/wxwidgets/pcb_suggestion_model.cpp
    ui/wxwidgets/pcb_selection_dialog.cpp
    ui/wxwidgets/pcb_selection_view.cpp
    ui/wxwidgets/pcb_selection_layers.cpp
    ui/wxwidgets/pcb_selection_materials.cpp
    ui/wxwidgets/pcb_selection_suggestions.cpp
    ui/wxwidgets/pcb_selection_review.cpp
    ui/wxwidgets/studio_pcb.cpp
    ui/wxwidgets/studio_pcb_features.cpp
    ui/wxwidgets/studio_pcb_import.cpp
    ui/wxwidgets/pcb_import_dialog.cpp
    ui/wxwidgets/pcb_import_form.cpp
    ui/wxwidgets/pcb_import_transfer.cpp
    ui/wxwidgets/pcb_import_review.cpp
    ui/wxwidgets/pcb_import_model.cpp
    ui/wxwidgets/pcb_feature_model.cpp
    ui/wxwidgets/pcb_feature_form.cpp
    ui/wxwidgets/pcb_feature_scalar.cpp
    ui/wxwidgets/pcb_feature_lists.cpp
        ui/wxwidgets/pcb_feature_loops.cpp
    ui/wxwidgets/pcb_feature_list_dialog.cpp
    ui/wxwidgets/pcb_feature_dialog.cpp
    ui/wxwidgets/pcb_feature_review.cpp
        ui/wxwidgets/pcb_feature_modes.cpp
        ui/wxwidgets/pcb_cam_output_view.cpp
        ui/wxwidgets/pcb_cam_output_data.cpp
    ui/wxwidgets/reviewed_request_store.cpp
    ui/wxwidgets/studio_smoke_pcb.cpp
    ui/wxwidgets/studio_smoke_events.cpp
    ui/wxwidgets/studio_frame.cpp
    ui/wxwidgets/studio_layout.cpp
    ui/wxwidgets/studio_workspace.cpp
    ui/wxwidgets/studio_shell.cpp
    ui/wxwidgets/workspace_bar.cpp
    ui/wxwidgets/drawing_rail.cpp
    ui/wxwidgets/studio_theme.cpp
    ui/wxwidgets/studio_notebook.cpp
    ui/wxwidgets/network_chart.cpp
    ui/wxwidgets/result_presentation.cpp
    ui/wxwidgets/result_source_browser.cpp
    ui/wxwidgets/result_conditions_view.cpp
    ui/wxwidgets/result_network_view.cpp
    ui/wxwidgets/result_compare_view.cpp
    ui/wxwidgets/result_metrics_view.cpp
    ui/wxwidgets/result_radiation_canvas.cpp
    ui/wxwidgets/result_radiation_view.cpp
    ui/wxwidgets/field_slice_canvas.cpp
    ui/wxwidgets/field_result_view.cpp
    ui/wxwidgets/smith_chart.cpp
    ui/wxwidgets/smith_view.cpp
    ui/wxwidgets/result_workspace.cpp
    ui/wxwidgets/result_workspace_pinned.cpp
    ui/wxwidgets/result_workspace_compare.cpp
    ui/wxwidgets/result_workspace_measurement.cpp
    ui/wxwidgets/measurement_compare_view.cpp
    ui/wxwidgets/measurement_model.cpp
    ui/wxwidgets/measurement_record_form.cpp
    ui/wxwidgets/measurement_record_collections.cpp
    ui/wxwidgets/measurement_collection_dialog.cpp
    ui/wxwidgets/measurement_uncertainty_dialog.cpp
    ui/wxwidgets/measurement_processing_dialog.cpp
    ui/wxwidgets/measurement_record_dialog.cpp
    ui/wxwidgets/measurement_attachment_dialog.cpp
    ui/wxwidgets/measurement_history_dialog.cpp
    ui/wxwidgets/measurement_operation_dialog.cpp
    ui/wxwidgets/measurement_operation_form.cpp
    ui/wxwidgets/measurement_quantity_group.cpp
    ui/wxwidgets/studio_measurement.cpp
    ui/wxwidgets/studio_results.cpp
    ui/wxwidgets/rf_validation_model.cpp
    ui/wxwidgets/rf_validation_view.cpp
    ui/wxwidgets/rf_validation_details.cpp
    ui/wxwidgets/rf_validation_controller.cpp
    ui/wxwidgets/studio_rf_validation.cpp
    ui/wxwidgets/drawing_sheet_model.cpp
    ui/wxwidgets/drawing_sheet_canvas.cpp
    ui/wxwidgets/drawing_output_view.cpp
    ui/wxwidgets/drawing_output_detail.cpp
    ui/wxwidgets/step_output_view.cpp
    ui/wxwidgets/output_model.cpp
    ui/wxwidgets/output_conditions_view.cpp
    ui/wxwidgets/output_record_dialog.cpp
    ui/wxwidgets/output_workspace.cpp
    ui/wxwidgets/handoff_output_view.cpp
    ui/wxwidgets/handoff_output_controller.cpp
    ui/wxwidgets/output_pending_store.cpp
    ui/wxwidgets/output_controller.cpp
    ui/wxwidgets/output_controller_jobs.cpp
    ui/wxwidgets/studio_output.cpp
    ui/wxwidgets/studio_smoke_output.cpp
    ui/wxwidgets/studio_smoke_features.cpp
    ui/wxwidgets/studio_smoke_pcb_exchange.cpp
    ui/wxwidgets/studio_smoke_validation.cpp
    ui/wxwidgets/frequency_display.cpp
    ui/wxwidgets/frequency_assessment_display.cpp
    ui/wxwidgets/network_panel.cpp
    ui/wxwidgets/studio_network.cpp
    ui/wxwidgets/network_assessment_panel.cpp
    ui/wxwidgets/studio_network_assessment.cpp
    ui/wxwidgets/network_import_dialog.cpp
    ui/wxwidgets/network_import_form.cpp
    ui/wxwidgets/network_import_review.cpp
    ui/wxwidgets/network_import_measurement.cpp
    ui/wxwidgets/network_circuit_dialog.cpp
    ui/wxwidgets/network_circuit_view.cpp
    ui/wxwidgets/network_assessment_dialog.cpp
    ui/wxwidgets/network_transform_dialog.cpp
    ui/wxwidgets/network_source_dialog.cpp
    ui/wxwidgets/network_export.cpp
    ui/wxwidgets/studio_smoke_network.cpp
    ui/wxwidgets/studio_smoke_network_safety.cpp
    ui/wxwidgets/sweep_model.cpp
    ui/wxwidgets/sweep_result_model.cpp
    ui/wxwidgets/sweep_dialog.cpp
    ui/wxwidgets/sweep_form.cpp
    ui/wxwidgets/sweep_panel.cpp
    ui/wxwidgets/sweep_result_dialog.cpp
    ui/wxwidgets/sweep_selection_dialog.cpp
    ui/wxwidgets/sweep_selection_model.cpp
    ui/wxwidgets/sweep_selection_recovery.cpp
    ui/wxwidgets/studio_sweep_selection.cpp
    ui/wxwidgets/studio_sweep.cpp
    ui/wxwidgets/studio_sweep_dialogs.cpp
    ui/wxwidgets/studio_smoke_sweep.cpp
    ui/wxwidgets/studio_smoke_selection.cpp
    ui/wxwidgets/studio_smoke_results.cpp
    ui/wxwidgets/project_setup_dialog.cpp
    ui/wxwidgets/target_editor_dialog.cpp
    ui/wxwidgets/target_editor_view.cpp
    ui/wxwidgets/template_dialog.cpp
    ui/wxwidgets/template_view.cpp
    ui/wxwidgets/template_seed_view.cpp
    ui/wxwidgets/studio_design_setup.cpp
    ui/wxwidgets/design_rules_dialog.cpp
    ui/wxwidgets/design_rules_review.cpp
    ui/wxwidgets/physical_setup_dialog.cpp
    ui/wxwidgets/physical_setup_review.cpp
    ui/wxwidgets/studio_smoke_physical.cpp
    ui/wxwidgets/studio_smoke_rules.cpp
    ui/wxwidgets/studio_smoke_setup.cpp
    ui/wxwidgets/studio_smoke_precision_editor.cpp
    ui/wxwidgets/studio_smoke_precision_planar.cpp
    ui/wxwidgets/studio_smoke_targets.cpp
    ui/wxwidgets/studio_smoke_templates.cpp
    ui/wxwidgets/studio_smoke_printed.cpp
    ui/wxwidgets/studio_smoke_setup_safety.cpp
    ui/wxwidgets/study_report_dialog.cpp
    ui/wxwidgets/study_report_model.cpp
    ui/wxwidgets/project_study_dialog.cpp
    ui/wxwidgets/project_study_form.cpp
    ui/wxwidgets/project_study_model.cpp
    ui/wxwidgets/studio_study.cpp
    ui/wxwidgets/studio_smoke_study.cpp
    ui/wxwidgets/studio_geometry_dialogs.cpp
    ui/wxwidgets/studio_drawing.cpp
    ui/wxwidgets/studio_validation.cpp
    ui/wxwidgets/studio_cad.cpp
    ui/wxwidgets/studio_solver.cpp
    ui/wxwidgets/radiation_dialog.cpp
    ui/wxwidgets/studio_controls.cpp
    ui/wxwidgets/studio_session.cpp
    ui/wxwidgets/studio_project.cpp
    ui/wxwidgets/studio_navigation.cpp
    ui/wxwidgets/studio_object_tools.cpp
    ui/wxwidgets/studio_precision.cpp
    ui/wxwidgets/precision_dialog.cpp
    ui/wxwidgets/design_canvas_dimensions.cpp
    ui/wxwidgets/object_rename_dialog.cpp
    ui/wxwidgets/studio_editing.cpp
    ui/wxwidgets/studio_lifecycle.cpp
    ui/wxwidgets/studio_smoke_editor.cpp
    ui/wxwidgets/studio_smoke_canvas.cpp
    ui/wxwidgets/studio_smoke_precision.cpp
    ui/wxwidgets/studio_smoke_primitives.cpp
    ui/wxwidgets/studio_smoke_workers.cpp
    ui/wxwidgets/studio_smoke_report.cpp
    ui/wxwidgets/studio_support.cpp
    ui/wxwidgets/async_state.cpp
    ui/wxwidgets/analysis_workflow.cpp
    ui/wxwidgets/editor_panel.cpp
    ui/wxwidgets/design_canvas.cpp
    ui/wxwidgets/design_canvas_precision.cpp
    ui/wxwidgets/model_view.cpp
    ui/wxwidgets/service_client.cpp
    ${RFAD_RESOURCE}
)
target_include_directories(tracewave_gui PRIVATE "${RFAD_JSON_INCLUDE_DIR}")
target_compile_definitions(tracewave_gui PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(tracewave_gui PRIVATE ${RFAD_WX_LIBRARIES} ole32 opengl32 bcrypt)

add_executable(tracewave_canvas_benchmark tools/canvas_render_benchmark.cpp
    ui/wxwidgets/canvas_renderer.cpp ui/wxwidgets/canvas_scene.cpp ui/wxwidgets/canvas_pcb_features.cpp ui/wxwidgets/canvas_viewport.cpp)
target_include_directories(tracewave_canvas_benchmark PRIVATE ui/wxwidgets "${RFAD_JSON_INCLUDE_DIR}")
target_compile_definitions(tracewave_canvas_benchmark PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(tracewave_canvas_benchmark PRIVATE ${RFAD_WX_LIBRARIES} psapi)
set_target_properties(tracewave_canvas_benchmark PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/bin")
if(MSVC)
    target_compile_options(tracewave_gui PRIVATE "$<$<COMPILE_LANGUAGE:CXX>:/W4;/utf-8>")
else()
    target_compile_options(tracewave_gui PRIVATE "$<$<COMPILE_LANGUAGE:CXX>:-Wall;-Wextra;-Wpedantic;-finput-charset=UTF-8;-fexec-charset=UTF-8>")
endif()
set_target_properties(tracewave_gui PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/bin")

include(CTest)
if(BUILD_TESTING)
    add_executable(tracewave_project_study_tests tests/project_study_model_test.cpp ui/wxwidgets/project_study_model.cpp)
    target_include_directories(tracewave_project_study_tests PRIVATE ui/wxwidgets "${RFAD_JSON_INCLUDE_DIR}")
    set_target_properties(tracewave_project_study_tests PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/bin")
    if(MSVC)
        target_compile_options(tracewave_project_study_tests PRIVATE /W4 /utf-8)
    else()
        target_compile_options(tracewave_project_study_tests PRIVATE -Wall -Wextra -Wpedantic -finput-charset=UTF-8 -fexec-charset=UTF-8)
    endif()
    add_test(NAME project_study COMMAND tracewave_project_study_tests "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/pcb_power_balance_study.json" "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/pcb_radiation_convergence_study.json")
    add_executable(tracewave_study_report_tests tests/study_report_model_test.cpp ui/wxwidgets/study_report_model.cpp)
    target_include_directories(tracewave_study_report_tests PRIVATE ui/wxwidgets "${RFAD_JSON_INCLUDE_DIR}")
    set_target_properties(tracewave_study_report_tests PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/bin")
    if(MSVC)
        target_compile_options(tracewave_study_report_tests PRIVATE /W4 /utf-8)
    else()
        target_compile_options(tracewave_study_report_tests PRIVATE -Wall -Wextra -Wpedantic -finput-charset=UTF-8 -fexec-charset=UTF-8)
    endif()
    add_test(NAME study_report COMMAND tracewave_study_report_tests)
    add_executable(tracewave_radiation_pattern_tests tests/radiation_pattern_test.cpp)
    target_include_directories(tracewave_radiation_pattern_tests PRIVATE ui/wxwidgets "${RFAD_JSON_INCLUDE_DIR}")
    set_target_properties(tracewave_radiation_pattern_tests PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/bin")
    if(MSVC)
        target_compile_options(tracewave_radiation_pattern_tests PRIVATE /W4 /utf-8)
    else()
        target_compile_options(tracewave_radiation_pattern_tests PRIVATE -Wall -Wextra -Wpedantic -finput-charset=UTF-8 -fexec-charset=UTF-8)
    endif()
    add_test(NAME radiation_pattern COMMAND tracewave_radiation_pattern_tests)
    add_executable(tracewave_pcb_selection_tests tests/pcb_selection_model_test.cpp
        ui/wxwidgets/pcb_selection_model.cpp ui/wxwidgets/pcb_selection_model_data.cpp)
    target_include_directories(tracewave_pcb_selection_tests PRIVATE ui/wxwidgets "${RFAD_JSON_INCLUDE_DIR}")
    if(MSVC)
        target_compile_options(tracewave_pcb_selection_tests PRIVATE /W4 /utf-8)
    else()
        target_compile_options(tracewave_pcb_selection_tests PRIVATE -Wall -Wextra -Wpedantic -finput-charset=UTF-8 -fexec-charset=UTF-8)
    endif()
    set_target_properties(tracewave_pcb_selection_tests PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/bin")
    add_test(NAME pcb_selection COMMAND tracewave_pcb_selection_tests)
    add_executable(tracewave_pcb_suggestion_tests tests/pcb_suggestion_model_test.cpp
        ui/wxwidgets/pcb_suggestion_model.cpp ui/wxwidgets/pcb_selection_model_data.cpp)
    target_include_directories(tracewave_pcb_suggestion_tests PRIVATE ui/wxwidgets "${RFAD_JSON_INCLUDE_DIR}")
    if(MSVC)
        target_compile_options(tracewave_pcb_suggestion_tests PRIVATE /W4 /utf-8)
    else()
        target_compile_options(tracewave_pcb_suggestion_tests PRIVATE -Wall -Wextra -Wpedantic -finput-charset=UTF-8 -fexec-charset=UTF-8)
    endif()
    set_target_properties(tracewave_pcb_suggestion_tests PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/bin")
    add_test(NAME pcb_suggestions COMMAND tracewave_pcb_suggestion_tests)
    add_executable(tracewave_gui_presentation_tests tests/gui_presentation_test.cpp
        ui/wxwidgets/canvas_scene.cpp ui/wxwidgets/canvas_pcb_features.cpp ui/wxwidgets/canvas_viewport.cpp ui/wxwidgets/editor_presentation.cpp
        ui/wxwidgets/frequency_display.cpp ui/wxwidgets/frequency_assessment_display.cpp
        ui/wxwidgets/sweep_model.cpp ui/wxwidgets/sweep_result_model.cpp)
    target_include_directories(tracewave_gui_presentation_tests PRIVATE ui/wxwidgets "${RFAD_JSON_INCLUDE_DIR}")
    set_target_properties(tracewave_gui_presentation_tests PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/bin")
    add_test(NAME gui_presentation COMMAND tracewave_gui_presentation_tests)
    add_executable(tracewave_result_view_tests tests/result_view_model_test.cpp
        ui/wxwidgets/result_presentation.cpp ui/wxwidgets/frequency_display.cpp ui/wxwidgets/rf_validation_model.cpp
        ui/wxwidgets/sweep_selection_model.cpp)
    target_include_directories(tracewave_result_view_tests PRIVATE ui/wxwidgets "${RFAD_JSON_INCLUDE_DIR}")
    set_target_properties(tracewave_result_view_tests PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/bin")
    add_test(NAME result_view_model COMMAND tracewave_result_view_tests)
    add_executable(tracewave_output_model_tests tests/output_model_test.cpp
        ui/wxwidgets/drawing_sheet_model.cpp ui/wxwidgets/output_model.cpp)
    target_include_directories(tracewave_output_model_tests PRIVATE ui/wxwidgets "${RFAD_JSON_INCLUDE_DIR}")
    set_target_properties(tracewave_output_model_tests PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/bin")
    add_test(NAME output_model COMMAND tracewave_output_model_tests)
    add_executable(tracewave_pcb_feature_tests tests/pcb_feature_model_test.cpp
        ui/wxwidgets/pcb_feature_model.cpp ui/wxwidgets/pcb_import_model.cpp ui/wxwidgets/output_model.cpp
        ui/wxwidgets/canvas_scene.cpp ui/wxwidgets/canvas_pcb_features.cpp)
    target_include_directories(tracewave_pcb_feature_tests PRIVATE ui/wxwidgets "${RFAD_JSON_INCLUDE_DIR}")
    set_target_properties(tracewave_pcb_feature_tests PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/bin")
    add_test(NAME pcb_features COMMAND tracewave_pcb_feature_tests)
    add_executable(tracewave_network_export_tests tests/network_export_test.cpp
        ui/wxwidgets/network_export.cpp ui/wxwidgets/studio_support.cpp)
    target_include_directories(tracewave_network_export_tests PRIVATE ui/wxwidgets "${RFAD_JSON_INCLUDE_DIR}")
    target_compile_definitions(tracewave_network_export_tests PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
    target_link_libraries(tracewave_network_export_tests PRIVATE ${RFAD_WX_LIBRARIES} ole32 bcrypt)
    if(MSVC)
        target_compile_options(tracewave_network_export_tests PRIVATE /W4 /utf-8)
    else()
        target_compile_options(tracewave_network_export_tests PRIVATE -Wall -Wextra -Wpedantic -finput-charset=UTF-8 -fexec-charset=UTF-8)
    endif()
    set_target_properties(tracewave_network_export_tests PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/bin")
    add_test(NAME network_export COMMAND tracewave_network_export_tests)
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
