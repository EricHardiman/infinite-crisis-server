"""RSA helpers. Works with pycryptodome (what the old project used) or with
the 'cryptography' package, whichever is installed."""
import struct

try:
    from Crypto.Cipher import PKCS1_OAEP, PKCS1_v1_5
    from Crypto.PublicKey import RSA
    BACKEND = "pycryptodome"
except ImportError:
    RSA = None
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        BACKEND = "cryptography"
    except ImportError:
        BACKEND = None


class Key:
    """An RSA-1024 private key: .n (modulus), .e, .decrypt_session_key(blob)."""

    def __init__(self, pem_bytes):
        if BACKEND == "pycryptodome":
            self._k = RSA.import_key(pem_bytes)
            self.n, self.e, self.bits = self._k.n, self._k.e, self._k.size_in_bits()
        elif BACKEND == "cryptography":
            self._k = serialization.load_pem_private_key(pem_bytes, password=None)
            pub = self._k.public_key().public_numbers()
            self.n, self.e, self.bits = pub.n, pub.e, self._k.key_size
        else:
            raise RuntimeError("install pycryptodome:  pip install pycryptodome")

    def decrypt_session_key(self, blob):
        """Returns (scheme name, plaintext) or (None, None)."""
        if BACKEND == "pycryptodome":
            attempts = [("OAEP-SHA1", lambda: PKCS1_OAEP.new(self._k).decrypt(blob)),
                        ("PKCS1-v1.5", lambda: PKCS1_v1_5.new(self._k).decrypt(blob, None))]
        else:
            attempts = [("OAEP-SHA1", lambda: self._k.decrypt(blob, padding.OAEP(
                            mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None))),
                        ("PKCS1-v1.5", lambda: self._k.decrypt(blob, padding.PKCS1v15()))]
        for name, attempt in attempts:
            try:
                plain = attempt()
            except ValueError:
                plain = None
            if plain:
                return name, plain
        return None, None


def load_key(path):
    with open(path, "rb") as f:
        return Key(f.read())


def generate_key_pem():
    if BACKEND == "pycryptodome":
        return RSA.generate(1024).export_key()
    if BACKEND == "cryptography":
        k = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        return k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                               serialization.NoEncryption())
    raise RuntimeError("install pycryptodome:  pip install pycryptodome")


def find_session_key_blob(hello):
    """The client hello carries '\\x04' '3des' u32 len + RSA blob (128 bytes)."""
    marker = hello.find(b"\x043des")
    if marker < 0 or len(hello) < marker + 9:
        return None
    blob_len = struct.unpack_from("<I", hello, marker + 5)[0]
    blob = hello[marker + 9:marker + 9 + blob_len]
    return blob if blob_len == 128 and len(blob) == 128 else None
