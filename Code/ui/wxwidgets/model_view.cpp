#include "model_view.h"
#include "display_mesh_picking.h"
#include "display_mesh_preview.h"
#include "model_vertex_buffer.h"
#include "system_appearance.h"

#include <wx/glcanvas.h>
#include <wx/dcclient.h>
#include <GL/gl.h>

#include <chrono>
#include <cmath>
#include <future>
#include <set>
#include <utility>

namespace
{
using Scene = DisplayMesh::Scene;
using Camera = DisplayMesh::Camera;
constexpr int EmptyContextIdleMs = 120000;
constexpr double PreviewEnterPx = 0.65;
constexpr double PreviewLeavePx = 0.8;

wxString Text(const std::string& text)
{
    return wxString::FromUTF8(text.data(), text.size());
}

/** @brief UI thread에서만 GPU context와 표시 버퍼를 사용하는 작은 renderer다. */
class MeshCanvas final : public wxGLCanvas
{
public:
    explicit MeshCanvas(wxWindow* parent, const int* attributes)
        : wxGLCanvas(parent, wxID_ANY, attributes, wxDefaultPosition, wxDefaultSize, wxWANTS_CHARS),
          m_context(std::make_unique<wxGLContext>(this)), m_colours(StudioAppearance::CanvasColours::Read())
    {
        SetBackgroundStyle(wxBG_STYLE_PAINT);
        SetName(Text("3D 형상 보기"));
        SetToolTip(Text("방향키: 회전 / Shift+방향키: 이동 / +, -: 확대·축소 / F: 전체 보기"));
        Bind(wxEVT_PAINT, &MeshCanvas::Paint, this);
        Bind(wxEVT_SIZE, [this](wxSizeEvent& event)
        {
            Refresh(false);
            event.Skip();
        });
        Bind(wxEVT_LEFT_DOWN, &MeshCanvas::MouseDown, this);
        Bind(wxEVT_LEFT_UP, &MeshCanvas::MouseUp, this);
        Bind(wxEVT_MIDDLE_DOWN, &MeshCanvas::MouseDown, this);
        Bind(wxEVT_MIDDLE_UP, &MeshCanvas::MouseUp, this);
        Bind(wxEVT_MOTION, &MeshCanvas::Motion, this);
        Bind(wxEVT_MOUSE_CAPTURE_LOST, [this](wxMouseCaptureLostEvent&)
        {
            m_dragging = false;
        });
        Bind(wxEVT_MOUSEWHEEL, [this](wxMouseEvent& event)
        {
            if (event.GetWheelDelta() != 0)
            {
                m_camera.Zoom(static_cast<double>(event.GetWheelRotation()) / event.GetWheelDelta());
                Refresh(false);
            }
        });
        Bind(wxEVT_SYS_COLOUR_CHANGED, [this](wxSysColourChangedEvent& event)
        {
            m_colours = StudioAppearance::CanvasColours::Read();
            Refresh(false);
            event.Skip();
        });
        Bind(wxEVT_KEY_DOWN, [this](wxKeyEvent& event)
        {
            const auto key = event.GetKeyCode();
            if (key == 'F')
            {
                Fit();
            }
            else if (key == WXK_ESCAPE)
            {
                m_dragging = false;
                if (HasCapture())
                {
                    ReleaseMouse();
                }
            }
            else if (key == WXK_ADD || key == WXK_NUMPAD_ADD || key == '+' ||
                     key == WXK_SUBTRACT || key == WXK_NUMPAD_SUBTRACT || key == '-')
            {
                m_camera.Zoom(key == WXK_ADD || key == WXK_NUMPAD_ADD || key == '+' ? 1.0 : -1.0);
                Refresh(false);
            }
            else if (key == WXK_LEFT || key == WXK_RIGHT || key == WXK_UP || key == WXK_DOWN)
            {
                const double dx = key == WXK_LEFT ? -12.0 : key == WXK_RIGHT ? 12.0 : 0.0;
                const double dy = key == WXK_UP ? -12.0 : key == WXK_DOWN ? 12.0 : 0.0;
                if (event.ShiftDown())
                {
                    PanView(dx, dy);
                }
                else
                {
                    RotateView(dx, dy);
                }
            }
            else
            {
                event.Skip();
            }
        });
    }

