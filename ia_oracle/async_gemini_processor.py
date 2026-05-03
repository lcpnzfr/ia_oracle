import os
import json
import asyncio
import aiofiles
from google import genai
from google.genai import types
from pathlib import Path
from dotenv import load_dotenv

# ---------------------------------------------------------
# Configuração Global da API
# ---------------------------------------------------------
load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("A variável de ambiente GEMINI_API_KEY não foi definida.")

# 1. MUDANÇA: Instanciamento correto do Cliente da nova SDK.
# Removemos o "genai.configure" e o "GenerativeModel".
client = genai.Client(api_key=API_KEY)

MODELOS_ATIVOS =[
    # ---- GERAÇÃO 3 (Mais Inteligentes / Previews Recentes) ----
    "gemini-3.1-pro",           # O mais avançado de todos atualmente
    "gemini-3-flash",           # Rápido e inteligência nível Pro
    "gemini-3.1-flash-lite",    # O mais barato e rápido da nova geração
    
    # ---- GERAÇÃO 2.5 (Super Estáveis e Padrão de Mercado) ----
    "gemini-2.5-pro",           # Focado em raciocínio e código
    "gemini-2.5-flash",         # O melhor custo-benefício (Standard)
    "gemini-2.5-flash-lite",    # Versão ultra-rápida do 2.5
    
    # ---- GERAÇÃO 2.0 (Os mais antigos que AINDA funcionam) ----
    "gemini-2.0-flash",         # Legado estável
    "gemini-2.0-flash-lite"     # Legado leve
]

# ---------------------------------------------------------
# Componente 2 & 3: ConcurrencyController e LLMWorker
# ---------------------------------------------------------
import re # <-- Não esqueça de colocar isso lá no topo do arquivo junto com os imports

async def process_single_message(message: dict, semaphore: asyncio.Semaphore) -> dict:
    """
    LLMWorker com Retry Inteligente lendo o 'retryDelay' da API do Google.
    """
    msg_id = message.get("id")
    content = message.get("content")
    max_retries = 5 # Vamos dar 5 chances já que agora controlamos o tempo exato
    
    async with semaphore:
        for attempt in range(max_retries):
            print(f"[{msg_id}] Iniciando processamento (Tentativa {attempt + 1}/{max_retries})...")
            try:
                response = await client.aio.models.generate_content(
                    model='gemini-2.5-flash-lite', 
                    contents=content
                )

                # Verifica bloqueio de segurança
                if response.candidates and response.candidates[0].finish_reason in[
                    types.FinishReason.SAFETY, 
                    types.FinishReason.BLOCKLIST
                ]:
                    print(f"[{msg_id}] Erro: Bloqueado por políticas de segurança.")
                    return {"id": msg_id, "status": "blocked_by_safety"}

                print(f"[{msg_id}] Sucesso.")
                
                # Respiro padrão de 2 segundos mesmo no sucesso para não "sufocar" a API logo em seguida
                await asyncio.sleep(4.5)
                
                return {
                    "id": msg_id,
                    "original_prompt": content,
                    "response": response.text,
                    "status": "success"
                }
                
            except Exception as e:
                error_msg = str(e)
                
                # Se for erro 429
                if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                    if attempt < max_retries - 1:
                        
                        wait_time = 30.0 # Tempo padrão caso não encontremos o número na mensagem
                        
                        # Tenta procurar pelo padrão numérico: "Please retry in 8.0777s."
                        match = re.search(r"Please retry in (\d+(?:\.\d+)?)s", error_msg)
                        if match:
                            # Captura o número exato pedido pela API e soma +1s de garantia
                            wait_time = float(match.group(1)) + 1.0 
                        else:
                            # Plano B: Tenta achar o parâmetro 'retryDelay': '8s'
                            match_delay = re.search(r"'retryDelay':\s*'(\d+)s'", error_msg)
                            if match_delay:
                                wait_time = float(match_delay.group(1)) + 1.0
                        
                        print(f"[{msg_id}] ⚠️ API pediu pausa. Entrando em stand-by por {wait_time:.2f} segundos...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        print(f"[{msg_id}] Falha fatal após {max_retries} tentativas.")
                        return {"id": msg_id, "status": "error", "error_message": "Rate limit esgotado."}
                
                # Para outros tipos de erro
                print(f"[{msg_id}] Erro de I/O ou API: {error_msg}")
                return {"id": msg_id, "status": "error", "error_message": error_msg}

# ---------------------------------------------------------
# Componente 1: MockIngestor
# ---------------------------------------------------------
async def load_messages(filepath: str) -> list:
    """Lê o arquivo de forma assíncrona (File I/O Optimization)"""
    try:
        async with aiofiles.open(filepath, mode='r', encoding='utf-8') as f:
            content = await f.read()
            return json.loads(content)
    except FileNotFoundError:
        print(f"Arquivo de input não encontrado: {filepath}")
        return[]

# ---------------------------------------------------------
# Componente 4: ResultAggregator
# ---------------------------------------------------------
async def save_results(filepath: str, results: list):
    """Grava o resultado no disco de forma assíncrona"""
    
    # Garante que a pasta pai exista antes de tentar salvar
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    async with aiofiles.open(filepath, mode='w', encoding='utf-8') as f:
        await f.write(json.dumps(results, indent=4, ensure_ascii=False))
    print(f"\nResultados salvos com sucesso em: {filepath}")

# ---------------------------------------------------------
# Fluxo de Execução Principal
# ---------------------------------------------------------
async def main():

    # 1. Encontrar raiz do projeto
    ROOT_DIR = Path(__file__).parent

    # 2. Montar caminhos para inputs/outputs
    DATA_DIR = os.path.join(ROOT_DIR, 'data')
    input_file = os.path.join(DATA_DIR, "mock_messages.json")
    output_file = os.path.join(DATA_DIR, "output_results.json")
    
    # Controle de Concorrência
    MAX_CONCURRENT_REQUESTS = 1
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    
    print("Iniciando ingestão de dados...")
    messages = await load_messages(input_file)
    
    if not messages:
        print("Nenhuma mensagem para processar. Encerrando.")
        return

    print(f"{len(messages)} mensagens carregadas. Iniciando cluster de processamento assíncrono...")
    
    # Cria uma lista de tarefas (Coroutines) para executar em paralelo no Event Loop
    tasks =[process_single_message(msg, semaphore) for msg in messages]
    
    # asyncio.gather executa todas as tarefas de forma concorrente e aguarda todas finalizarem
    results = await asyncio.gather(*tasks)
    
    print("Consolidando resultados...")
    await save_results(output_file, list(results))

if __name__ == "__main__":
    # Ponto de entrada do sistema assíncrono
    asyncio.run(main())