"""Minimal Mach-O (32/64, fat/thin, arm64/arm64e) reader for static analysis + patching."""
import struct

MH_MAGIC = 0xFEEDFACE
MH_MAGIC_64 = 0xFEEDFACF
FAT_MAGIC = 0xCAFEBABE
FAT_MAGIC_64 = 0xCAFEBABF

LC_SEGMENT = 0x1
LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x2
LC_DYSYMTAB = 0xB
LC_LOAD_DYLIB = 0xC
LC_LOAD_WEAK_DYLIB = 0x80000018
LC_REEXPORT_DYLIB = 0x8000001F
LC_ID_DYLIB = 0xD
LC_LOAD_UPWARD_DYLIB = 0x80000023
LC_CODE_SIGNATURE = 0x1D
LC_DYLD_INFO = 0x22
LC_DYLD_INFO_ONLY = 0x80000022
LC_FUNCTION_STARTS = 0x26
LC_DYLD_CHAINED_FIXUPS = 0x80000034
LC_DYLD_EXPORTS_TRIE = 0x80000033

CPU_ARCH_ABI64 = 0x01000000
CPU_TYPE_X86_64 = 0x01000007
CPU_TYPE_ARM64 = 0x0100000C
CPU_TYPE_ARM64_32 = 0x0200000C

class Section:
    __slots__ = ("sectname","segname","addr","size","offset","align","flags","reserved1","reserved2","index")
    def __repr__(self):
        return f"<{self.segname},{self.sectname} addr={self.addr:#x} size={self.size:#x} off={self.offset:#x}>"

class Segment:
    __slots__ = ("name","vmaddr","vmsize","fileoff","filesize","maxprot","initprot","nsects","sections","cmd_index")
    def __repr__(self):
        return f"<seg {self.name} vm={self.vmaddr:#x}+{self.vmsize:#x} off={self.fileoff:#x}>"

