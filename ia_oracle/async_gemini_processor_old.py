import os
import json
import asyncio
import aiofiles
import re
from google import genai
from google.genai import types
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("A variável de ambiente GEMINI_API_KEY não foi definida.")

client = genai.Client(api_key=API_KEY)

# ----------------------
# Configuração Avançada 
# ----------------------

ROOT_DIR = Path(__file__).parent
PROMPT_FILE = os.path.join(ROOT_DIR, "prompts", "ia_trend_oracle.md")

with open(PROMPT_FILE, "r", encoding="utf-8") as f:
    system_prompt = f.read()

tools = [
    types.Tool(url_context=types.UrlContext()),
    #types.Tool(googleSearch=types.GoogleSearch()),
]

configuracao_playground = types.GenerateContentConfig(
    temperature=0.2,
    top_p=0.95,
    max_output_tokens=22000,
    thinking_config=types.ThinkingConfig(
        thinking_level="MEDIUM",
    ),
    media_resolution="MEDIA_RESOLUTION_MEDIUM",
    tools=tools,
    system_instruction=[
        types.Part.from_text(text=system_prompt),
    ]
)

async def descobrir_modelos_disponiveis(client):
    """
    Consulta a API para descobrir quais modelos estão disponíveis.
    Retorna uma lista limpa dos modelos que suportam geração de conteúdo.
    """
    print("🔍 Consultando modelos disponíveis na API...")
    
    # O client.models.list é síncrono por padrão na SDK atual
    # Para ser puramente assíncrono, usamos o thread, mas aqui é um setup inicial rápido
    response = client.models.list()
    
    modelos_validos = []
    
    for model in response:

        # Filtra apenas modelos que suportam generateContent
        if "generateContent" in model.supported_actions:
            # Filtra apenas modelos que começam com 'gemini-'
            if model.name.startswith("models/gemini-"):
                # Remove o prefixo 'models/' para ficar igual ao que enviamos na API
                nome_limpo = model.name.replace("models/", "")
                
                #if "robotics" in nome_limpo or "image" in nome_limpo:
                    #continue

                modelos_validos.append(nome_limpo)
    
    print(f"✅ Modelos encontrados: {len(modelos_validos)}")
    # Ordena para garantir que os mais recentes apareçam primeiro (opcional)
    return sorted(modelos_validos, reverse=True)

# ---------------------------------------------------------
# Worker Assíncrono com Rotação de Modelos
# ---------------------------------------------------------
async def process_single_message(message: dict, semaphore: asyncio.Semaphore) -> dict:
    msg_id = message.get("id")
    content = message.get("content")
    
    # Agora desvinculamos o número de tentativas do tamanho do array.
    # Podemos tentar 15 vezes. Como temos 6 modelos, ele vai dar "2 voltas e meia" no array antes de desistir.
    max_retries = 15 
    total_modelos = len(MODELOS_ATIVOS)
    
    async with semaphore:
        for attempt in range(max_retries):
            # O TRUQUE DE MESTRE: Index circular usando Módulo (%)
            # Garante que o index sempre fique entre 0 e 5.
            index_atual = attempt % total_modelos
            modelo_atual = MODELOS_ATIVOS[index_atual]
            
            print(f"[{msg_id}] Processando (Modelo: {modelo_atual}) | Tent. {attempt + 1}/{max_retries}...")
            
            try:
                response = await client.aio.models.generate_content(
                    model=modelo_atual, 
                    contents=content,
                    config=configuracao_playground
                )

                if response.candidates and response.candidates[0].finish_reason in[
                    types.FinishReason.SAFETY, types.FinishReason.BLOCKLIST
                ]:
                    print(f"[{msg_id}] Erro: Bloqueado por segurança.")
                    return {"id": msg_id, "status": "blocked_by_safety"}

                print(f"[{msg_id}] ✅ Sucesso com {modelo_atual}.")
                await asyncio.sleep(1.0) 
                
                return {
                    "id": msg_id,
                    "original_prompt": content,
                    "response": response.text,
                    "status": "success",
                    "model_used": modelo_atual
                }
                
            except Exception as e:
                error_msg = str(e)
                
                if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                    if attempt < max_retries - 1:
                        # Pega o nome do próximo modelo apenas para informar no log
                        proximo_index = (attempt + 1) % total_modelos
                        proximo_modelo = MODELOS_ATIVOS[proximo_index]
                        
                        print(f"[{msg_id}] ⚠️ Cota do {modelo_atual} esgotada. Rotacionando para {proximo_modelo}...")
                        
                        # Se deu a volta completa no array (tentou todos os modelos 1 vez), 
                        # dá uma pausa maior para a API inteira "respirar".
                        if proximo_index == 0:
                            print(f"[{msg_id}] 🔄 Ciclo completo! Pausa de segurança de 10s...")
                            await asyncio.sleep(10.0)
                        else:
                            await asyncio.sleep(2.0)
                            
                        continue
                    else:
                        print(f"[{msg_id}] ❌ Falha fatal: Cota esgotada após {max_retries} tentativas.")
                        return {"id": msg_id, "status": "error", "error_message": "Rate limit esgotado em todas as rotações."}
                
                # Para erros que não são de Rate Limit (como internet off)
                print(f"[{msg_id}] Erro Crítico: {error_msg}")
                return {"id": msg_id, "status": "error", "error_message": error_msg}

# ---------------------------------------------------------
# Restante do script (Load, Save e Main continuam os mesmos)
# ---------------------------------------------------------
async def load_messages(filepath: str) -> list:
    try:
        async with aiofiles.open(filepath, mode='r', encoding='utf-8') as f:
            return json.loads(await f.read())
    except FileNotFoundError:
        return[]

async def save_results(filepath: str, results: list):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    async with aiofiles.open(filepath, mode='w', encoding='utf-8') as f:
        await f.write(json.dumps(results, indent=4, ensure_ascii=False))
    print(f"\nResultados salvos em: {filepath}")

async def main():
    
    DATA_DIR = os.path.join(ROOT_DIR, 'data')
    input_file = os.path.join(DATA_DIR, "mock_messages.json")
    output_file = os.path.join(DATA_DIR, "output_results.json")
    
    # Com a rotação de modelos, você pode arriscar subir a concorrência para 3 ou 5!
    semaphore = asyncio.Semaphore(3) 
    
    messages = await load_messages(input_file)
    if not messages: return

    global MODELOS_ATIVOS
    MODELOS_ATIVOS = await descobrir_modelos_disponiveis(client)
    
    if not MODELOS_ATIVOS:
        print("❌ Nenhum modelo compatível encontrado!")
        return
        
    print(f"🚀 Modelos carregados dinamicamente: {MODELOS_ATIVOS}")

    print(f"Iniciando cluster. Total de mensagens: {len(messages)}")
    tasks =[process_single_message(msg, semaphore) for msg in messages]
    results = await asyncio.gather(*tasks)
    
    await save_results(output_file, list(results))

if __name__ == "__main__":
    asyncio.run(main())