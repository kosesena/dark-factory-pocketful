#!/usr/bin/env python3
"""Specification-derived HTTP probes. Standard library only; destructive test resets.

BASE_URL=http://127.0.0.1:18765 python3 probes/run.py
--include-known executes documented failures too (and exits nonzero).
No shipped check or application module is imported. No export/credential is persisted.
"""
# Reproduced against 3ca8d961ce2c0738e0661bc51752e305d50940b2.
# Every skip prints FAIL ... KNOWN_OPEN SKIPPED; --include-known reruns these.
# R009 flags an invented signup restriction; see the verdict's interpretation notes.
KNOWN_OPEN = frozenset({
    'R009', 'R016', 'R027', 'R036',
    'R057', 'R058', 'R067', 'R068', 'R077', 'R078',
    'R087', 'R088', 'R097', 'R098',
    'R109', 'R110', 'R111', 'R112', 'R113',
})

import concurrent.futures
import copy
import datetime
import json
import os
import re
import signal
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get('BASE_URL', '').rstrip('/')
TESTS = []
TOKENS = {}
SERIAL = 0
ABSENT = object()
PASSWORD = 'correct horse'
NAMES = ('ada', 'bob', 'cy', 'dee', 'eve')


def requirement(rid, title, quote, risk=2, source='common.py / server.py'):
    def decorate(fn):
        TESTS.append(dict(id=rid, title=title, quote=quote, risk=risk,
                          source=source, scenario=(fn.__doc__ or title).strip(), fn=fn))
        return fn
    return decorate


def eq(actual, expected, context=''):
    assert actual == expected, '%s expected %r; got %r' % (context, expected, actual)


def key():
    global SERIAL
    SERIAL += 1
    return 'probe-%d' % SERIAL


def http(method, path, body=ABSENT, user=None, idem=ABSENT, raw=None,
         auth=ABSENT, base=None):
    headers = {'Content-Type': 'application/json; charset=utf-8'}
    if auth is not ABSENT:
        headers['Authorization'] = auth
    elif user is not None:
        headers['Authorization'] = 'Bearer ' + TOKENS.get(user, user)
    if idem is not ABSENT:
        headers['Idempotency-Key'] = idem
    data = raw if raw is not None else (None if body is ABSENT else json.dumps(body, ensure_ascii=True).encode())
    req = urllib.request.Request((base or BASE) + path, data=data, method=method, headers=headers)
    start = time.monotonic()
    timeout = 10 if path.startswith('/_test/') else 5
    try:
        response = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        data = response.read()
        status = response.status
        content_type = response.headers.get('Content-Type', '').lower()
    assert time.monotonic() - start < timeout, 'request exceeded timeout: ' + path
    assert status < 500, '%s %s returned %d: %r' % (method, path[:100], status, data[:200])
    if status == 204:
        eq(data, b'', '204 must have no content')
        return status, None
    assert 'application/json' in content_type and 'charset=utf-8' in content_type.replace(' ', ''), content_type
    value = json.loads(data.decode('utf-8'))
    if status >= 400:
        assert isinstance(value, dict) and isinstance(value.get('error'), dict), value
        assert isinstance(value['error'].get('code'), str), value
        assert isinstance(value['error'].get('message'), str) and value['error']['message'], value
    return status, value


def ok(method, path, body=ABSENT, user=None, idem=ABSENT, status=200, **kw):
    s, b = http(method, path, body, user, idem, **kw)
    eq(s, status, method + ' ' + path[:100] + ' response ' + repr(b)[:180])
    return b


def error(method, path, body, status, code, user=None, idem=ABSENT, **kw):
    s, b = http(method, path, body, user, idem, **kw)
    eq((s, b.get('error', {}).get('code')), (status, code), path[:100] + ' ' + repr(body)[:120])
    return b


def fixture(balances=None, currency='EUR', minor=2):
    balances = balances if balances is not None else [10000, 2500, 0, 0, 0]
    return dict(currency=currency, minor_units=minor,
                users=[dict(id='u_' + name, email=name + '@example.com', password=PASSWORD,
                            display_name=name.title(), handle=name, balance=balance)
                       for name, balance in zip(NAMES, balances)], payments=[], requests=[],
                settlement_operator_ids=['u_ada'])


def reset(fix=None):
    TOKENS.clear()
    ok('POST', '/_test/reset', fixture() if fix is None else fix, status=204)
    for name in NAMES:
        b = ok('POST', '/auth/login', {'email': name + '@example.com', 'password': PASSWORD})
        TOKENS[name] = b['token']


def me(name):
    return ok('GET', '/me', user=name)


def balances():
    return [me(name)['balance'] for name in NAMES]


def feed(name='ada', query='?limit=200'):
    return ok('GET', '/activity' + query, user=name)['payments']


def requests(name='ada', query='?limit=200'):
    return ok('GET', '/requests' + query, user=name)['requests']


def payment(frm='ada', to='bob', amount=10, **fields):
    return ok('POST', '/payments', dict(to_handle=to, amount=amount, **fields), frm, key(), 201)


def request(frm='ada', payer='bob', amount=10, **fields):
    return ok('POST', '/requests', dict(payer_handle=payer, amount=amount, **fields), frm, key(), 201)


def pay(r, user='bob', body=None, idem=None):
    return ok('POST', '/requests/' + r['request_id'] + '/pay', {} if body is None else body,
              user, idem or key(), 201)


def transfer(frm='ada', to='bob', amount=10, **fields):
    return dict(from_handle=frm, to_handle=to, amount=amount, **fields)


def settlement(entries, user='ada', idem=None):
    return ok('POST', '/settlements', {'transfers': entries}, user, idem or key(), 201)


def split(amount=10, participants=None, user='ada', **fields):
    return ok('POST', '/splits', dict(amount=amount, participant_handles=participants or ['ada', 'bob', 'cy'], **fields),
              user, key(), 201)


def snapshot():
    return ok('GET', '/_test/export')


def unchanged(before):
    eq(snapshot(), before, 'failed request must leave full exported state unchanged')


def race(functions):
    gate = threading.Barrier(len(functions))
    def call(fn):
        gate.wait(timeout=5)
        return fn()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(functions)) as pool:
        return list(pool.map(call, functions))


def stamp(value):
    assert isinstance(value, str) and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)', value), value
    assert datetime.datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is not None


def identifier(value):
    assert isinstance(value, str) and 1 <= len(value) <= 64, value


def receipt(p, frm, to, amount, request_id=None, settlement_id=None):
    expected = dict(from_user_id='u_' + frm, from_handle=frm, to_user_id='u_' + to,
                    to_handle=to, amount=amount, currency=me(frm)['currency'],
                    request_id=request_id, settlement_id=settlement_id)
    for field, value in expected.items():
        eq(p.get(field, ABSENT), value, field)
    identifier(p['payment_id'])
    stamp(p['created_at'])


@requirement('R001', 'Health, JSON UTF-8, bounded HTTP responses',
             'GET /health  ->  200  {"status": "ok"}')
def health():
    eq(ok('GET', '/health'), {'status': 'ok'})


@requirement('R002', 'Fixture balances are already net; seeded credentials work',
             'Seeded users must be able to log in with the given password immediately.', source='store.py / auth.py')
def seed():
    """Reset with a seeded payment and pending request; log in and assert the supplied net balances and records."""
    f = fixture()
    f['payments'] = [dict(id='p_seed', from_user_id='u_ada', to_user_id='u_bob', amount=500, note='seed', visibility='public')]
    f['requests'] = [dict(id='r_seed', requester_id='u_bob', payer_id='u_ada', amount=200, note='taxi', status='pending')]
    reset(f)
    eq(balances(), [10000, 2500, 0, 0, 0])
    eq(feed()[0]['payment_id'], 'p_seed')
    eq(requests()[0]['request_id'], 'r_seed')


@requirement('R003', 'Reset replaces all records, keys, tokens and permissions',
             'Replace all service state with the fixture in the request body (§4).', 1, 'store.py / testctl.py')
def reset_replacement():
    reset()
    old = TOKENS['ada']
    b = {'to_handle': 'bob', 'amount': 1}
    ok('POST', '/payments', b, 'ada', 'old', 201)
    request()
    f = fixture()
    f['settlement_operator_ids'] = []
    reset(f)
    error('GET', '/me', ABSENT, 401, 'unauthenticated', auth='Bearer ' + old)
    eq(feed(), [])
    eq(requests(), [])
    eq(balances(), [10000, 2500, 0, 0, 0])
    ok('POST', '/payments', b, 'ada', 'old', 201)
    error('POST', '/settlements', {'transfers': [transfer()]}, 403, 'forbidden', 'ada', key())
    reset()
    eq(feed(), [])


@requirement('R004', 'Negative fixture balance rejects reset without changing state',
             'A `balance` below zero in a fixture is a reset error: return `422 validation_failed` from `POST /_test/reset` and change nothing.', 1, 'store.py')
