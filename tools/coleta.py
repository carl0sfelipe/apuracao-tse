"""Baixa o boletim de urna de cada seção do 2º turno (presidente) direto do TSE.

Uso: python3 coleta.py [uf ...]     (sem argumento = todas)
Saída: _dados/secoes/<uf>.csv  (retoma de onde parou)
"""
import csv, json, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import ber

BASE = 'https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3221'
PLEITO, ELEICAO, CARGO = '3221', 6258, 1
UFS = 'ac al am ap ba ce df es go ma mg ms mt pa pb pe pi pr rj rn ro rr rs sc se sp to zz'.split()
OUT = os.path.join(os.path.dirname(__file__), '..', '_dados', 'secoes')
CAMPOS = ['uf', 'mun', 'zona', 'secao', 'local', 'aptos', 'comp', 'lula', 'bolsonaro', 'brancos', 'nulos', 'status']

_tl = threading.local()
def sess():
    if not hasattr(_tl, 's'):
        _tl.s = requests.Session()
        _tl.s.mount('https://', requests.adapters.HTTPAdapter(pool_maxsize=4, max_retries=3))
    return _tl.s

def get(url, binary=False):
    for tentativa in range(5):
        try:
            r = sess().get(url, timeout=30)
            if r.status_code == 200:
                return r.content if binary else r.json()
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(1 + tentativa * 2)
    raise RuntimeError('falhou: ' + url)

def ints(nodes):
    return [int.from_bytes(v, 'big', signed=True) for c, cons, t, v in nodes if not cons and c == 0 and t == 2]

def seqs(nodes):
    return [n for n in nodes if n[1]]

def parse_bu(b):
    env = ber.decode(b)[0][3]
    bu = ber.decode(env[-1][3])[0][3]
    res = {}
    for c, cons, t, v in bu:
        if not cons:
            continue
        # identificação da seção: SEQ{ SEQ{mun, zona}, local, secao }
        if len(v) >= 3 and v[0][1] and len(ints(v[0][3])) == 2 and len(ints(v[1:])) == 2 and 'local' not in res:
            res['local'], _ = ints(v[1:])
        # resultados por eleição: SEQ OF SEQ{ idEleicao, aptos, ..., SEQ OF resultadoVotacao }
        for e in v:
            if not e[1] or not e[3] or e[3][0][1] or ints(e[3][:1]) != [ELEICAO]:
                continue
            res['aptos'] = ints(e[3][1:2])[0]
            for rv in seqs(e[3])[0][3]:             # resultadosVotacao
                res['comp'] = ints(rv[3])[0]
                for tvc in seqs(rv[3])[0][3]:       # totaisVotosCargo
                    cod = [x for x in tvc[3] if x[0] == 2 and x[2] == 1]
                    if not cod or int.from_bytes(cod[0][3], 'big') != CARGO:
                        continue
                    for vv in seqs(tvc[3])[0][3]:   # votosVotaveis
                        d = {x[2]: x for x in vv[3] if x[0] == 2}
                        tipo = int.from_bytes(d[1][3], 'big')
                        qtd = int.from_bytes(d[2][3], 'big')
                        if tipo == 1:
                            num = ints(d[3][3])[-1]
                            res[{13: 'lula', 22: 'bolsonaro'}.get(num, f'c{num}')] = qtd
                        elif tipo == 2:
                            res['brancos'] = qtd
                        elif tipo == 3:
                            res['nulos'] = qtd
    return res

def secao(uf, mun, zona, sec):
    pasta = f'{BASE}/dados/{uf}/{mun}/{zona}/{sec}'
    aux = get(f'{pasta}/p00{PLEITO}-{uf}-m{mun}-z{zona}-s{sec}-aux.json')
    linha = dict(uf=uf, mun=mun, zona=zona, secao=sec)
    if not aux:
        return {**linha, 'status': 'sem-aux'}
    for h in aux.get('hashes', []):
        bu = next((a['nm'] for a in h['arq'] if a['tp'] == 'bu'), None)
        if not bu:
            continue
        dados = get(f"{pasta}/{h['hash']}/{bu}", binary=True)
        if dados:
            r = parse_bu(dados)
            return {**linha, **r, 'status': aux.get('st', '')}
    return {**linha, 'status': 'sem-bu:' + aux.get('st', '')}

def coleta_uf(uf, pool):
    os.makedirs(OUT, exist_ok=True)
    arq = os.path.join(OUT, f'{uf}.csv')
    feitas = set()
    if os.path.exists(arq):
        with open(arq) as f:
            feitas = {(r['mun'], r['zona'], r['secao']) for r in csv.DictReader(f)}
    cs = get(f'{BASE}/config/{uf}/{uf}-p00{PLEITO}-cs.json')
    todas = [(m['cd'], z['cd'], s['ns']) for ab in cs['abr'] for m in ab['mu'] for z in m['zon'] for s in z['sec']]
    falta = [t for t in todas if t not in feitas]
    print(f'{uf}: {len(todas)} seções, faltam {len(falta)}', flush=True)
    novo = not os.path.exists(arq)
    with open(arq, 'a', newline='') as f:
        w = csv.DictWriter(f, CAMPOS, extrasaction='ignore')
        if novo:
            w.writeheader()
        futs = [pool.submit(secao, uf, *t) for t in falta]
        for i, fu in enumerate(as_completed(futs), 1):
            try:
                w.writerow(fu.result())
            except Exception as e:
                print(f'  erro {uf}: {e}', flush=True)
            if i % 5000 == 0:
                f.flush()
                print(f'  {uf} {i}/{len(falta)}', flush=True)

if __name__ == '__main__':
    ufs = sys.argv[1:] or UFS
    with ThreadPoolExecutor(int(os.environ.get('THREADS', 48))) as pool:
        for uf in ufs:
            coleta_uf(uf, pool)
