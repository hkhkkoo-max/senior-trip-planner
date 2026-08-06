import json, sys
sys.stdout.reconfigure(encoding='utf-8')
trips = json.load(open('trips.json', 'r', encoding='utf-8'))
latest = sorted(trips.values(), key=lambda x: x.get('createdAt',''))[-1]
lots = latest['output']['routePlan'].get('parkingLots', [])
print('=== 주차장 목록 ===')
for i, lot in enumerate(lots):
    print(i, lot['name'], '/', lot['feeInfo'])
ev = latest['output']['routePlan'].get('evChargingStation')
print('=== EV 충전소 ===')
print(ev)