def negative_reset():
    reset()
    payment()
    before = snapshot()
    f = fixture(); f['users'][2]['balance'] = -1
    error('POST', '/_test/reset', f, 422, 'validation_failed')
    unchanged(before)


@requirement('R005', 'One currency and exact minor units in all monetary receipts',
             'Every amount in the API is an integer count of its minor units: `1000` in a `minor_units: 2` service is €10.00, and `1000` in a `minor_units: 0` service is ¥1000.', source='store.py / ledger.py')
def currencies():
    for currency, minor in [('EUR', 2), ('JPY', 0), ('BHD', 3)]:
        reset(fixture(currency=currency, minor=minor))
        eq(me('ada'), dict(user_id='u_ada', display_name='Ada', handle='ada', balance=10000, currency=currency, minor_units=minor))
        p = payment(amount=1000); r = request(amount=1000); s = split(1000)
        for b in (p, r, s):
            eq(b['amount'], 1000); eq(b['currency'], currency)
        pay(r)
        eq(balances(), [10000, 2500, 0, 0, 0])


@requirement('R006', 'Signup derives immutable valid handle; starts at zero and can receive immediately',
             'take the local part, lowercase it, replace every character outside `[a-z0-9_]` with `_`, and truncate to 20 characters.', source='auth.py')
def signup_derived():
    reset()
    email = 'AB.C+dé_12345678901234567890@example.com'
    u = ok('POST', '/auth/signup', dict(email=email, password='12345678', display_name='新しい', handle='ignored'), status=201)
    identifier(u['user_id'])
    h = re.sub('[^a-z0-9_]', '_', email.split('@')[0].lower())[:20]
    TOKENS['new'] = u['token']
    eq(me('new')['handle'], h); eq(me('new')['balance'], 0)
    payment(to=h, amount=1)
    r = request(payer=h, amount=1)
    pay(r, 'new')
    eq(me('new')['handle'], h); eq(me('new')['balance'], 0)
    login = ok('POST', '/auth/login', dict(email=email, password='12345678'))
    eq(login['user_id'], u['user_id'])
    eq(login['display_name'], '新しい')


@requirement('R007', 'Signup rejects email and derived-handle collisions without creating accounts',
             'The handle derived from the email (§4) is already taken | 409 `handle_taken`, and no account is created', source='auth.py')
def signup_collisions():
    reset()
    before = snapshot()
    error('POST', '/auth/signup', dict(email='ada@example.com', password=PASSWORD, display_name='X'), 409, 'email_taken')
    error('POST', '/auth/signup', dict(email='ada@other.test', password=PASSWORD, display_name='X'), 409, 'handle_taken')
    error('POST', '/auth/login', dict(email='ada@other.test', password=PASSWORD), 401, 'unauthenticated')
    unchanged(before)
    email = 'A.B@example.com'
    ok('POST', '/auth/signup', dict(email=email, password=PASSWORD, display_name='X'), status=201)
    error('POST', '/auth/signup', dict(email='A+B@example.com', password=PASSWORD, display_name='X'), 409, 'handle_taken')
    prefix = 'abcdefghijklmnopqrst'
    ok('POST', '/auth/signup', dict(email=prefix+'a@a', password=PASSWORD, display_name='X'), status=201)
    error('POST', '/auth/signup', dict(email=prefix+'b@b', password=PASSWORD, display_name='X'), 409, 'handle_taken')


@requirement('R008', 'Signup password/email boundaries and required fields',
             'Password shorter than 8 characters | 422 `validation_failed`', source='auth.py')
def signup_validation():
    reset()
    valid = dict(email='fresh@domain', password='12345678', display_name='X')
    for field in valid:
        b = dict(valid); del b[field]
        error('POST', '/auth/signup', b, 422, 'validation_failed')
        for value in [None, True, 3, [], {}]:
            b = dict(valid); b[field] = value
            error('POST', '/auth/signup', b, 400, 'malformed_request')
    for email in ['', 'abc', '@domain', 'local@', 'a@b@c']:
        error('POST', '/auth/signup', dict(valid, email=email), 422, 'validation_failed')
    for password in ['', '1234567']:
        error('POST', '/auth/signup', dict(valid, password=password), 422, 'validation_failed')
    ok('POST', '/auth/signup', valid, status=201)


@requirement('R009', 'Signup does not invent a nonempty display-name rule',
             '{ "email": "a@example.com", "password": "correct horse", "display_name": "Ada" }', source='auth.py')
def empty_display_name():
    """Use a present string display_name of empty string; no specified rule limits this field's length."""
    reset()
    b = ok('POST', '/auth/signup', dict(email='fresh@domain', password=PASSWORD, display_name=''), status=201)
    eq(b['display_name'], '')


@requirement('R010', 'Login failures and multiple concurrent valid sessions',
             'Tokens do not expire. An account may have multiple valid tokens and concurrent sessions.', source='auth.py')
def login_sessions():
    reset()
    error('POST', '/auth/login', dict(email='ada@example.com', password='wrong'), 401, 'unauthenticated')
    error('POST', '/auth/login', dict(email='missing@example.com', password=PASSWORD), 401, 'unauthenticated')
    for b, status, code in [({}, 422, 'validation_failed'), ({'email': 1, 'password': PASSWORD}, 400, 'malformed_request'),
                            ({'email': 'ada@example.com', 'password': None}, 400, 'malformed_request')]:
        error('POST', '/auth/login', b, status, code)
    sessions = race([lambda: ok('POST', '/auth/login', dict(email='ada@example.com', password=PASSWORD)) for _ in range(10)])
    for s in sessions:
        eq(ok('GET', '/me', auth='Bearer ' + s['token'])['user_id'], 'u_ada')
    eq(me('ada')['user_id'], 'u_ada')


@requirement('R011', 'Every protected endpoint requires a valid bearer token',
             'Every other endpoint requires a bearer token, except `/health`, `/_test/reset` and the two above.', source='server.py / testctl.py')
def authentication():
    reset()
    paths = [('GET', p) for p in ['/me', '/activity', '/requests']] + [('POST', p) for p in
             ['/payments', '/requests', '/requests/missing/pay', '/requests/missing/cancel', '/requests/missing/decline', '/splits', '/settlements']]
    for method, path in paths:
        for auth in ['', 'Basic whatever', 'Bearer', 'Bearer unknown']:
            error(method, path, {} if method == 'POST' else ABSENT, 401, 'unauthenticated', auth=auth, idem=key())
    exported = snapshot()
    ok('POST', '/_test/import', exported, status=204)


@requirement('R012', 'Unknown body fields are ignored on every write',
             'Unknown fields in a request body are ignored, never an error.', source='all endpoint modules')
def unknown_fields():
    reset(dict(fixture(), ignored={'nested': [1, None]}))
    u = ok('POST', '/auth/signup', dict(email='new@domain', password=PASSWORD, display_name='N', ignored=[]), status=201)
    ok('POST', '/auth/login', dict(email='new@domain', password=PASSWORD, ignored={}))
    p = payment(ignored={'amount': False}); eq(p['amount'], 10)
    r = request(visibility='private', ignored=None)
    assert 'visibility' not in r
    p = pay(r, body={'ignored': 1}); eq(p['visibility'], 'public')
    for action, user in [('decline', 'bob'), ('cancel', 'ada')]:
        r = request()
        ok('POST', '/requests/' + r['request_id'] + '/' + action, {'ignored': 1}, user)
    split(ignored=True)
    ok('POST', '/settlements', dict(transfers=[transfer(ignored=[])], ignored={}), 'ada', key(), 201)
    exported = snapshot(); exported['ignored'] = 3
    ok('POST', '/_test/import', exported, status=204)


@requirement('R013', 'Unknown query parameters are ignored',
             'Unknown query parameters are ignored.', source='server.py / requests_api.py')
def unknown_queries():
    reset(); payment(); request()
    for path in ['/me', '/health', '/activity', '/requests', '/_test/export']:
        eq(ok('GET', path+'?unrecognised=%F0%9F%92%B0&foo=1', user='ada'), ok('GET', path, user='ada'))


@requirement('R014', 'Malformed JSON must fail on all body-taking write paths',
             '400 | `malformed_request` | Unparseable body, or a field of the wrong JSON type', 1, 'server.py / requests_api.py')
def malformed_bodies():
    reset()
    for path in ['/auth/login', '/auth/signup', '/_test/reset', '/_test/import', '/payments', '/requests', '/splits', '/settlements']:
        for raw in [b'{', b'null trailing', b'\xff', b'{"a": NaN}']:
            before = snapshot()
            error('POST', path, ABSENT, 400, 'malformed_request', 'ada', key(), raw=raw)
            unchanged(before)
    r = request()
    error('POST', '/requests/' + r['request_id'] + '/pay', ABSENT, 400, 'malformed_request', 'bob', key(), raw=b'{')


@requirement('R015', 'Non-object JSON bodies reject as malformed',
             'Reserve 400 `malformed_request` for a body that does not parse or a field of the wrong type.', source='server.py')
