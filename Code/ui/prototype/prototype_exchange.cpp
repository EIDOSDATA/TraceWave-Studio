#include "prototype_exchange.h"

#include <algorithm>
#include <cstdio>
#include <stdexcept>
#include <utility>

namespace
{
using nlohmann::json;

enum class Kind { drawing, board, footprint, cam };

struct Format
{
    const char* label;
    const char* key;
    const char* profile;
    const char* suffix;
    Kind kind;
};

constexpr Format formats[] =
{
    {"PDF 도면", "pdf", "rfad.exchange.drawing/0.1", ".pdf", Kind::drawing},
    {"SVG 도면", "svg", "rfad.exchange.drawing/0.1", ".svg", Kind::drawing},
    {"DXF 도면", "dxf", "rfad.exchange.drawing/0.1", ".dxf", Kind::drawing},
    {"KiCad 보드", "kicad_pcb", "rfad.exchange.kicad-board/0.1", ".kicad_pcb", Kind::board},
    {"KiCad 풋프린트", "kicad_mod", "rfad.exchange.kicad-footprint/0.1", ".kicad_mod", Kind::footprint},
    {"Gerber / XNC / Job", "gerber_job", "rfad.exchange.cam/0.1", ".gbrjob", Kind::cam}
};

bool isHash(const json& value)
{
    if (!value.is_string())
    {
        return false;
    }
    const auto& text = value.get_ref<const std::string&>();
    return text.size() == 64 && text.find_first_not_of("0123456789abcdef") == std::string::npos;
}

std::string diagnostic(const json& error)
{
    const auto data = error.value("data", json::object());
    const auto code = data.value("domain_code", error.value("code", json(nullptr)).is_string()
        ? error.at("code").get<std::string>() : "");
    const auto message = data.value("message_ko", error.value("message_ko",
        error.value("message", "서비스 상태를 확인하세요.")));
    return code.empty() ? message : code + " " + message;
}
}

const char* PrototypeExchange::name() const
{
    return formats[format_].label;
}

bool PrototypeExchange::canMove(int direction) const
{
    static_assert(std::tuple_size_v<decltype(published_)> == std::size(formats));
    return !active() && (direction < 0 ? format_ > 0 : format_ + 1 < std::size(formats));
}

void PrototypeExchange::moveFormat(int direction)
{
    if (canMove(direction))
    {
        format_ = direction < 0 ? format_ - 1 : format_ + 1;
        status_.clear();
    }
}

const PrototypeExchange::Footprint* PrototypeExchange::footprint() const
{
    return footprints_.empty() ? nullptr : &footprints_[footprintIndex_];
}

bool PrototypeExchange::canMoveFootprint(int direction) const
{
    return choosingFootprint() && footprint() &&
        (direction < 0 ? footprintIndex_ > 0 : footprintIndex_ + 1 < footprints_.size());
}

void PrototypeExchange::moveFootprint(int direction)
{
    if (canMoveFootprint(direction))
    {
        footprintIndex_ = direction < 0 ? footprintIndex_ - 1 : footprintIndex_ + 1;
    }
}

bool PrototypeExchange::canApprove(const std::string& revision) const
{
    return phase_ == Phase::approval && revision_ == revision;
}

bool PrototypeExchange::canCancel() const
{
    return active() && phase_ != Phase::list && phase_ != Phase::record && !cancelRequested_;
}

void PrototypeExchange::startReview(const std::string& project, const std::string& revision)
{
    if (!active())
    {
        project_ = project;
        revision_ = revision;
        phase_ = Phase::seal;
        status_ = "출력 입력 개정을 봉인하는 중";
    }
    else if (choosingFootprint() && footprint() && project_ == project && revision_ == revision)
    {
        beginPreview({{"footprint_id", footprint()->id}});
    }
}

void PrototypeExchange::approve(const std::string& revision)
{
    if (canApprove(revision))
    {
        phase_ = Phase::build;
        status_ = "승인한 출력의 생성을 요청하는 중";
    }
}

void PrototypeExchange::startVerify(const std::string& project)
{
    if (!active() && published())
    {
        project_ = project;
        phase_ = Phase::verify;
        status_ = "게시한 원본의 재검수를 요청하는 중";
    }
}

