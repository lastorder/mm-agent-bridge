"""Monkey-patches for mattermostdriver 7.3.2 + Python 3.14 compatibility.

mattermostdriver was last updated Jan 2022 and has two bugs that surface
on modern Python:

1. **WebSocket SSL context** — ``websocket.py`` creates an SSL context with
   ``ssl.Purpose.CLIENT_AUTH`` (server-side purpose).  Python 3.14 now
   strictly rejects using a server context for client connections.
   Fix: subclass ``Websocket`` with the correct ``ssl.Purpose.SERVER_AUTH``.

2. **Content-Type check in ``client.get()``** — uses strict ``!=`` equality
   against ``'application/json'``.  Servers that return
   ``'application/json; charset=utf-8'`` cause ``get()`` to return a raw
   ``Response`` object instead of parsed JSON.  This breaks
   ``get_user("me")``, username lookups, and ``get_thread()``.
   Fix: monkey-patch to use ``startswith`` check.
"""

from __future__ import annotations

import asyncio
import logging
import ssl

import websockets
from mattermostdriver.websocket import Websocket

log = logging.getLogger("mattermostdriver.websocket")


# ---------------------------------------------------------------------------
# Fix 1: WebSocket SSL context (Python 3.14)
# ---------------------------------------------------------------------------


class _FixedWebsocket(Websocket):
    """Fix mattermostdriver bug: ssl.Purpose.CLIENT_AUTH produces a server-side
    TLS context, which websockets rejects for outgoing connections.
    SERVER_AUTH is correct for a TLS client connecting to a server."""

    async def connect(self, event_handler):
        context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
        if not self.options['verify']:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

        scheme = 'wss://'
        if self.options['scheme'] != 'https':
            scheme = 'ws://'
            context = None

        url = '{scheme:s}{url:s}:{port:s}{basepath:s}/websocket'.format(
            scheme=scheme,
            url=self.options['url'],
            port=str(self.options['port']),
            basepath=self.options['basepath'],
        )

        self._alive = True
        while True:
            try:
                kw_args = self.options['websocket_kw_args'] or {}
                websocket = await websockets.connect(url, ssl=context, **kw_args)
                await self._authenticate_websocket(websocket, event_handler)
                log.info("WebSocket connected to %s", url)
                while self._alive:
                    try:
                        await self._start_loop(websocket, event_handler)
                    except websockets.ConnectionClosedError:
                        break
                if (not self.options['keepalive']) or (not self._alive):
                    break
            except Exception as e:
                log.warning("Failed to establish websocket connection: %s", e)
                await asyncio.sleep(self.options['keepalive_delay'])


# ---------------------------------------------------------------------------
# Fix 2: Content-Type check in Client.get() (returns raw Response otherwise)
# ---------------------------------------------------------------------------

from mattermostdriver.client import Client as _Client  # noqa: E402

_original_get = _Client.get


def _patched_get(self, endpoint, options=None, params=None):
    """Patched Client.get that accepts 'application/json; charset=...' etc."""
    response = self.make_request('get', endpoint, options=options, params=params)

    content_type = response.headers.get('Content-Type', '')
    if not content_type.startswith('application/json'):
        log.debug('Response is not application/json, returning raw response')
        return response

    try:
        return response.json()
    except ValueError:
        log.debug('Could not convert response to json, returning raw response')
        return response


_Client.get = _patched_get