def nonobject_bodies():
    reset()
    for path in ['/auth/login', '/auth/signup', '/_test/reset', '/_test/import', '/payments', '/requests', '/splits', '/settlements']:
        for value in [None, [], True, 'text', 2]:
            error('POST', path, value, 400, 'malformed_request', 'ada', key())


@requirement('R016', 'Reset fields of the wrong JSON type return malformed_request',
             'Other wrong JSON types follow the rule below.', source='store.py / common.py')
def fixture_types():
    """Set currency to a number in an otherwise valid fixture: 400, unchanged state."""
    reset()
    before = snapshot()
    for field, value in [('currency', 3), ('minor_units', '2'), ('users', {}), ('payments', {}), ('requests', {}), ('settlement_operator_ids', {})]:
        f = fixture(); f[field] = value
        error('POST', '/_test/reset', f, 400, 'malformed_request')
        unchanged(before)


@requirement('R017', 'Amounts accept integral JSON numeric forms on every applicable write',
             'API amounts must have an integral numeric value: JSON `1000`, `1000.0` and `1e3` all represent the same valid minor-unit amount.', source='common.py')
def integral_amounts():
    for representation in ['1000', '1000.0', '1e3', '1.000e3', '1000000000']:
        reset(fixture([4000000000, 4000000000, 0, 0, 0]))
        for path, raw in [('/payments', '{"to_handle":"bob","amount":%s}'),
                          ('/requests', '{"payer_handle":"bob","amount":%s}'),
                          ('/splits', '{"participant_handles":["ada","bob"],"amount":%s}'),
                          ('/settlements', '{"transfers":[{"from_handle":"ada","to_handle":"bob","amount":%s}]}')]:
            b = ok('POST', path, user='ada', idem=key(), status=201, raw=(raw % representation).encode())
            actual = b['payments'][0]['amount'] if path == '/settlements' else b['amount']
            eq(actual, int(float(representation)))
            assert type(actual) is int


@requirement('R018', 'Invalid amounts always give 422, including booleans and strings',
             'Endpoint-specific field rules take precedence: invalid `amount` values (including strings and booleans), non-string `note` values (including `null`), and any `visibility` other than `public` or `private` are 422 `validation_failed`.', source='common.py')
def invalid_amounts():
    reset()
    for value in [0, -1, 1000000001, 1.5, '1', True, False, None, [], {}]:
        for path, b in [('/payments', dict(to_handle='bob', amount=value)),
                        ('/requests', dict(payer_handle='bob', amount=value)),
                        ('/splits', dict(participant_handles=['bob'], amount=value)),
                        ('/settlements', dict(transfers=[transfer(amount=value)]))]:
            before = snapshot()
            error('POST', path, b, 422, 'validation_failed', 'ada', key())
            unchanged(before)
    for raw in [b'{"to_handle":"bob","amount":1e1000}', b'{"to_handle":"bob","amount":1.00000000000000000000000000001}']:
        error('POST', '/payments', ABSENT, 422, 'validation_failed', 'ada', key(), raw=raw)


@requirement('R019', 'Notes default only when omitted; preserve Unicode verbatim through all paths',
             '`note` is stored and returned verbatim: no trimming, no escaping, no normalisation. Unicode and emoji survive a round trip byte for byte.', source='common.py / ledger.py')
def note_roundtrip():
    reset()
    note = '  e\u0301 é 💰 <script> & " \\ \n\t  '
    for n in ['', note, '💰'*200]:
        p = payment(note=n); eq(p['note'], n)
        eq(next(x for x in feed('bob') if x['payment_id'] == p['payment_id'])['note'], n)
        r = request(note=n); eq(r['note'], n)
        eq(pay(r)['note'], n)
        s = split(note=n); eq(s['note'], n)
        for row in s['requests']: eq(row['note'], n)
        eq(settlement([transfer(note=n)])['payments'][0]['note'], n)
    eq(payment()['note'], '')
    eq(request()['note'], '')
    eq(split()['note'], '')
    eq(settlement([transfer()])['payments'][0]['note'], '')


@requirement('R020', 'Note wrong types, null and length 201 reject with 422',
             'Endpoint-specific field rules take precedence: invalid `amount` values (including strings and booleans), non-string `note` values (including `null`), and any `visibility` other than `public` or `private` are 422 `validation_failed`.', source='common.py')
def invalid_notes():
    reset()
    for value in [None, True, 1, [], {}, 'x'*201, '💰'*201]:
        for path, b in [('/payments', dict(to_handle='bob', amount=1, note=value)),
                        ('/requests', dict(payer_handle='bob', amount=1, note=value)),
                        ('/splits', dict(participant_handles=['bob'], amount=1, note=value)),
                        ('/settlements', dict(transfers=[transfer(note=value)]))]:
            error('POST', path, b, 422, 'validation_failed', 'ada', key())


@requirement('R021', 'Visibility defaults to public only on omission and validates all other values',
             'any `visibility` other than `public` or `private` are 422 `validation_failed`. Omission alone selects the optional-field defaults.', source='common.py')
def visibility_validation():
    reset()
    r = request()
    for value in [None, True, False, 1, [], {}, '', 'PUBLIC', 'friends']:
        for path, b, user in [('/payments', dict(to_handle='bob', amount=1, visibility=value), 'ada'),
                              ('/requests/'+r['request_id']+'/pay', dict(visibility=value), 'bob'),
                              ('/settlements', dict(transfers=[transfer(visibility=value)]), 'ada')]:
            error('POST', path, b, 422, 'validation_failed', user, key())
    eq(payment()['visibility'], 'public')
    eq(pay(r)['visibility'], 'public')
    eq(settlement([transfer()])['payments'][0]['visibility'], 'public')


@requirement('R022', 'Missing required fields are 422; typed handles and split lists reject with 400',
             'A required field or query parameter is missing, or a stated rule is violated with no more specific code', source='ledger.py / splits.py')
def required_fields():
    reset()
    for path, template, fields in [('/payments', dict(to_handle='bob', amount=1), ['to_handle', 'amount']),
                                  ('/requests', dict(payer_handle='bob', amount=1), ['payer_handle', 'amount']),
                                  ('/splits', dict(participant_handles=['bob'], amount=1), ['participant_handles', 'amount'])]:
        for field in fields:
            b = dict(template); del b[field]
            error('POST', path, b, 422, 'validation_failed', 'ada', key())
        field = fields[0]
        for value in [None, True, 1, {}]:
            error('POST', path, dict(template, **{field: value}), 400, 'malformed_request', 'ada', key())
    error('POST', '/splits', dict(participant_handles=['bob', 1], amount=1), 400, 'malformed_request', 'ada', key())


@requirement('R023', 'Unknown recipients and self-transfers never move money',
             'Money moves only between existing wallets.', source='payments.py / requests_api.py / settlements.py')
def recipient_errors():
    reset()
    for path, b, status, code in [('/payments', dict(to_handle='absent', amount=1), 404, 'not_found'),
                                 ('/requests', dict(payer_handle='absent', amount=1), 404, 'not_found'),
                                 ('/payments', dict(to_handle='ada', amount=1), 422, 'self_payment'),
                                 ('/requests', dict(payer_handle='ada', amount=1), 422, 'self_request'),
                                 ('/settlements', dict(transfers=[transfer(to='absent')]), 404, 'not_found'),
                                 ('/settlements', dict(transfers=[transfer(to='ada')]), 422, 'self_payment')]:
        before = snapshot()
        error('POST', path, b, status, code, 'ada', key())
        unchanged(before)


@requirement('R024', 'Unassigned handle strings use endpoint-specific not_found',
             'A field of the correct JSON type with an invalid format or out-of-range value gives 422 `validation_failed`, unless an endpoint specifies a different error.', source='ledger.py / splits.py / settlements.py')
def handle_format():
    """Uppercase, punctuation and 21-character strings match no existing handle; apply the endpoint-specific unknown-handle 404 rule."""
    reset()
    for h in ['BOB', 'bad-handle', 'a'*21]:
        for path, body in [('/payments', dict(to_handle=h, amount=1)), ('/requests', dict(payer_handle=h, amount=1)),
                           ('/splits', dict(participant_handles=[h], amount=1)), ('/settlements', dict(transfers=[transfer(to=h)]))]:
            error('POST', path, body, 404, 'not_found', 'ada', key())


@requirement('R025', 'Payment receipt, exact balance movement and failed-payment atomicity',
             'The debit and the credit are one atomic step. A payment is never visible in one wallet and not the other, and a failed payment leaves no trace in either.', 1, 'payments.py / ledger.py / server.py')
def payment_atomic():
    reset()
    p = payment(amount=10000, visibility='private')
    receipt(p, 'ada', 'bob', 10000)
    eq(balances(), [0, 12500, 0, 0, 0])
    before = snapshot()
    error('POST', '/payments', dict(to_handle='bob', amount=1), 409, 'insufficient_funds', 'ada', key())
    unchanged(before)
    eq(feed('bob')[0], p)


@requirement('R026', 'Monetary arithmetic remains exact at the 2^53 boundary',
             'Monetary arithmetic must preserve exact minor-unit values without rounding error.', 1, 'ledger.py')
