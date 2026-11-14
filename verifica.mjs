import { readFileSync } from "node:fs";
import { melhores } from "./motor.js";

const clima = JSON.parse(readFileSync("clima.json", "utf8"));
const culturas = JSON.parse(readFileSync("culturas.json", "utf8")).culturas;
const porId = Object.fromEntries(culturas.map((c) => [c.id, c]));
const anterior = porId["milho"];

const PERFIS = {
  "equilibrado":     { agua: 1, calor: 1, azoto: 1, pragas: 1, raiz: 1 },
  "poupar agua":     { agua: 3, calor: 1, azoto: 1, pragas: 1, raiz: 1 },
  "recuperar solo":  { agua: 1, calor: 1, azoto: 3, pragas: 2, raiz: 2 },
};

const saida = [];
for (const lugar of clima.lugares) {
  for (const [perfil, pesos] of Object.entries(PERFIS)) {
    const { resultados } = melhores(lugar, culturas, anterior, pesos);
    for (const r of resultados) {
      saida.push([lugar.nome, perfil, r.sequencia.join(" > "), r.total.toFixed(3),
                  r.deficitAguaMm.toFixed(1), r.saldoAzoto].join(" | "));
    }
  }
}
console.log(saida.join("\n"));