class MachO:
    def __init__(self, data, base=0):
        self.data = data
        self.base = base  # offset of this slice inside file
        magic = struct.unpack_from("<I", data, 0)[0]
        if magic in (MH_MAGIC_64,):
            self.is64 = True
        elif magic == MH_MAGIC:
            self.is64 = False
        else:
            # big endian variants
            magic_be = struct.unpack_from(">I", data, 0)[0]
            if magic_be == MH_MAGIC_64:
                raise ValueError("big-endian 64-bit not supported")
            raise ValueError("not a mach-o: %08x" % magic)
        (self.cputype, self.cpusubtype, self.filetype, self.ncmds,
         self.sizeofcmds, self.flags) = struct.unpack_from("<iiIIII", data, 4)
        self.reserved = struct.unpack_from("<I", data, 28)[0] if self.is64 else 0
        self.segments = []
        self.sections = []
        self.dylibs = []      # (cmd, name)
        self.cmds = []        # (cmd, offset, cmdsize)
        self.symtab = None
        self.code_signature = None
        self.dyld_info = None
        self.function_starts = None
        self.chained_fixups = None
        self.exports_trie = None
        self._parse()

    @staticmethod
    def from_file(path):
        with open(path, "rb") as f:
            data = f.read()
        magic = struct.unpack_from(">I", data, 0)[0]
        if magic in (FAT_MAGIC, FAT_MAGIC_64):
            nfat = struct.unpack_from(">I", data, 4)[0]
            off = 8
            slices = []
            for i in range(nfat):
                if magic == FAT_MAGIC:
                    cputype, cpusub, offset, size, align = struct.unpack_from(">iiIII", data, off)
                    off += 20
                else:
                    cputype, cpusub, offset, size, align, _r = struct.unpack_from(">iiIIII", data, off)
                    off += 32
                slices.append((cputype, cpusub, offset, size))
            return data, [ (t, s, offset, size, MachO(data[offset:offset+size], offset)) for (t,s,offset,size) in slices ]
        return data, [ (struct.unpack_from("<i", data, 4)[0], struct.unpack_from("<i", data, 8)[0], 0, len(data), MachO(data, 0)) ]

    def _parse(self):
        off = 32 if self.is64 else 28
        for i in range(self.ncmds):
            cmd, cmdsize = struct.unpack_from("<II", self.data, off)
            self.cmds.append((cmd, off, cmdsize))
            if cmd in (LC_SEGMENT_64, LC_SEGMENT):
                seg = Segment()
                seg.cmd_index = i
                if cmd == LC_SEGMENT_64:
                    name = self.data[off+8:off+24].split(b"\0")[0].decode("utf-8", "replace")
                    vmaddr, vmsize, fileoff, filesize, maxprot, initprot, nsects, flags = struct.unpack_from("<QQQQiiII", self.data, off+24)
                    seg.nsects = nsects
                    s_off = off + 72
                    ssize = 80
                else:
                    name = self.data[off+8:off+24].split(b"\0")[0].decode("utf-8", "replace")
                    vmaddr, vmsize, fileoff, filesize, maxprot, initprot, nsects, flags = struct.unpack_from("<IIIIiiII", self.data, off+24)
                    seg.nsects = nsects
                    s_off = off + 56
                    ssize = 68
                seg.name, seg.vmaddr, seg.vmsize, seg.fileoff, seg.filesize = name, vmaddr, vmsize, fileoff, filesize
                seg.maxprot, seg.initprot = maxprot, initprot
                seg.sections = []
                for j in range(nsects):
                    p = s_off + j*ssize
                    sectname = self.data[p:p+16].split(b"\0")[0].decode("utf-8", "replace")
                    segname = self.data[p+16:p+32].split(b"\0")[0].decode("utf-8", "replace")
                    if cmd == LC_SEGMENT_64:
                        addr, size = struct.unpack_from("<QQ", self.data, p+32)
                        offset, align, reloff, nreloc, flags2, r1, r2, r3 = struct.unpack_from("<IIIIIIII", self.data, p+48)
                    else:
                        addr, size = struct.unpack_from("<II", self.data, p+32)
                        offset, align, reloff, nreloc, flags2, r1, r2 = struct.unpack_from("<IIIIIII", self.data, p+48)
                        r3 = 0
                    s = Section()
                    s.sectname, s.segname, s.addr, s.size, s.offset = sectname, segname, addr, size, offset
                    s.align, s.flags, s.reserved1, s.reserved2, s.index = align, flags2, r1, r2, len(self.sections)
                    seg.sections.append(s)
                    self.sections.append(s)
                self.segments.append(seg)
            elif cmd in (LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB, LC_REEXPORT_DYLIB, LC_ID_DYLIB, LC_LOAD_UPWARD_DYLIB):
                nameoff = struct.unpack_from("<I", self.data, off+8)[0]
                nm = self.data[off+nameoff:off+cmdsize].split(b"\0")[0].decode("utf-8", "replace")
                self.dylibs.append((cmd, nm))
            elif cmd == LC_SYMTAB:
                symoff, nsyms, stroff, strsize = struct.unpack_from("<IIII", self.data, off+8)
                self.symtab = (symoff, nsyms, stroff, strsize)
            elif cmd == LC_CODE_SIGNATURE:
                dataoff, datasize = struct.unpack_from("<II", self.data, off+8)
                self.code_signature = (dataoff, datasize, off)
            elif cmd in (LC_DYLD_INFO, LC_DYLD_INFO_ONLY):
                self.dyld_info = struct.unpack_from("<IIIIIIIIII", self.data, off+8)
            elif cmd == LC_FUNCTION_STARTS:
                self.function_starts = struct.unpack_from("<II", self.data, off+8)
            elif cmd == LC_DYLD_CHAINED_FIXUPS:
                self.chained_fixups = struct.unpack_from("<II", self.data, off+8)
            elif cmd == LC_DYLD_EXPORTS_TRIE:
                self.exports_trie = struct.unpack_from("<II", self.data, off+8)
            off += cmdsize

    # ---- helpers ----
    def segment(self, name):
        for s in self.segments:
            if s.name == name:
                return s
        return None

    def section(self, segname, sectname):
        for s in self.sections:
            if s.segname == segname and s.sectname == sectname:
                return s
        return None

    def vm2off(self, addr):
        for seg in self.segments:
            if seg.vmaddr <= addr < seg.vmaddr + seg.vmsize:
                delta = addr - seg.vmaddr
                if seg.filesize == 0:
                    return None
                if delta >= seg.filesize:
                    return None
                return seg.fileoff + delta
        return None

    def off2vm(self, off):
        for seg in self.segments:
            if seg.fileoff <= off < seg.fileoff + seg.filesize:
                return seg.vmaddr + (off - seg.fileoff)
        return None

    def read_vm(self, addr, size):
        o = self.vm2off(addr)
        if o is None:
            return None
        return self.data[o:o+size]

    def cstr_vm(self, addr):
        o = self.vm2off(addr)
        if o is None:
            return None
        end = self.data.find(b"\0", o)
        return self.data[o:end].decode("utf-8", "replace")

    def cstr_off(self, off):
        end = self.data.find(b"\0", off)
        return self.data[off:end].decode("utf-8", "replace")

    def symbols(self):
        out = []
        if not self.symtab:
            return out
        symoff, nsyms, stroff, strsize = self.symtab
        esz = 16 if self.is64 else 12
        for i in range(nsyms):
            p = symoff + i*esz
            if self.is64:
                strx, ntype, nsect, ndesc, nvalue = struct.unpack_from("<IBBHQ", self.data, p)
            else:
                strx, ntype, nsect, ndesc, nvalue = struct.unpack_from("<IBBHI", self.data, p)
            name = self.cstr_off(stroff + strx)
            out.append((name, ntype, nvalue))
        return out

    def arch_name(self):
        t = self.cputype
        if t == CPU_TYPE_ARM64:
            sub = self.cpusubtype & 0x00FFFFFF
            return "arm64e" if sub == 2 else "arm64"
        if t == CPU_TYPE_X86_64:
            return "x86_64"
        return "cpu_%x" % (t & 0xFFFFFFFF)

    def entitlements_blob(self):
        """Return the embedded entitlements XML bytes if present (search __TEXT for plist)."""
        s = self.segment("__TEXT")
        if not s:
            return None
        blob = self.data[s.fileoff:s.fileoff+s.filesize]
        i = blob.find(b"<?xml")
        if i < 0:
            return None
        j = blob.find(b"</plist>", i)
        if j < 0:
            return None
        return blob[i:j+8]