def exact_range():
    reset(fixture([2**53, 0, 0, 0, 0]))
    payment(amount=1)
    eq(balances(), [2**53-1, 1, 0, 0, 0])
    payment('bob', 'ada', 1)
    eq(balances(), [2**53, 0, 0, 0, 0])


@requirement('R027', 'No operation produces a balance above 2^53',
             'no operation produces a balance outside ±2⁵³.', 1, 'ledger.py / payments.py / settlements.py')
def balance_ceiling():
    """Seed Ada=1 and Bob=2^53, then send Bob one unit; reject atomically with the general 422 rule."""
    reset(fixture([1, 2**53, 0, 0, 0]))
    before = snapshot()
    error('POST', '/payments', dict(to_handle='bob', amount=1), 422, 'validation_failed', 'ada', key())
    unchanged(before)


@requirement('R028', 'Public/private feed is exactly sender, receiver or public',
             'A payment appears for a caller **if and only if** its `visibility` is `public`, **or** the caller is its sender or its receiver.', 1, 'activity.py')
def feed_visibility():
    reset()
    public = payment(visibility='public'); private = payment(visibility='private')
    request(); split()
    for user in NAMES:
        got = {p['payment_id']: p for p in feed(user)}
        expected = [public, private] if user in ('ada', 'bob') else [public]
        eq(got, {p['payment_id']: p for p in expected})


@requirement('R029', 'Requests exceed balance, remain pending after failed pay and become payable later',
             'Money can arrive later and the same request then becomes payable.', 1, 'requests_api.py')
def request_later_funds():
    reset()
    r = request(payer='cy', amount=30)
    eq(r['status'], 'pending'); eq(r['payment_id'], None)
    eq(r['requester_id'], 'u_ada'); eq(r['requester_handle'], 'ada'); eq(r['payer_id'], 'u_cy'); eq(r['payer_handle'], 'cy')
    identifier(r['request_id']); stamp(r['created_at'])
    path = '/requests/'+r['request_id']+'/pay'
    before = snapshot()
    error('POST', path, {}, 409, 'insufficient_funds', 'cy', 'retry')
    unchanged(before)
    payment(to='cy', amount=30)
    p = ok('POST', path, {}, 'cy', 'retry', 201)
    receipt(p, 'cy', 'ada', 30, r['request_id'])
    current = requests('cy')[0]
    eq(current['status'], 'paid'); eq(current['payment_id'], p['payment_id'])
    eq(balances(), [10000, 2500, 0, 0, 0])


@requirement('R030', 'Request visibility belongs only to payer-selected payment',
             'A request carries no visibility of its own and never appears in anyone else\'s feed.', source='requests_api.py / activity.py')
def request_visibility():
    reset()
    r = request(visibility='public')
    assert 'visibility' not in r
    for user in NAMES: eq(feed(user), [])
    p = pay(r, body={'visibility': 'private'})
    eq(p['visibility'], 'private')
    eq(feed('ada'), [p]); eq(feed('bob'), [p]); eq(feed('cy'), [])


@requirement('R031', 'Request actions enforce payer/requester roles and missing resources',
             'Only the payer may pay or decline it; only the requester may cancel it.', source='requests_api.py')
def request_roles():
    reset(); r = request()
    for action, allowed in [('pay', 'bob'), ('decline', 'bob'), ('cancel', 'ada')]:
        for user in NAMES:
            if user == allowed: continue
            before = snapshot()
            error('POST', '/requests/'+r['request_id']+'/'+action, {}, 403, 'forbidden', user, key())
            unchanged(before)
        error('POST', '/requests/missing/'+action, {}, 404, 'not_found', allowed, key())


@requirement('R032', 'Decline/cancel repeats are 200 and terminal states cannot change',
             'A request is `pending`, and then exactly one of `paid`, `declined` or `cancelled`.', 1, 'requests_api.py')
def terminal_states():
    for first, actor, state in [('pay', 'bob', 'paid'), ('decline', 'bob', 'declined'), ('cancel', 'ada', 'cancelled')]:
        reset(); r = request()
        path = '/requests/'+r['request_id']+'/'
        result = ok('POST', path+first, {}, actor, key() if first == 'pay' else ABSENT, 201 if first == 'pay' else 200)
        eq(requests()[0]['status'], state)
        for action, user in [('pay', 'bob'), ('decline', 'bob'), ('cancel', 'ada')]:
            before = snapshot()
            if action == first and action != 'pay':
                eq(ok('POST', path+action, {}, user), result)
            else:
                error('POST', path+action, {}, 409, 'request_not_pending', user, key() if action == 'pay' else ABSENT)
            unchanged(before)


@requirement('R033', 'Request lists show only own incoming/outgoing requests and filter all statuses',
             '`GET /requests`, which returns only requests where the caller is the requester or the payer.', source='requests_api.py')
def request_filters():
    reset()
    rows = [request('ada', 'bob'), request('bob', 'ada'), request('cy', 'dee'), request('ada', 'cy')]
    pay(rows[0]); ok('POST', '/requests/'+rows[1]['request_id']+'/decline', {}, 'ada')
    ok('POST', '/requests/'+rows[3]['request_id']+'/cancel', {}, 'ada')
    rows = {r['request_id']: r for r in requests('ada') + requests('cy')}
    for user in NAMES:
        for direction in [None, 'incoming', 'outgoing']:
            for status in [None, 'pending', 'paid', 'declined', 'cancelled']:
                q = {'limit': 200}
                if direction: q['direction'] = direction
                if status: q['status'] = status
                expected = [r for r in rows.values() if
                            (r['payer_handle'] == user if direction == 'incoming' else r['requester_handle'] == user if direction == 'outgoing' else user in (r['payer_handle'], r['requester_handle']))
                            and (status is None or r['status'] == status)]
                eq({r['request_id'] for r in requests(user, '?'+urllib.parse.urlencode(q))}, {r['request_id'] for r in expected})
    for field in ['direction', 'status']:
        for value in ['', 'wrong', 'PUBLIC']:
            error('GET', '/requests?'+field+'='+value, ABSENT, 422, 'validation_failed', 'ada')


@requirement('R034', 'Pagination defaults, boundaries, offset and has_more use visible items',
             '`has_more` is true when items exist beyond the last one returned.', source='requests_api.py / activity.py')
def pagination():
    f=fixture()
    f['payments']=[dict(id='p_seed_'+str(i),from_user_id='u_ada',to_user_id='u_bob',amount=1,note='',visibility='public') for i in range(205)]
    f['requests']=[dict(id='rq_seed_'+str(i),requester_id='u_ada',payer_id='u_bob',amount=1,note='',status='pending') for i in range(205)]
    reset(f)
    payment(visibility='private')
    for path, field, user, total in [('/activity', 'payments', 'cy', 205), ('/requests', 'requests', 'ada', 205)]:
        for query, length, more in [('', 50, True), ('?limit=1', 1, True), ('?limit=200', 200, True),
                                    ('?limit=2&offset=203', 2, False), ('?limit=1&offset=203', 1, True),
                                    ('?limit=1&offset=205', 0, False), ('?offset=99999', 0, False), ('?limit=0001&offset=00', 1, True)]:
            b = ok('GET', path+query, user=user)
            eq(len(b[field]), length); eq(b['has_more'], more); assert type(b['has_more']) is bool
        first = ok('GET', path+'?limit=1', user=user)[field][0]
        second = ok('GET', path+'?limit=1&offset=1', user=user)[field][0]
        assert first != second


@requirement('R035', 'Integer query parameters accept only plain digits within range',
             'An integer-valued **query parameter** is written as plain decimal digits: `1e9`, `4.0` and `+4` are 422 `validation_failed` whatever their numeric value.', source='requests_api.py')
def query_validation():
    reset()
    for path in ['/activity', '/requests']:
        for field in ['limit', 'offset']:
            values = ['', '-1', '1e9', '4.0', '+4', 'true', ' 4', '٤'] + (['0', '201'] if field == 'limit' else [])
            for value in values:
                error('GET', path+'?'+urllib.parse.urlencode({field: value}), ABSENT, 422, 'validation_failed', 'ada')


@requirement('R036', 'Unbounded decimal offset never produces a server error',
             '`offset` | integer 0 or more | 422 `validation_failed`', 1, 'requests_api.py')
def huge_query():
    """Use a 4,500-digit decimal offset (valid, beyond all items) and limit (invalid range); neither may produce 5xx."""
    reset()
    for path, field in [('/activity', 'payments'), ('/requests', 'requests')]:
        eq(ok('GET', path+'?offset='+'9'*4500, user='ada'), {field: [], 'has_more': False})
        error('GET', path+'?limit='+'9'*4500, ABSENT, 422, 'validation_failed', 'ada')


@requirement('R037', 'Feeds and requests sort newest first without assuming order within a second',
             'Payments visible to the caller by the feed contract in §4, newest first by `created_at`.', source='activity.py / requests_api.py')
