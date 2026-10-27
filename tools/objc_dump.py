"""Dump ObjC metadata (classes, methods, properties) from a 64-bit Mach-O."""
import struct, sys

def u32(d,o): return struct.unpack_from("<I", d, o)[0]
def u64(d,o): return struct.unpack_from("<Q", d, o)[0]
def i32(d,o): return struct.unpack_from("<i", d, o)[0]

class ObjC:
    def __init__(self, m):
        self.m = m
        self.classes = []   # dict: name, addr, methods[(sel, types, imp)], props, ivars, super
        self._load()

    def _name_of(self, m, addr):
        o = m.vm2off(addr)
        if o is None: return None
        return m.cstr_off(o)

    def _class_ro(self, m, class_addr):
        data_bits = u64(m.data, m.vm2off(class_addr) + 32)
        ro_addr = data_bits & 0x00007FFFFFFFFFFF
        o = m.vm2off(ro_addr)
        if o is None: return None
        flags = u32(m.data, o)
        instanceStart = u32(m.data, o+4)
        instanceSize = u32(m.data, o+8)
        # reserved u32
        ivarLayout = u64(m.data, o+16)
        name_addr = u64(m.data, o+24)
        baseMethods = u64(m.data, o+32)
        baseProtocols = u64(m.data, o+40)
        ivars = u64(m.data, o+48)
        weakIvarLayout = u64(m.data, o+56)
        baseProperties = u64(m.data, o+64)
        return dict(flags=flags, name=self._name_of(m, name_addr), methods=baseMethods,
                    protocols=baseProtocols, ivars=ivars, properties=baseProperties, ro=ro_addr)

    def _methods(self, m, list_addr):
        out = []
        o = m.vm2off(list_addr)
        if o is None: return out
        flags = u32(m.data, o); count = u32(m.data, o+4)
        if flags & 0x80000000:  # relative method list
            entry = o + 8
            for i in range(count):
                p = entry + i*12
                name_off = i32(m.data, p)
                types_off = i32(m.data, p+4)
                imp_off = i32(m.data, p+8)
                sel = m.cstr_off(p + name_off)
                types_addr = p + 4 + types_off
                types = m.cstr_off(types_addr)
                imp = (p + 8 + imp_off) & 0xFFFFFFFFFFFF
                out.append((sel, types, self._vm_from_file(p, m)))
        else:
            entry = o + 8
            for i in range(count):
                p = entry + i*24
                name_addr = u64(m.data, p)
                types_addr = u64(m.data, p+8)
                imp = u64(m.data, p+16)
                out.append((self._name_of(m, name_addr), self._name_of(m, types_addr), imp))
        return out

    def _vm_from_file(self, file_off, m):
        return None

    def _load(self):
        m = self.m
        cl = m.section("__DATA_CONST", "__objc_classlist") or m.section("__DATA", "__objc_classlist")
        if not cl:
            print("no __objc_classlist", file=sys.stderr); return
        count = cl.size // 8
        for i in range(count):
            p = cl.offset + i*8
            cls_addr = u64(m.data, p)
            ro = self._class_ro(m, cls_addr)
            if not ro: continue
            superclass = None
            try:
                so = m.vm2off(cls_addr) + 8
                sup = u64(m.data, so)
                if sup:
                    superclass = self._name_of(m, sup)
            except Exception:
                pass
            methods = self._methods(m, ro["methods"]) if ro["methods"] else []
            self.classes.append(dict(name=ro["name"], addr=cls_addr, super=superclass,
                                     methods=methods, flags=ro["flags"], ro=ro["ro"],
                                     catlist=None))

    def categories(self):
        m = self.m
        out = []
        cl = m.section("__DATA_CONST", "__objc_catlist") or m.section("__DATA", "__objc_catlist")
        if not cl: return out
        for i in range(cl.size // 8):
            p = cl.offset + i*8
            cat_addr = u64(m.data, p)
            o = m.vm2off(cat_addr)
            if o is None: continue
            name = self._name_of(m, u64(m.data, o))
            cls = self._name_of(m, u64(m.data, o+8))
            inst = self._methods(m, u64(m.data, o+16)) if u64(m.data, o+16) else []
            cls_m = self._methods(m, u64(m.data, o+24)) if u64(m.data, o+24) else []
            out.append(dict(name=name, cls=cls, inst=inst, clsm=cls_m))
        return out

def main():
    sys.path.insert(0, r"D:\文档\deepseek-harness\default-workspace\tmallcampus-adfree\tools")
    import macho
    path = sys.argv[1]
    out = sys.argv[2]
    data, slices = macho.MachO.from_file(path)
    m = slices[0][4]
    oc = ObjC(m)
    cats = oc.categories()
    with open(out, "w", encoding="utf-8") as f:
        for c in sorted(oc.classes, key=lambda x: (x["name"] or "")):
            f.write("CLASS %s : %s\n" % (c["name"], c["super"]))
            for sel, types, imp in c["methods"]:
                f.write("   -/+ %s  %s  imp=%s\n" % (sel, types, hex(imp) if imp else "?"))
        for cat in cats:
            f.write("CATEGORY %s (%s)\n" % (cat["name"], cat["cls"]))
            for sel, types, imp in cat["inst"] + cat["clsm"]:
                f.write("   -/+ %s %s\n" % (sel, types))
    print("classes:", len(oc.classes), "categories:", len(cats))

if __name__ == "__main__":
    main()
