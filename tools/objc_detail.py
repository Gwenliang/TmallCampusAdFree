"""Detailed ObjC inspection: separate instance vs class methods, show IMPs, find callers."""
import struct, sys, json

def u32(d,o): return struct.unpack_from("<I", d, o)[0]
def u64(d,o): return struct.unpack_from("<Q", d, o)[0]
def i32(d,o): return struct.unpack_from("<i", d, o)[0]

class Reader:
    def __init__(self, m):
        self.m = m

    def name(self, addr):
        o = self.m.vm2off(addr)
        if o is None: return None
        return self.m.cstr_off(o)

    def ro(self, class_addr):
        o = self.m.vm2off(class_addr)
        if o is None: return None
        bits = u64(self.m.data, o+32)
        ro_addr = bits & 0x00007FFFFFFFFFFF
        o2 = self.m.vm2off(ro_addr)
        if o2 is None: return None
        return dict(name=self.name(u64(self.m.data, o2+24)),
                    methods=u64(self.m.data, o2+32),
                    properties=u64(self.m.data, o2+64),
                    ivars=u64(self.m.data, o2+48),
                    flags=u32(self.m.data, o2))

    def methods(self, list_addr):
        out = []
        o = self.m.vm2off(list_addr)
        if o is None: return out
        flags = u32(self.m.data, o); count = u32(self.m.data, o+4)
        base = o + 8
        for i in range(count):
            if flags & 0x80000000:
                p = base + i*12
                sel = self.m.cstr_off(p + i32(self.m.data, p))
                types = self.m.cstr_off(p + 4 + i32(self.m.data, p+4))
                imp = None  # relative: file offset of the imp field + rel
                # imp is a 32-bit offset relative to the field address
                field_off = p + 8
                field_vm = self.m.off2vm(field_off)
                rel = i32(self.m.data, field_off)
                imp = field_vm + rel if field_vm else None
            else:
                p = base + i*24
                sel = self.name(u64(self.m.data, p))
                types = self.name(u64(self.m.data, p+8))
                imp = u64(self.m.data, p+16)
            out.append((sel, types, imp))
        return out

    def class_info(self, class_addr):
        o = self.m.vm2off(class_addr)
        if o is None: return None
        isa = u64(self.m.data, o)
        ro = self.ro(class_addr)
        metaclass_ro = self.ro(isa) if isa else None
        return dict(addr=class_addr, name=ro["name"] if ro else None,
                    inst=self.methods(ro["methods"]) if ro and ro["methods"] else [],
                    cls=self.methods(metaclass_ro["methods"]) if metaclass_ro and metaclass_ro["methods"] else [])

    def all_classes(self):
        m = self.m
        cl = m.section("__DATA_CONST", "__objc_classlist") or m.section("__DATA", "__objc_classlist")
        out = []
        for i in range(cl.size // 8):
            addr = u64(m.data, cl.offset + i*8)
            info = self.class_info(addr)
            if info: out.append(info)
        return out

def main():
    sys.path.insert(0, r"D:\文档\deepseek-harness\default-workspace\tmallcampus-adfree\tools")
    import macho
    path, names = sys.argv[1], sys.argv[2].split(",")
    data, slices = macho.MachO.from_file(path)
    m = slices[0][4]
    r = Reader(m)
    for c in r.all_classes():
        if c["name"] in names:
            print("="*70)
            print("CLASS", c["name"], hex(c["addr"]))
            for tag, lst in (("- ", c["inst"]), ("+ ", c["cls"])):
                for sel, types, imp in lst:
                    print("  %s%s  %-28s imp=%s" % (tag, sel, types, hex(imp) if imp else "?"))

if __name__ == "__main__":
    main()
