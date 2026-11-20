/** @file @brief native 파일 선택, 표시 상태와 서비스 요청을 연결한다. */
#include "large_result_dialog.h"
#include "field_result_view.h"
#include "network_chart.h"
#include "frequency_display.h"
#include "result_presentation.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <windows.h>
#include <bcrypt.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <fstream>
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/filedlg.h>
#include <wx/listctrl.h>
#include <wx/simplebook.h>
#include <wx/sizer.h>
#include <wx/spinctrl.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <wx/weakref.h>

namespace
{
constexpr std::uintmax_t FieldLimit = 1056ULL * 1024 * 1024;
constexpr std::uintmax_t CurveLimit = 32ULL * 1024 * 1024;
constexpr std::uintmax_t PackageLimit = FieldLimit + 4140;

/** @brief UI가 선택한 원문을 같은 프로젝트의 배타적인 수신 파일로 복사한다. */
std::string CopyIncoming(const std::filesystem::path& source, const std::filesystem::path& destination,
                         std::uintmax_t limit)
{
    const auto part = std::filesystem::path(destination.wstring() + L".partial");
    try
    {
        const auto sourceAttributes = GetFileAttributesW(source.c_str());
        if (sourceAttributes == INVALID_FILE_ATTRIBUTES ||
            (sourceAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) != 0)
        {
            return "링크가 없는 결과 파일을 선택하십시오.";
        }
        const auto size = std::filesystem::file_size(source);
        if (size < 8 || size > limit)
        {
            return "선택한 파일이 등록 크기 상한을 벗어났습니다.";
        }
        const auto directory = destination.parent_path();
        for (auto ancestor = directory.parent_path(); !ancestor.empty(); ancestor = ancestor.parent_path())
        {
            const auto attributes = GetFileAttributesW(ancestor.c_str());
            if (attributes == INVALID_FILE_ATTRIBUTES || (attributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
            {
                return "프로젝트 수신 경로는 연결 폴더를 포함할 수 없습니다.";
            }
            if (ancestor == ancestor.root_path())
            {
                break;
            }
        }
        std::filesystem::create_directory(directory);
        const auto attributes = GetFileAttributesW(directory.c_str());
        if (attributes == INVALID_FILE_ATTRIBUTES || (attributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
        {
            return "결과 수신 폴더가 연결 경로를 포함합니다.";
        }
        if (std::filesystem::space(directory).available < size * 3)
        {
            return "원문을 봉인할 작업 영역의 여유 공간이 부족합니다.";
        }
        if (!std::filesystem::copy_file(source, part))
        {
            return "같은 수신 토큰의 복사본이 이미 있습니다.";
        }
        if (std::filesystem::file_size(part) != size)
        {
            std::filesystem::remove(part);
            return "복사하는 동안 원문의 길이가 바뀌었습니다.";
        }
        std::filesystem::rename(part, destination);
        return {};
    }
    catch (const std::filesystem::filesystem_error&)
    {
        std::error_code ignored;
        std::filesystem::remove(part, ignored);
        return "선택한 결과의 복사에 실패했습니다. 파일과 작업 영역을 확인하십시오.";
    }
}

/** @brief 전송 사본의 전체 SHA256을 1 MiB 버퍼로 계산한다. */
bool HasPackageDigest(const std::filesystem::path& path, std::uintmax_t size, const std::string& digest)
{
    std::ifstream input(path, std::ios::binary);
    std::vector<unsigned char> buffer(1024 * 1024);
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    if (!input || BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) < 0)
    {
        return false;
    }
    BCRYPT_HASH_HANDLE hash = nullptr;
    auto status = BCryptCreateHash(algorithm, &hash, nullptr, 0, nullptr, 0, 0);
    while (status >= 0 && size > 0)
    {
        const auto count = static_cast<ULONG>(std::min<std::uintmax_t>(size, buffer.size()));
        if (!input.read(reinterpret_cast<char*>(buffer.data()), count))
        {
            break;
        }
        status = BCryptHashData(hash, buffer.data(), count, 0);
        size -= count;
    }
    std::array<unsigned char, 32> value{};
    const bool finished = size == 0 && input.peek() == std::char_traits<char>::eof() && status >= 0 &&
                          BCryptFinishHash(hash, value.data(), static_cast<ULONG>(value.size()), 0) >= 0;
    if (hash != nullptr)
    {
        BCryptDestroyHash(hash);
    }
    BCryptCloseAlgorithmProvider(algorithm, 0);
    static constexpr char Hex[] = "0123456789abcdef";
    std::string actual;
    for (auto byte : value)
    {
        actual += Hex[byte >> 4];
        actual += Hex[byte & 0xf];
    }
    return finished && actual == digest;
}

/** @brief 검증한 임시 사본만 이동하며 목적지의 기존 파일은 보존한다. */
std::string CopyTransfer(const std::filesystem::path& source, const std::filesystem::path& destination,
                         const std::filesystem::path& temporary, std::uintmax_t size, const std::string& digest)
{
    const auto attrs = GetFileAttributesW(source.c_str());
    if (attrs == INVALID_FILE_ATTRIBUTES || (attrs & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) != 0)
    {
        return "봉인한 이관 원문을 열 수 없습니다.";
    }
    try
    {
        if (std::filesystem::exists(destination) || std::filesystem::file_size(source) != size ||
            !std::filesystem::copy_file(source, temporary))
        {
            return "새 저장 경로를 선택하고 원본 이관 상태를 확인하십시오.";
        }
        if (HasPackageDigest(temporary, size, digest) &&
            MoveFileExW(temporary.c_str(), destination.c_str(), MOVEFILE_WRITE_THROUGH))
        {
            return {};
        }
    }
    catch (const std::exception&)
    {
        /** @brief 임시 사본의 실패를 상태에 남기고 기존 파일은 건드리지 않는다. */
    }
    std::error_code ignored;
    std::filesystem::remove(temporary, ignored);
    return "이관 사본을 검증해 저장하지 못했습니다. 파일과 남은 공간을 확인하십시오.";
}
}

LargeResultDialog::LargeResultDialog(wxWindow* parent, std::filesystem::path project, std::string revision,
                                     DialogGateway gateway)
    : wxDialog(parent, wxID_ANY, Display("대용량 결과"), wxDefaultPosition, wxDefaultSize,
               wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER),
      m_project(std::move(project)), m_revision(std::move(revision)), m_gateway(std::move(gateway)), m_timer(this)
{
    StudioTheme::BindSurface(*this);
    auto* main = new wxBoxSizer(wxVERTICAL);
    auto* toolbar = new wxBoxSizer(wxHORIZONTAL);
    m_importField = new wxButton(this, wxID_ANY, Display("필드 HDF5 등록"));
    m_importTraces = new wxButton(this, wxID_ANY, Display("복소 곡선 HDF5 등록"));
    m_importPackage = new wxButton(this, wxID_ANY, Display("이관 파일 등록"));
    m_exportPackage = new wxButton(this, wxID_ANY, Display("선택 결과 이관..."));
    auto* reload = new wxButton(this, wxID_ANY, Display("목록 새로 고침"));
    toolbar->Add(m_importField, 0, wxRIGHT, FromDIP(8));
    toolbar->Add(m_importTraces, 0, wxRIGHT, FromDIP(8));
    toolbar->Add(m_importPackage, 0, wxRIGHT, FromDIP(8));
    toolbar->Add(reload);
    main->Add(toolbar, 0, wxEXPAND | wxALL, FromDIP(10));
    auto* content = new wxBoxSizer(wxHORIZONTAL);
    auto* side = new wxBoxSizer(wxVERTICAL);
    m_records = new wxListCtrl(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(245, -1)),
                               wxLC_REPORT | wxLC_SINGLE_SEL);
    m_records->SetName(Display("등록한 대용량 결과"));
    m_records->AppendColumn(Display("등록한 자료"), wxLIST_FORMAT_LEFT, FromDIP(150));
    m_records->AppendColumn(Display("유형"), wxLIST_FORMAT_LEFT, FromDIP(78));
    StudioTheme::Table(*m_records);
    side->Add(m_records, 1, wxEXPAND);
    side->Add(m_exportPackage, 0, wxEXPAND | wxTOP, FromDIP(8));
    m_details = new wxTextCtrl(this, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 139)),
                              wxTE_MULTILINE | wxTE_READONLY);
    m_details->SetName(Display("결과 원본과 당시 개정"));
    side->Add(m_details, 0, wxEXPAND | wxTOP, FromDIP(8));
    content->Add(side, 0, wxEXPAND | wxRIGHT, FromDIP(10));
    m_pages = new wxSimplebook(this);
    auto* empty = new wxPanel(m_pages);
    auto* emptyLayout = new wxBoxSizer(wxVERTICAL);
    emptyLayout->Add(new wxStaticText(empty, wxID_ANY, Display("등록한 자료를 선택하십시오.")),
                     0, wxALL, FromDIP(14));
    empty->SetSizer(emptyLayout);
    m_pages->AddPage(empty, Display("결과 선택"));
    m_field = new FieldResultView(m_pages);
    m_pages->AddPage(m_field, Display("필드 단면"));
    auto* curves = new wxPanel(m_pages);
    auto* graph = new wxBoxSizer(wxVERTICAL);
    auto* settings = new wxBoxSizer(wxHORIZONTAL);
    m_mode = new wxChoice(curves, wxID_ANY);
    m_mode->SetName(Display("복소 곡선 조회 모드"));
    m_mode->Append(Display("전체 범위 극값"));
    m_mode->Append(Display("원본 표본"));
    m_mode->SetSelection(0);
    m_metric = new wxChoice(curves, wxID_ANY);
    m_metric->SetName(Display("표시할 복소 성분"));
    m_metric->Append(Display("실수부 (Re)"));
    m_metric->Append(Display("허수부 (Im)"));
    m_metric->SetSelection(0);
    m_offset = new wxSpinCtrl(curves, wxID_ANY, "1", wxDefaultPosition, FromDIP(wxSize(102, -1)),
                              wxSP_ARROW_KEYS, 1, 100000, 1);
    m_offset->SetName(Display("원본 표본 시작 순번"));
    m_offset->Enable(false);
    m_readCurves = new wxButton(curves, wxID_ANY, Display("조회"));
    settings->Add(m_mode, 0, wxRIGHT, FromDIP(8));
    settings->Add(m_metric, 0, wxRIGHT, FromDIP(8));
    settings->Add(new wxStaticText(curves, wxID_ANY, Display("시작 표본")),
                  0, wxRIGHT | wxALIGN_CENTER_VERTICAL, FromDIP(4));
    settings->Add(m_offset, 0, wxRIGHT, FromDIP(8));
    settings->Add(m_readCurves);
    graph->Add(settings, 0, wxEXPAND | wxBOTTOM, FromDIP(8));
    m_chart = new NetworkChart(curves);
    m_chart->SetMinSize(FromDIP(wxSize(-1, 225)));
    graph->Add(m_chart, 1, wxEXPAND);
    m_sources = new wxListCtrl(curves, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 143)),
                               wxLC_REPORT | wxLC_SINGLE_SEL);
    m_sources->SetName(Display("비교 곡선 출처"));
    m_sources->AppendColumn(Display("곡선"), wxLIST_FORMAT_LEFT, FromDIP(184));
    m_sources->AppendColumn(Display("원본 표본"), wxLIST_FORMAT_RIGHT, FromDIP(95));
    m_sources->AppendColumn(Display("기준 임피던스"), wxLIST_FORMAT_LEFT, FromDIP(114));
    StudioTheme::Table(*m_sources);
    graph->Add(m_sources, 0, wxEXPAND | wxTOP, FromDIP(8));
    m_sourceDetail = new wxTextCtrl(curves, wxID_ANY, wxEmptyString, wxDefaultPosition,
                                    FromDIP(wxSize(-1, 66)), wxTE_MULTILINE | wxTE_READONLY);
    m_sourceDetail->SetName(Display("곡선 출처와 측정 조건"));
    graph->Add(m_sourceDetail, 0, wxEXPAND | wxTOP, FromDIP(4));
    curves->SetSizer(graph);
    m_pages->AddPage(curves, Display("복소 곡선 비교"));
    content->Add(m_pages, 1, wxEXPAND);
    main->Add(content, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(10));
    auto* footer = new wxBoxSizer(wxHORIZONTAL);
    m_status = new wxStaticText(this, wxID_ANY, wxEmptyString, wxDefaultPosition, wxDefaultSize,
                                wxST_NO_AUTORESIZE | wxST_ELLIPSIZE_END);
    footer->Add(m_status, 1, wxALIGN_CENTER_VERTICAL | wxRIGHT, FromDIP(8));
    footer->Add(new wxButton(this, wxID_CANCEL, Display("닫기")));
    main->Add(footer, 0, wxEXPAND | wxALL, FromDIP(10));
    SetSizer(main);
    SetMinSize(FromDIP(wxSize(830, 605)));
    SetClientSize(FromDIP(wxSize(1080, 700)));
    CentreOnParent();
    m_field->onSlice = [this](const Json& selection) { ReadField(selection); };
    m_importField->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { ChooseFile("field"); });
    m_importTraces->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { ChooseFile("traces"); });
    m_importPackage->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { ChooseFile("package"); });
    m_exportPackage->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { ChooseTransferDestination(); });
    reload->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { Reload(); });
    m_readCurves->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { ReadCurves(); });
    m_mode->Bind(wxEVT_CHOICE, [this](wxCommandEvent&)
    {
        m_offset->Enable(m_mode->GetSelection() == 1);
        ReadCurves();
    });
    m_metric->Bind(wxEVT_CHOICE, [this](wxCommandEvent&) { ReadCurves(); });
    m_records->Bind(wxEVT_LIST_ITEM_SELECTED, [this](wxListEvent& event) { Select(event.GetIndex()); });
    m_sources->Bind(wxEVT_LIST_ITEM_SELECTED, [this](wxListEvent& event)
    {
        const auto& row = m_record.at("details").at("curves").at(event.GetIndex());
        const auto note = [](const Json& value) { return value.is_string() ? value.get<std::string>() : "미정"; };
        m_sourceDetail->ChangeValue(Display("출처  " + note(row.at("source")) +
                                             "\n측정 조건  " + note(row.at("measurement"))));
    });
    m_chart->onMarker = [this](std::size_t series, int index, double frequency)
    {
        if (!m_curvePage.is_object())
        {
            return;
        }
        const auto& points = m_curvePage.at("pages").at(series).at("samples");
        for (const auto& point : points)
        {
            if (point.at("index") == index && point.at("valid") == true)
            {
                const auto scale = StudioFrequency::ForRange(frequency, frequency);
                const auto label = m_record.at("details").at("curves").at(series).at("label").get<std::string>();
                Status(label + " / " + StudioFrequency::Value(frequency, scale, 10) + " " + scale.unit +
                       " / Re " + ResultUi::Number(point.at("real"), 10) + " / Im " + ResultUi::Number(point.at("imag"), 10));
                break;
            }
        }
    };
    Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        if (!m_busy && m_job.empty() && !m_copy.valid())
        {
            EndModal(wxID_CANCEL);
        }
    }, wxID_CANCEL);
    Bind(wxEVT_CLOSE_WINDOW, [this](wxCloseEvent& event)
    {
        if (event.CanVeto() && (m_busy || m_copy.valid() || !m_job.empty()))
        {
            event.Veto();
            return;
        }
        event.Skip();
    });
    Bind(wxEVT_TIMER, &LargeResultDialog::Poll, this);
    m_timer.Start(100);
    Reload();
}

