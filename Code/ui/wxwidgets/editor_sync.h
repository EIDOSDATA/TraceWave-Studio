/** @file @brief 편집 원본과 캔버스가 현재 프로젝트의 같은 개정을 가리키는지 검사한다. */
#pragma once
#include "studio_types.h"
#include <string>

namespace Studio
{
/** @brief 응답의 프로필과 프로젝트/개정 소유권이 모두 일치해야 속성을 편집할 수 있다. */
inline bool MatchesEditor(const Json& editor, const std::string& project, const std::string& revision)
{
    return !project.empty() && !revision.empty() && editor.is_object() &&
           editor.value("profile", Json(nullptr)) == "rfad.editor/0.1" &&
           editor.value("project_id", Json(nullptr)) == project &&
           editor.value("revision_id", Json(nullptr)) == revision;
}

/** @brief 오래된 다른 프로젝트의 형상을 같은 선택이나 편집 근거로 사용하지 않는다. */
inline bool MatchesCanvas(const Json& scene, const std::string& project, const std::string& revision)
{
    return !project.empty() && !revision.empty() && scene.is_object() &&
           scene.value("profile", Json(nullptr)) == "rfad.canvas/0.1" &&
           scene.value("project_id", Json(nullptr)) == project &&
           scene.value("revision_id", Json(nullptr)) == revision && scene.value("unit", Json(nullptr)) == "mm" &&
           scene.value("angle_unit", Json(nullptr)) == "deg";
}

/** @brief 두 조회 중 하나라도 실패하거나 이전 원본이면 편집을 잠근다. */
inline bool EditableProject(const Json& editor, const Json& scene, const std::string& project,
                            const std::string& revision)
{
    return MatchesEditor(editor, project, revision) && MatchesCanvas(scene, project, revision);
}
}
