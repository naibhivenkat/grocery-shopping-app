"""Read-only deployment checks; never registers users or creates transactions.

Public checks prove availability/response contracts, not business journeys.
Protected checks prove authentication boundaries, not authenticated success.
"""
import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def check(base, method, path, expected):
    data = b'{}' if method in {'POST', 'PUT', 'PATCH'} else None
    req = Request(base + path, data=data, method=method,
                  headers={'Content-Type':'application/json'})
    try:
        with urlopen(req, timeout=30) as response:
            status, body = response.status, response.read()
    except HTTPError as error:
        status, body = error.code, error.read()
    except (URLError, TimeoutError) as error:
        return {'method':method, 'path':path, 'ok':False, 'status':0,
                'expected':expected, 'error':type(error).__name__}
    try:
        parsed = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        parsed = None
    result = {'method':method, 'path':path, 'status':status,
              'expected':expected, 'ok':status==expected and parsed is not None}
    if path == '/features' and status == 200:
        result['features'] = parsed
        result['ok'] = result['ok'] and parsed.get('wallet_enabled') is False and parsed.get('backend_contract_version') == 2
    if isinstance(parsed, list):
        result['count'] = len(parsed)
    return result


def cases(release):
    result=[('GET','/health',200), ('GET','/',200), ('GET','/cities',200),
            ('GET','/shops',200), ('GET','/shops/categories',200),
            ('GET','/subscriptions/plans',200), ('GET','/ai/summary',200),
            ('GET','/services/available',200)]
    if release:
        result += [('GET','/features',200), ('GET','/promotions',200)]
    # Scan only functions carrying an authentication/role decorator. No tokens
    # are supplied, so each handler must stop before reading or writing data.
    for source in (Path(__file__).resolve().parents[1] / 'routes').glob('*.py'):
        text=source.read_text()
        for match in re.finditer(r'''@(\w+)\.(get|post|put|patch|delete)\(["']([^"'\n]+)["']\)\n((?:@[^\n]+\n)*)def ''',text):
            _, method, path, decorators=match.groups()
            if not re.search(r'@require_(auth|role)',decorators):
                continue
            if path.startswith(('/wallet','/service-wallet')):
                if release: result.append((method.upper(),path,410))
                continue
            path=re.sub(r'<(?:[^:>]+:)?[^>]+>','__verification__',path)
            result.append((method.upper(),path,401))
    if release:
        result += [('GET','/debug/smoke-test',404), ('GET','/wallet',410),
                   ('POST','/wallet/refund',410)]
    return list(dict.fromkeys(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',default='https://grocery-backend-956424262985.asia-south1.run.app')
    parser.add_argument('--phase',choices=['baseline','release'],default='release')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    release=args.phase=='release'
    if release:
        feature=check(args.base_url.rstrip('/'),'GET','/features',200)
        if not feature['ok']:
            print(json.dumps({'ok':False,'blocked':'Backend contract v2 is not deployed','features_check':feature},indent=2))
            sys.exit(1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda c:check(args.base_url.rstrip('/'),*c),cases(release)))
    report={'checked_at':datetime.now(timezone.utc).isoformat(),'base_url':args.base_url,
            'phase':args.phase,'ok':all(r['ok'] for r in results),
            'passed':sum(r['ok'] for r in results),'total':len(results),'results':results,
            'boundary':'Public availability and unauthenticated access only; authenticated business/provider journeys are separate.'}
    output=json.dumps(report,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(output+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='results'},indent=2))
    print(json.dumps([r for r in results if not r['ok']],indent=2))
    sys.exit(0 if report['ok'] else 1)
