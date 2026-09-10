
# Magickal Union — Handoff Histórico e Arquitetural

> Documento de memória arquitetural para futura reconciliação contra o polyrepo real do ForexSystem.
>
> **Fonte primária:** conversa `Pesquisa aprofundada Base44` (`6aa08897-229c-83e9-a6eb-4ce93bbb1eb7`), ocorrida entre 2026-09-08 e 2026-09-10 (America/Sao_Paulo), incluindo o arquivo anexado `magickal_union.md`.
>
> **Regra de leitura:** os estados abaixo registram o que foi decidido, proposto, substituído, rejeitado ou deixado em aberto na conversa. Eles **não certificam implementação**. Toda alegação sobre o estado atual do código permanece não verificada até a fase forense no polyrepo.

---

## 1. Objetivo e escopo deste handoff

Este documento preserva a evolução da ideia denominada **Magickal Union**: a integração entre a Central de Inteligência Fundamental e a Central de Análise Técnica e Operações do ForexSystem.

Ele deve permitir que um Work com acesso ao polyrepo:

1. reconstrua o estado atual a partir de `AGENTS.md`, documentação, contratos, schemas, código, testes e configuração de runtime;
2. diferencie visão normativa de alegações históricas de implementação;
3. encontre equivalentes já existentes antes de sugerir componentes novos;
4. produza análise de gaps e arquitetura de migração;
5. derive, somente depois da investigação, o futuro `magickal_union_architecture.md`.

Este handoff **não** é a arquitetura final e **não** autoriza implementação automática.

### 1.1 Estados usados

| Estado         | Significado neste documento                                                                        |
| -------------- | -------------------------------------------------------------------------------------------------- |
| `DECIDED`    | Houve escolha ou concordância explícita na conversa. Ainda pode exigir verificação no código. |
| `PROPOSED`   | Direção ou desenho recomendado, mas não confirmado como decisão final ou implementação.      |
| `SUPERSEDED` | Formulação anterior substituída por outra mais precisa.                                         |
| `REJECTED`   | Alternativa explicitamente descartada ou considerada inadequada.                                   |
| `OPEN`       | Questão pendente, dependente de evidência, escolha ou validação futura.                        |

### 1.2 Integridade e limites das fontes

- A conversa foi recuperada pelo identificador original e comparada com o preview fornecido no pedido atual.
- O `magickal_union.md` original anexado foi lido integralmente. Ele é uma fonte histórica da intenção do autor, não prova independente do estado do polyrepo.
- Uma resposta arquitetural muito extensa da conversa foi disponibilizada com um trecho intermediário truncado pela interface de recuperação. Os conceitos preservados neste documento foram corroborados pelo começo e fim visíveis dessa resposta, pela síntese explícita da versão 2 e pelas decisões posteriores. Nenhuma lacuna foi preenchida como fato de implementação.
- A conversa mencionou a criação de `magickal_union_v2.md`, mas esse arquivo não está presente no workspace atual. Sua existência, conteúdo integral e localização devem ser confirmados.
- Duas imagens históricas estavam anexadas à conversa; elas sustentavam a metáfora dos alfabetos mágicos, mas não constituem especificação técnica.

---

## 2. Sumário executivo

- **`DECIDED` — Um sistema, não dois.** Inteligência Fundamental e Análise Técnica/Operações são sistemas cognitivos complementares de um único organismo decisório.
- **`DECIDED` — Tese central.** A Inteligência Fundamental representa dinamicamente o estado do mundo; a Análise Técnica observa como os preços reagem a esse estado.
- **`DECIDED` — O elo central é causal e temporal.** A união não pode ser apenas envio de tags ou texto entre serviços. Precisa traduzir eventos do mundo em hipóteses específicas por mercado/ativo e confrontá-las com reação real do preço.
- **`DECIDED` — `Global Pulse != BLUF`.** O Global Pulse é estado estruturado, temporal e rastreável. BLUF é uma projeção narrativa derivada desse estado, não a memória canônica.
- **`DECIDED` — Respiração bidirecional.** Fundamental influencia interpretação, tolerância, confiança e sizing dentro de limites; a resposta técnica confirma, contradiz ou recalibra a hipótese fundamental.
- **`DECIDED` — Segurança soberana.** `LOCK_DOWN` deve ser tratado como política dura e constitucional. Nenhum LLM, Oracle, Pulse ou fundamento pode anulá-lo.
- **`DECIDED` — Separação documental.** `magickal_union_v2.md` é a especificação conceitual/ontológica; `magickal_union_architecture.md` será a manifestação técnica reconciliada com o código.
- **`DECIDED` — Investigação antes de desenho.** O futuro Work deve executar descoberta forense cross-repo antes de propor criação, renome ou migração de componente.
- **`DECIDED` — Workspace canônico.** `ForexSystemLocal` foi escolhido como fonte canônica para arquitetura e código; `ForexSystemCloud` não deve evoluir como segunda verdade concorrente.
- **`PROPOSED` — Topologia Base44.** Base44 pode atuar como produto/UI/auth, com Python contínuo fora da plataforma e Supabase/Postgres como data plane. Essa proposta nasceu antes da reconciliação com o ForexSystem real e não deve ser tomada como target state sem auditoria.

---

## 3. Cronologia da evolução

### Fase 1 — Pesquisa de Base44 e fronteiras de runtime

#### H-001 — Necessidade original de plataforma

**Estado: `OPEN`**

O pedido inicial investigou se Base44 poderia sustentar:

- REST API;
- conexão a banco existente;
- jobs Python em background e conectados à internet;
- ML em Python;
- consumo de Massive.com e GDELT;
- scraping de sites públicos como Forex Factory;
- listener Telegram/Telethon em tempo real;
- fontes de OHLC e notícias;
- plugins/conectores, incluindo Hugging Face;
- datasource e conector externo próprio.

Não houve, nessa etapa, decisão final de adotar Base44. A necessidade subjacente era descobrir a fronteira entre uma camada de produto low-code/AI e workloads contínuos de dados, NLP/ML e OSINT.

#### H-002 — Base44 não como host do daemon Python

**Estado: `PROPOSED`**

Foi estabelecida como orientação arquitetural a separação:

```text
Base44                         Runtime Python externo
UI / auth / app / HTTP   <->   collectors / workers / ML / WebSocket / scraping
```

Racional registrado:

- funções backend da Base44 foram tratadas como serverless Deno/TypeScript e adequadas a HTTP, webhook, polling curto e orquestração;
- processos como Telethon `run_until_disconnected`, WebSocket persistente, consumidor de fila e modelo ML residente exigem serviço long-running;
- um worker não precisa expor endpoint público; uma API web e um worker contínuo são papéis operacionais diferentes.

**Dependência:** revalidar capacidades, limites, preços e conectores atuais da Base44 antes de qualquer adoção, pois são dados temporais da plataforma.

#### H-003 — Supabase como data plane e Python em serviço externo

**Estado: `PROPOSED`**

Topologia recomendada para um MVP isolado:

```text
Fontes externas
  -> Python workers (Railway/Render/Fly/ECS/VM etc.)
  -> Supabase/PostgreSQL
  -> FastAPI e/ou Data API
  -> Base44
```

Responsabilidades sugeridas:

- Base44: produto, UI, autenticação e lógica leve;
- runtime externo: FastAPI, Telethon, Massive WebSocket, GDELT, scraping, NLP/ML;
- Supabase: PostgreSQL, API de dados, realtime e storage;
- Redis/fila: opcional para desacoplar collectors, normalização e workers especializados.