void LargeResultDialog::Status(const std::string& message, bool pending)
{
    m_busy = pending;
    m_status->SetLabel(Display(message));
    m_status->SetToolTip(Display(message));
    m_importField->Enable(!pending);
    m_importTraces->Enable(!pending);
    m_importPackage->Enable(!pending);
    m_exportPackage->Enable(!pending && m_record.is_object());
    m_records->Enable(!pending);
    m_readCurves->Enable(!pending);
    m_mode->Enable(!pending);
    m_metric->Enable(!pending);
    m_offset->Enable(!pending && m_mode->GetSelection() == 1);
}

void LargeResultDialog::Error(const Json& error)
{
    m_job.clear();
    m_transferDestination.clear();
    m_field->SetBusy(false);
    Status(DiagnosticMessage(error));
    if (!m_fixture.is_null())
    {
        SmokeFinish(DiagnosticMessage(error));
    }
}

void LargeResultDialog::Reload()
{
    if (m_busy)
    {
        return;
    }
    Status("프로젝트의 대용량 결과를 읽고 있습니다.", true);
    wxWeakRef<LargeResultDialog> weak(this);
    m_gateway("result.large.list", Json::object(), false, [weak](const Json& value)
    {
        if (!weak)
        {
            return;
        }
        weak->m_catalog = value.at("records");
        weak->m_record = nullptr;
        weak->m_pages->SetSelection(0);
        weak->m_details->Clear();
        weak->m_records->DeleteAllItems();
        long row = 0;
        for (const auto& record : weak->m_catalog)
        {
            weak->m_records->InsertItem(row, Display(record.at("name").get<std::string>()));
            weak->m_records->SetItem(row++, 1, Display(record.at("kind") == "field" ? "필드" : "복소 곡선"));
        }
        weak->Status(weak->m_catalog.empty() ? "등록한 결과가 없습니다." : "등록한 자료를 선택하십시오.");
    }, [weak](const Json& error) { if (weak) { weak->Error(error); } });
}

