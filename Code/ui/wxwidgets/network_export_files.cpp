/** @file @brief 기존 원본을 덮지 않고 두 임시 파일의 완성과 실패 복구를 보장한다. */
#include "network_export_files.h"
#include "display_mesh.h"
#include <algorithm>
#include <cstddef>
#include <cstring>
#include <cwctype>
#include <filesystem>
#include <memory>
#include <objbase.h>
#include <wincrypt.h>
#include <string_view>
#include <stdexcept>
#include <vector>

namespace
{
using Path = std::filesystem::path;
constexpr std::size_t SourceLimit = 512U * 1024U;

void Require(bool condition, const char* message)
{
    if (!condition)
    {
        throw std::runtime_error(message);
    }
}

/** @brief 보유한 handle의 최종 경로를 읽고 Win32 확장 접두어를 같은 DOS/UNC 표현으로 맞춘다. */
Path ActualPath(HANDLE handle)
{
    const DWORD count = GetFinalPathNameByHandleW(handle, nullptr, 0, FILE_NAME_NORMALIZED | VOLUME_NAME_DOS);
    Require(count > 0 && count <= 32768, "열린 파일의 최종 경로 길이를 확인할 수 없습니다.");
    std::vector<wchar_t> buffer(static_cast<std::size_t>(count) + 1);
    const DWORD written = count == 0
                              ? 0
                              : GetFinalPathNameByHandleW(handle, buffer.data(), static_cast<DWORD>(buffer.size()),
                                                          FILE_NAME_NORMALIZED | VOLUME_NAME_DOS);
    Require(written > 0 && written < buffer.size(), "열린 파일의 최종 경로를 확인할 수 없습니다.");
    std::wstring name(buffer.data(), written);
    if (name.rfind(L"\\\\?\\UNC\\", 0) == 0)
    {
        name = L"\\\\" + name.substr(8);
    }
    else if (name.rfind(L"\\\\?\\", 0) == 0)
    {
        name.erase(0, 4);
    }
    return Path(name).lexically_normal();
}

/** @brief 열린 디렉터리의 실제 경로를 읽어 junction 별칭으로 workspace를 우회하지 않는다. */
Path ActualDirectory(const Path& path)
{
    const HANDLE handle = CreateFileW(path.c_str(), FILE_READ_ATTRIBUTES, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                                      OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, nullptr);
    Require(handle != INVALID_HANDLE_VALUE, "저장할 폴더를 열 수 없습니다.");
    const std::unique_ptr<void, decltype(&CloseHandle)> owned(handle, &CloseHandle);
    return ActualPath(handle);
}

/** @brief Windows의 대소문자 비교와 경로 요소 경계를 함께 적용한다. */
bool Inside(const Path& candidate, const Path& root)
{
    auto child = candidate.begin();
    for (auto part = root.begin(); part != root.end(); ++part, ++child)
    {
        if (child == candidate.end() || CompareStringOrdinal(child->c_str(), -1, part->c_str(), -1, TRUE) != CSTR_EQUAL)
        {
            return false;
        }
    }
    return true;
}

/** @brief 이름이 이미 존재하면 덮어쓰기나 기존 파일 제거 없이 거절한다. */
void Missing(const Path& path)
{
    const DWORD attributes = GetFileAttributesW(path.c_str());
    const DWORD error = attributes == INVALID_FILE_ATTRIBUTES ? GetLastError() : ERROR_SUCCESS;
    Require(attributes == INVALID_FILE_ATTRIBUTES && error == ERROR_FILE_NOT_FOUND,
            "교환 파일 또는 조건 sidecar가 이미 있거나 경로를 확인할 수 없습니다. 다른 파일 이름을 선택하세요.");
}

/** @brief 자신이 새로 만든 파일 handle만 유지하여 실패 복구가 다른 파일을 지우지 않게 한다. */
class PreparedFile final
{
public:
    ~PreparedFile()
    {
        Rollback();
    }

