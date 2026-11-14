"""
Field Shift - NASA Space Apps 2026
Passo 7: o motor de decisao.

Le clima.json e culturas.json, gera todas as rotacoes possiveis,
pontua cada uma em cinco indicadores, aplica as prioridades do
agricultor como pesos, e devolve as melhores.

Correr:  python motor.py
"""

import json
import math

DIAS_EPOCA = 181          # Novembro a Abril
HORIZONTE = 4             # quantas epocas a rotacao cobre


# ---------------------------------------------------------------------------
# CARREGAR
# ---------------------------------------------------------------------------

def carregar():
    with open("clima.json", encoding="utf-8") as f:
        clima = json.load(f)
    with open("culturas.json", encoding="utf-8") as f:
        culturas = json.load(f)["culturas"]
    return {l["nome"]: l for l in clima["lugares"]}, culturas


# ---------------------------------------------------------------------------
# PROPRIEDADES DERIVADAS DE CADA CULTURA
# ---------------------------------------------------------------------------

def kc_medio(c):
    """
    Kc medio ao longo do ciclo, com a fase intermedia a pesar o dobro.
    Aproximacao da curva do FAO-56 sem precisar das duracoes de cada fase.
    """
    return (c["kc_ini"] + 2 * c["kc_mid"] + c["kc_end"]) / 4


def epocas_ocupadas(c):
    """
    Quantas epocas a cultura ocupa. A mandioca tem ciclo de 300 dias,
    por isso ocupa duas. Sem isto, as culturas longas ganham sempre,
    porque so lhes era cobrada uma epoca de agua.
    """
    return max(1, math.ceil(c["ciclo_dias"] / DIAS_EPOCA))


# ---------------------------------------------------------------------------
# OS CINCO INDICADORES
# Cada um devolve um valor entre 0 e 1, onde 1 e o melhor.
# ---------------------------------------------------------------------------

def ind_agua(sequencia, lugar):
    """
    Compara a agua que as culturas pedem com a chuva que cai.
    ETc = Kc medio x ET0. Devolve o deficit em mm: quanto maior, pior.
    O sinal e invertido na normalizacao.
    """
    et0_dia = lugar["et0_epoca_mm"] / DIAS_EPOCA
    chuva_dia = lugar["chuva_epoca_mm"] / DIAS_EPOCA

    deficit_total = 0.0
    for c in sequencia:
        dias = c["ciclo_dias"]
        etc = kc_medio(c) * et0_dia * dias
        chuva = chuva_dia * dias
        deficit_total += max(0.0, etc - chuva)

    return -deficit_total


def ind_calor(sequencia, lugar):
    """
    Verifica se a epoca acumula graus-dia suficientes para cada cultura.

    O clima.json traz graus-dia com base 10. Para culturas com outra base,
    aproximamos: GDD(base b) = GDD(base 10) - (b - 10) x dias.
    """
    gdd10 = lugar["graus_dia_base10"]

    pontos = []
    for c in sequencia:
        ajuste = (c["temp_base_c"] - 10) * DIAS_EPOCA
        disponivel = max(0.0, gdd10 - ajuste) * epocas_ocupadas(c)
        preciso = c["graus_dia_total"]
        if preciso <= 0:
            pontos.append(1.0)
        else:
            pontos.append(min(1.0, disponivel / preciso))
    return sum(pontos) / len(pontos)


def ind_azoto(sequencia):
    """
    Soma o efeito no azoto ao longo da rotacao.
    Leguminosas somam, cereais e raizes subtraem.
    """
    return float(sum(c["azoto"] for c in sequencia))


def ind_pragas(sequencia, cultura_anterior):
    """
    Penaliza culturas da mesma familia botanica em epocas seguidas,
    e penaliza mais ainda a repeticao da mesma cultura.
    """
    cadeia = ([cultura_anterior] if cultura_anterior else []) + list(sequencia)
    if len(cadeia) < 2:
        return 1.0

    transicoes = len(cadeia) - 1
    penalizacao = 0.0
    for a, b in zip(cadeia, cadeia[1:]):
        if a["id"] == b["id"]:
            penalizacao += 1.0
        elif a["familia"] == b["familia"]:
            penalizacao += 0.6
    return max(0.0, 1.0 - penalizacao / transicoes)


def ind_raiz(sequencia, cultura_anterior):
    """
    Premeia a alternancia entre profundidades de raiz diferentes,
    que melhora a estrutura e a infiltracao do solo.
    """
    cadeia = ([cultura_anterior] if cultura_anterior else []) + list(sequencia)
    if len(cadeia) < 2:
        return 1.0

    nivel = {"rasa": 0, "media": 1, "funda": 2}
    transicoes = len(cadeia) - 1
    ganho = 0.0
    for a, b in zip(cadeia, cadeia[1:]):
        ganho += abs(nivel[a["raiz"]] - nivel[b["raiz"]]) / 2.0
    return ganho / transicoes


# ---------------------------------------------------------------------------
# GERAR E PONTUAR
# ---------------------------------------------------------------------------

def gerar_sequencias(culturas, slots=HORIZONTE):
    """
    Todas as rotacoes que cabem no horizonte.
    Uma cultura que ocupa duas epocas consome dois lugares.
    """
    resultado = []

    def recursivo(parcial, restantes):
        if restantes == 0:
            resultado.append(tuple(parcial))
            return
        for c in culturas:
            custo = epocas_ocupadas(c)
            if custo > restantes:
                continue
            # Regra agronomica dura: repetir a mesma cultura em epocas
            # seguidas nao e uma rotacao, e monocultura. Excluimos essas
            # sequencias do conjunto em vez de apenas as penalizar, porque
            # senao distorcem a escala dos indicadores: quatro epocas de
            # leguminosa dariam o saldo de azoto maximo possivel e fariam
            # parecer fracas todas as rotacoes reais.
            if parcial and parcial[-1]["id"] == c["id"]:
                continue
            parcial.append(c)
            recursivo(parcial, restantes - custo)
            parcial.pop()

    recursivo([], slots)
    return resultado


