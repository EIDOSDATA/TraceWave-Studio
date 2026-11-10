#include "model_view.h"
#include "display_mesh.h"

#include <wx/glcanvas.h>
#include <wx/dcclient.h>
#include <GL/gl.h>

#include <chrono>
#include <future>
#include <set>
#include <utility>

namespace
{
using Scene = DisplayMesh::Scene;
using Camera = DisplayMesh::Camera;

wxString Text(const std::string& text)
{
    return wxString::FromUTF8(text.data(), text.size());
}

/** @brief UI thread에서만 GPU context와 표시 버퍼를 사용하는 작은 renderer다. */
class MeshCanvas final : public wxGLCanvas
{
public:
    explicit MeshCanvas(wxWindow* parent, const int* attributes)
        : wxGLCanvas(parent, wxID_ANY, attributes), m_context(std::make_unique<wxGLContext>(this))
    {
        SetBackgroundStyle(wxBG_STYLE_PAINT);
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
        Bind(wxEVT_KEY_DOWN, [this](wxKeyEvent& event)
        {
            if (event.GetKeyCode() == 'F')
            {
                Fit();
            }
            else if (event.GetKeyCode() == WXK_ESCAPE)
            {
                m_dragging = false;
                if (HasCapture())
                {
                    ReleaseMouse();
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

    void SetScene(std::shared_ptr<const Scene> scene)
    {
        m_scene = std::move(scene);
        Refresh(false);
    }

    void Fit()
    {
        m_camera.zoom = 1.0;
        m_camera.panX = 0.0;
        m_camera.panY = 0.0;
        Refresh(false);
    }

    void RecreateContext()
    {
        m_context = std::make_unique<wxGLContext>(this);
        renderer.clear();
        Refresh(false);
    }

    void View(const std::string& view)
    {
        m_camera.yaw = view == "top" ? 0.0 : -35.0;
        m_camera.pitch = view == "top" ? 0.0 : 55.0;
        Refresh(false);
    }

    void Selection(const std::string& identity)
    {
        m_selection = identity;
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
    std::function<void(const std::string&)> onError;
    std::function<void(const std::string&)> onSelection;
    std::function<void(const std::string&)> onHint;
    std::string renderer;
    std::uint64_t frames = 0;

private:
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
        glClearColor(0.92f, 0.945f, 0.965f, 1.0f);
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
        glEnable(GL_LIGHTING);
        glEnable(GL_LIGHT0);
        glEnable(GL_COLOR_MATERIAL);
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE);
        glTranslated(m_camera.panX, m_camera.panY, 0.0);
        glRotated(m_camera.pitch, 1.0, 0.0, 0.0);
        glRotated(m_camera.yaw, 0.0, 0.0, 1.0);
        glEnableClientState(GL_VERTEX_ARRAY);
        glEnableClientState(GL_NORMAL_ARRAY);
        for (const auto& body : m_scene->bodies)
        {
            if (m_hiddenLayers.count(body.layer) != 0)
            {
                continue;
            }
            const bool selected = body.id == m_selection ||
                std::find(body.sources.begin(), body.sources.end(), m_selection) != body.sources.end();
            if (selected)
            {
                glColor3f(0.20f, 0.58f, 0.94f);
            }
            else if (body.role == "conductor")
            {
                glColor3f(0.88f, 0.60f, 0.22f);
            }
            else
            {
                glColor3f(0.25f, 0.55f, 0.39f);
            }
            glVertexPointer(3, GL_FLOAT, 0, body.positions.data());
            glNormalPointer(GL_FLOAT, 0, body.normals.data());
            glDrawArrays(GL_TRIANGLES, 0, static_cast<GLsizei>(body.positions.size() / 3));
        }
        glDisableClientState(GL_NORMAL_ARRAY);
        glDisableClientState(GL_VERTEX_ARRAY);
        glDisable(GL_LIGHTING);
        glDisable(GL_COLOR_MATERIAL);
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
                const double unit = 2.0 * m_camera.HalfHeight(m_scene->radius) / std::max(1, GetClientSize().y);
                const double limit = m_scene->radius * 100.0;
                m_camera.panX = std::clamp(m_camera.panX + dx * unit, -limit, limit);
                m_camera.panY = std::clamp(m_camera.panY - dy * unit, -limit, limit);
            }
            else
            {
                m_camera.Rotate(dx, dy);
            }
            Refresh(false);
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
            const int index = DisplayMesh::Pick(*m_scene, m_camera,
                (event.GetX() - size.x / 2.0) * unit, (size.y / 2.0 - event.GetY()) * unit, m_hiddenLayers);
            m_selection = index >= 0 ? m_scene->bodies[static_cast<std::size_t>(index)].sources.front() : "";
            Refresh(false);
            if (onSelection)
            {
                onSelection(m_selection);
            }
            if (onHint)
            {
                const auto* body = index >= 0 ? &m_scene->bodies[static_cast<std::size_t>(index)] : nullptr;
                if (body != nullptr && body->role == "conductor" && body->sources.size() > 1)
                {
                    onHint("여러 패턴이 합쳐진 형상입니다. 대표 패턴의 속성을 표시합니다. 개별 패턴은 왼쪽 목록에서 선택하세요.");
                }
                else
                {
                    onHint("3D 기하 보기 | 드래그: 회전, Shift/가운데 드래그: 이동, 휠: 확대, F: 전체 보기");
                }
            }
        }
    }

    std::unique_ptr<wxGLContext> m_context;
    std::shared_ptr<const Scene> m_scene;
    Camera m_camera;
    std::set<std::string> m_hiddenLayers;
    std::string m_selection;
    wxPoint m_down;
    wxPoint m_last;
    bool m_dragging = false;
    bool m_moved = false;
    bool m_panning = false;
};
}

/** @brief 파일 작업과 UI 소유 context의 수명을 분리한다. */
struct ModelView::Impl
{
    ModelView* owner;
    wxTimer timer;
    wxStaticText* message = nullptr;
    MeshCanvas* canvas = nullptr;
    std::future<Scene> pendingLoad;
    std::shared_ptr<std::atomic<bool>> cancelled;
    std::shared_ptr<const Scene> scene;
    std::shared_ptr<const Scene> candidate;
    std::string error;
    std::string selection;
    std::set<std::string> hiddenLayers;
    bool discard = false;
    bool recovering = false;

