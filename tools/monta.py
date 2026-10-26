"""Junta votos por seção com lat/long do local de votação

Uso: python3 monta.py <turno> <arquivo.zip|csv do TSE ...>
  aceita votacao_secao_2026_BR.zip ou bweb_<t>t_<UF>_*.zip (boletim de urna);
  sem arquivo, usa _dados/secoes/*.csv (saída do coleta.py)
e gera os arquivos do mapa:
  mapa/secoes.bin  -> por seção: lon f32, lat f32, lula u16, bolsonaro u16, idx do local u32
  mapa/locais.json -> [nome do local, município, uf, zona, seção] por índice
"""
import csv, glob, io, json, math, os, struct, sys, zipfile
from collections import defaultdict

AQUI = os.path.dirname(os.path.abspath(__file__))
DADOS = os.path.join(AQUI, '..', '_dados')
SAIDA = os.path.join(AQUI, '..', 'mapa')

def num(s):
    try:
        return float(s.replace(',', '.'))
    except ValueError:
        return None

TURNO = sys.argv[1] if len(sys.argv) > 1 else '2'
FONTES = sys.argv[2:]

# 1) coordenadas por seção (linhas do 2º turno)
coord, locais, idx_local = {}, [], {}
for arq in sorted(glob.glob(os.path.join(DADOS, 'eleitorado_local_votacao_2026_*.csv'))):
    if arq.endswith('BRASIL.csv'):
        continue
    with open(arq, encoding='latin1') as f:
        for r in csv.DictReader(f, delimiter=';'):
            if r['NR_TURNO'] != TURNO:
                continue
            lat, lon = num(r['NR_LATITUDE']), num(r['NR_LONGITUDE'])
            if lat is None or lon is None or lat == -1 or lon == -1 or lat == 0:
                continue
            uf = r['SG_UF'].lower()
            chave_local = (uf, r['CD_MUNICIPIO'], r['NR_LOCAL_VOTACAO'])
            if chave_local not in idx_local:
                idx_local[chave_local] = len(locais)
                locais.append([r['NM_LOCAL_VOTACAO'].title(), r['NM_MUNICIPIO'].title(), uf.upper()])
            coord[(uf, r['CD_MUNICIPIO'].zfill(5), r['NR_ZONA'].zfill(4), r['NR_SECAO'].zfill(4))] = (lon, lat, idx_local[chave_local])

# 2) votos
os.makedirs(SAIDA, exist_ok=True)
def linhas_tse(caminho):
    """Linhas (uf, mun, zona, secao, numero_votavel, votos) do presidente no turno pedido."""
    arqs = []
    if caminho.endswith('.zip'):
        z = zipfile.ZipFile(caminho)
        arqs = [io.TextIOWrapper(z.open(n), encoding='latin1') for n in z.namelist() if n.lower().endswith('.csv')]
    else:
        arqs = [open(caminho, encoding='latin1')]
    for f in arqs:
        for r in csv.DictReader(f, delimiter=';'):
            cargo = r.get('CD_CARGO') or r.get('CD_CARGO_PERGUNTA')
            if r['NR_TURNO'] != TURNO or cargo != '1':
                continue
            yield (r['SG_UF'].lower(), r['CD_MUNICIPIO'].zfill(5), r['NR_ZONA'].zfill(4), r['NR_SECAO'].zfill(4),
                   r['NR_VOTAVEL'], int(r['QT_VOTOS']))

votos = defaultdict(lambda: [0, 0])
if FONTES:
    for fonte in FONTES:
        for uf, mun, zona, sec, nr, qt in linhas_tse(fonte):
            if nr in ('13', '22'):
                votos[(uf, mun, zona, sec)][nr == '22'] += qt
            else:
                votos[(uf, mun, zona, sec)]
else:
    for arq in sorted(glob.glob(os.path.join(DADOS, 'secoes', '*.csv'))):
        with open(arq) as f:
            for r in csv.DictReader(f):
                if r['lula'] or r['bolsonaro']:
                    votos[(r['uf'], r['mun'], r['zona'], r['secao'])] = [int(r['lula'] or 0), int(r['bolsonaro'] or 0)]

os.makedirs(SAIDA, exist_ok=True)
pontos, sem_coord, exterior, tot = [], 0, 0, {'lula': 0, 'bolsonaro': 0}
for k, (l, b) in votos.items():
    tot['lula'] += l; tot['bolsonaro'] += b
    if k[0] == 'zz':
        exterior += 1
        continue
    c = coord.get(k)
    if not c:
        sem_coord += 1
        continue
    pontos.append((c[0], c[1], l, b, c[2], int(k[2]), int(k[3])))

# seções do mesmo local ficam numa roseta pequena em volta do ponto (senão uma tampa a outra)
por_local = defaultdict(list)
for p in pontos:
    por_local[p[4]].append(p)
saida = []
for lst in por_local.values():
    lst.sort(key=lambda p: (p[5], p[6]))
    n = len(lst)
    for i, p in enumerate(lst):
        if n == 1:
            dx = dy = 0
        else:
            ang = i * 2.399963  # ângulo de ouro: espiral compacta
            r = 0.00012 * math.sqrt(i + 0.5)
            dx, dy = r * math.cos(ang) / max(math.cos(math.radians(p[1])), 0.2), r * math.sin(ang)
        saida.append((p[0] + dx, p[1] + dy, p[2], p[3], p[4], p[5], p[6]))

with open(os.path.join(SAIDA, 'secoes.bin'), 'wb') as f:
    for lon, lat, l, b, li, z, s in saida:
        f.write(struct.pack('<ffHHIHH', lon, lat, min(l, 65535), min(b, 65535), li, z, s))
with open(os.path.join(SAIDA, 'locais.json'), 'w') as f:
    json.dump(locais, f, ensure_ascii=False, separators=(',', ':'))

fonte = ', '.join(os.path.basename(x) for x in FONTES) or 'boletins de urna por seção'
obs = f'{sem_coord} seções sem coordenada e {exterior} do exterior ficaram fora do mapa.'
with open(os.path.join(SAIDA, 'meta.json'), 'w') as f:
    json.dump({'turno': int(TURNO), 'fonte': fonte, 'obs': obs, 'secoes': len(saida)}, f, ensure_ascii=False)
print(f'seções no mapa: {len(saida)} | sem coordenada: {sem_coord} | exterior: {exterior}')
print(f"total lido: Lula {tot['lula']:,} x Bolsonaro {tot['bolsonaro']:,}")