Railway e Render foram apontados como opções simples; Fly.io, ECS/Fargate, EC2, Compute Engine e Azure Container Apps/VM como alternativas. Cloud Run foi considerado bom para HTTP, inferência sob demanda e jobs, mas menos natural para conexões eternas.

**Importante:** isso foi uma arquitetura exploratória de hospedagem. A conversa posterior mudou o foco para o polyrepo ForexSystem já existente. Portanto, essa topologia não pode ser promovida automaticamente a arquitetura alvo.

### Fase 2 — O documento `magickal_union.md` torna o problema ontológico

#### H-004 — `Cruzamento Semântico`

**Estado: `DECIDED`**

O documento original introduziu o **Cruzamento Semântico**: linguagem abstrata, simbólica ou mística deve ser traduzida para correlações de sistema, arquitetura e código sem perder a intenção que ela comunica.

O mecanismo não é decorativo. Ele orienta a transformação:

```text
metáfora / intenção
  -> conceito semântico
  -> responsabilidade sistêmica
  -> componente
  -> contrato
  -> estado
  -> evento/MQ
  -> algoritmo/regra
  -> teste
```

#### H-005 — Duas dimensões passam a ser entendidas como um organismo

**Estado: `SUPERSEDED`** para a ideia de “dois sistemas integrados”
**Estado: `DECIDED`** para “um sistema com dimensões cognitivas complementares”

Formulação anterior:

```text
Central de Inteligência Fundamental <-> Central de Análise Técnica e Operações
```

Formulação adotada:

```text
                         MARKET INTELLIGENCE SYSTEM
                                    |
                 +------------------+------------------+
                 |                                     |
       WORLD / FUNDAMENTAL                    MARKET / TECHNICAL
          INTELLIGENCE                           INTELLIGENCE
                 |                                     |
                 +------------------+------------------+
                                    |
                         OPERATIONAL DECISION
```

A frase-tese foi adotada como centro da visão:

> A Inteligência Fundamental funciona como uma representação dinâmica do estado do mundo, enquanto a Análise Técnica observa como os preços do mercado estão reagindo a esse estado.

### Fase 3 — Refinamento do Global Pulse e do elo causal

#### H-006 — Separação entre evidência, estado e apresentação

**Estado: `DECIDED`**

A formulação original aproximava `Global Pulse` do BLUF produzido recursivamente pelo Strategist. A conversa refinou isso:

```text
Evidência canônica          Estado estruturado           Projeção humana/agente
Event Store / facts   ->    Global Pulse State      ->   BLUF
```

- **Event Store/evidência:** eventos e mensagens rastreáveis, com fonte, tempo e atributos.
- **Global Pulse:** estado vivo e estruturado, por entidade, país, moeda, tema, risco, hipótese ou dimensão equivalente a validar.
- **BLUF:** resumo derivado e regenerável, adequado a consumo humano/agente.

Foi descartada a ideia de usar uma narrativa resumida como única memória recursiva do mundo, por risco de compressão cumulativa, perda de proveniência, deriva semântica e amplificação de erro de LLM.

#### H-007 — Temporalidade real do Pulse

**Estado: `DECIDED` no conceito; `OPEN` no modelo matemático**

O Global Pulse deve incorporar:

- decaimento;
- reforço por novas evidências;
- contradição;
- validade temporal;
- confiança;
- rastreabilidade até as evidências.

O Pulse não pode ser apenas “último resumo + novas mensagens”. A função de atualização, pesos, janelas, meia-vida, tratamento de fonte e propagação entre entidades/ativos continuam abertos.

#### H-008 — `DANGER_SCORE` não equivale a relevância de mercado

**Estado: `DECIDED`**

O `DANGER_SCORE` histórico mede perigo/criticidade no pipeline NLP. Ele não deve ser usado como sinônimo de:

- relevância financeira;
- impacto esperado;
- direção por ativo;
- magnitude;
- duração;
- confiança de mercado.

Exemplo semântico: um evento pode ser perigoso e pouco relevante para um par cambial específico; outro pode ser pouco “perigoso” e altamente material para juros, moeda ou commodity.

#### H-009 — Terceira dimensão: Market Translation / Causal / Impact Layer

**Estado: `DECIDED` como capacidade arquitetural; `OPEN` quanto à materialização em serviços**

A divisão em Fundamental e Técnico foi refinada para três capacidades:

1. **World Intelligence** — o que está acontecendo?
2. **Market Translation / Causal Layer** — o que isso significa para cada mercado e ativo?
3. **Execution Intelligence** — o mercado confirma, e quando é operável agir?

Modelo semântico mínimo:

```text
evento
  -> mecanismo causal
  -> ativo/mercado afetado
  -> direção esperada
  -> magnitude esperada
  -> horizonte/duração
  -> confiança
  -> condições de invalidação
```

Essa camada foi identificada como o principal gap conceitual. Não foi decidido se será um novo serviço, uma capacidade distribuída ou evolução de componentes existentes.

### Fase 4 — União bidirecional e decisão probabilística

#### H-010 — Fundamental como prior; Técnico como evidence; decisão como posterior

**Estado: `DECIDED` como modelo conceitual; `OPEN` quanto à implementação estatística**

Formulação adotada:

```text
Fundamental = prior
Technical   = evidence
Decision    = posterior
```

Objetivo:

```text
P(sucesso ou movimento persistente | contexto técnico, contexto fundamental)
```

em vez de considerar apenas:

```text
P(sucesso | contexto técnico)
```

Isso não significa que uma inferência Bayesiana formal já exista ou tenha sido escolhida. O modelo serve como restrição de desenho: o fundamento condiciona a leitura, e a reação observada atualiza a crença.

#### H-011 — Respiração bidirecional Fundamental ⇄ Técnico

**Estado: `DECIDED`**

Fluxo adotado:

```text
World evidence
  -> Global Pulse / market hypothesis
  -> expected market reaction
  -> technical observation / Fire Triangle
  -> confirmation, contradiction or delay
  -> update confidence/context/model
  -> operational decision under risk policy
```

Consequências:

- Fundamental pode modular confiança, histerese, tolerância a pullback e sizing dentro de limites;
- Técnico não é mero executor do Fundamental: ele mede a reação real do mercado;
- divergência entre reação esperada e observada deve produzir informação de volta ao sistema;
- a ausência de confirmação também é evidência;
- a arquitetura precisa correlacionar hipótese, reação, setup e resultado.

#### H-012 — Fire Triangle como sensor/gate, não ordem isolada

**Estado: `DECIDED` no papel conceitual; `OPEN` na integração concreta**

O Fire Triangle foi reposicionado como sensor da reação geométrica/técnica do mercado e possível mecanismo de confirmação operacional.

Foi rejeitada a equivalência simplista:

```text
FireTriangle == true -> BUY
```

O evento técnico deve ser interpretado sob contexto, risco, hipótese causal e regras de execução.

#### H-013 — Memória empírica mundo → mercado → resultado

**Estado: `PROPOSED`**

Foi proposto formar corpus histórico próprio:

```text
evento
  -> reação esperada
  -> reação observada
  -> setup técnico
  -> decisão
  -> resultado
```

Dimensões sugeridas incluem tipo de evento, contexto anterior, ativo, regime, padrão técnico e distribuição futura de retornos. A finalidade é permitir calibração e aprendizado das relações entre estado do mundo e comportamento de mercado.

### Fase 5 — Segurança e autoridade

#### H-014 — `LOCK_DOWN` deixa de ser só mensagem de controle

**Estado: `SUPERSEDED`** para o entendimento puramente operacional
**Estado: `DECIDED`** para a formulação constitucional

