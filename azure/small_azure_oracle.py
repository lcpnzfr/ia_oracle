import requests  
  
# Configuration  
endpoint_url = "https://lcpnz-morcz1sn-eastus2.cognitiveservices.azure.com/openai/deployments/gpt-4o/chat/completions?api-version=2025-01-01-preview"  
api_key = "Fa8HqCRkONrTEfhgLjTr9mkrG91hT4iqihcCO1QwoCzlKGNoMVGyJQQJ99CEACYeBjFXJ3w3AAAAACOGa81s"  # Replace with your actual API key  
  
# Headers  
headers = {  
    "Content-Type": "application/json",  
    "Authorization": f"Bearer {api_key}"  
}  
  
# Request Payload  
payload = {  
    "messages": [  
        {"role": "system", "content": "You are a helpful assistant."},  
        {"role": "user", "content": "What are the benefits of using Azure Cognitive Services for AI?"}  
    ],  
    "max_tokens": 150,  # Increased response length  
    "temperature": 0.5,  # Reduced randomness for more focused responses  
    "top_p": 1.0,  # Full diversity  
    "frequency_penalty": 0.5,  # Penalize frequent words for more varied responses  
    "presence_penalty": 0.6  # Encourage exploration of new topics  
}  
  
# Make the API request  
response = requests.post(endpoint_url, headers=headers, json=payload)  
  
# Check the response  
if response.status_code == 200:  
    result = response.json()  
    print("Response:", result)  
else:  
    print("Error:", response.status_code, response.text)  