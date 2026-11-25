#include "prototype_manufacturing.h"

#include "prototype_service.h"

#include <SDL3/SDL.h>
#include <commdlg.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <filesystem>
#include <memory>
#include <stdexcept>
#include <string_view>
#include <utility>
#include <vector>

namespace
{
using Path = std::filesystem::path;
using Handle = std::unique_ptr<void, decltype(&CloseHandle)>;

constexpr std::array labels{"IPC-2581C + ODB++", "IPC-2581C", "ODB++"};
constexpr std::array<std::wstring_view, 3> formats{L"", L"ipc2581", L"odb"};

Path Utf8Path(std::string_view value)
{
    return Path(std::u8string(value.begin(), value.end()));
}

/** @brief 사용자가 지정한 KiCad 실행 파일과 새 후보 ZIP의 전체 경로를 받는다. */
Path PickFile(SDL_Window* window, bool save)
{
    std::vector<wchar_t> buffer(32768, L'\0');
    constexpr wchar_t defaultName[] = L"manufacturing.zip";
    if (save)
    {
        std::copy(std::begin(defaultName), std::end(defaultName), buffer.begin());
    }
    OPENFILENAMEW dialog{};
    dialog.lStructSize = sizeof(dialog);
    dialog.hwndOwner = static_cast<HWND>(SDL_GetPointerProperty(SDL_GetWindowProperties(window),
        SDL_PROP_WINDOW_WIN32_HWND_POINTER, nullptr));
    dialog.lpstrFile = buffer.data();
    dialog.nMaxFile = static_cast<DWORD>(buffer.size());
    dialog.lpstrFilter = save ? L"ZIP (*.zip)\0*.zip\0" : L"KiCad CLI (kicad-cli.exe)\0kicad-cli.exe\0";
    dialog.lpstrTitle = save ? L"새 제조 교환 후보 ZIP 저장" : L"KiCad 명령줄 실행 파일 선택";
    dialog.lpstrDefExt = save ? L"zip" : nullptr;
    dialog.Flags = OFN_EXPLORER | OFN_NOCHANGEDIR | OFN_PATHMUSTEXIST | OFN_NOREADONLYRETURN;
    if (!save)
    {
        dialog.Flags |= OFN_FILEMUSTEXIST;
    }
    if (!(save ? GetSaveFileNameW(&dialog) : GetOpenFileNameW(&dialog)))
    {
        if (CommDlgExtendedError())
        {
            throw std::runtime_error("제조 교환 파일 선택 창을 열지 못했습니다.");
        }
        return {};
    }
    return Path(buffer.data());
}

/** @brief 게시 manifest의 해시를 넘겨 기존 변환기를 시작하고 제한된 진단 메시지를 회수한다. */
std::string Convert(const Path& python, const Path& code, const Path& workspace, const Path& package,
    const Path& cli, const Path& destination, const std::string& hash, std::wstring_view format)
{
    try
    {
        std::wstring command = ServiceClient::Quote(python.native()) +
            L" -X utf8 -m rfad.adapters.exchange.manufacturing_export --quiet --input " + ServiceClient::Quote(package.native()) +
            L" --output " + ServiceClient::Quote(destination.native()) + L" --kicad-cli " + ServiceClient::Quote(cli.native()) +
            L" --workspace " + ServiceClient::Quote(workspace.native()) +
            L" --manifest-sha256 " + std::wstring(hash.begin(), hash.end());
        if (!format.empty())
        {
            command += L" --format ";
            command += format;
        }

        SECURITY_ATTRIBUTES inheritable{sizeof(SECURITY_ATTRIBUTES), nullptr, TRUE};
        HANDLE pipeRead = nullptr;
        HANDLE pipeWrite = nullptr;
        if (!CreatePipe(&pipeRead, &pipeWrite, &inheritable, 0))
        {
            throw std::runtime_error("변환 결과를 받는 파이프를 만들지 못했습니다.");
        }
        const Handle read(pipeRead, &CloseHandle);
        Handle write(pipeWrite, &CloseHandle);
        const Handle input(CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, &inheritable,
            OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr), &CloseHandle);
        if (!SetHandleInformation(read.get(), HANDLE_FLAG_INHERIT, 0) || input.get() == INVALID_HANDLE_VALUE)
        {
            throw std::runtime_error("변환기 입출력 경로를 준비하지 못했습니다.");
        }
        STARTUPINFOW start{};
        start.cb = sizeof(start);
        start.dwFlags = STARTF_USESTDHANDLES;
        start.hStdInput = input.get();
        start.hStdOutput = write.get();
        start.hStdError = write.get();
        PROCESS_INFORMATION process{};
        if (!CreateProcessW(python.c_str(), command.data(), nullptr, nullptr, TRUE, CREATE_NO_WINDOW,
            nullptr, code.c_str(), &start, &process))
        {
            throw std::runtime_error("제조 교환 Python 실행 파일과 소스 경로를 확인하세요.");
        }
        const Handle child(process.hProcess, &CloseHandle);
        CloseHandle(process.hThread);
        write.reset();
        std::array<char, 1024> buffer{};
        std::string diagnostic;
        DWORD bytes = 0;
        while (ReadFile(read.get(), buffer.data(), static_cast<DWORD>(buffer.size()), &bytes, nullptr) && bytes)
        {
            constexpr std::size_t limit = 2048;
            diagnostic.append(buffer.data(), bytes);
            if (diagnostic.size() > limit)
            {
                diagnostic.erase(0, diagnostic.size() - limit);
            }
        }
        DWORD codeValue = 0;
        if (WaitForSingleObject(child.get(), INFINITE) != WAIT_OBJECT_0 || !GetExitCodeProcess(child.get(), &codeValue))
        {
            throw std::runtime_error("변환기 종료 상태를 읽지 못했습니다.");
        }
        if (codeValue != 0)
        {
            return diagnostic.empty() ? "제조 교환 변환 실패. 종료 코드 " + std::to_string(codeValue)
                                      : "제조 교환 변환 실패. " + diagnostic;
        }
        return "제조 교환 후보 ZIP을 저장했습니다. 수신 검증 대기.";
    }
    catch (const std::exception& error)
    {
        return std::string("제조 교환 변환 실패. ") + error.what();
    }
}
}