def ordering():
    reset()
    payment(); request()
    time.sleep(1.05)
    payment(); request()
    for items in [feed(), requests()]:
        times = [datetime.datetime.fromisoformat(x['created_at'].replace('Z', '+00:00')) for x in items]
        eq(times, sorted(times, reverse=True)); assert times[0] > times[-1]


@requirement('R038', 'Split shares cover participant order, total exactly and differ by at most one',
             'Shares must be whole minor units, sum exactly to `amount` and differ by at most one minor unit.', 1, 'splits.py')
def split_rounding():
    reset()
    for amount, participants in [(1000, ['ada','bob','cy']), (1, ['ada','bob','cy']), (10, ['ada','bob','cy']),
                                  (999, ['ada','bob','cy']), (5, list(NAMES)), (1000000000, list(NAMES))]:
        s = split(amount, participants)
        identifier(s['split_id']); stamp(s['created_at'])
        q, r = divmod(amount, len(participants))
        eq(s['shares'], [dict(handle=h, amount=q+(i<r)) for i,h in enumerate(participants)])
        values = [row['amount'] for row in s['shares']]
        assert all(type(x) is int for x in values)
        eq(sum(values), amount); assert max(values)-min(values) <= 1
        eq([row['payer_handle'] for row in s['requests']], [h for h in participants if h != 'ada'])
        for row in s['requests']:
            eq(row['requester_handle'], 'ada'); eq(row['status'], 'pending'); eq(row['payment_id'], None)
            eq(row['amount'], next(x['amount'] for x in s['shares'] if x['handle'] == row['payer_handle']))


@requirement('R039', 'Remainders follow input order independently of earlier splits',
             'Each split\'s shares are independent of previous splits.', source='splits.py')
def split_order():
    reset()
    for handles in [['ada','bob','cy'], ['cy','ada','bob'], ['bob','cy','ada'], ['ada','bob','cy']]:
        s = split(10, handles)
        eq(s['shares'], [dict(handle=h, amount=4 if i == 0 else 3) for i,h in enumerate(handles)])
    eq(balances(), [10000,2500,0,0,0])


@requirement('R040', 'Caller inclusion optional; caller-only valid; no participant balance check',
             'A split whose only participant is the caller is **valid**: it computes one share, creates zero requests, and returns `"requests": []`.', source='splits.py')
def split_participants():
    reset(fixture([0,0,0,0,0]))
    s = split(1000000000, ['ada']); eq(s['requests'], []); eq(s['shares'], [dict(handle='ada', amount=1000000000)])
    s = split(10, ['cy','bob']); eq([r['payer_handle'] for r in s['requests']], ['cy','bob'])
    eq([r['amount'] for r in s['requests']], [5,5])
    for user in NAMES: eq(feed(user), [])
    eq(requests('dee'), [])


@requirement('R041', 'Zero shares create payable requests and full split payments conserve money',
             'A share of `0` is legal and still produces a request for that participant.', 1, 'splits.py / requests_api.py')
def zero_shares():
    reset(fixture([100,100,100,100,100]))
    for amount in [1,10,5,17]:
        s = split(amount, ['ada','cy','bob'])
        for r in s['requests']:
            p = pay(r, r['payer_handle']); eq(p['amount'], r['amount'])
        eq(sum(balances()), 500)
        assert min(balances()) >= 0


@requirement('R042', 'Split invalid participants fail atomically without partial requests',
             '`participant_handles` empty, or containing a duplicate handle | 422 `validation_failed`', source='splits.py')
def split_errors():
    reset()
    for handles, status, code in [([],422,'validation_failed'), (['bob','bob'],422,'validation_failed'),
                                  (['bob','missing'],404,'not_found')]:
        before = snapshot()
        error('POST', '/splits', dict(amount=10, participant_handles=handles), status, code, 'ada', key())
        unchanged(before)


@requirement('R043', 'Settlement operator required and permission does not bypass privacy',
             'This permission does not grant access to another user\'s requests or private activity items.', 1, 'settlements.py / activity.py / requests_api.py')
def operator_permissions():
    reset()
    p = payment('bob','cy',1,visibility='private'); r = request('bob','cy',1)
    eq(feed('ada'), []); eq(requests('ada'), [])
    error('POST','/requests/'+r['request_id']+'/pay',{},403,'forbidden','ada',key())
    for user in ['bob','cy']:
        error('POST','/settlements',dict(transfers=[transfer()]),403,'forbidden',user,key())
    f=fixture(); del f['settlement_operator_ids']; reset(f)
    error('POST','/settlements',dict(transfers=[transfer()]),403,'forbidden','ada',key())


@requirement('R044', 'Settlement batch shape is 1 through 32 objects',
             'transfers contains 1..32 objects.', source='settlements.py')
def batch_shape():
    reset()
    for b in [{}, {'transfers': None}, {'transfers': {}}, {'transfers': []}, {'transfers': [None]},
              {'transfers': [1]}, {'transfers': [transfer()]*33}]:
        before=snapshot()
        error('POST','/settlements',b,422,'validation_failed','ada',key()); unchanged(before)
    eq(len(settlement([transfer(amount=1)]*32)['payments']),32)


@requirement('R045', 'Settlement validates entry errors in input order before funds',
             'Entry errors take precedence in input order, before insufficient funds.', 1, 'settlements.py')
def batch_precedence():
    reset()
    for entries, status, code in [([transfer(frm='cy'),transfer(to='missing')],404,'not_found'),
                                  ([transfer(to='missing'),transfer(amount=0)],404,'not_found'),
                                  ([transfer(amount=0),transfer(to='missing')],422,'validation_failed'),
                                  ([transfer(to='ada'),transfer(to='missing')],422,'self_payment')]:
        before=snapshot()
        error('POST','/settlements',{'transfers':entries},status,code,'ada',key()); unchanged(before)


@requirement('R046', 'Settlement affordability uses net flow, including zero-funded cycles',
             'A settlement is affordable when every wallet\'s balance after all incoming and outgoing transfers is nonnegative.', 1, 'settlements.py / ledger.py')
def net_settlement():
    reset(fixture([0,0,0,0,0]))
    s=settlement([transfer('ada','bob',10),transfer('bob','cy',10),transfer('cy','ada',10)])
    eq(balances(),[0,0,0,0,0]); eq(len(s['payments']),3)
    reset(fixture([10,0,0,0,0]))
    settlement([transfer('bob','cy',10),transfer('ada','bob',10)])
    eq(balances(),[0,0,10,0,0])


@requirement('R047', 'Insufficient collective funds leave no payment, key or revision',
             'Either all movements commit together or none do; failed validation claims no idempotency key and creates no payment or revision.', 1, 'settlements.py')
def settlement_atomic_failure():
    reset(fixture([10,0,0,0,0]))
    before=snapshot()
    error('POST','/settlements',{'transfers':[transfer('ada','bob',10),transfer('bob','cy',11)]},409,'insufficient_funds','ada','failed')
    unchanged(before)
    settlement([transfer('ada','bob',1)],idem='failed')


@requirement('R048', 'Settlement receipts preserve input order, membership and shared timestamp',
             'Members have null request_id and the same server-assigned created_at, equal to committed_at.', source='settlements.py / ledger.py')
def settlement_receipts():
    reset()
    entries=[transfer('ada','bob',11,note='first',visibility='private'),transfer('bob','cy',7,note='second')]
    s=settlement(entries); identifier(s['settlement_id']); stamp(s['committed_at'])
    for p,e in zip(s['payments'],entries):
        receipt(p,e['from_handle'],e['to_handle'],e['amount'],settlement_id=s['settlement_id'])
        eq(p['created_at'],s['committed_at']); eq(p['note'],e['note'])
    for user in NAMES:
        expected=[p for p in s['payments'] if p['visibility']=='public' or user in (p['from_handle'],p['to_handle'])]
        eq({p['payment_id']:p for p in feed(user)},{p['payment_id']:p for p in expected})
    eq(payment()['settlement_id'],None)
    eq(pay(request())['settlement_id'],None)


def write_case(kind, same_user=False):
    f=fixture([10000,10000,10000,0,0]); f['settlement_operator_ids']=['u_ada','u_bob']
    reset(f)
    if kind=='payments': return '/payments','ada',dict(to_handle='cy',amount=10)
    if kind=='requests': return '/requests','ada',dict(payer_handle='cy',amount=10)
    if kind=='splits': return '/splits','ada',dict(amount=10,participant_handles=['cy'])
    if kind=='settlements': return '/settlements','ada',dict(transfers=[transfer('ada','cy',10)])
    r=request('ada','bob',10)
    return '/requests/'+r['request_id']+'/pay','bob',{'visibility':'private'}


