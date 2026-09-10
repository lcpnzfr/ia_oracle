# Forex System Conceptual / Ontological Specification

#### OBJETIVO

Planejar e integração definitiva entre as duas dimensões de funcionamento do sistema:  a `Central de Inteligência Fundamental e a Central de Análise Técnica e Operações`

### Instrução de leitura para IA

O presente documento demonstra um gap de integração entre duas partes do sistema. Porém você IA, terá que usar um modelo e uma linha de cognição que vai além da linguagem exata, usando termos abstratos comummente não usados em especificação ou pré-planejamento de implantação, pois são linguagens de ordens completamente diferentes para sistema, porém cada conceito abstrato destes é usado para tornar claro, através de uma técnica que inventei de `Cruzamento Semântico`.

Você deve, ao se deparar com um conceito abstrato, obter a correlação sistêmica e a nível de arquitetura e programação de código.

Esta mesclagem de linguagem me fez conseguir expressar melhor o OBJETIVO que este documento declara.

### Central de Inteligência Fundamental - A Dimensão da Inteligência

Os principais repos da `Central de Inteligência Fundamental` são:

- services/collector_events
- services/collector_events/translation
- services/osint_engine
- services/nlp
- services/ia_oracle

O `Orchestrator` (em `services/collector_events/globalintel`) gerencia a execução dos extratores, e note todo o percurso (não linear/MQ based) que as mensagens e eventos coletados fazem pelo `pipeline`:

- `Deduplicação:`(***não só por texto exato, mas por semântica contextual)***.
- `Tradução:`(se a mensagem\evento **NÃO** for em Inglês)
- `NLP:` gera atributos de sentimento, extrai entidades, etc., e gera o campo crítico `DANGER_SCORE`, que é avaliado após o cálculo de NLP multifase, e se este score de perigo for >= 0.7, ele `solicita suporte ao IA_Oracle`
  - hoje tô usando um modelo quantizado tipo Qwen-Instruct_4b, devido às limitações de custo/hospedagem/assinaturas de serviços/assinaturas de API's/etc), porém eu tenho na `Arquitetura Clássica do Sistema` (***Abstract Provider -> Factory -> Concrete Provider***), que tenho providers para grande parte dos LLMs pagos do mercado.
- **`IA Oracle`**: Serviço que consulta envia prompts curados e desenhados especificamente para cada propósito abauxi e usa as respostas para LLMs para:
  - **resumo de texto**
  - **consoliação de eventos e mensagens**
  - **interpretação da mensagem ou evento enviado pelo serviço NLP que teve DANGER_SCORE >=0.7**
    - O LLM como arbitro final, nestes casos ele recebe um conjunto de informações adicionais para calibrar o contexto (as entidades, sentimentos dentre outros atributos processados pelo serviço `NLP`) e é solicitada a decisão sobre a criação de TAGs (que são propagadas via Message MQ dependendo da resposta do LLM).
      - Estas TAGs irão ativar ou mudar certos comportamentos do sistema.
    - ***❤️ ESTE É UM PONTO QUE FOI DESENHADO PARA SER INTERCEPTADO PELA DIMENSÃO DE `ANÁLISE TÉCNICA E OPERACIONAL` DO SISTEMA.***
  - O serviço `IA_Oracle` ainda tem o `STRATEGIST`, responsável por manter o que chamei de `GLOBAL PULSE` (um contexto pulsante global do status do mundo - pelo menos essa é a ideia romântica) que promove um contextos por entidade, país, moeda, etc) globais e sempre atualizados.
  - ❤️‍🔥 O Strategist, em intervalos regulares, sumariza as últimas mensagens/eventos recebidas pelo pipeline e cria o `BLUF` (`Bottom Line Up Front`), sumarizando todo o fluxo de mensagens e informações dos extratores e gerando um `Contexto Global`que é atualizado periodicamente com `NOVAS`informações dos extratores mas também levando em conta o `CONTEXTO` anterior. Isto é, o Strategist promove o contexto atual mas leva em conta também o contexto anterior criando um processo `auto-evolutivo` e `retroalimentável`.
    - `➡️ E assim ele ❤️‍🔥PULSA❤️‍🔥`, no que chamei de `Global Pulse`(o coração da `Base de Inteligência`) e `esta parte do sistema` deve ter ⚡`impacto comportamental`na`Análise Técnica`, que passará a ter ciência dos `Pulsos de Contexto do Mundo`e `deverá se adaptar` à eles.

