from dotenv import load_dotenv
load_dotenv()
import sys
sys.path.insert(0, '.')
from tools.spotify_tool import get_artist_overview, get_top_tracks

print("=== Testing get_artist_overview ===")
result = get_artist_overview("Dua Lipa")
for key, value in result.items():
    print(f"{key}: {value}")

print()
print("=== Testing get_top_tracks ===")
tracks = get_top_tracks(result["artist_id"])
for t in tracks:
    print(f"  {t['name']} — popularity: {t['popularity']}")
