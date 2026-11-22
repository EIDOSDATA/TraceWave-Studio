/** @file @brief 동일 해시 원문의 순차 청크 전송과 보존 작업 조회를 담당한다. */
#include "pcb_import_dialog.h"
#include "display_mesh.h"
#include "output_model.h"
#include "studio_support.h"
#include <wx/base64.h>
#include <wx/choice.h>
#include <wx/file.h>
#include <wx/filedlg.h>
#include <wx/filename.h>
#include <wx/listctrl.h>
#include <wx/textctrl.h>
#include <wx/weakref.h>
#include <algorithm>
#include <set>

namespace
{
/** @brief 파서가 정리한 IPC-2581 제조 구조와 지원 범위를 읽기 전용으로 표시한다. */
std::string IpcSummary(const Json& parsed)
{
    const auto& data = parsed.at("records").at(0).at("data");
    std::string text = "IPC-2581 Rev C 원본 검토 완료\n원본 단위 " +
        OutputUi::Text(data.at("units"), "미정") + " | 작성 도구 " + OutputUi::Text(data.at("writer"), "미정");
    text += "\n층 " + std::to_string(data.at("layers").size()) +
        "개 | 적층 " + std::to_string(data.at("stackups").size()) +
        "개 | 보드 정의 " + std::to_string(data.at("steps").size()) + "개";
    for (const auto& stack : data.at("stackups"))
    {
        const auto& thickness = stack.at("thickness_mm");
        text += "\n적층 " + OutputUi::Text(stack.at("name"), "이름 미정") +
            " | 적층층 " + std::to_string(stack.at("layers").size()) + "개";
        if (thickness.is_object())
        {
            text += " | " + Utf8(wxString::Format("%.6g mm", thickness.at("converted").get<double>()));
        }
    }
    for (const auto& board : data.at("steps"))
    {
        text += "\n" + OutputUi::Text(board.at("name"), "이름 미정") +
            " | 논리 넷 " + std::to_string(board.at("logical_nets").get<int>()) +
            "개 | 물리 넷 " + std::to_string(board.at("physical_nets").get<int>()) +
            "개 | 홀 " + std::to_string(board.at("holes").get<int>()) +
            "개 | 슬롯 " + std::to_string(board.at("slots").get<int>()) +
            "개 | 부품 " + std::to_string(board.at("components").get<int>()) + "개";
        for (const auto& [category, count] : board.at("hole_plating").items())
        {
            text += "\n  도금 구분 " + category + " " + std::to_string(count.get<int>()) + "개";
        }
    }
    for (const auto& layer : data.at("layers"))
    {
        text += "\n층 " + OutputUi::Text(layer.at("name"), "이름 미정") + " | " +
            OutputUi::Text(layer.at("layerFunction"), "기능 미정") + " | " +
            OutputUi::Text(layer.at("side"), "면 미정");
    }
    return text + "\n이 원본은 제조 구조를 확인하는 데 사용합니다. 설계 반영과 재출력은 후속 범위입니다.";
}
}

void PcbImportDialog::Browse()
{
    if (!Editable() || m_pending || Uncertain())
    {
        return;
    }
    const bool vendor = VendorFormat();
    const bool ipc = Format() == "ipc2581_revc";
    const auto filter = ipc ? "IPC-2581 Rev C XML (*.xml)|*.xml" :
        vendor ? "제조사 원본 (*.zip;*.dxf;*.spl;*.gbr)|*.zip;*.dxf;*.spl;*.gbr|모든 파일 (*.*)|*.*" :
                                "PCB / CAM (*.kicad_pcb;*.kicad_mod;*.gbr;*.gbrjob;*.drl;*.xnc)|"
                                "*.kicad_pcb;*.kicad_mod;*.gbr;*.gbrjob;*.drl;*.xnc|모든 파일 (*.*)|*.*";
    const long flags = wxFD_OPEN | wxFD_FILE_MUST_EXIST | ((vendor || ipc) ? 0 : wxFD_MULTIPLE);
    wxFileDialog dialog(this, Display("가져올 PCB / CAM 원문 파일"), wxEmptyString, wxEmptyString,
                        Display(filter), flags);
    if (dialog.ShowModal() != wxID_OK)
    {
        return;
    }
    wxArrayString paths;
    dialog.GetPaths(paths);
    LoadFiles(std::vector<wxString>(paths.begin(), paths.end()));
}

