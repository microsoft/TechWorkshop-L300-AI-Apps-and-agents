import time
from utils.log_utils import log_timing

def call_fallback(llm_client, fallback_prompt: str, gpt_deployment = "gpt-5-mini"):
    """Call the fallback model and return its reply."""
    start_time = time.time()
    
    chat_prompt = [    
        {
            "role": "system",      
            "content": 
            [           
                {               
                    "type": "text",               
                    "text": fallback_prompt           
                }       
            ]   
        }]

    messages = chat_prompt
    completion = llm_client.chat.completions.create(
        model=gpt_deployment,
        messages=messages,
        temperature=0.7,
        stream=False)
    result = completion.choices[0].message.content
    log_timing("Fallback Call", start_time, f"Model: {gpt_deployment}")
    return result

def cora_fallback(llm_client, fallback_prompt: str, gpt_deployment = "Phi-4"):
    """Call the fallback model for cora and return its reply."""
    start_time = time.time()
    
    chat_prompt = [    
        {
            "role": "system",      
            "content": 
            [           
                {               
                    "type": "text",               
                    "text": fallback_prompt           
                }       
            ]   
        }]

    messages = chat_prompt
    completion = llm_client.chat.completions.create(
        model=gpt_deployment,
        messages=messages,
        temperature=0.7,
        top_p=0.95,
        frequency_penalty=0,
        presence_penalty=0,
        stop=None,
        stream=False)
    result = completion.choices[0].message.content
    log_timing("Cora Fallback Call", start_time, f"Model: {gpt_deployment}")
    return result