def add_idempotency_requirements():
    definitions=[
        ('key', 'Required idempotency key and length 1..255', 'Header absent or empty | 400 `missing_idempotency_key`'),
        ('replay', 'First use 201, semantic JSON replay 200 and exactly unchanged state', '"Same body" means the same JSON value after parsing — key order and whitespace do not matter.'),
        ('conflict', 'Claimed key beats invalid fields and current resource state', 'Thus changing a successful request to an invalid body with the same key still returns `409 idempotency_key_reuse`.'),
        ('retry', 'Failed requests leave their key reusable', 'Key reused after the original request failed with 4xx | Treated as a first use'),
        ('scope', 'Key scoped independently to authenticated user and path', 'Two different users may use the same key string with no interaction between them.'),
        ('race', '50 identical concurrent writes perform exactly once', 'For concurrent identical requests with an unused key, exactly one returns 201.'),
        ('frozen', 'Successful replay retains original response after later resource changes', 'A successful replay returns the original response, even after the resource changes or is cancelled.'),
        ('parse', 'Malformed JSON and unauthenticated callers do not replay a claimed key', 'After the body has parsed as a JSON object and the caller is authenticated, an already claimed key is resolved before endpoint field validation or current-resource checks.'),
        ('decimal', 'Equal fractional values in ignored fields remain the same JSON body', '"Same body" means the same JSON value after parsing — key order and whitespace do not matter.'),
        ('collision', 'Different JSON types in ignored fields cannot collide as idempotent bodies', 'Same key, different body | 409 `idempotency_key_reuse`'),
    ]
    for index,kind in enumerate(['payments','requests','pay','splits','settlements']):
        for offset,(mode,title,quote) in enumerate(definitions):
            rid='R%03d'%(49+index*10+offset)
            def run(kind=kind,mode=mode):
                path,user,body=write_case(kind)
                if mode=='key':
                    for idem in [ABSENT,'']:
                        error('POST',path,body,400,'missing_idempotency_key',user,idem)
                    error('POST',path,body,422,'validation_failed',user,'k'*256)
                    ok('POST',path,body,user,'k',201)
                    # Pay needs a fresh pending request for the second successful write.
                    path,user,body=write_case(kind)
                    ok('POST',path,body,user,'k'*255,201)
                elif mode=='replay':
                    original=ok('POST',path,body,user,'same',201)
                    before=snapshot()
                    raw=json.dumps(dict(reversed(list(body.items()))),indent=3).encode()
                    eq(ok('POST',path,user=user,idem='same',raw=raw),original)
                    unchanged(before)
                    if kind!='pay':
                        # Integral numeric spellings are equal JSON values.
                        raw=json.dumps(body).replace('10','1e1').encode()
                        eq(ok('POST',path,user=user,idem='same',raw=raw),original)
                elif mode=='conflict':
                    ok('POST',path,body,user,'same',201); before=snapshot()
                    for invalid in [{},dict(body,amount=False,visibility='invalid'),dict(body,extra='different')]:
                        if invalid==body: continue
                        error('POST',path,invalid,409,'idempotency_key_reuse',user,'same'); unchanged(before)
                elif mode=='retry':
                    before=snapshot()
                    error('POST',path,ABSENT,400,'malformed_request',user,'retry',raw=b'{'); unchanged(before)
                    bad=dict(body)
                    if kind=='pay': bad['visibility']=None
                    elif kind=='settlements': bad={'transfers':[transfer(amount=0)]}
                    else: bad['amount']=0
                    error('POST',path,bad,422,'validation_failed',user,'retry'); unchanged(before)
                    ok('POST',path,body,user,'retry',201)
                elif mode=='scope':
                    if kind=='pay':
                        # Same empty body and key, different payer paths; and another user's pay.
                        r1=request('ada','bob',1); r2=request('ada','bob',1); r3=request('ada','cy',1)
                        for r,actor in [(r1,'bob'),(r2,'bob'),(r3,'cy')]:
                            ok('POST','/requests/'+r['request_id']+'/pay',{},actor,'shared',201)
                    else:
                        first=ok('POST',path,body,'ada','shared',201)
                        second=ok('POST',path,body,'bob','shared',201)
                        assert first!=second
                        # All paths use a fresh string; combined fields make exactly the same body legal on both.
                        combined={'to_handle':'cy','payer_handle':'cy','amount':1,'participant_handles':['cy'],'transfers':[transfer('ada','cy',1)]}
                        for other_path in ['/payments','/requests','/splits','/settlements']:
                            ok('POST',other_path,combined,'ada','cross-path',201)
                elif mode=='race':
                    results=race([lambda: http('POST',path,body,user,'race') for _ in range(50)])
                    eq([s for s,b in results].count(201),1)
                    eq([s for s,b in results].count(200),49)
                    original=next(b for s,b in results if s==201)
                    for status,b in results: eq(b,original)
                    if kind in ('payments','pay','settlements'): eq(len(feed()),1)
                    elif kind=='requests': eq(len(requests('ada')),1)
                    else: eq(len(requests('ada')),1)
                    eq(sum(balances()),30000)
                elif mode=='frozen':
                    original=ok('POST',path,body,user,'frozen',201)
                    if kind=='requests':
                        ok('POST','/requests/'+original['request_id']+'/cancel',{},user)
                    elif kind=='splits':
                        for r in original['requests']: pay(r,r['payer_handle'])
                    else: payment('cy','ada',1)
                    before=snapshot()
                    eq(ok('POST',path,body,user,'frozen'),original); unchanged(before)
                elif mode=='parse':
                    ok('POST',path,body,user,'claimed',201)
                    before=snapshot()
                    error('POST',path,ABSENT,400,'malformed_request',user,'claimed',raw=b'{')
                    error('POST',path,[],400,'malformed_request',user,'claimed')
                    error('POST',path,body,401,'unauthenticated',idem='claimed',auth='Bearer unknown')
                    unchanged(before)
                elif mode=='decimal':
                    body=dict(body,ignored_fraction=1.5)
                    original=ok('POST',path,body,user,'decimal',201)
                    raw=json.dumps(body).replace('1.5','1.50').encode()
                    eq(ok('POST',path,user=user,idem='decimal',raw=raw),original)
                elif mode=='collision':
                    body=dict(body,ignored_fraction=1.5)
                    ok('POST',path,body,user,'collision',201)
                    changed=dict(body,ignored_fraction={'$dec':'1.5'})
                    error('POST',path,changed,409,'idempotency_key_reuse',user,'collision')
            run.__doc__='%s: %s. All requests use only HTTP, start with a fresh fixture, and check the full response/status.'%(kind, title)
            requirement(rid,kind+': '+title,quote,1,'idem.py / common.py / server.py')(run)


add_idempotency_requirements()


@requirement('R099', 'Empty pay body differs from explicit public for idempotency',
             '`{}` and `{"visibility": "public"}` are different JSON values, so reusing a key across the two is `409 idempotency_key_reuse`, per §7.', source='idem.py / requests_api.py')
def pay_default_identity():
    reset(); r=request()
    path='/requests/'+r['request_id']+'/pay'
    p=ok('POST',path,{},'bob','body',201)
    error('POST',path,{'visibility':'public'},409,'idempotency_key_reuse','bob','body')
    eq(ok('POST',path,{},'bob','body'),p)


@requirement('R100', '50 competing payments never overspend and conserve total',
             'The sum of wallet balances always equals the total seeded by the last `POST /_test/reset`.', 1, 'server.py / payments.py')
def concurrent_payments():
    reset(fixture([25,0,0,0,0]))
    calls=[lambda i=i: http('POST','/payments',dict(to_handle='bob' if i%2 else 'cy',amount=1),'ada','unique-'+str(i)) for i in range(50)]
    results=race(calls)
    eq(sum(s==201 for s,b in results),25)
    for s,b in results:
        assert s in (201,409),(s,b)
        if s==409: eq(b['error']['code'],'insufficient_funds')
    eq(sum(balances()),25); eq(balances()[0],0); assert min(balances())>=0
    eq(len(feed()),25)


@requirement('R101', 'A request moves money at most once with concurrent different keys',
             'A payment request may move money at most once.', 1, 'requests_api.py / server.py')
def concurrent_request_pay():
    reset(); r=request(amount=25); path='/requests/'+r['request_id']+'/pay'
    results=race([lambda i=i: http('POST',path,{},'bob','pay-'+str(i)) for i in range(50)])
    eq(sum(s==201 for s,b in results),1)
    for s,b in results:
        if s!=201: eq((s,b['error']['code']),(409,'request_not_pending'))
    eq(balances(),[10025,2475,0,0,0]); eq(len(feed()),1)
    eq(requests()[0]['payment_id'],feed()[0]['payment_id'])


@requirement('R102', 'Concurrent pay/decline/cancel chooses one terminal state',
             'A request is `pending`, and then exactly one of `paid`, `declined` or `cancelled`.', 1, 'requests_api.py / server.py')
def transition_race():
    for _ in range(3):
        reset(); r=request(amount=25); path='/requests/'+r['request_id']+'/'
        actions=[('pay','bob'),('decline','bob'),('cancel','ada')]*10
        results=race([lambda i=i,a=a,u=u: http('POST',path+a,{},u,'action-'+str(i)) for i,(a,u) in enumerate(actions)])
        state=requests()[0]['status']; assert state in ('paid','declined','cancelled')
        for (a,u),(s,b) in zip(actions,results):
            target={'pay':'paid','decline':'declined','cancel':'cancelled'}[a]
            if s<300: eq(target,state)
            else: eq((s,b['error']['code']),(409,'request_not_pending'))
        eq(len(feed()),int(state=='paid'))
        eq(balances(),[10025,2475,0,0,0] if state=='paid' else [10000,2500,0,0,0])