void LargeResultDialog::ChooseFile(const std::string& kind)
{
    wxFileDialog choose(this, Display("결과 원본 선택"), wxEmptyString, wxEmptyString,
                        Display(kind == "package" ? "TraceWave 결과 이관 (*.rfadres)|*.rfadres"
                                                  : "HDF5 파일 (*.h5;*.hdf5)|*.h5;*.hdf5"),
                        wxFD_OPEN | wxFD_FILE_MUST_EXIST);
    if (choose.ShowModal() == wxID_OK)
    {
        StartImport(std::filesystem::path(choose.GetPath().ToStdWstring()), kind);
    }
}

void LargeResultDialog::StartImport(const std::filesystem::path& file, const std::string& kind)
{
    if (m_busy)
    {
        return;
    }
    const auto token = Uuid();
    const auto name = Utf8(wxString(file.stem().wstring()));
    const auto sourceName = Utf8(wxString(file.filename().wstring()));
    if (name.empty() || name.size() > 512 || sourceName.size() > 512)
    {
        Error({{"message", "파일 이름은 UTF-8 512바이트 이내여야 합니다."}});
        return;
    }
    m_import = {{"token", token}, {"kind", kind}, {"name", name}, {"source_name", sourceName},
                {"revision_id", m_revision}};
    const auto destination = m_project / "result-inbox" / (token + ".h5");
    const auto limit = kind == "field" ? FieldLimit : kind == "traces" ? CurveLimit : PackageLimit;
    m_copy = std::async(std::launch::async, CopyIncoming, file, destination, limit);
    Status("선택한 원문을 복사하고 있습니다.", true);
}

