#include "prototype_archive.h"

#include "../wxwidgets/display_mesh.h"
#include "prototype_service.h"

#include <SDL3/SDL.h>
#include <commdlg.h>
#include <wincrypt.h>

#include <algorithm>
#include <chrono>
#include <fstream>
#include <stdexcept>
#include <string_view>
#include <vector>

namespace
{
using nlohmann::json;
constexpr std::size_t chunkBytes = 128 * 1024;
constexpr std::size_t limit = 64 * 1024 * 1024;
constexpr std::string_view receiver = "rfad.archive-receive/0.1";
constexpr std::string_view archive = "rfad.project-archive/0.1";

/** @brief 사용자가 지정하는 하나의 원본 ZIP을 읽기 전용으로 고른다. */
std::filesystem::path Pick(SDL_Window* window)
{
    std::vector<wchar_t> name(32768);
    OPENFILENAMEW dialog{};
    dialog.lStructSize = sizeof(dialog);
    dialog.hwndOwner = static_cast<HWND>(SDL_GetPointerProperty(SDL_GetWindowProperties(window),
        SDL_PROP_WINDOW_WIN32_HWND_POINTER, nullptr));
    dialog.lpstrFilter = L"TraceWave ZIP (*.zip)\0*.zip\0";
    dialog.lpstrTitle = L"복원할 TraceWave 보존 ZIP 선택";
    dialog.lpstrFile = name.data();
    dialog.nMaxFile = static_cast<DWORD>(name.size());
    dialog.Flags = OFN_EXPLORER | OFN_NOCHANGEDIR | OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST;
    if (!GetOpenFileNameW(&dialog))
    {
        if (CommDlgExtendedError())
        {
            throw std::runtime_error("보존 ZIP 선택 창을 열 수 없습니다.");
        }
        return {};
    }
    return name.data();
}

std::string Encode(std::string_view bytes)
{
    constexpr DWORD mode = CRYPT_STRING_BASE64 | CRYPT_STRING_NOCRLF;
    const auto* data = reinterpret_cast<const BYTE*>(bytes.data());
    const auto size = static_cast<DWORD>(bytes.size());
    DWORD capacity = 0;
    DisplayMesh::Require(CryptBinaryToStringA(data, size, mode, nullptr, &capacity) && capacity > 1,
        "복원 청크의 인코딩 길이를 확인할 수 없습니다.");
    std::string output(capacity, '\0');
    DisplayMesh::Require(CryptBinaryToStringA(data, size, mode, output.data(), &capacity),
        "복원 청크를 인코딩할 수 없습니다.");
    output.resize(capacity);
    return output;
}
}

bool PrototypeArchive::busy() const
{
    return phase_ != Phase::idle && phase_ != Phase::approval;
}

bool PrototypeArchive::canChoose() const
{
    return phase_ == Phase::idle;
}

bool PrototypeArchive::canApprove() const
{
    return phase_ == Phase::approval && !cancelling_;
}

bool PrototypeArchive::canCancel() const
{
    return phase_ == Phase::read || phase_ == Phase::begin || phase_ == Phase::chunk ||
        phase_ == Phase::review || phase_ == Phase::approval;
}

void PrototypeArchive::choose()
{
    if (canChoose())
    {
        clear();
        restored_.clear();
        phase_ = Phase::choose;
    }
}

void PrototypeArchive::approve()
{
    if (canApprove())
    {
        phase_ = Phase::reserve;
        status_ = "검토한 ZIP의 복원 접수를 확인하는 중";
    }
}

void PrototypeArchive::cancel()
{
    if (canCancel())
    {
        cancelling_ = true;
        status_ = "복원 검토를 취소하는 중";
        if (phase_ == Phase::approval)
        {
            phase_ = Phase::drop;
        }
    }
}

