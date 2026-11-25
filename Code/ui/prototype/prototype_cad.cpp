#include "prototype_cad.h"

#include "../wxwidgets/display_mesh_picking.h"

#include <chrono>
#include <cstdio>
#include <utility>

using nlohmann::json;

PrototypeCad::PrototypeCad(const char* workspace)
{
    if (workspace)
    {
        workspace_ = std::filesystem::u8path(workspace);
    }
}

PrototypeCad::~PrototypeCad()
{
    cancelled_.store(true);
    if (pending_.valid())
    {
        pending_.wait();
    }
}

void PrototypeCad::setStatus(std::string status)
{
    status_ = std::move(status);
}

/** @brief RC10의 표시 범위 선택을 따라 STEP의 미리보기와 별도 형상 결과를 구분한다. */
void PrototypeCad::accept(const json& reply, const std::string& project)
{
    using DisplayMesh::Require;
    Require(reply.at("profile") == "rfad.cad-view/0.1", "지원하지 않는 CAD 조회 응답입니다.");
    const auto& latest = reply.at("result");
    if (latest.is_null())
    {
        scene_.reset();
        setStatus("게시된 3D 형상이 없습니다.");
        return;
    }
    const json* display = &latest;
    if (latest.value("projection_purpose", "") == "step")
    {
        display = reply.contains("view_result") ? &reply.at("view_result") : nullptr;
    }
    if (!display || display->is_null())
    {
        scene_.reset();
        setStatus("표시용 3D 형상이 아직 게시되지 않았습니다.");
        return;
    }
    if (!load(*display, project))
    {
        scene_.reset();
        setStatus("게시된 결과에 표시용 3D 파일이 없습니다.");
    }
}

/** @brief 새 게시의 검증을 시작하고 기존 장면은 확인이 끝날 때까지 유지한다. */
bool PrototypeCad::load(const json& result, const std::string& project)
{
    using DisplayMesh::Require;
    Require(!loading(), "이전 3D 파일 검증이 끝나지 않았습니다.");
    const auto& snapshot = result.at("snapshot");
    Require(snapshot.at("project_id") == project && result.at("status") == "generated_unverified",
        "3D 표시 자료가 현재 프로젝트 또는 게시 상태와 다릅니다.");
    const auto& artifacts = result.at("artifacts");
    Require(artifacts.is_array(), "3D 자료의 게시 파일 목록이 올바르지 않습니다.");
    const json* reference = nullptr;
    for (const auto& artifact : artifacts)
    {
        if (artifact.value("role", "") == "display_mesh")
        {
            Require(!reference, "3D 표시 파일 참조가 중복되었습니다.");
            reference = &artifact;
        }
    }
    if (!reference)
    {
        return false;
    }
    const auto run = DisplayMesh::Identity(reference->at("run_id"));
    pending_ = std::async(std::launch::async, [this, artifact = *reference, snapshot, run]() -> Scene
    {
        auto scene = DisplayMesh::Load(workspace_, artifact, snapshot, run, &cancelled_);
        DisplayMesh::BuildPickIndex(scene, &cancelled_);
        return std::make_shared<DisplayMesh::Scene>(std::move(scene));
    });
    setStatus("3D 형상 파일을 확인하는 중");
    return true;
}

void PrototypeCad::poll()
{
    if (!pending_.valid() || pending_.wait_for(std::chrono::seconds(0)) != std::future_status::ready)
    {
        return;
    }
    try
    {
        auto verified = pending_.get();
        std::printf("CAD display: snapshot=%s revision=%s run=%s bodies=%zu triangles=%zu\n",
            verified->snapshotId.c_str(), verified->revisionId.c_str(), verified->runId.c_str(),
            verified->bodies.size(), verified->triangles);
        scene_ = std::move(verified);
        status_.clear();
    }
    catch (const std::exception& error)
    {
        status_ = std::string("3D 형상 읽기 실패: ") + error.what();
        std::fprintf(stderr, "%s\n", status_.c_str());
    }
}
