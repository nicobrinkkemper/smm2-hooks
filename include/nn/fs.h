#pragma once

#include <cstdint>
#include <cstddef>

namespace nn {
    namespace fs {
        struct FileHandle {
            void* handle;
        };

        constexpr int MODE_READ = 1;
        constexpr int MODE_WRITE = 2;
        constexpr int MODE_APPEND = 4;

        struct WriteOption {
            int flags;
        };

        constexpr int WRITE_OPTION_FLUSH = 1;

        uint32_t MountSdCardForDebug(const char* mount);

        uint32_t CreateDirectory(const char* path);
        uint32_t CreateDirectoryRecursively(const char* path);
        uint32_t CreateFile(const char* path, int64_t length);
        uint32_t DeleteFile(const char* path);
        uint32_t OpenFile(FileHandle* handle, const char* path, int mode);
        uint32_t SetFileSize(FileHandle handle, int64_t size);
        uint32_t ReadFile(size_t* bytes_read, FileHandle handle, int64_t off, void* data, size_t bytes_to_read);
        uint32_t WriteFile(FileHandle handle, int64_t off, const void* data, size_t bytes_to_write, const WriteOption& option);
        uint32_t FlushFile(FileHandle handle);
        void CloseFile(FileHandle handle);
    }
}