No documento original, `LOCK_DOWN` aparece como mensagem de controle emitida quando o RiskManager detecta risco na conta, rejeitando ordens até desativação.

Na visão refinada, ele se torna **HARD SAFETY POLICY**:

- soberana sobre Global Pulse, IA Oracle, Strategist, LLMs, estratégias e contexto fundamental;
- impossível de ser anulada por narrativa “o fundamento continua bullish/bearish”;
- responsável por hard stops e condições catastróficas;
- separada de mecanismos de saída/tolerância suaves.

Divisão adotada:

```text
SOFT EXIT / SOFT CONSTRAINT
  pode ser influenciado por contexto fundamental, dentro de limites

HARD RISK EXIT / LOCK_DOWN
  não pode ser desabilitado pelo contexto fundamental
```

Critérios exatos, autoridade de ativação/desativação, persistência, idempotência, auditoria e fail-safe permanecem abertos.

### Fase 6 — Versionamento dos documentos

#### H-015 — Preservar o original e criar `magickal_union_v2.md`

**Estado: `DECIDED`**

O `magickal_union.md` original deve permanecer como **semente ontológica/histórica**. A orientação foi não apagar sua linguagem mágica nem convertê-lo em documento corporativo convencional.

A versão 2 deveria:

- preservar Cruzamento Semântico, Alfabeto Celestial, conexão, elevação consciencial e transformação do Trader;
- incorporar `Global Pulse != BLUF`;
- separar evidência, estado e apresentação;
- adicionar decaimento, reforço, contradição e temporalidade;
- separar `DANGER_SCORE` de impacto de mercado;
- introduzir `World State -> Market Causal/Impact -> Expected Reaction`;
- formalizar a respiração bidirecional;
- reposicionar Fire Triangle;
- registrar o modelo prior/evidence/posterior;
- tornar `LOCK_DOWN` uma política soberana de segurança.

**Estado do artefato: `OPEN`.** A conversa afirmou que a v2 foi criada, porém ela não foi localizada no workspace atual e precisa ser recuperada ou regenerada a partir das fontes.

#### H-016 — Separar ontologia de arquitetura técnica

**Estado: `DECIDED`**

Papéis documentais:

```text
magickal_union_v2.md
  = o que a união é, por que existe e quais princípios preserva

magickal_union_architecture.md
  = como a união existe no sistema real
```

O futuro documento de arquitetura deve fazer a passagem:

```text
conceito -> componente -> contrato -> estado -> MQ -> algoritmo -> regra -> teste
```

Foi rejeitado produzir imediatamente um `magickal_union_architecture.md` especulativo sem inspeção do polyrepo.

### Fase 7 — Organização do trabalho e fonte de verdade

#### H-017 — `ForexSystemLocal` como workspace canônico

**Estado: `DECIDED`**

Foi decidido mover a trilha conceitual para o projeto local e evitar a evolução concorrente em múltiplos contextos.

Responsabilidades adotadas:

```text
ForexSystemLocal
  = source of truth de código, specs, investigação e arquitetura

ForexSystemCloud
  = espelho, publicação ou artefatos consolidados; não uma segunda verdade
```

Risco que a decisão busca mitigar: **context split-brain** entre arquitetura local, arquitetura cloud, chat fora do projeto, implementação Codex e memória Work.

**Verificação pendente:** confirmar no ambiente real quais projetos, repos e sincronizações existem e se `ForexSystemCloud` já contém mudanças não presentes localmente.

#### H-018 — Chat, Work e Codex com papéis distintos

**Estado: `DECIDED`**

- Chat conceitual: visão, semântica, decisões e memória da Magickal Union.
- Work: descoberta cross-repo, reconstrução do estado atual, gap analysis e documento final.
- Codex: inspeção de código, refactors, implementação por fases, testes e validação executável.

O chat não deve virar a sessão operacional de leitura de centenas de arquivos; a continuidade conceitual deve ser preservada enquanto o Work conduz a investigação pesada.

#### H-019 — Fase forense antes de qualquer target architecture

**Estado: `DECIDED`**

Ordem de precedência proposta e aceita:

1. `AGENTS.md` e instruções de cada repo;
2. `magickal_union_v2.md` como visão normativa;
3. specs arquiteturais atuais;
4. contratos, interfaces e schemas;
5. código implementado;
6. testes;
7. runtime e deployment config.

Distinção obrigatória:

```text
Magickal Union says WHAT WE WANT TO BE.
Code says WHAT WE ARE.
Architecture explains HOW WE GET FROM ONE TO THE OTHER.
```

Regra severa adotada:

> Não propor a criação de um componente antes de procurar no código implementações equivalentes, parcialmente equivalentes, depreciadas, planejadas ou existentes sob outro nome.

---

## 4. Registro consolidado de decisões arquiteturais

| ID      | Estado       | Decisão / proposta                                                                           | Racional                                                              | Evidência futura necessária                                                             |
| ------- | ------------ | --------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| ADR-H01 | `DECIDED`  | Tratar o ForexSystem como um organismo decisório único.                                     | Evita integração rasa entre silos Fundamental e Técnico.           | Mapear bounded contexts e fluxos reais.                                                   |
| ADR-H02 | `DECIDED`  | Inteligência Fundamental representa estado do mundo; Técnica observa a reação do mercado. | Separa explicação/hipótese de confirmação observável.           | Localizar modelos de contexto e sinais existentes.                                        |
| ADR-H03 | `DECIDED`  | `Global Pulse != BLUF`.                                                                     | Evita transformar resumo textual em estado canônico.                 | Auditar persistência do Strategist/BLUF.                                                 |
| ADR-H04 | `DECIDED`  | Preservar evidência bruta/rastreável e derivar estado e narrativa.                          | Proveniência, reprocessamento e redução de deriva.                 | Localizar event stores, tabelas, filas e retenção.                                      |
| ADR-H05 | `DECIDED`  | O Pulse precisa de dinâmica temporal e contradição.                                        | Estado mundial não é uma sequência de snapshots independentes.     | Identificar timestamps, TTLs, weights e state reducers.                                   |
| ADR-H06 | `DECIDED`  | Separar perigo de impacto/relevância de mercado.                                             | Criticidade social/geopolítica não implica materialidade por ativo. | Auditar schema e consumidores de`DANGER_SCORE`.                                         |
| ADR-H07 | `DECIDED`  | Existência lógica de uma Market Translation/Causal Layer.                                   | Falta traduzir evento em hipótese específica por ativo.             | Determinar se capacidade já está distribuída em Oracle/Strategist/SignalGenerator etc. |
| ADR-H08 | `DECIDED`  | Integração bidirecional Fundamental ⇄ Técnico.                                            | Reação real confirma ou invalida hipótese do mundo.                | Localizar contratos de feedback e correlação.                                           |
| ADR-H09 | `DECIDED`  | Fire Triangle funciona como sensor/confirmação, não gatilho autossuficiente.               | Impede decisão sem contexto e risco.                                 | Inspecionar implementação, outputs e consumidores.                                      |
| ADR-H10 | `DECIDED`  | Fundamental pode modular parâmetros suaves, nunca segurança dura.                           | Evita racionalização de perdas contra risco catastrófico.          | Auditar RiskManager, Executor e controles MQ.                                             |
| ADR-H11 | `DECIDED`  | `LOCK_DOWN` é política soberana.                                                          | Segurança deve dominar todos os componentes cognitivos.              | Verificar autoridade, persistência, recuperação e testes.                              |
| ADR-H12 | `PROPOSED` | Construir memória empírica evento–hipótese–reação–setup–resultado.                   | Permite calibração e aprendizado causal/condicional.                | Verificar telemetry, IDs de correlação e outcome store.                                 |
| ADR-H13 | `DECIDED`  | Preservar documento ontológico separado da arquitetura técnica.                             | Evita perder intenção ou congelar design especulativo.              | Recuperar v2 e definir ownership/versionamento.                                           |
| ADR-H14 | `DECIDED`  | Executar descoberta forense antes de criação/refactor.                                      | Evita duplicação e conflito com o polyrepo real.                    | Inventário completo e matriz de equivalência.                                           |
| ADR-H15 | `DECIDED`  | `ForexSystemLocal` é fonte canônica; cloud é derivação.                                | Evita split-brain de contexto e arquitetura.                          | Reconciliar divergências Local/Cloud.                                                    |
| ADR-H16 | `PROPOSED` | Base44 + runtime Python externo + Supabase como possível topologia de produto.               | Separa UI low-code de workloads contínuos.                           | Reavaliar fit contra arquitetura existente e requisitos atuais.                           |

