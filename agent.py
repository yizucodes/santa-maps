import asyncio
import json
import os

# Optional imports - only needed when running the agent
try:
    from dedalus_labs import AsyncDedalus, DedalusRunner
    from dotenv import load_dotenv
    load_dotenv()
except (ImportError, PermissionError):
    # Allow importing for testing without these dependencies
    pass

# Step 3.1: Define Santa's Stops
SANTA_STOPS = [
    "New York, NY, USA",
    "London, UK",
    "Tokyo, Japan",
    "Dubai, UAE",
    "Sydney, Australia",
    "São Paulo, Brazil"
]

# Step 3.3: Risk Scoring Logic
def calculate_risk_score(weather_data):
    """
    Calculate risk level and multiplier based on weather conditions.
    
    Risk thresholds:
    - Precipitation > 70%: HIGH risk, 1.30x multiplier
    - Wind speed > 40 km/h: MEDIUM risk, 1.15x multiplier
    - Snow/ice (codes 71-77, 85-86): HIGH risk, 1.40x multiplier
    - Multiple conditions: use highest multiplier
    - Clear conditions: LOW risk, 1.0x multiplier
    """
    risk_level = "LOW"
    risk_color = "green"
    risk_multiplier = 1.0
    risk_factors = []
    
    # Extract weather values (handle different response formats)
    precip_prob = weather_data.get('precipitation_probability', 0)
    wind_speed = weather_data.get('wind_speed_kmh', 0)
    weather_code = weather_data.get('weather_code', 0)
    
    # Check for snow/ice conditions (highest priority)
    snow_codes = list(range(71, 78)) + [85, 86]
    if weather_code in snow_codes:
        risk_level = "HIGH"
        risk_color = "red"
        risk_multiplier = max(risk_multiplier, 1.40)
        risk_factors.append("Snow/ice conditions")
    
    # Check precipitation probability
    if precip_prob > 70:
        risk_level = "HIGH"
        risk_color = "red"
        risk_multiplier = max(risk_multiplier, 1.30)
        risk_factors.append(f"High precipitation ({precip_prob}%)")
    
    # Check wind speed
    if wind_speed > 40:
        if risk_level != "HIGH":
            risk_level = "MEDIUM"
            risk_color = "yellow"
        risk_multiplier = max(risk_multiplier, 1.15)
        risk_factors.append(f"High winds ({wind_speed} km/h)")
    
    # If no significant risks found
    if risk_multiplier == 1.0:
        risk_factors.append("Clear conditions")
    
    return {
        "risk_level": risk_level,
        "risk_color": risk_color,
        "risk_multiplier": risk_multiplier,
        "risk_factors": risk_factors
    }

# Step 3.5: Build Data Merge Function
def merge_route_and_weather(legs_data, weather_data_list):
    """
    Merge routing data with weather data and calculate adjusted ETAs.
    
    Returns structured route with risk assessments.
    """
    merged_legs = []
    
    for i, (leg, weather) in enumerate(zip(legs_data, weather_data_list)):
        # Calculate risk
        risk_info = calculate_risk_score(weather)
        
        # Get base values
        distance_km = leg.get('distance_km', 0)
        distance_miles = distance_km * 0.621371  # Convert to miles
        base_duration_seconds = leg.get('duration_seconds', 0)
        base_eta_hours = base_duration_seconds / 3600
        
        # Apply risk multiplier
        adjusted_duration_seconds = base_duration_seconds * risk_info['risk_multiplier']
        adjusted_eta_hours = adjusted_duration_seconds / 3600
        delay_hours = adjusted_eta_hours - base_eta_hours
        
        # Build leg object
        leg_obj = {
            "leg_number": i + 1,
            "from": leg.get('origin'),
            "to": leg.get('destination'),
            "distance_km": round(distance_km, 2),
            "distance_miles": round(distance_miles, 2),
            "base_duration_seconds": base_duration_seconds,
            "base_eta_hours": round(base_eta_hours, 2),
            "weather": {
                "location": leg.get('destination'),
                "condition": weather.get('condition', 'Unknown'),
                "precipitation_probability": weather.get('precipitation_probability', 0),
                "wind_speed_kmh": weather.get('wind_speed_kmh', 0),
                "temperature_celsius": weather.get('temperature_celsius', 0),
                "weather_code": weather.get('weather_code', 0)
            },
            "risk_level": risk_info['risk_level'],
            "risk_color": risk_info['risk_color'],
            "risk_multiplier": risk_info['risk_multiplier'],
            "risk_factors": risk_info['risk_factors'],
            "adjusted_duration_seconds": round(adjusted_duration_seconds),
            "adjusted_eta_hours": round(adjusted_eta_hours, 2),
            "delay_hours": round(delay_hours, 2)
        }
        
        merged_legs.append(leg_obj)
    
    # Calculate summary
    total_distance_miles = sum(leg['distance_miles'] for leg in merged_legs)
    total_base_eta = sum(leg['base_eta_hours'] for leg in merged_legs)
    total_adjusted_eta = sum(leg['adjusted_eta_hours'] for leg in merged_legs)
    total_delay = total_adjusted_eta - total_base_eta
    
    high_risk_count = sum(1 for leg in merged_legs if leg['risk_level'] == 'HIGH')
    medium_risk_count = sum(1 for leg in merged_legs if leg['risk_level'] == 'MEDIUM')
    low_risk_count = sum(1 for leg in merged_legs if leg['risk_level'] == 'LOW')
    
    # Determine overall risk
    if high_risk_count >= 2:
        overall_risk = "HIGH"
    elif high_risk_count >= 1 or medium_risk_count >= 3:
        overall_risk = "MEDIUM"
    else:
        overall_risk = "LOW"
    
    return {
        "route_summary": {
            "total_distance_miles": round(total_distance_miles, 2),
            "total_base_eta_hours": round(total_base_eta, 2),
            "total_adjusted_eta_hours": round(total_adjusted_eta, 2),
            "total_delay_hours": round(total_delay, 2),
            "high_risk_legs": high_risk_count,
            "medium_risk_legs": medium_risk_count,
            "low_risk_legs": low_risk_count,
            "overall_risk": overall_risk
        },
        "legs": merged_legs
    }

