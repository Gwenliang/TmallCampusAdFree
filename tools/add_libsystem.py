"""给 dylib 补上 LC_LOAD_DYLIB /usr/lib/libSystem.B.dylib

用 -nostdlib 编译出来的 dylib 是零依赖的，但里面有 _objc_msgSend / _objc_getClass
等未定义符号。iOS 上这些必须由 libSystem 提供，缺了这条依赖 dyld 就加载失败 → 闪退。

做法：在 load commands 末尾的 padding 里追加一条 LC_LOAD_DYLIB，不移动任何段。
"""
import struct, sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import macho

LC_LOAD_DYLIB = 0xC
DEFAULT_LIB = "/usr/lib/libSystem.B.dylib"


def align8(n):
    return (n + 7) // 8 * 8


def add_libsystem(dylib_path, lib=DEFAULT_LIB, dry_run=False):
    with open(dylib_path, "rb") as f:
        raw = bytearray(f.read())

    data, slices = macho.MachO.from_file(dylib_path)
    m = slices[0][4]
    if len(slices) != 1:
        raise SystemExit("只支持单架构")

    # 已存在就跳过
    for cmd, name in m.dylibs:
        if name == lib:
            print("[%s] 已有 %s，跳过" % (os.path.basename(dylib_path), lib))
            return False

    header_size = 32 if m.is64 else 28
    cmd_end = header_size + m.sizeofcmds

    # 找可用空间上限：第一个 section 的文件偏移（即 __TEXT,__text）
    limit = None
    for sec in m.sections:
        if sec.offset > 0:
            limit = sec.offset if limit is None else min(limit, sec.offset)
    if limit is None:
        limit = len(raw)

    name = lib.encode() + b"\x00"
    cmdsize = align8(24 + len(name))
    free = limit - cmd_end
    if cmdsize > free:
        raise SystemExit("空间不足：需要 %d，可用 %d" % (cmdsize, free))

    if dry_run:
        print("[dry-run] %s: cmdsize=%d free=%d" % (os.path.basename(dylib_path), cmdsize, free))
        return True

    struct.pack_into("<IIIIII", raw, cmd_end,
                     LC_LOAD_DYLIB, cmdsize,
                     24,             # name offset
                     2, 0x10000, 0x10000)  # timestamp, current_version, compatibility_version
    raw[cmd_end+24:cmd_end+24+len(name)] = name
    for i in range(24 + len(name), cmdsize):
        raw[cmd_end+i] = 0

    struct.pack_into("<I", raw, 16, m.ncmds + 1)
    struct.pack_into("<I", raw, 20, m.sizeofcmds + cmdsize)

    with open(dylib_path, "wb") as f:
        f.write(raw)
    print("[%s] 已追加 LC_LOAD_DYLIB %s (cmdsize=%d)" % (os.path.basename(dylib_path), lib, cmdsize))

    # 复核
    data2, s2 = macho.MachO.from_file(dylib_path)
    m2 = s2[0][4]
    assert m2.ncmds == m.ncmds + 1
    assert any(n == lib for _, n in m2.dylibs), "追加后仍未找到依赖"
    return True


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    for p in sys.argv[1:]:
        if p.startswith("--"):
            continue
        add_libsystem(p, dry_run=dry)
