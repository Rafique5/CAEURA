/*
 * Field Shift - NASA Space Apps 2026
 * Motor de decisao, traduzido de motor.py.
 *
 * Nao tem dependencias e nao precisa de servidor. Corre no browser
 * dentro de um <script type="module">, e tambem em Node para testes.
 *
 * As funcoes recebem os dados como argumentos, por isso sao puras e
 * faceis de testar. O carregamento dos ficheiros fica a cargo de quem
 * as chama.
 */

export const DIAS_EPOCA = 181;      // Novembro a Abril
export const HORIZONTE = 4;         // quantas epocas a rotacao cobre
export const INDICADORES = ["agua", "calor", "azoto", "pragas", "raiz"];

const NIVEL_RAIZ = { rasa: 0, media: 1, funda: 2 };

/* ------------------------------------------------------------------ *
 * Propriedades derivadas de cada cultura
 * ------------------------------------------------------------------ */

/**
 * Kc medio ao longo do ciclo, com a fase intermedia a pesar o dobro.
 * Aproximacao da curva do FAO-56 sem precisar das duracoes de cada fase.
 */
export function kcMedio(c) {
  return (c.kc_ini + 2 * c.kc_mid + c.kc_end) / 4;
}

/**
 * Quantas epocas a cultura ocupa. A mandioca tem ciclo de 300 dias,
 * por isso ocupa duas. Sem isto, as culturas longas ganhavam sempre,
 * porque so lhes era cobrada uma epoca de agua.
 */
export function epocasOcupadas(c) {
  return Math.max(1, Math.ceil(c.ciclo_dias / DIAS_EPOCA));
}

/* ------------------------------------------------------------------ *
 * Os cinco indicadores (valores brutos; a normalizacao vem depois)
 * ------------------------------------------------------------------ */

/**
 * Compara a agua que as culturas pedem com a chuva que cai.
 * ETc = Kc medio x ET0. Devolve o deficit em mm com sinal negativo,
 * para que maior seja sempre melhor.
 */
export function indAgua(sequencia, lugar) {
  const et0Dia = lugar.et0_epoca_mm / DIAS_EPOCA;
  const chuvaDia = lugar.chuva_epoca_mm / DIAS_EPOCA;

  let deficit = 0;
  for (const c of sequencia) {
    const dias = c.ciclo_dias;
    const etc = kcMedio(c) * et0Dia * dias;
    const chuva = chuvaDia * dias;
    deficit += Math.max(0, etc - chuva);
  }
  return -deficit;
}

/**
 * Verifica se a epoca acumula graus-dia suficientes para cada cultura.
 *
 * O clima.json traz graus-dia com base 10. Para culturas com outra base,
 * aproximamos: GDD(base b) = GDD(base 10) - (b - 10) x dias.
 */
export function indCalor(sequencia, lugar) {
  const gdd10 = lugar.graus_dia_base10;

  let soma = 0;
  for (const c of sequencia) {
    const ajuste = (c.temp_base_c - 10) * DIAS_EPOCA;
    const disponivel = Math.max(0, gdd10 - ajuste) * epocasOcupadas(c);
    const preciso = c.graus_dia_total;
    soma += preciso <= 0 ? 1 : Math.min(1, disponivel / preciso);
  }
  return soma / sequencia.length;
}

/**
 * Soma o efeito no azoto ao longo da rotacao.
 * Leguminosas somam, cereais e raizes subtraem.
 */
export function indAzoto(sequencia) {
  return sequencia.reduce((s, c) => s + c.azoto, 0);
}

/**
 * Penaliza culturas da mesma familia botanica em epocas seguidas,
 * e penaliza mais ainda a repeticao da mesma cultura.
 */
export function indPragas(sequencia, culturaAnterior) {
  const cadeia = culturaAnterior
    ? [culturaAnterior, ...sequencia]
    : [...sequencia];
  if (cadeia.length < 2) return 1;

  const transicoes = cadeia.length - 1;
  let penalizacao = 0;
  for (let i = 0; i < transicoes; i++) {
    const a = cadeia[i];
    const b = cadeia[i + 1];
    if (a.id === b.id) penalizacao += 1.0;
    else if (a.familia === b.familia) penalizacao += 0.6;
  }
  return Math.max(0, 1 - penalizacao / transicoes);
}

/**
 * Premeia a alternancia entre profundidades de raiz diferentes,
 * que melhora a estrutura e a infiltracao do solo.
 */
export function indRaiz(sequencia, culturaAnterior) {
  const cadeia = culturaAnterior
    ? [culturaAnterior, ...sequencia]
    : [...sequencia];
  if (cadeia.length < 2) return 1;

  const transicoes = cadeia.length - 1;
  let ganho = 0;
  for (let i = 0; i < transicoes; i++) {
    ganho += Math.abs(NIVEL_RAIZ[cadeia[i].raiz] - NIVEL_RAIZ[cadeia[i + 1].raiz]) / 2;
  }
  return ganho / transicoes;
}

/* ------------------------------------------------------------------ *
 * Gerar e pontuar
 * ------------------------------------------------------------------ */

