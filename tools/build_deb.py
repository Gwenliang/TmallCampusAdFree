"""打包成 .deb（越狱设备用，Cydia/Sileo/Zebra 安装）。不依赖 dpkg-deb，手写 ar + tar.gz。"""
import os, sys, io, tarfile, time, struct, gzip, hashlib

def ar_member(name, data, mtime):
    """构造 ar 归档成员（Unix ar 格式）"""
    hdr = b"%-16s%-12d%-6d%-6d%-8s%-10d`\n" % (
        name.encode(), mtime, 0, 0, b"100644", len(data))
    pad = b"\n" if len(data) % 2 else b""
    return hdr + data + pad

def build_tar_gz(files, mtime):
    """files: [(arcname, content_bytes, mode)]"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for arcname, content, mode in files:
            ti = tarfile.TarInfo(arcname)
            ti.size = len(content)
            ti.mtime = mtime
            ti.mode = mode
            ti.uid = 0
            ti.gid = 0
            ti.uname = "root"
            ti.gname = "wheel"
            tf.addfile(ti, io.BytesIO(content))
    return gzip.compress(buf.getvalue(), compresslevel=9, mtime=mtime)

def main():
    dylib = sys.argv[1]
    out_deb = sys.argv[2]
    version = sys.argv[3] if len(sys.argv) > 3 else "1.0.0"
    name = os.path.splitext(os.path.basename(dylib))[0]
    ident = "com.tmallcampus." + name.lower()
    mtime = int(time.time())

    with open(dylib, "rb") as f:
        dylib_bytes = f.read()
    installed_size = len(dylib_bytes) // 1024

    control = (
        "Package: %s\n"
        "Name: %s\n"
        "Version: %s\n"
        "Architecture: iphoneos-arm64\n"
        "Description: 天猫校园去广告（开屏/信息流/激励视频/广告节点）\n"
        "Maintainer: local\n"
        "Author: local\n"
        "Section: Tweaks\n"
        "Depends: mobilesubstrate\n"
        "Installed-Size: %d\n"
    ) % (ident, name, version, installed_size)

    # deb 内的 data.tar.gz：/Library/MobileSubstrate/DynamicLibraries/
    base = "Library/MobileSubstrate/DynamicLibraries"
    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n'
        '\t<key>Filter</key>\n\t<dict>\n'
        '\t\t<key>Bundles</key>\n\t\t<array>\n'
        '\t\t\t<string>com.tmall.campus4iphone</string>\n'
        '\t\t</array>\n'
        '\t</dict>\n</dict>\n</plist>\n'
    )
    data_files = [
        ("%s/%s.dylib" % (base, name), dylib_bytes, 0o755),
        ("%s/%s.plist" % (base, name), plist.encode(), 0o644),
    ]
    control_files = [("./control", control.encode(), 0o644)]

    data_tar = build_tar_gz(data_files, mtime)
    control_tar = build_tar_gz(control_files, mtime)

    debian_binary = b"2.0\n"
    parts = [
        ar_member("debian-binary", debian_binary, mtime),
        ar_member("control.tar.gz", control_tar, mtime),
        ar_member("data.tar.gz", data_tar, mtime),
    ]
    with open(out_deb, "wb") as f:
        f.write(b"!<arch>\n")
        for p in parts:
            f.write(p)

    print("wrote %s (%.1f KB)" % (out_deb, os.path.getsize(out_deb) / 1024))
    print("sha256", hashlib.sha256(open(out_deb, "rb").read()).hexdigest())

if __name__ == "__main__":
    main()
