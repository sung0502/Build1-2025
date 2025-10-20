# core/llm.py
"""
LLM wrapper for TimeBuddy using Google GenAI SDK.
Provides simple interface for generation and classification.
"""
import json
from typing import Any, Optional
from google import genai
from google.genai import types


class LLM:
    """Wrapper around Google GenAI client for TimeBuddy."""
    
    def __init__(self, api_key: str, model_name: str = "gemini-flash-lite-latest"):
        """
        Initialize LLM client.
        
        Args:
            api_key: Google AI API key
            model_name: Model to use (default: gemini-flash-lite-latest)
        """
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
    
    def generate(
        self,
        system_instruction: str,
        prompt: str,
        temperature: float = 0.4,
        max_tokens: int = 1024
    ) -> str:
        """
        Generate text response.
        
        Args:
            system_instruction: System-level instructions
            prompt: User prompt
            temperature: Sampling temperature
            max_tokens: Maximum output tokens
            
        Returns:
            Generated text
        """
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=config,
        )
        
        return response.text if response.text else ""
    
    def classify_json(
        self,
        system_instruction: str,
        prompt: str,
        schema_hint: Optional[str] = None
    ) -> Any:
        """
        Generate JSON response and parse to Python object.
        
        Args:
            system_instruction: System-level instructions
            prompt: User prompt
            schema_hint: Optional hint about expected JSON structure
            
        Returns:
            Parsed Python object (dict/list) or None if parsing fails
        """
        full_prompt = prompt
        if schema_hint:
            full_prompt = f"{prompt}\n\nExpected JSON format: {schema_hint}"
        
        # Use lower temperature for classification
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.2,
            max_output_tokens=512,
        )
        
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=full_prompt,
                config=config,
            )
            
            if not response.text:
                return None
            
            # Try to extract JSON from response
            text = response.text.strip()
            
            # Remove markdown code fences if present
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
                text = text.replace("```json", "").replace("```", "").strip()
            
            return json.loads(text)
            
        except json.JSONDecodeError:
            return None
        except Exception:
            return None