# Step 3.2 & 3.4: Build Agent Workflow with MCP Integration
async def optimize_santa_route():
    """
    Main agent workflow that:
    1. Takes Santa's stops
    2. Calls Google Maps MCP for routing between consecutive cities
    3. Calls Open-Meteo MCP for weather at each destination
    4. Calculates risk scores and adjusts ETAs
    5. Returns comprehensive route plan
    """
    client = AsyncDedalus()
    runner = DedalusRunner(client)
    
    print("🎅 Starting Santa's Route Optimization...")
    print(f"📍 Planning route through {len(SANTA_STOPS)} cities")
    print(f"   Route: {' → '.join(SANTA_STOPS)}\n")
    
    # Build the agent prompt
    prompt = f"""You are Santa's logistics AI assistant. Optimize the delivery route with weather risk analysis.

SANTA'S STOPS (in order):
{json.dumps(SANTA_STOPS, indent=2)}

YOUR TASK:
1. For each consecutive pair of cities, get routing information:
   - Use the Google Maps tools to get directions/distance/duration
   - Extract: distance in kilometers, duration in seconds
   
2. For each destination city, get weather forecast:
   - Use the Open-Meteo tools to get weather forecast
   - Get: temperature, precipitation probability, wind speed, weather code
   
3. Provide the data in a structured format for each leg:
   Leg 1: {SANTA_STOPS[0]} → {SANTA_STOPS[1]}
   Leg 2: {SANTA_STOPS[1]} → {SANTA_STOPS[2]}
   And so on for all legs.

IMPORTANT:
- Call the routing tool for EACH consecutive pair of cities
- Call the weather tool for EACH destination city
- Provide all numerical data (distance, duration, precipitation %, wind speed, temperature)
- Use the tools available to you - don't make up data

Please execute this plan and provide structured results."""

    print("🤖 Agent is calling MCP servers...")
    print("   - Google Maps MCP for routing")
    print("   - Open-Meteo MCP for weather forecasts\n")
    
    # Run agent with both MCP servers
    result = await runner.run(
        input=prompt,
        model="openai/gpt-4o",
        mcp_servers=[
            "yizucodes/mcp-google-map",      # Google Maps MCP
            "cathy-di/open-meteo-mcp"      # Open-Meteo MCP
        ]
    )
    
    print("✅ Agent completed!\n")
    print("=" * 80)
    print("RAW AGENT OUTPUT:")
    print("=" * 80)
    print(result.final_output)
    print("=" * 80)
    
    return result.final_output

async def main():
    """
    Main entry point - runs the optimization and displays results.
    """
    try:
        result = await optimize_santa_route()
        
        print("\n🎄 Santa's Route Optimization Complete!")
        print("\nNext steps:")
        print("- Review the routing and weather data above")
        print("- The data can be structured into the format shown in Phase 3.5")
        print("- Ready for UI integration in Phase 4")
        
    except Exception as e:
        print(f"\n❌ Error during optimization: {e}")
        print("\nTroubleshooting:")
        print("- Check that both MCP servers are accessible")
        print("- Verify API keys are set in .env file")
        print("- Check internet connection")
        raise

if __name__ == "__main__":
    asyncio.run(main())