/**
 * Todas as rotacoes que cabem no horizonte.
 * Uma cultura que ocupa duas epocas consome dois lugares.
 *
 * Regra agronomica dura: repetir a mesma cultura em epocas seguidas
 * nao e rotacao, e monocultura. Excluimos essas sequencias do conjunto
 * em vez de apenas as penalizar, porque senao distorcem a escala dos
 * indicadores: quatro epocas de leguminosa dariam o saldo de azoto
 * maximo possivel e fariam parecer fracas todas as rotacoes reais.
 */
export function gerarSequencias(culturas, slots = HORIZONTE) {
  const resultado = [];
  const parcial = [];

  function recursivo(restantes) {
    if (restantes === 0) {
      resultado.push([...parcial]);
      return;
    }
    for (const c of culturas) {
      const custo = epocasOcupadas(c);
      if (custo > restantes) continue;
      if (parcial.length && parcial[parcial.length - 1].id === c.id) continue;
      parcial.push(c);
      recursivo(restantes - custo);
      parcial.pop();
    }
  }

  recursivo(slots);
  return resultado;
}

/**
 * Calcula os valores brutos dos cinco indicadores para cada rotacao
 * possivel, e normaliza cada indicador de 0 a 1 ao longo de todas elas.
 *
 * A normalizacao e feita aqui, e nao dentro de cada indicador, por uma
 * razao importante: sem ela os indicadores vivem em escalas diferentes
 * e os pesos do agricultor quase nao mudam o resultado. Normalizados,
 * um peso de 3 na agua pesa mesmo tres vezes mais.
 *
 * Devolve { avaliadas, discrimina }. Em discrimina, um indicador a false
 * significa que deu o mesmo valor a todas as rotacoes: naquele lugar nao
 * distingue nada, e isso e informacao util para mostrar ao utilizador.
 */
export function avaliarTodas(lugar, culturas, culturaAnterior) {
  const avaliadas = gerarSequencias(culturas).map((seq) => ({
    culturas: seq,
    brutos: {
      agua: indAgua(seq, lugar),
      calor: indCalor(seq, lugar),
      azoto: indAzoto(seq),
      pragas: indPragas(seq, culturaAnterior),
      raiz: indRaiz(seq, culturaAnterior),
    },
    notas: {},
  }));

  const discrimina = {};
  for (const k of INDICADORES) {
    let lo = Infinity;
    let hi = -Infinity;
    for (const a of avaliadas) {
      if (a.brutos[k] < lo) lo = a.brutos[k];
      if (a.brutos[k] > hi) hi = a.brutos[k];
    }
    discrimina[k] = hi - lo > 1e-9;
    for (const a of avaliadas) {
      a.notas[k] = discrimina[k] ? (a.brutos[k] - lo) / (hi - lo) : 1;
    }
  }

  return { avaliadas, discrimina };
}

/**
 * As melhores rotacoes para um lugar, dadas as prioridades do agricultor.
 *
 * Os pesos sao um objecto como { agua: 3, calor: 1, azoto: 1, pragas: 1, raiz: 1 }.
 */
export function melhores(lugar, culturas, culturaAnterior, pesos, quantas = 5) {
  const { avaliadas, discrimina } = avaliarTodas(lugar, culturas, culturaAnterior);

  const somaPesos = INDICADORES.reduce((s, k) => s + (pesos[k] || 0), 0) || 1;
  for (const a of avaliadas) {
    a.total =
      INDICADORES.reduce((s, k) => s + a.notas[k] * (pesos[k] || 0), 0) / somaPesos;
  }

  avaliadas.sort((x, y) => y.total - x.total);

  // Diversidade: nao mostrar duas rotacoes com o mesmo conjunto de culturas.
  // Sem isto as melhores saem quase iguais, e o agricultor nao aprende nada
  // ao olhar para a segunda. O objectivo da lista e mostrar alternativas com
  // compromissos diferentes, nao variacoes da mesma.
  const vistas = new Set();
  const escolhidas = [];
  for (const a of avaliadas) {
    const assinatura = a.culturas
      .map((c) => c.id)
      .sort()
      .join("|");
    if (vistas.has(assinatura)) continue;
    vistas.add(assinatura);
    escolhidas.push(a);
    if (escolhidas.length === quantas) break;
  }

  const resultados = escolhidas.map((a) => ({
    sequencia: a.culturas.map((c) => c.nome),
    culturas: a.culturas,
    total: a.total,
    notas: { ...a.notas },
    deficitAguaMm: -a.brutos.agua,
    saldoAzoto: a.brutos.azoto,
  }));

  return { resultados, discrimina };
}

/* ------------------------------------------------------------------ *
 * Ajuda para o browser
 * ------------------------------------------------------------------ */

/**
 * Carrega os dois ficheiros e devolve { lugares, culturas, porId }.
 * lugares vem indexado por nome, para a interface poder escolher.
 */
export async function carregar(caminhoClima = "clima.json", caminhoCulturas = "culturas.json") {
  const [clima, culturasRaw] = await Promise.all([
    fetch(caminhoClima).then((r) => r.json()),
    fetch(caminhoCulturas).then((r) => r.json()),
  ]);

  const culturas = culturasRaw.culturas;
  const lugares = {};
  for (const l of clima.lugares) lugares[l.nome] = l;
  const porId = {};
  for (const c of culturas) porId[c.id] = c;

  return { lugares, culturas, porId, fontes: culturasRaw._fontes };
}
