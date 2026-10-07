"""Build InfiniteCrisis_patched.exe from the untouched Steam client.

    python tools/patch_client.py [path/to/InfiniteCrisis.exe] [output.exe]

Defaults: ../InfiniteCrisis.exe (the game folder) -> ../InfiniteCrisis_patched.exe.
Every patch checks the original bytes first and refuses to run on an unknown
build. The RSA patch writes the modulus of keys/server_private.pem over the
client's built-in public key; generate your key pair first with
    python tools/patch_client.py --newkey
(the server and the patched exe must use the same key).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(HERE)
KEY_PATH = os.path.join(SERVER_DIR, "keys", "server_private.pem")

# (file offset, original bytes, patched bytes, description)
PATCHES = [
    (0xBE3862, bytes.fromhex("56 8b cb e8 66 25 b2 ff"), bytes.fromhex("33 c0 90 90 90 90 90 90"),
     "Oodle: stop compressing outgoing game-connection packets (rva 0xbe4462)"),
    (0x67EF34, bytes.fromhex("83 e2 0c 80 fa 0c"), bytes.fromhex("83 e2 08 80 fa 08"),
     "dialog gate: conversations need gate bit 8 only, not 'match started' (rva 0x67fb34)"),
    (0x11DB16C, bytes.fromhex("00 00 20 40"), bytes.fromhex("cd cc 4c 3e"),
     "lighting environment re-evaluation interval 2.5 s -> 0.2 s (rva 0x11dcd6c)"),
]
RSA_DER_OFFSET = 0x11A1F58            # PKCS#1 RSAPublicKey DER, 0x8c bytes
RSA_DER_HEADER = bytes.fromhex("30 81 89 02 81 81 00")
RSA_MODULUS_OFFSET = RSA_DER_OFFSET + len(RSA_DER_HEADER)
RSA_TRAILER = bytes.fromhex("02 03 01 00 01")   # exponent 65537


def new_key():
    from Crypto.PublicKey import RSA
    key = RSA.generate(1024)
    with open(KEY_PATH, "wb") as f:
        f.write(key.export_key())
    print("wrote", KEY_PATH)


def main(argv):
    if argv[1:2] == ["--newkey"]:
        return new_key()
    src = argv[1] if len(argv) > 1 else os.path.join(SERVER_DIR, "..", "InfiniteCrisis.exe")
    dst = argv[2] if len(argv) > 2 else os.path.join(os.path.dirname(src), "InfiniteCrisis_patched.exe")
    data = bytearray(open(src, "rb").read())
    for off, orig, new, desc in PATCHES:
        cur = bytes(data[off:off + len(orig)])
        if cur == new:
            print("already applied:", desc)
            continue
        if cur != orig:
            sys.exit(f"unexpected bytes at {off:#x} ({cur.hex()}): wrong client build? aborting")
        data[off:off + len(orig)] = new
        print("applied:", desc)
    if bytes(data[RSA_DER_OFFSET:RSA_MODULUS_OFFSET]) != RSA_DER_HEADER or \
            bytes(data[RSA_MODULUS_OFFSET + 128:RSA_MODULUS_OFFSET + 128 + len(RSA_TRAILER)]) != RSA_TRAILER:
        sys.exit("RSA public key not found at the expected offset: wrong client build? aborting")
    from Crypto.PublicKey import RSA
    key = RSA.import_key(open(KEY_PATH, "rb").read())
    if key.e != 65537 or key.size_in_bits() != 1024:
        sys.exit("keys/server_private.pem must be RSA-1024 with e = 65537")
    data[RSA_MODULUS_OFFSET:RSA_MODULUS_OFFSET + 128] = key.n.to_bytes(128, "big")
    print("applied: RSA login key replaced with the modulus of", os.path.relpath(KEY_PATH, SERVER_DIR))
    open(dst, "wb").write(data)
    print("wrote", dst)


if __name__ == "__main__":
    main(sys.argv)