void PrototypeExchange::reload(const std::string& project)
{
    if (!active())
    {
        project_ = project;
        listOffset_ = 0;
        latestTime_ = 0;
        latestId_.clear();
        phase_ = Phase::list;
        status_ = "선택한 형식의 최신 게시 기록을 읽는 중";
    }
}

void PrototypeExchange::cancel()
{
    if (canCancel())
    {
        if (job_.Empty() && pending_ == Request::none)
        {
            finish("출력 실행 전에 취소했습니다.");
        }
        else
        {
            cancelRequested_ = true;
            status_ = "출력 취소 요청 중";
        }
    }
}

void PrototypeExchange::checkRevision(const std::string& revision)
{
    if ((choosingFootprint() || phase_ == Phase::approval) && revision_ != revision)
    {
        finish("개정이 바뀌었습니다. 새 출력 입력을 검토하세요.");
    }
}

json PrototypeExchange::snapshotInput() const
{
    return {{"snapshot_id", snapshot_.at("snapshot_id")}, {"content_hash", snapshot_.at("content_hash")}};
}

/** @brief 이 클라이언트가 이미 접수한 작업과 새 요청을 한 서비스 파이프로 전송한다. */
bool PrototypeExchange::send(PrototypeService& service)
{
    using namespace std::chrono_literals;
    if (!active() || pending_ != Request::none || choosingFootprint() || phase_ == Phase::approval)
    {
        return false;
    }
    bool sent = false;
    const json context{{"project_id", project_}};
    if (!job_.Empty())
    {
        if (cancelRequested_ && !cancelSent_)
        {
            sent = service.request("job.cancel", json::object(),
                {{"job_id", job_.Id()}, {"reason", "GUI 출력 작업 취소"}}, true);
            pending_ = Request::cancel;
        }
        else if (job_.BeginPoll(Studio::Clock::now(), cancelSent_ ? 50ms : 100ms))
        {
            sent = service.request("job.status", json::object(), {{"job_id", job_.Id()}});
            pending_ = Request::poll;
        }
        else
        {
            return false;
        }
    }
    else
    {
        const auto& format = formats[format_];
        pending_ = Request::acceptJob;
        switch (phase_)
        {
            case Phase::seal:
                sent = service.request("snapshot.create", context,
                    {{"expected_revision", revision_}, {"description", std::string("시제품 출력 입력 / ") + format.label}}, true);
                break;
            case Phase::context:
                sent = service.request("export.context", context, {{"snapshot", snapshotInput()}});
                pending_ = Request::context;
                break;
            case Phase::preview:
                sent = service.request("export.preview", context, input_, true);
                break;
            case Phase::build:
                sent = service.request("export.build", context, input_, true);
                break;
            case Phase::verify:
                sent = service.request("export.verify", context,
                    {{"job_id", published()->job}, {"manifest_sha256", published()->manifest}}, true);
                break;
            case Phase::list:
                sent = service.request("export.list", context, {{"format", format.key}, {"offset", listOffset_}});
                pending_ = Request::list;
                break;
            case Phase::record:
                sent = service.request("export.get", context, {{"job_id", latestId_}});
                pending_ = Request::record;
                break;
            default:
                break;
        }
    }
    if (!sent)
    {
        finish("출력 요청을 보내지 못했습니다. 게시 상태를 다시 확인하세요.");
    }
    return sent;
}

