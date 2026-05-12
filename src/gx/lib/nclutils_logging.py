"""Bridge nclutils stdlib logger to pp.debug.

nclutils emits internal diagnostics through `logging.getLogger("nclutils")` rather than
through pp, so they are silent by default. Forward those records to pp.debug() so they
surface under the same -v flag that controls the rest of gx's debug output.
"""

from __future__ import annotations

import logging

from nclutils import pp
from nclutils.pp.constants import Verbosity


class _NclutilsToPp(logging.Handler):
    """Forward nclutils log records to pp at the matching severity.

    Routes DEBUG to ``pp.debug`` (verbosity-gated) and WARNING+ to ``pp.warning`` /
    ``pp.error`` so library-level warnings still surface at default verbosity.
    """

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if record.levelno >= logging.ERROR:
            pp.error(message)
        elif record.levelno >= logging.WARNING:
            pp.warning(message)
        else:
            pp.debug(message)


def configure_nclutils_logging() -> None:
    """Attach the pp-forwarding handler and set the nclutils log level to match verbosity.

    Call after :func:`pp.configure` so the logger level tracks ``pp``'s verbosity.
    Below DEBUG verbosity the level stays at WARNING, which lets nclutils skip the
    formatting work behind its ``logger.isEnabledFor(DEBUG)`` guards.
    """
    logger = logging.getLogger("nclutils")
    if not any(isinstance(h, _NclutilsToPp) for h in logger.handlers):
        logger.addHandler(_NclutilsToPp())
        logger.propagate = False

    verbosity = pp.get_default().verbosity
    logger.setLevel(logging.DEBUG if verbosity >= Verbosity.DEBUG else logging.WARNING)