INDICADORES = ["agua", "calor", "azoto", "pragas", "raiz"]


def avaliar_todas(lugar, culturas, cultura_anterior):
    """
    Calcula os valores brutos dos cinco indicadores para cada rotacao
    possivel, e normaliza cada indicador de 0 a 1 ao longo de todas elas.

    A normalizacao e feita aqui, e nao dentro de cada indicador, por uma
    razao importante: sem ela os indicadores vivem em escalas diferentes
    e os pesos do agricultor quase nao mudam o resultado. Normalizados,
    um peso de 3 na agua pesa mesmo tres vezes mais.
    """
    avaliadas = []
    for seq in gerar_sequencias(culturas):
        avaliadas.append({
            "culturas": seq,
            "brutos": {
                "agua": ind_agua(seq, lugar),
                "calor": ind_calor(seq, lugar),
                "azoto": ind_azoto(seq),
                "pragas": ind_pragas(seq, cultura_anterior),
                "raiz": ind_raiz(seq, cultura_anterior),
            },
        })

    # normalizacao min-max por indicador
    discrimina = {}
    for k in INDICADORES:
        valores = [a["brutos"][k] for a in avaliadas]
        lo, hi = min(valores), max(valores)
        discrimina[k] = (hi - lo) > 1e-9
        for a in avaliadas:
            if discrimina[k]:
                a.setdefault("notas", {})[k] = (a["brutos"][k] - lo) / (hi - lo)
            else:
                # o indicador e igual para todas as rotacoes: nao distingue
                # nada neste lugar, e isso e informacao util
                a.setdefault("notas", {})[k] = 1.0

    return avaliadas, discrimina


def melhores(lugar, culturas, cultura_anterior, pesos, quantas=5):
    avaliadas, discrimina = avaliar_todas(lugar, culturas, cultura_anterior)
    soma_pesos = sum(pesos.values()) or 1.0

    for a in avaliadas:
        a["total"] = sum(
            a["notas"][k] * pesos.get(k, 0) for k in INDICADORES
        ) / soma_pesos

    avaliadas.sort(key=lambda x: -x["total"])

    # Diversidade: nao mostrar duas rotacoes com o mesmo conjunto de culturas.
    # Sem isto as cinco melhores saem quase iguais, e o agricultor nao aprende
    # nada ao olhar para a segunda. O objectivo da lista e mostrar alternativas
    # com compromissos diferentes, nao variacoes da mesma.
    vistas = set()
    escolhidas = []
    for a in avaliadas:
        assinatura = tuple(sorted(c["id"] for c in a["culturas"]))
        if assinatura in vistas:
            continue
        vistas.add(assinatura)
        escolhidas.append(a)
        if len(escolhidas) == quantas:
            break

    saida = []
    for a in escolhidas:
        saida.append({
            "sequencia": [c["nome"] for c in a["culturas"]],
            "total": round(a["total"], 3),
            "notas": {k: round(v, 3) for k, v in a["notas"].items()},
            "deficit_agua_mm": round(-a["brutos"]["agua"], 1),
            "saldo_azoto": a["brutos"]["azoto"],
        })
    return saida, discrimina


# ---------------------------------------------------------------------------
# DEMONSTRACAO
# ---------------------------------------------------------------------------

PERFIS = {
    "equilibrado": {"agua": 1, "calor": 1, "azoto": 1, "pragas": 1, "raiz": 1},
    "poupar agua": {"agua": 3, "calor": 1, "azoto": 1, "pragas": 1, "raiz": 1},
    "recuperar solo": {"agua": 1, "calor": 1, "azoto": 3, "pragas": 2, "raiz": 2},
}


def main():
    lugares, culturas = carregar()
    por_id = {c["id"]: c for c in culturas}
    anterior = por_id["milho"]       # a epoca passada plantaram milho

    total_seq = len(gerar_sequencias(culturas))
    print(f"{len(culturas)} culturas, horizonte de {HORIZONTE} epocas")
    print(f"{total_seq} rotacoes avaliadas por cada combinacao\n")

    for nome_lugar, lugar in lugares.items():
        print("=" * 68)
        print(f"{nome_lugar}   chuva {lugar['chuva_epoca_mm']} mm   "
              f"ET0 {lugar['et0_epoca_mm']} mm   "
              f"graus-dia {lugar['graus_dia_base10']}")
        print(f"cultura anterior: {anterior['nome']}")

        for nome_perfil, pesos in PERFIS.items():
            print(f"\n  prioridade: {nome_perfil}")
            resultados, discrimina = melhores(lugar, culturas, anterior, pesos)

            mudos = [k for k, v in discrimina.items() if not v]
            if mudos:
                print(f"   (nao distingue neste lugar: {', '.join(mudos)})")

            for i, r in enumerate(resultados, 1):
                seq = " > ".join(r["sequencia"])
                n = r["notas"]
                print(f"   {i}. {seq}")
                print(f"      total {r['total']:.3f}   "
                      f"agua {n['agua']:.2f}  calor {n['calor']:.2f}  "
                      f"azoto {n['azoto']:.2f}  pragas {n['pragas']:.2f}  "
                      f"raiz {n['raiz']:.2f}")
                print(f"      deficit de agua {r['deficit_agua_mm']} mm   "
                      f"saldo de azoto {r['saldo_azoto']:+.0f}")
        print()


if __name__ == "__main__":
    main()
