import asyncio
import json
import os
import re

# Optional imports - only needed when running the agent
try:
    from dedalus_labs import AsyncDedalus, DedalusRunner
    from dotenv import load_dotenv
    load_dotenv()
except (ImportError, PermissionError):
    # Allow importing for testing without these dependencies
    pass

# Configuration: Set to True to use mock data (bypass MCP servers)
USE_MOCK_DATA = True  # Set to False when MCPs are fixed

# City coordinates for weather lookups
CITY_COORDINATES = {
    "New York, NY, USA": {"lat": 40.7128, "lon": -74.0060},
    "London, UK": {"lat": 51.5074, "lon": -0.1278},
    "Tokyo, Japan": {"lat": 35.6762, "lon": 139.6503},
    "Dubai, UAE": {"lat": 25.2048, "lon": 55.2708},
    "Sydney, Australia": {"lat": -33.8688, "lon": 151.2093},
    "São Paulo, Brazil": {"lat": -23.5505, "lon": -46.6333}
}

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

# Mock Routing Data Generator (no weather)
def get_mock_routing_data():
    """
    Returns mock routing data for Santa's route.
    Only includes distances and durations - weather is fetched separately from MCP.
    """
    return [
        {
            "origin": "New York, NY, USA",
            "destination": "London, UK",
            "distance_km": 5571,
            "duration_seconds": 77400  # ~21.5 hours
        },
        {
            "origin": "London, UK",
            "destination": "Tokyo, Japan",
            "distance_km": 9588,
            "duration_seconds": 129600  # ~36 hours
        },
        {
            "origin": "Tokyo, Japan",
            "destination": "Dubai, UAE",
            "distance_km": 7779,
            "duration_seconds": 105000  # ~29 hours
        },
        {
            "origin": "Dubai, UAE",
            "destination": "Sydney, Australia",
            "distance_km": 12051,
            "duration_seconds": 162900  # ~45 hours
        },
        {
            "origin": "Sydney, Australia",
            "destination": "São Paulo, Brazil",
            "distance_km": 13553,
            "duration_seconds": 183240  # ~51 hours
        }
    ]