---

## 5. Conceitos semânticos e sua tradução arquitetural

| Conceito                          | Estado                                                             | Significado semântico                                                         | Tradução arquitetural esperada                                                   | Não significa                                         |
| --------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------- | ------------------------------------------------------ |
| Magickal Union / Grande União    | `DECIDED`                                                        | Harmonia entre inteligência do mundo e inteligência do mercado.              | Um ciclo decisório único, com estado, causalidade, feedback, risco e execução. | Apenas conectar duas APIs ou publicar tags.            |
| Cruzamento Semântico             | `DECIDED`                                                        | Traduzir linguagem abstrata sem destruir sua intenção.                       | Rastrear conceito até responsabilidade, contrato, estado, regra e teste.          | Implementar metáforas literalmente.                   |
| Global Pulse                      | `DECIDED`                                                        | Representação viva do estado do mundo e de hipóteses relevantes.            | Estado estruturado, temporal, contraditável, reforçável e rastreável.          | Um BLUF textual ou o último resumo disponível.       |
| BLUF                              | `DECIDED`                                                        | Visão compacta “Bottom Line Up Front”.                                      | Read model/projeção derivada para humanos e agentes.                             | Fonte de verdade ou memória canônica recursiva.      |
| World Intelligence                | `DECIDED`                                                        | Detecta e interpreta o que acontece no mundo.                                  | Collectors, tradução, deduplicação, NLP, entidades, evidências, Oracle.       | Sinal de trading pronto.                               |
| Market Translation / Causal Layer | `DECIDED`/`OPEN`                                               | Converte estado do mundo em hipótese por mercado/ativo.                       | Mecanismo, direção, magnitude, duração, confiança e invalidação.            | Necessariamente um microserviço novo.                 |
| Expected Reaction                 | `DECIDED`                                                        | Comportamento de mercado previsto sob uma hipótese.                           | Contrato correlacionável com observação técnica posterior.                     | Garantia de movimento ou autorização de trade.       |
| Technical Reaction                | `DECIDED`                                                        | Resposta real do preço/fluxo ao contexto.                                     | Evidência de confirmação, contradição, atraso ou regime diferente.            | Apenas confirmação obediente do Fundamental.         |
| Fire Triangle                     | `DECIDED`/`OPEN`                                               | Sensor geométrico/técnico de operabilidade.                                  | Feature/sinal contextualizado por hipótese e risco.                               | Regra`true -> BUY`.                                  |
| `DANGER_SCORE`                  | `DECIDED`                                                        | Criticidade/perigo de evento no pipeline histórico.                           | Feature de triagem/escalação ao Oracle, conforme contrato real a auditar.        | Score de impacto financeiro completo.                  |
| `LOCK_DOWN`                     | `DECIDED`                                                        | Limite constitucional de segurança.                                           | Política dura, soberana, auditável e fail-safe.                                  | Preferência estratégica ajustável por LLM.          |
| “Respirar juntos”               | `DECIDED`                                                        | Comunicação de mão dupla e atualização mútua.                            | Loop hipótese → observação → feedback → recalibração.                      | Fluxo unidirecional Fundamental → Técnico.           |
| Elevação consciencial do Trader | `DECIDED` como metáfora                                         | Decidir com contexto superior ao preço isolado.                               | Interfaces explicáveis que ligam evidência, hipótese, reação e risco.         | Autoridade irrestrita do usuário ou da IA.            |
| Alfabeto Celestial                | `DECIDED` como metáfora; `SUPERSEDED` na precisão histórica | Preço sem contexto é um texto cujos símbolos não bastam para compreensão. | Necessidade de modelo interpretativo e contexto.                                   | Sinônimo histórico estrito de Malachim ou Enoqueano. |

### 5.1 Correção semântica registrada

Foi recomendado não tratar **Alfabeto Celestial**, **Malachim** e **Enoqueano/Angelical** como sinônimos históricos estritos. A correção não altera a função arquitetural da metáfora: conhecer símbolos não equivale a possuir o modelo que os interpreta.

---

## 6. Arquitetura alvo pretendida — visão, não implementação confirmada

### 6.1 Loop cognitivo alvo

```text
DATA SOURCES / WORLD EVENTS / OSINT
              |
              v
COLLECTION -> DEDUP -> TRANSLATION -> NLP / ENTITY / SENTIMENT
              |                         |
              |                         +-> DANGER / TRIAGE -> IA ORACLE
              v
IMMUTABLE OR TRACEABLE EVIDENCE
              |
              v
GLOBAL PULSE STRUCTURED STATE
  decay | reinforcement | contradiction | confidence | provenance
              |
              +-----------------> BLUF / dashboards / agent views
              |
              v
MARKET TRANSLATION / CAUSAL IMPACT
  event -> mechanism -> asset -> direction -> magnitude -> horizon
              |
              v
EXPECTED REACTION / MARKET HYPOTHESIS
              |
              v
TECHNICAL OBSERVATION / FIRE TRIANGLE / REGIME / FLOW
              |
              +-> confirm / contradict / delayed / no reaction
              |                         |
              |                         +---- feedback to Pulse/model
              v
STRATEGY / SESSION / SIGNAL / SIZING
              |
              v
RISK MANAGER -- HARD SAFETY / LOCK_DOWN
              |
              v
EXECUTION / EXIT / OUTCOME
              |
              +---- empirical memory and calibration
```

### 6.2 Planos lógicos

#### Evidence plane

**Estado: `DECIDED` como responsabilidade; `OPEN` em tecnologia e ownership**

- preserva fontes e eventos;
- registra tempo, origem, versão de processamento e proveniência;
- suporta reprocessamento e auditoria;
- não depende exclusivamente de texto gerado por LLM.

#### State plane

**Estado: `DECIDED` como responsabilidade; `OPEN` em schema**

- representa o Global Pulse estruturado;
- resolve reforço, decaimento, contradição e confiança;
- deve permitir visões por entidade, país, moeda, tema, ativo e hipótese, se confirmadas no domínio real.

#### Narrative/read-model plane

**Estado: `DECIDED`**

- BLUF, dashboards, alertas e explicações são projeções;
- podem ser regenerados a partir de evidência e estado;
- não devem dominar a verdade histórica.

#### Causal/market translation plane

**Estado: `DECIDED` como capacidade; `OPEN` em boundaries**

- liga evento mundial a mecanismo econômico/financeiro;
- produz impacto/hipótese por ativo;
- define reação esperada e condições de invalidação;
- evita usar `DANGER_SCORE` como atalho semântico.

#### Technical/execution plane