void LargeResultDialog::ChooseTransferDestination()
{
    wxFileDialog choose(this, Display("선택한 원문과 출처를 이관"), wxEmptyString, Display("TraceWave-결과.rfadres"),
                        Display("TraceWave 결과 이관 (*.rfadres)|*.rfadres"), wxFD_SAVE);
    if (choose.ShowModal() == wxID_OK)
    {
        StartTransfer(std::filesystem::path(choose.GetPath().ToStdWstring()));
    }
}

void LargeResultDialog::StartTransfer(const std::filesystem::path& file)
{
    if (m_busy || !m_record.is_object())
    {
        return;
    }
    m_transferDestination = file;
    Status("등록 원문과 당시 출처를 확인해 이관 파일을 준비합니다.", true);
    wxWeakRef<LargeResultDialog> weak(this);
    m_gateway("result.large.transfer", {{"id", m_record.at("id")}}, true, [weak](const Json& value)
    {
        if (weak)
        {
            weak->m_job = value.at("job_id").get<std::string>();
        }
    }, [weak](const Json& error) { if (weak) { weak->Error(error); } });
}

void LargeResultDialog::SaveTransfer(const Json& artifact)
{
    const auto size = artifact.at("bytes").get<std::uintmax_t>();
    const auto& digest = artifact.at("sha256").get_ref<const std::string&>();
    if (!size || size > PackageLimit || digest.size() != 64)
    {
        Error({{"message", "이관 응답의 파일 크기 또는 SHA256이 올바르지 않습니다."}});
        return;
    }
    const auto source = m_project / "large-results" / m_record.at("id").get<std::string>() / "transfer.rfadres";
    const auto temporary = std::filesystem::path(m_transferDestination.wstring() + L"." + Display(Uuid()).ToStdWstring() + L".partial");
    m_copy = std::async(std::launch::async, CopyTransfer, source, m_transferDestination, temporary, size, digest);
    Status("이관 사본을 복사하고 SHA256을 확인합니다.", true);
}

