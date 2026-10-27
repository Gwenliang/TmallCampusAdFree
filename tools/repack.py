"""Repack Payload/ into an IPA with unix modes preserved (executable bits matter for iOS)."""
import os, sys, zipfile, stat, time

MACHO_MAGICS = {
    b"\xcf\xfa\xed\xfe",  # MH_MAGIC_64 LE
    b"\xce\xfa\xed\xfe",  # MH_MAGIC LE
    b"\xca\xfe\xba\xbe",  # FAT
    b"\xca\xfe\xba\xbf",
}

def is_macho(path):
    try:
        with open(path, "rb") as f:
            head = f.read(4)
        return head in MACHO_MAGICS
    except OSError:
        return False

def main():
    root = sys.argv[1]          # directory containing Payload/
    out = sys.argv[2]
    src = os.path.join(root, "Payload")
    entries = []
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames.sort(); filenames.sort()
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        entries.append((rel_dir + "/", None, 0o40755))
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            mode = 0o100755 if is_macho(full) else 0o100644
            entries.append((rel, full, mode))

    if os.path.exists(out):
        os.remove(out)
    t0 = time.time()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel, full, mode in entries:
            zi = zipfile.ZipInfo(rel, date_time=(2026, 10, 27, 19, 18, 12))
            zi.create_system = 3                      # unix
            zi.external_attr = (mode << 16) | (0x10 if full is None else 0)
            zi.compress_type = zipfile.ZIP_DEFLATED
            if full is None:
                z.writestr(zi, b"")
            else:
                with open(full, "rb") as f:
                    z.writestr(zi, f.read())
    print("wrote %s (%.1f MB) in %.1fs, %d entries" % (out, os.path.getsize(out)/1048576, time.time()-t0, len(entries)))

if __name__ == "__main__":
    main()