    ~MeshCanvas() override
    {
        if (HasCapture())
        {
            ReleaseMouse();
        }
    }

    bool Ready() const
    {
        return m_context != nullptr && m_context->IsOK();
    }

    bool EnsureContext()
    {
        if (!Ready())
        {
            RecreateContext();
        }
        return Ready();
    }

    void SetScene(std::shared_ptr<const Scene> scene)
    {
        const bool changed = m_scene != scene;
        if (changed)
        {
            m_vertices.Invalidate();
            m_previewVertices.Invalidate();
            m_showingPreview = false;
        }
        m_scene = std::move(scene);
        if (changed && ((m_scene == nullptr && m_vertices.Bytes() != 0) || m_previewVertices.Bytes() != 0))
        {
            if (IsShownOnScreen() && Ready() && SetCurrent(*m_context))
            {
                if (m_scene == nullptr)
                {
                    m_vertices.Release();
                }
                m_previewVertices.Release();
            }
            else
            {
                DropContext();
            }
        }
        Refresh(false);
    }

    ModelView::Json VertexBufferDiagnostics() const
    {
        ModelView::Json state{{"bytes", m_vertices.Bytes()}, {"uploads", m_vertices.Uploads()}};
        if (m_previewVertices.Uploads() != 0)
        {
            state["preview_bytes"] = m_previewVertices.Bytes();
            state["preview_uploads"] = m_previewVertices.Uploads();
        }
        return state;
    }

    bool ShowingPreview() const
    {
        return m_showingPreview;
    }

    void Fit()
    {
        m_camera.zoom = 1.0;
        m_camera.panX = 0.0;
        m_camera.panY = 0.0;
        Refresh(false);
    }

    /** @brief 장면을 비운 뷰의 native context를 유휴 상태에서 반환한다. */
    void ReleaseWhenEmpty()
    {
        if (m_scene == nullptr)
        {
            DropContext();
        }
    }

    void RecreateContext()
    {
        DropContext();
        m_context = std::make_unique<wxGLContext>(this);
        Refresh(false);
    }

    void View(const std::string& view)
    {
        m_camera.yaw = view == "top" ? 0.0 : -35.0;
        m_camera.pitch = view == "top" ? 0.0 : 55.0;
        Refresh(false);
    }

    void RotateView(double dx, double dy)
    {
        m_camera.Rotate(dx, dy);
        Refresh(false);
    }

    void PanView(double dx, double dy)
    {
        if (m_scene == nullptr || !std::isfinite(dx) || !std::isfinite(dy))
        {
            return;
        }
        const double unit = 2.0 * m_camera.HalfHeight(m_scene->radius) / std::max(1, GetClientSize().y);
        const double limit = m_scene->radius * 100.0;
        m_camera.panX = std::clamp(m_camera.panX + dx * unit, -limit, limit);
        m_camera.panY = std::clamp(m_camera.panY - dy * unit, -limit, limit);
        Refresh(false);
    }

    void Selection(const std::string& identity)
    {
        m_selection = identity;
        Refresh(false);
    }

    void RelatedSelection(const std::vector<std::string>& identities)
    {
        m_relatedSelection = identities;
        Refresh(false);
    }

    void Layer(const std::string& identity, bool visible)
    {
        if (visible)
        {
            m_hiddenLayers.erase(identity);
        }
        else
        {
            m_hiddenLayers.insert(identity);
        }
        Refresh(false);
    }

    std::function<void()> onFrame;
    std::function<void(wxWindow&)> onDrawDisplayMarker;
    std::function<void(const std::string&)> onError;
    std::function<void(const std::string&)> onSelection;
    std::function<void(const std::vector<std::string>&)> onSelectionCandidates;
    std::function<void(const std::string&)> onHint;
    std::string renderer;
    std::uint64_t frames = 0;
    std::size_t submittedTriangles = 0;

private:
    /** @brief 숨겨진 뷰나 유실된 context에서도 파기와 함께 GPU 자원을 회수한다. */
    void DropContext()
    {
        m_context.reset();
        m_vertices.ContextDiscarded();
        m_previewVertices.ContextDiscarded();
        m_showingPreview = false;
        renderer.clear();
    }