bool PrototypeExchange::readReply(PrototypeService& service)
{
    if (pending_ == Request::none)
    {
        return true;
    }
    const auto reply = service.takeReply();
    if (reply.is_null())
    {
        return false;
    }
    const auto request = std::exchange(pending_, Request::none);
    try
    {
        if (reply.contains("error"))
        {
            throw std::runtime_error(diagnostic(reply.at("error")));
        }
        const auto& result = reply.at("result");
        switch (request)
        {
            case Request::acceptJob:
                job_.Assign(result.at("job_id").get<std::string>());
                std::printf("Exchange accepted: phase=%d job=%s format=%s\n", static_cast<int>(phase_),
                    job_.Id().c_str(), formats[format_].key);
                break;
            case Request::poll:
                acceptStatus(result);
                break;
            case Request::context:
                if (cancelRequested_)
                {
                    finish("출력 실행 전에 취소했습니다.");
                }
                else
                {
                    acceptContext(result);
                }
                break;
            case Request::cancel:
                if (result.at("job_id") != job_.Id())
                {
                    throw std::runtime_error("출력 취소 영수증의 작업 ID가 다릅니다.");
                }
                cancelSent_ = true;
                status_ = "출력 작업자 종료를 확인하는 중";
                break;
            case Request::list:
                acceptList(result);
                break;
            case Request::record:
            {
                if (result.at("project_id") != project_ || result.at("format") != formats[format_].key ||
                    result.at("operation_method") != "export.build" || result.at("state") != "completed")
                {
                    throw std::runtime_error("게시 기록의 소유 프로젝트 또는 출력 상태가 다릅니다.");
                }
                const auto& manifest = result.at("manifest_sha256");
                if (!isHash(manifest))
                {
                    throw std::runtime_error("게시 기록의 manifest 해시가 올바르지 않습니다.");
                }
                acceptPublished(result.at("result"), latestId_, manifest);
                finish("이전에 게시한 출력의 출처를 읽었습니다.");
                break;
            }
            case Request::none:
                break;
        }
    }
    catch (const std::exception& error)
    {
        std::string status = std::string("출력 조회 또는 요청 실패. ") + error.what();
        if (request == Request::poll && !job_.Empty())
        {
            job_.AbandonPoll();
            status_ = std::move(status);
        }
        else if (request == Request::cancel)
        {
            cancelRequested_ = false;
            cancelSent_ = false;
            status_ = std::move(status);
        }
        else
        {
            finish(std::move(status));
        }
    }
    return true;
}

/** @brief 고정 입력의 서비스 기본값과 저장된 도면 주석을 사용한다. */
void PrototypeExchange::acceptContext(const json& result)
{
    if (result.at("project_id") != project_ || result.at("revision_id") != revision_ ||
        result.at("source_revision_id") != revision_ || result.at("source_snapshot") != snapshot_)
    {
        throw std::runtime_error("출력 문맥이 봉인한 개정과 다릅니다.");
    }
    auto options = json::object();
    const auto kind = formats[format_].kind;
    if (kind == Kind::drawing)
    {
        options = result.at("default_options");
        const auto& annotations = result.at("drawing_annotations").at("saved");
        if (!annotations.is_null())
        {
            const auto& view = annotations.at("view");
            auto& views = options.at("views");
            if (std::find(views.begin(), views.end(), view) == views.end())
            {
                views.push_back(view);
            }
            if (annotations.contains("placement"))
            {
                options.update(annotations.at("placement").at("paper"));
            }
            options["annotations"] = annotations;
        }
    }
    else if (kind == Kind::cam)
    {
        options["layer_ids"] = result.at("pcb").at("default_cam_layer_ids");
    }
    else if (kind == Kind::footprint)
    {
        const auto& choices = result.at("pcb").at("footprints");
        if (!choices.is_array())
        {
            throw std::runtime_error("봉인 입력의 풋프린트 목록을 확인할 수 없습니다.");
        }
        std::vector<Footprint> footprints;
        footprints.reserve(choices.size());
        for (const auto& row : choices)
        {
            Footprint item{row.at("id").get<std::string>(), row.at("name").get<std::string>()};
            if (item.id.empty() || item.name.empty() ||
                std::ranges::find(footprints, item.id, &Footprint::id) != footprints.end())
            {
                throw std::runtime_error("봉인 입력의 풋프린트 이름 또는 식별자가 올바르지 않습니다.");
            }
            footprints.push_back(std::move(item));
        }
        if (footprints.empty())
        {
            finish("이 개정에 저장된 풋프린트가 없습니다.");
            return;
        }
        footprints_ = std::move(footprints);
        phase_ = Phase::chooseFootprint;
        status_ = "봉인한 목록에서 출력할 풋프린트를 고르고 선택 검토를 누르세요.";
        return;
    }
    beginPreview(std::move(options));
}

/** @brief 도면 옵션이나 선택한 풋프린트의 UUID를 같은 승인 경로로 전달한다. */
void PrototypeExchange::beginPreview(json options)
{
    const auto& format = formats[format_];
    input_ = {{"profile", format.profile}, {"format", format.key}, {"snapshot", snapshotInput()},
        {"options", std::move(options)}};
    phase_ = Phase::preview;
    status_ = "봉인한 출력의 포함 범위와 제외 항목을 검토하는 중";
}

