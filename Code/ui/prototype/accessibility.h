#pragma once

#include <imgui.h>

#include <cstddef>
#include <memory>
#include <string>
#include <vector>

namespace accessibility
{
constexpr std::size_t noteCapacity = 256;

enum class Control
{
    root, menuBar, windowMenu, showBoard, showResult, focusNote, detachResult, detachNote, resetLayout,
    board, resetBoard, result, input, note, clearNote, reloadProject, saveProject, undoProject, moveLeft, moveRight, moveDown, moveUp, toggleModel, reloadModel, reloadResult
};

enum class Operation { focus, invoke, toggle, expand, collapse, setValue };

struct Action
{
    Control control;
    Operation operation;
    std::string value;
};

#if defined(_WIN32)
/** @brief SDL 창마다 ImGui 요소의 Windows UI Automation 트리를 게시한다. */
class Bridge
{
public:
    Bridge();
    ~Bridge();
    Bridge(const Bridge&) = delete;
    Bridge& operator=(const Bridge&) = delete;

    void item(Control control, Control parent, bool enabled = true, bool checked = false,
        const ImGuiViewport* viewport = nullptr);
    void panel(Control control);
    void publish(const char* value);
    std::vector<Action> takeActions();

private:
    struct State;
    std::unique_ptr<State> state;
};
#else
class Bridge
{
public:
    void item(Control, Control, bool = true, bool = false, const ImGuiViewport* = nullptr) {}
    void panel(Control) {}
    void publish(const char*) {}
    std::vector<Action> takeActions() { return {}; }
};
#endif
}