bool PcbImportDialog::LoadFiles(const std::vector<wxString>& paths)
{
    if (!Editable() || m_pending || Uncertain() || paths.empty() || paths.size() > 40)
    {
        return false;
    }
    try
    {
        std::vector<File> files;
        std::set<wxString> names;
        std::size_t total = 0;
        for (const auto& path : paths)
        {
            const auto name = wxFileName(path).GetFullName();
            if (!names.insert(name.Lower()).second)
            {
                throw std::runtime_error("같은 원문 파일 이름을 중복 선택할 수 없습니다.");
            }
            wxFile file(path, wxFile::read);
            const auto size = file.IsOpened() ? file.Length() : wxInvalidOffset;
            if (size <= 0 || size > 16 * 1024 * 1024 || total + static_cast<std::size_t>(size) > 16 * 1024 * 1024)
            {
                throw std::runtime_error("원문 합계는 16 MiB 이하이며 비어 있지 않은 읽기 가능한 파일이어야 합니다.");
            }
            File loaded{Utf8(name), std::string(static_cast<std::size_t>(size), '\0'), {}};
            if (file.Read(loaded.bytes.data(), loaded.bytes.size()) != size || file.Length() != size)
            {
                throw std::runtime_error("파일을 읽는 동안 길이가 바뀌었습니다. 원문을 다시 선택하세요.");
            }
            loaded.sha256 = DisplayMesh::Sha256(loaded.bytes);
            total += loaded.bytes.size();
            files.push_back(std::move(loaded));
        }
        if (!m_upload.empty())
        {
            if (!m_uploadState.is_object() || m_uploadState.value("status", "") != "uploading")
            {
                throw std::runtime_error(
                    "보존된 원문은 교체하지 않습니다. 새 전송을 선택한 뒤 다른 파일을 선택하세요.");
            }
            const auto expected = m_uploadState.value("files", Json::array());
            if (expected.size() != files.size())
            {
                throw std::runtime_error("이어 보내기는 이전 전송과 같은 파일 전체를 선택해야 합니다.");
            }
            for (const auto& row : expected)
            {
                const auto found = std::find_if(files.begin(), files.end(),
                                                [&row](const File& file)
                                                {
                                                    return file.name == row.at("path");
                                                });
                if (found == files.end() || found->bytes.size() != row.at("bytes").get<std::size_t>() ||
                    found->sha256 != row.at("sha256"))
                {
                    throw std::runtime_error(
                        "선택한 파일의 이름 / 길이 / SHA256이 이전 원문과 다릅니다. 이어 보내기를 중단합니다.");
                }
            }
        }
        m_files = std::move(files);
        Changed();
        RenderFiles();
        SetStatus(m_upload.empty() ? "선택한 원문 바이트를 전송할 준비가 되었습니다. 전송 이후 별도 읽기를 시작하세요."
                                   : "이전 원문과 일치합니다. 확인된 마지막 바이트부터 이어 보낼 수 있습니다.");
        UpdateActions();
        return true;
    }
    catch (const std::exception& error)
    {
        SetStatus(error.what());
        return false;
    }
}

void PcbImportDialog::RenderFiles()
{
    m_fileTable->DeleteAllItems();
    Json files = Json::array();
    if (m_uploadState.is_object())
    {
        files = m_uploadState.value("files", Json::array());
    }
    else
    {
        for (const auto& file : m_files)
        {
            files.push_back(
                {{"path", file.name}, {"bytes", file.bytes.size()}, {"received", 0}, {"sha256", file.sha256}});
        }
    }
    for (const auto& file : files)
    {
        const long row =
            m_fileTable->InsertItem(m_fileTable->GetItemCount(), Display(file.at("path").get<std::string>()));
        m_fileTable->SetItem(row, 1, Display(OutputUi::Text(file.at("bytes"))));
        m_fileTable->SetItem(row, 2, Display(OutputUi::Text(file.at("received"))));
        m_fileTable->SetItem(row, 3, Display(file.at("sha256").get<std::string>()));
    }
}

void PcbImportDialog::Upload()
{
    if (!Editable() || m_pending || Uncertain() || m_files.empty())
    {
        return;
    }
    m_uploading = true;
    if (!m_upload.empty())
    {
        UploadNext();
        return;
    }
    Json files = Json::array();
    for (const auto& file : m_files)
    {
        files.push_back({{"path", file.name}, {"bytes", file.bytes.size()}, {"sha256", file.sha256}});
    }
    Request("pcb.import.begin", {{"format", Format()}, {"files", files}}, true,
            [this](const Json& response)
            {
                m_upload = response.at("upload_id").get<std::string>();
                ReadUpload(m_upload, true);
            });
}

void PcbImportDialog::UploadNext()
{
    if (!Editable() || m_pending || Uncertain() || !m_uploadState.is_object())
    {
        return;
    }
    try
    {
        for (const auto& row : m_uploadState.at("files"))
        {
            const auto offset = row.at("received").get<std::size_t>();
            const auto total = row.at("bytes").get<std::size_t>();
            if (offset >= total)
            {
                continue;
            }
            const auto path = row.at("path").get<std::string>();
            const auto file = std::find_if(m_files.begin(), m_files.end(),
                                           [&path](const File& candidate)
                                           {
                                               return candidate.name == path;
                                           });
            if (file == m_files.end() || file->sha256 != row.at("sha256") || file->bytes.size() != total)
            {
                throw std::runtime_error("이어 보낼 원문을 다시 선택하여 전체 해시를 확인하세요.");
            }
            const std::size_t count = std::min<std::size_t>(256U * 1024U, total - offset);
            const auto encoded = wxBase64Encode(file->bytes.data() + offset, count);
            Request(
                "pcb.import.chunk",
                {{"upload_id", m_upload}, {"path", path}, {"offset", offset}, {"content_base64", Utf8(encoded)}}, true,
                [this, path, offset, count](const Json& response)
                {
                    if (response.value("upload_id", "") != m_upload || response.value("path", "") != path ||
                        response.value("received", std::size_t(0)) != offset + count)
                    {
                        throw std::runtime_error("원문 전송 응답의 위치가 다릅니다. 같은 요청 영수증을 확인하세요.");
                    }
                    for (auto& item : m_uploadState.at("files"))
                    {
                        if (item.at("path") == path)
                        {
                            item["received"] = offset + count;
                        }
                    }
                    RenderFiles();
                    UploadNext();
                });
            return;
        }
        m_uploading = false;
        m_dirty = false;
        SetStatus("원문 전체 전송이 완료되었습니다. '보존 원문 읽기'로 별도 읽기 작업을 시작하세요.");
        UpdateActions();
    }
    catch (const std::exception& error)
    {
        m_uploading = false;
        SetStatus(error.what());
        UpdateActions();
    }
}