    void Fail(const std::string& error)
    {
        if (onError)
        {
            onError(error);
        }
    }

    void Paint(wxPaintEvent&)
    {
        wxPaintDC paint(this);
        if (!IsShownOnScreen() || m_scene == nullptr)
        {
            return;
        }
        if (!Ready() || !SetCurrent(*m_context))
        {
            Fail("3D OpenGL context를 사용할 수 없습니다. 편집과 저장은 계속 사용할 수 있습니다.");
            return;
        }
        GLenum priorError = glGetError();
        for (int attempt = 0; priorError != GL_NO_ERROR && attempt < 8; ++attempt)
        {
            priorError = glGetError();
        }
        if (priorError != GL_NO_ERROR)
        {
            Fail("3D context 오류가 지속됩니다. 편집과 저장은 계속 사용할 수 있습니다.");
            return;
        }
        if (renderer.empty())
        {
            const auto* version = glGetString(GL_VERSION);
            const auto* device = glGetString(GL_RENDERER);
            renderer = std::string(version != nullptr ? reinterpret_cast<const char*>(version) : "unknown") + " / " +
                (device != nullptr ? reinterpret_cast<const char*>(device) : "unknown");
        }
        const wxSize size = GetClientSize();
        const double scale = GetContentScaleFactor();
        const int width = std::max(1, static_cast<int>(std::lround(size.x * scale)));
        const int height = std::max(1, static_cast<int>(std::lround(size.y * scale)));
        const double halfHeight = m_camera.HalfHeight(m_scene->radius);
        const double halfWidth = halfHeight * width / height;
        glViewport(0, 0, width, height);
        if (m_colours.HighContrast())
        {
            const auto& background = m_colours.background;
            glClearColor(background.Red() / 255.0f, background.Green() / 255.0f, background.Blue() / 255.0f, 1.0f);
        }
        else
        {
            glClearColor(0.92f, 0.945f, 0.965f, 1.0f);
        }
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glEnable(GL_DEPTH_TEST);
        glDepthFunc(GL_LEQUAL);
        glDisable(GL_CULL_FACE);
        glMatrixMode(GL_PROJECTION);
        glLoadIdentity();
        glOrtho(-halfWidth, halfWidth, -halfHeight, halfHeight, -m_scene->radius * 4.0, m_scene->radius * 4.0);
        glMatrixMode(GL_MODELVIEW);
        glLoadIdentity();
        const GLfloat light[] = {-0.3f, -0.5f, 1.0f, 0.0f};
        const GLfloat ambient[] = {0.45f, 0.45f, 0.45f, 1.0f};
        const GLfloat diffuse[] = {0.65f, 0.65f, 0.65f, 1.0f};
        glLightfv(GL_LIGHT0, GL_POSITION, light);
        glLightfv(GL_LIGHT0, GL_DIFFUSE, diffuse);
        glLightModelfv(GL_LIGHT_MODEL_AMBIENT, ambient);
        glLightModeli(GL_LIGHT_MODEL_TWO_SIDE, GL_TRUE);
        if (!m_colours.HighContrast())
        {
            glEnable(GL_LIGHTING);
        }
        glEnable(GL_LIGHT0);
        glEnable(GL_COLOR_MATERIAL);
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE);
        glTranslated(m_camera.panX, m_camera.panY, 0.0);
        glRotated(m_camera.pitch, 1.0, 0.0, 0.0);
        glRotated(m_camera.yaw, 0.0, 0.0, 1.0);
        const double unitsPerPixel = 2.0 * halfHeight / height;
        const double threshold = m_showingPreview ? PreviewLeavePx : PreviewEnterPx;
        m_showingPreview = m_scene->preview != nullptr && m_selection.empty() && m_relatedSelection.empty() && m_camera.zoom <= 0.5 &&
                           m_scene->preview->maximumDisplacement <= unitsPerPixel * threshold;
        const auto& drawingScene = m_showingPreview ? m_scene->preview->mesh : *m_scene;
        auto& vertices = m_showingPreview ? m_previewVertices : m_vertices;
        const bool buffered = vertices.Bind(drawingScene);
        submittedTriangles = 0;
        glEnableClientState(GL_VERTEX_ARRAY);
        glEnableClientState(GL_NORMAL_ARRAY);
        for (std::size_t index = 0; index < drawingScene.bodies.size(); ++index)
        {
            const auto& body = drawingScene.bodies[index];
            if (m_hiddenLayers.count(body.layer) != 0 ||
                !DisplayMesh::MayIntersectView(*m_scene, index, m_camera, halfWidth + unitsPerPixel, halfHeight + unitsPerPixel))
            {
                continue;
            }
            const bool selected = body.id == m_selection ||
                std::find(body.sources.begin(), body.sources.end(), m_selection) != body.sources.end() ||
                std::any_of(m_relatedSelection.begin(), m_relatedSelection.end(), [&body](const std::string& id)
                {
                    return std::find(body.sources.begin(), body.sources.end(), id) != body.sources.end();
                });
            if (m_colours.HighContrast())
            {
                const auto& color = selected ? m_colours.focus : m_colours.ink;
                glColor3ub(color.Red(), color.Green(), color.Blue());
            }
            else if (selected)
            {
                glColor3f(0.20f, 0.58f, 0.94f);
            }
            else if (body.role == "surface")
            {
                glColor3f(0.30f, 0.60f, 0.70f);
            }
            else if (body.role == "environment")
            {
                glColor3f(0.57f, 0.54f, 0.69f);
            }
            else if (body.role == "conductor")
            {
                glColor3f(0.88f, 0.60f, 0.22f);
            }
            else
            {
                glColor3f(0.25f, 0.55f, 0.39f);
            }
            if (buffered)
            {
                vertices.BodyPointers(index);
            }
            else
            {
                glVertexPointer(3, GL_FLOAT, 0, body.positions.data());
                glNormalPointer(GL_FLOAT, 0, body.normals.data());
            }
            glDrawArrays(GL_TRIANGLES, 0, static_cast<GLsizei>(body.positions.size() / 3));
            submittedTriangles += body.positions.size() / 9;
        }
        glDisableClientState(GL_NORMAL_ARRAY);
        glDisableClientState(GL_VERTEX_ARRAY);
        if (buffered)
        {
            vertices.Unbind();
        }
        glDisable(GL_LIGHTING);
        glDisable(GL_COLOR_MATERIAL);
        if (onDrawDisplayMarker)
        {
            onDrawDisplayMarker(*this);
        }
        const GLenum error = glGetError();
        if (error != GL_NO_ERROR || !SwapBuffers())
        {
            Fail("3D 화면 갱신에 실패했습니다. 이전 출력 파일과 편집 내용은 유지됩니다.");
            return;
        }
        ++frames;
        if (onFrame)
        {
            onFrame();
        }
    }