PrototypeArchive::File PrototypeArchive::readFile(const std::filesystem::path& path)
{
    const auto size = std::filesystem::file_size(path);
    DisplayMesh::Require(size > 0 && size <= limit, "보존 ZIP은 1바이트에서 64 MiB까지 지원합니다.");
    std::ifstream input(path, std::ios::binary);
    std::string bytes(static_cast<std::size_t>(size), '\0');
    DisplayMesh::Require(input.read(bytes.data(), static_cast<std::streamsize>(size)) && input.peek() == EOF,
        "보존 ZIP을 읽을 수 없거나 읽는 중 길이가 바뀌었습니다.");
    const auto sha = DisplayMesh::Sha256(bytes);
    return {std::move(bytes), sha};
}

/** @brief 전경의 일반 프로젝트 요청이 멈춘 동안 수신 청크를 한 건씩 확인한다. */
void PrototypeArchive::update(SDL_Window* window, PrototypeService& service)
{
    if (!busy())
    {
        return;
    }
    try
    {
        if (service.state() != PrototypeService::State::connected)
        {
            throw std::runtime_error("복원 상태를 확인할 수 없습니다. 프로젝트와 보존 ZIP을 다시 확인하세요.");
        }
        if (phase_ == Phase::choose)
        {
            const auto path = Pick(window);
            if (path.empty())
            {
                status_ = "보존 ZIP 선택을 취소했습니다.";
                clear();
                return;
            }
            read_ = std::async(std::launch::async, readFile, path);
            status_ = "선택한 ZIP의 SHA-256을 계산하는 중";
            phase_ = Phase::read;
            return;
        }
        if (phase_ == Phase::read)
        {
            if (read_.wait_for(std::chrono::seconds(0)) != std::future_status::ready)
            {
                return;
            }
            file_ = read_.get();
            phase_ = Phase::begin;
        }
        if (waiting_)
        {
            const auto response = service.takeReply();
            if (response.is_null())
            {
                return;
            }
            waiting_ = false;
            if (response.contains("error"))
            {
                const auto& error = response.at("error");
                const auto code = error.value("data", json::object()).value("domain_code", "");
                throw std::runtime_error(code + " " + error.value("message", "복원 요청이 실패했습니다."));
            }
            accept(response.at("result"));
        }
        if (cancelling_ && canCancel())
        {
            if (upload_.empty())
            {
                clear();
                status_ = "보존 ZIP 검토를 취소했습니다.";
                return;
            }
            phase_ = Phase::drop;
        }
        const json context = json::object();
        switch (phase_)
        {
            case Phase::begin:
                waiting_ = service.request("archive.receive.begin", context,
                    {{"bytes", file_.bytes.size()}, {"archive_sha256", file_.sha}});
                break;
            case Phase::chunk:
                sent_ = std::min(chunkBytes, file_.bytes.size() - position_);
                waiting_ = service.request("archive.receive.chunk", context,
                    {{"upload_id", upload_}, {"offset", position_},
                        {"content_base64", Encode(std::string_view(file_.bytes).substr(position_, sent_))}});
                break;
            case Phase::review:
                waiting_ = service.request("archive.receive.review", context, {{"upload_id", upload_}});
                break;
            case Phase::reserve:
                waiting_ = service.request("archive.receive.reserve", context, approval(), true);
                break;
            case Phase::apply:
                waiting_ = service.request("archive.receive.apply", context, approval(), true);
                break;
            case Phase::drop:
                waiting_ = service.request("archive.receive.drop", context, {{"upload_id", upload_}});
                break;
            default:
                return;
        }
        if (!waiting_)
        {
            throw std::runtime_error("복원 요청을 서비스에 전달할 수 없습니다.");
        }
    }
    catch (const std::exception& error)
    {
        status_ = std::string("보존 ZIP 복원 실패. ") + error.what();
        cancelling_ = false;
        if (!upload_.empty() && phase_ != Phase::drop && service.state() == PrototypeService::State::connected)
        {
            phase_ = Phase::drop;
            waiting_ = false;
        }
        else
        {
            clear();
        }
    }
}

