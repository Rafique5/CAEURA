"""
Field Shift - NASA Space Apps 2026
Passo 5: vai buscar o clima ao NASA POWER e calcula os indicadores climaticos.

Produz clima.json, no formato combinado no contrato de dados.

Correr:  python dados_nasa.py
"""

import json
import math
import urllib.request
from datetime import date

# ---------------------------------------------------------------------------
# CONFIGURACAO
# ---------------------------------------------------------------------------

LUGARES = [
    {"nome": "Chokwe", "latitude": -24.5333, "longitude": 32.9833},
    {"nome": "Gurue",  "latitude": -15.4669, "longitude": 36.9778},
]

ANO_INICIO = 2015
ANO_FIM = 2024

# Epoca agricola principal no hemisferio sul: Novembro a Abril.
# Atravessa o fim do ano, por isso e tratada como epoca "a cavalo".
EPOCA_MES_INICIO = 11
EPOCA_MES_FIM = 4

PARAMETROS = [
    "T2M",                  # temperatura media (C)
    "T2M_MAX",              # temperatura maxima (C)
    "T2M_MIN",              # temperatura minima (C)
    "PRECTOTCORR",          # precipitacao corrigida (mm/dia)
    "RH2M",                 # humidade relativa (%)
    "ALLSKY_SFC_SW_DWN",    # radiacao solar a superficie (MJ/m2/dia)
    "WS2M",                 # vento a 2 m (m/s) - necessario para o ET0
]

EM_FALTA = -999.0


# ---------------------------------------------------------------------------
# OBTER OS DADOS
# ---------------------------------------------------------------------------

def buscar_power(latitude, longitude, ano_inicio, ano_fim):
    """Pede a serie diaria ao NASA POWER e devolve o JSON cru."""
    url = (
        "https://power.larc.nasa.gov/api/temporal/daily/point"
        f"?parameters={','.join(PARAMETROS)}"
        "&community=AG"
        f"&latitude={latitude}"
        f"&longitude={longitude}"
        f"&start={ano_inicio}0101"
        f"&end={ano_fim}1231"
        "&format=JSON"
    )
    print(f"  a pedir: {latitude}, {longitude}")
    with urllib.request.urlopen(url, timeout=120) as resposta:
        return json.loads(resposta.read().decode("utf-8"))


def em_linhas(bruto):
    """
    Converte o formato do POWER numa lista de dias.

    O POWER devolve properties.parameter.T2M = {"20150101": 24.66, ...}
    Isto transforma em [{"data": "20150101", "T2M": 24.66, ...}, ...]
    e descarta qualquer dia que tenha um valor em falta.
    """
    parametros = bruto["properties"]["parameter"]
    datas = sorted(parametros[PARAMETROS[0]].keys())

    linhas = []
    descartados = 0
    for d in datas:
        linha = {"data": d}
        valido = True
        for p in PARAMETROS:
            v = parametros[p].get(d)
            if v is None or v <= EM_FALTA:
                valido = False
                break
            linha[p] = v
        if valido:
            linhas.append(linha)
        else:
            descartados += 1

    if descartados:
        print(f"  {descartados} dias descartados por falta de dados")
    return linhas


# ---------------------------------------------------------------------------
# ET0 - EVAPOTRANSPIRACAO DE REFERENCIA (FAO-56 Penman-Monteith)
# ---------------------------------------------------------------------------
# Referencia: Allen et al. (1998), FAO Irrigation and Drainage Paper 56,
# equacao 6. Devolve milimetros por dia.

def pressao_vapor_saturacao(t):
    """es(T) em kPa, para a temperatura t em C."""
    return 0.6108 * math.exp(17.27 * t / (t + 237.3))


def radiacao_extraterrestre(latitude, dia_do_ano):
    """Ra em MJ/m2/dia. Depende so da latitude e do dia do ano."""
    gsc = 0.0820                                   # constante solar
    phi = math.radians(latitude)
    dr = 1 + 0.033 * math.cos(2 * math.pi * dia_do_ano / 365)
    delta = 0.409 * math.sin(2 * math.pi * dia_do_ano / 365 - 1.39)

    # angulo horario do por do sol, protegido contra latitudes polares
    x = -math.tan(phi) * math.tan(delta)
    x = max(-1.0, min(1.0, x))
    ws = math.acos(x)

    return (24 * 60 / math.pi) * gsc * dr * (
        ws * math.sin(phi) * math.sin(delta)
        + math.cos(phi) * math.cos(delta) * math.sin(ws)
    )