    void MouseDown(wxMouseEvent& event)
    {
        SetFocus();
        m_down = event.GetPosition();
        m_last = m_down;
        m_dragging = true;
        m_moved = false;
        m_panning = event.MiddleDown() || event.ShiftDown();
        if (!HasCapture())
        {
            CaptureMouse();
        }
    }

    void Motion(wxMouseEvent& event)
    {
        if (!m_dragging || m_scene == nullptr)
        {
            return;
        }
        const auto current = event.GetPosition();
        const int dx = current.x - m_last.x;
        const int dy = current.y - m_last.y;
        if (std::abs(current.x - m_down.x) + std::abs(current.y - m_down.y) > FromDIP(3))
        {
            m_moved = true;
        }
        if (m_moved)
        {
            if (m_panning)
            {
                PanView(dx, dy);
            }
            else
            {
                RotateView(dx, dy);
            }
        }
        m_last = current;
    }

    void MouseUp(wxMouseEvent& event)
    {
        if (!m_dragging)
        {
            return;
        }
        m_dragging = false;
        if (HasCapture())
        {
            ReleaseMouse();
        }
        if (!m_moved && !m_panning && m_scene != nullptr)
        {
            const wxSize size = GetClientSize();
            const double unit = 2.0 * m_camera.HalfHeight(m_scene->radius) / std::max(1, size.y);
            const int index = DisplayMesh::PickIndexed(*m_scene, m_camera,
                (event.GetX() - size.x / 2.0) * unit, (size.y / 2.0 - event.GetY()) * unit, m_hiddenLayers);
            if (index >= 0 && m_scene->bodies[static_cast<std::size_t>(index)].sources.size() > 1 && onSelectionCandidates)
            {
                onSelectionCandidates(m_scene->bodies[static_cast<std::size_t>(index)].sources);
                return;
            }
            m_selection = index >= 0 ? m_scene->bodies[static_cast<std::size_t>(index)].sources.front() : "";
            Refresh(false);
            if (onHint)
            {
                onHint("3D 기하 보기 | 드래그: 회전, Shift/가운데 드래그: 이동, 휠: 확대, F: 전체 보기");
            }
            if (onSelection)
            {
                onSelection(m_selection);
            }
        }
    }

public:
    /** @brief 실제 상면 카메라에서 보드 좌표를 합성 마우스 입력으로 바꾼다. */
    bool ClickTopPoint(double x, double y)
    {
        if (!m_scene || !IsShownOnScreen() || m_camera.pitch != 0.0 || m_camera.yaw != 0.0)
        {
            return false;
        }
        const wxSize size = GetClientSize();
        const double unit = 2.0 * m_camera.HalfHeight(m_scene->radius) / std::max(1, size.y);
        const wxPoint pixel(static_cast<int>(std::lround((x - m_scene->center.x + m_camera.panX) / unit + size.x / 2.0)),
                            static_cast<int>(std::lround(size.y / 2.0 - (y - m_scene->center.y + m_camera.panY) / unit)));
        if (!GetClientRect().Contains(pixel))
        {
            return false;
        }
        wxMouseEvent down(wxEVT_LEFT_DOWN);
        down.SetEventObject(this);
        down.SetPosition(pixel);
        down.SetLeftDown(true);
        GetEventHandler()->ProcessEvent(down);
        wxMouseEvent up(wxEVT_LEFT_UP);
        up.SetEventObject(this);
        up.SetPosition(pixel);
        GetEventHandler()->ProcessEvent(up);
        return true;
    }

private:
    std::unique_ptr<wxGLContext> m_context;
    ModelVertexBuffer m_vertices;
    ModelVertexBuffer m_previewVertices;
    std::shared_ptr<const Scene> m_scene;
    Camera m_camera;
    std::set<std::string> m_hiddenLayers;
    std::string m_selection;
    std::vector<std::string> m_relatedSelection;
    wxPoint m_down;
    wxPoint m_last;
    bool m_dragging = false;
    bool m_moved = false;
    bool m_panning = false;
    bool m_showingPreview = false;
    StudioAppearance::CanvasColours m_colours;
};
}