**Estado: `DECIDED` na interação; `OPEN` nos contratos**

- observa regimes, fluxo, geometria, setup e timing;
- confronta reação esperada e observada;
- fornece feedback ao contexto;
- envia decisão ao risco e à execução, nunca contornando hard safety.

#### Safety plane

**Estado: `DECIDED` no princípio; `OPEN` nos mecanismos**

- RiskManager e `LOCK_DOWN` possuem precedência;
- nenhuma camada cognitiva pode desativar hard exits;
- ações e transições precisam ser auditáveis e testáveis.

### 6.3 Estados conceituais mínimos de uma hipótese

**Estado: `PROPOSED`**

Sem impor schema ou nomes de classes, a arquitetura futura deverá avaliar a necessidade de representar:

- identidade da hipótese;
- evidências de suporte e contradição;
- entidades, países, moedas, mercados e ativos envolvidos;
- mecanismo causal;
- direção, magnitude, horizonte e confiança esperados;
- reação esperada;
- reação observada;
- regime técnico;
- condições de validação/invalidação;
- validade temporal/decay;
- decisão, sizing e limites de risco aplicados;
- outcome e aprendizado posterior;
- correlation/causation IDs para rastreio entre serviços.

---

## 7. Componentes e repositórios afetados

As listas abaixo vêm do `magickal_union.md` anexado e da conversa. A existência e o nome exato de cada caminho devem ser verificados.

### 7.1 Central de Inteligência Fundamental

| Caminho/nome histórico                                  | Papel alegado                           | Impacto da Magickal Union                                             | Estado de implementação |
| -------------------------------------------------------- | --------------------------------------- | --------------------------------------------------------------------- | ------------------------- |
| `services/collector_events`                            | Coleta de eventos                       | Proveniência, IDs e publicação de evidência.                      | **Não verificado** |
| `services/collector_events/translation`                | Tradução para inglês                 | Preservar origem, texto original e versão traduzida.                 | **Não verificado** |
| `services/collector_events/globalintel` / Orchestrator | Orquestração de extratores            | Descobrir ownership do pipeline e do Global Pulse.                    | **Não verificado** |
| `services/osint_engine`                                | Fontes OSINT                            | Normalização, confiabilidade e ingestão temporal.                  | **Não verificado** |
| `services/nlp`                                         | Sentimento, entidades e`DANGER_SCORE` | Separar criticidade de relevância/impacto de mercado.                | **Não verificado** |
| `services/ia_oracle`                                   | Resumo, consolidação e arbitragem LLM | Limitar autoridade; preservar evidência; expor decisão rastreável. | **Não verificado** |
| `STRATEGIST`                                           | Global Pulse e BLUF                     | Separar state reducer de gerador narrativo.                           | **Não verificado** |

### 7.2 Análise Técnica e Operações

| Caminho/nome histórico        | Papel alegado           | Impacto da Magickal Union                                        | Estado de implementação |
| ------------------------------ | ----------------------- | ---------------------------------------------------------------- | ------------------------- |
| `services/collector_history` | Histórico OHLC         | Correlacionar mercado observado com hipóteses/eventos.          | **Não verificado** |
| `services/session_manager`   | Sessões                | Contextualizar regimes e validade temporal.                      | **Não verificado** |
| `services/indicator_engine`  | Indicadores             | Produzir features observáveis, não decisão isolada.           | **Não verificado** |
| `services/signal_generator`  | Sinais                  | Consumir contexto causal/técnico e emitir decisão rastreável. | **Não verificado** |
| `services/geo_vision`        | Análise geométrica    | Verificar relação com Fire Triangle e confirmação.           | **Não verificado** |
| `services/trading_session`   | Estado operacional      | Propagar contexto, decisão, risco e lifecycle.                  | **Não verificado** |
| `services/executor_trading`  | Execução/encerramento | Respeitar`LOCK_DOWN` e contratos idempotentes.                 | **Não verificado** |
| `services/risk_manager`      | Risco da conta          | Autoridade soberana, hard exits e auditoria.                     | **Não verificado** |
| Fire Triangle                  | Motor/setup técnico    | Sensor de reação e gate contextual.                            | **Não verificado** |

### 7.3 Infraestrutura e contratos transversais

| Elemento                                          | Alegação histórica                                                 | Questão de reconciliação                                                       |
| ------------------------------------------------- | --------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| RabbitMQ / mensagens MQ                           | Fluxos principais, alertas e controle usam MQ.                        | Exchanges, queues, routing keys, schemas, DLQ, retries, ordering e idempotência. |
| `BUY_ENTRY` / `SELL_ENTRY`                    | Exemplos de alertas globais.                                          | São alertas, comandos ou eventos? Quem tem autoridade?                           |
| `LOCK_DOWN`                                     | Mensagem de controle do RiskManager.                                  | Modelar como estado/policy durável, não só evento efêmero.                    |
| Qwen-Instruct 4B quantizado                       | Modelo usado por restrições de custo, segundo o documento original. | Verificar provider, versão, runtime e se ainda é atual.                         |
| Abstract Provider → Factory → Concrete Provider | Padrão alegado para múltiplos LLMs.                                 | Localizar interfaces, providers reais e cobertura de testes.                      |
| Machine Learning                                  | Marcado no original como ainda não iniciado.                         | Não assumir que continua não iniciado. Verificar código atual.                 |
| Backtesting                                       | Alegado como parcial e pouco testado.                                 | Localizar implementação, datasets, reprodutibilidade e métricas.               |

### 7.4 Plataformas exploratórias externas

| Plataforma                                  | Papel discutido                          | Estado                                                          |
| ------------------------------------------- | ---------------------------------------- | --------------------------------------------------------------- |
| Base44                                      | UI/app/auth/orquestração leve          | `PROPOSED`, não reconciliado                                 |
| Supabase/PostgreSQL                         | Data plane/API/realtime/storage          | `PROPOSED`, não reconciliado                                 |
| Railway/Render/Fly/ECS/VM                   | Hosting de Python long-running           | `PROPOSED`, escolha aberta                                    |
| FastAPI                                     | API para exposição de dados e comandos | `PROPOSED`                                                    |
| Redis/queue                                 | Desacoplamento de collectors/workers     | `PROPOSED`; RabbitMQ já é alegado no sistema                |
| Massive.com, GDELT, Telegram, Forex Factory | Fontes de dados/OSINT/market data        | `OPEN`; verificar licenças, ToS, contratos e implementação |
| FinBERT, GLiNER, Hugging Face               | NLP/ML possíveis                        | `PROPOSED`; nenhuma adoção confirmada                       |

---

## 8. Alternativas descartadas ou substituídas

### A-001 — Continuar a arquitetura fora de um Project

**Estado: `REJECTED`**

Motivo: aumentaria fragmentação entre memória conceitual, código local, cloud e ferramentas.

### A-002 — Manter `ForexSystemLocal` e `ForexSystemCloud` como verdades concorrentes

**Estado: `REJECTED`**

Motivo: risco explícito de context split-brain e versões incompatíveis.

### A-003 — Pedir imediatamente “crie `magickal_union_architecture.md`”

**Estado: `REJECTED`**

Motivo: produziria arquitetura bonita, porém potencialmente inventada e duplicada em relação ao sistema real.

### A-004 — Criar um novo componente para cada conceito novo

**Estado: `REJECTED`**

Motivo: conceitos como Global Pulse State ou Market Causal Layer podem já existir parcialmente sob nomes diferentes ou distribuídos entre serviços.

### A-005 — BLUF como memória canônica recursiva

**Estado: `REJECTED`**