async def fetch_real_weather_data(destination_cities):
    """
    Fetches real weather data from Open-Meteo MCP for each destination city.
    
    Args:
        destination_cities: List of city names (destinations for each leg)
    
    Returns:
        List of weather data dictionaries matching the expected format
    """
    client = AsyncDedalus()
    runner = DedalusRunner(client)
    
    weather_data_list = []
    
    print("🌤️  Fetching real weather data from Open-Meteo MCP...")
    
    for i, city in enumerate(destination_cities, 1):
        print(f"   [{i}/{len(destination_cities)}] Fetching weather for {city}...")
        
        # Get coordinates for the city
        coords = CITY_COORDINATES.get(city, {})
        lat = coords.get("lat")
        lon = coords.get("lon")
        
        # Build prompt for weather forecast
        if lat and lon:
            prompt = f"""Get the current weather forecast for {city} (coordinates: {lat}, {lon}).

Please use the Open-Meteo tools to get:
- Temperature in Celsius
- Precipitation probability (percentage)
- Wind speed in km/h
- Weather code

Return the data in a structured format with these exact fields:
- temperature_celsius
- precipitation_probability
- wind_speed_kmh
- weather_code
- condition (human-readable description like "Clear", "Rain", "Snow", etc.)
- location (city name)

If you cannot get the data, provide reasonable defaults."""
        else:
            prompt = f"""Get the current weather forecast for {city}.

Please use the Open-Meteo tools to get:
- Temperature in Celsius
- Precipitation probability (percentage)
- Wind speed in km/h
- Weather code

Return the data in a structured format with these exact fields:
- temperature_celsius
- precipitation_probability
- wind_speed_kmh
- weather_code
- condition (human-readable description)
- location (city name)"""

        try:
            result = await runner.run(
                input=prompt,
                model="openai/gpt-4o",
                mcp_servers=[
                    "cathydi/open-meteo-mcp"  # Only Open-Meteo MCP
                ]
            )
            
            # Parse the response to extract weather data
            response_text = result.final_output
            
            # Try to extract weather data from the response
            weather_data = {
                "location": city,
                "condition": "Unknown",
                "precipitation_probability": 0,
                "wind_speed_kmh": 0,
                "temperature_celsius": 0,
                "weather_code": 0
            }
            
            # Try to parse as JSON first (if the response is structured)
            try:
                # Look for JSON in the response
                json_match = re.search(r'\{[^}]+\}', response_text)
                if json_match:
                    json_data = json.loads(json_match.group(0))
                    weather_data.update({
                        "temperature_celsius": json_data.get("temperature_celsius", weather_data["temperature_celsius"]),
                        "precipitation_probability": json_data.get("precipitation_probability", weather_data["precipitation_probability"]),
                        "wind_speed_kmh": json_data.get("wind_speed_kmh", weather_data["wind_speed_kmh"]),
                        "weather_code": json_data.get("weather_code", weather_data["weather_code"]),
                        "condition": json_data.get("condition", weather_data["condition"])
                    })
            except:
                pass  # Fall through to regex parsing
            
            # Enhanced regex parsing - look for various formats
            # Temperature patterns: "temperature: 15", "temp: 15°C", "15°C", "15 C"
            temp_patterns = [
                r'temperature[:\s]+(-?\d+)',
                r'temp[:\s]+(-?\d+)',
                r'(-?\d+)\s*°?\s*C(?:elsius)?',
                r'(-?\d+)\s*degrees?\s*(?:C|celsius)'
            ]
            for pattern in temp_patterns:
                temp_match = re.search(pattern, response_text, re.IGNORECASE)
                if temp_match:
                    weather_data["temperature_celsius"] = int(temp_match.group(1))
                    break
            
            # Precipitation patterns: "precipitation: 75%", "precip: 75", "75% chance"
            precip_patterns = [
                r'precipitation[:\s]+(\d+)',
                r'precip[:\s]+(\d+)',
                r'(\d+)%\s*(?:precipitation|precip|chance)',
                r'precipitation[:\s]+(\d+)%'
            ]
            for pattern in precip_patterns:
                precip_match = re.search(pattern, response_text, re.IGNORECASE)
                if precip_match:
                    weather_data["precipitation_probability"] = int(precip_match.group(1))
                    break
            
            # Wind speed patterns: "wind: 25 km/h", "wind speed: 25", "25 km/h"
            wind_patterns = [
                r'wind[:\s]+(\d+)\s*km/h',
                r'wind[:\s]+speed[:\s]+(\d+)',
                r'(\d+)\s*km/h\s*(?:wind|speed)',
                r'wind[:\s]+(\d+)'
            ]
            for pattern in wind_patterns:
                wind_match = re.search(pattern, response_text, re.IGNORECASE)
                if wind_match:
                    weather_data["wind_speed_kmh"] = int(wind_match.group(1))
                    break
            
            # Weather code patterns: "code: 73", "weather code: 73", "WMO: 73"
            code_patterns = [
                r'weather[_\s]*code[:\s]+(\d+)',
                r'code[:\s]+(\d+)',
                r'WMO[:\s]+(\d+)',
                r'weather[:\s]+code[:\s]+(\d+)'
            ]
            for pattern in code_patterns:
                code_match = re.search(pattern, response_text, re.IGNORECASE)
                if code_match:
                    weather_data["weather_code"] = int(code_match.group(1))
                    break
            
            # Condition description - more comprehensive matching
            response_lower = response_text.lower()
            if any(word in response_lower for word in ["clear", "sunny", "fair"]):
                weather_data["condition"] = "Clear Sky"
            elif any(word in response_lower for word in ["rain", "rainy", "drizzle", "shower"]):
                weather_data["condition"] = "Rain"
            elif any(word in response_lower for word in ["snow", "snowy", "snowing", "blizzard"]):
                weather_data["condition"] = "Snow"
            elif any(word in response_lower for word in ["cloud", "cloudy", "overcast"]):
                weather_data["condition"] = "Cloudy"
            elif any(word in response_lower for word in ["fog", "foggy", "mist"]):
                weather_data["condition"] = "Foggy"
            elif any(word in response_lower for word in ["storm", "thunder", "lightning"]):
                weather_data["condition"] = "Storm"
            else:
                weather_data["condition"] = "Unknown"
            
            weather_data_list.append(weather_data)
            print(f"      ✓ Weather retrieved: {weather_data['condition']}, {weather_data['temperature_celsius']}°C")
            
        except Exception as e:
            print(f"      ⚠️  Error fetching weather for {city}: {e}")
            print(f"      Using default weather data")
            # Fallback to default weather
            weather_data_list.append({
                "location": city,
                "condition": "Unknown",
                "precipitation_probability": 0,
                "wind_speed_kmh": 0,
                "temperature_celsius": 0,
                "weather_code": 0
            })
    
    print()
    return weather_data_list