void PcbImportDialog::Parse()
{
    if (!Editable() || m_pending || Uncertain() || m_upload.empty())
    {
        return;
    }
    Request("pcb.import.parse", {{"upload_id", m_upload}}, true,
            [this](const Json& response)
            {
                if (response.value("upload_id", "") != m_upload || !response.contains("job_id"))
                {
                    throw std::runtime_error("읽기 작업의 원문 전송을 확인할 수 없습니다.");
                }
                ReadUpload(m_upload);
            });
}

void PcbImportDialog::ReadUpload(const std::string& identity, bool resume)
{
    if (!Editable() || m_pending || Uncertain())
    {
        return;
    }
    m_upload = identity;
    Request("pcb.import.get", {{"upload_id", identity}}, false,
            [this, identity, resume](const Json& response)
            {
                if (m_upload != identity || response.value("upload_id", "") != identity)
                {
                    return;
                }
                RenderUpload(response);
                if (resume)
                {
                    UploadNext();
                }
            });
}

void PcbImportDialog::RenderUpload(const Json& response)
{
    m_uploadState = response;
    RenderFiles();
    auto found = std::find(m_uploadIds.begin(), m_uploadIds.end(), m_upload);
    if (found == m_uploadIds.end())
    {
        const auto files = response.value("files", Json::array());
        const auto name = files.empty() ? std::string("보존한 원문 전송")
                                        : files.front().value("path", std::string("보존한 원문 전송"));
        m_uploadIds.push_back(m_upload);
        m_uploadChoice->Append(
            Display(name + (files.size() > 1 ? " 외 " + std::to_string(files.size() - 1) + "개" : "")));
        found = m_uploadIds.end() - 1;
    }
    m_uploadChoice->SetSelection(static_cast<int>(found - m_uploadIds.begin()));
    const auto format = response.value("format", "");
    const auto selected = std::find(m_formats.begin(), m_formats.end(), format);
    if (selected != m_formats.end())
    {
        m_format->SetSelection(static_cast<int>(selected - m_formats.begin()));
        DescribeFormat();
    }
    const auto parse = response.value("parse_state", Json(nullptr));
    std::string summary = "원문 상태: " + OutputUi::State(response.value("status", "unknown")) + "\n읽기 작업: " +
                          OutputUi::State(parse.is_string() ? parse.get<std::string>() : "not_started");
    if (response.value("parsed", Json(nullptr)).is_object())
    {
        RenderMapping(response);
        if (format == "ipc2581_revc")
        {
            summary += "\n" + IpcSummary(response.at("parsed"));
        }
        else
        {
            summary += "\n읽기 완료. 층 / 넷을 직접 선택하고 손실 항목을 확인한 뒤 변환 후보를 검토하세요.";
        }
        m_poll.Stop();
    }
    else if (parse == "queued" || parse == "running")
    {
        m_poll.Start(600);
        summary += "\n보존 원문을 읽는 중입니다. 이 창을 닫아도 보존된 작업 목록에서 다시 확인할 수 있습니다.";
    }
    else
    {
        m_poll.Stop();
    }
    if (!response.value("error", Json(nullptr)).is_null())
    {
        summary += "\n" + DiagnosticMessage(response.at("error"));
    }
    if (!response.value("applied_revision", Json(nullptr)).is_null())
    {
        summary += "\n이미 적용한 원문입니다. 같은 가져오기를 중복 적용하지 않습니다.";
    }
    m_summary->ChangeValue(Display(summary));
    m_raw->ChangeValue(Display(response.dump(2)));
    std::string sources =
        "원문 파일은 이름 / 바이트 / SHA256으로 보존됩니다. 제작 / 측정 / RF 검증을 뜻하지 않습니다.\n";
    for (const auto& file : response.value("files", Json::array()))
    {
        sources += "\n" + file.at("path").get<std::string>() + "\nSHA256: " + file.at("sha256").get<std::string>();
    }
    m_source->ChangeValue(Display(sources));
    SetStatus(summary);
    UpdateActions();
}

void PcbImportDialog::Poll(wxTimerEvent&)
{
    if (!m_closed && Editable() && !m_pending && !Uncertain() && !m_upload.empty())
    {
        ReadUpload(m_upload);
    }
}