void PrototypeManufacturing::chooseFormat()
{
    if (!active())
    {
        format_ = (format_ + 1) % labels.size();
    }
}

const char* PrototypeManufacturing::format() const
{
    return labels[format_];
}

void PrototypeManufacturing::select(const PrototypeExchange::Published& board)
{
    if (!active())
    {
        selected_ = board;
    }
}

void PrototypeManufacturing::update(SDL_Window* window, const PrototypeServiceOptions& options)
{
    if (active() && result_.wait_for(std::chrono::seconds(0)) == std::future_status::ready)
    {
        status_ = result_.get();
    }
    auto board = std::exchange(selected_, std::nullopt);
    if (!board)
    {
        return;
    }

    try
    {
        const auto manifest = Utf8Path(board->manifestUri);
        if (manifest.is_absolute() || manifest.has_root_path() || manifest.filename() != L"manifest.json")
        {
            throw std::runtime_error("게시된 제조 원문의 manifest 위치가 올바르지 않습니다.");
        }
        for (const auto& part : manifest)
        {
            if (part.native().find_first_of(L":\\") != std::wstring::npos || part == L"." || part == L"..")
            {
                throw std::runtime_error("게시된 제조 원문의 manifest 위치가 올바르지 않습니다.");
            }
        }
        const auto cli = PickFile(window, false);
        if (cli.empty())
        {
            status_ = "제조 교환 변환을 취소했습니다.";
            return;
        }
        if (CompareStringOrdinal(cli.filename().c_str(), -1, L"kicad-cli.exe", -1, TRUE) != CSTR_EQUAL)
        {
            throw std::runtime_error("KiCad의 kicad-cli.exe를 선택하세요.");
        }
        const auto destination = PickFile(window, true);
        if (destination.empty())
        {
            status_ = "제조 교환 변환을 취소했습니다.";
            return;
        }
        const auto python = Utf8Path(options.exchangePython ? options.exchangePython : options.python);
        const auto code = Utf8Path(options.source);
        const auto workspace = Utf8Path(options.workspace);
        const auto package = (workspace / manifest).parent_path();
        const auto format = formats[format_];
        const auto hash = std::move(board->manifest);
        status_ = "선택한 KiCad 보드의 제조 교환 후보를 생성하는 중";
        result_ = std::async(std::launch::async, Convert, python, code, workspace, package, cli, destination, hash, format);
    }
    catch (const std::exception& error)
    {
        status_ = std::string("제조 교환 변환 실패. ") + error.what();
    }
}