Motivo: perda de evidência, proveniência e detalhes; drift acumulativo e dependência excessiva de geração narrativa.

### A-006 — `DANGER_SCORE` como proxy universal de impacto financeiro

**Estado: `REJECTED`**

Motivo: perigo, relevância, direção, magnitude, duração e confiança são dimensões distintas.

### A-007 — Fluxo apenas Fundamental → Técnico

**Estado: `SUPERSEDED`**

Substituído por loop bidirecional em que a reação observada retroalimenta a hipótese e o contexto.

### A-008 — Fire Triangle como ordem automática isolada

**Estado: `REJECTED`**

Motivo: setup técnico sem hipótese, regime, risco e confirmação contextual é insuficiente.

### A-009 — Fundamento anulando hard risk

**Estado: `REJECTED`**

Motivo: uma narrativa fundamental pode persistir enquanto o preço e a conta entram em condição catastrófica.

### A-010 — Rodar daemon Python 24x7 dentro de Base44

**Estado: `REJECTED` na proposta histórica**

Motivo: incompatibilidade entre execução serverless limitada e processos persistentes como Telethon/WebSocket/consumidor de fila. Deve ser revalidado contra a plataforma atual antes de ser tratado como restrição permanente.

---

## 9. Conflitos, assunções e riscos

### 9.1 Visão normativa versus realidade implementada

**Estado: `OPEN`**

O maior conflito potencial é entre `magickal_union_v2.md` e os contratos já existentes. A reconciliação não deve declarar automaticamente a visão “correta” sobre nomes, boundaries ou protocolos; deve conservar os princípios e adaptar a manifestação ao sistema real.

### 9.2 `Global Pulse`, `BLUF` e Strategist podem estar acoplados

**Estado: `OPEN`**

O original descreve o Strategist resumindo novas mensagens junto do contexto anterior para produzir BLUF e, assim, manter o Pulse. É preciso descobrir se há:

- estado estruturado separado;
- armazenamento apenas narrativo;
- schemas por entidade/país/moeda;
- referências às evidências;
- versionamento e temporalidade;
- consumidores que dependem do formato atual.

### 9.3 Event Store é conceito, não tecnologia escolhida

**Estado: `OPEN`**

“Event Store” foi adotado como responsabilidade de evidência canônica. Não houve decisão sobre EventStoreDB, PostgreSQL, Kafka, RabbitMQ streams, object storage ou outro produto.

### 9.4 Market Causal Layer pode já existir fragmentada

**Estado: `OPEN`**

Ela pode estar parcialmente presente em tags do Oracle, Strategist, GlobalIntel, SignalGenerator, GeoVision ou estratégias. Criar um novo serviço sem mapear equivalências violaria a decisão forense.

### 9.5 Mensagem versus estado durável

**Estado: `OPEN`**

`LOCK_DOWN`, `BUY_ENTRY`, `SELL_ENTRY`, hipóteses e confirmações podem estar modelados como mensagens efêmeras. É preciso classificar cada payload como command, event, alert, policy state ou read model e verificar entrega/replay/idempotência.

### 9.6 Autoridade de IA/LLM

**Estado: `OPEN` nos detalhes; `DECIDED` no limite de segurança**

O Oracle foi descrito como árbitro final em eventos com `DANGER_SCORE >= 0.7` e criador de tags comportamentais. A arquitetura deve esclarecer:

- “árbitro final” de qual decisão;
- quando há fallback sem LLM;
- validação de schema;
- explicabilidade e proveniência;
- proteção contra prompt injection/conteúdo hostil;
- limites de autoridade sobre trading e risco.

### 9.7 Base44/Supabase versus polyrepo existente

**Estado: `OPEN`**

A arquitetura Base44 + Railway + Supabase surgiu como resposta a uma exploração de plataforma. O ForexSystem pode já usar outros bancos, deploys, APIs e filas. Nenhuma migração deve ser proposta sem comparação de requisitos, custo, operação, lock-in, segurança e esforço.

### 9.8 Atualidade de fornecedores e custos

**Estado: `OPEN`**

Capacidades e free tiers de Base44, Supabase, Railway, Render, Fly, Cloud Run e provedores de dados mudam. Qualquer decisão futura deve usar documentação e preços atuais.

### 9.9 Licenças e termos de dados

**Estado: `OPEN`**

Scraping do Forex Factory, canais Telegram, OHLC/news feeds e APIs externas exigem validação de termos de uso, licença, retenção, redistribuição e privacidade.

### 9.10 Precisão causal

**Estado: `OPEN`**

O nome “causal” não garante inferência causal científica. Deve-se distinguir:

- hipótese causal explicável;
- associação histórica;
- previsão condicional;
- causalidade identificada com desenho estatístico apropriado.

### 9.11 Risco de look-ahead e leakage

**Estado: `OPEN`**

Ao formar memória empírica e backtests, todos os eventos, traduções, revisões, BLUFs e preços devem respeitar event time, ingestion time e disponibilidade real para evitar leakage.

---

## 10. Alegações históricas que não podem ser promovidas a fatos sem inspeção

| Alegação presente no material histórico                                             | Tratamento obrigatório                                                |
| -------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| O Orchestrator existe em`services/collector_events/globalintel`.                     | Localizar caminho, entrypoint e ownership.                             |
| O pipeline é não linear e MQ-based.                                                  | Reconstruir grafo real de produtores/consumidores.                     |
| Deduplicação é semântica/contextual.                                               | Identificar algoritmo, thresholds e testes.                            |
| Tradução ocorre quando o conteúdo não está em inglês.                            | Validar detecção de idioma e contratos.                              |
| NLP produz sentimento, entidades e`DANGER_SCORE`.                                    | Inspecionar schema, ranges, versão e consumidores.                    |
| `DANGER_SCORE >= 0.7` aciona IA Oracle.                                              | Verificar threshold/configuração e caminhos alternativos.            |
| IA Oracle resume, consolida, interpreta e cria tags.                                   | Localizar prompts, validações, persistência e autoridade.           |
| Strategist mantém Global Pulse e BLUF.                                                | Separar responsabilidades realmente implementadas.                     |
| RabbitMQ transporta os principais fluxos.                                              | Inventariar topologia e garantias de entrega.                          |
| `LOCK_DOWN` bloqueia ordens.                                                         | Verificar enforcement no executor, não apenas publicação do evento. |
| Qwen-Instruct 4B quantizado é o modelo atual.                                         | Confirmar modelo, provider e versão.                                  |
| Há providers para vários LLMs pagos via Abstract Provider/Factory/Concrete Provider. | Localizar código e cobertura.                                         |
| ML técnico ainda não foi iniciado.                                                   | Reavaliar data atual; não repetir como fato.                          |
| Backtesting existe parcialmente e foi pouco testado.                                   | Auditar runners, datasets, determinismo e resultados.                  |
| Parte das ideias propostas talvez já esteja implementada.                             | Tratar como hipótese central da descoberta, não conclusão.          |

---

## 11. Pendências arquiteturais

### 11.1 Artefatos e governança

- `OPEN` — localizar ou regenerar `magickal_union_v2.md` sem modificar o original;
- `OPEN` — localizar documentos finais da Central de Inteligência Fundamental e da Análise Técnica mencionados pelo usuário;
- `OPEN` — definir local canônico, ownership, versionamento e processo de aprovação dos documentos;
- `OPEN` — comparar conteúdo de `ForexSystemLocal` e `ForexSystemCloud` antes de declarar sincronização.

### 11.2 Domínio e semântica

