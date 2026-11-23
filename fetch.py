"""Download 2026 results from CivicAPI for every ballot measure and party race listed in data/.

Responses are cached in cache/<race id>.json, so a rerun only asks for what is missing. Pass --refresh to
download everything again (results are unofficial and still changing until states certify).

CivicAPI (https://civicapi.org) is a free public API. Requests go one at a time with a short pause between them,
since it answers parallel requests with errors.
"""
import argparse
import csv
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

API = 'https://civicapi.org/api/v2/race/{}'
ROOT = Path(__file__).parent
CACHE = ROOT / 'cache'
PAUSE_SECONDS = 0.4


def race_ids():
    ids = []
    for name in ('measures.csv', 'party_races.csv'):
        with open(ROOT / 'data' / name, newline='') as fh:
            ids += [row['civic_race_id'] for row in csv.DictReader(fh)]
    return sorted(set(ids), key=int)


def fetch(race_id, attempts=3):
    request = urllib.request.Request(API.format(race_id), headers={'User-Agent': 'ballot-measures-2026 analysis'})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if attempt == attempts - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == attempts - 1:
                raise
        time.sleep(2 * (attempt + 1))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--refresh', action='store_true', help='download every race again')
    args = parser.parse_args()
    CACHE.mkdir(exist_ok=True)
    ids = race_ids()
    missing = []
    for n, race_id in enumerate(ids, 1):
        path = CACHE / f'{race_id}.json'
        if path.exists() and not args.refresh:
            continue
        data = fetch(race_id)
        if data is None:
            missing.append(race_id)
        else:
            path.write_text(json.dumps(data))
        print(f'\r{n}/{len(ids)}', end='', flush=True)
        time.sleep(PAUSE_SECONDS)
    print(f'\n{len(ids) - len(missing)} races cached in {CACHE.name}/', f'(not found: {", ".join(missing)})' if missing else '')


if __name__ == '__main__':
    main()
