/** @file @brief 보고서 검토, 영수증과 검증한 ZIP 전달을 기존 출력 서비스에 연결한다. */
#include "output_controller.h"
#include "output_workspace.h"
#include "handoff_output_view.h"
#include "display_mesh.h"
#include "file_delivery.h"
#include "output_pending_store.h"
#include "studio_support.h"
#include <wx/base64.h>
#include <wx/filedlg.h>
#include <algorithm>
#include <stdexcept>

namespace
{
constexpr std::size_t ChunkBytes = 128U * 1024U;
constexpr std::size_t MaxZipBytes = 8U * 1024U * 1024U;
constexpr int EvidencePageSize = 12;
constexpr auto Profile = "rfad.project-handoff/0.1";

bool ValidPackage(const Json& package, const std::string& project)
{
    return package.is_object() && package.value("profile", "") == Profile && package.at("project_id") == project &&
           package.at("package_id").is_string() && package.at("snapshot_id").is_string() &&
           package.at("chunk_bytes") == ChunkBytes && package.at("file_name").is_string() &&
           package.at("artifact").at("sha256").is_string() && package.at("artifact").at("bytes").is_number_unsigned() &&
           package.at("artifact").at("bytes").get<std::size_t>() > 0 &&
           package.at("artifact").at("bytes").get<std::size_t>() <= MaxZipBytes;
}
}

void OutputController::HandoffSync()
{
    const auto snapshot = m_view->Snapshot();
    if (!m_handoffSupported || !m_available)
    {
        m_view->SetHandoffConditions(snapshot, nullptr);
        if (m_connected && !m_handoffSupported)
        {
            m_view->SetStatus("현재 서비스의 인계 계약을 사용할 수 없습니다.");
        }
        return;
    }
    if (snapshot != m_handoffSnapshot)
    {
        m_handoffSnapshot = snapshot;
        m_handoffInput = nullptr;
        m_view->Handoff()->ResetEvidence();
    }
    m_view->SetHandoffConditions(snapshot, m_view->Handoff()->Review());
    HandoffCatalog();
    if (m_uncertain)
    {
        Status("unresolved", "이전 출력 요청의 결과를 확인해야 합니다. 새 생성은 잠겼습니다.");
    }
    else if (snapshot.is_object())
    {
        HandoffEvidence(0);
    }
    else
    {
        m_view->SetStatus("고정 입력을 선택하거나 발행 기록에서 ZIP을 저장하세요.");
    }
}

void OutputController::HandoffEvidence(int offset)
{
    const auto snapshot = m_view->Snapshot();
    if (!m_handoffSupported || !snapshot.is_object() || Active())
    {
        return;
    }
    const auto generation = ++m_handoffGeneration;
    Read("evidence.query",
         {{"snapshot", snapshot},
          {"kinds", Json::array()},
          {"records", Json::array()},
          {"offset", offset},
          {"limit", EvidencePageSize}},
         [this, snapshot, offset, generation](const Json& value)
         {
             if (generation != m_handoffGeneration || snapshot != m_view->Snapshot() || m_view->Kind() != 3)
             {
                 return;
             }
             if (value.at("project_id") != m_project || value.at("snapshot_id") != snapshot.at("snapshot_id") ||
                 value.at("content_hash") != snapshot.at("content_hash") || value.at("offset") != offset ||
                 !value.at("items").is_array() || value.at("items").size() > EvidencePageSize)
             {
                 throw std::runtime_error("인계 근거의 고정 입력 또는 페이지가 다릅니다.");
             }
             m_view->Handoff()->SetEvidence(value);
             m_view->SetStatus("선택한 고정 입력의 보고서 근거를 읽었습니다.");
         });
}

void OutputController::HandoffCatalog(const std::string& preferred)
{
    const auto generation = ++m_handoffCatalogGeneration;
    Read("package.list", Json::object(),
         [this, preferred, generation](const Json& value)
         {
             if (generation != m_handoffCatalogGeneration)
             {
                 return;
             }
             if (value.value("profile", "") != Profile || value.at("project_id") != m_project ||
                 !value.at("items").is_array() || value.at("items").size() > 32)
             {
                 throw std::runtime_error("인계 발행 기록의 형식 또는 프로젝트가 다릅니다.");
             }
             for (const auto& package : value.at("items"))
             {
                 if (!ValidPackage(package, m_project))
                 {
                     throw std::runtime_error("인계 발행 기록의 파일 식별자를 확인할 수 없습니다.");
                 }
             }
             m_view->Handoff()->SetCatalog(value, preferred);
         });
}

void OutputController::HandoffPreview()
{
    const auto snapshot = m_view->Snapshot();
    if (!m_available || !m_handoffSupported || Active() || m_reads != 0 || !snapshot.is_object())
    {
        return;
    }
    auto* handoff = m_view->Handoff();
    auto input = handoff->Input();
    input["snapshot"] = snapshot;
    m_handoffInput = nullptr;
    handoff->SetReview(nullptr);
    Read("package.preview", input,
         [this, snapshot, input](const Json& value)
         {
             if (m_view->Kind() != 3 || m_view->Snapshot() != snapshot)
             {
                 return;
             }
             if (value.value("profile", "") != Profile || value.at("project_id") != m_project ||
                 value.at("snapshot_id") != snapshot.at("snapshot_id") ||
                 value.at("content_hash") != snapshot.at("content_hash") || !value.at("review_hash").is_string() ||
                 !value.value("read_only_handoff", false))
             {
                 throw std::runtime_error("인계 검토 응답의 고정 입력이나 계약이 다릅니다.");
             }
             m_handoffInput = input;
             m_view->Handoff()->SetReview(value);
             m_view->SetStatus("보고서와 파일 목록을 확인한 뒤 인계 묶음을 생성하세요.");
         });
}

