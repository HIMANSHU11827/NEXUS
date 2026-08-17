import os
import time

import requests


def test_remote_speed():
    url = os.environ.get("NEXUS_SPEED_TEST_URL", "http://127.0.0.1:11434/api/generate")
    model = os.environ.get("NEXUS_SPEED_TEST_MODEL", "llama3.2")
    prompt = "Tell me a short story about an AI living in a cloud in 50 words."
    
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False
    }
    
    print(f">>> Sending request to Cloud Model ({model})...")
    start_time = time.time()
    
    try:
        response = requests.post(url, json=payload, timeout=60)
        end_time = time.time()
        
        if response.status_code == 200:
            data = response.json()
            reply = data.get("response", "")
            duration = end_time - start_time
            
            # Estimate tokens (approx 4 chars per token)
            token_count = len(reply) / 4
            tps = token_count / duration
            
            print("\n" + "="*50)
            print(f"✅ SUCCESS! Response received in {duration:.2f} seconds.")
            print(f"📊 Estimated Speed: {tps:.2f} tokens per second.")
            print(f"🤖 REPLY: {reply[:100]}...")
            print("="*50 + "\n")
        else:
            print(f"❌ Error {response.status_code}: {response.text}")
    except Exception as e:
        print(f"❌ Connection Failed: {str(e)}")

if __name__ == "__main__":
    test_remote_speed()
