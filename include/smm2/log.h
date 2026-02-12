#pragma once

#include "nn/fs.h"
#include <cstdint>
#include <cstdarg>
#include <cstdio>
#include <cstring>

namespace smm2 {
namespace log {

// Simple SD card logger. Writes to sd:/smm2-hooks/<filename>
// Ring buffer in memory, flushes periodically or on demand.

constexpr size_t BUFFER_SIZE = 8192;

struct Logger {
    char path[64];
    char buffer[BUFFER_SIZE];
    size_t pos = 0;
    int64_t file_pos = 0;
    bool initialized = false;

    void init(const char* filename) {
        std::snprintf(path, sizeof(path), "sd:/smm2-hooks/%s", filename);
        // Delete old file to prevent corruption from leftover data
        nn::fs::DeleteFile(path);
        nn::fs::CreateFile(path, 0);
        pos = 0;
        file_pos = 0;
        initialized = true;
    }

    void write(const char* data, size_t len) {
        if (!initialized) return;

        // Flush if buffer would overflow
        if (pos + len >= BUFFER_SIZE) {
            flush();
        }

        // If single write exceeds buffer, write directly
        if (len >= BUFFER_SIZE) {
            nn::fs::FileHandle f;
            if (nn::fs::OpenFile(&f, path, nn::fs::MODE_WRITE) == 0) {
                nn::fs::WriteOption opt = {.flags = nn::fs::WRITE_OPTION_FLUSH};
                nn::fs::SetFileSize(f, file_pos + len);
                nn::fs::WriteFile(f, file_pos, data, len, opt);
                file_pos += len;
                nn::fs::CloseFile(f);
            }
            return;
        }

        std::memcpy(buffer + pos, data, len);
        pos += len;
    }

    void writef(const char* fmt, ...) __attribute__((format(printf, 2, 3))) {
        char tmp[256];
        va_list args;
        va_start(args, fmt);
        int n = std::vsnprintf(tmp, sizeof(tmp), fmt, args);
        va_end(args);
        if (n > 0) write(tmp, n);
    }

    void flush() {
        if (!initialized || pos == 0) return;

        nn::fs::FileHandle f;
        if (nn::fs::OpenFile(&f, path, nn::fs::MODE_WRITE) == 0) {
            nn::fs::WriteOption opt = {.flags = nn::fs::WRITE_OPTION_FLUSH};
            nn::fs::SetFileSize(f, file_pos + pos);
            nn::fs::WriteFile(f, file_pos, buffer, pos, opt);
            file_pos += pos;
            nn::fs::CloseFile(f);
        }
        pos = 0;
    }
};

} // namespace log
} // namespace smm2