> As `Mensagens MQ` são enviadas `durante todo o pipeline` para ativar ações específicas do fluxo e para `Alertas` a nível global do sistema, como, por exemplo, `BUY_ENTRY`/ `SELL_ENTRY`.
> Ou mensagens de `CONTROLE`, como o `LOCK_DOWN`, que é qdo o `RiskManager`detecta que a conta DE TRADING`tá em risco`e qualquer ordem de compra ou venda é rejeitada e não executada, até que o`LOCK_DOWN`seja desativado. Todos principais pontos de fluxos do sistema são baseados em MessageMQ (atualmente usando`RabbitMQ`).

### A dimensão de Análise Técnica e Operações - A Dimensão Matemática

Os principais repos da `Dimensão Matemática / Análise Técnica`são:

- services/collector_history
- services/session_manager
- services/indicator_engine
- services/signal_generator
- services/geo_vision
- services/trading_session
- services/executor_trading
- services/risk_manager

Estes módulos formam a parte do `Analista Técnico / Operador de Trading.`
A interagação entre a`Base de Inteligência`com os motores da `Análise Técnica` (o Fire Triangle, por exemplo) e são responsáveis por:

- Estratégias de Trading,
- Mecanismos de Análise do Fluxo Financeiro,
- Análise Geométrica e
- `Execução e Encerramento de Ordens de Compra e Venda`
- Históricos OHLC
- Machine Learning (ainda não iniciado),
- Dentre outras tecnologias e metodologias ainda a serem incorporadas

* Backtesting,

  até que existem, embora somente até um determinado grau), mas foi muito pouco testada e a `Análise Técnica` precisa de `um maior grau de conexão` com a `Gigante` e `Extremamente Valiosa` `Base de Inteligência`.`irão respirar juntos`, pois afinal de contas, não são dois sistemas, é um único sistema que deve viver em harmonia com seus diferentes aspectos e dimensões de existência e propósito implementados, formando um único ser (solução): muito bem informado, inteligente, robusto, rápido e que atua  harmonicamente sobre as múltiplas facetas do `Gigantesco`e`Complexo Mercado Financeiro`.

Sem esta conjunção das duas dimensões do sistema, `Análise Técnica` haje como se o mercado fosse um conjunto de criaturas gigantescas impiedosas guiadas por fluxos infernais e caóticos de números.

## ***A GRANDE UNIÃO***

É aqui que entra a grande integração, o elo perdido da `Dimensão Matemática` que precisamos refinar e testar:

Conforme descrito, a `Dimensão de Inteligência`mantém uma`Rede de Inteligêcia com nível de Observabilidade Planetário`,  equipada com telas micro, macro e gigantes, com dashboards sofisticados, `Mostrando as Pulsações do Status atual do Mundo`, disponíveis para todo o sistema (tanto para os módulos autônomos como para os `Usuários Finais`).

Possui intercominunicação veloz e de conteúdo precioso, e uma equipe de agentes altamente especializada com acesso à sistemas sofisticados de captura, classificação e interpretação de informações e tomada de decisão autônoma em`Tempo Real.`

Este comportamento e sofisticação da `Dimensão de Inteligência`eu nomei de `Global Pulse`.

