"""Crude arm64 xref scanner: list objc selectors / C strings referenced by a given function."""
import struct, sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import macho, objc_detail as od


def adrp_target(insn, pc):
    immlo = (insn >> 29) & 0x3
    immhi = (insn >> 5) & 0x7FFFF
    imm = (immhi << 2) | immlo
    if imm & (1 << 20):
        imm -= (1 << 21)
    return (pc & ~0xFFF) + (imm << 12)


def decode_refs(m, start_vm, end_vm, selrefs, cstrings_map):
    """Scan [start_vm, end_vm) and return (selectors, strings, bl_targets)."""
    out_sel, out_str, bls = [], [], []
    o = m.vm2off(start_vm)
    if o is None:
        return out_sel, out_str, bls
    n = (end_vm - start_vm) // 4
    regs = {}
    for i in range(n):
        pc = start_vm + i*4
        insn = struct.unpack_from("<I", m.data, o + i*4)[0]
        if (insn & 0x9F000000) == 0x90000000:          # ADRP
            rd = insn & 0x1F
            regs[rd] = adrp_target(insn, pc)
            continue
        if (insn & 0x7F000000) == 0x11000000:          # ADD immediate
            rd = insn & 0x1F; rn = (insn >> 5) & 0x1F
            imm12 = (insn >> 10) & 0xFFF
            if rn in regs:
                addr = regs[rn] + imm12
                regs[rd] = addr
                if addr in cstrings_map:
                    out_str.append((hex(pc), cstrings_map[addr]))
                continue
        for mask, base, size in ((0xFFC00000, 0xF9400000, 8), (0xFFC00000, 0xB9400000, 4),
                                 (0xFFC00000, 0x39400000, 1), (0xFFC00000, 0x79400000, 2)):
            if (insn & mask) == base:
                rt = insn & 0x1F; rn = (insn >> 5) & 0x1F
                imm12 = (insn >> 10) & 0xFFF
                if rn in regs and regs[rn] is not None:
                    addr = regs[rn] + imm12*size
                    regs[rt] = None
                    if addr in selrefs:
                        out_sel.append((hex(pc), selrefs[addr]))
                    elif size == 8 and addr in cstrings_map:
                        out_str.append((hex(pc), "*" + cstrings_map[addr]))
                break
        if (insn & 0xFC000000) == 0x94000000:          # BL
            imm26 = insn & 0x3FFFFFF
            if imm26 & (1 << 25):
                imm26 -= (1 << 26)
            bls.append(pc + imm26*4)
    return out_sel, out_str, bls


def main():
    binpath = sys.argv[1]
    targets = sys.argv[2].split(",")     # Class.sel  (sel prefixed by -/+)
    data, slices = macho.MachO.from_file(binpath)
    m = slices[0][4]
    r = od.Reader(m)
    classes = {c["name"]: c for c in r.all_classes()}

    # selrefs
    sr = m.section("__DATA_CONST", "__objc_selrefs") or m.section("__DATA", "__objc_selrefs")
    selrefs = {}
    if sr:
        for i in range(sr.size // 8):
            p = sr.offset + i*8
            ptr = struct.unpack_from("<Q", m.data, p)[0]
            name = r.name(ptr)
            if name:
                selrefs[sr.addr + i*8] = name

    # cstring map
    cs = m.section("__TEXT", "__cstring")
    cstrings = {}
    if cs:
        blob = m.data[cs.offset:cs.offset+cs.size]
        base = cs.addr
        idx = 0
        while idx < len(blob):
            end = blob.find(b"\x00", idx)
            if end < 0: break
            if end > idx:
                try:
                    cstrings[base + idx] = blob[idx:end].decode("utf-8", "replace")
                except Exception:
                    pass
            idx = end + 1

    # function starts for range boundaries
    with open(os.devnull, "w"):
        pass
    import verify_imps as vi
    fs = sorted(vi.function_starts(m) or [])

    for t in targets:
        kind, rest = t[0], t[1:]
        cls, sel = rest.split(".", 1)
        c = classes.get(cls)
        if not c:
            print("no class", cls); continue
        lst = c["inst"] if kind == "-" else c["cls"]
        imp = next((i for (s, ty, i) in lst if s == sel), None)
        if not imp:
            print("no method", t); continue
        # find end = next function start
        end = None
        for f in fs:
            if f > imp:
                end = f; break
        if end is None: end = imp + 0x400
        sels, strs, bls = decode_refs(m, imp, min(end, imp + 0x4000), selrefs, cstrings)
        print("="*72)
        print("%s  imp=%#x .. %#x" % (t, imp, end))
        print("  selectors:", sorted({s for _, s in sels}))
        print("  strings:", [s for _, s in strs if not s.startswith("*")][:25])
        print("  bl count:", len(bls))


if __name__ == "__main__":
    main()
