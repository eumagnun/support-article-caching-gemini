import subprocess
import json
import os
import time

# --- CONFIGURAÇÕES ---
# O ID do projeto foi atualizado para o seu ambiente de testes
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "[SEU-PROJECT-ID]")
LOCATION = "global"

# Ajuste do endpoint caso a localização seja 'global'
if LOCATION == "global":
    API_ENDPOINT = "aiplatform.googleapis.com"
else:
    API_ENDPOINT = f"{LOCATION}-aiplatform.googleapis.com"

MODEL_ID = "gemini-3-flash-preview" 

def run_curl(method, path, data=None):
    """Executa um comando curl e retorna o JSON de resposta."""
    # Obtém o token de autenticação via gcloud
    token_proc = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True)
    token = token_proc.stdout.strip()

    url = f"https://{API_ENDPOINT}/v1/projects/{PROJECT_ID}/locations/{LOCATION}/{path}"
    
    cmd = [
        "curl", "-s", "-X", method,
        "-H", f"Authorization: Bearer {token}",
        "-H", "Content-Type: application/json",
        url
    ]
    
    if data:
        cmd += ["-d", json.dumps(data)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if not result.stdout:
        return {"error": "Sem resposta da API (stdout vazio)", "details": result.stderr}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": "Falha ao decodificar JSON", "raw": result.stdout}

def test_implicit_caching():
    print("\n--- A TESTAR CACHE IMPLÍCITO ---")
    
    # 1. Garantir que o cache está habilitado no projeto
    print("A ativar o cache no projeto...")
    run_curl("PATCH", "cacheConfig", {
        "name": f"projects/{PROJECT_ID}/locations/{LOCATION}/cacheConfig",
        "disableCache": False
    })

    # 2. Enviar requisições repetidas com o mesmo prefixo
    # Incluindo um PDF e texto longo para garantir que passamos os 2048 tokens
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {
                    "fileData": {
                        "mimeType": "application/pdf", 
                        "fileUri": "gs://cloud-samples-data/generative-ai/pdf/2312.11805v3.pdf"
                    }
                },
                {"text": "Este é um contexto muito longo que deve ser repetido para testar o cache... " * 100},
                {"text": "Pergunta: Resume o documento PDF e o texto acima."}
            ]
        }]
    }

    for i in range(1, 4):
        print(f"Tentativa {i}...")
        response = run_curl("POST", f"publishers/google/models/{MODEL_ID}:generateContent", payload)
        
        if "error" in response:
            print(f"Erro na API: {json.dumps(response, indent=2)}")
            break

        usage = response.get("usageMetadata", {})
        cached_tokens = usage.get("cachedContentTokenCount", 0)
        print(f"Tokens de entrada: {usage.get('promptTokenCount')}")
        print(f"Tokens em cache: {cached_tokens}")
        
        if cached_tokens > 0:
            print("✓ Cache hit detetado no cache implícito!")
            break
        time.sleep(1)

def test_explicit_caching():
    print("\n--- A TESTAR CACHE EXPLÍCITO ---")

    # 1. Criar o Context Cache
    print("A criar cache explícito...")
    cache_config = {
        "model": f"projects/{PROJECT_ID}/locations/{LOCATION}/publishers/google/models/{MODEL_ID}",
        "contents": [{
            "role": "user",
            "parts": [
                {"fileData": {"mimeType": "application/pdf", "fileUri": "gs://cloud-samples-data/generative-ai/pdf/2312.11805v3.pdf"}},
                {"fileData": {"mimeType": "application/pdf", "fileUri": "gs://cloud-samples-data/generative-ai/pdf/2403.05530.pdf"}}
            ]
        }],
        "ttl": "600s"
    }
    
    cache_response = run_curl("POST", "cachedContents", cache_config)
    
    if "error" in cache_response:
        print(f"Erro ao criar cache: {json.dumps(cache_response, indent=2)}")
        return

    cache_name = cache_response.get("name")
    print(f"Cache criado com sucesso: {cache_name}")

    # 2. Usar o Cache para gerar conteúdo
    print("A enviar pergunta usando o cache criado...")
    query_payload = {
        "contents": [{
            "role": "user",
            "parts": [{"text": "Qual o objetivo comum destes dois artigos?"}]
        }],
        "cachedContent": cache_name
    }
    
    gen_response = run_curl("POST", f"publishers/google/models/{MODEL_ID}:generateContent", query_payload)
    
    if "error" in gen_response:
        print(f"Erro ao gerar conteúdo: {json.dumps(gen_response, indent=2)}")
    elif "candidates" not in gen_response:
        print(f"Resposta inesperada da API: {json.dumps(gen_response, indent=2)}")
    else:
        usage = gen_response.get("usageMetadata", {})
        text = gen_response['candidates'][0]['content']['parts'][0].get('text', 'Sem texto na resposta.')
        print(f"Resposta do modelo: {text[:100]}...")
        print(f"Tokens em cache utilizados: {usage.get('cachedContentTokenCount')}")

    # 3. Atualizar TTL do cache
    print("A atualizar o tempo de expiração (TTL)...")
    run_curl("PATCH", cache_name, {"ttl": "3600s"})

    # 4. Eliminar o cache
    print("Limpeza: A eliminar o cache...")
    run_curl("DELETE", cache_name)
    print("Cache eliminado.")

if __name__ == "__main__":
    if PROJECT_ID == "[SEU-PROJECT-ID]":
        print("Por favor, configure o PROJECT_ID no script ou na variável de ambiente.")
    else:
        test_implicit_caching()
        test_explicit_caching()