void OutputController::HandoffBuild()
{
    if (!m_available || !m_handoffSupported || Active() || m_reads != 0)
    {
        return;
    }
    auto* handoff = m_view->Handoff();
    auto input = handoff->Input();
    input["snapshot"] = m_view->Snapshot();
    if (input != m_handoffInput || !handoff->Review().is_object())
    {
        return;
    }
    input["review_hash"] = handoff->Review().at("review_hash");
    Start("package.build", input);
}

void OutputController::CompleteHandoff(const Json& package)
{
    const auto& input = m_pending.at("input");
    if (!ValidPackage(package, m_project) || package.at("snapshot_id") != input.at("snapshot").at("snapshot_id") ||
        package.at("review_hash") != input.at("review_hash"))
    {
        throw std::runtime_error("인계 발행 결과가 검토한 고정 입력과 다릅니다.");
    }
    const auto packageId = package.at("package_id").get<std::string>();
    OutputPendingStore::Clear(m_workspace, m_project);
    m_pending = nullptr;
    m_uncertain = false;
    HandoffCatalog(packageId);
    Status("completed", "인계 묶음을 발행했습니다. ZIP 사본 저장에서 전달할 경로를 선택하세요.");
}

void OutputController::HandoffSave()
{
    if (!m_available || !m_handoffSupported || Active() || m_reads != 0)
    {
        return;
    }
    const auto package = m_view->Handoff()->SelectedPackage();
    if (!ValidPackage(package, m_project))
    {
        return;
    }
    const auto serial = m_serial;
    wxFileDialog chooser(m_view, Display("검증한 인계 ZIP 사본 저장"), wxEmptyString,
                         Display(package.at("file_name").get<std::string>()),
                         Display("인계 ZIP (*.rfad.zip)|*.rfad.zip"), wxFD_SAVE);
    if (chooser.ShowModal() != wxID_OK || m_serial != serial || !m_available)
    {
        return;
    }
    if (!chooser.GetPath().Lower().EndsWith(".rfad.zip"))
    {
        Status("failed", "인계 사본 파일 이름의 끝을 .rfad.zip으로 지정하세요.");
        return;
    }
    m_handoffPath = Utf8(chooser.GetPath());
    m_handoffDownload = package;
    m_handoffBytes.reserve(package.at("artifact").at("bytes").get<std::size_t>());
    m_view->SetStatus("인계 묶음의 바이트와 해시를 대조하고 있습니다.");
    if (onStateChanged)
    {
        onStateChanged();
    }
    HandoffChunk();
}

void OutputController::HandoffChunk()
{
    const auto& artifact = m_handoffDownload.at("artifact");
    const auto size = artifact.at("bytes").get<std::size_t>();
    const auto offset = m_handoffBytes.size();
    const auto hash = artifact.at("sha256").get<std::string>();
    const auto id = m_handoffDownload.at("package_id").get<std::string>();
    const auto finish = [this](const std::string& state, const std::string& message)
    {
        EndHandoffSave();
        Status(state, message);
        if (onStateChanged)
        {
            onStateChanged();
        }
    };
    Read(
        "package.read", {{"package_id", id}, {"sha256", hash}, {"offset", offset}},
        [this, offset, size, hash, id, finish](const Json& value)
        {
            try
            {
                const auto& encoded = value.at("content_base64").get_ref<const std::string&>();
                const auto expected = std::min(size - offset, ChunkBytes);
                if (value.value("profile", "") != Profile || value.at("project_id") != m_project ||
                    value.at("package_id") != id || value.at("sha256") != hash || value.at("total") != size ||
                    value.at("offset") != offset || encoded.size() != ((expected + 2) / 3) * 4)
                {
                    throw std::runtime_error("인계 사본의 프로젝트, 해시 또는 청크 위치가 다릅니다.");
                }
                const auto decoded = wxBase64Decode(encoded.data(), encoded.size(), wxBase64DecodeMode_Strict);
                if (decoded.GetDataLen() != expected)
                {
                    throw std::runtime_error("인계 사본 청크의 실제 길이가 다릅니다.");
                }
                const auto end = offset + expected;
                const Json next = end < size ? Json(end) : Json(nullptr);
                if (value.at("next_offset") != next)
                {
                    throw std::runtime_error("인계 사본의 다음 청크 위치가 다릅니다.");
                }
                m_handoffBytes.append(static_cast<const char*>(decoded.GetData()), expected);
                if (end < size)
                {
                    HandoffChunk();
                    return;
                }
                if (DisplayMesh::Sha256(m_handoffBytes) != hash)
                {
                    throw std::runtime_error("인계 사본 전체의 SHA256이 발행 기록과 다릅니다.");
                }
                WriteExternalExportFile(Display(m_handoffPath), Display(m_workspace), m_handoffBytes);
                finish("completed", "SHA256이 일치하는 인계 사본을 저장했습니다.");
            }
            catch (const std::exception& error)
            {
                finish("failed", error.what());
            }
        },
        [finish](const Json& error)
        {
            finish("failed", DiagnosticMessage(error));
        });
}

void OutputController::EndHandoffSave()
{
    m_handoffDownload = nullptr;
    m_handoffPath.clear();
    std::string().swap(m_handoffBytes);
}
