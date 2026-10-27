"""Verify method IMPs are real function starts using LC_FUNCTION_STARTS, and disassemble a few words."""
import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import macho, objc_detail as od

def uleb(buf, i):
    r = 0; shift = 0
    while True:
        b = buf[i]; i += 1
        r |= (b & 0x7F) << shift
        if not (b & 0x80): break
        shift += 7
    return r, i

def function_starts(m):
    if not m.function_starts:
        return None
    off, size = m.function_starts
    o = m.vm2off(off) if off else None
    if o is None:
        # dataoff is a file offset for LC_FUNCTION_STARTS
        o = off
    buf = m.data[o:o+size]
    text = m.segment("__TEXT")
    addr = text.vmaddr
    out = set()
    i = 0
    while i < len(buf):
        d, i = uleb(buf, i)
        if d == 0: break
        addr += d
        out.add(addr)
    return out

def main():
    path = sys.argv[1]
    names = sys.argv[2].split(",") if len(sys.argv) > 2 else None
    data, slices = macho.MachO.from_file(path)
    m = slices[0][4]
    fs = function_starts(m)
    print("function starts:", len(fs) if fs else None)
    r = od.Reader(m)
    tot = 0; ins = 0
    for c in r.all_classes():
        if names and c["name"] not in names: continue
        for kind, lst in (("-", c["inst"]), ("+", c["cls"])):
            for sel, types, imp in lst:
                if not imp: continue
                tot += 1
                ok = fs is None or imp in fs
                if not ok:
                    ins += 1
                    print("  NOT-IN-FSTARTS %s%s[%s] imp=%#x" % (kind, c["name"], sel, imp))
                o = m.vm2off(imp)
                w = struct.unpack_from("<I", m.data, o)[0]
                print("  %s%s[%-40s] imp=%#x words=%08x" % (kind, c["name"][:22], sel, imp, w))
    print("checked", tot, "not-in-fstarts", ins)

if __name__ == "__main__":
    main()