def et0_dia(linha, latitude, altitude):
    """ET0 em mm/dia para um dia, pelo metodo FAO-56 Penman-Monteith."""
    tmax = linha["T2M_MAX"]
    tmin = linha["T2M_MIN"]
    tmed = linha["T2M"]
    rh = linha["RH2M"]
    rs = linha["ALLSKY_SFC_SW_DWN"]
    u2 = linha["WS2M"]

    dia_do_ano = date(
        int(linha["data"][0:4]), int(linha["data"][4:6]), int(linha["data"][6:8])
    ).timetuple().tm_yday

    # pressao atmosferica e constante psicrometrica
    p = 101.3 * ((293 - 0.0065 * altitude) / 293) ** 5.26
    gama = 0.000665 * p

    # pressoes de vapor
    es = (pressao_vapor_saturacao(tmax) + pressao_vapor_saturacao(tmin)) / 2
    ea = es * rh / 100

    # declive da curva de pressao de vapor
    delta = (4098 * pressao_vapor_saturacao(tmed)) / ((tmed + 237.3) ** 2)

    # radiacao liquida
    ra = radiacao_extraterrestre(latitude, dia_do_ano)
    rso = (0.75 + 2e-5 * altitude) * ra
    rns = 0.77 * rs                                # albedo 0.23

    sigma = 4.903e-9
    razao = min(rs / rso, 1.0) if rso > 0 else 1.0
    rnl = (
        sigma
        * (((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2)
        * (0.34 - 0.14 * math.sqrt(max(ea, 0)))
        * (1.35 * razao - 0.35)
    )
    rn = rns - rnl

    g = 0  # fluxo de calor no solo, desprezavel ao dia

    numerador = 0.408 * delta * (rn - g) + gama * (900 / (tmed + 273)) * u2 * (es - ea)
    denominador = delta + gama * (1 + 0.34 * u2)
    return max(numerador / denominador, 0.0)


# ---------------------------------------------------------------------------
# AGREGACAO POR EPOCA
# ---------------------------------------------------------------------------

def na_epoca(data_str):
    """True se a data cai na epoca agricola (Nov-Abr)."""
    mes = int(data_str[4:6])
    return mes >= EPOCA_MES_INICIO or mes <= EPOCA_MES_FIM


def rotulo_epoca(data_str):
    """A epoca 2015-16 vai de Nov/2015 a Abr/2016."""
    ano = int(data_str[0:4])
    mes = int(data_str[4:6])
    inicio = ano if mes >= EPOCA_MES_INICIO else ano - 1
    return f"{inicio}-{str(inicio + 1)[2:]}"


def agregar(linhas, latitude, altitude):
    """Soma chuva, ET0 e graus-dia por epoca, e faz a media das epocas."""
    epocas = {}

    for linha in linhas:
        if not na_epoca(linha["data"]):
            continue

        rotulo = rotulo_epoca(linha["data"])
        e = epocas.setdefault(
            rotulo,
            {"dias": 0, "chuva": 0.0, "et0": 0.0, "graus_dia_base10": 0.0,
             "dias_acima_35": 0},
        )

        e["dias"] += 1
        e["chuva"] += linha["PRECTOTCORR"]
        e["et0"] += et0_dia(linha, latitude, altitude)

        # graus-dia com base 10 C - a base real muda por cultura,
        # esta serve de referencia comum para comparar lugares
        media = (linha["T2M_MAX"] + linha["T2M_MIN"]) / 2
        e["graus_dia_base10"] += max(0.0, media - 10.0)

        if linha["T2M_MAX"] > 35:
            e["dias_acima_35"] += 1

    # so epocas completas: pelo menos 150 dos ~181 dias
    completas = {k: v for k, v in epocas.items() if v["dias"] >= 150}

    if not completas:
        raise ValueError("nenhuma epoca completa nos dados recebidos")

    n = len(completas)
    return {
        "epocas_usadas": sorted(completas.keys()),
        "chuva_epoca_mm": round(sum(v["chuva"] for v in completas.values()) / n, 1),
        "et0_epoca_mm": round(sum(v["et0"] for v in completas.values()) / n, 1),
        "graus_dia_base10": round(
            sum(v["graus_dia_base10"] for v in completas.values()) / n, 1
        ),
        "dias_acima_35": round(
            sum(v["dias_acima_35"] for v in completas.values()) / n, 1
        ),
        "por_epoca": {
            k: {
                "chuva_mm": round(v["chuva"], 1),
                "et0_mm": round(v["et0"], 1),
                "graus_dia_base10": round(v["graus_dia_base10"], 1),
            }
            for k, v in sorted(completas.items())
        },
    }


# ---------------------------------------------------------------------------
# PRINCIPAL
# ---------------------------------------------------------------------------

def main():
    saida = {
        "fonte": (
            "NASA POWER (Prediction of Worldwide Energy Resources), "
            "comunidade AG, serie diaria. "
            "ET0 calculado pelo metodo FAO-56 Penman-Monteith."
        ),
        "periodo": f"{ANO_INICIO}-{ANO_FIM}",
        "epoca": "Novembro a Abril",
        "lugares": [],
    }

    for lugar in LUGARES:
        print(f"\n{lugar['nome']}")
        bruto = buscar_power(
            lugar["latitude"], lugar["longitude"], ANO_INICIO, ANO_FIM
        )

        # a altitude vem no terceiro elemento de geometry.coordinates
        coords = bruto["geometry"]["coordinates"]
        altitude = coords[2] if len(coords) > 2 else 0.0

        linhas = em_linhas(bruto)
        print(f"  {len(linhas)} dias validos")

        resumo = agregar(linhas, lugar["latitude"], altitude)

        registo = {
            "nome": lugar["nome"],
            "latitude": lugar["latitude"],
            "longitude": lugar["longitude"],
            "altitude_m": round(altitude, 1),
            **resumo,
        }
        saida["lugares"].append(registo)

        print(f"  altitude      {registo['altitude_m']} m")
        print(f"  chuva/epoca   {registo['chuva_epoca_mm']} mm")
        print(f"  ET0/epoca     {registo['et0_epoca_mm']} mm")
        print(f"  graus-dia     {registo['graus_dia_base10']}")
        print(f"  balanco       {round(registo['chuva_epoca_mm'] - registo['et0_epoca_mm'], 1)} mm")

    with open("clima.json", "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)

    print("\nEscrito: clima.json")


if __name__ == "__main__":
    main()
