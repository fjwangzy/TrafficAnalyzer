/**
 * @file sample_backoff.cpp
 * @brief 实现：SQLite 全流降抽样 + cooldown 约束。
 *
 * 实现范围：
 *   - SampleBackoff::try_apply_backoff()：冷却判别 + SQLite 写入。
 *   - SampleBackoff::apply_sqlite_increment()：短连接 SQLite UPDATE。
 *
 * SQLite 使用 sqlite3 C API（短连接：open → exec → close），
 * 与 rtsp_receive_service/src/sqlite_hotupdate/stream_store.cpp 风格一致。
 */

#include "sample_backoff.h"

#include <sqlite3.h>
#include <cstdio>
#include <sstream>

namespace yolo {
namespace inference {

SampleBackoff::SampleBackoff(const std::string& db_path,
                             int backoff_ms,
                             int cooldown_ms)
    : db_path_(db_path)
    , backoff_ms_(backoff_ms > 0 ? backoff_ms : 25)
    , cooldown_ms_(cooldown_ms >= 0 ? cooldown_ms : 5000)
    , last_applied_(std::chrono::steady_clock::time_point::min()) {}

bool SampleBackoff::try_apply_backoff(const char* reason) {
    std::lock_guard<std::mutex> lk(mu_);

    auto now = std::chrono::steady_clock::now();

    // ---- 1. 冷却检查 ----
    if (last_applied_.time_since_epoch().count() > 0) {
        auto elapsed =
            std::chrono::duration_cast<std::chrono::milliseconds>(
                now - last_applied_).count();
        if (static_cast<long long>(elapsed) <
            static_cast<long long>(cooldown_ms_)) {
            // 冷却期内：只计指标
            ++skipped_count_;
            std::fprintf(stderr,
                         "[sample_backoff] cooldown: skipped %s "
                         "(elapsed=%lldms < cooldown=%dms) "
                         "applied=%llu skipped=%llu\n",
                         reason, static_cast<long long>(elapsed),
                         cooldown_ms_,
                         static_cast<unsigned long long>(applied_count_.load()),
                         static_cast<unsigned long long>(skipped_count_.load()));
            return false;
        }
    }

    // ---- 2. 执行 SQLite 写入 ----
    int updated = apply_sqlite_increment();
    if (updated < 0) {
        // 写入失败
        ++fail_count_;
        std::fprintf(stderr,
                     "[sample_backoff] SQLite UPDATE failed, reason=%s"
                     " db=%s fail_count=%llu\n",
                     reason, db_path_.c_str(),
                     static_cast<unsigned long long>(fail_count_.load()));
        return false;
    }

    // ---- 3. 成功：更新时间戳、累计 ----
    last_applied_ = now;
    ++applied_count_;

    std::fprintf(stderr,
                 "[sample_backoff] applied: reason=%s updated=%d rows"
                 " backoff_ms=%d applied=%llu\n",
                 reason, updated, backoff_ms_,
                 static_cast<unsigned long long>(applied_count_.load()));

    return true;
}

int SampleBackoff::apply_sqlite_increment() {
    // ---- 1. 打开数据库（短连接） ----
    sqlite3* db = nullptr;
    int rc = sqlite3_open_v2(db_path_.c_str(), &db,
                             SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE,
                             nullptr);
    if (rc != SQLITE_OK) {
        std::fprintf(stderr,
                     "[sample_backoff] sqlite3_open_v2 failed: %s (%s)\n",
                     db ? sqlite3_errmsg(db) : "null", db_path_.c_str());
        if (db) sqlite3_close(db);
        return -1;
    }

    // ---- 2. 构造语句 + 绑定参数 ----
    // WAL 模式对短连接写入友好
    sqlite3_exec(db, "PRAGMA journal_mode=WAL", nullptr, nullptr, nullptr);

    std::ostringstream sql;
    sql << "UPDATE stream_configs"
        << " SET sample_interval_ms = sample_interval_ms + "
        << backoff_ms_
        << " WHERE sample_interval_ms > 0";

    char* err_msg = nullptr;
    rc = sqlite3_exec(db, sql.str().c_str(), nullptr, nullptr, &err_msg);
    if (rc != SQLITE_OK) {
        std::fprintf(stderr,
                     "[sample_backoff] UPDATE failed: %s\n",
                     err_msg ? err_msg : "unknown");
        sqlite3_free(err_msg);
        sqlite3_close(db);
        return -1;
    }

    // ---- 3. 获取更新行数 ----
    int updated = sqlite3_changes(db);

    // ---- 4. 关闭短连接 ----
    sqlite3_close(db);
    return updated;
}

}  // namespace inference
}  // namespace yolo
