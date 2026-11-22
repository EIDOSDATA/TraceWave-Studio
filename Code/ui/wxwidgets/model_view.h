#pragma once

#include <wx/wx.h>
#include <nlohmann/json.hpp>

#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

/** @brief 게시된 표시용 삼각형만 비동기로 읽는 지연 생성 3D 화면이다. */
class ModelView final : public wxPanel
{
public:
    using Json = nlohmann::json;

    explicit ModelView(wxWindow* parent);
    ~ModelView() override;
    /** @brief 파일 참조와 같은 바이트의 SHA256을 background에서 확인한다. */
    bool LoadArtifact(const wxString& workspace, const Json& artifact, const Json& snapshot, const std::string& runId);
    void Clear();
    void SetSelection(const std::string& identity);
    /** @brief 현재 메시에 있는 급전 단자를 편집 선택과 구분하여 강조한다. */
    void SetRelatedSelection(const std::vector<std::string>& identities, bool suppressPrimary);
    void SetLayerVisible(const std::string& identity, bool visible);
    void FitView();
    /** @brief 설계 보기에서 선택할 수 있는 표시 전용 축 단면을 추가한다. */
    void EnableSections();
    void SetView(const std::string& view);
    /** @brief 드래그와 같은 카메라 회전/이동을 픽셀 변화량으로 적용한다. */
    void RotateView(double dx, double dy);
    void PanView(double dx, double dy);
    bool HasMesh() const;
    bool IsLoading() const;
    std::string Error() const;
    std::string LoadedSnapshotId() const;
    std::string Selection() const;
    /** @brief 선택 원본 ID에 연결된 3D 바디 역할을 조회한다. */
    std::string SourceRole(const std::string& id) const;
    std::string RendererDescription() const;
    /** @brief 실제 상태와 전송 횟수를 시험 기록에 제공한다. */
    Json VertexBufferDiagnostics() const;
    /** @brief 마지막 그리기에서 OpenGL에 제출한 삼각형 수다. */
    std::size_t SubmittedTriangleCount() const;
    std::size_t TriangleCount() const;
    std::size_t BodyCount() const;
    std::uint64_t RenderedFrameCount() const;
    /** @brief 명시적인 계측에서 이미 생성된 OpenGL 캔버스의 표시 기록을 전환한다. */
    void SetDisplayMarker(std::function<void(wxWindow&)> marker);
    /** @brief 반복 전환의 명시적 유지 시험에서 비어 있는 OpenGL 문맥을 유지한다. */
    void KeepContextForMeasurement();

    std::function<void(const std::string&)> onStatus;
    /** @brief 전용 계측 창에서 첫 파일을 열기 전에 지정하는 OpenGL 버퍼 표식이다. */
    std::function<void(wxWindow&)> onDrawDisplayMarker;
    std::function<void(const std::string&)> onSelection;
    /** @brief 병합 바디의 원본을 사용자에게 고르게 하며 첫 원본을 자동 채택하지 않는다. */
    std::function<void(const std::vector<std::string>&)> onSelectionCandidates;

private:
    friend class StudioSmokeDriver;
    bool ClickTopPointForSmoke(double x, double y);
    struct Impl;
    std::unique_ptr<Impl> m_impl;
};
