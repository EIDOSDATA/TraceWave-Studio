/** @file @brief 실제 wxGLCanvas에서 정점 버퍼와 CPU 배열의 픽셀과 context 수명을 비교한다. */
#include "model_vertex_buffer.h"
#include "display_mesh.h"
#include "large_display_fixture.h"

#include <wx/glcanvas.h>
#include <wx/wx.h>
#include <chrono>
#include <iostream>
#include <memory>

namespace
{
using DisplayMesh::Body;
using DisplayMesh::Scene;
using Json = nlohmann::json;
using Clock = std::chrono::steady_clock;
constexpr int Width = 512;
constexpr int Height = 384;

void Check(bool passed, const char* message)
{
    if (!passed)
    {
        throw std::runtime_error(message);
    }
}

/** @brief 고정 투영의 두 다른 바디가 각각 위치와 법선 오프셋을 사용하게 한다. */
Scene Fixture()
{
    Scene scene;
    scene.triangles = 100000;
    scene.bodies.resize(2);
    for (int row = 0; row < 200; ++row)
    {
        auto& body = scene.bodies[static_cast<std::size_t>(row / 100)];
        for (int column = 0; column < 250; ++column)
        {
            const float x = -0.85f + column * 0.0068f;
            const float y = -0.76f + row * 0.0076f;
            const float upperX = x + 0.0058f;
            const float upperY = y + 0.0066f;
            const float z = row < 100 ? 0.1f : -0.1f;
            const GLfloat positions[] = {x, y, z, upperX, y, z, x, upperY, z,
                                         upperX, y, z, upperX, upperY, z, x, upperY, z};
            body.positions.insert(body.positions.end(), std::begin(positions), std::end(positions));
            const GLfloat normal[] = {row < 100 ? -0.6f : 0.6f, 0.0f, 0.8f};
            for (int vertex = 0; vertex < 6; ++vertex)
            {
                body.normals.insert(body.normals.end(), std::begin(normal), std::end(normal));
            }
        }
    }
    return scene;
}

/** @brief 같은 두 바디를 입력 데이터 주소만 바꿔 OpenGL 호환 표시 경로로 제출한다. */
void Draw(const Scene& scene, ModelVertexBuffer* buffer, double angle, const wxSize& size)
{
    glViewport(0, 0, size.x, size.y);
    glClearColor(1.0f, 1.0f, 1.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glEnable(GL_DEPTH_TEST);
    glMatrixMode(GL_PROJECTION);
    glLoadIdentity();
    glOrtho(-1.05, 1.05, -0.85, 0.85, -1.0, 1.0);
    glMatrixMode(GL_MODELVIEW);
    glLoadIdentity();
    const GLfloat light[] = {0.3f, 0.5f, 1.0f, 0.0f};
    glLightfv(GL_LIGHT0, GL_POSITION, light);
    glEnable(GL_LIGHT0);
    glEnable(GL_LIGHTING);
    glEnable(GL_COLOR_MATERIAL);
    glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE);
    glRotated(angle, 0.0, 1.0, 0.0);
    if (buffer != nullptr)
    {
        Check(buffer->Bind(scene), "현재 OpenGL context의 정점 버퍼를 만들 수 없습니다.");
    }
    glEnableClientState(GL_VERTEX_ARRAY);
    glEnableClientState(GL_NORMAL_ARRAY);
    for (std::size_t index = 0; index < scene.bodies.size(); ++index)
    {
        const auto& body = scene.bodies[index];
        glColor3f(index == 0 ? 0.2f : 0.8f, 0.3f, index == 0 ? 0.9f : 0.1f);
        if (buffer != nullptr)
        {
            buffer->BodyPointers(index);
        }
        else
        {
            glVertexPointer(3, GL_FLOAT, 0, body.positions.data());
            glNormalPointer(GL_FLOAT, 0, body.normals.data());
        }
        glDrawArrays(GL_TRIANGLES, 0, static_cast<GLsizei>(body.positions.size() / 3));
    }
    glDisableClientState(GL_VERTEX_ARRAY);
    glDisableClientState(GL_NORMAL_ARRAY);
    if (buffer != nullptr)
    {
        buffer->Unbind();
    }
}

std::vector<unsigned char> Pixels(const wxSize& size)
{
    std::vector<unsigned char> data(static_cast<std::size_t>(size.x) * size.y * 4);
    glReadBuffer(GL_BACK);
    glReadPixels(0, 0, size.x, size.y, GL_RGBA, GL_UNSIGNED_BYTE, data.data());
    Check(glGetError() == GL_NO_ERROR, "OpenGL 픽셀 판독에서 오류가 발생했습니다.");
    return data;
}

/** @brief 실제 표시 파일 로더에서 크기, 해시, 역할과 실행 결합을 검사한다. */
Scene LoadFixture(const std::filesystem::path& directory)
{
    const auto value = ReadLargeDisplayFixture(directory);
    const auto& artifact = value.at("artifact");
    auto scene = DisplayMesh::Load(directory, artifact, value.at("snapshot"), artifact.at("run_id").get<std::string>());
    Check(scene.triangles == DisplayMesh::MaxLargeTriangles, "대형 표시 시험에 100만 삼각형이 필요합니다.");
    return scene;
}

Json Verify(wxGLCanvas& canvas, const std::filesystem::path& directory, const wxSize& size)
{
    Check(canvas.GetClientSize() == size, "OpenGL 시험 화면 크기가 요청한 값과 다릅니다.");
    const auto loadStarted = Clock::now();
    const auto scene = directory.empty() ? Fixture() : LoadFixture(directory);
    const double loadMs = std::chrono::duration<double, std::milli>(Clock::now() - loadStarted).count();
    const std::size_t gpuBytes = scene.triangles * 3 * 6 * sizeof(GLfloat);
    auto context = std::make_unique<wxGLContext>(&canvas);
    Check(context->IsOK() && canvas.SetCurrent(*context), "시험용 OpenGL context를 열 수 없습니다.");
    const auto* driver = glGetString(GL_RENDERER);
    Check(driver != nullptr, "시험용 OpenGL renderer 이름이 없습니다.");
    const std::string renderer(reinterpret_cast<const char*>(driver));
    ModelVertexBuffer buffer;
    Draw(scene, nullptr, 12.0, size);
    const auto cpuPixels = Pixels(size);
    Check(cpuPixels[0] == 255 && std::count_if(cpuPixels.begin(), cpuPixels.end(), [](unsigned char pixel)
    {
        return pixel < 200;
    }) > 1000, "비교에 사용할 기하가 표시되지 않았습니다.");
    Draw(scene, &buffer, 12.0, size);
    Check(cpuPixels == Pixels(size) && buffer.Bytes() == gpuBytes && buffer.Uploads() == 1,
          "두 바디의 GPU 표시가 CPU 위치/법선 배열과 다릅니다.");

    std::vector<double> directTimes, bufferedTimes;
    for (int iteration = 0; iteration < 48; ++iteration)
    {
        for (int order = 0; order < 2; ++order)
        {
            const bool buffered = (order + iteration) % 2 != 0;
            const auto start = Clock::now();
            Draw(scene, buffered ? &buffer : nullptr, (iteration % 30) - 15.0, size);
            glFinish();
            const auto time = std::chrono::duration<double, std::milli>(Clock::now() - start).count();
            Check(glGetError() == GL_NO_ERROR, "반복 회전에서 OpenGL 오류가 발생했습니다.");
            if (iteration >= 8)
            {
                (buffered ? bufferedTimes : directTimes).push_back(time);
            }
        }
    }
    Check(buffer.Uploads() == 1, "카메라 회전 중 같은 정점 데이터를 다시 올렸습니다.");
    buffer.Release();
    Check(buffer.Bytes() == 0 && glGetError() == GL_NO_ERROR, "현재 context의 정점 저장소를 해제하지 못했습니다.");
    buffer.Invalidate();
    Draw(scene, &buffer, 12.0, size);
    Check(Pixels(size) == cpuPixels && buffer.Uploads() == 2, "버퍼 해제 후 같은 메시를 새로 표시하지 못했습니다.");

    context.reset();
    buffer.ContextDiscarded();
    Check(buffer.Bytes() == 0, "파기된 context의 버퍼가 남았습니다.");
    context = std::make_unique<wxGLContext>(&canvas);
    Check(context->IsOK() && canvas.SetCurrent(*context), "새 OpenGL context를 만들 수 없습니다.");
    Draw(scene, &buffer, 12.0, size);
    Check(Pixels(size) == cpuPixels && buffer.Uploads() == 3, "새 context에서 위치/법선을 복구하지 못했습니다.");

    Scene mismatched;
    mismatched.bodies.resize(1);
    mismatched.bodies.front().positions = {0.0f, 0.0f, 0.0f};
    buffer.Invalidate();
    Check(!buffer.Bind(mismatched) && buffer.Bytes() == 0 && glGetError() == GL_NO_ERROR,
          "위치와 법선 크기가 다른 버퍼를 허용했습니다.");
    Draw(scene, nullptr, 12.0, size);
    Check(Pixels(size) == cpuPixels, "부적합 GPU 버퍼 이후 CPU 배열 그리기를 복구하지 못했습니다.");
    return {{"schema", "rfad.windows-vertex-buffer-probe/0.1"}, {"ok", true}, {"renderer", renderer},
            {"triangles", scene.triangles}, {"bodies", scene.bodies.size()}, {"gpu_bytes", gpuBytes},
            {"size", {size.x, size.y}}, {"sealed_file_loaded", !directory.empty()}, {"load_ms", loadMs},
            {"pixel_equal", true}, {"uploads_after_rotation", 1}, {"uploads_after_new_context", 3},
            {"cpu_fallback_after_bad_layout", true}, {"cpu_gl_finish_ms", directTimes}, {"buffered_gl_finish_ms", bufferedTimes},
            {"present_intervals_measured", false}};
}

class ProbeApp final : public wxApp
{
public:
    bool OnInit() override
    {
        return true;
    }
};
}