bool LargeResultDialog::SameRecord(const Json& value) const
{
    return m_record.is_object() && value.value("id", Json()) == m_record.at("id");
}

void LargeResultDialog::Select(int index)
{
    if (m_busy || index < 0 || static_cast<std::size_t>(index) >= m_catalog.size())
    {
        return;
    }
    m_record = m_catalog.at(index);
    const auto reference = m_record.at("artifact");
    std::string origin;
    if (m_record.contains("origin"))
    {
        const auto& initial = m_record.at("origin");
        origin = "\n원래 프로젝트  " + initial.at("project_id").get<std::string>() +
                 "\n원래 개정  " + initial.at("revision_id").get<std::string>();
    }
    m_details->ChangeValue(Display("원문  " + m_record.at("source_name").get<std::string>() +
        "\n개정  " + m_record.at("revision_id").get<std::string>() +
        origin + "\nSHA256  " + reference.at("sha256").get<std::string>() +
        "\n제작·측정 조건 미정. 독립 물리 검증 전."));
    if (m_record.at("kind") == "traces")
    {
        m_pages->SetSelection(2);
        m_chart->Clear();
        m_curvePage = nullptr;
        m_sources->DeleteAllItems();
        m_sourceDetail->Clear();
        m_offset->SetValue(1);
        const auto& curves = m_record.at("details").at("curves");
        long row = 0;
        for (const auto& curve : curves)
        {
            m_sources->InsertItem(row, Display(curve.at("label").get<std::string>()));
            m_sources->SetItemTextColour(row, NetworkChart::SeriesColour(static_cast<std::size_t>(row)));
            m_sources->SetItem(row, 1, wxString::Format("%d", curve.at("count").get<int>()));
            m_sources->SetItem(row++, 2, curve.at("reference_ohm").is_null() ? Display("미정")
                : Display(ResultUi::Number(curve.at("reference_ohm"), 10) + " Ω"));
        }
        ReadCurves();
        return;
    }
    m_pages->SetSelection(1);
    m_field->Clear("등록한 필드의 기록 좌표를 확인하고 있습니다.");
    Status("필드 정보를 조회하고 있습니다.", true);
    wxWeakRef<LargeResultDialog> weak(this);
    m_gateway("result.large.field", {{"id", m_record.at("id")}}, false, [weak](const Json& value)
    {
        if (weak && weak->SameRecord(value))
        {
            weak->m_field->SetDescription(value);
            weak->Status("기록 성분과 단면을 선택하십시오.");
        }
    }, [weak](const Json& error) { if (weak) { weak->Error(error); } });
}