    explicit Impl(ModelView* window) : owner(window), timer(window)
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
    }

    ~Impl()
    {
        timer.Stop();
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
            canvas->onError = nullptr;
            canvas->onSelection = nullptr;
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
    }

    bool EnsureCanvas()
    {
        if (canvas != nullptr)
        {
            return canvas->Ready();
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
            canvas->Selection(selection);
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

bool ModelView::LoadArtifact(const wxString& workspace, const Json& artifact, const Json& snapshot, const std::string& runId)
{
    if (IsLoading())
    {
        return false;
    }
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
            return DisplayMesh::Load(root, artifact, snapshot, runId, cancelled.get());
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
    }
    m_impl->Status("3D 형상을 생성하면 여기에 표시합니다.");
}

void ModelView::SetSelection(const std::string& identity)
{
    m_impl->selection = identity;
    if (m_impl->canvas != nullptr)
    {
        m_impl->canvas->Selection(identity);
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

std::size_t ModelView::TriangleCount() const
{
    return HasMesh() ? m_impl->scene->triangles : 0;
}

std::size_t ModelView::BodyCount() const
{
    return HasMesh() ? m_impl->scene->bodies.size() : 0;
}

std::uint64_t ModelView::RenderedFrameCount() const
{
    return m_impl->canvas != nullptr ? m_impl->canvas->frames : 0;
}
