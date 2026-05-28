import asyncio
import json
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Any, Callable, AsyncGenerator
from enum import Enum
import requests


class ModelBackend(Enum):
    OLLAMA = "ollama"
    VLLM = "vllm"
    LM_STUDIO = "lm_studio"
    OPENAI = "openai"


class ModelAdapter:
    def __init__(self, backend: ModelBackend, base_url: str = "http://localhost", port: int = 11434):
        self.backend = backend
        self.base_url = base_url
        self.port = port
        self.api_url = f"{base_url}:{port}"
        self._available_models = None
        self._default_model = None

    async def list_models(self) -> List[str]:
        try:
            if self.backend == ModelBackend.OLLAMA:
                response = requests.get(f"{self.api_url}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    return [model["name"] for model in data.get("models", [])]
            
            elif self.backend == ModelBackend.VLLM:
                response = requests.get(f"{self.api_url}/v1/models")
                if response.status_code == 200:
                    data = response.json()
                    return [model["id"] for model in data.get("data", [])]
            
            elif self.backend == ModelBackend.LM_STUDIO:
                response = requests.get(f"{self.api_url}/v1/models")
                if response.status_code == 200:
                    data = response.json()
                    return [model["id"] for model in data.get("data", [])]
            
            elif self.backend == ModelBackend.OPENAI:
                response = requests.get(f"{self.api_url}/v1/models")
                if response.status_code == 200:
                    data = response.json()
                    return [model["id"] for model in data.get("data", [])]
        except Exception as e:
            print(f"Failed to list models: {e}")
        
        return []

    async def generate(self, prompt: str, model: Optional[str] = None, 
                      max_tokens: int = 512, temperature: float = 0.7,
                      stream: bool = False) -> Dict[str, Any]:
        model = model or self._default_model
        
        if self.backend == ModelBackend.OLLAMA:
            return await self._ollama_generate(prompt, model, max_tokens, temperature, stream)
        
        elif self.backend == ModelBackend.VLLM:
            return await self._vllm_generate(prompt, model, max_tokens, temperature, stream)
        
        elif self.backend == ModelBackend.LM_STUDIO:
            return await self._lm_studio_generate(prompt, model, max_tokens, temperature, stream)
        
        elif self.backend == ModelBackend.OPENAI:
            return await self._openai_generate(prompt, model, max_tokens, temperature, stream)
        
        return {"error": "Unsupported backend"}

    async def generate_stream(self, prompt: str, model: Optional[str] = None,
                             max_tokens: int = 512, temperature: float = 0.7) -> AsyncGenerator[str, None]:
        model = model or self._default_model
        
        if self.backend == ModelBackend.OLLAMA:
            async for chunk in self._ollama_generate_stream(prompt, model, max_tokens, temperature):
                yield chunk
        
        elif self.backend == ModelBackend.VLLM:
            async for chunk in self._vllm_generate_stream(prompt, model, max_tokens, temperature):
                yield chunk
        
        elif self.backend == ModelBackend.LM_STUDIO:
            async for chunk in self._lm_studio_generate_stream(prompt, model, max_tokens, temperature):
                yield chunk
        
        elif self.backend == ModelBackend.OPENAI:
            async for chunk in self._openai_generate_stream(prompt, model, max_tokens, temperature):
                yield chunk

    async def _ollama_generate(self, prompt: str, model: str, max_tokens: int, temperature: float, stream: bool):
        try:
            data = {
                "model": model,
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": False
            }
            
            response = requests.post(f"{self.api_url}/api/generate", json=data)
            if response.status_code == 200:
                result = response.json()
                return {"response": result.get("response", ""), "model": model}
        except Exception as e:
            return {"error": str(e)}

    async def _ollama_generate_stream(self, prompt: str, model: str, max_tokens: int, temperature: float):
        try:
            data = {
                "model": model,
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": True
            }
            
            response = requests.post(f"{self.api_url}/api/generate", json=data, stream=True)
            response.raise_for_status()
            
            for line in response.iter_lines():
                if line:
                    line_data = json.loads(line.decode())
                    if "response" in line_data:
                        yield line_data["response"]
                    if line_data.get("done"):
                        break
        except Exception as e:
            yield f"[Error: {e}]"

    async def _vllm_generate(self, prompt: str, model: str, max_tokens: int, temperature: float, stream: bool):
        try:
            headers = {"Content-Type": "application/json"}
            data = {
                "model": model,
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": False
            }
            
            response = requests.post(f"{self.api_url}/v1/completions", json=data, headers=headers)
            if response.status_code == 200:
                result = response.json()
                return {"response": result["choices"][0]["text"], "model": model}
        except Exception as e:
            return {"error": str(e)}

    async def _vllm_generate_stream(self, prompt: str, model: str, max_tokens: int, temperature: float):
        try:
            headers = {"Content-Type": "application/json"}
            data = {
                "model": model,
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": True
            }
            
            response = requests.post(f"{self.api_url}/v1/completions", json=data, headers=headers, stream=True)
            response.raise_for_status()
            
            for line in response.iter_lines():
                if line:
                    line_str = line.decode()
                    if line_str.startswith("data: "):
                        line_data = json.loads(line_str[6:])
                        if line_data.get("choices"):
                            text = line_data["choices"][0].get("text", "")
                            yield text
        except Exception as e:
            yield f"[Error: {e}]"

    async def _lm_studio_generate(self, prompt: str, model: str, max_tokens: int, temperature: float, stream: bool):
        try:
            headers = {"Content-Type": "application/json"}
            data = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": False
            }
            
            response = requests.post(f"{self.api_url}/v1/chat/completions", json=data, headers=headers)
            if response.status_code == 200:
                result = response.json()
                return {"response": result["choices"][0]["message"]["content"], "model": model}
        except Exception as e:
            return {"error": str(e)}

    async def _lm_studio_generate_stream(self, prompt: str, model: str, max_tokens: int, temperature: float):
        try:
            headers = {"Content-Type": "application/json"}
            data = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": True
            }
            
            response = requests.post(f"{self.api_url}/v1/chat/completions", json=data, headers=headers, stream=True)
            response.raise_for_status()
            
            for line in response.iter_lines():
                if line:
                    line_str = line.decode()
                    if line_str.startswith("data: "):
                        line_data = json.loads(line_str[6:])
                        if line_data.get("choices"):
                            delta = line_data["choices"][0].get("delta", {})
                            text = delta.get("content", "")
                            yield text
        except Exception as e:
            yield f"[Error: {e}]"

    async def _openai_generate(self, prompt: str, model: str, max_tokens: int, temperature: float, stream: bool):
        try:
            headers = {"Content-Type": "application/json"}
            data = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": False
            }
            
            response = requests.post(f"{self.api_url}/v1/chat/completions", json=data, headers=headers)
            if response.status_code == 200:
                result = response.json()
                return {"response": result["choices"][0]["message"]["content"], "model": model}
        except Exception as e:
            return {"error": str(e)}

    async def _openai_generate_stream(self, prompt: str, model: str, max_tokens: int, temperature: float):
        try:
            headers = {"Content-Type": "application/json"}
            data = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": True
            }
            
            response = requests.post(f"{self.api_url}/v1/chat/completions", json=data, headers=headers, stream=True)
            response.raise_for_status()
            
            for line in response.iter_lines():
                if line:
                    line_str = line.decode()
                    if line_str.startswith("data: "):
                        if line_str == "data: [DONE]":
                            break
                        line_data = json.loads(line_str[6:])
                        if line_data.get("choices"):
                            delta = line_data["choices"][0].get("delta", {})
                            text = delta.get("content", "")
                            yield text
        except Exception as e:
            yield f"[Error: {e}]"

    async def embeddings(self, text: str, model: Optional[str] = None) -> List[float]:
        try:
            if self.backend == ModelBackend.OLLAMA:
                response = requests.post(f"{self.api_url}/api/embeddings", json={
                    "model": model or self._default_model,
                    "prompt": text
                })
                if response.status_code == 200:
                    result = response.json()
                    return result.get("embedding", [])
            
            elif self.backend in [ModelBackend.VLLM, ModelBackend.LM_STUDIO, ModelBackend.OPENAI]:
                headers = {"Content-Type": "application/json"}
                response = requests.post(f"{self.api_url}/v1/embeddings", json={
                    "model": model or self._default_model,
                    "input": text
                }, headers=headers)
                if response.status_code == 200:
                    result = response.json()
                    return result["data"][0]["embedding"]
        except Exception as e:
            print(f"Failed to get embeddings: {e}")
        
        return []

    async def health_check(self) -> bool:
        try:
            if self.backend == ModelBackend.OLLAMA:
                response = requests.get(f"{self.api_url}/api/tags", timeout=5)
                return response.status_code == 200
            else:
                response = requests.get(f"{self.api_url}/v1/models", timeout=5)
                return response.status_code == 200
        except:
            return False

    async def pull_model(self, model_name: str) -> bool:
        if self.backend == ModelBackend.OLLAMA:
            try:
                response = requests.post(f"{self.api_url}/api/pull", json={"name": model_name}, stream=True)
                response.raise_for_status()
                
                for line in response.iter_lines():
                    if line:
                        data = json.loads(line.decode())
                        status = data.get("status", "")
                        if status == "success":
                            return True
                return False
            except Exception as e:
                print(f"Failed to pull model: {e}")
                return False
        
        return False

    def set_default_model(self, model_name: str):
        self._default_model = model_name

    async def get_model_info(self, model_name: str) -> Optional[Dict]:
        if self.backend == ModelBackend.OLLAMA:
            models = await self.list_models()
            if model_name in models:
                return {"name": model_name, "backend": self.backend.value}
        return None