@requirement('R103', 'Export envelope is unauthenticated, read-only and stable',
             'Return 200 from export with a JSON object containing `track: "pocketful"`, `format_version: 1` and `state` (an implementation-defined JSON object).', source='testctl.py / store.py')
def export_contract():
    reset(); payment(); request()
    a=snapshot(); eq(a['track'],'pocketful'); eq(a['format_version'],1); assert type(a['format_version']) is int
    assert isinstance(a['state'],dict)
    eq(snapshot(),a)
    frozen=json.dumps(a,sort_keys=True)
    payment(); request()
    eq(json.dumps(a,sort_keys=True),frozen)
    ok('POST','/_test/import',a,status=204)
    eq(snapshot(),a); eq(len(feed()),1); eq(len(requests()),1)


@requirement('R104', 'Import restores identities, timestamps, credentials, sessions and balances',
             'Preserve accounts and hashed-password login, existing bearer tokens, currency, balances, payments, requests, permissions, all completed idempotent request bodies and original responses.', 1, 'store.py / testctl.py')
def import_preservation():
    reset(fixture(currency='BHD',minor=3))
    signup=ok('POST','/auth/signup',dict(email='new@domain',password=PASSWORD,display_name='N'),status=201)
    TOKENS['new']=signup['token']
    payment(to='new',amount=3)
    payment(visibility='private'); pay(request()); request(payer='cy'); split()
    settlement([transfer('bob','cy',1,visibility='private')])
    old_tokens=dict(TOKENS)
    old_me={n:me(n) for n in list(NAMES)+['new']}
    old_feeds={n:feed(n) for n in NAMES}; old_requests={n:requests(n) for n in NAMES}
    exported=snapshot()
    reset(); destination_token=TOKENS['ada']
    newcomer=ok('POST','/auth/signup',dict(email='destination@domain',password=PASSWORD,display_name='D'),status=201)
    for _ in range(2):
        ok('POST','/_test/import',exported,status=204); TOKENS.clear(); TOKENS.update(old_tokens)
        eq(snapshot(),exported)
        for n in list(NAMES)+['new']: eq(me(n),old_me[n])
        for n in NAMES: eq(feed(n),old_feeds[n]); eq(requests(n),old_requests[n])
        error('GET','/me',ABSENT,401,'unauthenticated',auth='Bearer '+destination_token)
        error('GET','/me',ABSENT,401,'unauthenticated',auth='Bearer '+newcomer['token'])
        error('POST','/auth/login',dict(email='destination@domain',password=PASSWORD),401,'unauthenticated')
    login=ok('POST','/auth/login',dict(email='new@domain',password=PASSWORD)); eq(login['user_id'],signup['user_id'])
    for n in NAMES:
        login=ok('POST','/auth/login',dict(email=n+'@example.com',password=PASSWORD)); eq(login['user_id'],'u_'+n)
    settlement([transfer(amount=1)])
    error('POST','/settlements',dict(transfers=[transfer()]),403,'forbidden','bob',key())
    reset(); eq(feed(),[]); eq(requests(),[])
    error('GET','/me',ABSENT,401,'unauthenticated',auth='Bearer '+old_tokens['new'])


@requirement('R105', 'Import preserves every completed idempotent body and original response',
             'Existing receipts, tokens and retries must remain valid after import; replacing the state with a fresh fixture does not satisfy this requirement.', 1, 'store.py / idem.py')
def import_replays():
    reset()
    cases=[]
    for path,user,body in [('/payments','ada',dict(to_handle='bob',amount=2)),
                           ('/requests','ada',dict(payer_handle='bob',amount=2)),
                           ('/splits','ada',dict(participant_handles=['ada','bob'],amount=3)),
                           ('/settlements','ada',dict(transfers=[transfer(amount=2)]))]:
        response=ok('POST',path,body,user,'persist',201); cases.append((path,user,body,response))
    r=cases[1][3]; path='/requests/'+r['request_id']+'/pay'
    response=ok('POST',path,{},'bob','persist',201); cases.append((path,'bob',{},response))
    # Pending->paid and split child cancellation must not rewrite cached create receipts.
    child=cases[2][3]['requests'][0]
    ok('POST','/requests/'+child['request_id']+'/cancel',{},'ada')
    error('POST','/payments',dict(to_handle='bob',amount=0),422,'validation_failed','ada','failed-persist')
    tokens=dict(TOKENS); exported=snapshot()
    reset(); ok('POST','/_test/import',exported,status=204); TOKENS.update(tokens)
    before=snapshot()
    for path,user,body,response in cases:
        eq(ok('POST',path,body,user,'persist'),response)
        error('POST',path,dict(body,extra=True),409,'idempotency_key_reuse',user,'persist')
    unchanged(before)
    ok('POST','/payments',dict(to_handle='bob',amount=1),'ada','failed-persist',201)


@requirement('R106', 'Invalid import is 422 and leaves the complete destination state unchanged',
             'missing fields, wrong track/version or an invalid state give 422 `validation_failed` without changing the destination.', 1, 'store.py / testctl.py')
def invalid_import():
    reset(); payment(); before=snapshot()
    invalid=[{},dict(track='wrong',format_version=1,state={}),dict(track='pocketful',format_version=2,state={})]
    for field in ['track','format_version','state']:
        b=copy.deepcopy(before); del b[field]; invalid.append(b)
    for version in [True,'1',None,0]: invalid.append(dict(before,format_version=version))
    for state in [None,{},[],1,'wrong']: invalid.append(dict(before,state=state))
    for b in invalid:
        error('POST','/_test/import',b,422,'validation_failed'); unchanged(before)
    error('POST','/_test/import',ABSENT,400,'malformed_request',raw=b'{'); unchanged(before)


@requirement('R107', 'Export snapshots during concurrent settlements contain only whole commits',
             'Export is an atomic, read-only snapshot; subsequent source writes do not change it.', 1, 'store.py / settlements.py / server.py')
def atomic_snapshots():
    reset(fixture([100,100,100,0,0]))
    tokens=dict(TOKENS)
    body={'transfers':[transfer('ada','bob',1),transfer('bob','cy',1)]}
    calls=[lambda i=i: http('POST','/settlements',body,'ada','snapshot-'+str(i)) for i in range(25)]
    calls += [lambda: http('GET','/_test/export') for _ in range(25)]
    results=race(calls)
    snapshots=[b for s,b in results if s==200]
    eq(len(snapshots),25)
    for s,b in results[:25]: eq(s,201)
    for exported in snapshots:
        ok('POST','/_test/import',exported,status=204); TOKENS.update(tokens)
        ps=feed(); assert len(ps)%2==0
        groups={}
        for p in ps: groups.setdefault(p['settlement_id'],[]).append(p)
        assert all(len(g)==2 for g in groups.values())
        n=len(ps)//2
        eq(balances(),[100-n,100,100+n,0,0]); eq(sum(balances()),300)


@requirement('R108', 'Mixed simultaneous settlements and direct payments commit only affordable states',
             'Requests must not produce 5xx responses, including under concurrent load.', 1, 'server.py / settlements.py / payments.py')
def mixed_race():
    reset(fixture([25,0,0,0,0]))
    batch={'transfers':[transfer('ada','bob',1),transfer('bob','cy',1)]}
    calls=[]
    for i in range(50):
        path,body=('/payments',dict(to_handle='cy',amount=1)) if i%2 else ('/settlements',batch)
        calls.append(lambda i=i,path=path,body=body:http('POST',path,body,'ada','mixed-'+str(i)))
    results=race(calls)
    eq(sum(s==201 for s,b in results),25)
    for s,b in results:
        if s!=201: eq((s,b['error']['code']),(409,'insufficient_funds'))
    eq(balances(),[0,0,25,0,0])
    groups={}
    for p in feed():
        if p['settlement_id']: groups.setdefault(p['settlement_id'],[]).append(p)
    assert all(len(g)==2 for g in groups.values())


@requirement('R109', 'Decline rejects unparseable JSON without changing the request',
             '400 | `malformed_request` | Unparseable body, or a field of the wrong JSON type', 1, 'requests_api.py')
def malformed_decline():
    reset(); r=request(); before=snapshot()
    error('POST','/requests/'+r['request_id']+'/decline',ABSENT,400,'malformed_request','bob',raw=b'{')
    unchanged(before)


@requirement('R110', 'Cancel rejects unparseable JSON without changing the request',
             '400 | `malformed_request` | Unparseable body, or a field of the wrong JSON type', 1, 'requests_api.py')
def malformed_cancel():
    reset(); r=request(); before=snapshot()
    error('POST','/requests/'+r['request_id']+'/cancel',ABSENT,400,'malformed_request','ada',raw=b'{')
    unchanged(before)


