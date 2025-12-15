"""
Flask server for Santa's Route Whisperer API
Wraps agent.py to provide REST endpoints for the frontend
"""
from flask import Flask, jsonify, request
from flask_cors import CORS
import asyncio
import random

# Import from agent.py
from agent import (
    CITY_COORDINATES, 
    SANTA_STOPS, 
    calculate_risk_score, 
    merge_route_and_weather,
    get_mock_routing_data,
    USE_MOCK_DATA
)

app = Flask(__name__)
CORS(app, origins="*", supports_credentials=True)  # Enable CORS for all origins

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# Available cities for selection
AVAILABLE_CITIES = [
    {"id": "nyc", "name": "New York, NY, USA", "shortName": "New York", "lat": 40.7128, "lng": -74.0060},
    {"id": "london", "name": "London, UK", "shortName": "London", "lat": 51.5074, "lng": -0.1278},
    {"id": "tokyo", "name": "Tokyo, Japan", "shortName": "Tokyo", "lat": 35.6762, "lng": 139.6503},
    {"id": "dubai", "name": "Dubai, UAE", "shortName": "Dubai", "lat": 25.2048, "lng": 55.2708},
    {"id": "sydney", "name": "Sydney, Australia", "shortName": "Sydney", "lat": -33.8688, "lng": 151.2093},
    {"id": "saopaulo", "name": "São Paulo, Brazil", "shortName": "São Paulo", "lat": -23.5505, "lng": -46.6333},
    {"id": "paris", "name": "Paris, France", "shortName": "Paris", "lat": 48.8566, "lng": 2.3522},
    {"id": "moscow", "name": "Moscow, Russia", "shortName": "Moscow", "lat": 55.7558, "lng": 37.6173},
    {"id": "beijing", "name": "Beijing, China", "shortName": "Beijing", "lat": 39.9042, "lng": 116.4074},
    {"id": "mumbai", "name": "Mumbai, India", "shortName": "Mumbai", "lat": 19.0760, "lng": 72.8777},
    {"id": "cairo", "name": "Cairo, Egypt", "shortName": "Cairo", "lat": 30.0444, "lng": 31.2357},
    {"id": "capetown", "name": "Cape Town, South Africa", "shortName": "Cape Town", "lat": -33.9249, "lng": 18.4241},
]