- `OPEN` — definir taxonomia de evento, entidade, país, moeda, tema, mercado, ativo, hipótese e regime;
- `OPEN` — distinguir threat/danger, relevance, impact, tradability, confidence e urgency;
- `OPEN` — definir semântica de confirmação, contradição, atraso, neutralidade e ausência de reação;
- `OPEN` — decidir se “Market Causal Layer” é nome definitivo ou apenas capacidade lógica;
- `OPEN` — definir condições de invalidação e lifecycle de hipóteses.

### 11.3 Estado, tempo e evidência

- `OPEN` — escolher modelo de armazenamento canônico;
- `OPEN` — modelar event time, ingestion time, processing time e market time;
- `OPEN` — definir decay, reinforcement, contradiction e confidence updates;
- `OPEN` — manter lineage de BLUF, tags, hipóteses e decisões até a evidência;
- `OPEN` — definir reprocessamento, replay, versionamento de modelos e correções.

### 11.4 Contratos e MQ

- `OPEN` — inventariar exchanges, queues, bindings, routing keys e payload schemas;
- `OPEN` — classificar commands, events, alerts, policies e read models;
- `OPEN` — definir correlation, causation, idempotency e trace IDs;
- `OPEN` — verificar ordering, retries, DLQs, poison messages e backpressure;
- `OPEN` — versionar contratos sem quebrar consumidores atuais.

### 11.5 Decisão, trading e risco

- `OPEN` — formalizar como o contexto altera histerese, sizing e tolerância;
- `OPEN` — estabelecer limites matemáticos para influência fundamental;
- `OPEN` — mapear Fire Triangle e demais sinais no decision pipeline;
- `OPEN` — definir precedência entre estratégia, sessão, sinal, risco e executor;
- `OPEN` — especificar `LOCK_DOWN`: ativação, persistência, propagação, recovery e autorização de release;
- `OPEN` — assegurar que hard exits sejam impossíveis de anular por LLM/contexto.

### 11.6 Aprendizado e validação

- `OPEN` — construir dataset evento–hipótese–reação–setup–resultado sem leakage;
- `OPEN` — definir métricas de calibração, direção, magnitude, horizonte e confiança;
- `OPEN` — separar backtest técnico de replay fundamental temporalmente correto;
- `OPEN` — decidir quando usar regras, estatística, ML ou LLM;
- `OPEN` — definir shadow mode, paper trading, canary e rollback antes de autonomia real.

### 11.7 Operação e plataforma

- `OPEN` — reconstruir deployment real;
- `OPEN` — decidir se Base44 tem qualquer papel no ForexSystem alvo;
- `OPEN` — comparar RabbitMQ existente com Redis/fila proposta e evitar duplicidade;
- `OPEN` — avaliar banco existente antes de considerar Supabase/Postgres;
- `OPEN` — validar observabilidade, custos, secrets, rede, resiliência e compliance.

---

## 12. Checklist de reconciliação futura contra o código real

### Fase 0 — Regras e proteção do workspace

- [ ] Ler integralmente todos os `AGENTS.md`, do root até cada repo/subdiretório relevante.
- [ ] Registrar precedência e conflitos entre instruções locais.
- [ ] Confirmar quais diretórios são read-only, gerados ou sincronizados.
- [ ] Registrar branch, commit, worktree e mudanças não commitadas de cada repo.
- [ ] Não editar código durante a fase de descoberta.

### Fase 1 — Inventário do polyrepo

- [ ] Enumerar repos, serviços, libs compartilhadas, infra e documentação.
- [ ] Localizar todos os caminhos/names históricos deste handoff.
- [ ] Marcar cada item como `FOUND`, `RENAMED`, `MISSING`, `DEPRECATED` ou `UNKNOWN`.
- [ ] Identificar owners, entrypoints, linguagens, frameworks e manifests.
- [ ] Localizar specs da Central Fundamental e da Análise Técnica.

### Fase 2 — Arquitetura atual reconstruída

- [ ] Gerar mapa de serviços e dependências a partir do código/configuração.
- [ ] Reconstruir fluxo de eventos da coleta à execução.
- [ ] Inventariar bancos, schemas, tabelas, stores, caches e retenção.
- [ ] Inventariar runtime/deploy, ambientes e segredos referenciados.
- [ ] Identificar observabilidade: logs, métricas, tracing e alertas.
- [ ] Citar arquivo e linha para cada conclusão.

### Fase 3 — Contratos e RabbitMQ

- [ ] Mapear producers e consumers.
- [ ] Catalogar exchange/queue/routing key.
- [ ] Extrair schemas e exemplos de payload.
- [ ] Classificar mensagem como command/event/alert/policy/read model.
- [ ] Verificar delivery semantics, retries, DLQ, ordering e idempotência.
- [ ] Rastrear `BUY_ENTRY`, `SELL_ENTRY`, `LOCK_DOWN` e tags do Oracle ponta a ponta.

### Fase 4 — Global Pulse / BLUF / Oracle

- [ ] Localizar modelos e persistência de Global Pulse, contexto e BLUF.
- [ ] Verificar se o BLUF é entrada recursiva do próximo ciclo.
- [ ] Localizar evidências canônicas e links de proveniência.
- [ ] Identificar temporalidade, TTL/decay, reinforcement e contradiction.
- [ ] Auditar prompts, modelos, providers, fallback e schema validation.
- [ ] Determinar autoridade real do Oracle e das tags.

### Fase 5 — NLP e semântica de impacto

- [ ] Localizar cálculo e threshold do `DANGER_SCORE`.
- [ ] Verificar entidades, sentimento, idioma e deduplicação semântica.
- [ ] Procurar scores existentes de relevance/impact/direction/horizon/confidence.
- [ ] Encontrar equivalentes da Market Translation/Causal Layer.
- [ ] Mapear evento → mercado/ativo → hipótese, se existir.

### Fase 6 — Técnico, Fire Triangle e operação

- [ ] Localizar Fire Triangle, GeoVision, IndicatorEngine e SignalGenerator.
- [ ] Documentar inputs, outputs e autoridade de cada um.
- [ ] Verificar se sinais já consomem tags/contexto fundamental.
- [ ] Identificar feedback técnico de volta ao Fundamental/Strategist.
- [ ] Mapear session, regime, sizing, entry, exit e outcome.

### Fase 7 — Risco e segurança

- [ ] Rastrear ativação de `LOCK_DOWN` desde RiskManager até Executor.
- [ ] Confirmar que a rejeição é aplicada no último ponto de autoridade da ordem.
- [ ] Verificar persistência e comportamento após restart/reconnect.
- [ ] Verificar quem pode desativar, com autenticação e auditoria.
- [ ] Separar soft exits/histerese de hard exits/limits.
- [ ] Localizar testes de cenários catastróficos e fail-safe.

### Fase 8 — Dados históricos, backtest e aprendizado

- [ ] Inventariar OHLC, eventos, revisões, hipóteses, sinais e outcomes.
- [ ] Validar alinhamento temporal e ausência de look-ahead.
- [ ] Localizar backtesting existente e medir cobertura/reprodutibilidade.
- [ ] Localizar qualquer ML já iniciado.
- [ ] Avaliar viabilidade do corpus evento–reação–setup–resultado.

### Fase 9 — Matriz conceito ↔ implementação

Para cada conceito da v2/handoff, produzir:

| Campo                 | Conteúdo exigido                                                                                                                                       |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Conceito              | Nome e definição normativa.                                                                                                                           |
| Evidência no repo    | Arquivo, linha, schema, teste ou configuração.                                                                                                        |
| Implementação atual | Descrição factual.                                                                                                                                    |
| Assessment            | `ALREADY_IMPLEMENTED`, `PARTIALLY_IMPLEMENTED`, `EXISTS_UNDER_DIFFERENT_NAME`, `CONFLICTS_WITH_V2`, `MISSING`, `SHOULD_NOT_BE_IMPLEMENTED`. |
| Gap                   | Diferença específica, sem linguagem genérica.                                                                                                        |
| Reuse                 | Componentes/contratos que devem ser preservados.                                                                                                        |
| Target                | Estado desejado justificado.                                                                                                                            |
| Migration             | Passos compatíveis e reversíveis.                                                                                                                     |
| Tests                 | Evidência de aceitação e regressão.                                                                                                                 |
| Confidence            | Alta/média/baixa e razão.                                                                                                                             |

### Fase 10 — Decisão de plataforma

- [ ] Reconstruir hosting, banco, filas e APIs atuais.
- [ ] Comparar requisitos com Base44/Supabase/runtime externo.
- [ ] Tratar a topologia Base44 como alternativa, não baseline.
- [ ] Revalidar documentação, preços, quotas e limites atuais.
- [ ] Avaliar segurança, lock-in, custo operacional e migração.
- [ ] Emitir ADR explícita: adotar, integrar parcialmente ou rejeitar.

### Fase 11 — Arquitetura alvo e migração

- [ ] Produzir current-state architecture com evidência.
- [ ] Produzir gap analysis sem inventar componentes.
- [ ] Definir boundaries alvo e contracts versionados.
- [ ] Definir transição de BLUF recursivo para evidência/estado/projeção, se aplicável.
- [ ] Definir integração bidirecional e feedback.
- [ ] Definir safety invariants e testes.
- [ ] Planejar migração por fases com compatibilidade, observabilidade e rollback.
- [ ] Só então gerar `magickal_union_architecture.md`.

---

## 13. Formato obrigatório do futuro relatório forense

O Work deve produzir, no mínimo:

1. escopo, commits e repos inspecionados;
2. regras `AGENTS.md` aplicáveis;
3. inventário do polyrepo;
4. arquitetura atual baseada em evidências;
5. catálogo de contratos/MQ/schemas;
6. mapa de estado, dados e temporalidade;
7. matriz conceito ↔ implementação;
8. conflitos entre documentação e código;
9. gaps e duplicações;
10. arquitetura alvo;
11. ADRs de decisões ainda abertas;
12. plano de migração faseado;
13. estratégia de testes e rollout;
14. apêndice com citações de arquivo/linha.

Cada descoberta deve separar:

```text
FACT         = comprovado no repo/runtime/config
INFERENCE    = conclusão derivada, com justificativa
HISTORICAL   = alegação vinda desta conversa/documentos
TARGET       = estado desejado
OPEN         = evidência ou decisão faltante
```

---

## 14. Critérios de aceitação do futuro `magickal_union_architecture.md`

O documento final somente estará pronto quando:

- [ ] nenhum componente novo for proposto sem busca por equivalentes;
- [ ] toda afirmação sobre implementação tiver evidência de arquivo/linha ou runtime;
- [ ] `Global Pulse`, BLUF, evidência e hipótese tiverem responsabilidades não ambíguas;
- [ ] perigo e impacto de mercado estiverem semanticamente separados;
- [ ] o loop Fundamental ⇄ Técnico estiver expresso em contratos e estados;
- [ ] Fire Triangle tiver papel e autoridade explícitos;
- [ ] `LOCK_DOWN` e hard safety tiverem invariantes verificáveis;
- [ ] MQ commands/events/policies estiverem classificados e versionados;
- [ ] event time e prevenção de leakage estiverem definidos;
- [ ] a migração preservar compatibilidade ou declarar breaking changes;
- [ ] Local/Cloud tiverem fluxo de publicação inequívoco;
- [ ] a linguagem ontológica da Magickal Union continuar reconhecível;
- [ ] nenhuma metáfora substituir especificação testável na seção técnica.

---

## 15. Próxima ação recomendada

**Estado: `DECIDED`**

Executar a fase forense no `ForexSystemLocal`, começando pelos `AGENTS.md`, sem alterações de código. A primeira entrega deve ser:

```text
FOREXSYSTEM_CURRENT_STATE_AND_MAGICKAL_UNION_RECONCILIATION.md
```

Esse relatório deve conter a matriz conceito ↔ implementação e resolver, com evidência, quais partes da visão:

- já estão implementadas;
- estão parcialmente implementadas;
- existem sob outro nome;
- conflitam com a v2;
- estão ausentes;
- não deveriam ser implementadas.

Somente após revisão dessa entrega deve ser escrito o `magickal_union_architecture.md` e, depois, quebrado o trabalho em fases implementáveis para o Codex.

---

## Apêndice A — Glossário de nomes adotados

| Nome                                       | Papel preservado                                                     |
| ------------------------------------------ | -------------------------------------------------------------------- |
| Magickal Union / Grande União             | Visão da integração multidimensional.                             |
| Cruzamento Semântico                      | Método de tradução de intenção abstrata em engenharia.          |
| Global Pulse                               | Estado dinâmico do mundo e hipóteses relacionadas ao mercado.      |
| BLUF                                       | Projeção resumida derivada.                                        |
| World Intelligence                         | Capacidade de perceber e interpretar o mundo.                        |
| Market Translation / Causal / Impact Layer | Capacidade intermediária de traduzir mundo em hipótese por ativo.  |
| Expected Reaction                          | Reação de mercado prevista pela hipótese.                         |
| Execution Intelligence                     | Capacidade de observar confirmação, decidir timing e operar.       |
| Fire Triangle                              | Sensor/motor técnico a contextualizar.                              |
| `DANGER_SCORE`                           | Score histórico de perigo/triagem NLP.                              |
| IA Oracle                                  | Serviço/agente LLM de resumo, consolidação e interpretação.     |
| Strategist                                 | Componente histórico associado ao Global Pulse e BLUF.              |
| `LOCK_DOWN`                              | Política dura e soberana de segurança.                             |
| Event Store                                | Responsabilidade de preservar evidência; tecnologia não escolhida. |

## Apêndice B — Nomes ilustrativos que não devem ser tratados como adotados

Durante a conversa foram usados exemplos como `GlobalPulseState`, `GlobalContextState`, `BLUFGenerator`, `StrategistState` e `GlobalPulseStateService` para explicar como mapear um conceito a implementações possivelmente existentes.

**Estado: `OPEN`**

Esses nomes foram ilustrativos/hipotéticos. Não criar, renomear ou procurar correspondência exata sem primeiro inspecionar o polyrepo.

## Apêndice C — Prompt operacional condensado para o futuro Work

> Leia primeiro todos os `AGENTS.md` aplicáveis. Reconstrua o estado atual do polyrepo antes de desenhar a arquitetura alvo. Trate `magickal_union_v2.md` como visão normativa e o código/testes/configuração como evidência do estado atual. Não proponha nenhum componente antes de procurar equivalentes completos, parciais, depreciados, planejados ou existentes sob outro nome. Para cada conceito, produza implementação atual, evidência de arquivo/linha, assessment, gap, reuse, target, migration e tests. Diferencie fatos, inferências, alegações históricas, target state e questões abertas. Audite especialmente Global Pulse versus BLUF, evidência/proveniência, temporalidade, `DANGER_SCORE` versus impacto de mercado, Market Translation/Causal Layer, feedback Fundamental ⇄ Técnico, Fire Triangle, RabbitMQ e `LOCK_DOWN`. Não altere código. Entregue primeiro a reconciliação current-state; somente após revisão produza `magickal_union_architecture.md`.