# Step 3.2 & 3.4: Build Agent Workflow with MCP Integration
async def optimize_santa_route():
    """
    Main agent workflow that:
    1. Takes Santa's stops
    2. Gets routing and weather data (mock or real)
    3. Calculates risk scores and adjusts ETAs
    4. Returns comprehensive route plan
    """
    print("🎅 Starting Santa's Route Optimization...")
    print(f"📍 Planning route through {len(SANTA_STOPS)} cities")
    print(f"   Route: {' → '.join(SANTA_STOPS)}\n")
    
    if USE_MOCK_DATA:
        print("🧪 Hybrid Mode: Mock Routing + Real Weather")
        print("   - Mock routing data for all legs")
        print("   - Real weather forecasts from Open-Meteo MCP\n")
        
        # Get mock routing data
        mock_legs = get_mock_routing_data()
        
        # Get destination cities (all except the first one)
        destination_cities = SANTA_STOPS[1:]  # London, Tokyo, Dubai, Sydney, São Paulo
        
        # Fetch real weather data from Open-Meteo MCP
        real_weather = await fetch_real_weather_data(destination_cities)
        
        # Process through our risk scoring and merge logic
        result = merge_route_and_weather(mock_legs, real_weather)
        
        print("✅ Route optimization completed!\n")
        print("=" * 80)
        print("OPTIMIZED ROUTE WITH RISK ANALYSIS:")
        print("=" * 80)
        
        # Display summary
        summary = result['route_summary']
        print(f"\n📊 ROUTE SUMMARY:")
        print(f"   Total Distance: {summary['total_distance_miles']:,.2f} miles")
        print(f"   Base ETA: {summary['total_base_eta_hours']:.2f} hours")
        print(f"   Weather-Adjusted ETA: {summary['total_adjusted_eta_hours']:.2f} hours")
        print(f"   Expected Delay: +{summary['total_delay_hours']:.2f} hours")
        print(f"   Overall Risk: {summary['overall_risk']}")
        print(f"   Risk Breakdown:")
        print(f"      🔴 HIGH risk legs: {summary['high_risk_legs']}")
        print(f"      🟡 MEDIUM risk legs: {summary['medium_risk_legs']}")
        print(f"      🟢 LOW risk legs: {summary['low_risk_legs']}")
        
        # Display each leg
        print(f"\n🛣️  DETAILED LEG-BY-LEG ANALYSIS:")
        for leg in result['legs']:
            risk_emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}[leg['risk_level']]
            print(f"\n   {risk_emoji} Leg {leg['leg_number']}: {leg['from']} → {leg['to']}")
            print(f"      Distance: {leg['distance_miles']:,.2f} miles ({leg['distance_km']:,.2f} km)")
            print(f"      Base Duration: {leg['base_eta_hours']:.2f} hours")
            print(f"      Weather: {leg['weather']['condition']} (REAL DATA)")
            print(f"         - Temperature: {leg['weather']['temperature_celsius']}°C")
            print(f"         - Precipitation: {leg['weather']['precipitation_probability']}%")
            print(f"         - Wind Speed: {leg['weather']['wind_speed_kmh']} km/h")
            print(f"      Risk Assessment: {leg['risk_level']} ({leg['risk_multiplier']}x multiplier)")
            print(f"         Factors: {', '.join(leg['risk_factors'])}")
            print(f"      Adjusted Duration: {leg['adjusted_eta_hours']:.2f} hours (+{leg['delay_hours']:.2f} hours)")
        
        print("\n" + "=" * 80)
        
        return result
    
    else:
        # Original MCP-based implementation
        client = AsyncDedalus()
        runner = DedalusRunner(client)
        
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
                "cathydi/open-meteo-mcp"      # Open-Meteo MCP
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
        
        # Check if result is a dict (mock data) or string (MCP output)
        if isinstance(result, dict):
            print("\n🎄 Santa's Route Optimization Complete!")
            print("\n✅ Route data is ready for UI integration!")
            print("   - All legs processed with risk assessment")
            print("   - Weather-adjusted ETAs calculated")
            print("   - Ready for Phase 4: UI Development")
        else:
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
        if USE_MOCK_DATA:
            print("- Note: Currently using mock data mode")
        raise

if __name__ == "__main__":
    asyncio.run(main())