void PrototypeExchange::acceptStatus(const json& result)
{
    if (!job_.EndPoll(result.at("job_id").get<std::string>()))
    {
        throw std::runtime_error("출력 상태 응답의 작업 ID가 다릅니다.");
    }
    const auto state = result.at("state").get<std::string>();
    const auto& events = result.at("events");
    if (!events.is_array() || events.empty() || events.back().at("state") != state)
    {
        throw std::runtime_error("출력 작업의 상태 이력이 올바르지 않습니다.");
    }
    const bool worker = result.value("native_worker_attached", false);
    if ((phase_ == Phase::build || phase_ == Phase::verify) && (observedState_ != state || observedWorker_ != worker))
    {
        std::printf("Exchange job: job=%s state=%s worker=%d\n", job_.Id().c_str(), state.c_str(), worker ? 1 : 0);
        observedState_ = state;
        observedWorker_ = worker;
    }
    const auto& last = events.back();
    if (state == "completed")
    {
        try
        {
            complete(last.at("operation_result"));
        }
        catch (const std::exception& error)
        {
            finish(std::string("출력 결과를 확인할 수 없습니다. ") + error.what());
        }
    }
    else if (state == "cancelled")
    {
        const bool confirmed = last.value("termination_confirmed", false) && !last.value("outcome_unknown", false);
        const bool ran = std::any_of(events.begin(), events.end(), [](const json& row)
        {
            return row.at("state") == "running";
        });
        finish(confirmed ? "출력 취소 완료. 작업자 종료를 확인했습니다."
                         : ran ? "출력이 취소됐습니다. 작업자 종료 확인이 필요합니다." : "출력 실행 전에 취소했습니다.");
    }
    else if (state == "failed" || state == "interrupted" || state == "timeout")
    {
        finish(last.value("outcome_unknown", false) ? "출력 작업이 중단됐습니다. 작업자 종료 확인이 필요합니다."
            : "출력 작업 실패. " + diagnostic(last.value("error", json::object())));
    }
    else if (phase_ == Phase::build || phase_ == Phase::verify)
    {
        status_ = cancelRequested_ || state == "cancel_requested" ? "출력 작업자 종료를 확인하는 중" :
            (worker ? "출력 작업자 실행 중" : "출력 작업 대기 또는 시작 중");
    }
}

/** @brief 검토와 같은 옵션으로 승인하고 검수 보고서는 원래 게시 기록에 결합한다. */
void PrototypeExchange::complete(const json& result)
{
    const auto receipt = job_.Id();
    job_.Reset();
    if (cancelRequested_ && (phase_ == Phase::seal || phase_ == Phase::preview))
    {
        finish("취소 요청 뒤 후속 출력을 시작하지 않았습니다.");
        return;
    }
    if (phase_ == Phase::seal)
    {
        if (result.at("project_id") != project_ || result.at("revision_id") != revision_ ||
            !result.at("snapshot_id").is_string() || !isHash(result.at("content_hash")))
        {
            throw std::runtime_error("봉인한 출력 개정이 요청과 다릅니다.");
        }
        snapshot_ = result;
        phase_ = Phase::context;
    }
    else if (phase_ == Phase::preview)
    {
        if (result.at("project_id") != project_ || result.at("revision_id") != revision_ || result.at("snapshot") != snapshot_ ||
            result.at("profile") != input_.at("profile") || result.at("format") != input_.at("format") ||
            result.at("options") != input_.at("options"))
        {
            throw std::runtime_error("출력 검토의 원본 또는 옵션이 다릅니다.");
        }
        if (!result.at("can_build").get<bool>())
        {
            const auto& issues = result.at("issues");
            finish("출력 검토에서 생성이 차단됐습니다. " +
                (issues.empty() ? std::string{} : diagnostic(issues.front())));
            return;
        }
        if (!isHash(result.at("review_hash")) || !result.at("pages").is_array() || !result.at("omissions").is_array())
        {
            throw std::runtime_error("출력 검토 해시 또는 범위가 다릅니다.");
        }
        review_ = result;
        input_["review_hash"] = result.at("review_hash");
        phase_ = Phase::approval;
        status_ = "출력 검토 완료. 승인 후 생성을 선택하세요.";
    }
    else if (phase_ == Phase::build)
    {
        if (result.at("snapshot") != snapshot_)
        {
            throw std::runtime_error("출력의 스냅샷이 승인한 입력과 다릅니다.");
        }
        acceptPublished(result, receipt);
        finish(cancelRequested_ ? "출력 게시가 취소보다 먼저 확정됐습니다." : "출력을 게시했습니다. 출처와 파일을 확인하세요.");
    }
    else if (phase_ == Phase::verify)
    {
        if (result.at("job_id") != receipt || result.at("snapshot") != published()->snapshot ||
            result.at("profile") != formats[format_].profile || result.at("original_job_id") != published()->job ||
            result.at("source_manifest_sha256") != published()->manifest ||
            result.at("verification").at("status") != "passed_profile")
        {
            throw std::runtime_error("재검수 결과가 선택한 출력과 다릅니다.");
        }
        finish("재검수 완료. 형식 재읽기 검사를 통과했습니다.");
    }
}