/** @brief 파일 작업과 UI 소유 context의 수명을 분리한다. */
struct ModelView::Impl
{
    ModelView* owner;
    wxTimer timer;
    wxTimer idleTimer;
    wxStaticText* message = nullptr;
    MeshCanvas* canvas = nullptr;
    std::future<Scene> pendingLoad;
    std::shared_ptr<std::atomic<bool>> cancelled;
    std::shared_ptr<const Scene> scene;
    std::shared_ptr<const Scene> candidate;
    std::string error;
    std::string selection;
    std::vector<std::string> relatedSelection;
    bool suppressPrimary = false;
    std::set<std::string> hiddenLayers;
    bool discard = false;
    bool recovering = false;
    bool keepContextForMeasurement = false;
    bool reportedPreview = false;

    explicit Impl(ModelView* window) : owner(window), timer(window), idleTimer(window)
    {
        auto* sizer = new wxBoxSizer(wxVERTICAL);
        message = new wxStaticText(window, wxID_ANY, Text("3D 형상을 생성하면 여기에 표시합니다. 물성/해석 결과와 구분되는 기하 보기입니다."));
        message->Wrap(window->FromDIP(500));
        sizer->Add(message, 0, wxEXPAND | wxALL, window->FromDIP(8));
        window->SetSizer(sizer);
        window->Bind(wxEVT_TIMER, [this](wxTimerEvent&)
        {
            Poll();
        }, timer.GetId());
        window->Bind(wxEVT_TIMER, [this](wxTimerEvent&)
        {
            if (canvas != nullptr && scene == nullptr && candidate == nullptr)
            {
                canvas->ReleaseWhenEmpty();
            }
        }, idleTimer.GetId());
    }