void LargeResultDialog::ReadField(const Json& selection)
{
    if (m_busy || !m_record.is_object())
    {
        return;
    }
    Status("선택한 필드 단면을 조회하고 있습니다.", true);
    m_field->SetBusy(true);
    wxWeakRef<LargeResultDialog> weak(this);
    m_gateway("result.large.slice", {{"id", m_record.at("id")}, {"selection", selection}}, false,
         [weak](const Json& value)
         {
             if (weak && weak->SameRecord(value))
             {
                 weak->m_field->SetBusy(false);
                 weak->m_field->SetSlice(value);
                 weak->Status("등록한 원문의 복소 단면을 표시합니다.");
             }
         }, [weak](const Json& error) { if (weak) { weak->Error(error); } });
}

void LargeResultDialog::ReadCurves()
{
    if (m_busy || !m_record.is_object() || m_record.at("kind") != "traces")
    {
        return;
    }
    const bool exact = m_mode->GetSelection() == 1;
    const std::string metric = m_metric->GetSelection() == 1 ? "imag" : "real";
    Status("복소 곡선의 원본 표본을 읽고 있습니다.", true);
    wxWeakRef<LargeResultDialog> weak(this);
    m_gateway("result.large.curves", {{"id", m_record.at("id")}, {"mode", exact ? "exact" : "overview"},
              {"offset", exact ? m_offset->GetValue()-1 : 0}, {"metric", metric}}, false,
         [weak, exact, metric](const Json& value)
         {
             if (!weak || !weak->SameRecord(value))
             {
                 return;
             }
             weak->m_curvePage = value;
             std::vector<wxString> labels;
             const auto& details = weak->m_record.at("details");
             for (const auto& curve : details.at("curves"))
             {
                 labels.push_back(Display(curve.at("label").get<std::string>()));
             }
             const auto unit = details.at("unit");
             const auto metricLabel = metric == "real" ? "실수부 (Re)" : "허수부 (Im)";
             weak->m_chart->SetMetric(metric, Display(std::string(metricLabel) + " / " +
                                                        (unit.is_null() ? "단위 미정" : unit.get<std::string>())));
             weak->m_chart->SetSeries(value.at("pages").get<std::vector<Json>>(), labels, true);
             weak->Status(exact ? "원본 표본을 각 곡선의 기록 순번과 주파수로 표시합니다."
                                : "구간별 원본 극값을 표시합니다. 원본 표본 모드에서 전체 값을 조회할 수 있습니다.");
         }, [weak](const Json& error) { if (weak) { weak->Error(error); } });
}