void PrototypeArchive::accept(const json& result)
{
    using DisplayMesh::Require;
    switch (phase_)
    {
        case Phase::begin:
        case Phase::chunk:
        {
            const auto received = result.at("received").get<std::size_t>();
            const auto id = result.at("upload_id").get<std::string>();
            Require(result.at("profile") == receiver && result.at("archive_sha256") == file_.sha &&
                result.at("bytes") == file_.bytes.size() && result.at("chunk_bytes") == chunkBytes && !id.empty() &&
                (phase_ == Phase::begin ? received <= file_.bytes.size() &&
                    (received == file_.bytes.size() || received % chunkBytes == 0)
                    : id == upload_ && received == position_ + sent_), "받은 ZIP 또는 청크 범위가 다릅니다.");
            upload_ = id;
            position_ = received;
            phase_ = position_ == file_.bytes.size() ? Phase::review : Phase::chunk;
            status_ = "보존 ZIP 전송 " + std::to_string(100 * position_ / file_.bytes.size()) + "%";
            return;
        }
        case Phase::review:
            Require(result.at("profile") == archive && result.at("upload_id") == upload_ &&
                result.at("archive_sha256") == file_.sha && result.at("review_hash").is_string() &&
                result.at("path").is_string() && result.at("scope").at("execution_on_restore") == false &&
                result.at("saved_revision").is_string() && result.at("revision_id").is_string() &&
                result.at("files").is_number_unsigned() && result.at("missing_count").is_number_unsigned() &&
                result.at("omitted_preview").is_array(), "검토가 선택한 ZIP이나 복원 범위와 다릅니다.");
            review_ = result;
            phase_ = Phase::approval;
            status_ = "저장본과 복원할 개정을 확인한 뒤 승인하세요.";
            return;
        case Phase::reserve:
            Require(result.at("archive_sha256") == file_.sha && result.at("review_hash") == review_.at("review_hash"),
                "복원 영수증이 승인한 검토와 다릅니다.");
            if (result.at("status") == "reserved")
            {
                phase_ = Phase::apply;
                status_ = "원문을 보존하고 프로젝트를 등록하는 중";
                return;
            }
            complete(result);
            return;
        case Phase::apply:
            complete(result);
            return;
        case Phase::drop:
            Require(result.at("profile") == receiver && result.at("upload_id") == upload_ && result.at("dropped") == true,
                "복원 수신 파일의 취소를 확인할 수 없습니다.");
            if (cancelling_)
            {
                status_ = "보존 ZIP 검토를 취소했습니다.";
            }
            clear();
            return;
        default:
            throw std::runtime_error("복원 응답 순서가 올바르지 않습니다.");
    }
}

json PrototypeArchive::approval() const
{
    return {{"upload_id", upload_}, {"archive_sha256", file_.sha}, {"review_hash", review_.at("review_hash")}};
}

void PrototypeArchive::complete(const json& result)
{
    DisplayMesh::Require(result.at("profile") == archive && result.at("status") == "restored" &&
        result.at("archive_sha256") == file_.sha && result.at("project_id") == review_.at("project_id") &&
        result.at("saved_revision") == review_.at("saved_revision") && result.at("revision_id") == review_.at("revision_id") &&
        result.at("path") == review_.at("path"), "복원된 프로젝트 또는 개정이 검토와 다릅니다.");
    restored_ = result.at("path").get<std::string>();
    phase_ = Phase::drop;
    status_ = "프로젝트를 복원했습니다. 복원한 프로젝트를 열 수 있습니다.";
}

void PrototypeArchive::clear()
{
    file_ = {};
    review_ = nullptr;
    upload_.clear();
    phase_ = Phase::idle;
    waiting_ = cancelling_ = false;
    position_ = sent_ = 0;
}