    ~Impl()
    {
        timer.Stop();
        idleTimer.Stop();
        if (cancelled != nullptr)
        {
            cancelled->store(true);
        }
        if (pendingLoad.valid())
        {
            pendingLoad.wait();
        }
        if (canvas != nullptr)
        {
            canvas->onFrame = nullptr;
            canvas->onDrawDisplayMarker = nullptr;
            canvas->onError = nullptr;
            canvas->onSelection = nullptr;
            canvas->onSelectionCandidates = nullptr;
            canvas->onHint = nullptr;
        }
    }

    void Status(const std::string& text)
    {
        message->SetLabel(Text(text));
        message->Show(scene == nullptr || !error.empty());
        owner->Layout();
        if (owner->onStatus)
        {
            owner->onStatus(text);
        }
    }

    void Failure(const std::string& text)
    {
        error = text;
        recovering = false;
        candidate.reset();
        if (canvas != nullptr)
        {
            canvas->SetScene(scene);
        }
        Status(text);
        if (scene == nullptr && canvas != nullptr && !keepContextForMeasurement)
        {
            idleTimer.StartOnce(EmptyContextIdleMs);
        }
    }

    bool EnsureCanvas()
    {
        if (canvas != nullptr)
        {
            return canvas->EnsureContext();
        }
        const int attributes[] = {WX_GL_RGBA, WX_GL_DOUBLEBUFFER, WX_GL_DEPTH_SIZE, 24, 0};
        if (!wxGLCanvas::IsDisplaySupported(attributes))
        {
            return false;
        }
        canvas = new MeshCanvas(owner, attributes);
        if (!canvas->Ready())
        {
            canvas->Destroy();
            canvas = nullptr;
            return false;
        }
        owner->GetSizer()->Add(canvas, 1, wxEXPAND);
        canvas->onDrawDisplayMarker = owner->onDrawDisplayMarker;
        for (const auto& layer : hiddenLayers)
        {
            canvas->Layer(layer, false);
        }
        canvas->onError = [this](const std::string& text)
        {
            if (error != text || candidate != nullptr)
            {
                Failure(text);
            }
        };
        canvas->onFrame = [this]()
        {
            if (reportedPreview != canvas->ShowingPreview())
            {
                reportedPreview = canvas->ShowingPreview();
                if (scene != nullptr && owner->onStatus)
                {
                    owner->onStatus(reportedPreview ? "저해상도 표시 | 확대하거나 객체를 선택하면 원본 표시로 돌아옵니다."
                                                    : "원본 해상도 표시 | 드래그로 회전, 휠로 확대");
                }
            }
            if (candidate != nullptr)
            {
                scene = std::move(candidate);
                error.clear();
                recovering = false;
                Status("3D 기하 보기 | " + std::to_string(scene->triangles) +
                    " 삼각형 | 드래그: 회전, Shift/가운데 드래그: 이동, 휠: 확대, F: 전체 보기");
            }
            else if (scene != nullptr && recovering)
            {
                error.clear();
                recovering = false;
                Status("이전의 검증된 3D 표시 형상을 다시 표시했습니다.");
            }
        };
        canvas->onSelection = [this](const std::string& identity)
        {
            selection = identity;
            if (owner->onSelection)
            {
                owner->onSelection(identity);
            }
        };
        canvas->onSelectionCandidates = [this](const std::vector<std::string>& sources)
        {
            if (owner->onSelectionCandidates)
            {
                owner->onSelectionCandidates(sources);
            }
        };
        canvas->onHint = [this](const std::string& text)
        {
            if (owner->onStatus)
            {
                owner->onStatus(text);
            }
        };
        owner->Layout();
        return true;
    }