wxIMPLEMENT_APP_NO_MAIN(ProbeApp);

int main(int argc, char** argv)
{
    if (argc != 1 && argc != 2)
    {
        return 2;
    }
    const auto directory = argc == 2 ? std::filesystem::absolute(std::filesystem::path(argv[1])) : std::filesystem::path{};
    const wxSize size = directory.empty() ? wxSize(Width, Height) : wxSize(1920, 1080);
    if (!wxEntryStart(argc, argv))
    {
        return 2;
    }
    Json report;
    if (wxTheApp->CallOnInit())
    {
        auto* frame = new wxFrame(nullptr, wxID_ANY, "TraceWave OpenGL vertex buffer probe");
        frame->SetClientSize(size);
        const int attributes[] = {WX_GL_RGBA, WX_GL_DOUBLEBUFFER, WX_GL_DEPTH_SIZE, 24, 0};
        auto* canvas = new wxGLCanvas(frame, wxID_ANY, attributes);
        auto* layout = new wxBoxSizer(wxVERTICAL);
        layout->Add(canvas, 1, wxEXPAND);
        frame->SetSizer(layout);
        frame->Show();
        frame->CallAfter([&report, frame, canvas, directory, size]()
        {
            try
            {
                report = Verify(*canvas, directory, size);
            }
            catch (const std::exception& error)
            {
                report = {{"ok", false}, {"error", error.what()}};
            }
            frame->Close();
        });
        wxTheApp->OnRun();
        wxTheApp->OnExit();
    }
    wxEntryCleanup();
    std::cout << report.dump() << '\n';
    return report.value("ok", false) ? 0 : 3;
}
