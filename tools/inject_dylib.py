"""把 dylib 注入 Mach-O 主二进制的 LC_LOAD_DYLIB（利用 load commands 后的空闲空间）。

算法：
  - 读出 mach_header (ncmds, sizeofcmds)
  - 在 32 + sizeofcmds 处追加 LC_LOAD_DYLIB 命令（24 字节头 + 路径串，8 字节对齐）
  - 更新 ncmds += 1, sizeofcmds += cmdsize
  - 校验新 sizeofcmds 不越过第一个 section 的文件偏移（__TEXT,__text 的 offset）
  不改动任何既有 load command，不移动段，因此结构绝对安全。
"""
import struct, sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import macho

LC_LOAD_DYLIB = 0xC

def inject(binpath, dylib_path_in_app, dry_run=False):
    with open(binpath, "rb") as f:
        raw = bytearray(f.read())

    data, slices = macho.MachO.from_file(binpath)
    m = slices[0][4]
    if len(slices) != 1:
        raise SystemExit("只支持单架构 Mach-O")

    text = m.section("__TEXT", "__text")
    header_size = 32 if m.is64 else 28
    cmd_end = header_size + m.sizeofcmds
    limit = text.offset if text else os.path.getsize(binpath)
    free = limit - cmd_end

    name = dylib_path_in_app.encode() + b"\x00"
    cmdsize = 24 + len(name)
    cmdsize = (cmdsize + 7) // 8 * 8
    if cmdsize > free:
        raise SystemExit("空间不足：需要 %d，可用 %d" % (cmdsize, free))

    # 检查是否已经注入过
    for c, n in m.dylibs:
        if dylib_path_in_app in n:
            print("already injected:", n)
            return False

    if dry_run:
        print("[dry-run] 追加 LC_LOAD_DYLIB: %s, cmdsize=%d, free=%d" % (dylib_path_in_app, cmdsize, free))
        return True

    # 追加命令
    off = cmd_end
    struct.pack_into("<IIIIII", raw, off,
                     LC_LOAD_DYLIB, cmdsize,
                     24,          # name offset
                     2, 0x10000, 2)  # timestamp, current_version(1.0.0), compatibility_version(1.0.0)
    raw[off+24:off+24+len(name)] = name
    # 对齐填充
    for i in range(24+len(name), cmdsize):
        raw[off+i] = 0

    # 更新 mach_header
    if m.is64:
        struct.pack_into("<I", raw, 16, m.ncmds + 1)      # ncmds
        struct.pack_into("<I", raw, 20, m.sizeofcmds + cmdsize)  # sizeofcmds
    else:
        struct.pack_into("<I", raw, 12, m.ncmds + 1)
        struct.pack_into("<I", raw, 16, m.sizeofcmds + cmdsize)

    with open(binpath, "wb") as f:
        f.write(raw)
    print("injected %s (cmdsize=%d) into %s" % (dylib_path_in_app, cmdsize, os.path.basename(binpath)))
    return True


if __name__ == "__main__":
    binpath = sys.argv[1]
    dylib_path = sys.argv[2]
    dry = "--dry-run" in sys.argv
    inject(binpath, dylib_path, dry)