    void Poll()
    {
        if (!pendingLoad.valid() || pendingLoad.wait_for(std::chrono::seconds(0)) != std::future_status::ready)
        {
            return;
        }
        timer.Stop();
        try
        {
            auto loaded = pendingLoad.get();
            if (discard)
            {
                return;
            }
            if (!EnsureCanvas())
            {
                Failure("OpenGL 3D 화면을 만들 수 없습니다. STEP 출력과 편집/저장은 계속 사용할 수 있습니다.");
                return;
            }
            candidate = std::make_shared<Scene>(std::move(loaded));
            canvas->Show();
            canvas->SetScene(candidate);
            canvas->Selection(suppressPrimary ? std::string() : selection);
            canvas->RelatedSelection(relatedSelection);
            canvas->Fit();
            Status("3D 표시 파일 검증 완료. 첫 화면을 준비하고 있습니다.");
        }
        catch (const std::exception& exception)
        {
            if (!discard)
            {
                Failure(exception.what());
            }
        }
    }
};

ModelView::ModelView(wxWindow* parent) : wxPanel(parent), m_impl(std::make_unique<Impl>(this))
{
}

ModelView::~ModelView() = default;

bool ModelView::ClickTopPointForSmoke(double x, double y)
{
    return m_impl->canvas && m_impl->canvas->ClickTopPoint(x, y);
}

void ModelView::SetDisplayMarker(std::function<void(wxWindow&)> marker)
{
    onDrawDisplayMarker = std::move(marker);
    if (m_impl->canvas != nullptr)
    {
        m_impl->canvas->onDrawDisplayMarker = onDrawDisplayMarker;
        m_impl->canvas->Refresh(false);
    }
}

bool ModelView::LoadArtifact(const wxString& workspace, const Json& artifact, const Json& snapshot, const std::string& runId)
{
    if (IsLoading())
    {
        return false;
    }
    m_impl->idleTimer.Stop();
    m_impl->discard = false;
    m_impl->recovering = false;
    m_impl->error.clear();
    m_impl->cancelled = std::make_shared<std::atomic<bool>>(false);
    const auto cancelled = m_impl->cancelled;
    const std::filesystem::path root(workspace.ToStdWstring());
    try
    {
        m_impl->pendingLoad = std::async(std::launch::async, [root, artifact, snapshot, runId, cancelled]()
        {
            auto scene = DisplayMesh::Load(root, artifact, snapshot, runId, cancelled.get());
            try
            {
                DisplayMesh::BuildPickIndex(scene, cancelled.get());
            }
            catch (const std::bad_alloc&)
            {
                /** @brief 할당할 수 없으면 검증을 마친 장면의 기존 선택 경로를 사용한다. */
                scene.pickIndex.reset();
            }
            try
            {
                scene.preview = DisplayMesh::BuildPreview(scene, cancelled.get());
            }
            catch (const std::bad_alloc&)
            {
                /** @brief 미리보기의 예산을 확보할 수 없으면 원본 표시를 유지한다. */
            }
            return scene;
        });
    }
    catch (const std::exception& exception)
    {
        m_impl->Failure(exception.what());
        return false;
    }
    m_impl->Status("3D 표시 파일을 읽고 SHA256과 객체 대응을 확인하고 있습니다.");
    m_impl->timer.Start(30);
    return true;
}

void ModelView::Clear()
{
    if (m_impl->cancelled != nullptr)
    {
        m_impl->cancelled->store(true);
    }
    m_impl->discard = true;
    m_impl->recovering = false;
    m_impl->candidate.reset();
    m_impl->scene.reset();
    m_impl->selection.clear();
    m_impl->relatedSelection.clear();
    if (m_impl->canvas != nullptr)
    {
        for (const auto& layer : m_impl->hiddenLayers)
        {
            m_impl->canvas->Layer(layer, true);
        }
    }
    m_impl->hiddenLayers.clear();
    m_impl->error.clear();
    if (m_impl->canvas != nullptr)
    {
        m_impl->canvas->SetScene(nullptr);
        m_impl->canvas->Hide();
        if (!m_impl->keepContextForMeasurement)
        {
            m_impl->idleTimer.StartOnce(EmptyContextIdleMs);
        }
    }
    m_impl->Status("3D 형상을 생성하면 여기에 표시합니다.");
}