/** @brief 읽기 전용 목록에서 형식별 최신 완료 원본을 결정한다. */
void PrototypeExchange::acceptList(const json& result)
{
    const auto& items = result.at("items");
    const auto& next = result.at("next_offset");
    if (result.at("project_id") != project_ || result.at("offset") != listOffset_ || !items.is_array() || items.size() > 25)
    {
        throw std::runtime_error("출력 목록의 프로젝트 또는 페이지가 다릅니다.");
    }
    for (const auto& row : items)
    {
        if (row.at("operation_method") == "export.build" && row.at("format") == formats[format_].key &&
            row.at("state") == "completed" && row.at("can_verify") == true)
        {
            const auto time = row.at("created_at").get<double>();
            const auto id = row.at("job_id").get<std::string>();
            if (latestId_.empty() || time > latestTime_ || (time == latestTime_ && id > latestId_))
            {
                latestId_ = id;
                latestTime_ = time;
            }
        }
    }
    if (!next.is_null())
    {
        if (items.empty() || next != listOffset_ + items.size() || next.get<std::size_t>() > 512)
        {
            throw std::runtime_error("출력 목록의 다음 위치가 올바르지 않습니다.");
        }
        listOffset_ += items.size();
    }
    else if (!latestId_.empty())
    {
        phase_ = Phase::record;
    }
    else
    {
        finish("이 형식으로 완료된 출력 기록이 없습니다.");
    }
}

void PrototypeExchange::acceptPublished(const json& result, const std::string& job, const json& manifestHash)
{
    const auto& formatsRow = formats[format_];
    const auto& snapshot = result.at("snapshot");
    const auto& rows = result.at("artifacts");
    if (result.at("job_id") != job || result.at("profile") != formatsRow.profile ||
        result.at("status") != "generated_unverified" || snapshot.at("project_id") != project_ || !rows.is_array())
    {
        throw std::runtime_error("게시된 출력의 작업, 원본 또는 형식이 다릅니다.");
    }
    const auto manifest = std::find_if(rows.begin(), rows.end(), [](const json& row)
    {
        return row.at("role") == "manifest";
    });
    const auto primary = std::find_if(rows.begin(), rows.end(), [&formatsRow](const json& row)
    {
        return row.at("uri").get_ref<const std::string&>().ends_with(formatsRow.suffix);
    });
    if (manifest == rows.end() || primary == rows.end() || !isHash(manifest->at("sha256")) ||
        !isHash(primary->at("sha256")) || (!manifestHash.is_null() && manifest->at("sha256") != manifestHash))
    {
        throw std::runtime_error("게시된 파일 또는 manifest의 해시가 누락됐습니다.");
    }
    published_[format_] = Published{job, snapshot.at("revision_id").get<std::string>(),
        primary->at("uri").get<std::string>(), primary->at("sha256").get<std::string>(),
        manifest->at("sha256").get<std::string>(), snapshot};
    std::printf("Exchange publication: job=%s revision=%s format=%s\n", job.c_str(),
        published()->revision.c_str(), formatsRow.key);
}

void PrototypeExchange::disconnected()
{
    if (active())
    {
        finish("서비스 연결이 끊겼습니다. 출력 게시 기록을 다시 확인하세요.");
    }
}

void PrototypeExchange::finish(std::string status)
{
    phase_ = Phase::idle;
    pending_ = Request::none;
    job_.Reset();
    snapshot_ = nullptr;
    input_ = nullptr;
    review_ = nullptr;
    footprints_.clear();
    footprintIndex_ = 0;
    cancelRequested_ = false;
    cancelSent_ = false;
    observedState_.clear();
    observedWorker_ = false;
    status_ = std::move(status);
}
