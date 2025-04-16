import io, os, time, base64, asyncio, json
from io import BytesIO
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Tuple, Union
from features.mcp.google_maps.location_intelligence import start_location_intelligence
import asyncio
import aiohttp
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
load_dotenv()

app = FastAPI()

# Models
class BusinessQuery(BaseModel):
    industry: str = Field(..., description="The industry sector of the business")
    product: List[str] = Field(..., description="Products or services offered by the business")
    location_city: List[str] = Field(..., alias="location/city", description="Geographic locations or cities of operation")
    budget: Tuple[int, int] = Field(..., description="Budget range in currency format (min, max)")
    size: str = Field(..., description="Size classification of the business")
    unique_selling_proposition: Optional[str] = Field(None, description="Key differentiators or unique value propositions")
    
    model_config = {
        "validate_by_name": True,
        "json_schema_extra": {
            "example": {
                "industry": "Food and Beverage",
                "product": ["Coffee", "Tea", "Pastries"],
                "location/city": ["Manhattan, New York"],
                "budget": [120000, 300000],
                "size": "Small Enterprise",
                "unique_selling_proposition": "High Quality, Organic, Locally Sourced Ingredients"
            }
        }
    }

class Competitor(BaseModel):
    name: str
    industry: str
    address: str
    size: str
    revenue: str
    market_share: str
    unique_selling_proposition: str
    growth_score: int
    customer_satisfaction_score: int
    reviews: List[str]
    rating: float

class Location(BaseModel):
    area: str
    city: str
    state: str
    population_density: str
    cost_of_living: str
    business_climate: str
    quality_of_life: str
    infrastructure: str
    suitability_score: int
    risk_score: int
    advantages: List[str]
    challenges: List[str]

class LocationIntelligenceResponse(BaseModel):
    locations: List[Location]
    competitors: List[Competitor]
    
async def async_send_to_api(session, api, data):
    """Send data to the API asynchronously and return the response"""
    try:
        async with session.post(f"{API_URL}/{api}", json=data, timeout=180) as response:
            response.raise_for_status()
            return await response.json()
    except Exception as e:
        return {"error": str(e)}
    
def run_async_calls(api_calls):
    """Run multiple API calls asynchronously"""
    results = {}
    
    async def fetch_all():
        async with aiohttp.ClientSession() as session:
            tasks = []
            for api_name, api_endpoint, api_data in api_calls:
                task = asyncio.create_task(async_send_to_api(session, api_endpoint, api_data))
                tasks.append((api_name, task))
            
            # Wait for all tasks to complete
            for api_name, task in tasks:
                try:
                    results[api_name] = await task
                except Exception as e:
                    results[api_name] = {"error": str(e)}
    
    # Run the async event loop in a separate thread
    with ThreadPoolExecutor() as executor:
        future = executor.submit(asyncio.run, fetch_all())
        future.result()  # Wait for completion
        
    return results

# API Endpoints    

# Root endpoint to check if the server is running 
@app.get("/")
def read_root():
    return "Welcome to the Venture-Scope API!"

# Health check endpoint to verify the server status
@app.get("/health")
def health_check():
    return {"status": "ok"}

# Endpoint to analyze location intelligence based on business query
@app.post("/location_intelligence", response_model=LocationIntelligenceResponse)
async def location_intelligence(query: BusinessQuery):
    try:
        # Format the query for agent processing
        formatted_query = {
            "industry": query.industry,
            "product": ", ".join(query.product),
            "location/city": ", ".join(query.location_city),
            "budget": f"{query.budget[0]} - {query.budget[1]}",
            "size": query.size,
            "unique_selling_proposition": query.unique_selling_proposition or ""
        }
        
        # Run the location intelligence pipeline
        result = await start_location_intelligence(formatted_query)
        
        # Validate the response has the expected structure
        if not isinstance(result, dict) or "locations" not in result or "competitors" not in result:
            raise ValueError("Invalid response structure from location intelligence pipeline")
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing location intelligence: {str(e)}")

import openai
import traceback
from pinecone import Pinecone
from fastapi import HTTPException
from services.vectordb_expertchat import query_pinecone
from pydantic import BaseModel

class ExpertChatRequest(BaseModel):
    expert_key: str
    namespace: str
    question: str
    model: str = "gpt-4o-mini"

@app.post("/chat_with_expert")
def chat_with_expert(request: ExpertChatRequest):
    try:
        print(f"[INFO] Incoming Chat Request:\n - Expert: {request.expert_key}\n - Namespace: {request.namespace}\n - Question: {request.question}")

        # Fetch relevant context from Pinecone
        matches = query_pinecone(request.question, namespace=request.namespace, top_k=7)
        print(f"[INFO] Matches retrieved: {len(matches)}")

        if not matches:
            return {
                "answer": f"📄 I couldn't find any relevant information from {request.expert_key.title()}'s material to answer your question. Try asking something more related to their expertise."
            }

        # Extract and structure context
        context_chunks = [m["metadata"]["text"] for m in matches if "text" in m.get("metadata", {})]
        context = "\n\n".join(context_chunks)

        # Expert role prompt
        expert_name = request.expert_key.replace('_', ' ').title()
        system_prompt = f"""
            You are {expert_name}, a renowned expert in your field. You are known for your authentic voice and sharp, insightful communication.

            Your task is to respond ONLY using insights, philosophies, and ideas that can be found in the material provided below.

            If the user’s question cannot be answered based on this material, kindly reply with:  
            “I’m sorry, but I can only respond based on the documented insights and material provided.”

            --- Begin Reference Material ---
            {context}
            --- End Reference Material ---

            Always respond in the tone and style of {expert_name}, making it feel like they are personally responding.
            """.strip()
         
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request.question}
        ]

        print(f"[INFO] Sending request to OpenAI with {len(messages)} messages...")
        response = openai.chat.completions.create(
            model=request.model,
            messages=messages
        )
        print("[INFO] Received response from OpenAI.")

        answer = response.choices[0].message.content.strip()
        return {"answer": answer}

    except Exception as e:
        print("[ERROR] Exception occurred during expert chat:")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Chat failed: {str(e)}")