void ModelView::KeepContextForMeasurement()
{
    m_impl->keepContextForMeasurement = true;
    m_impl->idleTimer.Stop();
}

void ModelView::SetSelection(const std::string& identity)
{
    m_impl->selection = identity;
    if (m_impl->canvas != nullptr)
    {
        m_impl->canvas->Selection(m_impl->suppressPrimary ? std::string() : identity);
    }
}

void ModelView::SetRelatedSelection(const std::vector<std::string>& identities, bool suppressPrimary)
{
    if (m_impl->suppressPrimary != suppressPrimary)
    {
        m_impl->suppressPrimary = suppressPrimary;
        if (m_impl->canvas != nullptr)
        {
            m_impl->canvas->Selection(suppressPrimary ? std::string() : m_impl->selection);
        }
    }
    if (m_impl->relatedSelection != identities)
    {
        m_impl->relatedSelection = identities;
        if (m_impl->canvas != nullptr)
        {
            m_impl->canvas->RelatedSelection(identities);
        }
    }
}

void ModelView::SetLayerVisible(const std::string& identity, bool visible)
{
    if (visible)
    {
        m_impl->hiddenLayers.erase(identity);
    }
    else
    {
        m_impl->hiddenLayers.insert(identity);
    }
    if (m_impl->canvas != nullptr)
    {
        m_impl->canvas->Layer(identity, visible);
    }
}

void ModelView::FitView()
{
    if (m_impl->canvas != nullptr)
    {
        if (!m_impl->error.empty())
        {
            m_impl->recovering = true;
            m_impl->canvas->RecreateContext();
        }
        m_impl->canvas->Fit();
    }
}

void ModelView::SetView(const std::string& view)
{
    if (m_impl->canvas != nullptr)
    {
        m_impl->canvas->View(view);
    }
}

void ModelView::RotateView(double dx, double dy)
{
    if (m_impl->canvas != nullptr)
    {
        m_impl->canvas->RotateView(dx, dy);
    }
}

void ModelView::PanView(double dx, double dy)
{
    if (m_impl->canvas != nullptr)
    {
        m_impl->canvas->PanView(dx, dy);
    }
}

bool ModelView::HasMesh() const
{
    return m_impl->scene != nullptr;
}

bool ModelView::IsLoading() const
{
    return m_impl->pendingLoad.valid() || m_impl->candidate != nullptr;
}

std::string ModelView::Error() const
{
    return m_impl->error;
}

std::string ModelView::LoadedSnapshotId() const
{
    return HasMesh() ? m_impl->scene->snapshotId : "";
}

std::string ModelView::Selection() const
{
    return m_impl->selection;
}

std::string ModelView::RendererDescription() const
{
    return m_impl->canvas != nullptr ? m_impl->canvas->renderer : "";
}

ModelView::Json ModelView::VertexBufferDiagnostics() const
{
    return m_impl->canvas != nullptr ? m_impl->canvas->VertexBufferDiagnostics() : Json{{"bytes", 0}, {"uploads", 0}};
}

std::size_t ModelView::SubmittedTriangleCount() const
{
    return HasMesh() && m_impl->canvas != nullptr ? m_impl->canvas->submittedTriangles : 0;
}

std::size_t ModelView::TriangleCount() const
{
    return HasMesh() ? m_impl->scene->triangles : 0;
}

std::string ModelView::SourceRole(const std::string& id) const
{
    if (m_impl->scene != nullptr)
    {
        for (const auto& body : m_impl->scene->bodies)
        {
            if (std::find(body.sources.begin(), body.sources.end(), id) != body.sources.end())
            {
                return body.role;
            }
        }
    }
    return {};
}

std::size_t ModelView::BodyCount() const
{
    return HasMesh() ? m_impl->scene->bodies.size() : 0;
}

std::uint64_t ModelView::RenderedFrameCount() const
{
    return m_impl->canvas != nullptr ? m_impl->canvas->frames : 0;
}
