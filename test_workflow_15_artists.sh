#!/bin/bash
# test_workflow_15_artists.sh
# Tests the full n8n workflow with 15 artists sequentially
# Each artist waits for completion before the next starts
#
# Usage: bash test_workflow_15_artists.sh
# Make sure n8n workflow is ACTIVATED before running

WEBHOOK="https://daria-b.n8n.irn.hk/webhook/ar-triage"
DELAY=20  # seconds between artists -- allows full pipeline to complete

echo "================================================"
echo "A&R Agent — Batch Test: 15 Artists"
echo "Delay between artists: ${DELAY}s"
echo "Total estimated time: $((15 * DELAY / 60)) minutes"
echo "================================================"
echo ""

test_artist() {
    local name=$1
    local genre=$2
    local expected=$3

    echo "► Testing: $name ($genre) — expected: $expected"

    response=$(curl -s -X POST "$WEBHOOK" \
        -H "Content-Type: application/json" \
        -d "{\"artist_name\": \"$name\", \"genre\": \"$genre\"}")

    decision=$(echo "$response" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('decision', 'ERROR'))
except:
    print('ERROR')
" 2>/dev/null)

    score=$(echo "$response" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('score', 0))
except:
    print(0)
" 2>/dev/null)

    if [ "$decision" = "$expected" ]; then
        echo "  ✓ $decision ($score/100)"
    else
        echo "  ✗ Got $decision ($score/100), expected $expected"
    fi
    echo ""

    sleep $DELAY
}

echo "--- EXPECTED SIGN ---"
test_artist "Fisher" "electronic" "SIGN"
test_artist "Bicep" "electronic" "SIGN"
test_artist "Four Tet" "electronic" "SIGN"

echo "--- EXPECTED WATCH ---"
test_artist "Rema" "afrobeats" "WATCH"
test_artist "Arlo Parks" "indie-pop" "WATCH"
test_artist "FKJ" "electronic" "WATCH"

echo "--- EXPECTED PASS (major label) ---"
test_artist "Dua Lipa" "pop" "PASS"
test_artist "Drake" "hip-hop" "PASS"
test_artist "Taylor Swift" "pop" "PASS"
test_artist "Ed Sheeran" "pop" "PASS"
test_artist "Billie Eilish" "pop" "PASS"

echo "--- EXPECTED PASS (low signals) ---"
test_artist "Gengahr" "indie" "PASS"
test_artist "bdrmm" "indie" "PASS"
test_artist "Nilufer Yanya" "indie" "PASS"
test_artist "Lime Cordiale" "indie-pop" "PASS"

echo "================================================"
echo "Batch test complete!"
echo "Check Google Sheets — all 15 rows should be filled"
echo "Check Slack — SIGN and WATCH alerts should have arrived"
echo "================================================"
