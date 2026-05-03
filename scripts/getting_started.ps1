# 1. Definindo os Cabeçalhos (Headers)
$headers = @{
    "Content-Type"   = "application/json"
    "X-goog-api-key" = "AIzaSyAXY3OfDHKyXH-rDSKwJMUWNP_N3qjLbAg"
}

# 2. Definindo o Corpo da Requisição (Payload JSON)
$body = @"
{
  "contents": [
    {
      "parts": [
        {
          "text": "Explain how AI works in a few words"
        }
      ]
    }
  ]
}
"@

# 3. Executando a requisição HTTP POST
$response = Invoke-RestMethod -Uri "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent" `
                              -Method Post `
                              -Headers $headers `
                              -Body $body

# 4. Exibindo o texto da resposta
$response.candidates[0].content.parts[0].text