    void Write(const Path& parent, const std::string& bytes)
    {
        GUID id{};
        wchar_t idText[39]{};
        Require(SUCCEEDED(CoCreateGuid(&id)) && StringFromGUID2(id, idText, 39) == 39,
                "교환 임시 파일 ID를 만들 수 없습니다.");
        m_path = parent / (L".tracewave-export-" + std::wstring(idText) + L".tmp");
        m_handle = CreateFileW(m_path.c_str(), GENERIC_WRITE | DELETE | FILE_READ_ATTRIBUTES, FILE_SHARE_READ, nullptr,
                               CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
        Require(m_handle != INVALID_HANDLE_VALUE, "교환 임시 파일을 만들 수 없습니다.");
        std::size_t offset = 0;
        while (offset < bytes.size())
        {
            DWORD written = 0;
            Require(WriteFile(m_handle, bytes.data() + offset, static_cast<DWORD>(bytes.size() - offset), &written,
                              nullptr) != 0 &&
                        written > 0,
                    "교환 임시 파일 전체를 쓰지 못했습니다.");
            offset += written;
        }
        Require(FlushFileBuffers(m_handle) != 0, "교환 임시 파일을 저장 장치에 기록하지 못했습니다.");
    }

    void Publish(const Path& target)
    {
        const std::wstring name = target.native();
        /** @brief FileName은 NUL로 끝내되 FileNameLength에는 종료 문자를 제외한 바이트 수만 기록한다. */
        std::vector<unsigned char> storage(offsetof(FILE_RENAME_INFO, FileName) + (name.size() + 1) * sizeof(wchar_t),
                                           0);
        auto* rename = reinterpret_cast<FILE_RENAME_INFO*>(storage.data());
        rename->ReplaceIfExists = FALSE;
        rename->RootDirectory = nullptr;
        rename->FileNameLength = static_cast<DWORD>(name.size() * sizeof(wchar_t));
        std::memcpy(rename->FileName, name.data(), rename->FileNameLength);
        rename->FileName[name.size()] = L'\0';
        Require(SetFileInformationByHandle(m_handle, FileRenameInfo, rename, static_cast<DWORD>(storage.size())) != 0,
                "새 교환 파일을 게시하지 못했습니다. 기존 파일은 덮어쓰지 않습니다.");
        m_path = target;
        const auto actual = ActualPath(m_handle);
        m_path = actual;
        /** @brief 잘못된 이름으로 게시된 자신의 파일은 commit하지 않고 보유 handle로 회수한다. */
        Require(CompareStringOrdinal(actual.c_str(), -1, target.c_str(), -1, TRUE) == CSTR_EQUAL,
                "게시된 파일의 실제 경로가 요청한 이름과 다릅니다. 새 파일을 회수합니다.");
    }

    void Commit()
    {
        CloseHandle(m_handle);
        m_handle = INVALID_HANDLE_VALUE;
    }

    /** @brief 열린 자신의 파일만 삭제 예약하므로 이름 경합 중 다른 파일을 지우지 않는다. */
    bool Rollback()
    {
        if (m_handle == INVALID_HANDLE_VALUE)
        {
            return true;
        }
        FILE_DISPOSITION_INFO disposition{};
        disposition.DeleteFile = TRUE;
        const bool removed =
            SetFileInformationByHandle(m_handle, FileDispositionInfo, &disposition, sizeof(disposition)) != 0;
        CloseHandle(m_handle);
        m_handle = INVALID_HANDLE_VALUE;
        return removed;
    }

    std::string Location() const
    {
        const auto name = m_path.u8string();
        return {name.begin(), name.end()};
    }

private:
    HANDLE m_handle = INVALID_HANDLE_VALUE;
    Path m_path;
};

/** @brief 부모 경로를 검증하고 파일 생성 전에 디렉터리 항목의 handle을 확보한다. */
Path Target(const Path& selected, const Path& workspace, DisplayMesh::Handles& directories)
{
    Require(selected.is_absolute() && selected.has_filename(), "교환 파일은 절대 경로로 선택하세요.");
    const std::wstring fileName = selected.filename().native();
    Require(!fileName.empty() && fileName.size() <= 220 &&
                fileName.find_first_of(L"<>:\"/\\|?*") == std::wstring::npos && fileName.back() != L'.' &&
                fileName.back() != L' ',
            "교환 파일 이름에 지원하지 않는 문자가 있습니다.");
    Require(std::none_of(fileName.begin(), fileName.end(),
                         [](wchar_t value)
                         {
                             return value < 32;
                         }),
            "교환 파일 이름에 제어 문자가 있습니다.");
    std::wstring stem = fileName.substr(0, fileName.find(L'.'));
    std::transform(stem.begin(), stem.end(), stem.begin(),
                   [](wchar_t value)
                   {
                       return std::towupper(value);
                   });
    Require(stem != L"CON" && stem != L"PRN" && stem != L"AUX" && stem != L"NUL" &&
                !(stem.size() == 4 && (stem.substr(0, 3) == L"COM" || stem.substr(0, 3) == L"LPT") && stem[3] >= L'1' &&
                  stem[3] <= L'9'),
            "Windows 장치 예약 이름으로 교환 파일을 저장하지 않습니다.");
    const Path parent = ActualDirectory(selected.parent_path());
    const Path storage = ActualDirectory(workspace);
    Require(
        !Inside(parent, storage),
        "프로젝트 작업 영역 안에는 교환 파일을 저장하지 않습니다. 원본과 과거 자료 보존을 위해 외부 폴더를 선택하세요.");
    Path current = parent.root_path();
    directories.Open(current, true);
    for (const auto& part : parent.relative_path())
    {
        current /= part;
        directories.Open(current, true);
    }
    return parent / selected.filename();
}

}

void NetworkExportFiles::WriteExternal(const Path& path, const Path& workspace, const std::string& bytes)
{
    DisplayMesh::Handles directories;
    const Path target = Target(path, workspace, directories);
    Missing(target);
    PreparedFile content;
    try
    {
        content.Write(target.parent_path(), bytes);
        content.Publish(target);
        content.Commit();
    }
    catch (const std::exception& error)
    {
        if (!content.Rollback())
        {
            throw std::runtime_error(std::string(error.what()) +
                                     "\n새 임시 파일을 회수하지 못했습니다: " + content.Location());
        }
        throw;
    }
}

void NetworkExportFiles::WriteResult(const nlohmann::json& result, const Path& path, const Path& workspace)
{
    Require(result.value("profile", "") == "rfad.network-workspace/0.1", "지원하지 않는 교환 응답입니다.");
    Require(result.contains("bytes") && result.at("bytes").is_number_integer(), "교환 파일의 원문 크기가 없습니다.");
    const auto expected = result.at("bytes").get<std::int64_t>();
    Require(expected > 0 && expected <= static_cast<std::int64_t>(SourceLimit),
            "교환 파일의 512 KiB 상한을 초과했습니다.");
    const std::string encoded = result.at("content_base64");
    Require(encoded.size() <= ((SourceLimit + 2) / 3) * 4, "교환 파일의 base64 상한을 초과했습니다.");
    const std::string_view source(encoded);
    const auto suffix = source.find('=');
    const auto body = source.substr(0, suffix);
    const auto padding = source.substr(body.size());
    Require(!body.empty() && source.size() % 4 == 0 && padding.size() <= 2 &&
                body.find_first_not_of("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/") == std::string_view::npos &&
                padding.find_first_not_of('=') == std::string_view::npos,
            "교환 파일의 base64 문자가 올바르지 않습니다.");
    DWORD decodedBytes = static_cast<DWORD>(expected);
    std::string raw(decodedBytes, '\0');
    Require(CryptStringToBinaryA(encoded.data(), static_cast<DWORD>(encoded.size()), CRYPT_STRING_BASE64 | CRYPT_STRING_STRICT,
                reinterpret_cast<BYTE*>(raw.data()), &decodedBytes, nullptr, nullptr) &&
                decodedBytes == static_cast<DWORD>(expected),
            "교환 파일의 base64 또는 원문 크기가 다릅니다.");
    Require(DisplayMesh::Sha256(raw) == result.at("sha256").get<std::string>(),
            "교환 파일의 SHA256이 서비스 응답과 다릅니다.");
    Require(result.at("sidecar").is_object() && result.at("sidecar").value("schema", "") == "rfad.network-export/0.1",
            "조건 sidecar의 형식이 다릅니다.");
    const std::string sidecar = result.at("sidecar").dump(2) + "\n";
    Require(sidecar.size() <= 1024U * 1024U, "조건 sidecar의 1 MiB 표시 및 저장 상한을 초과했습니다.");
    DisplayMesh::Handles directories;
    const Path target = Target(path, workspace, directories);
    const Path parent = target.parent_path();
    const auto fileName = target.filename().native();
    const Path metadata = parent / (fileName + L".conditions.json");
    Missing(target);
    Missing(metadata);
    PreparedFile contentFile;
    PreparedFile conditionFile;
    try
    {
        contentFile.Write(parent, raw);
        conditionFile.Write(parent, sidecar);
        contentFile.Publish(target);
        conditionFile.Publish(metadata);
        contentFile.Commit();
        conditionFile.Commit();
    }
    catch (const std::exception& error)
    {
        std::string message = error.what();
        const bool first = contentFile.Rollback();
        const bool second = conditionFile.Rollback();
        if (!first || !second)
        {
            message += "\n저장을 완료하지 못했고 새 파일 일부를 회수하지 못했습니다. 남은 경로를 확인하세요:";
            if (!first)
            {
                message += "\n" + contentFile.Location();
            }
            if (!second)
            {
                message += "\n" + conditionFile.Location();
            }
        }
        else
        {
            message += "\n새로 만든 파일을 회수했습니다. 교환 저장은 완료되지 않았습니다.";
        }
        throw std::runtime_error(message);
    }
}