void LargeResultDialog::Poll(wxTimerEvent&)
{
    wxWeakRef<LargeResultDialog> weak(this);
    if (m_copy.valid() && m_copy.wait_for(std::chrono::milliseconds(0)) == std::future_status::ready)
    {
        const auto error = m_copy.get();
        if (!error.empty())
        {
            Error({{"message", error}});
            return;
        }
        if (!m_transferDestination.empty())
        {
            m_transferDestination.clear();
            Status("원문과 출처가 포함된 이관 사본을 저장했습니다.");
            return;
        }
        Status("원문과 블록 해시를 검증해 등록하고 있습니다.", true);
        m_gateway("result.large.register", m_import, true, [weak](const Json& value)
        {
            if (weak)
            {
                weak->m_job = value.at("job_id").get<std::string>();
            }
        }, [weak](const Json& error) { if (weak) { weak->Error(error); } });
    }
    if (!m_job.empty() && !m_poll)
    {
        m_poll = true;
        m_gateway("job.status", {{"job_id", m_job}}, false, [weak](const Json& value)
        {
            if (!weak)
            {
                return;
            }
            weak->m_poll = false;
            const auto state = value.at("state");
            if (state == "completed")
            {
                weak->m_job.clear();
                if (weak->m_transferDestination.empty())
                {
                    weak->Status("원문을 등록했습니다.");
                    weak->Reload();
                }
                else
                {
                    weak->SaveTransfer(value.at("events").back().at("operation_result").at("artifact"));
                }
            }
            else if (state == "failed" || state == "cancelled" || state == "interrupted")
            {
                weak->Error(value.at("events").back().value("error", Json{{"message", "등록을 완료하지 못했습니다."}}));
            }
        }, [weak](const Json& error)
        {
            if (weak)
            {
                weak->m_poll = false;
                weak->Error(error);
            }
        });
    }
    if (!m_fixture.is_null())
    {
        SmokeTick();
    }
}