# Approximate distances between cities (km) - for demo purposes
CITY_DISTANCES = {
    ("New York, NY, USA", "London, UK"): 5571,
    ("London, UK", "Tokyo, Japan"): 9588,
    ("Tokyo, Japan", "Dubai, UAE"): 7779,
    ("Dubai, UAE", "Sydney, Australia"): 12051,
    ("Sydney, Australia", "São Paulo, Brazil"): 13553,
    ("São Paulo, Brazil", "New York, NY, USA"): 7688,
    ("Paris, France", "London, UK"): 344,
    ("Moscow, Russia", "Beijing, China"): 5794,
    ("Mumbai, India", "Dubai, UAE"): 1933,
    ("Cairo, Egypt", "Cape Town, South Africa"): 7245,
    # Add more as needed - will use haversine formula as fallback
}

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two points using Haversine formula"""
    import math
    R = 6371  # Earth's radius in km
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c

def get_distance(origin, destination):
    """Get distance between two cities"""
    # Try direct lookup
    key = (origin, destination)
    reverse_key = (destination, origin)
    
    if key in CITY_DISTANCES:
        return CITY_DISTANCES[key]
    if reverse_key in CITY_DISTANCES:
        return CITY_DISTANCES[reverse_key]
    
    # Fallback to haversine calculation
    origin_city = next((c for c in AVAILABLE_CITIES if c['name'] == origin), None)
    dest_city = next((c for c in AVAILABLE_CITIES if c['name'] == destination), None)
    
    if origin_city and dest_city:
        return haversine_distance(
            origin_city['lat'], origin_city['lng'],
            dest_city['lat'], dest_city['lng']
        )
    
    return 5000  # Default fallback

def generate_mock_weather(city_name):
    """Generate realistic mock weather data for a city"""
    # Weather presets based on typical conditions
    weather_presets = {
        "New York": {"temp": 2, "precip": 45, "wind": 28, "code": 3, "condition": "Partly Cloudy"},
        "London": {"temp": 6, "precip": 75, "wind": 42, "code": 61, "condition": "Light Rain"},
        "Tokyo": {"temp": 12, "precip": 20, "wind": 18, "code": 2, "condition": "Clear"},
        "Dubai": {"temp": 28, "precip": 5, "wind": 22, "code": 0, "condition": "Clear Sky"},
        "Sydney": {"temp": 26, "precip": 35, "wind": 30, "code": 3, "condition": "Scattered Clouds"},
        "São Paulo": {"temp": 24, "precip": 65, "wind": 15, "code": 80, "condition": "Rain Showers"},
        "Paris": {"temp": 8, "precip": 55, "wind": 25, "code": 45, "condition": "Foggy"},
        "Moscow": {"temp": -8, "precip": 80, "wind": 35, "code": 73, "condition": "Heavy Snow"},
        "Beijing": {"temp": 0, "precip": 30, "wind": 45, "code": 71, "condition": "Light Snow"},
        "Mumbai": {"temp": 30, "precip": 10, "wind": 12, "code": 1, "condition": "Mostly Clear"},
        "Cairo": {"temp": 22, "precip": 2, "wind": 20, "code": 0, "condition": "Clear Sky"},
        "Cape Town": {"temp": 24, "precip": 15, "wind": 38, "code": 2, "condition": "Few Clouds"},
    }
    
    # Get base weather or generate random
    short_name = city_name.split(",")[0].strip()
    base = weather_presets.get(short_name, {
        "temp": random.randint(-5, 30),
        "precip": random.randint(0, 100),
        "wind": random.randint(5, 60),
        "code": random.choice([0, 1, 2, 3, 45, 61, 71, 73, 80]),
        "condition": random.choice(["Clear", "Cloudy", "Rain", "Snow", "Windy"])
    })
    
    # Add some randomness
    return {
        "location": city_name,
        "temperature_celsius": base["temp"] + random.randint(-3, 3),
        "precipitation_probability": max(0, min(100, base["precip"] + random.randint(-10, 10))),
        "wind_speed_kmh": max(0, base["wind"] + random.randint(-5, 10)),
        "weather_code": base["code"],
        "condition": base["condition"]
    }

def get_weather_icon(condition, code):
    """Get weather emoji based on condition"""
    condition_lower = condition.lower()
    if "snow" in condition_lower or code in range(71, 78) or code in [85, 86]:
        return "🌨️"
    if "rain" in condition_lower or "shower" in condition_lower or code in [61, 63, 65, 80, 81, 82]:
        return "🌧️"
    if "thunder" in condition_lower or "storm" in condition_lower or code in [95, 96, 99]:
        return "⛈️"
    if "fog" in condition_lower or code in [45, 48]:
        return "🌫️"
    if "cloud" in condition_lower or code in [2, 3]:
        return "☁️"
    if "wind" in condition_lower:
        return "💨"
    return "☀️"

@app.route('/api/cities', methods=['GET'])
def get_cities():
    """Return list of available cities"""
    return jsonify(AVAILABLE_CITIES)

@app.route('/api/optimize', methods=['POST'])
def optimize_route():
    """
    Optimize route for selected cities
    Body: { "cities": ["nyc", "london", "tokyo", ...] }
    """
    data = request.get_json()
    city_ids = data.get('cities', [])
    
    if len(city_ids) < 2:
        return jsonify({"error": "Please select at least 2 cities"}), 400
    
    # Get full city objects
    selected_cities = []
    for city_id in city_ids:
        city = next((c for c in AVAILABLE_CITIES if c['id'] == city_id), None)
        if city:
            selected_cities.append(city)
    
    if len(selected_cities) < 2:
        return jsonify({"error": "Invalid city selection"}), 400
    
    # Build route legs
    legs = []
    for i in range(len(selected_cities) - 1):
        origin = selected_cities[i]
        destination = selected_cities[i + 1]
        
        # Get distance
        distance_km = get_distance(origin['name'], destination['name'])
        
        # Calculate duration (assuming ~800 km/h average for Santa's sleigh)
        duration_seconds = (distance_km / 800) * 3600
        
        legs.append({
            "origin": origin['name'],
            "destination": destination['name'],
            "distance_km": round(distance_km, 2),
            "duration_seconds": round(duration_seconds)
        })
    
    # Get weather for each destination
    destination_cities = [c['name'] for c in selected_cities[1:]]
    weather_data = [generate_mock_weather(city) for city in destination_cities]
    
    # Merge route with weather and calculate risks
    result = merge_route_and_weather(legs, weather_data)
    
    # Transform for frontend
    response = {
        "summary": result['route_summary'],
        "cities": [
            {
                "name": c['shortName'],
                "fullName": c['name'],
                "lat": c['lat'],
                "lng": c['lng']
            }
            for c in selected_cities
        ],
        "legs": []
    }
    
    # Build leg data for frontend
    for i, leg in enumerate(result['legs']):
        from_city = selected_cities[i]
        to_city = selected_cities[i + 1]
        
        weather = leg['weather']
        risk_color = {"red": "#ef4444", "yellow": "#f59e0b", "green": "#10b981"}[leg['risk_color']]
        
        response["legs"].append({
            "from": {
                "name": from_city['shortName'],
                "lat": from_city['lat'],
                "lng": from_city['lng']
            },
            "to": {
                "name": to_city['shortName'],
                "lat": to_city['lat'],
                "lng": to_city['lng']
            },
            "distance": round(leg['distance_miles']),
            "baseETA": round(leg['base_eta_hours'], 1),
            "adjustedETA": round(leg['adjusted_eta_hours'], 1),
            "risk": leg['risk_level'],
            "riskColor": risk_color,
            "weather": {
                "icon": get_weather_icon(weather['condition'], weather['weather_code']),
                "condition": weather['condition'],
                "temp": weather['temperature_celsius'],
                "wind": weather['wind_speed_kmh'],
                "precip": weather['precipitation_probability']
            }
        })
    
    return jsonify(response)

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok", "service": "santa-route-api"})

if __name__ == '__main__':
    print("🎅 Santa's Route API Starting...")
    print("   Available endpoints:")
    print("   GET  /api/cities  - Get available cities")
    print("   POST /api/optimize - Optimize route for selected cities")
    print("   GET  /health - Health check")
    print()
    app.run(host='0.0.0.0', debug=True, port=5001)