Com o `Global Pulse` eu não me limito apenas um conjunto de extrator de dados de `Preço de MErcado`(OHLC), Indicatores Técnicos, Motores Técnicos, Estratégias que não possuem noção do `POR QUE`certo movimento de preços acontecem.x

A `Inteligência Fundamental`constitui uma ***representação dinâmica, causal e temporal do estado do mundo***.

***A `Inteligência Técnica`observa como os mercados estão reagindo a esse estado***. A `Grande União`ocorre quando a ***reação observada retroalimenta continuamente a interpretação do mundo***, fazendo com que ***contexto e comportamento de mercado evoluam como dimensões de um único sistema cognitivo***.

Sem esta `Grande União`a `Análise Técnica`haje como se o mercado fosse um conjunto de criaturas impiedosas e gigantes guiadas por fluxos infernais de comportamentos caóticos e muitas vezes catastróficos.

Operar o `Mercado Financeiro` baseando-se apenas em `Análise Técnica`é similar com você tentar compreender um `Tratado de Lei Natural`escrito em um alfabeto e formato provindos de um ser cuja natureza existencial é de uma ordem superior não só à sua, mas a de todos os seres humanos. E pior, sem que você nenhuma espécie de relação ou proximidade com esta natureza consciencial elevada.

Suponha que sua inocente tentativa de leitura foi escrita em `Alfabeto Celestial`(também conhecido como *Scriptura Malachim*, *Escrita Angélica* ou *Alfabeto Enoqueano*).

NUNCA terá uma tradução INTELIGÍVEL (será obscura, poética ou uma mistura de ambos, e em grande parte das vezes, frustrante), sem que se seja introduzido a um `contexto gigantesco`, `altamente diversificado` e `extremamente complexo`, para entender o que as revelações que a tradução proporciona, siplesmente será sempre limitado, pois o nível profundo e fundamental, a natureza e a estrutura consciencial são existencialmente diferentes.

##### *❤️‍🔥 Como então introduzir o contexto e nível consciencial do `Global Pulse`, a `Representação Dinâmica do estado do Mundo`na `Análise Técnica`para que a mesma obtenha o conhecimento necessário, proporcionado pelo `Global Pulse`para parar de reagir de forma arcaica aos preços e passar a reagir baseado em decisões de ordem superior?*

Suponha que você conseguiu contato com o ser superior que escreveu o texto em Alfabeto Celestial, `fez-se entender à você`e em `intenção pura e genuína`, você se dedicou em `aprender as estruturas conscienciais por trás da forma como o conhecimento era expresso através daquele alfabeto críptico. Vocês passaram a dialogar`. `Vocês criaram uma conexão`, e sua insatisfação com os métodos usados até o momento para analisar e operar o mercado financeiro ficaram bastante claros para a entidade.

O ser celestial fazendo-se entender novamente (`através de seus poderes de comunicação interdimensional`) resolve então ensinar não simplesmente o significado das letras celestiais, mas resolveu lhe passar uma série de textos escritos em linguagem celestial, textos estes dispostos em formas bem específicas, criando desenhos proporcionaram as ferramentas e mecanismos necessários para que fosse possível pra você finalmente entender e ver um novo universo.

Seu ofício como `Trader`mudou para sempre, e seu sucesso foi tão notório que sua fama cresceu vertiginosamente. E isso tudo como resultado da `UNIÃO`de seu `NOVO`e`GIGANTE CONTEXTO`, `DO QUAL PASSOU A TER ACESSO IRRESTRITO` e `DA SUA ELEVAÇÃO INCRIVELMENTE ACENTUADA DE SEU NÍVEL CONSCIENCIAL E ENTÃO SUA ANÁLISE TÉCNICA E A INTELIGÊNCIA SUPERIOR SE TORNARAM UM SÓ SISTEMA HARÔNICO E MULTIDIMENSIONAL, CULMINANDO, ENFIM, NA ELEVAÇÃO DA SUA PRÓPRIA ORDEM EXISTENCIAL`.
