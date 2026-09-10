"""Small private-alpha HTTP boundary; session tokens never reach browser JSON."""
import hmac
import logging
from uuid import uuid4

from .alpha_auth import AlphaAuthStore
from .alpha_commerce import account, catalog, checkout
from .security import DeploymentMode, SecurityError, authenticate_request, load_runtime_config

ROUTES = {
    '/auth/login': 'POST', '/auth/logout': 'POST', '/auth/session': 'GET',
    '/auth/password': 'POST', '/billing/catalog': 'GET', '/account': 'GET',
    '/billing/checkout': 'POST',
}


def handle_alpha_route(handler, path: str, method: str) -> bool:
    if path not in ROUTES:
        return False
    from .server import _error, _json, RequestJsonError
    try:
        config = load_runtime_config()
        if config.mode != DeploymentMode.PRIVATE_ALPHA:
            _error(handler, 404, 'NOT_FOUND', 'Not found.')
            return True
        if method != ROUTES[path]:
            _error(handler, 405, 'METHOD_NOT_ALLOWED', 'Method not allowed.')
            return True
        if not hmac.compare_digest(handler.headers.get('x-internal-api-key', ''), config.internal_api_key or ''):
            raise SecurityError(401, 'UNAUTHORIZED', 'Missing or invalid internal API key.')
        auth = None if path in {'/auth/login', '/billing/catalog'} else authenticate_request(handler.headers, config)
        body = {}
        if method == 'POST':
            try:
                length = int(handler.headers.get('content-length', '0'))
            except ValueError as exc:
                raise RequestJsonError('Invalid Content-Length.') from exc
            if not 0 <= length <= 4096:
                raise RequestJsonError('Request body must be at most 4096 bytes.')
            body = handler._read_json()
        store = AlphaAuthStore(config.alpha_database_path)
        if path == '/auth/login':
            result = store.login(body.get('email'), body.get('password'))
        elif path == '/auth/session':
            result = {'user': {'id': auth.owner_id, 'email': auth.email}}
        elif path == '/auth/logout':
            store.logout(auth.access_token)
            result = {'ok': True}
        elif path == '/auth/password':
            store.change_password(auth.access_token, body.get('currentPassword'), body.get('newPassword'))
            result = {'ok': True}
        elif path == '/billing/catalog':
            result = catalog()
        elif path == '/account':
            result = account(config, auth)
        else:
            checkout(body.get('offerId'))
            raise AssertionError('Unconfigured checkout must not succeed.')
        _json(handler, 200, result)
    except SecurityError as exc:
        _error(handler, exc.status, exc.code, exc.message)
    except (RequestJsonError, ValueError) as exc:
        _error(handler, 400, 'REQUEST_INVALID', str(exc))
    except Exception as exc:
        request_id = uuid4().hex
        logging.getLogger(__name__).error('Alpha request failed: id=%s route=%s exception=%s', request_id, path, type(exc).__name__)
        _error(handler, 503, 'ALPHA_UNAVAILABLE', f'Private alpha is temporarily unavailable. Reference: {request_id}')
    return True
