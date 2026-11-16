/** @file @brief 기존 원본을 덮지 않고 두 임시 파일의 완성과 실패 복구를 보장한다. */
#include "network_export.h"
#include "display_mesh.h"
#include "studio_support.h"
#include <wx/base64.h>
#include <wx/filedlg.h>
#include <wx/msgdlg.h>
#include <algorithm>
#include <cstddef>
#include <cstring>
#include <cwctype>
#include <filesystem>
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

/** @brief 열린 디렉터리의 실제 경로를 읽어 junction 별칭으로 workspace를 우회하지 않는다. */
Path ActualDirectory(const Path& path)
{
    const HANDLE handle = CreateFileW(path.c_str(), FILE_READ_ATTRIBUTES, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                                      OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, nullptr);
    Require(handle != INVALID_HANDLE_VALUE, "저장할 폴더를 열 수 없습니다.");
    const DWORD count = GetFinalPathNameByHandleW(handle, nullptr, 0, FILE_NAME_NORMALIZED | VOLUME_NAME_DOS);
    std::vector<wchar_t> buffer(static_cast<std::size_t>(count) + 1);
    const DWORD written = count == 0
                              ? 0
                              : GetFinalPathNameByHandleW(handle, buffer.data(), static_cast<DWORD>(buffer.size()),
                                                          FILE_NAME_NORMALIZED | VOLUME_NAME_DOS);
    CloseHandle(handle);
    Require(written > 0 && written < buffer.size(), "저장 폴더의 실제 경로를 확인할 수 없습니다.");
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
        m_path = parent / (L".tracewave-export-" + Display(Uuid()).ToStdWstring() + L".tmp");
        m_handle = CreateFileW(m_path.c_str(), GENERIC_WRITE | DELETE, FILE_SHARE_READ, nullptr, CREATE_NEW,
                               FILE_ATTRIBUTE_NORMAL, nullptr);
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
        std::vector<unsigned char> storage(offsetof(FILE_RENAME_INFO, FileName) + name.size() * sizeof(wchar_t));
        auto* rename = reinterpret_cast<FILE_RENAME_INFO*>(storage.data());
        rename->ReplaceIfExists = FALSE;
        rename->RootDirectory = nullptr;
        rename->FileNameLength = static_cast<DWORD>(name.size() * sizeof(wchar_t));
        std::memcpy(rename->FileName, name.data(), rename->FileNameLength);
        Require(SetFileInformationByHandle(m_handle, FileRenameInfo, rename, static_cast<DWORD>(storage.size())) != 0,
                "새 교환 파일을 게시하지 못했습니다. 기존 파일은 덮어쓰지 않습니다.");
        m_path = target;
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
        return m_path.u8string();
    }

private:
    HANDLE m_handle = INVALID_HANDLE_VALUE;
    Path m_path;
};
}

void WriteNetworkExportFiles(const Json& result, const wxString& path, const wxString& workspace)
{
    Require(result.value("profile", "") == "rfad.network-workspace/0.1", "지원하지 않는 교환 응답입니다.");
    Require(result.contains("bytes") && result.at("bytes").is_number_integer(), "교환 파일의 원문 크기가 없습니다.");
    const auto expected = result.at("bytes").get<std::int64_t>();
    Require(expected > 0 && expected <= static_cast<std::int64_t>(SourceLimit),
            "교환 파일의 512 KiB 상한을 초과했습니다.");
    const std::string encoded = result.at("content_base64");
    Require(encoded.size() <= ((SourceLimit + 2) / 3) * 4, "교환 파일의 base64 상한을 초과했습니다.");
    const wxMemoryBuffer decoded = wxBase64Decode(encoded.data(), encoded.size(), wxBase64DecodeMode_Strict);
    Require(decoded.GetDataLen() == static_cast<std::size_t>(expected),
            "교환 파일의 base64 또는 원문 크기가 다릅니다.");
    const std::string raw(static_cast<const char*>(decoded.GetData()), decoded.GetDataLen());
    Require(DisplayMesh::Sha256(raw) == result.at("sha256").get<std::string>(),
            "교환 파일의 SHA256이 서비스 응답과 다릅니다.");
    Require(result.at("sidecar").is_object() && result.at("sidecar").value("schema", "") == "rfad.network-export/0.1",
            "조건 sidecar의 형식이 다릅니다.");
    const std::string sidecar = result.at("sidecar").dump(2) + "\n";
    Require(sidecar.size() <= 1024U * 1024U, "조건 sidecar의 1 MiB 표시/저장 상한을 초과했습니다.");
    const Path selected(path.ToStdWstring());
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
    const Path storage = ActualDirectory(Path(workspace.ToStdWstring()));
    Require(
        !Inside(parent, storage),
        "프로젝트 작업 영역 안에는 교환 파일을 저장하지 않습니다. 원본/과거 자료 보존을 위해 외부 폴더를 선택하세요.");
    DisplayMesh::Handles directories;
    Path current = parent.root_path();
    directories.Open(current, true);
    for (const auto& part : parent.relative_path())
    {
        current /= part;
        directories.Open(current, true);
    }
    const Path target = parent / selected.filename();
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

bool SaveNetworkExport(wxWindow* parent, const Json& result, const wxString& workspace)
{
    try
    {
        wxFileDialog chooser(parent, Display("복소 자료 내보내기"), wxEmptyString,
                             Display(result.at("file_name").get<std::string>()), Display("교환 파일 (*.*)|*.*"),
                             wxFD_SAVE);
        if (chooser.ShowModal() != wxID_OK)
        {
            return false;
        }
        WriteNetworkExportFiles(result, chooser.GetPath(), workspace);
        wxMessageBox(Display("교환 파일과 .conditions.json 조건 파일을 함께 저장했습니다.\nCSV 단독 재가져오기는 "
                             "기준면/Z0 전체 조건을 복원하지 않습니다. 전체 자료 교환에는 HDF5를 사용하세요."),
                     Display("내보내기 완료"), wxOK | wxICON_INFORMATION, parent);
        return true;
    }
    catch (const std::exception& error)
    {
        wxMessageBox(Display(error.what()), Display("내보내기를 완료하지 못함"), wxOK | wxICON_ERROR, parent);
        return false;
    }
}
