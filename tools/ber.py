"""Decodificador BER mínimo (só o necessário para o boletim de urna do TSE)."""

def _len(b, i):
    n = b[i]; i += 1
    if n < 0x80:
        return n, i
    k = n & 0x7f
    return int.from_bytes(b[i:i+k], 'big'), i + k

def decode(b, i=0, end=None):
    """Lista de (classe, construído, tag, valor); valor é lista (construído) ou bytes."""
    end = len(b) if end is None else end
    out = []
    while i < end:
        t = b[i]; i += 1
        cls, cons, tag = t >> 6, bool(t & 0x20), t & 0x1f
        if tag == 0x1f:
            tag = 0
            while True:
                x = b[i]; i += 1
                tag = (tag << 7) | (x & 0x7f)
                if not x & 0x80:
                    break
        n, i = _len(b, i)
        v = decode(b, i, i + n) if cons else b[i:i+n]
        out.append((cls, cons, tag, v))
        i += n
    return out

def dump(nodes, ind=0):
    for cls, cons, tag, v in nodes:
        name = f"{'UAPC'[cls]}{tag}"
        if cons:
            print(' ' * ind + name)
            dump(v, ind + 2)
        else:
            s = v[:24].hex() if len(v) > 8 else int.from_bytes(v, 'big', signed=True)
            try:
                txt = v.decode('ascii') if len(v) > 1 and all(32 <= c < 127 for c in v) else ''
            except Exception:
                txt = ''
            print(' ' * ind + f"{name} len={len(v)} {txt or s}")