@requirement('R111', 'Wrongly typed seeded references must never produce 5xx',
             'Requests must not produce 5xx responses, including under concurrent load.', 1, 'store.py')
def malformed_seed_reference():
    reset(); before=snapshot()
    f=fixture()
    f['payments']=[dict(id='p_bad',from_user_id={},to_user_id='u_bob',amount=1,note='',visibility='public')]
    error('POST','/_test/reset',f,400,'malformed_request'); unchanged(before)


@requirement('R112', 'Request payment cannot credit a balance beyond 2^53',
             'no operation produces a balance outside ±2⁵³.', 1, 'ledger.py / requests_api.py')
def pay_balance_ceiling():
    reset(fixture([2**53,1,0,0,0])); r=request(amount=1); before=snapshot()
    error('POST','/requests/'+r['request_id']+'/pay',{},422,'validation_failed','bob',key()); unchanged(before)


@requirement('R113', 'Settlement cannot credit a balance beyond 2^53',
             'no operation produces a balance outside ±2⁵³.', 1, 'ledger.py / settlements.py')
def settlement_balance_ceiling():
    reset(fixture([1,2**53,0,0,0])); before=snapshot()
    error('POST','/settlements',{'transfers':[transfer(amount=1)]},422,'validation_failed','ada',key()); unchanged(before)


@requirement('R114', 'Concurrent signup maintains uniqueness and creates only one account',
             'Every user has a **handle**: unique across the service, matching `^[a-z0-9_]{1,20}$`, and never changing once set.', 1, 'auth.py')
def signup_race():
    reset()
    body=dict(email='race@domain',password=PASSWORD,display_name='R')
    results=race([lambda:http('POST','/auth/signup',body) for _ in range(20)])
    eq(sum(s==201 for s,b in results),1)
    for s,b in results:
        if s!=201: eq((s,b['error']['code']),(409,'email_taken'))
    winner=next(b for s,b in results if s==201)
    eq(ok('POST','/auth/login',dict(email=body['email'],password=PASSWORD))['user_id'],winner['user_id'])


@requirement('R115', 'Payment recipient handle boundaries 1 and 20 characters are usable',
             'Every user has a **handle**: unique across the service, matching `^[a-z0-9_]{1,20}$`, and never changing once set.', source='auth.py / ledger.py')
def handle_boundaries():
    reset()
    for local in ['x','abcdefghijklmnopqrst']:
        user=ok('POST','/auth/signup',dict(email=local+'@d',password=PASSWORD,display_name=local),status=201)
        eq(ok('GET','/me',auth='Bearer '+user['token'])['handle'],local)
        payment(to=local,amount=1); request(payer=local,amount=1)


@requirement('R116', 'Fixtured minor_units accepts only 0, 2 and 3',
             '`minor_units` is `0`, `2` or `3`.', source='store.py')
def minor_units_validation():
    reset(); before=snapshot()
    for n in [-1,1,4,2.5]:
        f=fixture(); f['minor_units']=n
        error('POST','/_test/reset',f,422,'validation_failed'); unchanged(before)


@requirement('R117', 'Failed 404/403/409 writes leave their idempotency key reusable',
             'Key reused after the original request failed with 4xx | Treated as a first use', 1, 'idem.py')
def failure_retry_codes():
    reset()
    error('POST','/payments',dict(to_handle='missing',amount=1),404,'not_found','ada','recover')
    ok('POST','/payments',dict(to_handle='bob',amount=1),'ada','recover',201)
    error('POST','/requests',dict(payer_handle='missing',amount=1),404,'not_found','ada','recover')
    ok('POST','/requests',dict(payer_handle='bob',amount=1),'ada','recover',201)
    error('POST','/splits',dict(participant_handles=['missing'],amount=1),404,'not_found','ada','recover')
    ok('POST','/splits',dict(participant_handles=['bob'],amount=1),'ada','recover',201)
    error('POST','/settlements',{'transfers':[transfer(to='missing')]},404,'not_found','ada','recover')
    ok('POST','/settlements',{'transfers':[transfer(amount=1)]},'ada','recover',201)
    # A foreign caller's failure cannot claim the payer's key.
    r=request(); path='/requests/'+r['request_id']+'/pay'
    error('POST',path,{},403,'forbidden','cy','recover')
    ok('POST',path,{},'bob','recover',201)
    error('POST','/payments',dict(to_handle='ada',amount=1),409,'insufficient_funds','cy','short')
    payment(to='cy',amount=1)
    ok('POST','/payments',dict(to_handle='ada',amount=1),'cy','short',201)


@requirement('R118', 'Request list pagination applies direction/status filters before limit',
             'Requests where the caller is the requester or the payer, and no others.', source='requests_api.py')
def filtered_pagination():
    reset()
    for i in range(4):
        r=request('bob','ada',1)
        if i%2==0: ok('POST','/requests/'+r['request_id']+'/decline',{},'ada')
        request('ada','bob',1); request('cy','dee',1)
    b=ok('GET','/requests?direction=incoming&status=pending&limit=1',user='ada')
    eq(len(b['requests']),1); eq(b['has_more'],True)
    eq(b['requests'][0]['payer_handle'],'ada'); eq(b['requests'][0]['status'],'pending')
    c=ok('GET','/requests?direction=incoming&status=pending&limit=1&offset=1',user='ada')
    eq(c['has_more'],False); assert b['requests'][0]['request_id']!=c['requests'][0]['request_id']


@requirement('R119', 'Opaque IDs are strings of at most 64 characters and do not collide with seeded IDs',
             'IDs are opaque strings of at most 64 characters. Their format is yours.', source='store.py / ledger.py')
def ids_contract():
    f=fixture()
    f['payments']=[dict(id='p_1',from_user_id='u_ada',to_user_id='u_bob',amount=1,note='',visibility='public')]
    f['requests']=[dict(id='rq_1',requester_id='u_ada',payer_id='u_bob',amount=1,note='',status='pending')]
    reset(f)
    p=payment();r=request();s=split();batch=settlement([transfer()])
    assert p['payment_id']!='p_1';assert r['request_id']!='rq_1'
    u=ok('POST','/auth/signup',dict(email='idcheck@d',password=PASSWORD,display_name='I'),status=201)
    for obj in [p,r,s,batch,u]+s['requests']+batch['payments']:
        for name,value in obj.items():
            if name.endswith('_id') and value is not None:identifier(value)
    eq(len({p['payment_id'] for p in feed()}),len(feed()))
    eq(len({r['request_id'] for r in requests()}),len(requests()))


@requirement('R120', 'Every response timestamp is RFC 3339 with an explicit offset',
             'Timestamps in responses are RFC 3339 with an explicit offset, e.g. `2026-09-24T19:00:00+02:00`.', source='common.py / ledger.py')
def timestamps_contract():
    reset();r=request();s=split();batch=settlement([transfer()]);p=payment();paid=pay(r)
    for obj in [r,s,batch,p,paid]+s['requests']+batch['payments']+requests()+feed():
        for field in ['created_at','committed_at']:
            if field in obj:stamp(obj[field])


@requirement('R121', 'All observed error responses have the specified code and human-readable message envelope',
             'Every 4xx and 5xx response carries this body:', source='server.py')
def error_contract():
    reset()
    error('GET','/me',ABSENT,401,'unauthenticated')
    error('POST','/payments',dict(to_handle='bob',amount=0),422,'validation_failed','ada',key())
    error('POST','/payments',dict(to_handle='missing',amount=1),404,'not_found','ada',key())
    error('POST','/payments',dict(to_handle='bob',amount=1),400,'missing_idempotency_key','ada')
    error('POST','/settlements',dict(transfers=[transfer()]),403,'forbidden','bob',key())
    error('POST','/payments',dict(to_handle='bob',amount=1000000),409,'insufficient_funds','ada',key())


class Deadline(BaseException):
    pass


def main():
    if not BASE:
        print('BASE_URL is required',file=sys.stderr)
        return 1
    include_known='--include-known' in sys.argv
    failures=0
    def expired(signum,frame):
        raise Deadline()
    signal.signal(signal.SIGALRM,expired)
    signal.alarm(165)
    try:
        for index,test in enumerate(TESTS):
            rid=test['id']
            if rid in KNOWN_OPEN and not include_known:
                # A skipped open requirement is still visibly FAIL; only its exit status is exempted.
                print('FAIL %s KNOWN_OPEN SKIPPED: %s'%(rid,test['title']),flush=True)
                continue
            try:
                test['fn']()
                print('PASS %s %s'%(rid,test['title']),flush=True)
            except Exception as exc:
                failures+=1
                detail=str(exc).replace('\n',' ')[:650]
                print('FAIL %s %s: %s: %s'%(rid,test['title'],type(exc).__name__,detail),flush=True)
    except Deadline:
        for test in TESTS[index:]:
            print('FAIL %s suite exceeded 165-second budget'%test['id'],flush=True)
        return 1
    finally:
        signal.alarm(0)
    return int(failures>0)


if __name__=='__main__':
    sys.exit(main())
